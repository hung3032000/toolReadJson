import glob
import json
import os
import queue
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

try:
    import duckdb
except Exception:  # pragma: no cover - optional dependency
    duckdb = None


BASE_DIR = Path(__file__).resolve().parent
CODE_DIR = BASE_DIR / "Code"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)
STATE_DB = BASE_DIR / "web_state.db"
RETENTION_DAYS = 7
MAX_LOGS_IN_MEMORY = 3000

if str(CODE_DIR) not in sys.path:
    sys.path.append(str(CODE_DIR))

import process  # noqa: E402


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _safe_sheet_name(sheet_name: str, idx: int) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "_", sheet_name.strip())
    out = out.strip("_")
    if not out:
        out = f"sheet_{idx}"
    return out


def _json_load(text: Optional[str], default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


@dataclass
class JobState:
    job_id: str
    payload: Dict
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    logs: List[str] = field(default_factory=list)
    progress: Dict = field(
        default_factory=lambda: {
            "tasks_done": 0,
            "tasks_total": 0,
            "units_done": 0,
            "units_total": 0,
            "p95_latency_ms": 0.0,
            "error_rate": 0.0,
            "rows_received": 0,
            "parts_written": 0,
        }
    )
    counts: Dict = field(
        default_factory=lambda: {
            "single_case": 0,
            "split_case": 0,
            "split_case_manual": 0,
            "group_case": 0,
            "supplement_case": 0,
        }
    )
    output_file: Optional[str] = None
    case_files: Dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_db_tuple(self):
        return (
            self.job_id,
            json.dumps(self.payload, ensure_ascii=True),
            self.status,
            float(self.created_at),
            self.started_at,
            self.finished_at,
            json.dumps(self.progress, ensure_ascii=True),
            json.dumps(self.counts, ensure_ascii=True),
            self.output_file,
            json.dumps(self.case_files, ensure_ascii=True),
            self.error,
        )


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    progress_json TEXT,
                    counts_json TEXT,
                    output_file TEXT,
                    case_files_json TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    line TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_exports (
                    export_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    finished_at REAL,
                    file_path TEXT,
                    error TEXT
                )
                """
            )
            # Lightweight migrations for existing DB.
            self._ensure_column(conn, "jobs", "case_files_json", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs(job_id, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exports_job_id ON job_exports(job_id)")
            conn.commit()

    def _ensure_column(self, conn, table_name: str, column_name: str, column_type: str):
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {r[1] for r in rows}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def upsert_job(self, job: JobState):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, payload_json, status, created_at, started_at, finished_at,
                    progress_json, counts_json, output_file, case_files_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    progress_json=excluded.progress_json,
                    counts_json=excluded.counts_json,
                    output_file=excluded.output_file,
                    case_files_json=excluded.case_files_json,
                    error=excluded.error
                """,
                job.to_db_tuple(),
            )
            conn.commit()

    def append_log(self, job_id: str, line: str, created_at: float):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO job_logs(job_id, line, created_at) VALUES (?, ?, ?)",
                (job_id, line, float(created_at)),
            )
            conn.commit()

    def load_jobs(self, limit: int = 500, max_logs_per_job: int = MAX_LOGS_IN_MEMORY) -> List[JobState]:
        out = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            for row in rows:
                logs = conn.execute(
                    """
                    SELECT line FROM job_logs
                    WHERE job_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (row["job_id"], int(max_logs_per_job)),
                ).fetchall()
                logs = [x["line"] for x in reversed(logs)]
                job = JobState(
                    job_id=row["job_id"],
                    payload=_json_load(row["payload_json"], {}),
                    status=row["status"],
                    created_at=float(row["created_at"]),
                    started_at=row["started_at"],
                    finished_at=row["finished_at"],
                    logs=logs,
                    progress=_json_load(row["progress_json"], {}),
                    counts=_json_load(row["counts_json"], {}),
                    output_file=row["output_file"],
                    case_files=_json_load(row["case_files_json"], {}),
                    error=row["error"],
                )
                out.append(job)
        return out

    def create_export(self, export_id: str, job_id: str, status: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_exports(export_id, job_id, status, created_at, finished_at, file_path, error)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (export_id, job_id, status, float(time.time())),
            )
            conn.commit()

    def update_export(
        self,
        export_id: str,
        status: str,
        file_path: Optional[str] = None,
        error: Optional[str] = None,
        finished: bool = False,
    ):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE job_exports
                SET status = ?, file_path = ?, error = ?, finished_at = ?
                WHERE export_id = ?
                """,
                (status, file_path, error, float(time.time()) if finished else None, export_id),
            )
            conn.commit()

    def get_export(self, export_id: str):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM job_exports WHERE export_id = ?", (export_id,)).fetchone()
            return dict(row) if row else None

    def get_export_for_job(self, job_id: str, export_id: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_exports WHERE job_id = ? AND export_id = ?",
                (job_id, export_id),
            ).fetchone()
            return dict(row) if row else None

    def get_latest_succeeded_export_for_job(self, job_id: str):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM job_exports
                WHERE job_id = ? AND status = 'succeeded'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def prune_terminal_jobs_before(self, cutoff_ts: float) -> List[str]:
        terminal = ("succeeded", "failed", "canceled")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT job_id FROM jobs
                WHERE created_at < ? AND status IN (?, ?, ?)
                """,
                (float(cutoff_ts), *terminal),
            ).fetchall()
            ids = [r["job_id"] for r in rows]
            if not ids:
                return []
            conn.executemany("DELETE FROM job_logs WHERE job_id = ?", [(x,) for x in ids])
            conn.executemany("DELETE FROM jobs WHERE job_id = ?", [(x,) for x in ids])
            conn.executemany("DELETE FROM job_exports WHERE job_id = ?", [(x,) for x in ids])
            conn.commit()
            return ids


class _Combo:
    def __init__(self, value):
        self._value = value

    def currentText(self):
        return self._value


class _Line:
    def __init__(self, value):
        self._value = value

    def text(self):
        return self._value


class _Check:
    def __init__(self, value=False):
        self._value = bool(value)

    def isChecked(self):
        return self._value


class _Label:
    def __init__(self, value="0"):
        self._value = str(value)

    def setText(self, value):
        self._value = str(value)

    def text(self):
        return self._value


class _StatusText:
    def __init__(self, manager, job_id):
        self.manager = manager
        self.job_id = job_id

    def append(self, msg):
        self.manager.append_log(self.job_id, str(msg))

    def toPlainText(self):
        job = self.manager.get_job(self.job_id)
        if not job:
            return ""
        return "\n".join(job.logs)


class _BridgeUI:
    def __init__(self, payload: Dict, manager, job_id: str):
        source_types = set(payload.get("source_types", []))
        cache_dir = ARTIFACTS_DIR / job_id / "cases"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.envCombobox = _Combo(payload["env"])
        self.officeCode = _Combo(payload["office_code"])
        self.fromDate = _Line(payload["from_date"])
        self.toDtae = _Line(payload["to_date"])
        self.MRI = _Check("MRI" in source_types)
        self.FRT = _Check("FRT" in source_types)
        self.DMT = _Check("DMT" in source_types)
        self.TBP = _Check("TBP" in source_types)
        self.statusText = _StatusText(manager, job_id)
        self.single_case_count = _Label("0")
        self.split_case_count = _Label("0")
        self.split_manual_case_count = _Label("0")
        self.group_case_count = _Label("0")
        self.supplement_case_count = _Label("0")
        self.skip_excel_export = True
        self.web_output_dir = str(cache_dir)
        self.web_case_files = {}


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobState] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._export_queue: "queue.Queue[Dict]" = queue.Queue()
        self._store = JobStore(STATE_DB)
        self._cache_locks: Dict[str, threading.Lock] = {}

        self._load_from_store()
        self._prune_old_jobs()

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        self._export_worker = threading.Thread(target=self._export_worker_loop, daemon=True)
        self._export_worker.start()

        self._retention = threading.Thread(target=self._retention_loop, daemon=True)
        self._retention.start()

    def _load_from_store(self):
        loaded = self._store.load_jobs(limit=1000)
        with self._lock:
            for job in loaded:
                self._jobs[job.job_id] = job

    def _retention_loop(self):
        while True:
            time.sleep(3600)
            self._prune_old_jobs()

    def _prune_old_jobs(self):
        cutoff = time.time() - (RETENTION_DAYS * 24 * 3600)
        removed = self._store.prune_terminal_jobs_before(cutoff)
        if not removed:
            return
        with self._lock:
            for job_id in removed:
                self._jobs.pop(job_id, None)
        for job_id in removed:
            cache_dir = ARTIFACTS_DIR / job_id
            if cache_dir.exists():
                try:
                    shutil.rmtree(cache_dir, ignore_errors=True)
                except Exception:
                    pass

    def submit(self, payload: Dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = JobState(job_id=job_id, payload=payload)
        with self._lock:
            self._jobs[job_id] = job
        self._store.upsert_job(job)
        self._queue.put(job_id)
        return job_id

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[JobState]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def append_log(self, job_id: str, msg: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.logs.append(line)
            if len(job.logs) > MAX_LOGS_IN_MEMORY:
                job.logs = job.logs[-MAX_LOGS_IN_MEMORY:]
            self._update_progress_from_log(job, msg)
            self._store.upsert_job(job)
        self._store.append_log(job_id, line, time.time())

    def _update_progress_from_log(self, job: JobState, msg: str):
        tune_match = re.search(r"done=(\d+)/(\d+)\s+units=(\d+)/(\d+)", msg)
        if tune_match:
            job.progress["tasks_done"] = int(tune_match.group(1))
            job.progress["tasks_total"] = int(tune_match.group(2))
            job.progress["units_done"] = int(tune_match.group(3))
            job.progress["units_total"] = int(tune_match.group(4))

        perf_match = re.search(r"p95=([0-9.]+)ms err=([0-9.]+)%", msg)
        if perf_match:
            job.progress["p95_latency_ms"] = float(perf_match.group(1))
            job.progress["error_rate"] = float(perf_match.group(2))

        fetch_match = re.search(r"tasks=(\d+)\s+rows=(\d+)\s+parts=(\d+)", msg)
        if fetch_match:
            job.progress["tasks_done"] = int(fetch_match.group(1))
            job.progress["rows_received"] = int(fetch_match.group(2))
            job.progress["parts_written"] = int(fetch_match.group(3))

    def _worker_loop(self):
        while True:
            job_id = self._queue.get()
            try:
                self._execute(job_id)
            finally:
                self._queue.task_done()

    def _export_worker_loop(self):
        while True:
            item = self._export_queue.get()
            try:
                self._execute_export(item["job_id"], item["export_id"])
            finally:
                self._export_queue.task_done()

    def create_export(self, job_id: str) -> Dict:
        job = self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != "succeeded":
            raise HTTPException(status_code=400, detail="job is not completed")

        export_id = uuid.uuid4().hex[:10]
        self._store.create_export(export_id, job_id, "pending")
        self._export_queue.put({"job_id": job_id, "export_id": export_id})
        return {"export_id": export_id, "status": "pending"}

    def get_export(self, job_id: str, export_id: str) -> Dict:
        row = self._store.get_export_for_job(job_id, export_id)
        if not row:
            raise HTTPException(status_code=404, detail="export not found")
        return row

    def _execute_export(self, job_id: str, export_id: str):
        self._store.update_export(export_id, "running", finished=False)
        try:
            out_path = self._build_export_file(job_id, export_id)
            self._store.update_export(export_id, "succeeded", file_path=out_path, finished=True)
        except Exception as exc:
            self._store.update_export(export_id, "failed", error=str(exc), finished=True)

    def _build_export_file(self, job_id: str, export_id: str) -> str:
        job = self.get_job(job_id)
        if not job:
            raise Exception("job not found")

        export_dir = ARTIFACTS_DIR / job_id / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = export_dir / f"export_{export_id}_{ts}.xlsx"

        meta = self.ensure_result_cache(job_id)
        sheet_map = [(x.get("name"), x.get("path")) for x in meta.get("sheets", [])]
        if not sheet_map:
            raise Exception("no sheet data to export")

        with pd.ExcelWriter(out_file, engine="openpyxl", mode="w") as writer:
            for sheet_name, path in sheet_map:
                if not sheet_name or not path:
                    continue
                p = Path(path)
                if not p.exists():
                    continue
                if p.suffix.lower() == ".parquet":
                    df = pd.read_parquet(p)
                else:
                    df = pd.read_csv(p)
                df.to_excel(writer, sheet_name=str(sheet_name)[:31], index=False)

        return str(out_file)

    def _execute(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "running"
            job.started_at = time.time()
            self._store.upsert_job(job)

        ui = _BridgeUI(job.payload, self, job_id)
        replace_mode = (job.payload.get("save_mode") or "replace").lower() == "replace"
        output_file = None
        case_files = {}

        try:
            before_files = set(glob.glob(str(BASE_DIR / "output*.xlsx")))
            process.onFuncButtonClick(ui, None, replace_mode)
            case_files = dict(getattr(ui, "web_case_files", {}) or {})
            if not case_files:
                after_files = set(glob.glob(str(BASE_DIR / "output*.xlsx")))
                output_file = self._detect_output_file(job.payload, before_files, after_files, replace_mode)

            counts = {
                "single_case": int(ui.single_case_count.text()),
                "split_case": int(ui.split_case_count.text()),
                "split_case_manual": int(ui.split_manual_case_count.text()),
                "group_case": int(ui.group_case_count.text()),
                "supplement_case": int(ui.supplement_case_count.text()),
            }

            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return
                job.status = "succeeded"
                job.finished_at = time.time()
                job.counts = counts
                job.output_file = output_file
                job.case_files = case_files
                self._store.upsert_job(job)

            # Build cache after success for faster result queries.
            self.ensure_result_cache(job_id)
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return
                job.status = "failed"
                job.finished_at = time.time()
                job.error = str(exc)
                job.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] [ERR] {exc}")
                self._store.upsert_job(job)
            self._store.append_log(job_id, f"[{datetime.now().strftime('%H:%M:%S')}] [ERR] {exc}", time.time())

    def _detect_output_file(self, payload, before_files, after_files, replace_mode):
        env = payload["env"]
        office = payload["office_code"]
        new_files = sorted(list(after_files - before_files), key=lambda p: os.path.getmtime(p), reverse=True)
        if replace_mode:
            pattern = str(BASE_DIR / f"output_{office}_{env}_*.xlsx")
            matched = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
            if matched:
                return matched[0]
        else:
            default_path = str(BASE_DIR / "output.xlsx")
            if os.path.exists(default_path):
                return default_path
        if new_files:
            return new_files[0]
        return None

    def _cache_meta_path(self, job_id: str) -> Path:
        return ARTIFACTS_DIR / job_id / "meta.json"

    def _cache_lock(self, job_id: str) -> threading.Lock:
        with self._lock:
            lock = self._cache_locks.get(job_id)
            if lock is None:
                lock = threading.Lock()
                self._cache_locks[job_id] = lock
            return lock

    def ensure_result_cache(self, job_id: str) -> Dict:
        job = self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        meta_path = self._cache_meta_path(job_id)
        if meta_path.exists():
            return _json_load(meta_path.read_text(encoding="utf-8"), {"sheets": []})

        lock = self._cache_lock(job_id)
        with lock:
            if meta_path.exists():
                return _json_load(meta_path.read_text(encoding="utf-8"), {"sheets": []})

            cache_dir = meta_path.parent
            cache_dir.mkdir(parents=True, exist_ok=True)

            sheets = []
            if job.case_files:
                for idx, (sheet_name, path) in enumerate(job.case_files.items(), 1):
                    if path and os.path.exists(path):
                        sheets.append({"name": sheet_name, "path": str(Path(path).resolve())})

            if not sheets:
                if not job.output_file or not os.path.exists(job.output_file):
                    raise HTTPException(status_code=400, detail="output file not ready")
                xls = pd.ExcelFile(job.output_file)
                used_files = set()
                for idx, sheet in enumerate(xls.sheet_names, 1):
                    safe = _safe_sheet_name(sheet, idx)
                    while safe in used_files:
                        safe = f"{safe}_{idx}"
                    used_files.add(safe)
                    pq_name = f"{safe}.parquet"
                    pq_path = cache_dir / pq_name
                    df = pd.read_excel(xls, sheet_name=sheet)
                    df.to_parquet(pq_path, index=False, engine="pyarrow", compression="zstd")
                    sheets.append({"name": sheet, "path": str(pq_path.resolve())})

            meta = {"created_at": _iso(time.time()), "sheets": sheets}
            meta_path.write_text(json.dumps(meta, ensure_ascii=True, indent=2), encoding="utf-8")
            return meta

    def sheet_names(self, job_id: str) -> List[str]:
        meta = self.ensure_result_cache(job_id)
        return [x["name"] for x in meta.get("sheets", [])]

    def query_results(self, job_id: str, sheet: str, page: int, page_size: int, search: str, search_field: str):
        meta = self.ensure_result_cache(job_id)
        sheet_map = {}
        for item in meta.get("sheets", []):
            sheet_name = item.get("name")
            path = item.get("path")
            if not path and item.get("parquet"):
                path = str((ARTIFACTS_DIR / job_id / item["parquet"]).resolve())
            if sheet_name and path:
                sheet_map[sheet_name] = path
        data_path = sheet_map.get(sheet)
        if not data_path:
            raise HTTPException(status_code=400, detail=f"sheet not found: {sheet}")

        data_path = Path(data_path)
        if not data_path.exists():
            raise HTTPException(status_code=500, detail="cached result file missing")

        offset = (page - 1) * page_size

        # Fast path using DuckDB.
        if duckdb is not None:
            con = duckdb.connect(database=":memory:")
            try:
                if data_path.suffix.lower() == ".parquet":
                    source_fn = "read_parquet"
                else:
                    source_fn = "read_csv_auto"
                preview = con.execute(f"SELECT * FROM {source_fn}(?) LIMIT 0", [str(data_path)]).fetchdf()
                columns = [str(c) for c in preview.columns.tolist()]

                where_clause = ""
                where_params: List = []
                if search and search_field in columns:
                    needle = f"%{search.strip().lower()}%"
                    quoted = '"' + search_field.replace('"', '""') + '"'
                    where_clause = f" WHERE lower(CAST({quoted} AS VARCHAR)) LIKE ?"
                    where_params.append(needle)

                total = con.execute(
                    f"SELECT COUNT(*) AS c FROM {source_fn}(?) {where_clause}",
                    [str(data_path), *where_params],
                ).fetchone()[0]

                df = con.execute(
                    f"SELECT * FROM {source_fn}(?) {where_clause} LIMIT ? OFFSET ?",
                    [str(data_path), *where_params, int(page_size), int(offset)],
                ).fetchdf()
                df = df.where(pd.notnull(df), None)

                return {
                    "sheet": sheet,
                    "page": page,
                    "page_size": page_size,
                    "total": int(total),
                    "columns": columns,
                    "rows": df.to_dict(orient="records"),
                }
            finally:
                con.close()

        # Fallback path when DuckDB is unavailable.
        if data_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(data_path)
        else:
            df = pd.read_csv(data_path)
        if search and search_field in df.columns:
            token = search.strip().lower()
            df = df[df[search_field].astype(str).str.lower().str.contains(token, na=False)]
        total = len(df)
        page_df = df.iloc[offset : offset + page_size].copy()
        page_df = page_df.where(pd.notnull(page_df), None)
        return {
            "sheet": sheet,
            "page": page,
            "page_size": page_size,
            "total": int(total),
            "columns": [str(c) for c in page_df.columns.tolist()],
            "rows": page_df.to_dict(orient="records"),
        }


manager = JobManager()


class RunJobRequest(BaseModel):
    env: str = Field(..., description="TEST or STG")
    office_code: str
    from_date: str
    to_date: str
    source_types: List[str] = Field(default_factory=list)
    save_mode: str = Field(default="replace", description="replace|append")


app = FastAPI(title="toolReadJson Web")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://127.0.0.1:8000", "http://localhost", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = BASE_DIR / "webui" / "index.html"
    if not html_path.exists():
        return "<h1>webui/index.html not found</h1>"
    return html_path.read_text(encoding="utf-8")


@app.get("/api/v1/meta/options")
def meta_options():
    env_map = {"TEST": "test", "STG": "stg"}
    offices = {}
    for env_name, folder in env_map.items():
        env_dir = BASE_DIR / "ofc_cd" / folder
        if not env_dir.exists():
            offices[env_name] = []
            continue
        names = sorted([p.stem for p in env_dir.glob("*.txt")])
        offices[env_name] = names
    return {
        "envs": ["TEST", "STG"],
        "source_types": ["FRT", "MRI", "DMT", "TBP"],
        "save_modes": ["replace", "append"],
        "offices": offices,
    }


@app.post("/api/v1/jobs")
def create_job(req: RunJobRequest):
    env = req.env.strip().upper()
    if env not in ("TEST", "STG"):
        raise HTTPException(status_code=400, detail="env must be TEST or STG")
    if not re.match(r"^\d{8}$", req.from_date) or not re.match(r"^\d{8}$", req.to_date):
        raise HTTPException(status_code=400, detail="from_date/to_date must be YYYYMMDD")
    if req.save_mode.lower() not in ("replace", "append"):
        raise HTTPException(status_code=400, detail="save_mode must be replace or append")
    valid_sources = {"FRT", "MRI", "DMT", "TBP"}
    for src in req.source_types:
        if src not in valid_sources:
            raise HTTPException(status_code=400, detail=f"unsupported source_type: {src}")

    payload = {
        "env": env,
        "office_code": req.office_code.strip(),
        "from_date": req.from_date.strip(),
        "to_date": req.to_date.strip(),
        "source_types": req.source_types,
        "save_mode": req.save_mode.lower(),
    }
    job_id = manager.submit(payload)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "progress": job.progress,
        "counts": job.counts,
        "has_output": bool((job.output_file and os.path.exists(job.output_file)) or (job.case_files and len(job.case_files) > 0)),
        "error": job.error,
    }


@app.get("/api/v1/jobs/{job_id}/logs")
def get_job_logs(job_id: str, offset: int = Query(0, ge=0)):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    lines = job.logs[offset:]
    return {"logs": lines, "next_offset": offset + len(lines)}


@app.get("/api/v1/jobs/{job_id}/sheets")
def get_job_sheets(job_id: str):
    return {"sheets": manager.sheet_names(job_id)}


@app.get("/api/v1/jobs/{job_id}/results")
def get_job_results(
    job_id: str,
    sheet: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    search: str = Query(""),
    search_field: str = Query("INV_NO"),
):
    return manager.query_results(job_id, sheet, page, page_size, search, search_field)


@app.get("/api/v1/jobs/{job_id}/download")
def download_job_file(job_id: str):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    file_path = None
    if job.output_file and os.path.exists(job.output_file):
        file_path = job.output_file
    else:
        latest = manager._store.get_latest_succeeded_export_for_job(job_id)
        if latest:
            candidate = latest.get("file_path")
            if candidate and os.path.exists(candidate):
                file_path = candidate
    if not file_path:
        raise HTTPException(status_code=400, detail="output file not ready")
    file_name = os.path.basename(file_path)
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=file_name,
    )


@app.post("/api/v1/jobs/{job_id}/exports")
def create_export(job_id: str):
    return manager.create_export(job_id)


@app.get("/api/v1/jobs/{job_id}/exports/{export_id}")
def get_export_status(job_id: str, export_id: str):
    row = manager.get_export(job_id, export_id)
    return {
        "export_id": row["export_id"],
        "job_id": row["job_id"],
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
        "finished_at": _iso(row["finished_at"]),
        "has_file": bool(row.get("file_path") and os.path.exists(row["file_path"])),
        "error": row.get("error"),
    }


@app.get("/api/v1/jobs/{job_id}/exports/{export_id}/download")
def download_export(job_id: str, export_id: str):
    row = manager.get_export(job_id, export_id)
    if row["status"] != "succeeded":
        raise HTTPException(status_code=400, detail="export not ready")
    file_path = row.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="export file not found")
    file_name = os.path.basename(file_path)
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=file_name,
    )


@app.get("/api/v1/history")
def history(limit: int = Query(30, ge=1, le=200)):
    out = []
    for job in manager.list_jobs()[:limit]:
        out.append(
            {
                "job_id": job.job_id,
                "env": job.payload.get("env"),
                "office_code": job.payload.get("office_code"),
                "from_date": job.payload.get("from_date"),
                "to_date": job.payload.get("to_date"),
                "status": job.status,
                "created_at": _iso(job.created_at),
                "started_at": _iso(job.started_at),
                "finished_at": _iso(job.finished_at),
                "counts": job.counts,
                "has_output": bool((job.output_file and os.path.exists(job.output_file)) or (job.case_files and len(job.case_files) > 0)),
            }
        )
    return {"items": out}
