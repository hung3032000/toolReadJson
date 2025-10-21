import requests
import pandas as pd
from processCaseInBrim import *
from saveNewExcel import *
from util import *
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil

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
    update_message_status_box(self, "Calling API by 2-month windows...")
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
        # header để server hiểu trả JSON
        if "Accept" not in headers:
            headers["Accept"] = "application/json"

        from_date = body.get("fm_inv_issue_date")
        to_date   = body.get("to_inv_issue_date")
        ranges = split_into_bimonth_ranges(from_date, to_date)
        update_message_status_box(self, f"Total windows: {len(ranges)}")

        all_rows = []  # gom tất cả records
        for idx, (fm, to) in enumerate(ranges, 1):
            body["fm_inv_issue_date"] = fm
            body["to_inv_issue_date"] = to
            try:
                response = requests.post(base_url, headers=headers, data=json.dumps(body))
            except Exception as ex_net:
                update_message_status_box(self, f"[{idx}/{len(ranges)}] Network error {fm}→{to}: {ex_net}")
                continue

            sc = response.status_code
            if sc == 200:
                payload = parse_json_safely(self, response)
                if payload is None:
                    update_message_status_box(self, f"[{idx}/{len(ranges)}] Skip (bad JSON) {fm}→{to}")
                    continue
                records = extract_records(payload)
                all_rows.extend(records)
                update_message_status_box(self, f"[{idx}/{len(ranges)}] OK {fm}→{to} (+{len(records)})")
            elif sc == 204:
                update_message_status_box(self, f"[{idx}/{len(ranges)}] No data {fm}→{to}")
            elif sc == 401:
                update_message_status_box(self, f"[{idx}/{len(ranges)}] 401 Unauthorized {fm}→{to}: kiểm tra token")
            else:
                preview = (getattr(response, "text", "") or "")[:300]
                update_message_status_box(self, f"[{idx}/{len(ranges)}] Failed [{sc}] {fm}→{to}: {preview}")

        if not all_rows:
            update_message_status_box(self, "No data overall.")
            return
        try:
            # xử lý & ghi excel
            if optione1:
                saveAndReplaceExcel(self, all_rows)
            else:
                saveExcel(self, all_rows)
        except Exception as e:
            print(e)
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
    # merge_case đang chỉ print ra console
    print(str(result_count_of_case.get('merge_case', 0)))

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
