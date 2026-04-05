import urllib.parse
import pandas as pd
from datetime import datetime, timedelta

def clean_headers(df):
    df.columns = [c.strip().upper() for c in df.columns]
    return df

def generate_whatsapp_group_link(message):
    encoded_msg = urllib.parse.quote(message)
    return f"whatsapp://send?text={encoded_msg}"

def create_whatsapp_tabular_list(df_group, alert_type="delivery"):
    if alert_type == "delivery":
        header = "*DD | Customer | Products | OrderDate*\n"
    else:
        header = "*DD | Customer | Adv | Balance*\n"
        
    table_text = header + "------------------------------------------\n"
    
    for _, row in df_group.iterrows():
        dd = row["CUSTOMER DELIVERY DATE"].strftime('%d-%b') if pd.notnull(row["CUSTOMER DELIVERY DATE"]) else "N/A"
        cust = str(row["CUSTOMER NAME"])[:10]
        prods = str(row["PRODUCT NAME"])[:12]
        
        if alert_type == "delivery":
            od = row["DATE"].strftime('%d-%b') if pd.notnull(row["DATE"]) else "N/A"
            table_text += f"📅 {dd} | {cust} | {prods} | 📝 {od}\n"
        else:
            adv = int(row["ADV RECEIVED"]) if pd.notnull(row["ADV RECEIVED"]) else 0
            bal = int(row["PENDING AMOUNT"]) if pd.notnull(row["PENDING AMOUNT"]) else 0
            table_text += f"💰 {dd} | {cust} | ₹{adv} | *₹{bal}*\n"
    
    table_text += "------------------------------------------\n"
    return table_text

def get_alerts(df, team_df, alert_type="delivery"):
    if df is None or df.empty or team_df is None or team_df.empty:
        return []
    
    df = clean_headers(df)
    
    # Date Parsing
    df["CUSTOMER DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')

    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    
    # ---------- FILTER LOGIC ----------
    if alert_type == "delivery":
        # ✅ UPDATED COLUMN NAME
        mask = (df["REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
    else:
        df["ORDER AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors='coerce').fillna(0)
        df["ADV RECEIVED"] = pd.to_numeric(df["ADV RECEIVED"], errors='coerce').fillna(0)

        df["PENDING AMOUNT"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

        # ✅ FIXED LOGIC (ADV > 0 only)
        mask = (df["ADV RECEIVED"] > 0) & (df["PENDING AMOUNT"] > 0)

    # Only Tomorrow Records
    filtered_df = df[
        mask & (df["CUSTOMER DELIVERY DATE"].dt.date == tomorrow)
    ].dropna(subset=["CUSTOMER DELIVERY DATE"])
    
    if filtered_df.empty:
        return []

    # ---------- GROUPING ----------
    group_cols = [
        "CUSTOMER NAME",
        "CONTACT NUMBER",
        "SALES REP",
        "CUSTOMER DELIVERY DATE"
    ]

    if alert_type == "delivery":
        group_cols.append("DATE")
    
    grouped_df = filtered_df.groupby(group_cols, as_index=False).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum"
    })

    if alert_type == "payment":
        grouped_df["PENDING AMOUNT"] = grouped_df["ORDER AMOUNT"] - grouped_df["ADV RECEIVED"]

    alerts = []

    # ---------- MESSAGE CREATION ----------
    for sp_name, group in grouped_df.groupby("SALES REP"):
        table_content = create_whatsapp_tabular_list(group, alert_type)
        
        msg = (
            f"Attention Team & *{sp_name}*,\n\n"
            f"Pending {'Deliveries' if alert_type == 'delivery' else 'Payments'} scheduled for TOMORROW:\n\n"
            f"{table_content}\n"
            f"Please confirm once action is taken."
        )

        alerts.append((sp_name, msg))
                
    return alerts