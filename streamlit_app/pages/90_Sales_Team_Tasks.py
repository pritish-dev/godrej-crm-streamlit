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
# LOAD TASKS
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
    df = get_df("Sales Team")

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]
    df.rename(columns={"NAME": "EMPLOYEE"}, inplace=True)

    return df[df["ROLE"].str.upper() == "SALES"]


# =========================================================
# GENERATE TASKS (FIXED ADHOC)
# =========================================================
def generate_tasks(df, year, month):
    rows = []

    for _, row in df.iterrows():
        freq = str(row["FREQUENCY"]).lower()
        start = row["START DATE"]

        if pd.isna(start):
            continue

        # 🔥 ADHOC FIX
        if freq == "adhoc":
            if start.month == month and start.year == year:
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
# UPDATE TASK
# =========================================================
def update_task(task_id):
    df = get_df("SALES_TEAM_TASK")
    df.columns = [str(c).strip().upper() for c in df.columns]

    df.loc[df["TASK ID"] == task_id, "LAST COMPLETED DATE"] = datetime.now().strftime("%d-%m-%Y")

    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# =========================================================
# UI
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

today = datetime.now()

col1, col2 = st.columns(2)
year = col1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = col2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])


# =========================================================
# FILTERS (FINAL FIX)
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
    df_display["DUE DATE"] = df_display["DUE DATE"].dt.strftime("%d-%m-%Y")
    df_display["DONE"] = False

    edited = st.data_editor(
        df_display[["DONE", "TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS", "TASK ID"]],
        use_container_width=True
    )

    done_rows = edited[edited["DONE"] == True]

    if not done_rows.empty:
        for task_id in done_rows["TASK ID"]:
            update_task(task_id)
        st.rerun()

    return df


d1 = render_table(daily_df, "🟣 Daily & Adhoc Tasks")
d2 = render_table(weekly_df, "📅 Weekly Tasks")
d3 = render_table(monthly_df, "🗓️ Monthly Tasks")


# =========================================================
# WHATSAPP
# =========================================================
def format_task_whatsapp(df, title):
    if df.empty:
        return f"*{title}*\n\nNo tasks 🎉"

    msg = f"*{title}*\n\n"

    for _, row in df.iterrows():
        msg += f"{row['DUE DATE'].strftime('%d-%b')} | {row['TASK TITLE']} | {row['STATUS']}\n"

    return msg


col_w1, col_w2, col_w3 = st.columns(3)

with col_w1:
    if st.button("📲 Send Daily"):
        st.link_button("Send", generate_whatsapp_group_link(format_task_whatsapp(d1, "Daily Tasks")))

with col_w2:
    if st.button("📲 Send Weekly"):
        st.link_button("Send", generate_whatsapp_group_link(format_task_whatsapp(d2, "Weekly Tasks")))

with col_w3:
    if st.button("📲 Send Monthly"):
        st.link_button("Send", generate_whatsapp_group_link(format_task_whatsapp(d3, "Monthly Tasks")))


# =========================================================
# SALES PERFORMANCE (WITH DATE FILTER)
# =========================================================
st.divider()
st.subheader("📊 Sales Team Performance")

team_df = load_sales_team()

date_col1, date_col2 = st.columns(2)
start_date = date_col1.date_input("From", datetime(today.year, today.month, 1))
end_date = date_col2.date_input("To", today)

filtered_tasks = tasks[
    (tasks["DUE DATE"].dt.date >= start_date) &
    (tasks["DUE DATE"].dt.date <= end_date)
]

if filtered_tasks.empty:
    st.info("No Tasks Assigned")
else:
    perf = []

    for _, row in filtered_tasks.iterrows():
        for emp in str(row["ASSIGNED TO"]).split(","):
            emp = emp.strip()

            if row["STATUS"] == "🟢 Done":
                status = "Done"
            elif row["STATUS"] in ["🔴 Overdue", "🔴 Missed"]:
                status = "Overdue"
            else:
                status = "Pending"

            perf.append({"EMPLOYEE": emp, "STATUS": status})

    perf_df = pd.DataFrame(perf)

    summary = perf_df.groupby(["EMPLOYEE", "STATUS"]).size().unstack(fill_value=0).reset_index()

    for col in ["Done", "Pending", "Overdue"]:
        if col not in summary.columns:
            summary[col] = 0

    final = team_df.merge(summary, on="EMPLOYEE", how="left").fillna(0)

    st.dataframe(final, use_container_width=True)