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

    df.columns = [str(c).strip().upper() for c in df.columns]

    if "TASK DATE" in df.columns:
        df["START DATE"] = df["TASK DATE"]

    if "TASK ID" not in df.columns:
        df["TASK ID"] = df.index.astype(str)

    df["START DATE"] = pd.to_datetime(df["START DATE"], dayfirst=True, errors="coerce")
    df["LAST COMPLETED DATE"] = pd.to_datetime(df["LAST COMPLETED DATE"], dayfirst=True, errors="coerce")

    return df


# =========================================================
# GENERATE TASKS (Updated for ADHOC logic)
# =========================================================
def generate_tasks(df, year, month):
    rows = []

    for _, row in df.iterrows():
        freq = str(row["FREQUENCY"]).lower()
        start = row["START DATE"]

        if pd.isna(start):
            continue

        for day in range(1, 32):
            try:
                current = datetime(year, month, day)
            except:
                continue

            # Check logic based on Frequency
            if freq == "adhoc":
                # Adhoc tasks only show up on their specific Start Date
                if current.date() != start.date():
                    continue

            elif freq == "daily":
                pass

            elif freq == "weekly":
                if current.weekday() != start.weekday():
                    continue

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
# STATUS LOGIC
# =========================================================
def get_status(row):
    today = datetime.now().date()

    if pd.notnull(row["LAST COMPLETED DATE"]):
        # If it was completed, check if it was on or before the due date
        if row["LAST COMPLETED DATE"].date() > row["DUE DATE"].date():
            return "🔴 Missed"
        return "🟢 Done"

    if row["DUE DATE"].date() < today:
        return "🔴 Overdue"

    return "🟣 Pending"


# =========================================================
# UPDATE TASK
# =========================================================
def update_task(task_id, df, mark_done=True):
    if mark_done:
        df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = datetime.now().strftime("%d-%B-%Y")
    else:
        df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = ""

    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# =========================================================
# MAIN UI
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

# --- CREATE TASK SECTION ---
with st.expander("➕ Create New Task"):
    with st.form("new_task_form"):
        col_a, col_b = st.columns(2)
        new_title = col_a.text_input("Task Title")
        new_assigned = col_b.text_input("Assigned To (Comma separated)")
        
        col_c, col_d = st.columns(2)
        new_freq = col_c.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        new_date = col_d.date_input("Start / Task Date", value=datetime.now())
        
        if st.form_submit_button("Add Task to Sheet"):
            if new_title and new_assigned:
                # Prepare row for Google Sheets
                new_row = {
                    "TASK ID": str(len(df_master) + 1),
                    "TASK TITLE": new_title,
                    "FREQUENCY": new_freq,
                    "ASSIGNED TO": new_assigned,
                    "TASK DATE": new_date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": ""
                }
                
                # Append to master and write back
                updated_master = pd.concat([df_master, pd.DataFrame([new_row])], ignore_index=True)
                write_df("SALES_TEAM_TASK", updated_master)
                
                st.success(f"Task '{new_title}' added successfully!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Title and Assigned To are required.")

st.divider()

if df_master.empty:
    st.warning("No tasks found in the source sheet.")
    st.stop()

today = datetime.now()

# Date Selection
col1, col2 = st.columns(2)
year = col1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = col2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

if tasks.empty:
    st.info("No tasks generated for this period.")
    st.stop()

tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

# =========================================================
# FILTERS
# =========================================================
start_week = today - timedelta(days=today.weekday())
end_week = start_week + timedelta(days=6)

# DAILY now includes ADHOC tasks
daily_df = tasks[
    (tasks["FREQUENCY"].str.lower().isin(["daily", "adhoc"])) &
    (tasks["DUE DATE"].dt.date <= today.date())
]

weekly_df = tasks[
    (tasks["FREQUENCY"].str.lower() == "weekly") &
    (tasks["DUE DATE"].dt.date >= start_week.date()) &
    (tasks["DUE DATE"].dt.date <= end_week.date())
]

monthly_df = tasks[
    (tasks["FREQUENCY"].str.lower() == "monthly") &
    (tasks["DUE DATE"].dt.month == month)
]

# =========================================================
# TABLE RENDER FUNCTION
# =========================================================
def render_table(df, title):
    st.subheader(title)

    if df.empty:
        st.write("No tasks in this category.")
        return

    df_display = df.copy()
    df_display["DUE DATE"] = df_display["DUE DATE"].dt.strftime("%d-%B-%Y")
    df_display["DONE"] = False

    # Selection of specific columns for the editor
    cols_to_show = ["DONE", "TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS", "TASK ID"]
    edited = st.data_editor(df_display[cols_to_show], use_container_width=True, key=f"editor_{title}")

    done_rows = edited[edited["DONE"] == True]

    if not done_rows.empty:
        for task_id in done_rows["TASK ID"]:
            update_task(task_id, df_master, True)
        st.rerun()


# =========================================================
# DISPLAY TABLES
# =========================================================
render_table(daily_df, "🟣 Daily & Adhoc Tasks")
render_table(weekly_df, "📅 Weekly Tasks")
render_table(monthly_df, "🗓️ Monthly Tasks")


# =========================================================
# WHATSAPP FORMATTING
# =========================================================
def format_task_whatsapp(df, title):
    if df.empty:
        return f"*{title}*\n\nNo tasks 🎉"

    msg = f"*{title}*\n\n"
    msg += "📅 Date | Task | Assigned | Status\n"
    msg += "--------------------------------------\n"

    for _, row in df.iterrows():
        date = row["DUE DATE"].strftime("%d-%b")
        task = str(row["TASK TITLE"])[:18]
        assigned_list = [x.strip() for x in str(row["ASSIGNED TO"]).split(",")]

        if len(assigned_list) > 2:
            assigned = f"{assigned_list[0]}, {assigned_list[1]} +{len(assigned_list)-2}"
        else:
            assigned = ", ".join(assigned_list)
        
        status = row["STATUS"]
        msg += (
            f"DATE📅: {date}\n"
            f"TASK📝: {task}\n"
            f"Assigned To👥: {assigned}\n"
            f"STATUS📌: {status}\n\n"
        )

    msg += "--------------------------------------"
    return msg

st.divider()

# Only tasks for exactly today (Daily + Adhoc)
today_date = today.date()
today_tasks = daily_df[daily_df["DUE DATE"].dt.date == today_date]

# =========================================================
# WHATSAPP BUTTONS
# =========================================================
col_w1, col_w2, col_w3 = st.columns(3)

with col_w1:
    if st.button("📲 Prepare Daily Status"):
        msg = format_task_whatsapp(today_tasks, "📋 Today's Tasks")
        st.link_button("Confirm & Send WhatsApp", generate_whatsapp_group_link(msg))

with col_w2:
    if st.button("📲 Prepare Weekly Status"):
        msg = format_task_whatsapp(weekly_df, "📅 Weekly Tasks")
        st.link_button("Confirm & Send WhatsApp", generate_whatsapp_group_link(msg))

with col_w3:
    if st.button("📲 Prepare Monthly Status"):
        msg = format_task_whatsapp(monthly_df, "🗓️ Monthly Tasks")
        st.link_button("Confirm & Send WhatsApp", generate_whatsapp_group_link(msg))


# =========================================================
# EMPLOYEE PERFORMANCE
# =========================================================
st.divider()
st.subheader("📊 Employee Task Performance")

perf = []
for _, row in tasks.iterrows():
    employees = str(row["ASSIGNED TO"]).split(",")
    for emp in employees:
        emp = emp.strip()
        if row["STATUS"] == "🟢 Done":
            status = "Done"
        elif row["STATUS"] == "🔴 Missed":
            status = "Missed"
        else:
            status = "Not Done"

        perf.append({"EMPLOYEE": emp, "STATUS": status})

if perf:
    perf_df = pd.DataFrame(perf)
    summary = (
        perf_df.groupby(["EMPLOYEE", "STATUS"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    for col in ["Done", "Missed", "Not Done"]:
        if col not in summary.columns:
            summary[col] = 0

    summary = summary[["EMPLOYEE", "Done", "Missed", "Not Done"]]
    st.dataframe(summary, use_container_width=True)
else:
    st.info("No performance data available.")