import urllib.parse
import pandas as pd
from datetime import datetime, timedelta

def clean_headers(df):
    df.columns = [c.strip().upper() for c in df.columns]
    return df

def generate_whatsapp_group_link(message):
    """
    Uses the whatsapp:// URI scheme to open the Desktop App directly, bypassing browser tabs.
    Leaves the phone number blank so you can select a Group to forward the message to.
    """
    encoded_msg = urllib.parse.quote(message)
    return f"whatsapp://send?text={encoded_msg}"

def create_whatsapp_tabular_list(df_group, alert_type="delivery"):
    """Creates a clean text-based table for WhatsApp"""
    if alert_type == "delivery":
        header = "*DD | Customer | Products | OrderDate*\n"
    else:
        header = "*DD | Customer | Adv | Balance*\n"
        
    table_text = header + "------------------------------------------\n"
    
    for _, row in df_group.iterrows():
        dd = row["CUSTOMER DELIVERY DATE (TO BE)"].strftime('%d-%b')
        cust = str(row["CUSTOMER NAME"])[:10]
        prods = str(row["PRODUCT NAME"])[:12]
        
        if alert_type == "delivery":
            od = row["DATE"].strftime('%d-%b') if pd.notnull(row["DATE"]) else "N/A"
            table_text += f"📅 {dd} | {cust} | {prods} | 📝 {od}\n"
        else:
            adv = int(row["ADV RECEIVED"])
            bal = int(row["PENDING AMOUNT"])
            table_text += f"💰 {dd} | {cust} | ₹{adv} | *₹{bal}*\n"
    
    table_text += "------------------------------------------\n"
    return table_text

def get_alerts(df, team_df, alert_type="delivery"):
    """Generates one consolidated alert per Sales Person intended for a Group chat."""
    if df is None or df.empty or team_df is None or team_df.empty: return []
    
    df = clean_headers(df)
    
    # Dates for filtering
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    
    # Filter Logic
    if alert_type == "delivery":
        mask = (df["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
    else:
        df["PENDING AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors='coerce').fillna(0) - \
                               pd.to_numeric(df["ADV RECEIVED"], errors='coerce').fillna(0)
        mask = (df["PENDING AMOUNT"] > 0)

    # STRICT FILTER: Only include records where Delivery Date is exactly Tomorrow (1 day away)
    filtered_df = df[mask & (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == tomorrow)].dropna(subset=["CUSTOMER DELIVERY DATE (TO BE)"])
    
    if filtered_df.empty: return []

    # Grouping by Customer
    group_cols = ["CUSTOMER NAME", "CONTACT NUMBER", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)"]
    if alert_type == "delivery": group_cols.append("DATE")
    
    grouped_df = filtered_df.groupby(group_cols, as_index=False).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum", "ADV RECEIVED": "sum"
    })
    
    if alert_type == "payment":
        grouped_df["PENDING AMOUNT"] = grouped_df["ORDER AMOUNT"] - grouped_df["ADV RECEIVED"]

    alerts = []
    # Generate one message payload per Sales Person
    for sp_name, group in grouped_df.groupby("SALES PERSON"):
        table_content = create_whatsapp_tabular_list(group, alert_type)
        
        msg = (f"Attention Team & *{sp_name}*,\n\n"
               f"Pending {'Deliveries' if alert_type == 'delivery' else 'Payments'} scheduled for TOMORROW:\n\n"
               f"{table_content}\n"
               f"Please confirm to action taken.")

        # Return the SP name and the message payload
        alerts.append((sp_name, msg))
                
    return alerts