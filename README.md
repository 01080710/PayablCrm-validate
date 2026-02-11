# 📄 README – CC Reconcile Workflow

## 1️⃣ 專案概述

`cc_reconcile` 是一個用於 **信用卡退款對帳** 的自動化 ETL 流程，主要功能包括：

1. 從 **Payabl 系統**與 **CRM 系統**下載信用卡報表
2. 自動比對兩個系統的交易資料，找出 **退款差異（Mismatch Case）**
3. 將結果同步上傳到 **Lark Sheet** 方便內部查詢與追蹤

> 此流程完全自動化，可定期執行，並支援可觀測 JSON 格式 logging，方便監控每個流程階段。

---

## 2️⃣ 專案架構

```
./
├─ main.py                     # 主程式，控制 ETL 流程
├─ logger.py                   # 自訂 JSON Logger
├─ logs/                       # 儲放log資料夾
├─ cc_withdraw_crawler.py      # 負責下載報表
├─ cc_withdraw_basiclogic.py   # 對帳核心邏輯
├─ cc_withdraw_larkapi.py      # Lark API 封裝
├─ requirements.txt            # 所需套件
├─ crontab.txt                 # 時間排程器
├─ Dockerfile
├─ docker-compose.yml
```

---

## 3️⃣ 模組說明

| 模組                          | 功能                                                                    |
| --------------------------- | --------------------------------------------------------------------- |
| `logger.py`                 | 提供 JSON 格式 logging，支援 `service`、`stage`、`status`，可用於 ELK 或其他 log 監控系統 |
| `cc_withdraw_crawler.py`    | 下載報表：`download_payabl_reports()` 與 `download_davinci_cc_reports()`    |
| `cc_withdraw_basiclogic.py` | 核心對帳邏輯：`reconcile_cc_refunds(payabl, crm)`                            |
| `cc_withdraw_larkapi.py`    | 封裝 Lark API：登入、列出檔案、查詢 Sheet、上傳資料等                                    |
| `main.py`                   | 將所有模組串接起來，執行完整 ETL 流程                                                 |

---

## 4️⃣ 流程說明

整個流程可分為四個階段：

### 🔹 1. Download Reports

1. 下載 **Payabl CC 報表**
2. 下載 **CRM CC 報表**
3. Logging 範例：

```json
{
  "timestamp": "2026-02-11T12:00:00+0800",
  "level": "INFO",
  "logger": "etl_logger",
  "message": "Download Payabl CC Report Finish, Total: 1024",
  "service": "cc_reconcile",
  "stage": "download",
  "status": "ok"
}
```

### 🔹 2. Reconcile

1. 對比 Payabl 與 CRM 報表
2. 產生 `mismatch_case`，即未對帳成功的交易
3. Logging 範例：

```json
{
  "stage": "reconcile",
  "message": "Reconcile Finish, Total Mismatch Case: 23"
}
```

### 🔹 3. Connect Lark

1. 使用 `app_id` 與 `app_secret` 取得 **Lark Access Token**
2. 列出指定 Folder 中的所有 Sheet
3. Logging 範例：

```json
{
  "stage": "lark",
  "message": "Found LarkSheet - Name: RefundReport, Token: xxx, Sheet ID: 123"
}
```

### 🔹 4. Upload Data

1. 檢查 Sheet 是否已有資料
2. 只上傳 **未重複的 mismatch_case**
3. 若 Sheet 為空，先上傳 header 再上傳資料
4. Logging 範例：

```json
{
  "stage": "upload",
  "message": "Total unique keys in LarkSheet: 100, Total new mismatch cases to upload: 23"
}
```

---

## 5️⃣ Logging 設計

* 使用 `logger.py` 提供 **JSON Logger**
* 支援以下欄位：

  * `timestamp`：log 時間
  * `level`：INFO / WARNING / ERROR
  * `logger`：logger 名稱
  * `message`：主要訊息
  * `service`：服務名稱，例如 `cc_reconcile`
  * `stage`：流程階段，例如 download/reconcile/lark/upload
  * `status`：ok / error，可用於監控
* **建議做法**：所有 pandas 警告或 Exception 都捕捉後，透過 logger 輸出，避免污染 JSON log。

---

## 6️⃣ 注意事項

1. **DataFrame 操作**

   * 請使用 `.copy()` 避免 `SettingWithCopyWarning`
   * 避免使用 `applymap()`，改為 per-column `.dt.strftime()` 或 `.map()`

2. **Lark Sheet**

   * 須先上傳至少一個檔案建立 Sheet
   * 初次上傳時會包含 header

3. **Logging**

   * 建議開啟 `logging.captureWarnings(True)` 捕捉所有警告
   * 所有 warning 與 error 都會被 JSON log 捕捉，方便 ELK/監控分析

---

## 7️⃣ 流程示意圖

```
Download Reports
      │
      ▼
Reconcile Data
      │
      ▼
Connect Lark
      │
      ▼
Upload Mismatch Cases
      │
      ▼
Finish & Log
```

