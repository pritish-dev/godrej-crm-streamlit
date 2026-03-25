import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

if crm is None or crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# CLEAN NUMERIC
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# -----------------------------
# CLEAN DATE
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")

crm["DELIVERY DATE"] = pd.to_datetime(
    crm["CUSTOMER DELIVERY DATE (TO BE)"],
    format="%d-%m-%Y",
    errors="coerce"
)

crm = crm.sort_values("DATE", ascending=False)

# -----------------------------
# SALES TEAM
# -----------------------------
sales_people = []

if team is not None and not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    sales_people = (
        team[team["ROLE"] == "SALES"]["NAME"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

# -----------------------------
# FORMATTERS
# -----------------------------
def format_money(x):
    return f"₹{x:,.0f}"

def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return ""

# -----------------------------
# ALL ORDERS
# -----------------------------
st.subheader("📋 All Orders (Till Date)")

display_cols = [
    "DATE", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "CATEGORY",
    "ORDER AMOUNT", "ADV RECEIVED",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

df_display = crm[display_cols].copy()
df_display["DATE"] = df_display["DATE"].apply(format_date)

st.dataframe(df_display, use_container_width=True)

# -----------------------------
# YEAR SUMMARY
# -----------------------------
st.subheader("📊 Year-wise Summary")

crm["YEAR"] = crm["DATE"].dt.year

summary = crm.groupby("YEAR").agg({
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "ORDER NO": "count"
}).reset_index()

summary["PENDING"] = summary["ORDER AMOUNT"] - summary["ADV RECEIVED"]

for col in ["ORDER AMOUNT", "ADV RECEIVED", "PENDING"]:
    summary[col] = summary[col].apply(format_money)

st.dataframe(summary, use_container_width=True)

# -----------------------------
# TARGETS SHEET FIX (CRITICAL)
# -----------------------------
required_cols = ["MONTH", "YEAR", "SALES PERSON", "TARGET"]

if targets_sheet is None or targets_sheet.empty or len(targets_sheet.columns) == 0:
    targets_sheet = pd.DataFrame(columns=required_cols)
else:
    targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]

    for col in required_cols:
        if col not in targets_sheet.columns:
            targets_sheet[col] = ""

    targets_sheet = targets_sheet[required_cols]

# CLEAN TARGET SHEET DATA
targets_sheet["MONTH"] = targets_sheet["MONTH"].astype(str).str.strip()
targets_sheet["YEAR"] = targets_sheet["YEAR"].astype(str).str.strip()
targets_sheet["SALES PERSON"] = targets_sheet["SALES PERSON"].astype(str).str.strip().str.upper()

# -----------------------------
# TARGET VS ACHIEVEMENT
# -----------------------------
st.subheader("🎯 Target vs Achievement")

today = datetime.today()
month = today.strftime("%B")
year = str(today.year)
month_start = today.replace(day=1)

targets_current = targets_sheet[
    (targets_sheet["MONTH"] == month) &
    (targets_sheet["YEAR"] == year)
]

# AUTO ADD SALES PERSONS
rows_to_add = []
for sp in sales_people:
    if sp not in targets_current["SALES PERSON"].values:
        rows_to_add.append({
            "MONTH": month,
            "YEAR": year,
            "SALES PERSON": sp,
            "TARGET": 0
        })

if rows_to_add:
    for r in rows_to_add:
        upsert_record("Targets",
            {
                "SALES PERSON": r["SALES PERSON"],
                "MONTH": r["MONTH"],
                "YEAR": r["YEAR"]
            },
            r
        )
    st.rerun()

# -----------------------------
# INPUT TARGET
# -----------------------------
col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target", min_value=0, step=50000)

if st.button("Update Target"):
    upsert_record("Targets",
        {
            "SALES PERSON": selected_sales,
            "MONTH": month,
            "YEAR": year
        },
        {
            "TARGET": target_value
        }
    )
    st.success("Target Updated")
    st.rerun()

# -----------------------------
# CALCULATIONS
# -----------------------------
def calc_achievement(person):
    df = crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"].str.upper() == person)
    ]
    return df["ORDER AMOUNT"].sum()

def category_split(person, cat):
    return crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"].str.upper() == person) &
        (crm["CATEGORY"].str.upper() == cat)
    ]["ORDER AMOUNT"].sum()

df_targets = targets_current.copy()

df_targets["ACHIEVEMENT"] = df_targets["SALES PERSON"].apply(calc_achievement)
df_targets["HOME FURNITURE"] = df_targets["SALES PERSON"].apply(lambda x: category_split(x, "HOME FURNITURE"))
df_targets["HOME STORAGE"] = df_targets["SALES PERSON"].apply(lambda x: category_split(x, "HOME STORAGE"))

# -----------------------------
# RANKING
# -----------------------------
df_targets = df_targets.sort_values("ACHIEVEMENT", ascending=False)

medals = ["🥇", "🥈", "🥉"]
df_targets["RANK"] = ""

for i in range(min(3, len(df_targets))):
    df_targets.iloc[i, df_targets.columns.get_loc("RANK")] = medals[i]

# -----------------------------
# FORMAT
# -----------------------------
for col in ["TARGET", "ACHIEVEMENT", "HOME FURNITURE", "HOME STORAGE"]:
    df_targets[col] = df_targets[col].apply(format_money)

df_targets["MONTH DISPLAY"] = month + " " + year

def highlight(row):
    ach = int(row["ACHIEVEMENT"].replace("₹", "").replace(",", ""))
    tar = int(row["TARGET"].replace("₹", "").replace(",", ""))
    if ach >= tar:
        return ["background-color:#dcfce7"] * len(row)
    return [""] * len(row)

st.dataframe(
    df_targets[
        ["MONTH DISPLAY", "SALES PERSON", "TARGET",
         "ACHIEVEMENT", "HOME FURNITURE",
         "HOME STORAGE", "RANK"]
    ].style.apply(highlight, axis=1),
    use_container_width=True
)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[
    crm["DELIVERY REMARKS"].astype(str).str.upper() == "PENDING"
]

pending = pending.sort_values("DELIVERY DATE")

pending["CUSTOMER DELIVERY DATE (TO BE)"] = pending["DELIVERY DATE"].apply(format_date)

st.dataframe(pending[display_cols], use_container_width=True)

if st.button("📲 Send Delivery Alerts"):
    send_delivery_alerts()
    st.success("Delivery Alerts Sent")

# -----------------------------
# PAYMENT DUE
# -----------------------------
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]

due = crm[crm["PENDING AMOUNT"] > 0]

due["PENDING AMOUNT"] = due["PENDING AMOUNT"].apply(format_money)

st.dataframe(due[[
    "CUSTOMER NAME",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "PENDING AMOUNT",
    "SALES PERSON"
]], use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    send_payment_alerts()
    st.success("Payment Alerts Sent")