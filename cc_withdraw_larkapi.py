from logger import get_logger
import requests


logger = get_logger(service="cc_reconcile", stage="lark")

# Get token function 
def get_lark_token(app_id, app_secret):
    url = "https://open.larksuite.com/open-apis/auth/v3/app_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()["tenant_access_token"] 


# Query Spreadsheet Metadata
def query_sheet_info(access_token,sheet_token):
    url = f"https://open.larksuite.com/open-apis/sheets/v3/spreadsheets/{sheet_token}/sheets/query"
    
    headers = {
        "Authorization": f"Bearer {access_token}",  # 請替換成你的 access_token
        "Content-Type": "application/json; charset=utf-8"
    }
    
    response = requests.get(url, headers=headers)
    data = response.json()
    if data.get("code") == 0:
        spreadsheet_meta = data.get("data", {})
        return spreadsheet_meta['sheets'][0]
    else:
        raise Exception(f"取得 metadata 失敗: {data.get('msg')}")
    
    
# Query Files in Folder    
def files_in_folder(access_token, page_size=10, page_token=None, folder_token=None):
    """
    取得 Lark Drive 檔案清單
    
    Parameters:
        access_token (str): tenant_access_token 或 user_access_token
        page_size (int): 每頁筆數 (最大 200)
        page_token (str): 分頁用的 token (第一次呼叫可不填)
        folder_token (str): 資料夾 token (不填則列出使用者雲端空間)
    """

    url = "https://open.larksuite.com/open-apis/drive/v1/files"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    params = {
        "page_size": page_size
    }
    if page_token:
        params["page_token"] = page_token
    if folder_token:
        params["folder_token"] = folder_token

    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()

        if resp.status_code != 200:
            logger.error(f"❌ HTTP error: {resp.text}")
            return None
        if data.get("code", 0) != 0:
            logger.error(f"❌ API error: code={data.get('code')} msg={data.get('msg')}")
            return None
        logger.info("✅ Successfully retrieved file list from Lark Drive")
        return data

    except Exception as e:
        logger.error("❌ Exception occurred while retrieving file list from Lark Drive: " + str(e))
        return None
    

# Read Spreadsheet DataRow
def query_sheet_data(access_token,sheet_token,sheet_id):
    headers = {
        "Authorization": f"Bearer {access_token}",  # 請替換成你的 access_token
        "Content-Type": "application/json; charset=utf-8"
    }
    query_url  =  f'https://open.larksuite.com/open-apis/sheets/v2/spreadsheets/{sheet_token}/values_batch_get'
    
    # note : 1. max limit -> 10 MB  / 2. 100 per minute
    query_resp = requests.get(query_url,
                              headers=headers,
                              params={"ranges": sheet_id ,#data['data']['updates']['updatedRange'],  # data['data']['tableRange']
                                      "valueRenderOption": "ToString",
                                      "dateTimeRenderOption": "FormattedString" ,
                                    })
    query_data = query_resp.json()
    values = query_data.get("data", {}).get("valueRanges", [])[0].get("values", [])
    return values



# Create Spreadsheet
def create_sheet(access_token, folder_token,sheetname):
    url = "https://open.larksuite.com/open-apis/sheets/v3/spreadsheets"
    headers = {
        "Authorization": f"Bearer {access_token}",  # 請替換成你的 access_token
        "Content-Type": "application/json; charset=utf-8" 
    }
    
    payload = {
        "title": sheetname,
        "folder_token": folder_token  # 可選，若要指定資料夾
    }
    
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()
    
    if data.get("code") == 0:
        folder_meta = data.get("data", {})
        logger.info(f"Create New LarkSheet Sucess - Name: {sheetname}, Token: {folder_meta.get('token')}, Spreadsheet ID: {folder_meta.get('spreadsheet')}")
        return folder_meta
    else:
        raise Exception(f"取得 metadata 失敗: {data.get('msg')}")
    


# Append & Query Spreadsheet DataRow
def append_sheet(access_token ,sheet_token ,sheet_id ,datas ,row=2):
    headers = {
        "Authorization": f"Bearer {access_token}",  # 請替換成你的 access_token
        "Content-Type": "application/json; charset=utf-8"
    }
    append_url = f"https://open.larksuite.com/open-apis/sheets/v2/spreadsheets/{sheet_token}/values_append"
    query_url  =  f"https://open.larksuite.com/open-apis/sheets/v2/spreadsheets/{sheet_token}/values_batch_get"

    row_count = len(datas)
    col_count = len(datas[0]) if datas else 0
    def col_to_letter(n):
        result = ""
        while n > 0:
            n ,remainder = divmod(n-1,26)
            result = chr(65 + remainder) + result
        return result
    
    end_col = col_to_letter(col_count)
    range_str = f"{sheet_id}!A{row}:{end_col}{row_count+row}"
    logger.info(f"Append data to LarkSheet with range: {range_str}, rows: {row_count}, columns: {col_count}")
    
    ## Append data
    # note : 1. 5000rows & 100columns/per time  / 2. A single cell can't exceed 50,000 characters. 
    payload = {
        "valueRange": {
            "range": range_str,
            "values": datas
        }
    }
    try: 
        resp = requests.post(append_url,
                             headers=headers, 
                             json=payload) 
        data = resp.json() 
        if resp.status_code != 200: 
            logger.error(f"❌ HTTP error: {resp.text}")
            return None 
        if data.get("code", 0) != 0: 
            logger.error(f"❌ API error: code={data.get('code')} msg={data.get('msg')}")
            return None 
        logger.info("✅ Successfully appended data to LarkSheet")

        updated_range = data["data"]["updates"]["updatedRange"]

        # note : 1. max limit -> 10 MB  / 2. 100 per minute
        query_resp = requests.get(query_url,
                                  headers=headers,
                                  params={"ranges": updated_range,  # data['data']['tableRange']
                                          "valueRenderOption": "ToString",
                                          "dateTimeRenderOption": "FormattedString" ,
                                        })
        query_data = query_resp.json()
        values = query_data.get("data", {}).get("valueRanges", [])[0].get("values", []) 
        return values
        
    except Exception as e: 
        logger.error("❌ Exception occurred while appending data to LarkSheet: " + str(e))
        return None
    

