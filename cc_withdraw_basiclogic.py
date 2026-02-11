from pandas.api.types import is_datetime64_any_dtype
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd



def data_prepare(payabl_cc: pd.DataFrame, crm_cc: pd.DataFrame):
    p_columns = ['Createtime','Tx-Id','Tx-Type','Order No.','Status','Currency','Amount']
    mask = payabl_cc['Order No.'].astype(str).str.startswith(('VU', 'V2U'))
    payabl_cc_audit = payabl_cc.loc[mask, p_columns]
    payabl_cc_audit = payabl_cc_audit.rename(
        columns={
            'Order No.': 'Deposit Order Number',
            'Amount'   : 'Refund Amount'
        }
    )
    df1 = payabl_cc_audit[payabl_cc_audit['Tx-Type'] == 'Refund']
    # ---------------------------------------------------------------------------------------------------------
    c_columns = ['User ID','Account','Merchant Order','Status','Order Channel',
                'Deposit Order Number','Refund Amount','Order Amount','Order Currency',
                'CC Last Update Time','Order Status','Order Fulfillment','CC Operator']
    crm_cc1 = crm_cc[c_columns]
    df2 = crm_cc1[(~(crm_cc1['CC Operator'] == 'System Auto')) & (crm_cc1['Order Status'] == 'Refunded')]

    return df1, df2


def data_buildlogic(df1, df2):
    inner = pd.merge(
            df1,
            df2,
            on='Deposit Order Number',
            how='inner',
            suffixes=('_payabl', '_crm'),
            sort=False   # 保留 df1 的順序
    )
    
    ONs = inner['Deposit Order Number'].drop_duplicates()  # 提取完全交集清冊
    
    
    ## 筆數稽核（count layer）
    payabl_count = (                                       
        df1['Deposit Order Number']                        # Payabl 出現次數
        .value_counts()
        .reindex(ONs, fill_value=0)
    )

    crm_count = (
        df2['Deposit Order Number']                        # CRM 出現次數
        .value_counts()
        .reindex(ONs, fill_value=0)
    )

    audit_df = pd.DataFrame({                              # Combine count layer result into audit_df
        'Deposit Order Number': ONs,
        'crm_count':    crm_count.values,
        'payabl_count': payabl_count.values
    })

    ## 金額稽核（amount layer）
    payabl_refund = (                                       
        df1
        .groupby('Deposit Order Number', as_index=False)
        .agg(Refund_Amount_payabl=('Refund Amount', 'sum'))
    )

    crm_refund = (
        df2
        .groupby('Deposit Order Number', as_index=False)
        .agg(Refund_Amount_crm=('Refund Amount', 'sum'))
    )

    audit_df = (
        audit_df
        .merge(crm_refund, on='Deposit Order Number', how='left')
        .merge(payabl_refund, on='Deposit Order Number', how='left')
    )
    # print('Audit DataFrame 數量: ' ,len(audit_df))
    return audit_df


def data_seperatecase(audit_df, df1, df2):
    same      = audit_df.query('crm_count == payabl_count')
    different = audit_df.query('crm_count != payabl_count')
    
    # ---------- Layer 1: single / Match | Mismatch ----------
    same_one  = same[(same['crm_count'] == 1)]   # 數量 == 1 -> 判斷比對成功or失敗
    df_single_ok       = same_one[((-same_one['Refund_Amount_payabl'])  == (same_one['Refund_Amount_crm']))]       # no issue  -> 1
    df_single_mismatch = same_one[~((-same_one['Refund_Amount_payabl']) == (same_one['Refund_Amount_crm']))]       # has issue -> 1
    
    
    # ---------- Layer 2: Multi / Match | Mismatch(Only Payabl, Only CRM) ----------
    same_more  = same[(same['crm_count'] > 1)]   # 數量 > 1 -> 判斷比對成功or失敗
    df_except = pd.concat([same_more,different]) # different + same_more
    columns = 'Deposit Order Number'
    dons = df_except[columns].unique()


    recon_mismatch_payabl_rows = []
    recon_mismatch_crm_rows = []
    recon_match_multi_ok_dons = []
    for i, don in enumerate(dons):
        # tidy up to float list
        list_payabl = df1.loc[df1['Deposit Order Number'] == don, 'Refund Amount'].astype(float).tolist()
        list_crm    = df2.loc[df2['Deposit Order Number'] == don, 'Order Amount'].astype(float).tolist()
        
        # create counter
        c1 = Counter(list_payabl)
        c2 = Counter(list_crm)
        
        # find c1 & c2 part of not match
        diff_1_not_in_2 = list((c1 - c2).elements())  # payabl MoreTime
        diff_2_not_in_1 = list((c2 - c1).elements())  # crm    MoreTime

        # filter df1 not-matched row
        df_payabl_diff = df1[(df1['Deposit Order Number'] == don) &
        (df1['Refund Amount'].isin(diff_1_not_in_2))
        ][['Deposit Order Number','Refund Amount']]
        
        # filter df2 not-matched row
        df_crm_diff = df2[(df2['Deposit Order Number'] == don) &
            (df2['Order Amount'].astype(float).isin(diff_2_not_in_1))
        ][['Merchant Order','Deposit Order Number','Refund Amount']]

        # result
        if df_payabl_diff.empty and df_crm_diff.empty:
            df_crm_match_ok = df2[
                df2['Deposit Order Number'] == don
            ][['Merchant Order','Deposit Order Number','Refund Amount']]
            recon_match_multi_ok_dons.append(df_crm_match_ok)
            
        if not df_payabl_diff.empty:
            recon_mismatch_payabl_rows.append(
                df_payabl_diff
            )
            
        if not df_crm_diff.empty:
            recon_mismatch_crm_rows.append(
                df_crm_diff
            )

    return {
        'single_ok': df_single_ok ,
        'single_mismatch': df_single_mismatch ,
        'multi_ok': pd.concat(recon_match_multi_ok_dons, ignore_index=True)
                            if recon_match_multi_ok_dons else pd.DataFrame() ,
        'payabl_mismatch': pd.concat(recon_mismatch_payabl_rows, ignore_index=True)
                            if recon_mismatch_payabl_rows else pd.DataFrame() ,
        'crm_mismatch': pd.concat(recon_mismatch_crm_rows, ignore_index=True)
                            if recon_mismatch_crm_rows else pd.DataFrame()
        }


def data_regular(df_single_ok ,df_multi_ok ,df_single_mismatch , df1 ,df2):
    columns = [
        'Createtime',
        'Tx-Id',
        'Tx-Type',
        'Status',
        'Merchant Order',
        'Deposit Order Number',
        'Currency',
        'Refund Amount',
        'Refund_Amount_crm'
    ]
    
    # 1.
    df_single_ok1 = df_single_ok.merge(
        df2[['Merchant Order','Deposit Order Number']],
        on=['Deposit Order Number'],
        how='left')

    df_single_final = df_single_ok1.merge(
        df1,
        on='Deposit Order Number',
        how='left'
    )[columns]



    # 2.
    df_multi_ok1 = df_multi_ok.merge(
        df2[['Merchant Order','Deposit Order Number','Refund Amount']],
        on=['Merchant Order','Deposit Order Number'],
        how='left'
    ).rename(columns={
        'Refund Amount_x': 'Refund Amount',
        'Refund Amount_y': 'Refund_Amount_crm'
    })

    cols_to_fill = [
        'Deposit Order Number',
        'Createtime',
        'Tx-Id',
        'Tx-Type',
        'Status',
        'Currency'
    ]

    df_multi_ok2 = df_multi_ok1.merge(
        df1[cols_to_fill],
        on='Deposit Order Number',
        how='left'
    )[columns]

    df_multi_final = df_multi_ok2.drop_duplicates(['Merchant Order', 'Deposit Order Number'])
    df_multi_final = df_multi_final.copy()
    df_multi_final['Refund Amount'] = -df_multi_final['Refund Amount']

    # 3.
    df_single_mismatch1 = df_single_mismatch.merge(
        df2[['Merchant Order','Deposit Order Number']],
        on=['Deposit Order Number'],
        how='left')

    df_single_mismatch_final = df_single_mismatch1.merge(
        df1,
        on='Deposit Order Number',
        how='left'
    )[columns]
    return df_single_final ,df_multi_final ,df_single_mismatch_final


def format_datetime_columns(df):
    for col in df.columns:
        if is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
    return df


def reconcile_cc_refunds(payabl_cc : pd.DataFrame 
                         ,crm_cc   : pd.DataFrame):
    
    df1 ,df2 = data_prepare(payabl_cc, crm_cc)              # Data Preparation
    audit_df = data_buildlogic(df1, df2)                    # Data Build Logic
    case = data_seperatecase(audit_df, df1, df2)            # Data Separate Case    
    (df_single_ok ,                                         # Data Case Result
     df_multi_ok ,
     df_single_mismatch ,
     df_recon_mismatch_payabl ,
     df_recon_mismatch_crm) = case['single_ok']  ,case['multi_ok'] ,case['single_mismatch'],case['payabl_mismatch'] ,case['crm_mismatch']
        
    (df_single_final,                                       # Data Shape To Regular 
     df_multi_final , 
     df_single_mismatch_final) = data_regular(df_single_ok ,df_multi_ok ,df_single_mismatch , df1 ,df2)   
    
    SRC_BOTH     = 'Payabl & Crm'
    SRC_PAYABL   = 'Payabl'
    SRC_CRM      = 'Crm'
    RES_MATCH    = 'Match'
    RES_MISMATCH = 'Mismatch'
    df_single_final['recon_result'] = RES_MATCH             # single match
    df_single_final['recon_source'] = SRC_BOTH
    df_multi_final['recon_result'] = RES_MATCH              # multi match
    df_multi_final['recon_source'] = SRC_BOTH
    df_single_mismatch_final['recon_result'] = RES_MISMATCH # single mismatch (Both have problem)
    df_single_mismatch_final['recon_source'] = SRC_BOTH
    df_recon_mismatch_payabl['recon_result'] = RES_MISMATCH # payabl mismatch
    df_recon_mismatch_payabl['recon_source'] = SRC_PAYABL
    df_recon_mismatch_crm['recon_result'] = RES_MISMATCH    # crm mismatch
    df_recon_mismatch_crm['recon_source'] = SRC_CRM
    
    df_final = pd.concat(
        [   df_single_final,
            df_multi_final,
            df_single_mismatch_final,
            df_recon_mismatch_payabl,
            df_recon_mismatch_crm
        ],
        ignore_index=True
    )
    
    
    df_final = df_final.astype(object).where(pd.notna(df_final), "")
    df_final['Comparison Time'] = datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
    df_final = df_final[(df_final['recon_result'] == "Mismatch")]
    df_final = format_datetime_columns(df_final)
    
    return df_final