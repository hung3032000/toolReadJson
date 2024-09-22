import pandas as pd
from openpyxl import load_workbook
import os

def get_default_columns_from_excel(file_name, sheet_name=None):
    # Đọc sheet đầu tiên hoặc sheet chỉ định để lấy danh sách cột
    if sheet_name:
        df = pd.read_excel(file_name, sheet_name=sheet_name, nrows=0)
    else:
        df = pd.read_excel(file_name, nrows=0)  # Đọc sheet đầu tiên với nrows=0 để chỉ lấy tên cột
    return df.columns.tolist()  # Trả về danh sách cột


def saveNewExcel(dataframes, file_name) :
    name = 'dataFromJsonToExcel'
    excel_file_path = name + '.xlsx'
    default_columns  = get_default_columns_from_excel(excel_file_path)
    
    with pd.ExcelWriter(file_name, engine='openpyxl') as writer:
        for sheet_name in dataframes:
            if dataframes[sheet_name].empty:
                dataframes[sheet_name] = pd.DataFrame(columns=default_columns)
                
            dataframes[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"Đã tạo file mới '{file_name}' và ghi dữ liệu vào sheet.")
        
        
    # try:
    #     if os.path.exists(file_name):
    #             # Mở file Excel
    #         book = load_workbook(file_name)
            
    #         # Lấy danh sách các sheet có trong workbook
    #         sheet_names = book.sheetnames
            
    #         # Lặp qua từng sheet để xử lý dữ liệu
    #         with pd.ExcelWriter(file_name, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
    #             for sheet_name in sheet_names:
    #                 # Đọc sheet hiện tại
    #                 existing_df = pd.read_excel(file_name, sheet_name=sheet_name)
                    
    #                 if sheet_name in dataframes:
    #                     # Gộp dữ liệu mới vào dữ liệu hiện tại
    #                     updated_df = pd.concat([existing_df, dataframes[sheet_name]], ignore_index=True)
                        
    #                     # Ghi lại toàn bộ dữ liệu (cũ + mới) vào sheet
    #                     updated_df.to_excel(writer, sheet_name=sheet_name, index=False)
    #                     print(f"Đã thêm dữ liệu mới vào sheet '{sheet_name}'.")
    #     else:
    #         # Tạo file mới và ghi dữ liệu
    #         with pd.ExcelWriter(file_name, engine='openpyxl') as writer:
    #             for sheet_name in dataframes:
    #                 dataframes[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False)
    #         print(f"Đã tạo file mới '{file_name}' và ghi dữ liệu vào sheet.")
    # except PermissionError:
    #     print(f"Không thể ghi vào file {file_name}. File có thể đang mở hoặc không có quyền ghi.")
    