import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
import pytz
from services.sheets import get_df

MY_NUMBER = "918867143707"

def format_phone(num):
    if not num: return ""
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10: return "91" + digits
    return digits

def clean_headers(df):
    df.columns = [c.strip().upper() for c in df.columns]
    return df

def create_whatsapp_table(df_group, type_label="DELIVERY"):
    table_text = f"*Pending {type_label.title()}s List:*\n"
    table_text += "--------------------------\n"
    
    grouped_cust = df_group.groupby(["CUSTOMER NAME", "CONTACT NUMBER"])
    
    for (cust_name, cust_phone), cust_data in grouped_cust:
        def clean_val(val):
            try:
                if pd.isna(val): return 0.0
                clean = str(val).replace('₹', '').replace(',', '').strip()
                return float(clean) if clean else 0.0
            except: return 0.0

        items_list = ", ".join(cust_data["PRODUCT NAME"].astype(str).unique())
        d_date = cust_data["CUSTOMER DELIVERY DATE (TO BE)"].min().strftime('%d-%b') if pd.notnull(cust_data["CUSTOMER DELIVERY DATE (TO BE)"].min()) else "N/A"
        order_amt = cust_data["ORDER AMOUNT"].apply(clean_val).sum()
        adv_rec = cust_data["ADV RECEIVED"].apply(clean_val).sum()
        due = order_amt - adv_rec
        
        table_text += f"👤 *Cust:* {cust_name}\n"
        table_text += f"📞 *Ph:* {cust_phone}\n"
        table_text += f"🛋️ *Items:* {items_list}\n"
        table_text += f"📅 *DD:* {d_date}\n"
        table_text += f"💰 *Due:* ₹{due:,.0f}\n"
        table_text += "--------------------------\n"
    return table_text

def get_delivery_alerts_list(is_test=False):
    df = get_df("CRM") 
    if df is None or df.empty: return []
    df = clean_headers(df)
    
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    
    if not is_test:
        df = df[df["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"]
    
    df = df.dropna(subset=["CUSTOMER DELIVERY DATE (TO BE)"])

    group_cols = ["CUSTOMER NAME", "CONTACT NUMBER", "CUSTOMER DELIVERY DATE (TO BE)"]
    df_grouped = df.groupby(group_cols, as_index=False).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique())
    })

    alerts = []
    for _, row in df_grouped.iterrows():
        name = row["CUSTOMER NAME"]
        phone = format_phone(row["CONTACT NUMBER"])
        prods = row["PRODUCT NAME"]
        d_str = row["CUSTOMER DELIVERY DATE (TO BE)"].strftime('%d-%b-%Y')
        
        msg = f"Hello {name}, your order for {prods} is scheduled for delivery on {d_str}. Kindly ensure someone is available."
        alerts.append((name, phone, msg))
    return alerts

def get_payment_alerts_list():
    df = get_df("CRM")
    team_df = get_df("Sales Team")
    df = clean_headers(df)
    
    contacts = {str(r.get("NAME", "")).strip().lower(): format_phone(r.get("CONTACT NUMBER", "")) 
                for _, r in team_df.iterrows()} if team_df is not None else {}

    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    
    # Filter only those with actual pending amounts
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    df = df[(df["ORDER AMOUNT"] - df["ADV RECEIVED"]) > 0].dropna(subset=["CUSTOMER DELIVERY DATE (TO BE)"])

    alerts = []
    for sp_name, group in df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group, type_label="PAYMENT")
        final_msg = f"💰 *PAYMENT REMINDER*\n\nHello {sp_name},\n\nGrouped payments due:\n\n{table_msg}"
        
        # Format: (Label, Phone, Message)
        rec_list = [
            (f"SP: {sp_name}", contacts.get(sp_name_clean)),
            ("Manager Shaktiman", contacts.get("shaktiman")),
            ("Swati (Admin)", format_phone(MY_NUMBER))
        ]
        for label, phone in rec_list:
            if phone: alerts.append((label, phone, final_msg))
    return alerts

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_msg}"