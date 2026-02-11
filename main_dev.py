from cc_withdraw_crawler import (
    download_davinci_cc_reports,
    download_payabl_reports,
)
from cc_withdraw_basiclogic import (reconcile_cc_refunds)
from cc_withdraw_larkapi import (get_lark_token,
                                 files_in_folder,
                                 query_sheet_info,
                                 query_sheet_data,
                                 append_sheet)
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import glob


# 2. combination of data from two sources and generate differences summary (using Pandas)   
def safe_concat(files):
    return pd.concat(
        [pd.read_csv(f, encoding='utf-8-sig', low_memory=False) for f in files],
        ignore_index=True
    ) if files else pd.DataFrame()

today = datetime.now(ZoneInfo('Asia/Taipei'))
RealtimeHour = today.strftime('%Y%m%d%H')
path = r'C:\Users\peter.chang\Desktop\2026\02\11\CRM&Payabl\cc_withdraw/'

counts = 0
files = glob.glob(f'{path}*.csv')
realtime_files = [f for f in files if RealtimeHour in f]
crm_files = [
    f for f in realtime_files
    if any(x in f for x in ('VFSC', 'VFSC2'))
]

payabl_files = [
    f for f in realtime_files
    if 'payabl' in f.lower()
]

if not crm_files:
    raise ValueError('找不到 VFSC / VFSC2 檔案')

if not payabl_files:
    raise ValueError('找不到 Payabl 檔案')
    
payabl_cc = safe_concat(payabl_files)
crm_cc    = safe_concat(crm_files)
mismatch_case = reconcile_cc_refunds(payabl_cc, crm_cc)


# 3. Feed the combined data into the comparison logic and export the final file
app_id       = "cli_a86751faa8f9d029"
app_secret   = "TjZ5cprV3v3Y6Afj3UcZtea1qayrzpVn"
folder_token = "YTrefncx7lsH06d36pFla0yMgre"
access_token = get_lark_token(app_id, app_secret)
files        = files_in_folder(access_token, folder_token=folder_token)   
file_items = files.get('data', {}).get('files', []) if files else []
if not file_items:
    raise ValueError('此LarkFolder中沒有檔案，請先上傳一個檔案以建立LarkSheet')

sheet_list = []    
for f in file_items:
    sheet_name  = f.get('name')
    sheet_token = f.get('token')
    sheet_id = query_sheet_info(access_token,sheet_token)['sheet_id']
    print(sheet_name ,sheet_token,sheet_id)
    sheet_list.append({
            'sheet_name' : sheet_name,
            'sheet_token': sheet_token,
            'sheet_id': sheet_id
        })
    
default_sheet = sheet_list[0]
sheet_token ,sheet_id  = default_sheet['sheet_token'] ,default_sheet['sheet_id']
data         = query_sheet_data(access_token, sheet_token, sheet_id)

if data and len(data) > 1:
    columns ,datas = data[0] ,data[1:]
    df_uploaded = pd.DataFrame(datas, columns=columns)
    df_unique = df_uploaded.drop_duplicates(['Merchant Order', 'Deposit Order Number'])
    uploaded_keys = list(df_unique[['Merchant Order', 'Deposit Order Number']].itertuples(index=False, name=None))
    mismatch_case1 = mismatch_case[
        ~mismatch_case[['Merchant Order', 'Deposit Order Number']]
        .apply(tuple, axis=1)
        .isin(uploaded_keys)
        ]
    print(f"關鍵唯一值總數量: {len(uploaded_keys)}, 尚未上傳數量: {len(mismatch_case1)}")
    append_sheet(access_token, sheet_token, sheet_id, mismatch_case1.values.tolist(), row=2)    # only append data to row 2, header is already there
else:
    print('LarkSheet 中沒有資料，開始上傳全部資料...')                                             # Need to upload header first, then data
    append_sheet(access_token, sheet_token, sheet_id, [list(mismatch_case.columns)],  row=1)     
    append_sheet(access_token, sheet_token, sheet_id, mismatch_case.values.tolist(),  row=2)