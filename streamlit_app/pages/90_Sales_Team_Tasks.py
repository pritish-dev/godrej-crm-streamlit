import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

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

    df["START DATE"] = pd.to_datetime(df["START DATE"], dayfirst=True, errors="coerce")
    df["LAST COMPLETED DATE"] = pd.to_datetime(df["LAST COMPLETED DATE"], dayfirst=True, errors="coerce")

    return df


# =========================================================
# RECURRING TASK ENGINE
# =========================================================
def generate_today_tasks(df):
    today = datetime.now().date()
    task_rows = []

    for _, row in df.iterrows():
        freq = str(row.get("FREQUENCY", "")).lower()
        start_date = row["START DATE"]

        if pd.isna(start_date):
            continue

        start_date = start_date.date()

        # DAILY
        if freq == "daily":
            due = today

        # WEEKLY
        elif freq == "weekly":
            if start_date.weekday() == today.weekday():
                due = today
            else:
                continue

        # MONTHLY
        elif freq == "monthly":
            if start_date.day == today.day:
                due = today
            else:
                continue
        else:
            continue

        last_done = row["LAST COMPLETED DATE"]
        if pd.notnull(last_done) and last_done.date() == today:
            continue

        new_row = row.copy()
        new_row["DUE DATE"] = due
        new_row["STATUS"] = "Pending"
        task_rows.append(new_row)

    return pd.DataFrame(task_rows)


# =========================================================
# UPDATE TASK STATUS
# =========================================================
def mark_task_done(df, task_id):
    today = datetime.now().strftime("%d-%m-%Y")

    df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = today
    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# =========================================================
# WHATSAPP MESSAGE
# =========================================================
def generate_task_message(df):
    msg = "*📋 Today's Task List*\n\n"

    for _, row in df.iterrows():
        msg += f"📌 {row['TASK TITLE']} | {row['ASSIGNED TO']}\n"

    msg += "\nPlease update status."
    return msg


# =========================================================
# COLOR LOGIC
# =========================================================
def get_status(row):
    today = datetime.now().date()

    if pd.notnull(row["LAST COMPLETED DATE"]):
        if row["LAST COMPLETED DATE"].date() == today:
            return "🟢 Done"

    if row["DUE DATE"] < today:
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

# Generate today's tasks
tasks_today = generate_today_tasks(df_master)

if tasks_today.empty:
    st.info("No tasks for today")
    st.stop()

# STATUS COLUMN
tasks_today["STATUS VIEW"] = tasks_today.apply(get_status, axis=1)

# DISPLAY
display_df = tasks_today.copy()

display_df["DUE DATE"] = pd.to_datetime(display_df["DUE DATE"]).dt.strftime("%d-%B-%Y")

# =========================================================
# WHATSAPP ALERT
# =========================================================
st.subheader("📲 Send Task Alert")

if st.button("🚀 Send Tasks to WhatsApp Group"):
    msg = generate_task_message(tasks_today)
    st.link_button("Send to Group", generate_whatsapp_group_link(msg))


# =========================================================
# TABLE WITH CHECKBOX
# =========================================================
st.subheader("📌 Today's Tasks")

display_df["DONE"] = False

edited_df = st.data_editor(
    display_df,
    use_container_width=True,
    disabled=["TASK ID", "TASK TITLE", "ASSIGNED TO", "STATUS VIEW"],
)

# =========================================================
# AUTO UPDATE ON CHECK
# =========================================================
done_tasks = edited_df[edited_df["DONE"] == True]

if not done_tasks.empty:
    for task_id in done_tasks["TASK ID"]:
        mark_task_done(df_master, task_id)

    st.success("Tasks updated successfully!")
    st.rerun()


# =========================================================
# ASSIGN TASK UI
# =========================================================
st.divider()
st.subheader("➕ Create New Task")

with st.form("task_form"):

    task_title = st.text_input("Task Title")

    task_type = st.selectbox("Task Type", ["Daily", "Weekly", "Monthly"])

    assigned_to = st.text_input("Assign To (comma separated)")

    start_date = st.date_input("Start Date")

    submitted = st.form_submit_button("Create Task")

    if submitted:
        new_task = pd.DataFrame({
            "TASK ID": [str(int(datetime.now().timestamp()))],
            "TASK TITLE": [task_title],
            "TASK TYPE": [task_type],
            "ASSIGNED TO": [assigned_to],
            "START DATE": [start_date.strftime("%d-%m-%Y")],
            "STATUS": ["Pending"],
            "FREQUENCY": [task_type],
            "LAST COMPLETED DATE": [""],
            "REMARKS": [""]
        })

        df_master = pd.concat([df_master, new_task], ignore_index=True)

        write_df("SALES_TEAM_TASK", df_master)
        st.success("Task created successfully!")
        st.cache_data.clear()
        st.rerun()