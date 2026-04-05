import urllib.parse
import pandas as pd
from datetime import datetime, timedelta

def clean_headers(df):
    df.columns = [c.strip().upper() for c in df.columns]
    return df

# ✅ HELPER: Safe column getter
def get_col(df, *possible_names):
    for name in possible_names:
        if name in df.columns:
            return name
    return None

def generate_whatsapp_group_link(message):
    encoded_msg = urllib.parse.quote(message)
    return f"whatsapp://send?text={encoded_msg}"

def create_whatsapp_tabular_list(df_group, alert_type="delivery",
                                 delivery_col, order_col, adv_col):
    
    if alert_type == "delivery":
        header = "*DD | Customer | Products | OrderDate*\n"
    else:
        header = "*DD | Customer | Adv | Balance*\n"
        
    table_text = header + "------------------------------------------\n"
    
    for _, row in df_group.iterrows():
        dd = row[delivery_col].strftime('%d-%b') if pd.notnull(row[delivery_col]) else "N/A"
        cust = str(row["CUSTOMER NAME"])[:10]
        prods = str(row["PRODUCT NAME"])[:12]
        
        if alert_type == "delivery":
            od = row[order_col].strftime('%d-%b') if pd.notnull(row[order_col]) else "N/A"
            table_text += f"📅 {dd} | {cust} | {prods} | 📝 {od}\n"
        else:
            adv = int(row[adv_col]) if pd.notnull(row[adv_col]) else 0
            bal = int(row["PENDING AMOUNT"]) if pd.notnull(row["PENDING AMOUNT"]) else 0
            table_text += f"💰 {dd} | {cust} | ₹{adv} | *₹{bal}*\n"
    
    table_text += "------------------------------------------\n"
    return table_text


def get_alerts(df, team_df, alert_type="delivery"):
    if df is None or df.empty or team_df is None or team_df.empty:
        return []
    
    df = clean_headers(df)

    # ✅ COLUMN MAPPING (Handles both RAW + RENAMED)
    delivery_col = get_col(df, "CUSTOMER DELIVERY DATE", "DELIVERY DATE")
    order_col = get_col(df, "DATE", "ORDER DATE")
    adv_col = get_col(df, "ADV RECEIVED", "ADVANCE RECEIVED")
    remarks_col = get_col(df, "REMARKS", "DELIVERY STATUS")
    sales_col = get_col(df, "SALES REP", "SALES PERSON")

    if not all([delivery_col, order_col, adv_col, remarks_col, sales_col]):
        return []

    # Parse Dates
    df[delivery_col] = pd.to_datetime(df[delivery_col], dayfirst=True, errors='coerce')
    df[order_col] = pd.to_datetime(df[order_col], dayfirst=True, errors='coerce')

    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    # ---------- FILTER ----------
    if alert_type == "delivery":
        mask = (df[remarks_col].astype(str).str.upper().str.strip() == "PENDING")
    else:
        df["ORDER AMOUNT"] = pd.to_numeric(df.get("ORDER AMOUNT"), errors='coerce').fillna(0)
        df[adv_col] = pd.to_numeric(df[adv_col], errors='coerce').fillna(0)

        df["PENDING AMOUNT"] = df["ORDER AMOUNT"] - df[adv_col]

        # ✅ ADV > 0 condition
        mask = (df[adv_col] > 0) & (df["PENDING AMOUNT"] > 0)

    filtered_df = df[
        mask & (df[delivery_col].dt.date == tomorrow)
    ].dropna(subset=[delivery_col])

    if filtered_df.empty:
        return []

    # ---------- GROUP ----------
    group_cols = [
        "CUSTOMER NAME",
        "CONTACT NUMBER",
        sales_col,
        delivery_col
    ]

    if alert_type == "delivery":
        group_cols.append(order_col)

    grouped_df = filtered_df.groupby(group_cols, as_index=False).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum",
        adv_col: "sum"
    })

    if alert_type == "payment":
        grouped_df["PENDING AMOUNT"] = grouped_df["ORDER AMOUNT"] - grouped_df[adv_col]

    alerts = []

    for sp_name, group in grouped_df.groupby(sales_col):
        table_content = create_whatsapp_tabular_list(
            group, alert_type,
            delivery_col, order_col, adv_col
        )
        
        msg = (
            f"Attention Team & *{sp_name}*,\n\n"
            f"Pending {'Deliveries' if alert_type == 'delivery' else 'Payments'} scheduled for TOMORROW:\n\n"
            f"{table_content}\n"
            f"Please confirm once action is taken."
        )

        alerts.append((sp_name, msg))

    return alerts