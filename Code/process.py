import requests
import pandas as pd
from processCaseInBrim import *
from saveNewExcel import *
from util import *
import json
file_name = 'output.xlsx'
# Get env

# Func process
def onFuncButtonClick(self, MainWindown, optione1):
    update_message_status_box(self, "Calling API...")
    with open("config.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
    API_HOME_TEST = config_data["envData"].get("API_HOME_TEST", {})
    API_HOME_STG = config_data["envData"].get("API_HOME_STG", {})
    URL = config_data["envData"].get("URL_DATA", {})
    URL_STG = config_data["envData"].get("URL_DATA_STG", {}) 
    # Lấy giá trị từ ComboBox và xác định URL dựa trên giá trị chọn
    env = self.envCombobox.currentText().strip()
    if env == "STG":
        url = API_HOME_STG + URL_STG
    elif env == "TEST":
        url = API_HOME_TEST + URL
    else:
        update_message_status_box(self, "Invalid environment selected")
        return
    
    try:
        updateConfigSourceCode(self, "config.json")
        # Đọc header và body từ file "header_body.json"
        headers = config_data.get("headers", {})
        body = json.dumps(config_data.get("body",{}), indent=4)
        # Body là một chuỗi JSON (có thể điều chỉnh tham số theo API của bạn)
        
        # Gọi API sử dụng POST với header và body đã cấu hình
        response = requests.post(url, headers=headers, data=body)
 
        response.raise_for_status()  # Kiểm tra lỗi HTTP
        # Lấy dữ liệu trả về dạng JSON
        if response.status_code == 401:
            update_message_status_box(self, "Error 401 Unauthorized: Token invalid.")
            print("401 Unauthorized:", response.text)
        elif response.status_code == 200:
            json_data = response.json()
            update_message_status_box(self, "API call successful, processing data...")
            if optione1:
                saveAndReplaceExcel(self, json_data)
            else:
                saveExcel(self, json_data)
        elif response.status_code == 204:
            update_message_status_box(self, f"No data in this range of time")
        else:
            update_message_status_box(self, f"API call failed with status code: {response.text}")
    
    except Exception as e:
        update_message_status_box(self, f"Error calling API: {response.text}")
        

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
    # Chuyển dữ liệu JSON thành DataFrame và lưu tạm thời sang Excel nếu cần
    excelFilePatch = saveDataFromJsonToExcel(self, json_data)
    data_raw = readFileExcel(excelFilePatch)
    data_after_process = processDataRawToRealData(data_raw)
    print("Done processing")
    update_message_status_box(self, "Done processing data")
    return data_after_process

def saveDataFromJsonToExcel(self, json_data):
    # Chuyển dữ liệu JSON thành DataFrame
    data = pd.DataFrame(json_data)
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
    self.single_case_count.setText(str(result_count_of_case['single_case']))
    self.split_case_count.setText(str(result_count_of_case['split_case']))
    self.split_manual_case_count.setText(str(result_count_of_case['split_case_manual']))
    self.group_case_count.setText(str(result_count_of_case['group_case']))
    self.supplement_case_count.setText(str(result_count_of_case['supplement_case']))


def updateConfigSourceCode(self, config_file="config.json"):
    """
    Đọc file config.json, cập nhật trường 'source_code' trong body dựa trên các checkbox,
    và ghi lại file. Trả về config_data đã cập nhật nếu thành công, ngược lại trả về None.
    """
    try:
        office = self.officeCode.currentText()
        from_date = self.fromDate.text().strip()
        to_date = self.toDtae.text().strip()
        with open("config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        with open(office+'.txt', "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Loại bỏ khoảng trắng thừa và dòng rỗng
        cust_codes = [line.strip() for line in lines if line.strip()]
        # Chuyển đổi thành danh sách các dict
        cust_cd_list = [{"cust_cd": code} for code in cust_codes]
        
        # Xây dựng danh sách mới cho "source_code"
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
        # Ghi đè file config.json với cấu hình đã cập nhật
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        
        return config_data
    except Exception as e:
        update_message_status_box(self, f"Error updating config: {str(e)}")
        return None


def update_config_cust_cd(self, config_file="config.json"):
    try:
        office = self.officeCode.currentText()
        # Đọc file txt, mỗi dòng là một cust_cd
        with open(office+'.txt', "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Loại bỏ khoảng trắng thừa và dòng rỗng
        cust_codes = [line.strip() for line in lines if line.strip()]
        # Chuyển đổi thành danh sách các dict
        cust_cd_list = [{"cust_cd": code} for code in cust_codes]
        return cust_cd_list
    except Exception as e:
        print("Error updating config cust_cd:", str(e))
        return None
        