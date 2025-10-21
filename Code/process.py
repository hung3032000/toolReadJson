import requests
import pandas as pd
from processCaseInBrim import *
from saveNewExcel import *
from util import *
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil
import os
import glob

file_name = 'output.xlsx'


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
        for k in ['data', 'items', 'results', 'rows', 'content', 'list', 'records']:
            v = payload.get(k)
            if isinstance(v, list):
                return v
        return [payload]
    return []

def parse_json_safely(self, response):
    """
    Trả về object JSON (dict/list) nếu parse được; nếu không:
    - log 200 ký tự đầu để soi
    - ghi ra file last_response_bad.json
    - trả về None (bỏ qua window này)
    """
    try:
        return response.json()
    except ValueError as e:
        raw = (getattr(response, "text", "") or "").strip()
        update_message_status_box(self, f"Response is not valid JSON: {e}")
        update_message_status_box(self, f"Preview: {raw[:200]}")
        try:
            with open("last_response_bad.json", "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception:
            pass
        return None


# ===================== main flow =====================

def onFuncButtonClick(self, MainWindown, optione1):
    """
    Cải tiến:
    - Batch theo customer (BATCH_SIZE)
    - Chia 2 tháng/lần (range)
    - helper.fetch_window_adaptive: fallback range → source_code → customer
    - Ghi CSV tạm per (batch, range), cuối cùng merge → Excel
    """
    update_message_status_box(self, "Calling API by 2-month windows + customer batches...")
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
            return

        # Lấy danh sách customer theo office
        cust_cd_list = update_config_cust_cd(self) or []
        customers_all = [c.get("cust_cd") for c in cust_cd_list if c.get("cust_cd")]
        if not customers_all:
            update_message_status_box(self, "Không có customer nào để xử lý (file office .txt rỗng?).")
            return

        # Ranges theo 2 tháng
        ranges = split_into_bimonth_ranges(from_date, to_date)
        update_message_status_box(self, f"Total windows: {len(ranges)}; customers: {len(customers_all)}")

        # Tham số điều chỉnh
        BATCH_SIZE = 10  # thử 10 trước, có thể nâng lên 15–20 nếu ổn
        source_codes = [s.get("source_code") for s in body.get("source_code", []) if s.get("source_code")] \
                       or ["MRI", "FRT", "MDM", "MDT", "MRD"]

        # HTTP session dùng lại kết nối
        from helper import build_session, fetch_window_adaptive
        session = build_session()

        # folder tạm
        tmp_dir = "tmp"
        os.makedirs(tmp_dir, exist_ok=True)

        # Xử lý theo batch customer
        office = self.officeCode.currentText()
        batch_no = 0
        for start_idx in range(0, len(customers_all), BATCH_SIZE):
            batch_no += 1
            batch_customers = customers_all[start_idx:start_idx + BATCH_SIZE]
            update_message_status_box(self, f"Batch {batch_no}: {len(batch_customers)} customers")

            range_no = 0
            for (fm, to) in ranges:
                range_no += 1
                # Gọi theo cơ chế adaptive (range → source → customer)
                rows = fetch_window_adaptive(
                    self, session, base_url, headers, body,
                    office=office,
                    customers=batch_customers,
                    fm=fm, to=to,
                    source_codes=source_codes
                )
                # Ghi CSV tạm để giảm RAM
                if rows:
                    try:
                        df_tmp = pd.json_normalize(rows)
                        part_path = os.path.join(tmp_dir, f"{office}_b{batch_no}_r{range_no}.csv")
                        df_tmp.to_csv(part_path, index=False)
                        update_message_status_box(self, f"Saved part: {part_path} (+{len(df_tmp)})")
                    except Exception as ex_csv:
                        update_message_status_box(self, f"CSV write error: {ex_csv}")

                # Checkpoint
                try:
                    with open(f"progress_{office}.json", "w", encoding="utf-8") as pf:
                        json.dump({"office": office, "batch_no": batch_no, "range_no": range_no}, pf)
                except Exception:
                    pass

        # Merge các part CSV → DataFrame
        files = sorted(glob.glob(os.path.join(tmp_dir, f"{office}_b*_r*.csv")))
        if not files:
            update_message_status_box(self, "No data overall (không có file tạm nào).")
            return

        update_message_status_box(self, f"Merging {len(files)} parts ...")
        try:
            df_all = pd.concat((pd.read_csv(p) for p in files), ignore_index=True)
        except Exception as ex_merge:
            update_message_status_box(self, f"Merge CSV error: {ex_merge}")
            return

        # Đưa về pipeline sẵn có: xuất Excel tạm rồi chạy processCaseInBrim
        excelFilePatch = "dataFromJsonToExcel.xlsx"
        try:
            df_all.to_excel(excelFilePatch, index=False, engine='openpyxl')
            update_message_status_box(self, f"Excel file has been created: {excelFilePatch}")
        except Exception as ex_x:
            update_message_status_box(self, f"Write Excel error: {ex_x}")
            return

        # Đọc lại + phân loại case
        data_raw = readFileExcel(excelFilePatch)
        data_after_process = processDataRawToRealData(data_raw)
        update_message_status_box(self, "Done processing data")

        # Lưu kết quả cuối
        if optione1:
            saveNewExcel(self, data_after_process, file_name, 1)
            update_message_status_box(self, "Done Save And Replace Excel")
        else:
            saveNewExcel(self, data_after_process, file_name, 0)
            update_message_status_box(self, "Done Save Excel File")

        # Cập nhật số lượng case
        setDataCount(self)

    except Exception as e:
        msg = (getattr(response, "text", None)[:500] if response is not None and hasattr(response, "text") else str(e))
        update_message_status_box(self, f"Error (chunked): {msg}")


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
    name = 'dataFromJsonToExcel'
    excel_file_path = name + '.xlsx'
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

        with open(office+'.txt', "r", encoding="utf-8") as f:
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
        with open(office+'.txt', "r", encoding="utf-8") as f:
            lines = f.readlines()
        cust_codes = [line.strip() for line in lines if line.strip()]
        cust_cd_list = [{"cust_cd": code} for code in cust_codes]
        return cust_cd_list
    except Exception as e:
        print("Error updating config cust_cd:", str(e))
        return None
