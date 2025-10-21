import pandas as pd
total_case_map = {}


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
    return dataframes


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
