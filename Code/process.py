import pandas as pd
from processCaseInBrim import *
from saveNewExcel import *

def onFuncButtonClick(self,optione1):
    if optione1 == True:
        saveAndReplaceExcel(self)
    else:
        saveExcel(self)
        
        

def saveExcel(self):
    processData(self)
    print ("saveExcel")
    
    
def saveAndReplaceExcel(self):
    print ("saveAndReplaceExcel option:")
    processData(self)
    # setDataCount(self,10,9,1,1,1)
    print ("Done processing 2")
    
def processData(self):
    excelFilePatch = saveDataFromJsonToExcel(self)
    data_raw = readFileExcel(excelFilePatch)
    data_after_process  = processDataRawToRealData(data_raw)
    saveNewExcel(data_after_process, 'output.xlsx')
    print ("Done processing")
    
def saveDataFromJsonToExcel(self):
    json_file_path = 'res.json'
    data = pd.read_json(json_file_path)
    name = 'dataFromJsonToExcel'
    excel_file_path = name + '.xlsx'
    data.to_excel(excel_file_path, index=False, engine='openpyxl')
    self.statusText.setText(f"Excel file has been created: {excel_file_path}")
    return excel_file_path
    
def readFileExcel(excelFilePatch):
    excel_data = pd.read_excel(excelFilePatch)
    return excel_data



def setDataCount(self, groupCaseCount, splitCaseCount, splitManualCaseCount, supplementCaseCount, singleCaseCount):
    self.single_case_count.setText(str(singleCaseCount))
    self.split_case_count.setText(str(splitCaseCount))
    self.split_manual_case_count.setText(str(splitManualCaseCount))
    self.group_case_count.setText(str(groupCaseCount))
    self.supplement_case_count.setText(str(supplementCaseCount))
    
    
