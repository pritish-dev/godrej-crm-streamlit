import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")

if crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# CLEAN NUMERIC
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
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

# DELIVERY DATE
crm["DELIVERY DATE"] = pd.to_datetime(
    crm["CUSTOMER DELIVERY DATE (TO BE)"],
    format="%d-%m-%Y",
    errors="coerce"
)

# -----------------------------
# SORT
# -----------------------------
crm = crm.sort_values(by="DATE", ascending=False)

# -----------------------------
# FORMATTERS
# -----------------------------
def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return x

def format_money(x):
    return f"₹{x:,.0f}"

# -----------------------------
# SALES TEAM
# -----------------------------
sales_people = []

if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    sales_people = (
        team[team["ROLE"] == "SALES"]["NAME"]
        .dropna()
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

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
# TARGET VS ACHIEVEMENT
# -----------------------------
st.subheader("🎯 Target vs Achievement")

if "targets" not in st.session_state:
    st.session_state.targets = pd.DataFrame(columns=["Sales Person", "Target"])

col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target", min_value=0, step=50000)

# ADD TARGET
if st.button("Add / Update Target"):
    df = st.session_state.targets.copy()
    df = df[df["Sales Person"] != selected_sales]

    df = pd.concat([
        df,
        pd.DataFrame({"Sales Person": [selected_sales], "Target": [target_value]})
    ], ignore_index=True)

    st.session_state.targets = df

# -----------------------------
# ACHIEVEMENT LOGIC
# -----------------------------
today = datetime.today()
month_start = today.replace(day=1)

def calc_achievement(person):
    df = crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"].str.upper() == person)
    ]
    return df["ORDER AMOUNT"].sum()

def calc_days_to_target(person, target):
    df = crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"].str.upper() == person)
    ].sort_values("DATE")

    cum = df["ORDER AMOUNT"].cumsum()
    reached = df[cum >= target]

    if reached.empty:
        return None

    return (reached.iloc[0]["DATE"] - month_start).days

# BUILD TABLE
df_targets = st.session_state.targets.copy()

if not df_targets.empty:
    df_targets["Achievement"] = df_targets["Sales Person"].apply(calc_achievement)

    # CATEGORY SPLIT
    def category_split(person, cat):
        return crm[
            (crm["DATE"] >= month_start) &
            (crm["SALES PERSON"].str.upper() == person) &
            (crm["CATEGORY"].str.upper() == cat)
        ]["ORDER AMOUNT"].sum()

    df_targets["Home Furniture"] = df_targets["Sales Person"].apply(lambda x: category_split(x, "HOME FURNITURE"))
    df_targets["Home Storage"] = df_targets["Sales Person"].apply(lambda x: category_split(x, "HOME STORAGE"))

    # DAYS TO TARGET
    df_targets["Days"] = df_targets.apply(
        lambda r: calc_days_to_target(r["Sales Person"], r["Target"]),
        axis=1
    )

    # RANKING
    achieved = df_targets[df_targets["Achievement"] >= df_targets["Target"]]

    if not achieved.empty:
        if len(achieved) == len(df_targets):
            achieved = achieved.sort_values("Achievement", ascending=False)
        else:
            achieved = achieved.sort_values("Days")

        medals = ["🥇", "🥈", "🥉"]
        achieved["Rank"] = medals[:len(achieved)]

        df_targets = df_targets.merge(
            achieved[["Sales Person", "Rank"]],
            on="Sales Person",
            how="left"
        )

    # FORMAT
    for col in ["Target", "Achievement", "Home Furniture", "Home Storage"]:
        df_targets[col] = df_targets[col].apply(format_money)

    # HIGHLIGHT
    def highlight(row):
        ach = int(row["Achievement"].replace("₹", "").replace(",", ""))
        tar = int(row["Target"].replace("₹", "").replace(",", ""))
        if ach >= tar:
            return ["background-color:#dcfce7"] * len(row)
        return [""] * len(row)

    st.dataframe(df_targets.style.apply(highlight, axis=1), use_container_width=True)

# -----------------------------
# SALES FILTER
# -----------------------------
st.subheader("📈 Sales Filter")

col1, col2, col3 = st.columns(3)

with col1:
    sp_filter = st.selectbox("Sales Person", ["All"] + sales_people)

with col2:
    month_filter = st.selectbox("Month", ["All"] + list(range(1, 13)))

with col3:
    year_filter = st.selectbox("Year", ["All"] + sorted(crm["YEAR"].dropna().unique()))

df_f = crm.copy()

if sp_filter != "All":
    df_f = df_f[df_f["SALES PERSON"] == sp_filter]

if month_filter != "All":
    df_f = df_f[df_f["DATE"].dt.month == int(month_filter)]

if year_filter != "All":
    df_f = df_f[df_f["DATE"].dt.year == int(year_filter)]

df_f["MONTH"] = df_f["DATE"].dt.strftime("%b")

sales_summary = df_f.groupby(
    ["SALES PERSON", "MONTH"]
)["ORDER AMOUNT"].sum().reset_index()

sales_summary["ORDER AMOUNT"] = sales_summary["ORDER AMOUNT"].apply(format_money)

st.dataframe(sales_summary, use_container_width=True)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[
    crm["DELIVERY REMARKS"].str.upper() == "PENDING"
].sort_values("DELIVERY DATE")

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