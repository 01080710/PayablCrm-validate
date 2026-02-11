from cc_withdraw_crawler    import (download_davinci_cc_reports,
                                    download_payabl_reports)
from cc_withdraw_basiclogic import (reconcile_cc_refunds)
from cc_withdraw_larkapi    import (get_lark_token,
                                    files_in_folder,
                                    query_sheet_info,
                                    query_sheet_data,
                                    append_sheet)
from logger import get_logger
import pandas as pd


# 🟢 Init
logger = get_logger(service="cc_reconcile", stage="init")

# 🟢 Main
def main():
    # 1️⃣ Download Reports
    logger = get_logger(service="cc_reconcile", stage="download")
    logger.info("Start download reports...")
    payabl_cc = download_payabl_reports()
    logger.info(f"Download Payabl CC Report Finish ，Total: {len(payabl_cc)}")
    crm_cc    = download_davinci_cc_reports()
    logger.info(f"Download CRM CC Report Finish ，Total: {len(crm_cc)}")


    # 2️⃣ Reconcile  
    logger = get_logger(service="cc_reconcile", stage="reconcile")
    logger.info("Start reconcile...")
    mismatch_case = reconcile_cc_refunds(payabl_cc, crm_cc)
    logger.info(f"Reconcile Finish ，Total Mismatch Case: {len(mismatch_case)}")
    
    
    # 3️⃣ Connect Lark
    logger = get_logger(service="cc_reconcile", stage="lark")
    app_id       = "cli_a86751faa8f9d029"
    app_secret   = "TjZ5cprV3v3Y6Afj3UcZtea1qayrzpVn"
    folder_token = "YTrefncx7lsH06d36pFla0yMgre"
    access_token = get_lark_token(app_id, app_secret)
    logger.info(f"Connect Lark Finish")
    files        = files_in_folder(access_token, folder_token=folder_token)   
    file_items = files.get('data', {}).get('files', []) if files else []
    
    if not file_items:
        logger.error('The file list in the LarkFolder is empty. Please upload a file to create a LarkSheet first.')
        raise ValueError('此LarkFolder中沒有檔案，請先上傳一個檔案以建立LarkSheet')
    logger.info(f"Get file list in LarkFolder Finish")
    
    sheet_list = []    
    for f in file_items:
        sheet_name  = f.get('name')
        sheet_token = f.get('token')
        sheet_id = query_sheet_info(access_token,sheet_token)['sheet_id']
        logger.info(f"Found LarkSheet - Name: {sheet_name}, Token: {sheet_token}, Sheet ID: {sheet_id}")
        sheet_list.append({
                'sheet_name' : sheet_name,
                'sheet_token': sheet_token,
                'sheet_id': sheet_id
            })
        
    default_sheet = sheet_list[0]
    sheet_token ,sheet_id  = default_sheet['sheet_token'] ,default_sheet['sheet_id']
    logger.info('Start query existing data in LarkSheet...')
    data         = query_sheet_data(access_token, sheet_token, sheet_id)
    

    # 4️⃣ Upload
    if data and len(data) > 1:
        logger.info('Query existing data in LarkSheet Finish')
        columns ,datas = data[0] ,data[1:]
        df_uploaded = pd.DataFrame(datas, columns=columns)
        df_unique = df_uploaded.drop_duplicates(['Merchant Order', 'Deposit Order Number'])
        uploaded_keys = list(df_unique[['Merchant Order', 'Deposit Order Number']].itertuples(index=False, name=None))
        mismatch_case1 = mismatch_case[
            ~mismatch_case[['Merchant Order', 'Deposit Order Number']]
            .apply(tuple, axis=1)
            .isin(uploaded_keys)
            ]
        logger.info(f"Total unique keys in LarkSheet: {len(uploaded_keys)}, Total new mismatch cases to upload: {len(mismatch_case1)}")
        append_sheet(access_token, sheet_token, sheet_id, mismatch_case1.values.tolist(), row=2)    # only append data to row 2, header is already there
    else:
        logger.info('LarkSheet is empty, start uploading all data...')                              # Need to upload header first, then data                           
        append_sheet(access_token, sheet_token, sheet_id, [list(mismatch_case.columns)],  row=1)     
        append_sheet(access_token, sheet_token, sheet_id, mismatch_case.values.tolist(),  row=2)
    logger.info('Upload data to LarkSheet Finish')
    
main()