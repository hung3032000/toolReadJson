import argparse
from datetime import datetime
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd


REQUIRED_COLS = {"INV_NO", "INV_LOCL_AMT", "INV_TTL_LOCL_AMT"}


def _process_one_file(args: Tuple[str, float]) -> Optional[pd.DataFrame]:
    file_path, tolerance = args
    file_path = Path(file_path)
    out_frames: List[pd.DataFrame] = []

    try:
        xls = pd.ExcelFile(file_path)
    except Exception:
        return None

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet)
        except Exception:
            continue

        if not REQUIRED_COLS.issubset(df.columns):
            continue

        for col in ["INV_LOCL_AMT", "INV_TTL_LOCL_AMT"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        grp = (
            df.groupby("INV_NO", dropna=False)
            .agg(
                SUM_INV_LOCL_AMT=("INV_LOCL_AMT", "sum"),
                INV_TTL_LOCL_AMT=("INV_TTL_LOCL_AMT", "max"),
            )
            .reset_index()
        )

        grp["DIFF"] = grp["SUM_INV_LOCL_AMT"] - grp["INV_TTL_LOCL_AMT"]
        mismatch_inv = grp.loc[grp["DIFF"].abs() > tolerance, "INV_NO"]

        if mismatch_inv.empty:
            continue

        df_mismatch = df[df["INV_NO"].isin(mismatch_inv)].copy()
        df_mismatch["SOURCE_FILE"] = file_path.name
        df_mismatch["SOURCE_SHEET"] = sheet
        out_frames.append(df_mismatch)

    if not out_frames:
        return None

    valid_frames = [df for df in out_frames if not df.empty and not df.isna().all().all()]
    if not valid_frames:
        return None

    return pd.concat(valid_frames, ignore_index=True)


# ==========================================
# PUBLIC API: chỉ cần gọi hàm này là chạy xong
# ==========================================
def check_missmatch(
    input_folder: str = "./data",
    output_file: Optional[str] = None,
    tolerance: float = 0.01,
    workers: Optional[int] = None,
    return_dataframes: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Quét tất cả *.xlsx trong folder, scan mọi sheet để tìm INV_NO có:
      sum(INV_LOCL_AMT) != max(INV_TTL_LOCL_AMT) theo tolerance

    Output:
      - export Excel gồm 2 sheet: SUMMARY + DETAIL
    Return:
      - None nếu không có mismatch
      - dict {output_file, summary_df?, detail_df?} nếu có mismatch
    """
    input_folder = Path(input_folder)
    excel_files = sorted([p for p in input_folder.glob("*.xlsx") if not p.name.startswith("~$")])

    if not excel_files:
        return None

    workers = workers or max(1, (os.cpu_count() or 4) - 1)

    results: List[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        fut_map = {ex.submit(_process_one_file, (str(p), tolerance)): p for p in excel_files}
        for fut in as_completed(fut_map):
            df_part = fut.result()
            if df_part is not None and not df_part.empty:
                results.append(df_part)

    if not results:
        return None

    final_df = pd.concat(results, ignore_index=True)
    detail_df = final_df.copy()

    summary_df = (
        final_df.groupby("INV_NO", as_index=False)
        .agg({
            "INV_TTL_LOCL_AMT": "max",
            "INV_LOCL_AMT": "sum",
            "SOURCE_FILE": lambda x: ",".join(sorted(set(x))),
            "SOURCE_SHEET": lambda x: ",".join(sorted(set(x))),
        })
    )
    summary_df["DIFF"] = summary_df["INV_LOCL_AMT"] - summary_df["INV_TTL_LOCL_AMT"]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not output_file:
        output_file = f"invoice_mismatch_{ts}.xlsx"

    with pd.ExcelWriter(output_file) as writer:
        summary_df.to_excel(writer, sheet_name="SUMMARY", index=False)
        detail_df.to_excel(writer, sheet_name="DETAIL", index=False)

    if return_dataframes:
        return {"output_file": output_file, "summary_df": summary_df, "detail_df": detail_df}

    return {"output_file": output_file}


# (Optional) vẫn giữ CLI nếu muốn chạy terminal
def main():
    parser = argparse.ArgumentParser(description="Parallel scan Excel (*.xlsx) all sheets for invoice total mismatch.")
    parser.add_argument("--input", default="./data", help="Folder containing *.xlsx files")
    parser.add_argument("--output", default=None, help="Output Excel file")
    parser.add_argument("--tolerance", type=float, default=0.01, help="Numeric tolerance for mismatch")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel worker processes")
    args = parser.parse_args()

    result = check_missmatch(
        input_folder=args.input,
        output_file=args.output,
        tolerance=args.tolerance,
        workers=args.workers,
        return_dataframes=False,
    )

    if not result:
        print("✅ No mismatch invoice found.")
        return

    print(f"✅ DONE. Exported: {result['output_file']}")


if __name__ == "__main__":
    main()


# from check_invoice_mismatch import check_missmatch

# res = check_missmatch(input_folder="./data", tolerance=0.01)

# if res:
#     print("Exported:", res["output_file"])
# else:
#     print("No mismatch")

# res = check_missmatch("./data", return_dataframes=True)
# df_summary = res["summary_df"]
# df_detail = res["detail_df"]

