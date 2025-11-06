import pandas as pd
from processCaseInBrim import *
from saveNewExcel import *
from util import *
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil
import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import shutil
file_name = 'output.xlsx'
import time
import os, shutil, time, threading
import polars as pl
from helper import build_session, fetch_window_adaptive
# ===================== helpers =====================

def _parse_yyyymmdd(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d")

def split_into_bimonth_ranges(from_yyyymmdd: str, to_yyyymmdd: str):
    start = _parse_yyyymmdd(from_yyyymmdd)
    end   = _parse_yyyymmdd(to_yyyymmdd)
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
    """
    Chuẩn hoá JSON trả về về list[dict].
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
            # tìm danh sách phổ biến trong payload
        for k in ['data', 'items', 'results', 'rows', 'content', 'list', 'records']:
            v = payload.get(k)
            if isinstance(v, list):
                return v
        return [payload]
    return []

# ===================== main flow =====================

def onFuncButtonClick(self, MainWindown, optione1):
    """
    Cải tiến:
    - Đa luồng (ThreadPoolExecutor) theo task batch×range
    - Batch theo customer (BATCH_SIZE)
    - helper.fetch_window_adaptive: fallback range → source_code → customer
    - Mỗi thread chỉ ghi CSV tạm đặt tên duy nhất; cuối cùng merge → Excel
    """
    start_time = time.time()
    update_message_status_box(self, "⏳ Start processing ...")
    update_message_status_box(self, "Calling API by 2-month windows + customer batches (multithread)...")
    response = None
    try:
        # read config
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)

        API_HOME_TEST = cfg["envData"].get("API_HOME_TEST")
        API_HOME_STG  = cfg["envData"].get("API_HOME_STG")
        URL_TEST      = cfg["envData"].get("URL_DATA")
        URL_STG       = cfg["envData"].get("URL_DATA_STG")
        if not all([API_HOME_TEST, API_HOME_STG, URL_TEST, URL_STG]):
            update_message_status_box(self, "Config envData thiếu URL/host.")
            return

        env = self.envCombobox.currentText().strip()
        base_url = (API_HOME_STG + URL_STG) if env == "STG" else (API_HOME_TEST + URL_TEST)

        # update body theo UI
        cfg = updateConfigSourceCode(self, "config.json")
        if not cfg:
            return

        headers = cfg.get("headers", {}) or {}
        body    = cfg.get("body", {}) or {}
        if not headers.get("Content-Type"):
            headers["Content-Type"] = "application/json"
        if "Accept" not in headers:
            headers["Accept"] = "application/json"

        from_date = body.get("fm_inv_issue_date")
        to_date   = body.get("to_inv_issue_date")
        if not (from_date and to_date):
            update_message_status_box(self, "Vui lòng nhập đủ from/to date (YYYYMMDD).")
            end_time = time.time()
            count_time(self, end_time, start_time)
            return
        ofc_cd = body.get("ofc_cd")
        # Lấy danh sách customer theo office
        cust_cd_list = update_config_cust_cd(self, env) or []
        customers_all = [c.get("cust_cd") for c in cust_cd_list if c.get("cust_cd")]
        if not customers_all:
            update_message_status_box(self, "Không có customer nào để xử lý (file office .txt rỗng?).")
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

        # Ranges theo 2 tháng
        ranges = split_into_bimonth_ranges(from_date, to_date)
        update_message_status_box(self, f"Total windows: {len(ranges)}; customers: {len(customers_all)}")

        # Tham số điều chỉnh
        MAX_WORKERS = 4  # thử 3–5 cho 1 office
        BATCH_SIZE  = 10  # có thể nâng 15–20 nếu ổn
        source_codes = [s.get("source_code") for s in body.get("source_code", []) if s.get("source_code")] \
                       or ["MRI", "FRT", "MDM", "MDT", "MRD"]

        # folder tạm
        tmp_dir = "tmp"
        os.makedirs(tmp_dir, exist_ok=True)

        office = self.officeCode.currentText()

        # Chuẩn bị danh sách task: [(batch_no, range_no, batch_customers, (fm,to))]
        tasks = []
        batch_no = 0
        for start_idx in range(0, len(customers_all), BATCH_SIZE):
            batch_no += 1
            batch_customers = customers_all[start_idx:start_idx + BATCH_SIZE]
            for range_no, (fm, to) in enumerate(ranges, 1):
                tasks.append((batch_no, range_no, batch_customers, (fm, to)))

        update_message_status_box(self, f"Submitting {len(tasks)} tasks to thread pool ...")

        # Worker: mỗi task mở Session riêng, headers/body cục bộ, gọi helper, ghi CSV tạm


        def worker(task):
            bno, rno, batch_customers, (fm, to) = task
            session = build_session()                 # Session riêng per-thread
            headers_local = dict(headers)             # headers cục bộ
            body_local    = dict(body)                # body cục bộ

            rows = fetch_window_adaptive(
                self, session, base_url, headers_local, body_local,
                office=office,
                customers=batch_customers,
                fm=fm, to=to,
                source_codes=source_codes
            )
            if rows:
                df_tmp = pd.json_normalize(rows)
                
                # Ưu tiên ghi Parquet (nhanh/nhẹ), fallback CSV nếu thiếu dependency
                try:
                    pq_path = os.path.join(tmp_dir, f"{office}_b{bno}_r{rno}_{uuid.uuid4().hex[:8]}.parquet")
                    df_tmp.to_parquet(pq_path, index=False, engine="pyarrow", compression="zstd")
                    return f"[OK] b{bno} r{rno} (+{len(df_tmp)}) -> {os.path.basename(pq_path)}"
                except Exception:
                    part_path = os.path.join(tmp_dir, f"{office}_b{bno}_r{rno}_{uuid.uuid4().hex[:8]}.csv")
                    df_tmp.to_csv(part_path, index=False)
                    return f"[OK] b{bno} r{rno} (+{len(df_tmp)}) -> {os.path.basename(part_path)}"
                except Exception:
                    df_tmp.to_csv(part_path, index=False)
                    return f"[OK/CSV] b{bno} r{rno} (+{len(df_tmp)}) -> {os.path.basename(part_path)}"
            return f"[NO DATA] b{bno} r{rno}"

        # Chạy thread pool
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(worker, t) for t in tasks]
            for fut in as_completed(futures):
                try:
                    msg = fut.result()
                    update_message_status_box(self, msg)
                except Exception as e:
                    update_message_status_box(self, f"[ERR] {e}")
                    clear_temp_file(self)
                    

        
        # === Merge parts nhanh & tiết kiệm RAM ===
        def _merge_parts_fast(tmp_dir, office):
            parquet_files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r*.parquet")))
            csv_files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r_*.csv"))) or sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r*.csv")))

            # Ưu tiên Parquet + Polars
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

            # CSV path
            if csv_files:
                # Thử Polars CSV
                try:

                    with pl.StringCache():
                        lf = pl.scan_csv(csv_files, has_header=True, infer_schema_length=2000)
                        df_polars = lf.collect()
                        return df_polars.to_pandas(use_pyarrow_extension_array=True)
                except Exception:
                    pass
                # pandas + pyarrow
                def _read_csv(path):
                    try:
                        return pd.read_csv(path, engine="pyarrow")
                    except Exception:
                        return pd.read_csv(path)
                # Nếu quá nhiều file nhỏ, nối text → đọc 1 lần
                if len(csv_files) >= 80:
                    merged_path = os.path.join(tmp_dir, f"{office}__merged.csv")
                    try:
                        with open(merged_path, "w", encoding="utf-8", newline="") as w:
                            for i,p in enumerate(csv_files):
                                with open(p, "r", encoding="utf-8", newline="") as r:
                                    if i == 0:
                                        w.write(r.read())
                                    else:
                                        r.readline(); w.writelines(r.readlines())
                        df = _read_csv(merged_path)
                        try: os.remove(merged_path)
                        except Exception: pass
                        return df
                    except Exception as e:
                        update_message_status_box(self, f"Concat-text failed, fallback concat: {e}")
                # Bình thường: concat generator
                return pd.concat((_read_csv(p) for p in csv_files), ignore_index=True, copy=False)

            return None

        update_message_status_box(self, f"Merging parts in {tmp_dir} ...")
        df_all = _merge_parts_fast(tmp_dir, office)
        if df_all is None or df_all.empty:
            update_message_status_box(self, "No data overall sau khi merge.")
            end_time = time.time()
            count_time(self, end_time, start_time)
            clear_temp_file(self)
            return
# Đưa về pipeline sẵn có: xuất Excel tạm rồi chạy processCaseInBrim
        
        # Phân loại case trực tiếp không ghi/đọc Excel trung gian
        try:
            data_after_process = processDataRawToRealData(df_all)
            update_message_status_box(self, "Done processing data")
        except Exception as ex_proc:
            update_message_status_box(self, f"Process data error: {ex_proc}")
            end_time = time.time(); count_time(self, end_time, start_time); clear_temp_file(self); return
# Lưu kết quả cuối
        if optione1:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name2 = f"output_{ofc_cd}_{env}_{ts}.xlsx"
            saveNewExcel(self, data_after_process, file_name2, 1)
            update_message_status_box(self, "Done Save And Replace Excel")
        else:
            saveNewExcel(self, data_after_process, file_name, 0)
            update_message_status_box(self, "Done Save Excel File")

        # Cập nhật số lượng case
        setDataCount(self) 
        end_time = time.time()
        count_time(self, end_time, start_time)
    except Exception as e:
        msg = (getattr(response, "text", None)[:500] if response is not None and hasattr(response, "text") else str(e))
        update_message_status_box(self, f"Error (chunked): {msg}")
    finally:
        clear_temp_file(self)

def saveExcel(self, json_data):
    print("save Excel option:")
    data_after_process = processData(self, json_data)
    saveNewExcel(self, data_after_process, file_name, 0)
    setDataCount(self)
    update_message_status_box(self, "Done Save Excel File")

def saveAndReplaceExcel(self, json_data):
    print("save And Replace Excel option:")
    data_after_process = processData(self, json_data)
    saveNewExcel(self, data_after_process, file_name, 1)
    setDataCount(self)
    print("Done processing")
    update_message_status_box(self, "Done Save And Replace Excel")

def processData(self, json_data):
    # covert JSON to DataFrame and save to Excel if need
    excelFilePatch = saveDataFromJsonToExcel(self, json_data)
    data_raw = readFileExcel(excelFilePatch)
    data_after_process = processDataRawToRealData(data_raw)
    print("Done processing")
    update_message_status_box(self, "Done processing data")
    return data_after_process

def saveDataFromJsonToExcel(self, json_data):
    """
    Nhận vào mọi kiểu (list/dict) -> chuẩn hoá -> DataFrame.
    Dùng json_normalize để flatten nếu có nested.
    """
    records = extract_records(json_data)
    if not records:
        update_message_status_box(self, "Warning: no records to write.")
    data = pd.json_normalize(records)
    excel_file_path = 'dataFromJsonToExcel.xlsx'
    data.to_excel(excel_file_path, index=False, engine='openpyxl')
    update_message_status_box(self, f"Excel file has been created: {excel_file_path}")
    return excel_file_path

def readFileExcel(excelFilePatch):
    excel_data = pd.read_excel(excelFilePatch)
    return excel_data

def setDataCount(self):
    result_count_of_case = getCountOfCase()
    self.single_case_count.setText(str(result_count_of_case.get('single_case', 0)))
    self.split_case_count.setText(str(result_count_of_case.get('split_case', 0)))
    self.split_manual_case_count.setText(str(result_count_of_case.get('split_case_manual', 0)))
    self.group_case_count.setText(str(result_count_of_case.get('group_case', 0)))
    self.supplement_case_count.setText(str(result_count_of_case.get('supplement_case', 0)))
    # merge_case đang chỉ print ra console
    # print(str(result_count_of_case.get('merge_case', 0)))

def updateConfigSourceCode(self ,config_file="config.json"):
    """
    Read config.json, Update 'source_code' in body base on checkbox,
    and save into file. Return config_data if success, else None.
    """
    try:
        office = self.officeCode.currentText()
        from_date = self.fromDate.text().strip()
        to_date = self.toDtae.text().strip()
        env = self.envCombobox.currentText().lower().strip()
        with open("config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        with open(f'ofc_cd/{env}/' +office+'.txt', "r", encoding="utf-8") as f:
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
        with open(f'ofc_cd/{env}/'+office+'.txt', "r", encoding="utf-8") as f:
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
    update_message_status_box(self, f"✅ Done all. Total time: {int(mins)} min {secs:.1f} sec.")
    


def clear_temp_file(self, tmp_dir="tmp"):
    start = time.time()

    # Nếu folder chưa tồn tại → tạo luôn, không làm gì thêm
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
        update_message_status_box(self, "🧹 tmp folder created (was missing).")
        return

    # Đổi tên trước khi xoá để tránh lock & không chặn tiến trình khác
    tmp_old = f"{tmp_dir}__delete_me"
    try:
        if os.path.exists(tmp_old):
            shutil.rmtree(tmp_old, ignore_errors=True)
        os.rename(tmp_dir, tmp_old)
    except Exception as e:
        update_message_status_box(self, f"⚠️ Rename tmp failed: {e}")
        tmp_old = tmp_dir  # fallback: xoá trực tiếp

    # Xoá nền để không chặn giao diện/UI
    def _delete_bg(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    threading.Thread(target=_delete_bg, args=(tmp_old,), daemon=True).start()

    # Tạo lại thư mục mới rỗng
    os.makedirs(tmp_dir, exist_ok=True)

    elapsed = time.time() - start
    update_message_status_box(self, f"🧹 Cleaned up tmp folder in {elapsed:.2f}s (async delete).")

