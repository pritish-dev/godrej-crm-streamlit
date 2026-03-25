# services/automation.py

import time
import urllib.parse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from services.sheets import get_df, _get_spreadsheet


# ---------------- LOAD CONTACTS ---------------- #

def get_contacts():
    df = get_df("Sales Team")

    contacts = {}
    manager = None
    owner = None

    for _, row in df.iterrows():
        name = str(row.get("Name", "")).strip()
        role = str(row.get("Role", "")).strip().lower()
        phone = str(row.get("Phone", "")).strip()

        if not name or not phone:
            continue

        contacts[name] = phone

        if role == "manager":
            manager = phone
        elif role == "owner":
            owner = phone

    return contacts, manager, owner


# ---------------- DRIVER ---------------- #

def start_driver():
    options = Options()
    options.add_argument("--user-data-dir=./chrome-data")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")

    driver = webdriver.Chrome(options=options)
    driver.get("https://web.whatsapp.com")

    time.sleep(15)  # QR login first time

    return driver


# ---------------- SEND MESSAGE ---------------- #

def send_message(driver, phone, message):
    try:
        encoded = urllib.parse.quote(message)
        url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded}"

        driver.get(url)
        time.sleep(8)

        send_btn = driver.find_element(By.XPATH, '//span[@data-icon="send"]')
        send_btn.click()

        time.sleep(3)
        return True

    except Exception as e:
        print("Error:", e)
        return False


# ---------------- DELIVERY ALERT ---------------- #

def send_delivery_alerts():
    df = get_df("CRM")

    contacts, manager, owner = get_contacts()

    if df.empty:
        return "No data"

    driver = start_driver()
    today = datetime.today().date()

    count = 0

    for _, row in df.iterrows():
        try:
            delivery_date = datetime.strptime(
                row.get("CUSTOMER DELIVERY DATE (TO BE)", ""), "%d-%m-%Y"
            ).date()

            if (delivery_date - today).days == 1 and row.get("DELIVERY REMARKS", "").lower() == "pending":

                sp = row.get("SALES PERSON", "").strip()
                phone = contacts.get(sp, manager)

                msg = f"""
🚚 DELIVERY ALERT (Tomorrow)

Customer: {row.get('CUSTOMER NAME')}
Product: {row.get('PRODUCT NAME')}
Delivery Date: {row.get('CUSTOMER DELIVERY DATE (TO BE)')}
"""

                send_message(driver, phone, msg)
                send_message(driver, manager, msg)
                send_message(driver, owner, msg)

                count += 1

        except:
            continue

    driver.quit()
    return f"{count} alerts sent"


# ---------------- PAYMENT ALERT ---------------- #

def send_payment_alerts():
    df = get_df("CRM")
    contacts, manager, owner = get_contacts()

    driver = start_driver()
    today = datetime.today().date()

    count = 0

    for _, row in df.iterrows():
        try:
            delivery_date = datetime.strptime(
                row.get("CUSTOMER DELIVERY DATE (TO BE)", ""), "%d-%m-%Y"
            ).date()

            order_amt = float(row.get("ORDER AMOUNT", 0))
            adv = float(row.get("ADV RECEIVED", 0))

            due = order_amt - adv

            if (delivery_date - today).days == 7 and due > 0:

                sp = row.get("SALES PERSON", "").strip()
                phone = contacts.get(sp, manager)

                msg = f"""
💰 PAYMENT DUE ALERT

Customer: {row.get('CUSTOMER NAME')}
Order: ₹{order_amt}
Advance: ₹{adv}
Due: ₹{due}

Delivery: {row.get('CUSTOMER DELIVERY DATE (TO BE)')}
"""

                send_message(driver, phone, msg)
                send_message(driver, manager, msg)
                send_message(driver, owner, msg)

                count += 1

        except:
            continue

    driver.quit()
    return f"{count} payment alerts sent"