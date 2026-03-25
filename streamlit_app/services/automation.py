# services/automation.py

import time
import pandas as pd
from datetime import datetime, timedelta
import webbrowser
from services.sheets import get_df

# -------------------------------
# FORMAT PHONE
# -------------------------------
def format_phone(num):
    num = str(num).strip()
    digits = "".join(filter(str.isdigit, num))
    if len(digits) == 10:
        return "91" + digits
    return digits

# -------------------------------
# GET SALES TEAM CONTACTS
# -------------------------------
def get_sales_team():
    df = get_df("Sales Team")

    contacts = {}

    for _, row in df.iterrows():
        name = str(row.get("Name", "")).strip()
        phone = format_phone(row.get("Contact Number", ""))

        if name and phone:
            contacts[name.lower()] = phone

    return contacts


# -------------------------------
# SEND WHATSAPP MESSAGE
# -------------------------------
def send_whatsapp(phone, message):
    url = f"https://web.whatsapp.com/send?phone={phone}&text={message}"
    webbrowser.open(url)
    time.sleep(20)  # wait for WhatsApp Web load

    import pyautogui
    pyautogui.press("enter")

    time.sleep(5)


# -------------------------------
# DELIVERY ALERTS (1 DAY BEFORE)
# -------------------------------
def send_delivery_alerts():
    df = get_df("CRM")
    contacts = get_sales_team()

    today = datetime.today().date()
    target_date = today + timedelta(days=1)

    sent = 0

    for _, row in df.iterrows():

        try:
            delivery_date = pd.to_datetime(
                row.get("CUSTOMER DELIVERY DATE (TO BE)"), 
                dayfirst=True, 
                errors="coerce"
            ).date()
        except:
            continue

        if pd.isna(delivery_date):
            continue

        if delivery_date == target_date and str(row.get("DELIVERY REMARKS")).lower() == "pending":

            customer = row.get("CUSTOMER NAME", "")
            product = row.get("PRODUCT NAME", "")
            order_no = row.get("ORDER NO", "")
            sales_person = str(row.get("SALES PERSON", "")).lower()

            message = f"""
🚚 DELIVERY ALERT

Customer: {customer}
Product: {product}
Order No: {order_no}
Delivery Date: {delivery_date}

⚠️ Delivery is scheduled tomorrow. Please plan accordingly.
"""

            # Send to Salesperson
            if sales_person in contacts:
                send_whatsapp(contacts[sales_person], message)

            # Send to Manager
            if "shaktiman" in contacts:
                send_whatsapp(contacts["shaktiman"], message)

            # Send to You
            if "pritish" in contacts:
                send_whatsapp(contacts["pritish"], message)

            sent += 1

    return f"✅ Delivery alerts sent: {sent}"


# -------------------------------
# PAYMENT DUE ALERTS (7 DAYS BEFORE)
# -------------------------------
def send_payment_alerts():
    df = get_df("CRM")
    contacts = get_sales_team()

    today = datetime.today().date()
    target_date = today + timedelta(days=7)

    sent = 0

    for _, row in df.iterrows():

        try:
            delivery_date = pd.to_datetime(
                row.get("CUSTOMER DELIVERY DATE (TO BE)"),
                dayfirst=True,
                errors="coerce"
            ).date()
        except:
            continue

        if pd.isna(delivery_date):
            continue

        if delivery_date == target_date:

            order_amt = float(row.get("ORDER AMOUNT", 0) or 0)
            adv = float(row.get("ADV RECEIVED", 0) or 0)
            due = order_amt - adv

            if due <= 0:
                continue

            customer = row.get("CUSTOMER NAME", "")
            sales_person = str(row.get("SALES PERSON", "")).lower()

            message = f"""
💰 PAYMENT REMINDER

Customer: {customer}
Order Amount: ₹{order_amt}
Advance Paid: ₹{adv}
Balance Due: ₹{due}

⚠️ Payment pending before delivery (in 7 days).
"""

            # Salesperson
            if sales_person in contacts:
                send_whatsapp(contacts[sales_person], message)

            # Manager
            if "shaktiman" in contacts:
                send_whatsapp(contacts["shaktiman"], message)

            # You
            if "pritish" in contacts:
                send_whatsapp(contacts["pritish"], message)

            sent += 1

    return f"✅ Payment alerts sent: {sent}"


# -------------------------------
# DAILY REPORT
# -------------------------------
def send_daily_report():
    df = get_df("CRM")
    contacts = get_sales_team()

    today = datetime.today().date()

    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce").dt.date

    today_df = df[df["DATE"] == today]

    total_sales = pd.to_numeric(today_df["ORDER AMOUNT"], errors="coerce").sum()
    total_orders = len(today_df)

    message = f"""
📊 DAILY SALES REPORT

Date: {today}

Orders: {total_orders}
Sales: ₹{total_sales}
"""

    if "pritish" in contacts:
        send_whatsapp(contacts["pritish"], message)

    if "shaktiman" in contacts:
        send_whatsapp(contacts["shaktiman"], message)

    return "✅ Daily report sent"