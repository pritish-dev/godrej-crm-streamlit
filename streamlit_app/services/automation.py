import urllib.parse
import pandas as pd
from datetime import datetime, timedelta

def format_phone(num):
    if not num: return ""
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10: return "91" + digits
    return digits

def clean_headers(df):
    df.columns = [c.strip().upper() for c in df.columns]
    return df

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_msg}"

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
    if df is None or df.empty or team_df is None or team_df.empty: return []
    
    df = clean_headers(df)
    team_df = clean_headers(team_df)
    
    # Identify Owner and Manager from Sheet
    owner_row = team_df[team_df["ROLE"].str.upper() == "OWNER"]
    mgr_row = team_df[team_df["ROLE"].str.upper() == "MANAGER"]
    
    OWNER_PHONE = format_phone(owner_row["CONTACT NUMBER"].values[0]) if not owner_row.empty else ""
    MGR_PHONE = format_phone(mgr_row["CONTACT NUMBER"].values[0]) if not mgr_row.empty else ""

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

    filtered_df = df[mask & (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date <= tomorrow)].dropna(subset=["CUSTOMER DELIVERY DATE (TO BE)"])
    
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

    # Contacts Mapping for SPs
    sp_contacts = {str(r["NAME"]).strip().lower(): format_phone(r["CONTACT NUMBER"]) 
                   for _, r in team_df.iterrows()}

    alerts = []
    for sp_name, group in grouped_df.groupby("SALES PERSON"):
        sp_phone = sp_contacts.get(str(sp_name).strip().lower())
        table_content = create_whatsapp_tabular_list(group, alert_type)
        
        msg = (f"Dear *{sp_name}*,\n\n"
               f"Pending {'Deliveries' if alert_type == 'delivery' else 'Payments'}:\n\n"
               f"{table_content}\nAction required!")

        # Dynamic recipients
        recipients = [(f"SP: {sp_name}", sp_phone), ("Manager", MGR_PHONE), ("Owner", OWNER_PHONE)]
        for label, phone in recipients:
            if phone: alerts.append((label, phone, msg))
                
    return alerts