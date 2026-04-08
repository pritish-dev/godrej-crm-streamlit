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
# LOAD TASK DATA
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
# LOAD SALES TEAM
# =========================================================
@st.cache_data(ttl=60)
def load_sales_team():
    df = get_df("SALES_TEAM")

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


# =========================================================
# GENERATE TASKS
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

            if freq == "adhoc":
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
        if row["LAST COMPLETED DATE"].date() > row["DUE DATE"].date():
            return "🔴 Missed"
        return "🟢 Done"

    if row["DUE DATE"].date() < today:
        return "🔴 Overdue"

    return "🟣 Pending"


# =========================================================
# UPDATE TASK (SAFE)
# =========================================================
def update_task(task_id, mark_done=True):
    df_latest = get_df("SALES_TEAM_TASK")

    if df_latest is None or df_latest.empty:
        return

    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]

    if mark_done:
        df_latest.loc[df_latest["TASK ID"] == task_id, "LAST COMPLETED DATE"] = datetime.now().strftime("%d-%m-%Y")
    else:
        df_latest.loc[df_latest["TASK ID"] == task_id, "LAST COMPLETED DATE"] = ""

    write_df("SALES_TEAM_TASK", df_latest)
    st.cache_data.clear()


# =========================================================
# UI START
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

# =========================================================
# CREATE TASK
# =========================================================
with st.expander("➕ Create New Task"):
    with st.form("new_task_form"):
        col1, col2 = st.columns(2)
        new_title = col1.text_input("Task Title")
        new_assigned = col2.text_input("Assigned To (comma separated)")

        col3, col4 = st.columns(2)
        new_freq = col3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        new_date = col4.date_input("Task Date", value=datetime.now())

        if st.form_submit_button("Add Task"):
            if new_title and new_assigned:

                df_latest = get_df("SALES_TEAM_TASK")

                if df_latest is None or df_latest.empty:
                    next_id = 1
                    df_latest = pd.DataFrame()
                else:
                    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]
                    next_id = df_latest.shape[0] + 1

                new_row = {
                    "TASK ID": str(next_id),
                    "TASK TITLE": new_title,
                    "FREQUENCY": new_freq,
                    "ASSIGNED TO": new_assigned,
                    "TASK DATE": new_date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": ""
                }

                updated_df = pd.concat([df_latest, pd.DataFrame([new_row])], ignore_index=True)
                write_df("SALES_TEAM_TASK", updated_df)

                st.success("Task added successfully!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Please fill all fields")


st.divider()

if df_master.empty:
    st.warning("No tasks found.")
    st.stop()

today = datetime.now()

# =========================================================
# DATE FILTER
# =========================================================
col1, col2 = st.columns(2)
year = col1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = col2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

if tasks.empty:
    st.info("No tasks generated.")
    st.stop()

tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])


# =========================================================
# FILTERS (FIXED ADHOC)
# =========================================================
start_week = today - timedelta(days=today.weekday())
end_week = start_week + timedelta(days=6)

daily_df = tasks[
    (tasks["FREQUENCY"].str.lower().isin(["daily", "adhoc"])) &
    (
        (tasks["DUE DATE"].dt.date == today.date()) |
        (tasks["FREQUENCY"].str.lower() == "daily")
    )
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
# TABLE FUNCTION
# =========================================================
def render_table(df, title):
    st.subheader(title)

    if df.empty:
        st.write("No tasks.")
        return

    df_display = df.copy()
    df_display["DUE DATE"] = df_display["DUE DATE"].dt.strftime("%d-%m-%Y")
    df_display["DONE"] = False

    cols = ["DONE", "TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS", "TASK ID"]
    edited = st.data_editor(df_display[cols], use_container_width=True, key=title)

    done_rows = edited[edited["DONE"] == True]

    if not done_rows.empty:
        for task_id in done_rows["TASK ID"]:
            update_task(task_id, True)
        st.rerun()


render_table(daily_df, "🟣 Daily & Adhoc Tasks")
render_table(weekly_df, "📅 Weekly Tasks")
render_table(monthly_df, "🗓️ Monthly Tasks")


# =========================================================
# SALES TEAM PERFORMANCE
# =========================================================
st.divider()
st.subheader("📊 Sales Team Performance")

team_df = load_sales_team()

if team_df.empty:
    st.warning("No SALES_TEAM data found.")
else:
    perf = []

    for _, row in tasks.iterrows():
        employees = str(row["ASSIGNED TO"]).split(",")

        for emp in employees:
            emp = emp.strip()

            if row["STATUS"] == "🟢 Done":
                status = "Done"
            elif row["STATUS"] in ["🔴 Overdue", "🔴 Missed"]:
                status = "Overdue"
            else:
                status = "Pending"

            perf.append({"EMPLOYEE": emp, "STATUS": status})

    perf_df = pd.DataFrame(perf)

    if not perf_df.empty:
        summary = (
            perf_df.groupby(["EMPLOYEE", "STATUS"])
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )

        for col in ["Done", "Pending", "Overdue"]:
            if col not in summary.columns:
                summary[col] = 0

        summary = summary[["EMPLOYEE", "Done", "Pending", "Overdue"]]

        if "EMPLOYEE" in team_df.columns:
            final = team_df.merge(summary, on="EMPLOYEE", how="left").fillna(0)
        else:
            final = summary

        st.dataframe(final, use_container_width=True)
    else:
        st.info("No performance data available.")