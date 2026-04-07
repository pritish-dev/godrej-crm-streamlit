import sys
import os
import urllib.parse
import pandas as pd
import streamlit as st

st.set_page_config(layout="wide") 

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.sheets import get_df, update_followup
from utils.helpers import standardize_columns, fix_duplicate_columns

# =========================================================
# FOLLOW-UP DATA
# =========================================================
@st.cache_data(ttl=60)
def load_followup_data():
    df = get_df("FOLLOWUP_LOG")
    if df is None or df.empty:
        return {}

    df = standardize_columns(df)
    return dict(zip(df["CUSTOMER NAME"], df["LAST_FOLLOWUP_DATE"]))

# =========================================================
# CONFIG
# =========================================================
PHONE_COL = "CONTACT NUMBER"
NAME_COL = "CUSTOMER NAME"
AMOUNT_COL = "ORDER AMOUNT"
ITEM_COL = "PRODUCT NAME"
DATE_COL = "DATE"

# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=120)
def load_all_franchise_data():
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        return pd.DataFrame()

    config_df = standardize_columns(config_df)
    sheet_list = []

    if "FRANCHISE_SHEETS" in config_df.columns:
        sheet_list += config_df["FRANCHISE_SHEETS"].dropna().tolist()
    if "FOUR_S_SHEETS" in config_df.columns:
        sheet_list += config_df["FOUR_S_SHEETS"].dropna().tolist()

    sheet_list = list(set(sheet_list))
    all_dfs = []

    for sheet in sheet_list:
        df = get_df(sheet)
        if df is not None and not df.empty:
            df = standardize_columns(df)
            df = fix_duplicate_columns(df)
            df["SOURCE_SHEET"] = sheet
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True, sort=False)

# =========================================================
# EMPLOYEE DATA
# =========================================================
@st.cache_data(ttl=300)
def load_employee_data():
    df = get_df("Employee_Details")
    if df is None or df.empty:
        return set(), set()

    df = standardize_columns(df)
    emp_names = set(df["EMPLOYEE NAME"].astype(str).str.strip())
    emp_phones = set(df["CONTACT NUMBER"].astype(str).str[-10:])
    return emp_names, emp_phones

# =========================================================
# HELPERS
# =========================================================
def normalize_phones(phone):
    phones = str(phone).replace("/", ",").replace(";", ",").split(",")
    clean = []
    for p in phones:
        p = "".join(filter(str.isdigit, p))[-10:]
        if len(p) == 10:
            clean.append(p)
    return sorted(set(clean))

def clean_products(x):
    unique_items = list(dict.fromkeys(x.astype(str)))
    top_items = unique_items[:5]
    extra = len(unique_items) - 5
    text = ", ".join(top_items)
    if extra > 0:
        text += f" (+{extra} more)"
    return text

# =========================================================
# MERGE ORDERS
# =========================================================
def merge_duplicate_orders(df):
    df = df.copy()
    df[NAME_COL] = df[NAME_COL].astype(str).str.strip()
    df[AMOUNT_COL] = pd.to_numeric(df[AMOUNT_COL], errors="coerce").fillna(0)
    df["PHONE_LIST"] = df[PHONE_COL].apply(normalize_phones)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

    df["ORDER_KEY"] = df[NAME_COL] + "|" + df[AMOUNT_COL].astype(str)

    merged = df.groupby("ORDER_KEY").agg({
        NAME_COL: "first",
        AMOUNT_COL: "first",
        "PHONE_LIST": lambda x: sorted(set(sum(x, []))),
        ITEM_COL: clean_products,
        DATE_COL: lambda x: pd.to_datetime(x, errors="coerce").max()
    }).reset_index(drop=True)

    return merged

# =========================================================
# WHATSAPP (FIXED - DIRECT)
# =========================================================
def create_followup_message(name, days, products):
    return (
        f"Hi {name},\n\n"
        f"We noticed it’s been {int(days)} days since your last purchase with us 😊\n\n"
        f"We truly value your association with *Interio by Godrej Patia*.\n\n"
        f"Based on your past interest in:\n{products}\n\n"
        f"We would love to assist you with new arrivals and exclusive offers.\n\n"
        f"Best Wishes,\n"
        f"Team Interio by Godrej Patia\n"
        f"📍 Bhubaneswar\n"
        f"📞 9937423954"
    )

def generate_whatsapp_link(phone, message):
    if not phone:
        return None
    encoded_msg = urllib.parse.quote(message, safe='')
    return f"https://wa.me/91{phone}?text={encoded_msg}"

# =========================================================
# PAGINATION
# =========================================================
def paginate_df(df, page_size=10, key="pagination"):
    total_rows = len(df)
    total_pages = (total_rows // page_size) + (1 if total_rows % page_size else 0)
    if total_pages == 0:
        return df

    page = st.number_input(f"Page ({key})", 1, total_pages, 1, key=f"input_{key}")
    start = (page - 1) * page_size
    return df.iloc[start : start + page_size]

# =========================================================
# ANALYSIS
# =========================================================
def analyze_customers(df):
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    followup_map = load_followup_data()

    df = merge_duplicate_orders(df)
    df = df.explode("PHONE_LIST")
    df["PHONE_LIST"] = df["PHONE_LIST"].astype(str).replace('nan', None)

    emp_names, emp_phones = load_employee_data()
    df = df[~df[NAME_COL].isin(emp_names) & ~df["PHONE_LIST"].isin(emp_phones)]

    customer_summary = df.groupby(NAME_COL).agg(
        phone_list=("PHONE_LIST", lambda x: sorted(set(str(v) for v in x if pd.notna(v)))),
        total_orders=(NAME_COL, "count"),
        total_value=(AMOUNT_COL, "sum"),
        products_purchased=(ITEM_COL, "first"),
        last_purchase_date=(DATE_COL, lambda x: pd.to_datetime(x, errors='coerce').max())
    ).reset_index()

    today = pd.Timestamp.today().normalize()
    customer_summary["last_purchase_date"] = pd.to_datetime(customer_summary["last_purchase_date"])
    customer_summary["days_since_last_order"] = (today - customer_summary["last_purchase_date"]).dt.days
    customer_summary["last_followup_date"] = customer_summary[NAME_COL].map(lambda name: followup_map.get(name, "—"))

    def get_wa_link(row, index):
        try:
            plist = row["phone_list"]
            if len(plist) > index and row["days_since_last_order"] > 90:
                return generate_whatsapp_link(
                    plist[index],
                    create_followup_message(
                        row[NAME_COL],
                        row["days_since_last_order"],
                        row["products_purchased"]
                    )
                )
        except:
            return None

    customer_summary["WhatsApp"] = customer_summary.apply(lambda r: get_wa_link(r, 0), axis=1)
    customer_summary["Alt WhatsApp"] = customer_summary.apply(lambda r: get_wa_link(r, 1), axis=1)

    repeat_buyers = customer_summary[customer_summary["total_orders"] > 1]
    mvc = customer_summary[customer_summary["total_value"] > 500000]

    return repeat_buyers, mvc

# =========================================================
# TABLE UI (UNCHANGED)
# =========================================================
def render_customer_table(df):
    st.dataframe(
        df,
        column_config={
            "WhatsApp": st.column_config.LinkColumn("Primary Contact", display_text="💬 Message 1"),
            "Alt WhatsApp": st.column_config.LinkColumn("Secondary Contact", display_text="📲 Message 2"),
            "total_value": st.column_config.NumberColumn("Total Value", format="₹%d"),
            "last_followup_date": st.column_config.TextColumn("Last Follow-up"),
            "phone_list": None
        },
        hide_index=True,
        use_container_width=True,
        height=500
    )

# =========================================================
# MAIN
# =========================================================
crm_raw = load_all_franchise_data()
repeat_buyers_df, mvc_df = analyze_customers(crm_raw)

st.title("👥 Customer Intelligence Dashboard")

# 🔁 Repeat Buyers
st.subheader("🔁 Repeat Buyers")
if not repeat_buyers_df.empty:
    paged_repeat = paginate_df(
        repeat_buyers_df.sort_values(by="total_orders", ascending=False), 10, "repeat"
    )
    render_customer_table(paged_repeat)

    # ✅ Manual follow-up
    st.markdown("### ✅ Mark Follow-up Done")
    selected_customer = st.selectbox("Select Customer", paged_repeat[NAME_COL], key="r")
    if st.button("✔ Mark as Followed Up", key="rb"):
        update_followup(selected_customer, pd.Timestamp.today().strftime("%d-%B-%Y"))
        st.success(f"Updated {selected_customer}")

else:
    st.info("No repeat buyers found")

# 💎 MVC
st.subheader("💎 Most Valuable Customers (> ₹5L)")
if not mvc_df.empty:
    paged_mvc = paginate_df(
        mvc_df.sort_values(by="total_value", ascending=False), 10, "mvc"
    )
    render_customer_table(paged_mvc)

    # ✅ Manual follow-up
    st.markdown("### ✅ Mark Follow-up Done")
    selected_customer_mvc = st.selectbox("Select Customer", paged_mvc[NAME_COL], key="m")
    if st.button("✔ Mark as Followed Up", key="mb"):
        update_followup(selected_customer_mvc, pd.Timestamp.today().strftime("%d-%B-%Y"))
        st.success(f"Updated {selected_customer_mvc}")

else:
    st.info("No high value customers found")