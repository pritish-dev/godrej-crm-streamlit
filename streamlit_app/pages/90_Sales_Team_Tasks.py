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

    df.columns = [str(c).strip().upper() for c in df.columns]

    if "TASK DATE" in df.columns:
        df["START DATE"] = df["TASK DATE"]

    if "TASK ID" not in df.columns:
        df["TASK ID"] = df.index.astype(str)

    df["START DATE"] = pd.to_datetime(df["START DATE"], dayfirst=True, errors="coerce")
    df["LAST COMPLETED DATE"] = pd.to_datetime(df["LAST COMPLETED DATE"], dayfirst=True, errors="coerce")

    return df


# =========================================================
# DATE FORMAT
# =========================================================
def format_date(series):
    return pd.to_datetime(series).dt.strftime("%d-%B-%Y")


# =========================================================
# GENERATE MONTH TASKS
# =========================================================
def generate_month_tasks(df, year, month):
    rows = []

    for _, row in df.iterrows():
        freq = str(row["FREQUENCY"]).lower()
        start = row["START DATE"]

        if pd.isna(start):
            continue

        # loop days in month
        for day in range(1, 32):
            try:
                current = datetime(year, month, day)
            except:
                continue

            # DAILY
            if freq == "daily":
                pass

            # WEEKLY
            elif freq == "weekly":
                if current.weekday() != start.weekday():
                    continue

            # MONTHLY
            elif freq == "monthly":
                if current.day != start.day:
                    continue

            else:
                continue

            new_row = row.copy()
            new_row["DUE DATE"] = current
            rows.append(new_row)

    return pd.DataFrame(rows)


# =========================================================
# MARK DONE / UNDO
# =========================================================
def update_task_status(df, task_id, mark_done=True):
    if mark_done:
        df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = datetime.now().strftime("%d-%B-%Y")
    else:
        df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = ""

    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# =========================================================
# COLOR LOGIC
# =========================================================
def get_status(row):
    today = datetime.now().date()

    if pd.notnull(row["LAST COMPLETED DATE"]):
        return "🟢 Completed"

    if row["DUE DATE"].date() < today:
        return "🔴 Overdue"

    return "🟣 Pending"


# =========================================================
# MAIN
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

if df_master.empty:
    st.warning("No tasks found")
    st.stop()

# =========================================================
# MONTH SELECTOR
# =========================================================
today = datetime.now()

col1, col2 = st.columns(2)

with col1:
    year = st.selectbox("Select Year", [2024, 2025, 2026, 2027], index=2)

with col2:
    month = st.selectbox("Select Month", list(range(1, 13)), index=today.month - 1)

# Generate tasks
tasks = generate_month_tasks(df_master, year, month)

if tasks.empty:
    st.info("No tasks for selected month")
    st.stop()

tasks["STATUS"] = tasks.apply(get_status, axis=1)

tasks["DUE DATE"] = format_date(tasks["DUE DATE"])

# =========================================================
# SPLIT TASKS
# =========================================================
todo_df = tasks[tasks["STATUS"] != "🟢 Completed"].copy()
done_df = tasks[tasks["STATUS"] == "🟢 Completed"].copy()

# =========================================================
# TO DO SECTION
# =========================================================
st.subheader("🟣 To Do Tasks")

todo_df["DONE"] = False

edited_todo = st.data_editor(
    todo_df,
    use_container_width=True
)

# =========================================================
# COMPLETED SECTION
# =========================================================
st.subheader("🟢 Completed Tasks")

done_df["UNDO"] = False

edited_done = st.data_editor(
    done_df,
    use_container_width=True
)

# =========================================================
# HANDLE ACTIONS
# =========================================================
if "DONE" in edited_todo.columns:
    done_rows = edited_todo[edited_todo["DONE"] == True]

    if not done_rows.empty:
        for task_id in done_rows["TASK ID"]:
            update_task_status(df_master, task_id, True)

        st.success("Marked as Done")
        st.rerun()

if "UNDO" in edited_done.columns:
    undo_rows = edited_done[edited_done["UNDO"] == True]

    if not undo_rows.empty:
        for task_id in undo_rows["TASK ID"]:
            update_task_status(df_master, task_id, False)

        st.warning("Marked as Pending")
        st.rerun()

# =========================================================
# WHATSAPP ALERT
# =========================================================
st.divider()
st.subheader("📲 Send Monthly Task Summary")

if st.button("🚀 Send Tasks to WhatsApp"):
    msg = "*📋 Monthly Task Summary*\n\n"

    for _, row in tasks.iterrows():
        msg += f"{row['DUE DATE']} - {row['TASK TITLE']} ({row['STATUS']})\n"

    st.link_button("Send to Group", generate_whatsapp_group_link(msg))