import glob
import json
import math
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
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import xlsxwriter
from pydantic import BaseModel, Field

try:
    import duckdb
except Exception:  # pragma: no cover - optional dependency
    duckdb = None

try:
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover - optional dependency
    pq = None


BASE_DIR = Path(__file__).resolve().parent
CODE_DIR = BASE_DIR / "Code"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)
STATE_DB = BASE_DIR / "web_state.db"
RETENTION_DAYS = 7
MAX_LOGS_IN_MEMORY = 3000
EXCEL_EXPORT_MAX_ROWS = 1_000_000
EXPORT_BATCH_SIZE = 50_000
EXCEL_SHEET_TITLE_LIMIT = 31

if str(CODE_DIR) not in sys.path:
    sys.path.append(str(CODE_DIR))

import process  # noqa: E402
from web_filter import apply_to_dataframe, compile_sql, validate_expression


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


CASE_COUNT_KEYS = (
    "single_case",
    "split_case",
    "split_case_manual",
    "group_case",
    "supplement_case",
)

ALL_SHEETS_NAME = "__ALL_SHEETS__"
ALL_SHEETS_LABEL = "All Sheets"
SOURCE_SHEET_COLUMN = "SOURCE_SHEET"


def _default_counts():
    return {key: 0 for key in CASE_COUNT_KEYS}


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
    counts: Dict = field(default_factory=_default_counts)
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
        self._schema_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

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
                stale_keys = [key for key in self._schema_cache if key[0] == job_id]
                for key in stale_keys:
                    self._schema_cache.pop(key, None)
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
                self._execute_export(item["job_id"], item["export_id"], context=item.get("context") or {})
            finally:
                self._export_queue.task_done()

    def create_export(self, job_id: str, context: Optional[Dict[str, Any]] = None) -> Dict:
        job = self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != "succeeded":
            raise HTTPException(status_code=400, detail="job is not completed")

        export_context: Dict[str, Any] = {}
        context = context or {}
        if context:
            sheet = str(context.get("sheet") or "").strip() or ALL_SHEETS_NAME
            filter_expr = str(context.get("filter_expr") or "").strip()
            validation, schema = self._compile_filter_expr(job_id, sheet, filter_expr)
            grouping = self._resolve_grouping(
                schema,
                group_enabled=bool(context.get("group_enabled")),
                group_field=str(context.get("group_field") or ""),
                distinct_field=str(context.get("distinct_field") or ""),
                min_distinct=context.get("min_distinct") or 2,
            )
            export_context = {
                "sheet": sheet,
                "filter_expr": validation.get("normalized_expression", ""),
                "group_enabled": bool(grouping),
                "group_field": grouping["group_field"] if grouping else "",
                "distinct_field": grouping["distinct_field"] if grouping else "",
                "min_distinct": grouping["min_distinct"] if grouping else 2,
            }

        export_id = uuid.uuid4().hex[:10]
        self._store.create_export(export_id, job_id, "pending")
        self._export_queue.put({"job_id": job_id, "export_id": export_id, "context": export_context})
        return {"export_id": export_id, "status": "pending"}

    def get_export(self, job_id: str, export_id: str) -> Dict:
        row = self._store.get_export_for_job(job_id, export_id)
        if not row:
            raise HTTPException(status_code=404, detail="export not found")
        return row

    def _execute_export(self, job_id: str, export_id: str, context: Optional[Dict[str, Any]] = None):
        self._store.update_export(export_id, "running", finished=False)
        try:
            out_path = self._build_export_file(job_id, export_id, context=context or {})
            self._store.update_export(export_id, "succeeded", file_path=out_path, finished=True)
        except Exception as exc:
            self._store.update_export(export_id, "failed", error=self._friendly_export_error(exc), finished=True)

    def _friendly_export_error(self, exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        lowered = text.lower()
        if "permission denied" in lowered:
            return "Khong the ghi file Excel. Hay dong file dang mo roi thu lai."
        if "no sheet data to export" in lowered:
            return "Khong co du lieu sheet de xuat Excel."
        if "job not found" in lowered:
            return "Khong tim thay job de xuat Excel."
        return text

    def _unique_export_sheet_title(self, used_names: set, base_name: str, part_idx: int, force_suffix: bool) -> str:
        base = _safe_sheet_name(base_name, len(used_names) + 1)
        suffix = f"_{part_idx}" if force_suffix or part_idx > 1 else ""
        max_base_len = max(1, EXCEL_SHEET_TITLE_LIMIT - len(suffix))
        candidate = f"{base[:max_base_len]}{suffix}"
        seq = 1
        while candidate in used_names:
            extra = f"_{seq}"
            max_base_len = max(1, EXCEL_SHEET_TITLE_LIMIT - len(suffix) - len(extra))
            candidate = f"{base[:max_base_len]}{suffix}{extra}"
            seq += 1
        used_names.add(candidate)
        return candidate

    def _new_export_sheet(self, workbook, used_names: set, base_name: str, part_idx: int, force_suffix: bool, columns: List[str]):
        title = self._unique_export_sheet_title(used_names, base_name, part_idx, force_suffix)
        ws = workbook.add_worksheet(title)
        ws._export_next_row = 0
        if columns:
            ws.write_row(0, 0, [str(c) for c in columns])
            ws._export_next_row = 1
        return ws

    @staticmethod
    def _frame_to_rows(frame: pd.DataFrame) -> List[List[Any]]:
        # Vectorized NaN -> None conversion; .tolist() coerces numpy scalars to
        # native Python types (str/int/float/Timestamp/None) that xlsxwriter writes
        # directly. Avoids per-cell Python calls which dominated the old export cost.
        if frame.empty:
            return []
        obj = frame.astype(object).where(pd.notna(frame), None)
        return obj.values.tolist()

    def _write_rows_to_sheet(self, ws, rows: List[List[Any]]) -> None:
        next_row = ws._export_next_row
        write_row = ws.write_row
        for row in rows:
            write_row(next_row, 0, row)
            next_row += 1
        ws._export_next_row = next_row

    def _dataset_columns_for_path(self, data_path: Path) -> List[str]:
        if data_path.suffix.lower() == ".parquet":
            if pq is not None:
                return list(pq.ParquetFile(data_path).schema_arrow.names)
            return list(pd.read_parquet(data_path, engine="pyarrow").columns)
        return list(pd.read_csv(data_path, nrows=0).columns)

    def _iter_dataset_batches(self, data_path: Path, columns: List[str]):
        if data_path.suffix.lower() == ".parquet":
            if pq is not None:
                parquet_file = pq.ParquetFile(data_path)
                for batch in parquet_file.iter_batches(batch_size=EXPORT_BATCH_SIZE, columns=columns or None):
                    yield batch.to_pandas()
                return
            yield pd.read_parquet(data_path, engine="pyarrow", columns=columns or None)
            return

        for chunk in pd.read_csv(data_path, chunksize=EXPORT_BATCH_SIZE):
            yield chunk.reindex(columns=columns)

    def _append_dataframe_to_workbook(
        self,
        workbook,
        used_names: set,
        base_name: str,
        df: pd.DataFrame,
        columns: List[str],
    ) -> int:
        columns = list(columns or df.columns.tolist())
        frame = df.reindex(columns=columns)
        total_rows = int(len(frame.index))
        part_count = max(1, int(math.ceil(total_rows / float(EXCEL_EXPORT_MAX_ROWS)))) if total_rows else 1
        rows_written = 0

        for part_idx in range(1, part_count + 1):
            ws = self._new_export_sheet(workbook, used_names, base_name, part_idx, part_count > 1, columns)
            part_frame = frame.iloc[rows_written : rows_written + EXCEL_EXPORT_MAX_ROWS]
            self._write_rows_to_sheet(ws, self._frame_to_rows(part_frame))
            rows_written += int(len(part_frame.index))

        return rows_written

    def _append_dataset_path_to_workbook(
        self,
        workbook,
        used_names: set,
        base_name: str,
        data_path: Path,
        expected_rows: Optional[int] = None,
    ) -> int:
        columns = self._dataset_columns_for_path(data_path)
        part_count = 0
        rows_in_current_sheet = EXCEL_EXPORT_MAX_ROWS
        ws = None
        rows_written = 0
        force_suffix = bool(expected_rows and expected_rows > EXCEL_EXPORT_MAX_ROWS)

        for batch_df in self._iter_dataset_batches(data_path, columns):
            if batch_df.empty and rows_written:
                continue
            batch_df = batch_df.reindex(columns=columns)
            offset = 0
            while offset < len(batch_df.index):
                if ws is None or rows_in_current_sheet >= EXCEL_EXPORT_MAX_ROWS:
                    part_count += 1
                    ws = self._new_export_sheet(workbook, used_names, base_name, part_count, force_suffix or part_count > 1, columns)
                    rows_in_current_sheet = 0
                remaining = EXCEL_EXPORT_MAX_ROWS - rows_in_current_sheet
                part_df = batch_df.iloc[offset : offset + remaining]
                self._write_rows_to_sheet(ws, self._frame_to_rows(part_df))
                chunk_rows = int(len(part_df.index))
                rows_written += chunk_rows
                rows_in_current_sheet += chunk_rows
                offset += chunk_rows

        if part_count == 0:
            self._new_export_sheet(workbook, used_names, base_name, 1, force_suffix, columns)

        return rows_written

    def _build_export_file(self, job_id: str, export_id: str, context: Optional[Dict[str, Any]] = None) -> str:
        job = self.get_job(job_id)
        if not job:
            raise Exception("job not found")

        export_dir = ARTIFACTS_DIR / job_id / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = export_dir / f"export_{export_id}_{ts}.xlsx"
        tmp_file = export_dir / f"export_{export_id}_{ts}.tmp.xlsx"
        workbook = xlsxwriter.Workbook(
            str(tmp_file),
            {"constant_memory": True, "default_date_format": "yyyy-mm-dd hh:mm:ss"},
        )
        used_sheet_names = set()
        workbook_closed = False

        try:
            context = context or {}
            if context.get("sheet"):
                sheet = str(context.get("sheet") or ALL_SHEETS_NAME)
                filter_expr = str(context.get("filter_expr") or "")
                df, _, schema, _, _, _ = self.materialize_query_frame(
                    job_id,
                    sheet,
                    filter_expr=filter_expr,
                    group_enabled=bool(context.get("group_enabled")),
                    group_field=str(context.get("group_field") or ""),
                    distinct_field=str(context.get("distinct_field") or ""),
                    min_distinct=context.get("min_distinct") or 2,
                )
                output_sheet = "filtered_results" if sheet == ALL_SHEETS_NAME else sheet
                self._append_dataframe_to_workbook(
                    workbook,
                    used_sheet_names,
                    output_sheet,
                    df,
                    list(schema.get("columns", [])),
                )
            else:
                meta = self.ensure_result_cache(job_id)
                sheet_map = [
                    (x.get("name"), x.get("path"), x.get("row_count"))
                    for x in meta.get("sheets", [])
                ]
                if not sheet_map:
                    raise Exception("no sheet data to export")

                exported_any_sheet = False
                for sheet_name, path, row_count in sheet_map:
                    if not sheet_name or not path:
                        continue
                    data_path = Path(path)
                    if not data_path.exists():
                        continue
                    self._append_dataset_path_to_workbook(
                        workbook,
                        used_sheet_names,
                        str(sheet_name),
                        data_path,
                        expected_rows=int(row_count or 0),
                    )
                    exported_any_sheet = True

                if not exported_any_sheet:
                    raise Exception("no sheet data to export")

            workbook.close()
            workbook_closed = True
            if not tmp_file.exists() or tmp_file.stat().st_size <= 0:
                raise Exception("Excel export created an empty file")
            tmp_file.replace(out_file)
            return str(out_file)
        except Exception:
            if not workbook_closed:
                try:
                    workbook.close()
                except Exception:
                    pass
            for candidate in (tmp_file, out_file):
                if candidate.exists():
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
            raise

    def _execute(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "running"
            job.started_at = time.time()
            self._store.upsert_job(job)

        ui = _BridgeUI(job.payload, self, job_id)
        output_file = None
        case_files = {}

        try:
            before_files = set(glob.glob(str(BASE_DIR / "output*.xlsx")))
            process.onFuncButtonClick(ui, None, True)
            case_files = dict(getattr(ui, "web_case_files", {}) or {})
            if not case_files:
                after_files = set(glob.glob(str(BASE_DIR / "output*.xlsx")))
                output_file = self._detect_output_file(job.payload, before_files, after_files)

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

    def _detect_output_file(self, payload, before_files, after_files):
        env = payload["env"]
        office = payload["office_code"]
        new_files = sorted(list(after_files - before_files), key=lambda p: os.path.getmtime(p), reverse=True)
        pattern = str(BASE_DIR / f"output_{office}_{env}_*.xlsx")
        matched = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
        if matched:
            return matched[0]
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

    def _resolve_sheet_path(self, job_id: str, item: Dict) -> Optional[Path]:
        path = item.get("path")
        if path:
            p = Path(path)
            if not p.is_absolute():
                p = (BASE_DIR / p).resolve()
            else:
                p = p.resolve()
            return p

        parquet_name = item.get("parquet")
        if parquet_name:
            return (ARTIFACTS_DIR / job_id / parquet_name).resolve()
        return None

    def _count_rows_for_path(self, data_path: Path) -> int:
        if duckdb is not None:
            con = duckdb.connect(database=":memory:")
            try:
                source_fn = "read_parquet" if data_path.suffix.lower() == ".parquet" else "read_csv_auto"
                return int(con.execute(f"SELECT COUNT(*) FROM {source_fn}(?)", [str(data_path)]).fetchone()[0] or 0)
            finally:
                con.close()

        if data_path.suffix.lower() == ".parquet":
            return int(len(pd.read_parquet(data_path)))
        return int(len(pd.read_csv(data_path)))

    def _sync_job_counts_from_meta(self, job_id: str, meta: Dict):
        counts = _default_counts()
        for item in meta.get("sheets", []):
            name = str(item.get("name", "")).strip()
            if name in counts:
                try:
                    counts[name] = max(0, int(item.get("row_count", 0) or 0))
                except Exception:
                    counts[name] = 0

        with self._lock:
            job = self._jobs.get(job_id)
            if not job or dict(job.counts or {}) == counts:
                return
            job.counts = counts
            self._store.upsert_job(job)

    def _normalize_cache_meta(self, job_id: str, meta: Dict) -> Dict:
        if not isinstance(meta, dict):
            meta = {}

        changed = False
        normalized_sheets = []
        for item in meta.get("sheets", []):
            if not isinstance(item, dict):
                changed = True
                continue

            sheet_name = str(item.get("name", "")).strip()
            if not sheet_name:
                changed = True
                continue

            resolved_path = self._resolve_sheet_path(job_id, item)
            row_count = item.get("row_count")
            try:
                row_count = max(0, int(row_count))
            except Exception:
                row_count = None

            if resolved_path and resolved_path.exists():
                resolved_path_str = str(resolved_path)
                if item.get("path") != resolved_path_str:
                    changed = True
                if row_count is None:
                    row_count = self._count_rows_for_path(resolved_path)
                    changed = True
            else:
                resolved_path_str = str(resolved_path) if resolved_path else ""
                if row_count is None:
                    row_count = 0
                    changed = True

            normalized_sheets.append(
                {
                    "name": sheet_name,
                    "path": resolved_path_str,
                    "row_count": int(row_count or 0),
                }
            )

        normalized_meta = {
            "created_at": meta.get("created_at") or _iso(time.time()),
            "sheets": normalized_sheets,
        }
        if normalized_meta != meta:
            changed = True

        if changed:
            meta_path = self._cache_meta_path(job_id)
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(normalized_meta, ensure_ascii=True, indent=2), encoding="utf-8")

        self._sync_job_counts_from_meta(job_id, normalized_meta)
        return normalized_meta

    def ensure_result_cache(self, job_id: str) -> Dict:
        job = self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        meta_path = self._cache_meta_path(job_id)
        if meta_path.exists():
            meta = _json_load(meta_path.read_text(encoding="utf-8"), {"sheets": []})
            return self._normalize_cache_meta(job_id, meta)

        lock = self._cache_lock(job_id)
        with lock:
            if meta_path.exists():
                meta = _json_load(meta_path.read_text(encoding="utf-8"), {"sheets": []})
                return self._normalize_cache_meta(job_id, meta)

            cache_dir = meta_path.parent
            cache_dir.mkdir(parents=True, exist_ok=True)

            sheets = []
            if job.case_files:
                for sheet_name, path in job.case_files.items():
                    if path and os.path.exists(path):
                        resolved = Path(path).resolve()
                        sheets.append(
                            {
                                "name": sheet_name,
                                "path": str(resolved),
                                "row_count": self._count_rows_for_path(resolved),
                            }
                        )

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
                    sheets.append({"name": sheet, "path": str(pq_path.resolve()), "row_count": int(len(df))})

            meta = {"created_at": _iso(time.time()), "sheets": sheets}
            meta_path.write_text(json.dumps(meta, ensure_ascii=True, indent=2), encoding="utf-8")
            return self._normalize_cache_meta(job_id, meta)

    def sheet_names(self, job_id: str) -> List[str]:
        return [x["name"] for x in self.sheet_items(job_id)]

    def _source_fn_for_path(self, data_path: Path) -> str:
        return "read_parquet" if data_path.suffix.lower() == ".parquet" else "read_csv_auto"

    def _read_cached_frame(self, data_path: Path) -> pd.DataFrame:
        if data_path.suffix.lower() == ".parquet":
            return pd.read_parquet(data_path)
        return pd.read_csv(data_path)

    def _preview_cached_frame(self, data_path: Path, limit: int = 20) -> pd.DataFrame:
        if duckdb is not None:
            con = duckdb.connect(database=":memory:")
            try:
                source_fn = self._source_fn_for_path(data_path)
                return con.execute(
                    f"SELECT * FROM {source_fn}(?) LIMIT ?",
                    [str(data_path), int(limit)],
                ).fetchdf()
            finally:
                con.close()

        if data_path.suffix.lower() == ".parquet":
            return pd.read_parquet(data_path)
        return pd.read_csv(data_path, nrows=limit)

    def _infer_column_kind(self, series: pd.Series) -> str:
        if pd.api.types.is_numeric_dtype(series):
            return "number"
        return "text"

    def _real_sheet_sources(self, job_id: str) -> List[Dict[str, Any]]:
        meta = self.ensure_result_cache(job_id)
        out: List[Dict[str, Any]] = []
        for item in meta.get("sheets", []):
            name = str(item.get("name", "")).strip()
            resolved = self._resolve_sheet_path(job_id, item)
            if not name or not resolved or not resolved.exists():
                continue
            out.append(
                {
                    "name": name,
                    "label": name,
                    "path": resolved,
                    "row_count": int(item.get("row_count", 0) or 0),
                    "is_virtual": False,
                }
            )
        return out

    def _get_dataset_sources(self, job_id: str, sheet: str) -> Tuple[List[Dict[str, Any]], bool]:
        sources = self._real_sheet_sources(job_id)
        if sheet == ALL_SHEETS_NAME:
            return sources, True
        for source in sources:
            if source["name"] == sheet:
                return [source], False
        raise HTTPException(status_code=400, detail=f"sheet not found: {sheet}")

    def _dataset_total_rows(self, sources: List[Dict[str, Any]]) -> int:
        return int(sum(int(x.get("row_count", 0) or 0) for x in sources))

    def _get_dataset_schema(self, job_id: str, sheet: str) -> Dict[str, Any]:
        cache_key = (job_id, sheet)
        with self._lock:
            cached = self._schema_cache.get(cache_key)
        if cached is not None:
            return cached

        sources, include_source_sheet = self._get_dataset_sources(job_id, sheet)
        columns: List[str] = []
        column_info: Dict[str, Dict[str, Any]] = {}
        if sources:
            preview = self._preview_cached_frame(sources[0]["path"], limit=20)
            columns = [str(c) for c in preview.columns.tolist()]
            for col in columns:
                column_info[col] = {"kind": self._infer_column_kind(preview[col])}

        if include_source_sheet and SOURCE_SHEET_COLUMN not in columns:
            columns.append(SOURCE_SHEET_COLUMN)
            column_info[SOURCE_SHEET_COLUMN] = {"kind": "text"}

        schema = {"columns": columns, "column_info": column_info}
        with self._lock:
            self._schema_cache[cache_key] = schema
        return schema

    def sheet_items(self, job_id: str) -> List[Dict]:
        sources = self._real_sheet_sources(job_id)
        all_schema = self._get_dataset_schema(job_id, ALL_SHEETS_NAME) if sources else {"columns": [SOURCE_SHEET_COLUMN]}
        items = [
            {
                "name": ALL_SHEETS_NAME,
                "label": ALL_SHEETS_LABEL,
                "total_rows": self._dataset_total_rows(sources),
                "is_virtual": True,
                "columns": list(all_schema.get("columns", [])),
            }
        ]
        for source in sources:
            schema = self._get_dataset_schema(job_id, source["name"])
            items.append(
                {
                    "name": source["name"],
                    "label": source["label"],
                    "total_rows": int(source["row_count"]),
                    "is_virtual": False,
                    "columns": list(schema.get("columns", [])),
                }
            )
        return items

    def validate_filter(self, job_id: str, expression: str, sheet: str = ALL_SHEETS_NAME) -> Dict[str, Any]:
        schema = self._get_dataset_schema(job_id, sheet)
        result = validate_expression(expression, schema.get("columns", []))
        result.pop("ast", None)
        result["sheet"] = sheet
        result["columns"] = list(schema.get("columns", []))
        return result

    def _compile_filter_expr(self, job_id: str, sheet: str, filter_expr: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        schema = self._get_dataset_schema(job_id, sheet)
        validation = validate_expression(filter_expr, schema.get("columns", []))
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "filter expression is invalid",
                    "errors": validation.get("errors", []),
                    "suggestions": validation.get("suggestions", []),
                },
            )
        return validation, schema

    def _validate_grouping_fields(
        self,
        schema: Dict[str, Any],
        group_field: str,
        distinct_field: str,
    ) -> Tuple[str, str, List[str]]:
        columns = list(schema.get("columns", []))
        group_field = str(group_field or "").strip()
        distinct_field = str(distinct_field or "").strip()

        if not group_field or group_field not in columns:
            raise HTTPException(status_code=400, detail=f"group_field not found: {group_field or '(empty)'}")
        if not distinct_field or distinct_field not in columns:
            raise HTTPException(status_code=400, detail=f"distinct_field not found: {distinct_field or '(empty)'}")
        if group_field == distinct_field:
            raise HTTPException(status_code=400, detail="group_field and distinct_field must be different")
        return group_field, distinct_field, columns

    def _resolve_grouping(
        self,
        schema: Dict[str, Any],
        group_enabled: bool = False,
        group_field: str = "",
        distinct_field: str = "",
        min_distinct: int = 2,
    ) -> Optional[Dict[str, Any]]:
        if not group_enabled:
            return None

        group_field, distinct_field, _ = self._validate_grouping_fields(schema, group_field, distinct_field)
        try:
            min_distinct = int(min_distinct or 2)
        except Exception:
            raise HTTPException(status_code=400, detail="min_distinct must be an integer >= 2")
        if min_distinct < 2:
            raise HTTPException(status_code=400, detail="min_distinct must be >= 2")

        return {
            "group_field": group_field,
            "distinct_field": distinct_field,
            "min_distinct": min_distinct,
        }

    def _grouping_row_mask(
        self,
        df: pd.DataFrame,
        grouping: Dict[str, Any],
    ) -> pd.Series:
        """Vectorized mask of rows belonging to groups whose distinct count >= min.

        Replaces a per-group Python loop that dominated export/grouped-view latency
        (~23s on 280k rows). ``nunique`` + ``isin`` run in C and are ~150x faster.
        """
        group_field = grouping["group_field"]
        distinct_field = grouping["distinct_field"]
        min_distinct = grouping["min_distinct"]
        if df.empty:
            return pd.Series(False, index=df.index)

        distinct_counts = df.groupby(group_field, dropna=False)[distinct_field].nunique(dropna=True)
        valid_index = distinct_counts.index[distinct_counts.to_numpy() >= min_distinct]
        if len(valid_index) == 0:
            return pd.Series(False, index=df.index)

        null_qualifies = bool(pd.isna(valid_index).any())
        valid_nonnull = valid_index[~pd.isna(valid_index)]
        mask = df[group_field].isin(list(valid_nonnull))
        if null_qualifies:
            mask = mask | df[group_field].isna()
        return mask

    def _build_group_summary_rows(
        self,
        df: pd.DataFrame,
        grouping: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Build the grouped-view summary rows for an already group-filtered frame."""
        group_field = grouping["group_field"]
        distinct_field = grouping["distinct_field"]
        min_distinct = grouping["min_distinct"]
        if df.empty:
            return []

        # Route the null group through a sentinel key so all index/lookup ops work
        # on plain hashable strings (NaN keys break Series.get / dict lookups).
        null_key = "\x00__NULL_GROUP__"
        work = pd.DataFrame(
            {
                "_g": df[group_field].astype(object),
                "_d": df[distinct_field],
            }
        )
        null_mask = work["_g"].isna()
        if null_mask.any():
            work.loc[null_mask, "_g"] = null_key

        grouped = work.groupby("_g", sort=False)
        row_counts = grouped.size()
        distinct_counts = grouped["_d"].nunique(dropna=True)
        keep_keys = distinct_counts.index[distinct_counts.to_numpy() >= min_distinct]
        if len(keep_keys) == 0:
            return []

        pairs = work.loc[work["_d"].notna(), ["_g", "_d"]].copy()
        pairs["_d"] = pairs["_d"].astype(str)
        pairs = pairs.drop_duplicates().sort_values("_d")
        distinct_values = pairs.groupby("_g", sort=False)["_d"].agg(", ".join)

        summary_rows: List[Dict[str, Any]] = []
        for key in keep_keys:
            is_null_group = key == null_key
            values_text = distinct_values.get(key)
            summary_rows.append(
                {
                    group_field: None if is_null_group else str(key),
                    "GROUP_ROW_COUNT": int(row_counts.get(key, 0)),
                    "GROUP_DISTINCT_COUNT": int(distinct_counts.get(key, 0)),
                    "GROUP_DISTINCT_VALUES": values_text if isinstance(values_text, str) else None,
                }
            )

        summary_rows.sort(
            key=lambda row: (
                -int(row.get("GROUP_DISTINCT_COUNT", 0) or 0),
                -int(row.get("GROUP_ROW_COUNT", 0) or 0),
                str(row.get(group_field) or ""),
            )
        )
        return summary_rows

    def _apply_grouping_to_frame(
        self,
        df: pd.DataFrame,
        grouping: Optional[Dict[str, Any]],
        with_summary: bool = False,
    ) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
        if not grouping:
            return df, []

        mask = self._grouping_row_mask(df, grouping)
        filtered = df.loc[mask].copy()
        if filtered.empty:
            return filtered, []
        summary_rows = self._build_group_summary_rows(filtered, grouping) if with_summary else []
        return filtered, summary_rows

    def _build_duckdb_source_sql(self, sources: List[Dict[str, Any]], include_source_sheet: bool) -> Tuple[str, List[Any]]:
        parts: List[str] = []
        params: List[Any] = []
        for source in sources:
            source_fn = self._source_fn_for_path(source["path"])
            if include_source_sheet:
                parts.append(f'SELECT *, ? AS "{SOURCE_SHEET_COLUMN}" FROM {source_fn}(?)')
                params.extend([source["name"], str(source["path"])])
            else:
                parts.append(f"SELECT * FROM {source_fn}(?)")
                params.append(str(source["path"]))
        return " UNION ALL ".join(parts), params

    def _read_dataset_frame(self, sources: List[Dict[str, Any]], include_source_sheet: bool, schema_columns: List[str]) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        for source in sources:
            df = self._read_cached_frame(source["path"])
            if include_source_sheet and SOURCE_SHEET_COLUMN not in df.columns:
                df[SOURCE_SHEET_COLUMN] = source["name"]
            frames.append(df)

        if not frames:
            return pd.DataFrame(columns=schema_columns)

        if len(frames) == 1:
            merged = frames[0].copy()
        else:
            merged = pd.concat(frames, ignore_index=True, copy=False)

        for col in schema_columns:
            if col not in merged.columns:
                merged[col] = None
        return merged.reindex(columns=schema_columns)

    def materialize_filtered_frame(
        self,
        job_id: str,
        sheet: str,
        filter_expr: str = "",
        search: str = "",
        search_field: str = "",
    ) -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any], int]:
        sources, include_source_sheet = self._get_dataset_sources(job_id, sheet)
        validation, schema = self._compile_filter_expr(job_id, sheet, filter_expr)
        df = self._read_dataset_frame(sources, include_source_sheet, schema.get("columns", []))
        if validation.get("normalized_expression"):
            mask = apply_to_dataframe(df, validation["ast"], schema["column_info"])
            df = df.loc[mask].copy()
        if search and search_field and search_field in df.columns:
            token = search.strip().lower()
            df = df[df[search_field].astype(str).str.lower().str.contains(token, na=False)]
        return df, validation, schema, self._dataset_total_rows(sources)

    def materialize_query_frame(
        self,
        job_id: str,
        sheet: str,
        filter_expr: str = "",
        group_enabled: bool = False,
        group_field: str = "",
        distinct_field: str = "",
        min_distinct: int = 2,
        with_summary: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any], int, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        df, validation, schema, unfiltered_total = self.materialize_filtered_frame(
            job_id,
            sheet,
            filter_expr=filter_expr,
        )
        grouping = self._resolve_grouping(
            schema,
            group_enabled=group_enabled,
            group_field=group_field,
            distinct_field=distinct_field,
            min_distinct=min_distinct,
        )
        df, grouped_rows = self._apply_grouping_to_frame(df, grouping, with_summary=with_summary)
        return df, validation, schema, unfiltered_total, grouping, grouped_rows

    def query_results(
        self,
        job_id: str,
        sheet: str,
        page: int,
        page_size: int,
        search: str,
        search_field: str,
        filter_expr: str = "",
        filters: Optional[List[Dict]] = None,
        group_enabled: bool = False,
        group_field: str = "",
        distinct_field: str = "",
        min_distinct: int = 2,
    ):
        filters = filters or []
        df, validation, schema, unfiltered_total, grouping, _ = self.materialize_query_frame(
            job_id,
            sheet,
            filter_expr=filter_expr,
            group_enabled=group_enabled,
            group_field=group_field,
            distinct_field=distinct_field,
            min_distinct=min_distinct,
        )
        normalized_filter_expr = validation.get("normalized_expression", "")
        columns = list(schema.get("columns", []))
        source_rows_filtered = int(len(df.index))
        if search and search_field in df.columns:
            token = search.strip().lower()
            df = df[df[search_field].astype(str).str.lower().str.contains(token, na=False)]
        for item in filters:
            col = str(item.get("field", "")).strip()
            val = str(item.get("value", "")).strip()
            if col and val and col in df.columns:
                df = df[df[col].astype(str).str.lower().str.contains(val.lower(), na=False)]
        filtered_total = len(df)
        total_pages = max(1, int(math.ceil(filtered_total / float(page_size)))) if filtered_total else 1
        page = max(1, min(int(page), total_pages))
        offset = (page - 1) * page_size
        page_df = df.iloc[offset : offset + page_size].copy()
        page_df = page_df.where(pd.notnull(page_df), None)
        page_row_from = offset + 1 if filtered_total else 0
        page_row_to = offset + len(page_df.index) if filtered_total else 0
        return {
            "sheet": sheet,
            "page": page,
            "page_size": page_size,
            "total": int(filtered_total),
            "unfiltered_total": unfiltered_total,
            "filtered_total": int(filtered_total),
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "page_row_from": page_row_from,
            "page_row_to": page_row_to,
            "columns": columns,
            "filter_expr": filter_expr,
            "normalized_filter_expression": normalized_filter_expr,
            "applied_filters": filters,
            "group_enabled": bool(grouping),
            "group_field": grouping["group_field"] if grouping else "",
            "distinct_field": grouping["distinct_field"] if grouping else "",
            "min_distinct": grouping["min_distinct"] if grouping else None,
            "source_rows_filtered": source_rows_filtered,
            "rows": page_df.to_dict(orient="records"),
        }

    def query_grouped_results(
        self,
        job_id: str,
        sheet: str,
        group_field: str,
        distinct_field: str,
        page: int,
        page_size: int,
        filter_expr: str = "",
        min_distinct: int = 2,
        search: str = "",
    ):
        df, validation, _, source_rows_total, grouping, grouped_rows = self.materialize_query_frame(
            job_id,
            sheet,
            filter_expr=filter_expr,
            group_enabled=True,
            group_field=group_field,
            distinct_field=distinct_field,
            min_distinct=min_distinct,
            with_summary=True,
        )
        normalized_filter_expr = validation.get("normalized_expression", "")
        if not grouping:
            raise HTTPException(status_code=400, detail="grouping configuration is required")

        group_field = grouping["group_field"]
        distinct_field = grouping["distinct_field"]
        min_distinct = grouping["min_distinct"]
        summary_columns = [group_field, "GROUP_ROW_COUNT", "GROUP_DISTINCT_COUNT", "GROUP_DISTINCT_VALUES"]
        source_rows_filtered = int(len(df.index))
        search = str(search or "").strip()
        visible_grouped_rows = list(grouped_rows)
        if search:
            token = search.lower()
            visible_grouped_rows = [
                row
                for row in visible_grouped_rows
                if token in str(row.get(group_field) or "").lower()
                or token in str(row.get("GROUP_DISTINCT_VALUES") or "").lower()
            ]

        filtered_total = len(visible_grouped_rows)
        total_pages = max(1, int(math.ceil(filtered_total / float(page_size)))) if filtered_total else 1
        page = max(1, min(int(page), total_pages))
        offset = (page - 1) * page_size
        page_rows = visible_grouped_rows[offset : offset + page_size]
        page_row_from = offset + 1 if filtered_total else 0
        page_row_to = offset + len(page_rows) if filtered_total else 0
        return {
            "mode": "grouped",
            "sheet": sheet,
            "page": page,
            "page_size": page_size,
            "total": int(filtered_total),
            "unfiltered_total": source_rows_total,
            "filtered_total": int(filtered_total),
            "source_rows_total": source_rows_total,
            "source_rows_filtered": int(source_rows_filtered),
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "page_row_from": page_row_from,
            "page_row_to": page_row_to,
            "columns": summary_columns,
            "group_field": group_field,
            "distinct_field": distinct_field,
            "min_distinct": min_distinct,
            "search": search,
            "filter_expr": filter_expr,
            "normalized_filter_expression": normalized_filter_expr,
            "group_enabled": True,
            "rows": page_rows,
        }

    def _normalize_lookup_values(self, values: List[Any]) -> Tuple[List[str], List[str]]:
        normalized: List[str] = []
        distinct: List[str] = []
        seen = set()
        for item in values or []:
            text = str("" if item is None else item).strip()
            if not text:
                continue
            normalized.append(text)
            if text in seen:
                continue
            seen.add(text)
            distinct.append(text)
        return normalized, distinct

    def _format_lookup_literal(self, value: str) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            return text
        if re.fullmatch(r"[A-Za-z0-9_%./:-]+", text):
            return text
        return "'" + text.replace("'", "''") + "'"

    def lookup_rows(
        self,
        job_id: str,
        sheet: str,
        field: str,
        values: List[Any],
        filter_expr: str = "",
        group_enabled: bool = False,
        group_field: str = "",
        distinct_field: str = "",
        min_distinct: int = 2,
    ) -> Dict[str, Any]:
        df, validation, schema, unfiltered_total, grouping, _ = self.materialize_query_frame(
            job_id,
            sheet,
            filter_expr=filter_expr,
            group_enabled=group_enabled,
            group_field=group_field,
            distinct_field=distinct_field,
            min_distinct=min_distinct,
        )
        columns = list(schema.get("columns", []))
        field = str(field or "").strip()
        if not field or field not in columns:
            raise HTTPException(status_code=400, detail=f"field not found: {field or '(empty)'}")

        raw_values, distinct_values = self._normalize_lookup_values(values)
        if not distinct_values:
            raise HTTPException(status_code=400, detail="values must contain at least one non-empty item")

        lookup_expr = f"{field} IN ({', '.join(self._format_lookup_literal(value) for value in distinct_values)})"
        lookup_validation = validate_expression(lookup_expr, columns)
        if not lookup_validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "lookup expression is invalid",
                    "errors": lookup_validation.get("errors", []),
                    "suggestions": lookup_validation.get("suggestions", []),
                },
            )

        mask = apply_to_dataframe(df, lookup_validation["ast"], schema.get("column_info", {}))
        matched_df = df.loc[mask].copy()

        def to_lookup_text(value: Any) -> str:
            try:
                if pd.isna(value):
                    return ""
            except Exception:
                pass
            return str(value).strip()

        order_map = {value: index for index, value in enumerate(distinct_values)}
        if not matched_df.empty:
            matched_df["__lookup_order"] = matched_df[field].map(lambda value: order_map.get(to_lookup_text(value), len(order_map)))
            matched_df["__lookup_row_order"] = range(len(matched_df.index))
            matched_df = matched_df.sort_values(by=["__lookup_order", "__lookup_row_order"], kind="stable")
            matched_df = matched_df.drop(columns=["__lookup_order", "__lookup_row_order"])

        matched_value_set = {to_lookup_text(value) for value in matched_df[field].tolist()}
        matched_value_set.discard("")
        matched_values = [value for value in distinct_values if value in matched_value_set]
        missing_values = [value for value in distinct_values if value not in matched_value_set]
        matched_df = matched_df.reindex(columns=columns).where(pd.notnull(matched_df), None)
        normalized_filter_expr = validation.get("normalized_expression", "")

        return {
            "sheet": sheet,
            "field": field,
            "columns": columns,
            "rows": matched_df.to_dict(orient="records"),
            "lookup_input_total": len(raw_values),
            "lookup_distinct_total": len(distinct_values),
            "matched_rows_total": int(len(matched_df.index)),
            "matched_values_total": len(matched_values),
            "missing_values_total": len(missing_values),
            "matched_values": matched_values,
            "missing_values": missing_values,
            "lookup_expression": lookup_validation.get("normalized_expression", lookup_expr),
            "filter_expr": filter_expr,
            "normalized_filter_expression": normalized_filter_expr,
            "group_enabled": bool(grouping),
            "group_field": grouping["group_field"] if grouping else "",
            "distinct_field": grouping["distinct_field"] if grouping else "",
            "min_distinct": grouping["min_distinct"] if grouping else None,
            "source_rows_total": int(unfiltered_total),
            "source_rows_filtered": int(len(df.index)),
        }


manager = JobManager()


class RunJobRequest(BaseModel):
    env: str = Field(..., description="TEST or STG")
    office_code: str
    from_date: str
    to_date: str
    source_types: List[str] = Field(default_factory=list)


class ValidateFilterRequest(BaseModel):
    expression: str = ""
    sheet: str = ALL_SHEETS_NAME


class LookupRowsRequest(BaseModel):
    sheet: str = ALL_SHEETS_NAME
    field: str
    values: List[str] = Field(default_factory=list)
    filter_expr: str = ""
    group_enabled: bool = False
    group_field: str = ""
    distinct_field: str = ""
    min_distinct: int = 2


class CreateExportRequest(BaseModel):
    sheet: str = ""
    filter_expr: str = ""
    group_enabled: bool = False
    group_field: str = ""
    distinct_field: str = ""
    min_distinct: int = 2


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


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "app": "toolReadJson Web",
        "time": datetime.now().isoformat(timespec="seconds"),
    }


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
        "offices": offices,
    }


@app.post("/api/v1/jobs")
def create_job(req: RunJobRequest):
    env = req.env.strip().upper()
    if env not in ("TEST", "STG"):
        raise HTTPException(status_code=400, detail="env must be TEST or STG")
    if not re.match(r"^\d{8}$", req.from_date) or not re.match(r"^\d{8}$", req.to_date):
        raise HTTPException(status_code=400, detail="from_date/to_date must be YYYYMMDD")
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
    }
    job_id = manager.submit(payload)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status == "succeeded":
        try:
            manager.ensure_result_cache(job_id)
            job = manager.get_job(job_id) or job
        except Exception:
            pass
    counts = _default_counts()
    counts.update(job.counts or {})
    return {
        "job_id": job.job_id,
        "status": job.status,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "progress": job.progress,
        "counts": counts,
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
    items = manager.sheet_items(job_id)
    return {
        "sheets": [x["name"] for x in items],
        "items": items,
        "all_sheets_name": ALL_SHEETS_NAME,
    }


@app.post("/api/v1/jobs/{job_id}/filter/validate")
def validate_filter(job_id: str, req: ValidateFilterRequest):
    return manager.validate_filter(job_id, req.expression, sheet=req.sheet or ALL_SHEETS_NAME)


@app.post("/api/v1/jobs/{job_id}/utility/lookup-rows")
def lookup_job_rows(job_id: str, req: LookupRowsRequest):
    return manager.lookup_rows(
        job_id,
        sheet=req.sheet or ALL_SHEETS_NAME,
        field=req.field,
        values=req.values,
        filter_expr=req.filter_expr,
        group_enabled=req.group_enabled,
        group_field=req.group_field,
        distinct_field=req.distinct_field,
        min_distinct=req.min_distinct,
    )


@app.get("/api/v1/jobs/{job_id}/results")
def get_job_results(
    job_id: str,
    sheet: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    search: str = Query(""),
    search_field: str = Query("INV_NO"),
    filter_expr: str = Query(""),
    group_enabled: bool = Query(False),
    group_field: str = Query(""),
    distinct_field: str = Query(""),
    min_distinct: int = Query(2, ge=2, le=1000),
    filters_json: str = Query(""),
):
    filters = []
    if filters_json:
        try:
            raw = json.loads(filters_json)
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    filters.append(
                        {
                            "field": str(item.get("field", "")).strip(),
                            "value": str(item.get("value", "")).strip(),
                        }
                    )
        except Exception:
            raise HTTPException(status_code=400, detail="filters_json is invalid")
    return manager.query_results(
        job_id,
        sheet,
        page,
        page_size,
        search,
        search_field,
        filter_expr=filter_expr,
        filters=filters,
        group_enabled=group_enabled,
        group_field=group_field,
        distinct_field=distinct_field,
        min_distinct=min_distinct,
    )


@app.get("/api/v1/jobs/{job_id}/grouped-results")
def get_job_grouped_results(
    job_id: str,
    sheet: str = Query(...),
    group_field: str = Query(...),
    distinct_field: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    filter_expr: str = Query(""),
    min_distinct: int = Query(2, ge=2, le=1000),
    search: str = Query(""),
):
    return manager.query_grouped_results(
        job_id,
        sheet,
        group_field=group_field,
        distinct_field=distinct_field,
        page=page,
        page_size=page_size,
        filter_expr=filter_expr,
        min_distinct=min_distinct,
        search=search,
    )


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
def create_export(job_id: str, req: Optional[CreateExportRequest] = Body(None)):
    context = None
    if req is not None and (req.sheet or req.filter_expr or req.group_enabled):
        context = {
            "sheet": req.sheet,
            "filter_expr": req.filter_expr,
            "group_enabled": req.group_enabled,
            "group_field": req.group_field,
            "distinct_field": req.distinct_field,
            "min_distinct": req.min_distinct,
        }
    return manager.create_export(job_id, context=context)


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
        if job.status == "succeeded":
            try:
                manager.ensure_result_cache(job.job_id)
                job = manager.get_job(job.job_id) or job
            except Exception:
                pass
        counts = _default_counts()
        counts.update(job.counts or {})
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
                "counts": counts,
                **counts,
                "has_output": bool((job.output_file and os.path.exists(job.output_file)) or (job.case_files and len(job.case_files) > 0)),
            }
        )
    return {"items": out}
