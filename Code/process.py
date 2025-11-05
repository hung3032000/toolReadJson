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
        cust_cd_list = update_config_cust_cd(self) or []
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
        from helper import build_session, fetch_window_adaptive

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
                part_path = os.path.join(
                    tmp_dir, f"{office}_b{bno}_r{rno}_{uuid.uuid4().hex[:8]}.csv"
                )
                df_tmp.to_csv(part_path, index=False)
                return f"[OK] b{bno} r{rno} (+{len(df_tmp)}) -> {os.path.basename(part_path)}"
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
                    

        # Merge các part CSV → DataFrame
        files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r_*.csv"))) \
                or sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r*.csv")))
        if not files:
            update_message_status_box(self, "No data overall (không có file tạm nào).")
            end_time = time.time()
            count_time(self, end_time, start_time)
            return

        update_message_status_box(self, f"Merging {len(files)} parts ...")
        try:
            df_all = pd.concat((pd.read_csv(p) for p in files), ignore_index=True)
        except Exception as ex_merge:
            update_message_status_box(self, f"Merge CSV error: {ex_merge}")
            end_time = time.time()
            count_time(self, end_time, start_time)
            clear_temp_file(self)
            return

        # Đưa về pipeline sẵn có: xuất Excel tạm rồi chạy processCaseInBrim
        excelFilePatch = "dataFromJsonToExcel.xlsx"
        try:
            df_all.to_excel(excelFilePatch, index=False, engine='openpyxl')
            update_message_status_box(self, f"Excel file has been created: {excelFilePatch}")
        except Exception as ex_x:
            update_message_status_box(self, f"Write Excel error: {ex_x}")
            end_time = time.time()
            count_time(self, end_time, start_time)
            clear_temp_file(self)
            return

        # Đọc lại + phân loại case
        data_raw = readFileExcel(excelFilePatch)
        data_after_process = processDataRawToRealData(data_raw)
        update_message_status_box(self, "Done processing data")

        # Lưu kết quả cuối
        if optione1:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name2 = f"output_{ofc_cd}_{ts}.xlsx"
            saveNewExcel(self, data_after_process, file_name2, 1)
            update_message_status_box(self, "Done Save And Replace Excel")
        else:
            saveNewExcel(self, data_after_process, file_name, 0)
            update_message_status_box(self, "Done Save Excel File")

        # Cập nhật số lượng case
        setDataCount(self)
        try:
            clear_temp_file(self)
        except Exception as ex_clean:
            end_time = time.time()
            count_time(self, end_time, start_time)
            update_message_status_box(self, f"⚠️ Cleanup failed: {ex_clean}")
        
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

def updateConfigSourceCode(self, config_file="config.json"):
    """
    Read config.json, Update 'source_code' in body base on checkbox,
    and save into file. Return config_data if success, else None.
    """
    try:
        office = self.officeCode.currentText()
        from_date = self.fromDate.text().strip()
        to_date = self.toDtae.text().strip()
        with open("config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)

        with open('ofc_cd/'+office+'.txt', "r", encoding="utf-8") as f:
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
        with open('ofc_cd/'+office+'.txt', "r", encoding="utf-8") as f:
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
    
def clear_temp_file(self):
    shutil.rmtree("tmp")     # xoá toàn bộ folder tmp
    os.makedirs("tmp", exist_ok=True)  # tạo lại trống nếu cần chạy lần sau
    update_message_status_box(self, "🧹 Cleaned up tmp folder.")