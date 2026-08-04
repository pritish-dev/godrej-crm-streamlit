import urllib.parse
import pandas as pd
from datetime import datetime, timedelta

from services.payment_utils import money_receipt_total, MONEY_RECEIPTS_COL


def clean_headers(df):
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def get_col(df, *possible_names):
    for name in possible_names:
        if name in df.columns:
            return name
    return None


def generate_whatsapp_group_link(message):
    """Opens WhatsApp native app (desktop or mobile) with a pre-filled message."""
    encoded_msg = urllib.parse.quote(message)
    return "whatsapp://send?text={}".format(encoded_msg)


def generate_whatsapp_web_link(message):
    """Opens WhatsApp Web in the browser with a pre-filled message."""
    encoded_msg = urllib.parse.quote(message)
    return "https://web.whatsapp.com/send?text={}".format(encoded_msg)


def create_whatsapp_tabular_list(df_group, alert_type, delivery_col, order_col, adv_col):

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
            table_text += "DD {} | {} | {} | {}\n".format(dd, cust, prods, od)
        else:
            adv = int(row[adv_col]) if pd.notnull(row[adv_col]) else 0
            bal = int(row["PENDING AMOUNT"]) if pd.notnull(row["PENDING AMOUNT"]) else 0
            table_text += "DD {} | {} | {} | {}\n".format(dd, cust, adv, bal)

    table_text += "------------------------------------------\n"
    return table_text


def get_alerts(df, team_df, alert_type="delivery"):
    if df is None or df.empty or team_df is None or team_df.empty:
        return []

    df = clean_headers(df)

    # Exclude free stock items from all alerts
    if "FREE STOCK" in df.columns:
        df = df[df["FREE STOCK"].astype(str).str.strip().str.upper() != "FREE STOCK"].copy()

    delivery_col = get_col(df, "DELIVERY DATE", "CUSTOMER DELIVERY DATE", "CUSTOMER DELIVERY DATE (TO BE)")
    order_col    = get_col(df, "ORDER DATE", "DATE")
    adv_col      = get_col(df, "ADV RECEIVED", "ADVANCE RECEIVED")
    # New 26-27 sheets use the verbose column name; old sheets use REMARKS / DELIVERY STATUS
    remarks_col  = get_col(df, "DELIVERY STATUS", "DELIVERY REMARKS(DELIVERED/PENDING) REMARK", "REMARKS")
    sales_col    = get_col(df, "SALES PERSON", "SALES REP")

    if not delivery_col or not order_col or not adv_col or not remarks_col or not sales_col:
        return []

    df[delivery_col] = pd.to_datetime(df[delivery_col], dayfirst=True, errors='coerce')
    df[order_col] = pd.to_datetime(df[order_col], dayfirst=True, errors='coerce')

    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    if alert_type == "delivery":
        mask = df[remarks_col].astype(str).str.upper().str.strip() == "PENDING"
    else:
        # Support both old ("ORDER AMOUNT") and new ("ORDER VALUE") column names
        order_amt_col = get_col(df, "ORDER AMOUNT", "ORDER VALUE",
                                "ORDER UNIT PRICE=(AFTER DISC + TAX)")
        if order_amt_col:
            df["ORDER AMOUNT"] = pd.to_numeric(df[order_amt_col], errors="coerce").fillna(0)
        else:
            df["ORDER AMOUNT"] = 0
        df[adv_col] = pd.to_numeric(df[adv_col], errors="coerce").fillna(0)

        # Balance money receipts (B2C Franchise app): credit MONEY RECEIPT AMT n
        # against the order value alongside the advance. Zero on sheets without
        # those columns, preserving the plain ORDER AMOUNT − advance behaviour.
        df[MONEY_RECEIPTS_COL] = money_receipt_total(df)

        df["PENDING AMOUNT"] = df["ORDER AMOUNT"] - df[adv_col] - df[MONEY_RECEIPTS_COL]
        mask = (df[adv_col] > 0) & (df["PENDING AMOUNT"] > 0)

    filtered_df = df[
        mask & (df[delivery_col].dt.date == tomorrow)
    ].dropna(subset=[delivery_col])

    if filtered_df.empty:
        return []

    group_cols = [
        "CUSTOMER NAME",
        "CONTACT NUMBER",
        sales_col,
        delivery_col
    ]

    if alert_type == "delivery":
        group_cols.append(order_col)

    agg_map = {
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum",
        adv_col: "sum",
    }
    if alert_type == "payment" and MONEY_RECEIPTS_COL in filtered_df.columns:
        agg_map[MONEY_RECEIPTS_COL] = "sum"

    grouped_df = filtered_df.groupby(group_cols, as_index=False).agg(agg_map)

    if alert_type == "payment":
        _mr = grouped_df[MONEY_RECEIPTS_COL] if MONEY_RECEIPTS_COL in grouped_df.columns else 0
        grouped_df["PENDING AMOUNT"] = grouped_df["ORDER AMOUNT"] - grouped_df[adv_col] - _mr

    alerts = []

    for sp_name, group in grouped_df.groupby(sales_col):
        table_content = create_whatsapp_tabular_list(group, alert_type, delivery_col, order_col, adv_col)

        msg = "Attention Team & *{}*,\n\nPending {} for tomorrow:\n\n{}\nPlease confirm.".format(
            sp_name,
            "Deliveries" if alert_type == "delivery" else "Payments",
            table_content
        )

        alerts.append((sp_name, msg))

    return alerts