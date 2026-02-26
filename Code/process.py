import asyncio
import glob
import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import polars as pl
from dateutil.relativedelta import relativedelta

from helper import build_session, fetch_window_adaptive
from processCaseInBrim import getCountOfCase, processDataRawToRealData
from saveNewExcel import saveNewExcel
from util import update_message_status_box

file_name = "output.xlsx"


def _parse_yyyymmdd(s):
    return datetime.strptime(s, "%Y%m%d")


def split_into_bimonth_ranges(from_yyyymmdd, to_yyyymmdd):
    start = _parse_yyyymmdd(from_yyyymmdd)
    end = _parse_yyyymmdd(to_yyyymmdd)
    ranges = []
    cur = start
    while cur <= end:
        nxt = (cur + relativedelta(months=+2)) - relativedelta(days=1)
        if nxt > end:
            nxt = end
        ranges.append((cur.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        cur = nxt + relativedelta(days=1)
    return ranges


def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ["data", "items", "results", "rows", "content", "list", "records"]:
            v = payload.get(k)
            if isinstance(v, list):
                return v
        return [payload]
    return []


def _to_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _bounded_int(value, default, min_value=None, max_value=None):
    try:
        out = int(value)
    except Exception:
        out = int(default)
    if min_value is not None:
        out = max(int(min_value), out)
    if max_value is not None:
        out = min(int(max_value), out)
    return out


def _load_runtime_config(cfg):
    runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
    out = {
        "use_async_pipeline": _to_bool(runtime.get("use_async_pipeline", True), True),
        "start_concurrency": _bounded_int(runtime.get("start_concurrency", 16), 16, 1, 64),
        "min_concurrency": _bounded_int(runtime.get("min_concurrency", 8), 8, 1, 64),
        "max_concurrency": _bounded_int(runtime.get("max_concurrency", 24), 24, 1, 64),
        "start_chunk_size": _bounded_int(runtime.get("start_chunk_size", 40), 40, 1, 2000),
        "min_chunk_size": _bounded_int(runtime.get("min_chunk_size", 20), 20, 1, 2000),
        "max_chunk_size": _bounded_int(runtime.get("max_chunk_size", 60), 60, 1, 2000),
        "tune_interval_sec": _bounded_int(runtime.get("tune_interval_sec", 10), 10, 2, 120),
        "flush_rows": _bounded_int(runtime.get("flush_rows", 3000), 3000, 100, 500000),
        "flush_interval_sec": float(runtime.get("flush_interval_sec", 1)),
    }
    if out["min_concurrency"] > out["max_concurrency"]:
        out["min_concurrency"], out["max_concurrency"] = out["max_concurrency"], out["min_concurrency"]
    if out["start_concurrency"] < out["min_concurrency"]:
        out["start_concurrency"] = out["min_concurrency"]
    if out["start_concurrency"] > out["max_concurrency"]:
        out["start_concurrency"] = out["max_concurrency"]

    if out["min_chunk_size"] > out["max_chunk_size"]:
        out["min_chunk_size"], out["max_chunk_size"] = out["max_chunk_size"], out["min_chunk_size"]
    if out["start_chunk_size"] < out["min_chunk_size"]:
        out["start_chunk_size"] = out["min_chunk_size"]
    if out["start_chunk_size"] > out["max_chunk_size"]:
        out["start_chunk_size"] = out["max_chunk_size"]
    if out["flush_interval_sec"] <= 0:
        out["flush_interval_sec"] = 1.0
    return out


def _prepare_run_context(self):
    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    API_HOME_TEST = cfg.get("envData", {}).get("API_HOME_TEST")
    API_HOME_STG = cfg.get("envData", {}).get("API_HOME_STG")
    URL_TEST = cfg.get("envData", {}).get("URL_DATA")
    URL_STG = cfg.get("envData", {}).get("URL_DATA_STG")
    if not all([API_HOME_TEST, API_HOME_STG, URL_TEST, URL_STG]):
        update_message_status_box(self, "Config envData is missing URL/host.")
        return None

    env = self.envCombobox.currentText().strip()
    base_url = (API_HOME_STG + URL_STG) if env == "STG" else (API_HOME_TEST + URL_TEST)

    cfg = updateConfigSourceCode(self, "config.json")
    if not cfg:
        return None

    headers = cfg.get("headers", {}) or {}
    body = cfg.get("body", {}) or {}
    if not headers.get("Content-Type"):
        headers["Content-Type"] = "application/json"
    if "Accept" not in headers:
        headers["Accept"] = "application/json"
    try:
        from secret_provider import apply_secrets_to_headers

        headers = apply_secrets_to_headers(cfg, env, headers)
    except Exception:
        pass

    from_date = body.get("fm_inv_issue_date")
    to_date = body.get("to_inv_issue_date")
    if not (from_date and to_date):
        update_message_status_box(self, "Please input from/to date (YYYYMMDD).")
        return None

    ofc_cd = body.get("ofc_cd")
    cust_cd_list = update_config_cust_cd(self, env) or []
    customers_all = [c.get("cust_cd") for c in cust_cd_list if c.get("cust_cd")]
    if not customers_all:
        update_message_status_box(self, "No customer found for selected office/env.")
        return None

    ranges = split_into_bimonth_ranges(from_date, to_date)
    source_codes = [s.get("source_code") for s in body.get("source_code", []) if s.get("source_code")] or [
        "MRI",
        "FRT",
        "MDM",
        "MDT",
        "MRD",
    ]
    office = self.officeCode.currentText()

    return {
        "env": env,
        "base_url": base_url,
        "headers": headers,
        "body": body,
        "from_date": from_date,
        "to_date": to_date,
        "ofc_cd": ofc_cd,
        "customers_all": customers_all,
        "ranges": ranges,
        "source_codes": source_codes,
        "office": office,
    }


def _merge_parts_fast(self, parquet_files, csv_files):
    if parquet_files:
        try:
            with pl.StringCache():
                lf = pl.scan_parquet(parquet_files)
                df_polars = lf.collect(streaming=True)
                return df_polars.to_pandas(use_pyarrow_extension_array=True)
        except Exception:
            pass
        try:
            return pd.concat([pd.read_parquet(p) for p in parquet_files], ignore_index=True, copy=False)
        except Exception as e:
            update_message_status_box(self, f"Fallback read_parquet failed: {e}")

    if csv_files:
        try:
            with pl.StringCache():
                lf = pl.scan_csv(csv_files, has_header=True, infer_schema_length=2000)
                df_polars = lf.collect()
                return df_polars.to_pandas(use_pyarrow_extension_array=True)
        except Exception:
            pass

        def _read_csv(path):
            try:
                return pd.read_csv(path, engine="pyarrow")
            except Exception:
                return pd.read_csv(path)

        if len(csv_files) >= 80:
            merged_path = os.path.join(os.path.dirname(csv_files[0]), "__merged_tmp.csv")
            try:
                with open(merged_path, "w", encoding="utf-8", newline="") as w:
                    for i, p in enumerate(csv_files):
                        with open(p, "r", encoding="utf-8", newline="") as r:
                            if i == 0:
                                w.write(r.read())
                            else:
                                r.readline()
                                w.writelines(r.readlines())
                df = _read_csv(merged_path)
                try:
                    os.remove(merged_path)
                except Exception:
                    pass
                return df
            except Exception as e:
                update_message_status_box(self, f"Concat-text failed, fallback concat: {e}")

        return pd.concat((_read_csv(p) for p in csv_files), ignore_index=True, copy=False)

    return None


def _finalize_and_save(self, df_all, ofc_cd, env, optione1, start_time):
    try:
        data_after_process = processDataRawToRealData(df_all)
        update_message_status_box(self, "Done processing data")
    except Exception as ex_proc:
        update_message_status_box(self, f"Process data error: {ex_proc}")
        end_time = time.time()
        count_time(self, end_time, start_time)
        return

    skip_excel_export = bool(getattr(self, "skip_excel_export", False))
    web_case_files = {}

    if skip_excel_export:
        web_output_dir = getattr(self, "web_output_dir", None)
        if not web_output_dir:
            web_output_dir = os.path.join("artifacts", "case_cache")
        os.makedirs(web_output_dir, exist_ok=True)

        for idx, (sheet_name, df_case) in enumerate(data_after_process.items(), 1):
            safe_sheet = re.sub(r"[^A-Za-z0-9._-]+", "_", str(sheet_name)).strip("_") or f"sheet_{idx}"
            parquet_path = os.path.join(web_output_dir, f"{safe_sheet}.parquet")
            try:
                df_case.to_parquet(parquet_path, index=False, engine="pyarrow", compression="zstd")
                web_case_files[sheet_name] = parquet_path
            except Exception:
                csv_path = os.path.join(web_output_dir, f"{safe_sheet}.csv")
                df_case.to_csv(csv_path, index=False)
                web_case_files[sheet_name] = csv_path

        setattr(self, "web_case_files", web_case_files)
        update_message_status_box(self, f"Done cache case files ({len(web_case_files)} sheets)")
    else:
        if optione1:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name2 = f"output_{ofc_cd}_{env}_{ts}.xlsx"
            saveNewExcel(self, data_after_process, file_name2, 1)
            update_message_status_box(self, "Done Save And Replace Excel")
        else:
            saveNewExcel(self, data_after_process, file_name, 0)
            update_message_status_box(self, "Done Save Excel File")

    setDataCount(self)
    end_time = time.time()
    count_time(self, end_time, start_time)
    return data_after_process


def _run_pipeline_threaded_legacy(self, optione1, start_time, runtime_cfg=None):
    update_message_status_box(self, "Calling API by 2-month windows + customer batches (thread pool)...")

    try:
        ctx = _prepare_run_context(self)
        if not ctx:
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

        env = ctx["env"]
        base_url = ctx["base_url"]
        headers = ctx["headers"]
        body = ctx["body"]
        ofc_cd = ctx["ofc_cd"]
        customers_all = ctx["customers_all"]
        ranges = ctx["ranges"]
        source_codes = ctx["source_codes"]
        office = ctx["office"]

        update_message_status_box(self, f"Total windows: {len(ranges)}; customers: {len(customers_all)}")

        max_workers = 4
        batch_size = 10
        if runtime_cfg:
            max_workers = _bounded_int(runtime_cfg.get("start_concurrency", 4), 4, 1, 32)
            batch_size = _bounded_int(runtime_cfg.get("start_chunk_size", 10), 10, 1, 500)

        tmp_dir = "tmp"
        os.makedirs(tmp_dir, exist_ok=True)

        tasks = []
        batch_no = 0
        for start_idx in range(0, len(customers_all), batch_size):
            batch_no += 1
            batch_customers = customers_all[start_idx : start_idx + batch_size]
            for range_no, (fm, to) in enumerate(ranges, 1):
                tasks.append((batch_no, range_no, batch_customers, (fm, to)))

        update_message_status_box(self, f"Submitting {len(tasks)} tasks to thread pool ...")

        def worker(task):
            bno, rno, batch_customers, (fm, to) = task
            session = build_session()
            headers_local = dict(headers)
            body_local = dict(body)

            rows = fetch_window_adaptive(
                self,
                session,
                base_url,
                headers_local,
                body_local,
                office=office,
                customers=batch_customers,
                fm=fm,
                to=to,
                source_codes=source_codes,
            )
            if rows:
                df_tmp = pd.json_normalize(rows)
                try:
                    pq_path = os.path.join(tmp_dir, f"{office}_b{bno}_r{rno}_{uuid.uuid4().hex[:8]}.parquet")
                    df_tmp.to_parquet(pq_path, index=False, engine="pyarrow", compression="zstd")
                    return f"[OK] b{bno} r{rno} (+{len(df_tmp)}) -> {os.path.basename(pq_path)}"
                except Exception:
                    part_path = os.path.join(tmp_dir, f"{office}_b{bno}_r{rno}_{uuid.uuid4().hex[:8]}.csv")
                    df_tmp.to_csv(part_path, index=False)
                    return f"[OK/CSV] b{bno} r{rno} (+{len(df_tmp)}) -> {os.path.basename(part_path)}"
            return f"[NO DATA] b{bno} r{rno}"

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(worker, t) for t in tasks]
            for fut in as_completed(futures):
                try:
                    msg = fut.result()
                    update_message_status_box(self, msg)
                except Exception as e:
                    update_message_status_box(self, f"[ERR] {e}")

        parquet_files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r*.parquet")))
        csv_files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r*.csv")))
        update_message_status_box(self, f"Merging parts in {tmp_dir} ...")
        df_all = _merge_parts_fast(self, parquet_files, csv_files)
        if df_all is None or df_all.empty:
            update_message_status_box(self, "No data overall after merge.")
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

        _finalize_and_save(self, df_all, ofc_cd, env, optione1, start_time)
    except Exception as e:
        update_message_status_box(self, f"Error (threaded): {e}")
    finally:
        clear_temp_file(self)


async def run_pipeline_async(self, optione1, start_time, runtime_cfg):
    from adaptive_throttle import AdaptiveThrottle, ConcurrencyController
    from helper_async import build_async_client, fetch_window_adaptive_async

    update_message_status_box(self, "Calling API by 2-month windows + customer batches (async)...")
    try:
        ctx = _prepare_run_context(self)
        if not ctx:
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

        env = ctx["env"]
        base_url = ctx["base_url"]
        headers = ctx["headers"]
        body = ctx["body"]
        ofc_cd = ctx["ofc_cd"]
        customers_all = ctx["customers_all"]
        ranges = ctx["ranges"]
        source_codes = ctx["source_codes"]
        office = ctx["office"]

        update_message_status_box(self, f"Total windows: {len(ranges)}; customers: {len(customers_all)}")

        tmp_dir = "tmp"
        os.makedirs(tmp_dir, exist_ok=True)

        throttle = AdaptiveThrottle(
            window_sec=runtime_cfg["tune_interval_sec"],
            min_concurrency=runtime_cfg["min_concurrency"],
            max_concurrency=runtime_cfg["max_concurrency"],
            min_chunk_size=runtime_cfg["min_chunk_size"],
            max_chunk_size=runtime_cfg["max_chunk_size"],
        )
        controller = ConcurrencyController(
            initial_limit=runtime_cfg["start_concurrency"],
            min_limit=runtime_cfg["min_concurrency"],
            max_limit=runtime_cfg["max_concurrency"],
            initial_chunk_size=runtime_cfg["start_chunk_size"],
            min_chunk_size=runtime_cfg["min_chunk_size"],
            max_chunk_size=runtime_cfg["max_chunk_size"],
        )

        task_queue = asyncio.Queue(maxsize=max(32, controller.max_workers * 3))
        rows_queue = asyncio.Queue(maxsize=max(16, controller.max_workers * 2))

        progress = {
            "tasks_done": 0,
            "tasks_total": 0,
            "units_done": 0,
            "units_total": len(customers_all) * len(ranges),
            "rows_received": 0,
            "parts_written": 0,
        }

        def _flush_rows_to_part(rows, part_idx):
            if not rows:
                return "skip"
            df_tmp = pd.json_normalize(rows)
            try:
                pq_path = os.path.join(tmp_dir, f"{office}_part_{part_idx:06d}.parquet")
                df_tmp.to_parquet(pq_path, index=False, engine="pyarrow", compression="zstd")
                return f"[WRITE] part={part_idx} rows={len(df_tmp)} parquet"
            except Exception:
                csv_path = os.path.join(tmp_dir, f"{office}_part_{part_idx:06d}.csv")
                df_tmp.to_csv(csv_path, index=False)
                return f"[WRITE] part={part_idx} rows={len(df_tmp)} csv"

        async def dispatcher():
            idx = 0
            batch_no = 0
            while idx < len(customers_all):
                chunk_size = controller.get_chunk_size()
                batch_customers = customers_all[idx : idx + chunk_size]
                idx += len(batch_customers)
                batch_no += 1
                for range_no, (fm, to) in enumerate(ranges, 1):
                    await task_queue.put((batch_no, range_no, batch_customers, fm, to))
                    progress["tasks_total"] += 1

            for _ in range(controller.max_workers):
                await task_queue.put(None)

        async def worker(client):
            while True:
                task = await task_queue.get()
                if task is None:
                    task_queue.task_done()
                    return

                bno, rno, batch_customers, fm, to = task
                await controller.acquire()
                try:
                    rows = await fetch_window_adaptive_async(
                        self,
                        client,
                        base_url,
                        dict(headers),
                        dict(body),
                        office=office,
                        customers=batch_customers,
                        fm=fm,
                        to=to,
                        source_codes=source_codes,
                        throttle=throttle,
                    )
                    if rows:
                        await rows_queue.put((bno, rno, rows))
                        update_message_status_box(self, f"[OK] b{bno} r{rno} (+{len(rows)})")
                    else:
                        update_message_status_box(self, f"[NO DATA] b{bno} r{rno}")
                except Exception as e:
                    update_message_status_box(self, f"[ERR] b{bno} r{rno}: {e}")
                finally:
                    progress["tasks_done"] += 1
                    progress["units_done"] += len(batch_customers)
                    await controller.release()
                    task_queue.task_done()

        async def writer():
            buffer = []
            part_idx = 0
            last_flush = time.monotonic()

            while True:
                timeout = max(0.05, runtime_cfg["flush_interval_sec"] - (time.monotonic() - last_flush))
                timed_out = False
                try:
                    item = await asyncio.wait_for(rows_queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    item = None
                    timed_out = True

                if timed_out:
                    if buffer:
                        part_idx += 1
                        msg = await asyncio.to_thread(_flush_rows_to_part, list(buffer), part_idx)
                        buffer.clear()
                        last_flush = time.monotonic()
                        progress["parts_written"] = part_idx
                        if msg != "skip":
                            update_message_status_box(self, msg)
                    continue

                if item == "__STOP__":
                    rows_queue.task_done()
                    break

                bno, rno, rows = item
                buffer.extend(rows)
                progress["rows_received"] += len(rows)
                rows_queue.task_done()
                if len(buffer) >= runtime_cfg["flush_rows"]:
                    part_idx += 1
                    msg = await asyncio.to_thread(_flush_rows_to_part, list(buffer), part_idx)
                    buffer.clear()
                    last_flush = time.monotonic()
                    progress["parts_written"] = part_idx
                    if msg != "skip":
                        update_message_status_box(self, msg)

            if buffer:
                part_idx += 1
                msg = await asyncio.to_thread(_flush_rows_to_part, list(buffer), part_idx)
                progress["parts_written"] = part_idx
                if msg != "skip":
                    update_message_status_box(self, msg)

        stop_tuner = asyncio.Event()

        async def tuner():
            while not stop_tuner.is_set():
                await asyncio.sleep(runtime_cfg["tune_interval_sec"])
                stats = throttle.snapshot()
                cur_c = controller.get_limit()
                cur_b = controller.get_chunk_size()
                new_c, new_b, action = throttle.suggest(cur_c, cur_b)
                await controller.set_limit(new_c)
                controller.set_chunk_size(new_b)
                update_message_status_box(
                    self,
                    "[TUNE] action={} c={}->{} chunk={}->{} p95={:.1f}ms err={:.2%} done={}/{} units={}/{}".format(
                        action,
                        cur_c,
                        new_c,
                        cur_b,
                        new_b,
                        stats["p95_latency_ms"],
                        stats["error_rate"],
                        progress["tasks_done"],
                        max(progress["tasks_total"], 1),
                        progress["units_done"],
                        progress["units_total"],
                    ),
                )

        async with build_async_client() as client:
            writer_task = asyncio.create_task(writer())
            tuner_task = asyncio.create_task(tuner())
            dispatcher_task = asyncio.create_task(dispatcher())
            workers = [asyncio.create_task(worker(client)) for _ in range(controller.max_workers)]

            await dispatcher_task
            await task_queue.join()
            await asyncio.gather(*workers)

            await rows_queue.put("__STOP__")
            await rows_queue.join()
            await writer_task

            stop_tuner.set()
            await tuner_task

        update_message_status_box(
            self,
            f"Fetch complete. tasks={progress['tasks_done']} rows={progress['rows_received']} parts={progress['parts_written']}",
        )

        parquet_files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_part_*.parquet")))
        csv_files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_part_*.csv")))
        update_message_status_box(self, f"Merging parts in {tmp_dir} ...")
        df_all = _merge_parts_fast(self, parquet_files, csv_files)
        if df_all is None or df_all.empty:
            update_message_status_box(self, "No data overall after merge.")
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

        _finalize_and_save(self, df_all, ofc_cd, env, optione1, start_time)
    except Exception as e:
        update_message_status_box(self, f"Error (async): {e}")
        end_time = time.time()
        count_time(self, end_time, start_time)
    finally:
        clear_temp_file(self)


def onFuncButtonClick(self, MainWindown, optione1):
    start_time = time.time()
    setDefaultDataCount(self)
    update_message_status_box(self, "Start processing ...")

    cfg = {}
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        update_message_status_box(self, f"Cannot read config.json: {e}")
        end_time = time.time()
        count_time(self, end_time, start_time)
        return

    runtime_cfg = _load_runtime_config(cfg)
    if runtime_cfg["use_async_pipeline"]:
        try:
            import httpx  # noqa: F401
            from adaptive_throttle import AdaptiveThrottle  # noqa: F401
            from helper_async import fetch_window_adaptive_async  # noqa: F401
        except Exception as e:
            update_message_status_box(self, f"Async deps missing. Fallback legacy mode: {e}")
            _run_pipeline_threaded_legacy(self, optione1, start_time, runtime_cfg=runtime_cfg)
            return

        try:
            asyncio.run(run_pipeline_async(self, optione1, start_time, runtime_cfg))
            return
        except Exception as e:
            update_message_status_box(self, f"Async pipeline failed: {e}")
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

    _run_pipeline_threaded_legacy(self, optione1, start_time, runtime_cfg=runtime_cfg)


def saveExcel(self, json_data):
    data_after_process = processData(self, json_data)
    saveNewExcel(self, data_after_process, file_name, 0)
    setDataCount(self)
    update_message_status_box(self, "Done Save Excel File")


def saveAndReplaceExcel(self, json_data):
    data_after_process = processData(self, json_data)
    saveNewExcel(self, data_after_process, file_name, 1)
    setDataCount(self)
    update_message_status_box(self, "Done Save And Replace Excel")


def processData(self, json_data):
    excelFilePatch = saveDataFromJsonToExcel(self, json_data)
    data_raw = readFileExcel(excelFilePatch)
    data_after_process = processDataRawToRealData(data_raw)
    update_message_status_box(self, "Done processing data")
    return data_after_process


def saveDataFromJsonToExcel(self, json_data):
    records = extract_records(json_data)
    if not records:
        update_message_status_box(self, "Warning: no records to write.")
    data = pd.json_normalize(records)
    excel_file_path = "dataFromJsonToExcel.xlsx"
    data.to_excel(excel_file_path, index=False, engine="openpyxl")
    update_message_status_box(self, f"Excel file has been created: {excel_file_path}")
    return excel_file_path


def readFileExcel(excelFilePatch):
    excel_data = pd.read_excel(excelFilePatch)
    return excel_data


def setDataCount(self):
    result_count_of_case = getCountOfCase()
    self.single_case_count.setText(str(result_count_of_case.get("single_case", 0)))
    self.split_case_count.setText(str(result_count_of_case.get("split_case", 0)))
    self.split_manual_case_count.setText(str(result_count_of_case.get("split_case_manual", 0)))
    self.group_case_count.setText(str(result_count_of_case.get("group_case", 0)))
    self.supplement_case_count.setText(str(result_count_of_case.get("supplement_case", 0)))


def setDefaultDataCount(self):
    self.single_case_count.setText("0")
    self.split_case_count.setText("0")
    self.split_manual_case_count.setText("0")
    self.group_case_count.setText("0")
    self.supplement_case_count.setText("0")


def updateConfigSourceCode(self, config_file="config.json"):
    try:
        office = self.officeCode.currentText()
        from_date = self.fromDate.text().strip()
        to_date = self.toDtae.text().strip()
        env = self.envCombobox.currentText().lower().strip()
        with open("config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        with open(f"ofc_cd/{env}/" + office + ".txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        cust_codes = [line.strip() for line in lines if line.strip()]
        cust_cd_list = [{"cust_cd": code} for code in cust_codes]

        new_source_codes = []
        if self.MRI.isChecked():
            new_source_codes.append({"source_code": "MRI"})
        if self.FRT.isChecked():
            new_source_codes.append({"source_code": "FRT"})
        if self.DMT.isChecked():
            new_source_codes.append({"source_code": "MDM"})
            new_source_codes.append({"source_code": "MDT"})
        if self.TBP.isChecked():
            new_source_codes.append({"source_code": "MRD"})

        config_data["body"]["ofc_cd"] = office
        config_data["body"]["fm_inv_issue_date"] = from_date
        config_data["body"]["to_inv_issue_date"] = to_date
        config_data["body"]["source_code"] = new_source_codes
        config_data["body"]["cust_cd"] = cust_cd_list

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        return config_data

    except Exception as e:
        update_message_status_box(self, f"Error updating config: {str(e)}")
        return None


def update_config_cust_cd(self, config_file="config.json"):
    try:
        office = self.officeCode.currentText()
        env = self.envCombobox.currentText().lower().strip()
        with open(f"ofc_cd/{env}/" + office + ".txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        cust_codes = [line.strip() for line in lines if line.strip()]
        cust_cd_list = [{"cust_cd": code} for code in cust_codes]
        return cust_cd_list
    except Exception as e:
        print("Error updating config cust_cd:", str(e))
        return None


def count_time(self, end_time, start_time):
    elapsed = end_time - start_time
    mins, secs = divmod(elapsed, 60)
    update_message_status_box(self, f"Done all. Total time: {int(mins)} min {secs:.1f} sec.")


def clear_temp_file(self, tmp_dir="tmp"):
    start = time.time()

    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
        update_message_status_box(self, "tmp folder created (was missing).")
        return

    tmp_old = f"{tmp_dir}__delete_me"
    try:
        if os.path.exists(tmp_old):
            shutil.rmtree(tmp_old, ignore_errors=True)
        os.rename(tmp_dir, tmp_old)
    except Exception as e:
        update_message_status_box(self, f"Rename tmp failed: {e}")
        tmp_old = tmp_dir

    def _delete_bg(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    threading.Thread(target=_delete_bg, args=(tmp_old,), daemon=True).start()
    os.makedirs(tmp_dir, exist_ok=True)

    elapsed = time.time() - start
    update_message_status_box(self, f"Cleaned up tmp folder in {elapsed:.2f}s (async delete).")
