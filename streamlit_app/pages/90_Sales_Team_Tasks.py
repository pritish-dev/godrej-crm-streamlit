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
# DATE PARSER
# =========================================================
def parse_date(x):
    try:
        return pd.to_datetime(x, dayfirst=True)
    except:
        try:
            return pd.to_datetime(x)
        except:
            return pd.NaT


# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=60)
def load_tasks():
    df = get_df("SALES_TEAM_TASK")
    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [c.strip().upper() for c in df.columns]
    df["START DATE"] = df["TASK DATE"].apply(parse_date)
    df["LAST COMPLETED DATE"] = df["LAST COMPLETED DATE"].apply(parse_date)

    return df


@st.cache_data(ttl=60)
def load_sales_team():
    df = get_df("Sales Team")
    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [c.strip().upper() for c in df.columns]
    df.rename(columns={"NAME": "EMPLOYEE"}, inplace=True)

    return df[df["ROLE"].str.upper() == "SALES"]


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

        if freq == "adhoc":
            rows.append({**row, "DUE DATE": start})
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

            rows.append({**row, "DUE DATE": current})

    return pd.DataFrame(rows)


# =========================================================
# STATUS
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
# AUTO LOG SYSTEM (NEW)
# =========================================================
def auto_log_tasks(tasks):
    log_df = get_df("TASK_LOGS")

    if log_df is None or log_df.empty:
        log_df = pd.DataFrame(columns=["TASK ID", "EMPLOYEE", "DATE", "STATUS"])
    else:
        log_df.columns = [c.strip().upper() for c in log_df.columns]

    today_str = datetime.now().strftime("%d-%m-%Y")

    new_logs = []

    for _, row in tasks.iterrows():
        if row["DUE DATE"].date() > datetime.now().date():
            continue

        for emp in str(row["ASSIGNED TO"]).split(","):
            emp = emp.strip()

            exists = (
                (log_df["TASK ID"] == row["TASK ID"]) &
                (log_df["EMPLOYEE"] == emp) &
                (log_df["DATE"] == today_str)
            )

            if exists.any():
                continue

            if row["STATUS"] == "🟢 Done":
                status = "Done"
            elif row["STATUS"] in ["🔴 Overdue", "🔴 Missed"]:
                status = "Overdue"
            else:
                status = "Pending"

            new_logs.append({
                "TASK ID": row["TASK ID"],
                "EMPLOYEE": emp,
                "DATE": today_str,
                "STATUS": status
            })

    if new_logs:
        log_df = pd.concat([log_df, pd.DataFrame(new_logs)], ignore_index=True)
        write_df("TASK_LOGS", log_df)


# =========================================================
# UPDATE TASK
# =========================================================
def update_task(task_id, assigned_to):
    today_str = datetime.now().strftime("%d-%m-%Y")

    df = get_df("SALES_TEAM_TASK")
    df.columns = [c.strip().upper() for c in df.columns]

    df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = today_str
    write_df("SALES_TEAM_TASK", df)


# =========================================================
# UI START
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()
team_df = load_sales_team()

today = datetime.now()

# =========================================================
# CREATE TASK
# =========================================================
with st.expander("➕ Create Task"):
    with st.form("task"):
        t1, t2 = st.columns(2)
        title = t1.text_input("Task Title")
        assigned = t2.text_input("Assigned To")

        t3, t4 = st.columns(2)
        freq = t3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        date = t4.date_input("Date", today)

        if st.form_submit_button("Add"):
            df = get_df("SALES_TEAM_TASK")
            next_id = len(df) + 1 if df is not None else 1

            new = {
                "TASK ID": str(next_id),
                "TASK TITLE": title,
                "FREQUENCY": freq,
                "ASSIGNED TO": assigned,
                "TASK DATE": date.strftime("%d-%m-%Y"),
                "LAST COMPLETED DATE": ""
            }

            df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
            write_df("SALES_TEAM_TASK", df)
            st.success("Added")
            st.cache_data.clear()
            st.rerun()


# =========================================================
# FILTER
# =========================================================
year = st.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = st.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)
tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

# 🔥 AUTO LOG
auto_log_tasks(tasks)


# =========================================================
# FILTERS
# =========================================================
start_week = today - timedelta(days=today.weekday())

daily_df = tasks[
    (tasks["FREQUENCY"].str.lower().isin(["daily", "adhoc"])) &
    (tasks["DUE DATE"].dt.date <= today.date())
]

weekly_df = tasks[
    (tasks["FREQUENCY"].str.lower() == "weekly") &
    (tasks["DUE DATE"].dt.date >= start_week.date()) &
    (tasks["DUE DATE"].dt.date <= today.date())
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
        return df

    df_display = df.copy()
    df_display["DONE"] = False
    df_display["DUE DATE"] = df_display["DUE DATE"].dt.strftime("%d-%b")

    edited = st.data_editor(df_display[["DONE","TASK TITLE","ASSIGNED TO","DUE DATE","STATUS","TASK ID"]])

    done_rows = edited[edited["DONE"] == True]

    if not done_rows.empty:
        for tid in done_rows["TASK ID"]:
            assigned = df[df["TASK ID"] == tid]["ASSIGNED TO"].values[0]
            update_task(tid, assigned)
        st.rerun()

    return df


d1 = render_table(daily_df, "🟣 Daily")
d2 = render_table(weekly_df, "📅 Weekly")
d3 = render_table(monthly_df, "🗓️ Monthly")


# =========================================================
# MANAGER ALERTS
# =========================================================
st.divider()
st.subheader("🚨 Manager Alerts")

overdue = tasks[tasks["STATUS"].isin(["🔴 Overdue","🔴 Missed"])]

if overdue.empty:
    st.success("No overdue tasks 🎉")
else:
    st.error(f"{len(overdue)} overdue tasks!")

    alert_df = overdue.groupby("ASSIGNED TO").size().reset_index(name="Overdue Count")
    st.dataframe(alert_df)


# =========================================================
# LEADERBOARD
# =========================================================
st.divider()
st.subheader("🏆 Leaderboard")

log_df = get_df("TASK_LOGS")

if log_df is not None and not log_df.empty:
    log_df.columns = [c.strip().upper() for c in log_df.columns]

    score = log_df.groupby(["EMPLOYEE","STATUS"]).size().unstack(fill_value=0).reset_index()

    score["SCORE"] = score.get("Done",0) - score.get("Overdue",0)*2

    score = score.sort_values("SCORE", ascending=False)

    st.dataframe(score)
else:
    st.info("No data yet")