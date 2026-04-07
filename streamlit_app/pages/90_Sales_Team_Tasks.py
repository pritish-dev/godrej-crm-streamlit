import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, write_df
from services.automation import generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="Sales Team Tasks")

# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=60)
def load_tasks():
    df = get_df("SALES_TEAM_TASK")
    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [c.strip().upper() for c in df.columns]

    df["TASK DATE"] = pd.to_datetime(df["TASK DATE"], dayfirst=True, errors="coerce")
    df["STATUS"] = df["STATUS"].fillna("Pending")

    return df


# =========================================================
# SAVE BACK (MARK DONE)
# =========================================================
def update_task_status(df, index, status):
    df.loc[index, "STATUS"] = status
    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# =========================================================
# WHATSAPP MESSAGE
# =========================================================
def generate_task_message(df):
    msg = "*📋 Sales Team Tasks Update*\n\n"

    for _, row in df.iterrows():
        date = row["TASK DATE"].strftime("%d-%b") if pd.notnull(row["TASK DATE"]) else ""
        msg += f"📌 {date} | {row['TASK TITLE']} | {row['ASSIGNED TO']}\n"

    msg += "\nPlease update status."
    return msg


# =========================================================
# COLOR LOGIC
# =========================================================
def highlight_row(row):
    today = datetime.now().date()

    if row["STATUS"] == "Done":
        return ["background-color: #d4edda"] * len(row)  # Green

    if pd.notnull(row["TASK DATE"]) and row["TASK DATE"].date() < today:
        return ["background-color: #f8d7da"] * len(row)  # Red

    return ["background-color: #e6d6ff"] * len(row)  # Purple


# =========================================================
# MAIN
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df = load_tasks()

if df.empty:
    st.warning("No tasks found")
    st.stop()

today = datetime.now().date()

# =========================================================
# FILTERS
# =========================================================
st.subheader("📅 Filters")

col1, col2 = st.columns(2)

with col1:
    task_type = st.selectbox("Task Type", ["All", "Daily", "Weekly", "Monthly"])

with col2:
    assigned = st.selectbox("Assigned To", ["All"] + sorted(df["ASSIGNED TO"].dropna().unique()))

filtered_df = df.copy()

if task_type != "All":
    filtered_df = filtered_df[filtered_df["TASK TYPE"] == task_type]

if assigned != "All":
    filtered_df = filtered_df[filtered_df["ASSIGNED TO"] == assigned]


# =========================================================
# WHATSAPP ALERT BUTTON
# =========================================================
st.subheader("📲 Send Task Alert")

if st.button("🚀 Send Tasks to WhatsApp Group"):
    msg = generate_task_message(filtered_df)
    st.link_button("Send to Group", generate_whatsapp_group_link(msg))


# =========================================================
# TASK TABLE
# =========================================================
st.subheader("📌 Task List")

display_df = filtered_df.copy()

display_df["TASK DATE"] = display_df["TASK DATE"].dt.strftime("%d-%B-%Y")

styled_df = display_df.style.apply(highlight_row, axis=1)

st.dataframe(styled_df, use_container_width=True)


# =========================================================
# MARK DONE SECTION
# =========================================================
st.subheader("✅ Update Task Status")

task_index = st.selectbox(
    "Select Task",
    filtered_df.index,
    format_func=lambda x: f"{df.loc[x, 'TASK TITLE']} ({df.loc[x, 'ASSIGNED TO']})"
)

col1, col2 = st.columns(2)

with col1:
    if st.button("✔ Mark as Done"):
        update_task_status(df, task_index, "Done")
        st.success("Task marked as Done")

with col2:
    if st.button("🔄 Mark as Pending"):
        update_task_status(df, task_index, "Pending")
        st.warning("Task marked as Pending")