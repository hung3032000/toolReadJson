import pandas as pd
from openpyxl import load_workbook
import os
from util import *

def saveNewExcel(self, dataframes, file_name, save_flag):
    """
    save_flag = 0 → append nếu file đã có
    save_flag = 1 → tạo file mới (replace)
    """
    file_exists = os.path.exists(file_name)

    try:
        # Nếu file có sẵn và không yêu cầu replace → append
        if file_exists and save_flag == 0:
            with pd.ExcelWriter(file_name, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
                for sheet_name, df in dataframes.items():
                    if sheet_name in writer.book.sheetnames:
                        # đọc sheet cũ
                        existing_df = pd.read_excel(file_name, sheet_name=sheet_name)
                        # gộp dữ liệu cũ + mới (lọc DF rỗng/toàn NaN để tránh FutureWarning)
                        frames = [d for d in [existing_df, df] if not d.empty and not d.isna().all().all()]
                        updated_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                        updated_df.to_excel(writer, sheet_name=sheet_name, index=False)
                        update_message_status_box(self, f"Appended data to '{sheet_name}'")
                    else:
                        # sheet chưa có → tạo mới
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                        update_message_status_box(self, f"Created new sheet '{sheet_name}'")
        else:
            # tạo file mới (mode='w' → không dùng if_sheet_exists)
            with pd.ExcelWriter(file_name, engine='openpyxl', mode='w') as writer:
                for sheet_name, df in dataframes.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    update_message_status_box(self, f"Wrote '{sheet_name}' to new file")
        update_message_status_box(self, f"✅ Saved Excel: {file_name}")

    except PermissionError:
        update_message_status_box(self, f"⚠️ Cannot write to {file_name}. File may be open or no permission.")
    except Exception as e:
        update_message_status_box(self, f"⚠️ Error saving Excel: {e}")
