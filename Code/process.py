import pandas as pd
from processCaseInBrim import *
from saveNewExcel import *
from PyQt5.QtWidgets import  QFileDialog
from util import *
file_name = 'output.xlsx'




def onFuncButtonClick(self,MainWindown, optione1):
    self.statusText.setText('')
    # Mở hộp thoại chọn file
    json_file_path, _ = QFileDialog.getOpenFileName(MainWindown, 'Chọn file', r'<Default dir>', 'Json Files (*.json)')
    if json_file_path:
        # Hiển thị đường dẫn file đã chọn vào text box
        update_message_status_box(self, f"Choose file susscess: {json_file_path}")
    if optione1 == True:
        saveAndReplaceExcel(self, json_file_path)
    else:
        saveExcel(self, json_file_path)
        
        

def saveExcel(self, json_file_path):
    print ("save And Replace Excel option:")
    data_after_process =  processData(self, json_file_path)
    saveNewExcel(self, data_after_process, file_name,1)
    setDataCount(self)
    update_message_status_box(self, "Done Save Excel File")
    
    
def saveAndReplaceExcel(self, json_file_path):
    print ("save And Replace Excel option:")
    data_after_process =  processData(self, json_file_path)
    saveNewExcel(self, data_after_process, file_name,1)
    setDataCount(self)
    print ("Done processing")
    update_message_status_box(self, "Done Save And Replace Excel")
    
def processData(self, json_file_path):
    excelFilePatch = saveDataFromJsonToExcel(self, json_file_path)
    data_raw = readFileExcel(excelFilePatch)
    data_after_process  = processDataRawToRealData(data_raw)
    print ("Done processing")
    update_message_status_box(self, "Done processing data")
    return data_after_process
    
def saveDataFromJsonToExcel(self, json_file_path):
    data = pd.read_json(json_file_path)
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
    
    
    

    
