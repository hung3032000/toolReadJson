import pandas as pd
total_case_map = {}
def processDataRawToRealData(data):
    # Init dataframes
    dataframes = {}

    # Get data from child func and put them into dataframes
    dataframes.update(splitManualCaseData(data))
    dataframes.update(splitCaseData(data))
    dataframes.update(groupCaseData(data))
    dataframes.update(supplementCaseData(data))
    dataframes.update(singleCase(data))

    # return
    return dataframes


def getCountOfCase():
    return total_case_map
    
def groupCaseData(data):
    # Group case: Find INV_NO with multiple ZZ_IF_ID and BL_SRC_NO
    grouped_data = data.groupby('INV_NO').agg({
        'ZZ_IF_ID': pd.Series.nunique, 
        'BL_SRC_NO': pd.Series.nunique
    }).reset_index()

    # Filter for INV_NO where both ZZ_IF_ID and BL_SRC_NO have more than one unique value
    group_case = grouped_data[(grouped_data['ZZ_IF_ID'] > 1) & (grouped_data['BL_SRC_NO'] > 1)]
    filtered_data  = data[data['INV_NO'].isin(group_case['INV_NO'])]
    total_case_map['group_case'] = filtered_data.shape[0]
    dataframes = {
        'group_case': pd.concat([filtered_data], ignore_index=True),
    }
    # Return the results
    return dataframes

def supplementCaseData(data):
    # Supplement case: Find INV_NO with multiple ZZ_IF_ID
    supplement_data = data.groupby(['INV_NO', 'BL_SRC_NO']).agg({
        'ZZ_IF_ID': pd.Series.nunique
    }).reset_index()
    supplement_case = supplement_data[(supplement_data['ZZ_IF_ID'] > 1)]
    
    filtered_data  = data[data['INV_NO'].isin(supplement_case['INV_NO'])]
    total_case_map['supplement_case'] = filtered_data.shape[0]
    dataframes = {
        'supplement_case': pd.concat([filtered_data], ignore_index=True),
    }
    return dataframes
    
def splitManualCaseData(data):
    # Split case: Find ZZ_IF_ID with multiple INV_NO
    split_data = data.groupby('ZZ_IF_ID').agg({
        'INV_NO': pd.Series.nunique, 
        'INV_CUST_CD': pd.Series.nunique
    }).reset_index()

    # Filter for ZZ_IF_ID where both INV_NO and INV_CUST_CD have more than one unique value
    split_case_manual = split_data[(split_data['INV_NO'] > 1)]
    filtered_data  = data[data['INV_NO'].isin(split_case_manual['INV_NO'])]
    total_case_map['split_case_manual'] = filtered_data.shape[0]
    dataframes = {
        'split_case_manual': pd.concat([filtered_data], ignore_index=True),
    }
    return dataframes



def splitCaseData(data):
    # Split case: Find ZZ_IF_ID with multiple INV_NO
    split_data = data.groupby('ZZ_IF_ID').agg({
        'INV_NO': pd.Series.nunique, 
        'INV_CUST_CD': pd.Series.nunique
    }).reset_index()
    # Split case: Find ZZ_IF_ID with multiple INV_NO and INV_CUST_CD
    # Filter for ZZ_IF_ID where both INV_NO and INV_CUST_CD have more than one unique value
    split_case = split_data[(split_data['INV_NO'] > 1) & (split_data['INV_CUST_CD'] > 1)]   
    filtered_data  = data[data['INV_NO'].isin(split_case['INV_NO'])]
    total_case_map['split_case'] = filtered_data.shape[0]
    dataframes = {
        'split_case': pd.concat([filtered_data], ignore_index=True),
    }
    return dataframes

def singleCase(data):
    # Single case: Find INV_NO with one ZZ_IF_ID
    single_case_data = data.groupby('INV_NO').agg({
        'ZZ_IF_ID': pd.Series.nunique
    }).reset_index()
    
    singleCase_data = single_case_data[(single_case_data['ZZ_IF_ID'] == 1)]
    filtered_data  = data[data['INV_NO'].isin(singleCase_data['INV_NO'])]
    total_case_map['single_case'] = filtered_data.shape[0]
    dataframes = {
        'single_case': pd.concat([filtered_data], ignore_index=True),
    }
    return dataframes


