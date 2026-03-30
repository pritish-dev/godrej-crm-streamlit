import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
import pytz # Standard library for timezones
from services.sheets import get_df

def format_phone(num):
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10:
        return "91" + digits
    return digits

def get_sales_team_contacts():
    df = get_df("Sales Team")
    contacts = {}
    if df is not None and not df.empty:
        # Standardize columns to handle mixed case from Sheets
        df.columns = [c.strip().upper() for c in df.columns]
        for _, row in df.iterrows():
            name = str(row.get("NAME", "")).strip().lower()
            phone = format_phone(row.get("CONTACT NUMBER", ""))
            if name and phone:
                contacts[name] = phone
    return contacts

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/{phone}?text={encoded_msg}"

def get_delivery_alerts_list():
    """Returns a list of (phone, message) tuples for tomorrow's deliveries"""
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    
    # 1. FIX TIMEZONE: Force IST (India Standard Time)
    # This prevents the "Server is in UTC" bug
    IST = pytz.timezone('Asia/Kolkata')
    today = datetime.now(IST).date()
    target_date = today + timedelta(days=1) 
    
    alerts = []
    
    # 2. Clean Column Names
    df.columns = [c.strip().upper() for c in df.columns]
    date_col = "CUSTOMER DELIVERY DATE (TO BE)"
    
    if date_col not in df.columns:
        return []

    # 3. Process Rows
    for _, row in df.iterrows():
        raw_date = row.get(date_col)
        if pd.isna(raw_date) or str(raw_date).strip() == "":
            continue

        try:
            # Try multiple date formats to be safe
            delivery_date = pd.to_datetime(raw_date, dayfirst=True, errors='coerce').date()
        except:
            continue

        if pd.isna(delivery_date):
            continue

        # 4. The Logic Check
        remarks = str(row.get("DELIVERY REMARKS", "")).strip().upper()
        
        # Check if Date matches Tomorrow AND Remarks is Pending
        if delivery_date == target_date and remarks == "PENDING":
            customer = row.get("CUSTOMER NAME", "Customer")
            product = row.get("PRODUCT NAME", "Godrej Product")
            order_no = row.get("ORDER NO", "N/A")
            
            msg = f"🚚 *DELIVERY ALERT*\n\n*Customer:* {customer}\n*Product:* {product}\n*Order No:* {order_no}\n*Date:* {delivery_date.strftime('%d-%b-%Y')}\n\n⚠️ Scheduled for tomorrow. Please confirm transport!"
            
            # Identify Salesperson
            sp = str(row.get("SALES PERSON", "")).strip().lower()
            
            # Use a set to avoid duplicate messages to the same person
            targets = set()
            if sp in contacts: targets.add(contacts[sp])
            if "shaktiman" in contacts: targets.add(contacts["shaktiman"])
            if "pritish" in contacts: targets.add(contacts["pritish"])
            if "swati" in contacts: targets.add(contacts["swati"])

            for phone in targets:
                alerts.append((phone, msg))
                    
    return alerts

def get_payment_alerts_list():
    """Returns a list of (phone, message) tuples for payments due in 7 days"""
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    
    IST = pytz.timezone('Asia/Kolkata')
    target_date = datetime.now(IST).date() + timedelta(days=7)
    
    alerts = []
    df.columns = [c.strip().upper() for c in df.columns]

    for _, row in df.iterrows():
        try:
            raw_date = row.get("CUSTOMER DELIVERY DATE (TO BE)")
            d_date = pd.to_datetime(raw_date, dayfirst=True, errors='coerce').date()
        except: continue

        if d_date == target_date:
            try:
                # Cleaner numeric conversion
                order_amt = float(str(row.get("ORDER AMOUNT", 0)).replace(",","").replace("₹","").strip())
                adv = float(str(row.get("ADV RECEIVED", 0)).replace(",","").replace("₹","").strip())
                due = order_amt - adv
            except: due = 0

            if due > 0:
                msg = f"💰 *PAYMENT REMINDER*\n\n*Customer:* {row.get('CUSTOMER NAME')}\n*Due:* ₹{due:,.2f}\n*Delivery Date:* {d_date.strftime('%d-%b-%Y')}\n\n⚠️ Payment required before delivery!"
                
                sp = str(row.get("SALES PERSON")).strip().lower()
                targets = set()
                if sp in contacts: targets.add(contacts[sp])
                if "shaktiman" in contacts: targets.add(contacts["shaktiman"])
                if "pritish" in contacts: targets.add(contacts["pritish"])
                if "swati" in contacts: targets.add(contacts["swati"])

                for phone in targets:
                    alerts.append((phone, msg))
    return alerts