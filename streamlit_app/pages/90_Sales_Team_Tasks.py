"""
pages/90_Sales_Team_Tasks.py
Sales Team Task Dashboard — Fixed & Enhanced
Key fixes:
- Daily tasks: exact-date completion check → Missed if not done that day
- Weekly/Monthly: >= comparison → Overdue if past due date
- Auto-log upserts (updates status when it changes, no duplicates)
- Drill-down shows Task Title + Date, not just Task ID
- Missed tracked separately from Overdue in performance table
- Stable checkbox keys prevent cross-task state bleed
"""
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
    if pd.isna(x) or str(x).strip() in ("", "nan", "NaT"):
        return pd.NaT
    try:
        return pd.to_datetime(x, dayfirst=True)
    except Exception:
        try:
            return pd.to_datetime(x)
        except Exception:
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
    df["EMPLOYEE"] = df["EMPLOYEE"].str.strip().str.upper()
    return df[df["ROLE"].str.upper() == "SALES"]


# =========================================================
# GENERATE TASKS — expand recurring tasks into occurrences
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
            except ValueError:
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
# STATUS — Core business logic
#
# DAILY tasks: must be completed on the EXACT due date.
#   LCD == DUE DATE              -> Done
#   DUE DATE < today, LCD != DUE -> Missed   (NOT Overdue)
#   DUE DATE >= today             -> Pending
#
# WEEKLY / MONTHLY / ADHOC: any completion on/after due date counts.
#   LCD >= DUE DATE              -> Done
#   DUE DATE < today, not done   -> Overdue
#   DUE DATE >= today             -> Pending
# =========================================================
def get_status(row):
    today = datetime.now().date()
    freq = str(row.get("FREQUENCY", "")).strip().lower()
    due = row["DUE DATE"].date() if pd.notna(row["DUE DATE"]) else None
    lcd = row["LAST COMPLETED DATE"].date() if pd.notna(row["LAST COMPLETED DATE"]) else None

    if due is None:
        return "Pending"

    if freq == "daily":
        if lcd is not None and lcd == due:
            return "Done"
        if due < today:
            return "Missed"
        return "Pending"
    else:
        if lcd is not None and lcd >= due:
            return "Done"
        if due < today:
            return "Overdue"
        return "Pending"


STATUS_EMOJI = {
    "Done": "Done",
    "Pending": "Pending",
    "Overdue": "Overdue",
    "Missed": "Missed",
}

STATUS_LABEL = {
    "Done": "Done",
    "Pending": "Pending",
    "Overdue": "Overdue",
    "Missed": "Missed (Daily)",
}

STATUS_COLOR = {
    "Done":    "#90EE90",
    "Pending": "#FFE5B4",
    "Overdue": "#FF6B6B",
    "Missed":  "#FF6B6B",
}


def get_status_color_hex(status):
    return STATUS_COLOR.get(status, "#FFFFFF")


def status_icon(status):
    icons = {"Done": "🟢", "Pending": "🟡", "Overdue": "🔴", "Missed": "❌"}
    return icons.get(status, "") + " " + status


# =========================================================
# UPDATE TASK — write today's date to master sheet
# =========================================================
def update_task(task_id):
    today_str = datetime.now().strftime("%d-%m-%Y")
    df = get_df("SALES_TEAM_TASK")
    if df is None or df.empty:
        return
    df.columns = [str(c).strip().upper() for c in df.columns]
    mask = df["TASK ID"].astype(str).str.strip() == str(task_id).strip()
    df.loc[mask, "LAST COMPLETED DATE"] = today_str
    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# =========================================================
# AUTO LOG — upsert one row per (TASK ID, EMPLOYEE, DATE)
#   Stores TASK TITLE + FREQUENCY so drill-downs show real names.
#   Updates status if it has changed since last write.
# =========================================================
def auto_log_tasks(tasks):
    log_df = get_df("TASK_LOGS")
    COLS = ["TASK ID", "TASK TITLE", "FREQUENCY", "EMPLOYEE", "DATE", "STATUS"]

    if log_df is None or log_df.empty:
        log_df = pd.DataFrame(columns=COLS)
    else:
        log_df.columns = [str(c).strip().upper() for c in log_df.columns]
        for col in COLS:
            if col not in log_df.columns:
                log_df[col] = ""

    today_str = datetime.now().strftime("%d-%m-%Y")
    today_date = datetime.now().date()
    changed = False

    for _, row in tasks.iterrows():
        due_date = row["DUE DATE"].date() if pd.notna(row["DUE DATE"]) else None
        if due_date is None or due_date > today_date:
            continue

        raw_status = row.get("STATUS", "Pending")
        log_status = raw_status if raw_status in ("Done", "Pending", "Overdue", "Missed") else "Pending"

        task_id    = str(row.get("TASK ID", "")).strip()
        task_title = str(row.get("TASK TITLE", "")).strip()
        frequency  = str(row.get("FREQUENCY", "")).strip()

        for emp_raw in str(row["ASSIGNED TO"]).split(","):
            emp = emp_raw.strip().upper()
            if not emp:
                continue

            mask = (
                (log_df["TASK ID"].astype(str).str.strip() == task_id) &
                (log_df["EMPLOYEE"].str.strip().str.upper() == emp) &
                (log_df["DATE"].astype(str).str.strip() == today_str)
            )

            if mask.any():
                if log_df.loc[mask, "STATUS"].values[0] != log_status:
                    log_df.loc[mask, "STATUS"]     = log_status
                    log_df.loc[mask, "TASK TITLE"] = task_title
                    log_df.loc[mask, "FREQUENCY"]  = frequency
                    changed = True
            else:
                log_df = pd.concat([log_df, pd.DataFrame([{
                    "TASK ID":    task_id,
                    "TASK TITLE": task_title,
                    "FREQUENCY":  frequency,
                    "EMPLOYEE":   emp,
                    "DATE":       today_str,
                    "STATUS":     log_status,
                }])], ignore_index=True)
                changed = True

    if changed:
        write_df("TASK_LOGS", log_df)


# =========================================================
# RENDER INTERACTIVE TABLE
# =========================================================
def render_interactive_table(df, title, freq_type):
    st.subheader(title)

    if df.empty:
        st.info("No tasks for this period.")
        return

    employees = ["All"] + sorted(df["ASSIGNED TO"].str.upper().unique().tolist())
    statuses  = ["All"] + sorted(df["STATUS"].unique().tolist())

    c1, c2 = st.columns([2, 2])
    with c1:
        sel_emp = st.selectbox(
            "Filter by Sales Person", employees,
            key=f"emp_filter_{freq_type}", label_visibility="collapsed"
        )
    with c2:
        sel_status = st.selectbox(
            "Filter by Status", statuses,
            key=f"status_filter_{freq_type}", label_visibility="collapsed"
        )

    fdf = df.copy()
    if sel_emp != "All":
        fdf = fdf[fdf["ASSIGNED TO"].str.upper().str.contains(sel_emp, na=False)]
    if sel_status != "All":
        fdf = fdf[fdf["STATUS"] == sel_status]

    if fdf.empty:
        st.warning("No tasks match the selected filters.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Pending", len(fdf[fdf["STATUS"] == "Pending"]))
    c2.metric("✅ Done",    len(fdf[fdf["STATUS"] == "Done"]))
    c3.metric("🔴 Overdue", len(fdf[fdf["STATUS"] == "Overdue"]))
    c4.metric("❌ Missed",  len(fdf[fdf["STATUS"] == "Missed"]))

    st.write("")
    st.write("**Task Table:**")

    hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([0.8, 3, 2, 1.5, 1.8, 1.2])
    hc1.write("**✓**"); hc2.write("**Task Title**"); hc3.write("**Assigned To**")
    hc4.write("**Due Date**"); hc5.write("**Status**"); hc6.write("**Freq**")
    st.divider()

    for _, row in fdf.iterrows():
        task_id = str(row["TASK ID"]).strip()
        due_str = row["DUE DATE"].strftime("%Y%m%d") if pd.notna(row["DUE DATE"]) else "na"
        cb_key  = f"cb_{freq_type}_{task_id}_{due_str}"
        status  = row["STATUS"]
        is_done = (status == "Done")

        tc1, tc2, tc3, tc4, tc5, tc6 = st.columns([0.8, 3, 2, 1.5, 1.8, 1.2])

        with tc1:
            if is_done:
                st.write("✅")
            else:
                if st.checkbox("done", key=cb_key, label_visibility="collapsed", help="Mark as done"):
                    update_task(task_id)
                    st.rerun()

        tc2.write(row["TASK TITLE"])
        tc3.write(str(row["ASSIGNED TO"]).upper())
        tc4.write(row["DUE DATE"].strftime("%d-%b-%Y") if pd.notna(row["DUE DATE"]) else "N/A")

        with tc5:
            color = get_status_color_hex(status)
            st.markdown(
                f'<div style="background:{color};padding:5px 6px;border-radius:4px;'
                f'text-align:center;font-weight:bold;font-size:12px;">'
                f'{status_icon(status)}</div>',
                unsafe_allow_html=True,
            )

        tc6.write(str(row["FREQUENCY"]).capitalize())
        st.divider()


# =========================================================
# MAIN UI
# =========================================================
st.title("Sales Team Task Dashboard")

df_master = load_tasks()

# ── CREATE TASK ──────────────────────────────────────────
with st.expander("Add New Task", expanded=False):
    with st.form("new_task"):
        c1, c2 = st.columns(2)
        title    = c1.text_input("Task Title")
        assigned = c2.text_input("Assigned To (comma-separated)")

        c3, c4 = st.columns(2)
        freq      = c3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        task_date = c4.date_input("Task Date", datetime.now())

        if st.form_submit_button("Add Task"):
            if title and assigned:
                df_latest = get_df("SALES_TEAM_TASK")
                if df_latest is None or df_latest.empty:
                    df_latest = pd.DataFrame()
                    next_id = 1
                else:
                    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]
                    try:
                        next_id = int(
                            df_latest["TASK ID"].astype(str)
                            .str.extract(r"(\d+)")[0].dropna().astype(int).max()
                        ) + 1
                    except Exception:
                        next_id = len(df_latest) + 1

                new_row = {
                    "TASK ID":             str(next_id),
                    "TASK TITLE":          title.strip(),
                    "FREQUENCY":           freq,
                    "ASSIGNED TO":         assigned.strip().upper(),
                    "TASK DATE":           task_date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": "",
                }
                df_latest = pd.concat([df_latest, pd.DataFrame([new_row])], ignore_index=True)
                write_df("SALES_TEAM_TASK", df_latest)
                st.success(f"Task '{title}' added (ID: {next_id})")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Task Title and Assigned To are required.")

# ── TIME PERIOD ──────────────────────────────────────────
st.write("---")
st.subheader("Select Time Period")
today = datetime.now()

c1, c2 = st.columns(2)
year  = c1.selectbox("Year",  [2024, 2025, 2026, 2027], index=2)
month = c2.selectbox("Month", list(range(1, 13)), index=today.month - 1)

tasks = generate_tasks(df_master, year, month)

EMPTY_COLS = ["TASK ID", "TASK TITLE", "FREQUENCY", "ASSIGNED TO",
              "DUE DATE", "STATUS", "LAST COMPLETED DATE"]

if not tasks.empty:
    tasks["STATUS"]   = tasks.apply(get_status, axis=1)
    tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])
else:
    tasks = pd.DataFrame(columns=EMPTY_COLS)
    tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

auto_log_tasks(tasks)

# ── SPLIT BY FREQUENCY ───────────────────────────────────
start_week = today - timedelta(days=today.weekday())

if not tasks.empty:
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
else:
    daily_df = weekly_df = monthly_df = pd.DataFrame(columns=EMPTY_COLS)

# ── RENDER TABLES ────────────────────────────────────────
st.write("---")
render_interactive_table(daily_df,   "Daily & Adhoc Tasks",  "daily")
st.write("")
render_interactive_table(weekly_df,  "Weekly Tasks",         "weekly")
st.write("")
render_interactive_table(monthly_df, "Monthly Tasks",        "monthly")

# =========================================================
# SALES TEAM PERFORMANCE
# =========================================================
st.write("---")
st.subheader("Sales Team Performance")

team_df = load_sales_team()
log_df  = get_df("TASK_LOGS")

if log_df is None or log_df.empty:
    st.info("No tasks logged yet.")
else:
    log_df.columns = [str(c).strip().upper() for c in log_df.columns]
    log_df["EMPLOYEE"] = log_df["EMPLOYEE"].str.strip().str.upper()
    log_df["DATE"]     = pd.to_datetime(log_df["DATE"], dayfirst=True, errors="coerce")

    # backward compat with old logs that lacked TASK TITLE / FREQUENCY
    if "TASK TITLE" not in log_df.columns:
        log_df["TASK TITLE"] = log_df.get("TASK ID", "Unknown")
    if "FREQUENCY" not in log_df.columns:
        log_df["FREQUENCY"] = ""

    c1, c2 = st.columns(2)
    start_date = c1.date_input("From", datetime(today.year, today.month, 1), key="perf_start")
    end_date   = c2.date_input("To",   today,                                key="perf_end")

    logs_filtered = log_df[
        (log_df["DATE"].dt.date >= start_date) &
        (log_df["DATE"].dt.date <= end_date)
    ].copy()

    if logs_filtered.empty:
        st.info("No task data in the selected date range.")
    else:
        summary = (
            logs_filtered
            .groupby(["EMPLOYEE", "STATUS"])
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )
        summary["EMPLOYEE"] = summary["EMPLOYEE"].str.strip().str.upper()

        for col in ["Done", "Pending", "Overdue", "Missed"]:
            if col not in summary.columns:
                summary[col] = 0

        final = team_df.merge(summary, on="EMPLOYEE", how="left").fillna(0)
        for col in ["Done", "Pending", "Overdue", "Missed"]:
            final[col] = final[col].astype(int)

        display_cols = ["EMPLOYEE"] + [c for c in ["Done", "Pending", "Overdue", "Missed"] if c in final.columns]
        st.write("**Summary Table:**")
        st.dataframe(final[display_cols], use_container_width=True, hide_index=True)

        # ── DRILL-DOWN PER EMPLOYEE ───────────────────────
        st.write("---")
        st.write("**Click an employee to view task details:**")

        for _, erow in final.iterrows():
            employee    = erow["EMPLOYEE"]
            done_cnt    = int(erow.get("Done",    0))
            pending_cnt = int(erow.get("Pending", 0))
            overdue_cnt = int(erow.get("Overdue", 0))
            missed_cnt  = int(erow.get("Missed",  0))

            label = (
                f"👤 {employee}  —  "
                f"✅ Done: {done_cnt}  |  "
                f"📋 Pending: {pending_cnt}  |  "
                f"🔴 Overdue: {overdue_cnt}  |  "
                f"❌ Missed: {missed_cnt}"
            )

            with st.expander(label):
                emp_logs = logs_filtered[
                    logs_filtered["EMPLOYEE"] == employee
                ][["TASK TITLE", "FREQUENCY", "DATE", "STATUS"]].copy()

                emp_logs["DATE"] = emp_logs["DATE"].dt.strftime("%d-%b-%Y")
                emp_logs = emp_logs.sort_values("DATE", ascending=False)

                tab_done, tab_pending, tab_overdue, tab_missed = st.tabs(
                    ["🟢 Done", "🟡 Pending", "🔴 Overdue", "❌ Missed"]
                )

                def _show(tab, status_val, empty_msg):
                    with tab:
                        subset = emp_logs[emp_logs["STATUS"] == status_val].copy()
                        if subset.empty:
                            st.success(empty_msg)
                        else:
                            st.dataframe(
                                subset.rename(columns={
                                    "TASK TITLE": "Task Title",
                                    "FREQUENCY":  "Frequency",
                                    "DATE":       "Date",
                                    "STATUS":     "Status",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )

                _show(tab_done,    "Done",    "No completed tasks in this range")
                _show(tab_pending, "Pending", "No pending tasks in this range")
                _show(tab_overdue, "Overdue", "No overdue tasks in this range")
                _show(tab_missed,  "Missed",  "No missed daily tasks in this range")

st.write("---")
st.info("Daily automated emails are sent at 10 AM and 8 PM with task updates and status reports.")
