import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, write_df

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

    # ✅ FIX: Normalize names
    df["EMPLOYEE"] = df["EMPLOYEE"].str.strip().str.upper()

    return df[df["ROLE"].str.upper() == "SALES"]


# =========================================================
# AUTO LOG SYSTEM
# =========================================================
def auto_log_tasks(tasks):
    log_df = get_df("TASK_LOGS")

    if log_df is None or log_df.empty:
        log_df = pd.DataFrame(columns=["TASK ID", "EMPLOYEE", "DATE", "STATUS"])
    else:
        log_df.columns = [str(c).strip().upper() for c in log_df.columns]

    today_str = datetime.now().strftime("%d-%m-%Y")

    new_logs = []

    for _, row in tasks.iterrows():

        if row["DUE DATE"].date() > datetime.now().date():
            continue

        for emp in str(row["ASSIGNED TO"]).split(","):
            emp = emp.strip().upper()  # ✅ FIX

            exists = (
                (log_df["TASK ID"].astype(str).str.strip() == str(row.get("TASK ID", "")).strip()) &
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
                "TASK ID": str(row.get("TASK ID", "")).strip(),  # ✅ FIX
                "EMPLOYEE": emp,
                "DATE": today_str,
                "STATUS": status
            })

    if new_logs:
        log_df = pd.concat([log_df, pd.DataFrame(new_logs)], ignore_index=True)
        write_df("TASK_LOGS", log_df)


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

    return "🟡 Pending"


# =========================================================
# GET STATUS COLOR
# =========================================================
def get_status_color(status):
    if "Done" in status:
        return "#90EE90"  # Light Green
    elif "Overdue" in status or "Missed" in status:
        return "#FF6B6B"  # Red
    elif "Pending" in status:
        return "#FFE5B4"  # Peach/Light Orange
    return "#FFFFFF"  # White


# =========================================================
# UPDATE TASK
# =========================================================
def update_task(task_id, assigned_to):
    today_str = datetime.now().strftime("%d-%m-%Y")

    df = get_df("SALES_TEAM_TASK")
    df.columns = [str(c).strip().upper() for c in df.columns]

    df.loc[df["TASK ID"].astype(str) == str(task_id), "LAST COMPLETED DATE"] = today_str
    write_df("SALES_TEAM_TASK", df)

    st.cache_data.clear()


# =========================================================
# RENDER COLOR-CODED TABLE WITH FILTERS
# =========================================================
def render_table_with_filters(df, title, freq_type):
    st.subheader(title)

    if df.empty:
        st.write("No tasks.")
        return df

    # Get unique values for filters
    employees = ["All"] + sorted(df["ASSIGNED TO"].str.upper().unique().tolist())
    statuses = ["All"] + sorted(df["STATUS"].unique().tolist())

    # Filters in columns
    c1, c2 = st.columns(2)
    selected_employee = c1.selectbox(f"Filter by Sales Person ({freq_type})", employees, key=f"emp_{freq_type}")
    selected_status = c2.selectbox(f"Filter by Status ({freq_type})", statuses, key=f"status_{freq_type}")

    # Apply filters
    filtered_df = df.copy()

    if selected_employee != "All":
        filtered_df = filtered_df[filtered_df["ASSIGNED TO"].str.upper().str.contains(selected_employee, na=False)]

    if selected_status != "All":
        filtered_df = filtered_df[filtered_df["STATUS"] == selected_status]

    if filtered_df.empty:
        st.write("No tasks matching filters.")
        return df

    # Prepare display dataframe
    df_display = filtered_df.copy()
    df_display["DONE"] = False
    df_display["DUE DATE"] = df_display["DUE DATE"].dt.strftime("%d-%b")

    # Create HTML table with colors
    html_table = "<table style='width:100%; border-collapse: collapse;'>"
    html_table += "<tr style='background-color: #1f77b4; color: white;'>"
    html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Done</th>"
    html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Task Title</th>"
    html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Assigned To</th>"
    html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Due Date</th>"
    html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Status</th>"
    html_table += "</tr>"

    for idx, row in df_display.iterrows():
        color = get_status_color(row["STATUS"])
        html_table += f"<tr style='background-color: {color};'>"
        html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>☐</td>"
        html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['TASK TITLE']}</td>"
        html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['ASSIGNED TO']}</td>"
        html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['DUE DATE']}</td>"
        html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['STATUS']}</td>"
        html_table += "</tr>"

    html_table += "</table>"
    st.markdown(html_table, unsafe_allow_html=True)

    # Checkbox for marking done
    st.write("**Mark tasks as done:**")
    cols = st.columns(len(df_display))
    done_indices = []

    for idx, (i, row) in enumerate(df_display.iterrows()):
        with cols[idx % len(cols)]:
            if st.checkbox(f"✓ {row['TASK TITLE'][:20]}", key=f"done_{freq_type}_{i}"):
                done_indices.append(i)

    if done_indices:
        for idx in done_indices:
            task_id = filtered_df.iloc[idx]["TASK ID"]
            assigned = filtered_df.iloc[idx]["ASSIGNED TO"]
            update_task(task_id, assigned)
        st.rerun()

    return df


# =========================================================
# UI
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

# CREATE TASK
with st.expander("➕ Create New Task"):
    with st.form("new_task"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Task Title")
        assigned = c2.text_input("Assigned To")

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
# FILTER
# =========================================================
today = datetime.now()

c1, c2 = st.columns(2)
year = c1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = c2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

tasks["STATUS"] = tasks.apply(get_status, axis=1)
tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

# ✅ AUTO LOGGING
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
# RENDER FILTERED TABLES WITH COLORS
# =========================================================
d1 = render_table_with_filters(daily_df, "🟣 Daily & Adhoc Tasks", "Daily")
st.divider()

d2 = render_table_with_filters(weekly_df, "📅 Weekly Tasks", "Weekly")
st.divider()

d3 = render_table_with_filters(monthly_df, "🗓️ Monthly Tasks", "Monthly")
st.divider()


# =========================================================
# SALES TEAM PERFORMANCE WITH CLICKABLE COUNTS
# =========================================================
st.subheader("📊 Sales Team Performance")

team_df = load_sales_team()
log_df = get_df("TASK_LOGS")

if log_df is None or log_df.empty:
    st.info("No Tasks Assigned")
else:
    log_df.columns = [str(c).strip().upper() for c in log_df.columns]

    # ✅ Normalize
    log_df["EMPLOYEE"] = log_df["EMPLOYEE"].str.strip().str.upper()
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

        summary["EMPLOYEE"] = summary["EMPLOYEE"].str.strip().str.upper()

        for col in ["Done", "Pending", "Overdue"]:
            if col not in summary.columns:
                summary[col] = 0

        final = team_df.merge(summary, on="EMPLOYEE", how="left").fillna(0)

        # Display summary table
        st.dataframe(final, use_container_width=True)

        # ✅ CLICKABLE COUNTS
        st.write("**Click on counts to view detailed tasks:**")

        for idx, row in final.iterrows():
            employee = row["EMPLOYEE"]
            overdue_count = int(row.get("Overdue", 0))
            pending_count = int(row.get("Pending", 0))
            done_count = int(row.get("Done", 0))

            cols = st.columns([1, 1, 1, 2])

            # Overdue
            with cols[0]:
                if st.button(f"🔴 Overdue: {overdue_count}", key=f"overdue_{employee}"):
                    st.session_state.show_detail = f"overdue_{employee}"

            # Pending
            with cols[1]:
                if st.button(f"🟡 Pending: {pending_count}", key=f"pending_{employee}"):
                    st.session_state.show_detail = f"pending_{employee}"

            # Done
            with cols[2]:
                if st.button(f"🟢 Done: {done_count}", key=f"done_{employee}"):
                    st.session_state.show_detail = f"done_{employee}"

            # Show details if clicked
            if "show_detail" in st.session_state:
                detail_key = st.session_state.show_detail

                if detail_key == f"overdue_{employee}":
                    st.write(f"**Overdue Tasks for {employee}:**")
                    tasks_detail = logs_filtered[
                        (logs_filtered["EMPLOYEE"] == employee) &
                        (logs_filtered["STATUS"] == "Overdue")
                    ]
                    if not tasks_detail.empty:
                        st.dataframe(tasks_detail[["TASK ID", "EMPLOYEE", "DATE", "STATUS"]], use_container_width=True)
                    else:
                        st.write("No overdue tasks")

                elif detail_key == f"pending_{employee}":
                    st.write(f"**Pending Tasks for {employee}:**")
                    tasks_detail = logs_filtered[
                        (logs_filtered["EMPLOYEE"] == employee) &
                        (logs_filtered["STATUS"] == "Pending")
                    ]
                    if not tasks_detail.empty:
                        st.dataframe(tasks_detail[["TASK ID", "EMPLOYEE", "DATE", "STATUS"]], use_container_width=True)
                    else:
                        st.write("No pending tasks")

                elif detail_key == f"done_{employee}":
                    st.write(f"**Done Tasks for {employee}:**")
                    tasks_detail = logs_filtered[
                        (logs_filtered["EMPLOYEE"] == employee) &
                        (logs_filtered["STATUS"] == "Done")
                    ]
                    if not tasks_detail.empty:
                        st.dataframe(tasks_detail[["TASK ID", "EMPLOYEE", "DATE", "STATUS"]], use_container_width=True)
                    else:
                        st.write("No done tasks")

st.divider()
st.info("✅ Daily automated emails are sent at 10 AM and 8 PM with task updates and status reports.")
