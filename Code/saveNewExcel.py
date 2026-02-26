import pandas as pd
from util import *


def saveNewExcel(self, dataframes, file_name, save_flag):
    # save_flag is kept for backward compatibility. Runtime is now replace-only.
    _ = save_flag
    try:
        with pd.ExcelWriter(file_name, engine="openpyxl", mode="w") as writer:
            for sheet_name, df in dataframes.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                update_message_status_box(self, f"Wrote '{sheet_name}' to new file")
        update_message_status_box(self, f"Saved Excel: {file_name}")
    except PermissionError:
        update_message_status_box(self, f"Cannot write to {file_name}. File may be open or no permission.")
    except Exception as e:
        update_message_status_box(self, f"Error saving Excel: {e}")