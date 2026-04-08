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
# DATE PARSER (FIX)
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
# LOAD TASKS
# =========================================================
@st.cache_data(ttl=60)
def load_tasks():
    df = get_df("SALES_TEAM_TASK")

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]

    df["START DATE"] = df["TASK DATE"].apply(parse_date)
    df["LAST COMPLETED DATE"] = df["LAST COMPLETED DATE"].apply(parse_date)

    return df


# =========================================================
# LOAD SALES TEAM
# =========================================================
@st.cache_data(ttl=60)
def load_sales_team():
    df = get_df("Sales Team")

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]
    df.rename(columns={"NAME": "EMPLOYEE"}, inplace=True)

    return df[df["ROLE"].str.upper() == "SALES"]


# =========================================================
# CREATE TASK UI
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

with st.expander("➕ Create New Task"):
    with st.form("new_task"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Task Title")
        assigned = c2.text_input("Assigned To (comma separated)")

        c3, c4 = st.columns(2)
        freq = c3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        date = c4.date_input("Task Date", datetime.now())

        if st.form_submit_button("Add Task"):
            if title and assigned:
                df_latest = get_df("SALES_TEAM_TASK")

                if df_latest is None or df_latest.empty:
                    df_latest = pd.DataFrame()
                    next_id = 1
                else:
                    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]
                    next_id = len(df_latest) + 1

                new_row = {
                    "TASK ID": str(next_id),
                    "TASK TITLE": title,
                    "FREQUENCY": freq,
                    "ASSIGNED TO": assigned,
                    "TASK DATE": date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": ""
                }

                df_latest = pd.concat([df_latest, pd.DataFrame([new_row])], ignore_index=True)
                write_df("SALES_TEAM_TASK", df_latest)

                st.success("Task added successfully")
                st.cache_data.clear()
                st.rerun()


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
            new_row = row.copy()
            new_row["DUE DATE"] = start
            rows.append(new_row)
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
# UPDATE TASK + LOGGING
# =========================================================
def update_task(task_id, assigned_to):
    today_str = datetime.now().strftime("%d-%m-%Y")

    df = get_df("SALES_TEAM_TASK")
    df.columns = [str(c).strip().upper() for c in df.columns]

    df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = today_str
    write_df("SALES_TEAM_TASK", df)

    # LOG
    log_df = get_df("TASK_LOGS")

    if log_df is None or log_df.empty:
        log_df = pd.DataFrame(columns=["TASK ID", "EMPLOYEE", "DATE", "STATUS"])

    logs = []
    for emp in str(assigned_to).split(","):
        logs.append({
            "TASK ID": task_id,
            "EMPLOYEE": emp.strip(),
            "DATE": today_str,
            "STATUS": "Done"
        })

    log_df = pd.concat([log_df, pd.DataFrame(logs)], ignore_index=True)
    write_df("TASK_LOGS", log_df)

    st.cache_data.clear()


# =========================================================
# DATE FILTER
# =========================================================
today = datetime.now()

c1, c2 = st.columns(2)
year = c1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = c2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])


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

    edited = st.data_editor(
        df_display[["DONE", "TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS", "TASK ID"]],
        use_container_width=True
    )

    done_rows = edited[edited["DONE"] == True]

    if not done_rows.empty:
        for tid in done_rows["TASK ID"]:
            assigned = df[df["TASK ID"] == tid]["ASSIGNED TO"].values[0]
            update_task(tid, assigned)
        st.rerun()

    return df


d1 = render_table(daily_df, "🟣 Daily & Adhoc Tasks")
d2 = render_table(weekly_df, "📅 Weekly Tasks")
d3 = render_table(monthly_df, "🗓️ Monthly Tasks")


# =========================================================
# WHATSAPP FORMAT (YOUR ORIGINAL)
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

        assigned = ", ".join(assigned_list[:2])
        if len(assigned_list) > 2:
            assigned += f" +{len(assigned_list)-2}"

        msg += (
            f"DATE📅: {date}\n"
            f"TASK📝: {task}\n"
            f"Assigned To👥: {assigned}\n"
            f"STATUS📌: {row['STATUS']}\n\n"
        )

    msg += "--------------------------------------"
    return msg


col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📲 Daily Report"):
        st.link_button("Send", generate_whatsapp_group_link(format_task_whatsapp(d1, "📋 Today's Tasks")))

with col2:
    if st.button("📲 Weekly Report"):
        st.link_button("Send", generate_whatsapp_group_link(format_task_whatsapp(d2, "📅 Weekly Tasks")))

with col3:
    if st.button("📲 Monthly Report"):
        st.link_button("Send", generate_whatsapp_group_link(format_task_whatsapp(d3, "🗓️ Monthly Tasks")))


# =========================================================
# SALES PERFORMANCE (LOG BASED)
# =========================================================
st.divider()
st.subheader("📊 Sales Team Performance")

team_df = load_sales_team()
log_df = get_df("TASK_LOGS")

if log_df is None or log_df.empty:
    st.info("No Tasks Assigned")
else:
    log_df.columns = [str(c).strip().upper() for c in log_df.columns]
    log_df["DATE"] = pd.to_datetime(log_df["DATE"], dayfirst=True)

    d1, d2 = st.columns(2)
    start_date = d1.date_input("From", datetime(today.year, today.month, 1))
    end_date = d2.date_input("To", today)

    logs_filtered = log_df[
        (log_df["DATE"].dt.date >= start_date) &
        (log_df["DATE"].dt.date <= end_date)
    ]

    if logs_filtered.empty:
        st.info("No Tasks Assigned")
    else:
        summary = logs_filtered.groupby(["EMPLOYEE", "STATUS"]).size().unstack(fill_value=0).reset_index()

        for col in ["Done", "Pending", "Overdue"]:
            if col not in summary.columns:
                summary[col] = 0

        final = team_df.merge(summary, on="EMPLOYEE", how="left").fillna(0)

        st.dataframe(final, use_container_width=True)