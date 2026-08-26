import numpy as np
import pandas as pd
total_case_map = {}

# Tên sheet tổng chứa toàn bộ dòng + các cột cờ CASE_* để kết hợp case tự do.
ALL_CASES_SHEET = "all_cases"

# Các cột cờ, đặt tên để hiển thị/tra cứu nhất quán ở UI và filter.
CASE_FLAG_COLUMNS = [
    "CASE_SPLIT",
    "CASE_SPLIT_MANUAL",
    "CASE_GROUP",
    "CASE_SUPPLEMENT",
    "CASE_SINGLE",
    "CASE_MERGE",
]


def processDataRawToRealData(data):
    data = _normalize_cols(data)

    dataframes = {}

    # TÍNH CÁC TẬP KEY TRƯỚC ĐỂ LOẠI CHÉO
    # split (ZZ_IF_ID có >1 INV_NO và >1 INV_CUST_CD)
    pairs = data[['ZZ_IF_ID','INV_NO']].drop_duplicates()
    inv_per_if = pairs.groupby('ZZ_IF_ID')['INV_NO'].nunique()
    cust_per_if = data.groupby('ZZ_IF_ID')['INV_CUST_CD'].nunique()
    split_keys = set(inv_per_if[(inv_per_if > 1) & (cust_per_if > 1)].index)

    # split manual (ZZ_IF_ID có >1 INV_NO)
    split_manual_keys = set(inv_per_if[inv_per_if > 1].index)

    # Lưu lại để các hàm dùng
    ctx = {
        "split_keys": split_keys,
        "split_manual_keys": split_manual_keys,
    }

    # TÍNH CÁC CASE
    dataframes.update(groupCaseData(data, ctx))
    dataframes.update(splitCaseData(data, ctx))
    dataframes.update(splitManualCaseData(data, ctx))
    dataframes.update(supplementCaseData(data, ctx))
    # dataframes.update(mergeCase(data, ctx))
    dataframes.update(singleCase(data, ctx))  # single tính SAU CÙNG, loại chéo

    # Sheet tổng: mỗi dòng gắn cờ thuộc case nào => kết hợp group/split/... tùy ý ở tab Filter.
    dataframes.update(caseFlagsSheet(data, ctx))
    return dataframes


def _case_key_sets(data, ctx):
    """Tính các tập khóa của từng case (khớp đúng logic 5 sheet hiện có)."""
    split_keys = set(ctx["split_keys"])
    split_manual_keys = set(ctx["split_manual_keys"])
    # split_manual sheet là phần "manual thuần" = có >1 INV_NO nhưng KHÔNG phải split
    manual_only_keys = split_manual_keys - split_keys

    # group: INV_NO có >1 ZZ_IF_ID VÀ >1 BL_SRC_NO
    g = data.groupby('INV_NO').agg(
        nif=('ZZ_IF_ID', 'nunique'),
        nbl=('BL_SRC_NO', 'nunique'),
    )
    group_inv_keys = set(g[(g['nif'] > 1) & (g['nbl'] > 1)].index)

    # supplement: cặp (INV_NO, BL_SRC_NO) có >1 ZZ_IF_ID
    s = data.groupby(['INV_NO', 'BL_SRC_NO']).agg(nif=('ZZ_IF_ID', 'nunique')).reset_index()
    supplement_pairs = set(
        map(tuple, s[s['nif'] > 1][['INV_NO', 'BL_SRC_NO']].itertuples(index=False, name=None))
    )

    # single: INV_NO chỉ 1 ZZ_IF_ID, và loại INV mà IF của nó thuộc split_manual (khớp singleCase)
    inv_if_n = data.groupby('INV_NO')['ZZ_IF_ID'].nunique()
    single_inv = set(inv_if_n[inv_if_n == 1].index)
    inv_if_first = data.groupby('INV_NO')['ZZ_IF_ID'].first()
    single_inv_keys = {inv for inv in single_inv if inv_if_first.get(inv) not in split_manual_keys}

    # merge (multi-currency): INV_NO có >1 INV_ISS_CURR_CD
    if 'INV_ISS_CURR_CD' in data.columns:
        m = data.groupby('INV_NO')['INV_ISS_CURR_CD'].nunique()
        merge_inv_keys = set(m[m > 1].index)
    else:
        merge_inv_keys = set()

    return {
        "split": split_keys,
        "manual_only": manual_only_keys,
        "group": group_inv_keys,
        "supplement": supplement_pairs,
        "single": single_inv_keys,
        "merge": merge_inv_keys,
    }


def caseFlagsSheet(data, ctx):
    """Sheet tổng: toàn bộ dòng + cột cờ 'Y'/'N' cho từng case + CASE_TAGS."""
    keys = _case_key_sets(data, ctx)
    out = data.drop_duplicates().reset_index(drop=True)

    def yn(mask):
        return np.where(np.asarray(mask), 'Y', 'N')

    supplement_index = pd.MultiIndex.from_arrays([out['INV_NO'], out['BL_SRC_NO']])

    out['CASE_SPLIT'] = yn(out['ZZ_IF_ID'].isin(keys["split"]))
    out['CASE_SPLIT_MANUAL'] = yn(out['ZZ_IF_ID'].isin(keys["manual_only"]))
    out['CASE_GROUP'] = yn(out['INV_NO'].isin(keys["group"]))
    out['CASE_SUPPLEMENT'] = yn(supplement_index.isin(keys["supplement"]))
    out['CASE_SINGLE'] = yn(out['INV_NO'].isin(keys["single"]))
    out['CASE_MERGE'] = yn(out['INV_NO'].isin(keys["merge"]))

    # CASE_TAGS: danh sách case (viết thường) mà dòng thuộc về, ngăn cách bằng ", " để dễ đọc/lọc LIKE.
    tag_names = {
        "CASE_SPLIT": "split",
        "CASE_SPLIT_MANUAL": "split_manual",
        "CASE_GROUP": "group",
        "CASE_SUPPLEMENT": "supplement",
        "CASE_SINGLE": "single",
        "CASE_MERGE": "merge",
    }
    tag_matrix = np.column_stack([out[col].to_numpy() == 'Y' for col in tag_names])
    names_arr = np.array(list(tag_names.values()))
    out['CASE_TAGS'] = [", ".join(names_arr[row]) for row in tag_matrix]

    total_case_map[ALL_CASES_SHEET] = out.shape[0]
    return {ALL_CASES_SHEET: out}


def getCountOfCase():
    return total_case_map

def _normalize_cols(df):
    out = df.copy()
    for c in ['ZZ_IF_ID', 'INV_NO', 'INV_CUST_CD', 'BL_SRC_NO']:
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip()
            out[c] = out[c].replace({'': None, 'nan': None, 'None': None})
    return out

import pandas as pd
total_case_map = {}

def splitCaseData(data, ctx):
    # dùng split_keys đã tính
    keys = pd.Index(list(ctx["split_keys"]))
    filtered = data[data['ZZ_IF_ID'].isin(keys)].drop_duplicates()
    total_case_map['split_case'] = filtered.shape[0]
    return {'split_case': pd.concat([filtered], ignore_index=True)}

def splitManualCaseData(data, ctx):
    # dùng split_manual_keys (bao gồm cả split)
    keys = pd.Index(list(ctx["split_manual_keys"]))
    # nếu muốn split và split_manual tách sheet, loại split ra khỏi manual:
    keys = keys.difference(pd.Index(list(ctx["split_keys"])))
    filtered = data[data['ZZ_IF_ID'].isin(keys)].drop_duplicates()
    total_case_map['split_case_manual'] = filtered.shape[0]
    return {'split_case_manual': pd.concat([filtered], ignore_index=True)}

def groupCaseData(data, ctx):
    g = data.groupby('INV_NO').agg(
        ZZ_IF_ID=('ZZ_IF_ID','nunique'),
        BL_SRC_NO=('BL_SRC_NO','nunique')
    ).reset_index()
    inv_keys = g[(g['ZZ_IF_ID']>1)&(g['BL_SRC_NO']>1)]['INV_NO']
    filtered = data[data['INV_NO'].isin(inv_keys)].drop_duplicates()
    total_case_map['group_case'] = filtered.shape[0]
    return {'group_case': pd.concat([filtered], ignore_index=True)}

def supplementCaseData(data, ctx):
    g = data.groupby(['INV_NO','BL_SRC_NO']).agg(
        ZZ_IF_ID=('ZZ_IF_ID','nunique')
    ).reset_index()
    k = g[g['ZZ_IF_ID']>1][['INV_NO','BL_SRC_NO']]
    filtered = data.merge(k, on=['INV_NO','BL_SRC_NO'], how='inner').drop_duplicates()
    total_case_map['supplement_case'] = filtered.shape[0]
    return {'supplement_case': pd.concat([filtered], ignore_index=True)}

def mergeCase(data, ctx):
    g = data.groupby('INV_NO').agg(
        INV_ISS_CURR_CD=('INV_ISS_CURR_CD','nunique')
    ).reset_index()
    inv_keys = g[g['INV_ISS_CURR_CD']>1]['INV_NO']
    filtered = data[data['INV_NO'].isin(inv_keys)].drop_duplicates()
    total_case_map['merge_case'] = filtered.shape[0]
    return {'merge_case': pd.concat([filtered], ignore_index=True)}

def singleCase(data, ctx):
    # single: mỗi INV_NO chỉ có 1 ZZ_IF_ID
    g = data.groupby('INV_NO').agg(ZZ_IF_ID=('ZZ_IF_ID','nunique')).reset_index()
    inv_keys = set(g[g['ZZ_IF_ID']==1]['INV_NO'])

    # LOẠI CHÉO: nếu INV thuộc ZZ_IF_ID nằm trong split hoặc split_manual → loại khỏi single
    bad_if = ctx["split_manual_keys"]  # đã bao gồm split
    # map INV_NO -> ZZ_IF_ID ở dữ liệu đã chuẩn hoá
    inv_to_if = data.groupby('INV_NO')['ZZ_IF_ID'].nunique()
    # Lấy chính xác mapping 1-1 (vì single đang là 1 IF)
    inv_if = data.groupby('INV_NO')['ZZ_IF_ID'].first()

    # inv bị loại: những INV có IF thuộc bad_if
    to_exclude = {inv for inv in inv_keys if inv_if.get(inv) in bad_if}

    inv_final = pd.Index(list(inv_keys - to_exclude))
    filtered = data[data['INV_NO'].isin(inv_final)].drop_duplicates()
    total_case_map['single_case'] = filtered.shape[0]
    return {'single_case': pd.concat([filtered], ignore_index=True)}
