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

            if freq == "daily":
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
# MAIN
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

if df_master.empty:
    st.warning("No tasks found")
    st.stop()

today = datetime.now()

col1, col2 = st.columns(2)
year = col1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = col2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

if tasks.empty:
    st.info("No tasks")
    st.stop()

tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

# =========================================================
# FILTERS
# =========================================================
start_week = today - timedelta(days=today.weekday())
end_week = start_week + timedelta(days=6)

daily_df = tasks[
    (tasks["FREQUENCY"].str.lower() == "daily") &
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

    df = df.copy()
    df["DUE DATE"] = df["DUE DATE"].dt.strftime("%d-%B-%Y")
    df["DONE"] = False

    edited = st.data_editor(df, use_container_width=True)

    done_rows = edited[edited["DONE"] == True]

    if not done_rows.empty:
        for task_id in done_rows["TASK ID"]:
            update_task(task_id, df_master, True)

        st.rerun()


# =========================================================
# TABLES
# =========================================================
render_table(daily_df, "🟣 Daily Tasks")
render_table(weekly_df, "📅 Weekly Tasks")
render_table(monthly_df, "🗓️ Monthly Tasks")


def format_task_whatsapp(df, title):
    if df.empty:
        return f"*{title}*\n\nNo tasks 🎉"

    msg = f"*{title}*\n\n"

    msg += "📅 Date | Task | Assigned | Status\n"
    msg += "--------------------------------------\n"

    for _, row in df.iterrows():
        date = row["DUE DATE"].strftime("%d-%b")
        task = str(row["TASK TITLE"])[:18]
        assigned = str(row["ASSIGNED TO"])[:10]
        status = row["STATUS"]

        msg += f"{date} | {task} | {assigned} | {status}\n"

    msg += "--------------------------------------"

    return msg
st.divider()

today = datetime.now().date()

# ✅ DAILY = ONLY TODAY
today_tasks = daily_df[
    daily_df["DUE DATE"].dt.date == today
]

# =========================================================
# BUTTONS
# =========================================================
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📲 Send Daily Tasks"):
        msg = format_task_whatsapp(today_tasks, "📋 Today's Tasks")

        st.link_button("Send Daily", generate_whatsapp_group_link(msg))


with col2:
    if st.button("📲 Send Weekly Tasks"):
        msg = format_task_whatsapp(weekly_df, "📅 Weekly Tasks")

        st.link_button("Send Weekly", generate_whatsapp_group_link(msg))


with col3:
    if st.button("📲 Send Monthly Tasks"):
        msg = format_task_whatsapp(monthly_df, "🗓️ Monthly Tasks")

        st.link_button("Send Monthly", generate_whatsapp_group_link(msg))


# =========================================================
# EMPLOYEE PERFORMANCE (FIXED)
# =========================================================
st.divider()
st.subheader("📊 Employee Task Performance")

perf = []

for _, row in tasks.iterrows():
    employees = str(row["ASSIGNED TO"]).split(",")

    for emp in employees:
        emp = emp.strip()

        # Normalize status into 3 buckets
        if row["STATUS"] == "🟢 Done":
            status = "Done"
        elif row["STATUS"] == "🔴 Missed":
            status = "Missed"
        else:
            status = "Not Done"

        perf.append({
            "EMPLOYEE": emp,
            "STATUS": status
        })

perf_df = pd.DataFrame(perf)

# Aggregate safely
summary = (
    perf_df
    .groupby(["EMPLOYEE", "STATUS"])
    .size()
    .unstack(fill_value=0)
    .reset_index()
)

# Ensure all columns exist
for col in ["Done", "Missed", "Not Done"]:
    if col not in summary.columns:
        summary[col] = 0

# Reorder columns cleanly
summary = summary[["EMPLOYEE", "Done", "Missed", "Not Done"]]

st.dataframe(summary, use_container_width=True)