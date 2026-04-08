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
# SAFE WRITE FUNCTION (IMPORTANT FIX)
# =========================================================
def safe_write(df):
    """
    Always reload latest sheet before writing to prevent overwrite issues
    """
    latest_df = get_df("SALES_TEAM_TASK")

    if latest_df is None or latest_df.empty:
        write_df("SALES_TEAM_TASK", df)
        return

    latest_df.columns = [str(c).strip().upper() for c in latest_df.columns]
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Merge on TASK ID (prevents deletion)
    merged = pd.concat([latest_df, df]).drop_duplicates(subset=["TASK ID"], keep="last")

    write_df("SALES_TEAM_TASK", merged)


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
# UPDATE TASK (FIXED)
# =========================================================
def update_task(task_id, mark_done=True):
    df_latest = get_df("SALES_TEAM_TASK")
    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]

    if mark_done:
        df_latest.loc[df_latest["TASK ID"] == task_id, "LAST COMPLETED DATE"] = datetime.now().strftime("%d-%m-%Y")
    else:
        df_latest.loc[df_latest["TASK ID"] == task_id, "LAST COMPLETED DATE"] = ""

    write_df("SALES_TEAM_TASK", df_latest)
    st.cache_data.clear()


# =========================================================
# MAIN UI
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

# =========================================================
# CREATE TASK (FIXED)
# =========================================================
with st.expander("➕ Create New Task"):
    with st.form("new_task_form"):
        col_a, col_b = st.columns(2)
        new_title = col_a.text_input("Task Title")
        new_assigned = col_b.text_input("Assigned To")

        col_c, col_d = st.columns(2)
        new_freq = col_c.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        new_date = col_d.date_input("Start / Task Date", value=datetime.now())

        if st.form_submit_button("Add Task to Sheet"):
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

                st.success(f"Task '{new_title}' added!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Title & Assigned To required")


# =========================================================
# REST SAME (NO CHANGE)
# =========================================================
today = datetime.now()

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
# FILTERS
# =========================================================
start_week = today - timedelta(days=today.weekday())
end_week = start_week + timedelta(days=6)

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
# TABLE
# =========================================================
def render_table(df, title):
    st.subheader(title)

    if df.empty:
        st.write("No tasks.")
        return

    df_display = df.copy()
    df_display["DUE DATE"] = df_display["DUE DATE"].dt.strftime("%d-%B-%Y")
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