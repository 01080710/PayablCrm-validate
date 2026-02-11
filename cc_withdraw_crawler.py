from requests.exceptions import RequestException
from datetime import datetime ,timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logger import get_logger
import requests ,time ,io ,os
from zoneinfo import ZoneInfo
from io import StringIO
import pandas as pd

   

# Function Conclusion
def extract_token(driver) -> tuple[dict,str]:
    cookies = {c['name']: c['value'] for c in driver.get_cookies()}
    token_resp = requests.get(
        'https://admin.vantagemarkets.com/davinci/token',
        cookies=cookies,
        headers={
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0'
        }
    )
    token = token_resp.text.strip()
    return cookies ,token


def build_api_session(token:str, cookies: dict) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        'authorization': f'Bearer {token}',
        'content-type': 'application/json;charset=UTF-8',
        'accept': 'application/json, text/plain, */*',
        'user-agent': 'Mozilla/5.0'
    })
    session.cookies.update(cookies)

    return session


def dayrange(DayRange: int = 2):
    today = datetime.now(ZoneInfo('Asia/Taipei')).date()
    return [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(DayRange-1, -1, -1)]


def build_output_path(base_dir, system, branch, brand, dt):
    y, m, d = dt.strftime('%Y'), dt.strftime('%m'), dt.strftime('%d')
    output_dir = os.path.join(base_dir, y, m, d, system, branch)
    os.makedirs(output_dir, exist_ok=True)

    return output_dir 


def export_csv(brand: str, 
               brand_dfs: list[pd.DataFrame], 
               out_dir: str = '.', 
               prefix: str | None = None, 
               tz: str = 'Asia/Taipei') -> str | None:
    """
    Concatenate list of DataFrames and write CSV. Returns written filepath or None if no data.
    """
    if not brand_dfs:
        return None
    final_df = pd.concat(brand_dfs, ignore_index=True)
    now = datetime.now(ZoneInfo(tz)).strftime('%Y%m%d%H%M%S')
    filename = f'{brand}_all_{now}.csv' if prefix is None else f'{prefix}_{brand}_all_{now}.csv'

    DATA_DIR = os.getenv("DATA_DIR", "/data") # Docker deployment method
    out_path = build_output_path(
        base_dir= DATA_DIR,#r'C:\Users\peter.chang\Desktop', # DATA_DIR,
        system='CRM&Payabl',
        branch='cc_withdraw',
        dt=datetime.now(ZoneInfo('Asia/Taipei')),
        brand=brand
        ) 
    final_df.to_csv(f'{out_path}/{filename}', index=False, encoding='utf-8-sig')
    
    return out_path


def login_and_get_token(account: str, 
                        password: str, 
                        setup_key: str, 
                        max_retry: int = 3) -> tuple[dict,str]:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import pyotp, hashlib, time, requests
    
    logger = get_logger(service="cc_reconcile", stage="download_davinci")
    # 🔧 Session + Retry 設定
    session = requests.Session()

    retry_strategy = Retry(
        total=max_retry,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
        raise_on_status=False
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "user-agent": "Mozilla/5.0",
    }

    # 🔐 TOTP
    try:
        totp = pyotp.TOTP(setup_key)
        totp_code = totp.now()
    except Exception as e:
        raise RuntimeError(f"TOTP 產生失敗: {e}")

    # 🔑 密碼 
    password_hash = hashlib.md5(password.encode()).hexdigest()

    data = {
        "userName_login": account,
        "password_login": password_hash,
        "twoFactorType": "googleAuth",
        "googleAuthTotp": totp_code,
    }
    
    # 🚪 登入
    try:
        response = session.post(
            "https://admin.vantagemarkets.com/login/to_login",
            data=data,
            headers=headers,
            allow_redirects=True,
            timeout=(10, 30),  # connect, read
        )
    except requests.RequestException as e:
        raise RuntimeError(f"登入請求失敗: {e}")


    # ✅ 登入成功判斷
    if response.status_code != 200:
        raise RuntimeError(f"登入 HTTP 失敗，status={response.status_code}")

    if len(session.cookies) == 0:
        raise RuntimeError("登入後未取得任何 cookie（可能驗證失敗）")

    if "login" in response.url.lower():
        raise RuntimeError("被導回登入頁，帳密或 TOTP 可能錯誤")
    
    logger.info("Login successful, cookies obtained")
    cookies = session.cookies.get_dict()

    # 🎟 取得 token
    token = None
    last_error = None

    for attempt in range(1, max_retry + 1):
        try:
            token_resp = session.get(
                "https://admin.vantagemarkets.com/davinci/token",
                headers={
                    "x-requested-with": "XMLHttpRequest",
                    "user-agent": "Mozilla/5.0",
                },
                timeout=(5, 15),
            )

            if token_resp.status_code != 200:
                raise RuntimeError(f"token HTTP {token_resp.status_code}")

            token = token_resp.text.strip()

            # expect：token 不應該是 HTML / 空值
            if not token or "<html" in token.lower():
                raise RuntimeError("token 回傳格式異常")

            break  
        except Exception as e:
            last_error = e
            logger.warning(f"Get token error ({attempt}/{max_retry}): {e}")
            time.sleep(2)
    if not token:
        raise RuntimeError(f"❌ 最終仍無法取得 token：{last_error}")
    
    logger.info("Token obtained successfully")
    return cookies, token





# Davinci_CC_Report
def download_davinci_cc_reports(brands   = ['ASIC','VFSC','VFSC2','FCA'], 
                                missions = ['Users','Client','Account','Reports','Task','System Setting']
                                ) -> pd.DataFrame | None:
    
    logger = get_logger(service="cc_reconcile", stage="download_davinci")
    MAX_RETRIES = 3
    RETRY_SLEEP = 5
    POST_TIMEOUT = 600
    GET_TIMEOUT = 600

    cookies, token = login_and_get_token(             #  Login and Get token
        account="Deposit OP",
        password="Asdf@1021Dec",
        setup_key="43LMDYGOANF4SWDX5JLNQ2FPICLFC3N3",
    )          
    session = build_api_session(token, cookies)       #  Session

    df_total: list[pd.DataFrame] = []
    for brand in brands[1:3]:
        logger.info(f"Start downloading Davinci CC Report for brand: {brand}...")
        brand_dfs = []

        for day in dayrange(4):
            json_data = {
                'regulator': brand.lower(),
                'sort': {},
                'filter': {},
                'sFilter': {},
                'from': day,
                'to': day,
                'accountType': 1,
                # 'withdrawStatus': ['7', '16', '17'], # Status: Completed ,Success ,Partial Success
                'withdrawStatus': [], # Status: all status
                'orderChannel': [],
                'levelId': '',
                'showAll': True,
            }

            headers = {
                'authorization': f'Bearer {token}',
                'accept': 'application/json, text/plain, */*',
                'content-type': 'application/json;charset=UTF-8',
                'user-agent': 'Mozilla/5.0',
            }

            filename = None

            # Step 1：POST generate file 
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    start_post = time.time()
                    response = session.post(
                        'https://report.vantagemarkets.com/api/cc-detail/download',
                        headers=headers,
                        cookies=cookies,
                        json=json_data,
                        timeout=POST_TIMEOUT
                    )
                    response.raise_for_status()
                    filename = response.json()['data']['file']
                    elapsed = round(time.time() - start_post, 1)
                    logger.info(f"POST success ({brand} {day}): {filename}, took {elapsed}s")
                    break
                except RequestException as e:
                    elapsed = round(time.time() - start_post, 1)
                    logger.warning(f"POST failed ({brand} {day}) attempt {attempt}: {e}, took {elapsed}s")
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_SLEEP)
                    else:
                        logger.error(f"POST failed after {MAX_RETRIES} attempts ({brand} {day})")

            if not filename:
                continue  # skip this day


            # Step 2：Download CSV 
            download_url = f'https://report.vantagemarkets.com/api/download/{filename}'

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    start_get = time.time()
                    response = session.get(
                        download_url,
                        headers=headers,
                        cookies=cookies,
                        stream=True,
                        timeout=GET_TIMEOUT
                    )
                    response.raise_for_status()

                    content = b''.join(response.iter_content(chunk_size=8192))
                    df = pd.read_csv(io.BytesIO(content))
                    brand_dfs.append(df)

                    elapsed = round(time.time() - start_get, 1)
                    logger.info(f"Download success ({brand} {day}): {filename}, took {elapsed}s")
                    break

                except RequestException as e:
                    elapsed = round(time.time() - start_get, 1)
                    logger.warning(f"Download failed ({brand} {day}) attempt {attempt}: {e}, took {elapsed}s")
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_SLEEP)
                    else:
                        logger.error(f"Download failed after {MAX_RETRIES} attempts ({brand} {day})")

        #  Export after all days 
        if brand_dfs:
            export_csv(brand, brand_dfs)
            df_total.extend(brand_dfs)
        logger.info(f"Finish downloading Davinci CC - {brand} Report")
            
    if not df_total:
        logger.warning("No data downloaded for any brand.")
        return None
    logger.info(f"Finish downloading Davinci CC Report for all brands, total rows: {sum(len(df) for df in df_total)}")
    return pd.concat(df_total, ignore_index=True)

# Payabl_WD_Report
def download_payabl_reports(max_retry: int = 5) -> pd.DataFrame | None:
    logger = get_logger(service="cc_reconcile", stage="download_payabl")
    json_data = {
        'username': 'ops_vantage_new',
        'password': 'Vantage@0902',
        'ui_access': 1,
    }

    session = requests.Session()
    response = session.post('https://portal.payabl.com/api/accounts/auth/login'
                            ,json=json_data 
                            ,timeout=300)
    
    retry_strategy = Retry(
        total=max_retry,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)

    for attempt in range(1, max_retry + 1):
        try:
            response = session.post(
                'https://portal.payabl.com/api/accounts/auth/login',
                json=json_data,
                timeout=(10, 30),
            )

            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            try:
                cookies = response.json()
            except ValueError:
                raise RuntimeError("回傳不是 JSON")

            if not cookies.get("refresh_token"):
                raise RuntimeError("未取得 refresh_token")
            logger.info("Payabl Login Success and Get Token Success")
            break  
        except Exception as e:
            logger.warning(f"Payabl Login Failed ({attempt}/{max_retry}): {e}")
            time.sleep(2)

    # Get New Token
    brand_dfs: list[pd.DataFrame] = []          
    for day in dayrange(2):
        logger.info(f"Start downloading Payabl CC Report for date: {day}...")
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'authorization': f'Backoffice {cookies["refresh_token"]}',
            'content-type': 'application/json',
            'origin': 'https://portal.payabl.com',
            'priority': 'u=1, i',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        }

        params = {
            'offset': '0',
            'limit': '5',
        }

        json_data = {
            'orderId': '',
            'dateFrom': day,
            'dateTo':   day,
            'datetimeFrom': f'{day}T00:00:00',
            'datetimeTo':   f'{day}T23:59:59',
            'transactionId': 0,
            'txLogParams': {
                'txcount': [
                    1,
                ],
            },
        }

        response = requests.post(
            'https://portal.payabl.com/api/backoffice/transactionLog_download',
            params=params,
            cookies=cookies,
            headers=headers,
            json=json_data,
        )
        df = pd.read_csv(StringIO(response.text) ,low_memory=False)
        df = (
            df#[['Date', 'Time', 'Order No.', 'Amount']]
                .assign(
                    Createtime=pd.to_datetime(
                        df['Date'] + ' ' + df['Time'],
                        format='%d.%m.%Y %H:%M:%S',
                        errors='coerce'
                    )
                )
                .drop(columns=['Date', 'Time'])
                # [['Createtime', 'Order No.', 'Amount']]
        )
        brand_dfs.append(df)
    if brand_dfs:
        export_csv('payabl', brand_dfs)
    final_df = pd.concat(brand_dfs, ignore_index=True)
    logger.info(f"Finish downloading Payabl CC Report")
    return final_df


