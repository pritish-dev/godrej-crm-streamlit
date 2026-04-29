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
            emp = emp.strip().upper()

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
                "TASK ID": str(row.get("TASK ID", "")).strip(),
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
# GET STATUS COLOR (For display)
# =========================================================
def get_status_color_hex(status):
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
def update_task(task_id):
    today_str = datetime.now().strftime("%d-%m-%Y")

    df = get_df("SALES_TEAM_TASK")
    df.columns = [str(c).strip().upper() for c in df.columns]

    df.loc[df["TASK ID"].astype(str) == str(task_id), "LAST COMPLETED DATE"] = today_str
    write_df("SALES_TEAM_TASK", df)

    st.cache_data.clear()


# =========================================================
# RENDER INTERACTIVE TABLE WITH FILTERS
# =========================================================
def render_interactive_table(df, title, freq_type):
    """Render tasks in an interactive format with filters and marking capability"""

    st.subheader(title)

    if df.empty:
        st.info("No tasks.")
        return

    # Get unique values for filters
    employees = ["All"] + sorted(df["ASSIGNED TO"].str.upper().unique().tolist())
    statuses = ["All"] + sorted(df["STATUS"].unique().tolist())

    # Filters in columns
    col1, col2, col3 = st.columns([2, 2, 2])

    with col1:
        selected_employee = st.selectbox(
            "Filter by Sales Person",
            employees,
            key=f"emp_filter_{freq_type}",
            label_visibility="collapsed"
        )

    with col2:
        selected_status = st.selectbox(
            "Filter by Status",
            statuses,
            key=f"status_filter_{freq_type}",
            label_visibility="collapsed"
        )

    # Apply filters
    filtered_df = df.copy()

    if selected_employee != "All":
        filtered_df = filtered_df[filtered_df["ASSIGNED TO"].str.upper().str.contains(selected_employee, na=False)]

    if selected_status != "All":
        filtered_df = filtered_df[filtered_df["STATUS"] == selected_status]

    if filtered_df.empty:
        st.warning("No tasks matching filters.")
        return

    # Prepare display dataframe
    df_display = filtered_df.copy()
    df_display["DUE_DATE_STR"] = df_display["DUE DATE"].dt.strftime("%d-%b")
    df_display["Mark Done"] = False

    # Create interactive table
    st.write("**Task List:**")

    # Show summary stats
    col1, col2, col3 = st.columns(3)

    with col1:
        pending_count = len(df_display[df_display["STATUS"].str.contains("Pending")])
        st.metric("📋 Pending", pending_count)

    with col2:
        done_count = len(df_display[df_display["STATUS"].str.contains("Done")])
        st.metric("✅ Done", done_count)

    with col3:
        overdue_count = len(df_display[df_display["STATUS"].str.contains("Overdue|Missed", regex=True)])
        st.metric("🔴 Overdue", overdue_count)

    # Create table with color-coded rows
    st.write("")

    for idx, (i, row) in enumerate(df_display.iterrows()):
        # Create container for each task
        status = row["STATUS"]
        status_color = get_status_color_hex(status)

        # Task card
        with st.container():
            cols = st.columns([0.5, 2, 1.5, 1, 1.5, 0.5])

            # Mark Done Checkbox
            with cols[0]:
                marked_done = st.checkbox(
                    "✓",
                    key=f"done_marker_{freq_type}_{row['TASK ID']}_{idx}",
                    label_visibility="collapsed",
                    help="Mark task as done"
                )

                if marked_done:
                    update_task(row["TASK ID"])
                    st.rerun()

            # Task Title
            with cols[1]:
                st.markdown(f"**{row['TASK TITLE']}**")

            # Assigned To
            with cols[2]:
                st.text(row["ASSIGNED TO"])

            # Due Date
            with cols[3]:
                st.text(row["DUE_DATE_STR"])

            # Status with color background
            with cols[4]:
                # Create colored badge
                st.markdown(
                    f'<div style="background-color: {status_color}; padding: 8px; border-radius: 4px; text-align: center;"><b>{status}</b></div>',
                    unsafe_allow_html=True
                )

            with cols[5]:
                st.text(row["FREQUENCY"])

        st.divider()


# =========================================================
# UI
# =========================================================
st.title("📋 Sales Team Task Dashboard")

df_master = load_tasks()

# CREATE TASK
with st.expander("➕ Create New Task", expanded=False):
    with st.form("new_task"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Task Title")
        assigned = c2.text_input("Assigned To (comma-separated)")

        c3, c4 = st.columns(2)
        freq = c3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        date = c4.date_input("Task Date", datetime.now())

        if st.form_submit_button("➕ Add Task"):
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
                    "ASSIGNED TO": assigned.upper(),
                    "TASK DATE": date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": ""
                }

                df_latest = pd.concat([df_latest, pd.DataFrame([new_row])], ignore_index=True)
                write_df("SALES_TEAM_TASK", df_latest)

                st.success("✅ Task added successfully!")
                st.cache_data.clear()
                st.rerun()


# =========================================================
# FILTER
# =========================================================
today = datetime.now()

st.write("---")
st.subheader("📅 Select Time Period")

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
# RENDER TABLES
# =========================================================
st.write("---")

render_interactive_table(daily_df, "🟣 Daily & Adhoc Tasks", "daily")
st.write("")

render_interactive_table(weekly_df, "📅 Weekly Tasks", "weekly")
st.write("")

render_interactive_table(monthly_df, "🗓️ Monthly Tasks", "monthly")

st.write("---")

# =========================================================
# SALES TEAM PERFORMANCE WITH CLICKABLE COUNTS
# =========================================================
st.subheader("📊 Sales Team Performance")

team_df = load_sales_team()
log_df = get_df("TASK_LOGS")

if log_df is None or log_df.empty:
    st.info("No tasks logged yet")
else:
    log_df.columns = [str(c).strip().upper() for c in log_df.columns]

    # ✅ Normalize
    log_df["EMPLOYEE"] = log_df["EMPLOYEE"].str.strip().str.upper()
    log_df["DATE"] = pd.to_datetime(log_df["DATE"], dayfirst=True)

    c1, c2 = st.columns(2)
    start_date = c1.date_input("From", datetime(today.year, today.month, 1), key="perf_start")
    end_date = c2.date_input("To", today, key="perf_end")

    logs_filtered = log_df[
        (log_df["DATE"].dt.date >= start_date) &
        (log_df["DATE"].dt.date <= end_date)
    ]

    if logs_filtered.empty:
        st.info("No task data in selected date range")
    else:
        summary = logs_filtered.groupby(["EMPLOYEE", "STATUS"]).size().unstack(fill_value=0).reset_index()

        summary["EMPLOYEE"] = summary["EMPLOYEE"].str.strip().str.upper()

        for col in ["Done", "Pending", "Overdue"]:
            if col not in summary.columns:
                summary[col] = 0

        final = team_df.merge(summary, on="EMPLOYEE", how="left").fillna(0)

        # Display summary table
        st.write("**Summary Table:**")
        st.dataframe(final, use_container_width=True, hide_index=True)

        # ✅ CLICKABLE COUNTS
        st.write("---")
        st.write("**Click on counts below to view detailed tasks:**")

        for idx, row in final.iterrows():
            employee = row["EMPLOYEE"]
            overdue_count = int(row.get("Overdue", 0))
            pending_count = int(row.get("Pending", 0))
            done_count = int(row.get("Done", 0))

            # Create expandable section for each employee
            with st.expander(f"👤 {employee} - Overdue: {overdue_count} | Pending: {pending_count} | Done: {done_count}"):
                tab1, tab2, tab3 = st.tabs(["🔴 Overdue", "🟡 Pending", "🟢 Done"])

                with tab1:
                    if overdue_count > 0:
                        tasks_overdue = logs_filtered[
                            (logs_filtered["EMPLOYEE"] == employee) &
                            (logs_filtered["STATUS"] == "Overdue")
                        ]
                        st.dataframe(tasks_overdue[["TASK ID", "EMPLOYEE", "DATE", "STATUS"]], use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ No overdue tasks")

                with tab2:
                    if pending_count > 0:
                        tasks_pending = logs_filtered[
                            (logs_filtered["EMPLOYEE"] == employee) &
                            (logs_filtered["STATUS"] == "Pending")
                        ]
                        st.dataframe(tasks_pending[["TASK ID", "EMPLOYEE", "DATE", "STATUS"]], use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ No pending tasks")

                with tab3:
                    if done_count > 0:
                        tasks_done = logs_filtered[
                            (logs_filtered["EMPLOYEE"] == employee) &
                            (logs_filtered["STATUS"] == "Done")
                        ]
                        st.dataframe(tasks_done[["TASK ID", "EMPLOYEE", "DATE", "STATUS"]], use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ No completed tasks")

st.write("---")
st.info("✅ Daily automated emails are sent at 10 AM and 8 PM with task updates and status reports.")
