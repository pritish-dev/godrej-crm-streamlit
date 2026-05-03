"""
pages/90_Sales_Team_Tasks.py  —  Sales Team Task Dashboard
Python 3.13 compatible. No nested function definitions inside loops.
"""
import re
import sys
import os
import calendar
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, write_df

st.set_page_config(layout="wide", page_title="Sales Team Tasks")


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def parse_employees(assigned_str):
    """Split 'SWATI , ARCHITA & RANGANATH' into ['SWATI', 'ARCHITA', 'RANGANATH']."""
    parts = re.split(r"[,&]", str(assigned_str))
    return [p.strip().upper() for p in parts if p.strip()]


def parse_date(x):
    if pd.isna(x) or str(x).strip() in ("", "nan", "NaT"):
        return pd.NaT
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return pd.to_datetime(x, format=fmt, dayfirst=True)
        except Exception:
            pass
    try:
        return pd.to_datetime(x, dayfirst=True)
    except Exception:
        return pd.NaT


# ---------------------------------------------------------------------------
# DATA LOADERS
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def load_tasks():
    df = get_df("SALES_TEAM_TASK")
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip().upper() for c in df.columns]
    df["START DATE"] = df["TASK DATE"].apply(parse_date)
    df["LAST COMPLETED DATE"] = df["LAST COMPLETED DATE"].apply(parse_date)
    return df


@st.cache_data(ttl=60)
def load_sales_team():
    df = get_df("Sales Team")
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip().upper() for c in df.columns]
    df.rename(columns={"NAME": "EMPLOYEE"}, inplace=True)
    df["EMPLOYEE"] = df["EMPLOYEE"].str.strip().str.upper()
    return df[df["ROLE"].str.upper() == "SALES"]


# ---------------------------------------------------------------------------
# TASK GENERATION
# ---------------------------------------------------------------------------

def generate_tasks(df, year, month):
    """Expand master tasks into one row per (due-date x employee)."""
    rows = []
    for _, row in df.iterrows():
        freq = str(row["FREQUENCY"]).strip().lower()
        start = row["START DATE"]
        if pd.isna(start):
            continue
        employees = parse_employees(row.get("ASSIGNED TO", ""))
        if not employees:
            continue

        if freq == "adhoc":
            due_dates = [start]
        else:
            due_dates = []
            for day in range(1, 32):
                try:
                    current = datetime(year, month, day)
                except ValueError:
                    continue
                if freq == "daily":
                    due_dates.append(current)
                elif freq == "weekly":
                    if current.weekday() == start.weekday():
                        due_dates.append(current)
                elif freq == "monthly":
                    if current.day == start.day:
                        due_dates.append(current)

        for due in due_dates:
            for emp in employees:
                new_row = row.copy()
                new_row["DUE DATE"] = due
                new_row["EMPLOYEE"] = emp
                rows.append(new_row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# STATUS LOGIC
#
#   DAILY  : LCD == DUE  -> Done
#             DUE < today -> Missed   (never Overdue)
#             else        -> Pending
#
#   WEEKLY / MONTHLY / ADHOC:
#             LCD >= DUE  -> Done
#             DUE < today -> Overdue
#             else        -> Pending
# ---------------------------------------------------------------------------

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
        return "Missed" if due < today else "Pending"
    else:
        if lcd is not None and lcd >= due:
            return "Done"
        return "Overdue" if due < today else "Pending"


STATUS_COLOR = {
    "Done":    "#90EE90",
    "Pending": "#FFE5B4",
    "Overdue": "#FF8C8C",
    "Missed":  "#FF8C8C",
}

STATUS_ICON = {
    "Done":    "Done",
    "Pending": "Pending",
    "Overdue": "Overdue",
    "Missed":  "Missed",
}

STATUS_EMOJI = {
    "Done":    "✅",
    "Pending": "🟡",
    "Overdue": "🔴",
    "Missed":  "❌",
}


# ---------------------------------------------------------------------------
# TASK UPDATE
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# AUTO LOG — upsert per (TASK ID, EMPLOYEE, DATE=today)
# ---------------------------------------------------------------------------

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
        status = raw_status if raw_status in ("Done", "Pending", "Overdue", "Missed") else "Pending"

        task_id = str(row.get("TASK ID", "")).strip()
        task_title = str(row.get("TASK TITLE", "")).strip()
        frequency = str(row.get("FREQUENCY", "")).strip()
        emp = str(row.get("EMPLOYEE", "")).strip().upper()

        if not emp or not task_id:
            continue

        mask = (
            (log_df["TASK ID"].astype(str).str.strip() == task_id)
            & (log_df["EMPLOYEE"].str.strip().str.upper() == emp)
            & (log_df["DATE"].astype(str).str.strip() == today_str)
        )

        if mask.any():
            if log_df.loc[mask, "STATUS"].values[0] != status:
                log_df.loc[mask, "STATUS"] = status
                log_df.loc[mask, "TASK TITLE"] = task_title
                log_df.loc[mask, "FREQUENCY"] = frequency
                changed = True
        else:
            new_entry = pd.DataFrame([{
                "TASK ID":    task_id,
                "TASK TITLE": task_title,
                "FREQUENCY":  frequency,
                "EMPLOYEE":   emp,
                "DATE":       today_str,
                "STATUS":     status,
            }])
            log_df = pd.concat([log_df, new_entry], ignore_index=True)
            changed = True

    if changed:
        write_df("TASK_LOGS", log_df)


# ---------------------------------------------------------------------------
# SHOW TAB CONTENT — defined at module level (not inside loop)
# ---------------------------------------------------------------------------

def show_tab_content(tab, emp_logs, status_val, empty_msg, help_text):
    with tab:
        if help_text:
            st.caption(help_text)
        subset = emp_logs[emp_logs["STATUS"] == status_val].copy()
        if subset.empty:
            st.success(empty_msg)
        else:
            display = subset.rename(columns={
                "TASK TITLE": "Task Title",
                "FREQUENCY":  "Frequency",
                "DATE":       "Date",
                "STATUS":     "Status",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# RENDER TASK TABLE
# ---------------------------------------------------------------------------

def render_task_table(df, freq_type, helper_text, valid_statuses):
    st.caption(helper_text)

    if df.empty:
        st.info("No tasks for this period.")
        return

    all_employees = sorted(df["EMPLOYEE"].dropna().unique().tolist())
    emp_options = ["All"] + all_employees
    status_opts = ["All"] + sorted(df["STATUS"].unique().tolist())

    fc1, fc2 = st.columns([2, 2])
    sel_emp = fc1.selectbox(
        "Filter by Salesperson",
        emp_options,
        key="emp_" + freq_type,
    )
    sel_status = fc2.selectbox(
        "Filter by Status",
        status_opts,
        key="st_" + freq_type,
    )

    fdf = df.copy()
    if sel_emp != "All":
        fdf = fdf[fdf["EMPLOYEE"] == sel_emp]
    if sel_status != "All":
        fdf = fdf[fdf["STATUS"] == sel_status]

    if fdf.empty:
        st.warning("No tasks match the selected filters.")
        return

    icons_map = {
        "Done":    "✅ Done",
        "Pending": "📋 Pending",
        "Overdue": "🔴 Overdue",
        "Missed":  "❌ Missed",
    }
    mc = st.columns(len(valid_statuses))
    for i, s in enumerate(valid_statuses):
        mc[i].metric(icons_map.get(s, s), int((fdf["STATUS"] == s).sum()))

    st.write("")
    h1, h2, h3, h4, h5, h6 = st.columns([0.7, 2.8, 1.8, 1.5, 1.8, 1.4])
    h1.markdown("**Mark**")
    h2.markdown("**Task**")
    h3.markdown("**Salesperson**")
    h4.markdown("**Due Date**")
    h5.markdown("**Status**")
    h6.markdown("**Frequency**")
    st.divider()

    for _, row in fdf.iterrows():
        task_id = str(row["TASK ID"]).strip()
        due_dt = row["DUE DATE"]
        due_key = due_dt.strftime("%Y%m%d") if pd.notna(due_dt) else "na"
        emp_key = str(row["EMPLOYEE"]).replace(" ", "_")
        cb_key = "cb_" + freq_type + "_" + task_id + "_" + due_key + "_" + emp_key
        status = row["STATUS"]
        is_done = status == "Done"

        r1, r2, r3, r4, r5, r6 = st.columns([0.7, 2.8, 1.8, 1.5, 1.8, 1.4])

        with r1:
            if is_done:
                st.write("✅")
            else:
                checked = st.checkbox(
                    "done",
                    key=cb_key,
                    label_visibility="collapsed",
                    help="Mark this task as done",
                )
                if checked:
                    update_task(task_id)
                    st.rerun()

        r2.write(row["TASK TITLE"])
        r3.write(str(row["EMPLOYEE"]))
        r4.write(due_dt.strftime("%d-%b-%Y") if pd.notna(due_dt) else "N/A")

        with r5:
            color = STATUS_COLOR.get(status, "#FFFFFF")
            emoji = STATUS_EMOJI.get(status, "")
            label = STATUS_ICON.get(status, status)
            st.markdown(
                "<div style=\"background:" + color + ";padding:5px 8px;"
                "border-radius:5px;text-align:center;"
                "font-weight:bold;font-size:12px;\">"
                + emoji + " " + label + "</div>",
                unsafe_allow_html=True,
            )

        r6.write(str(row["FREQUENCY"]).capitalize())
        st.divider()


# ===========================================================================
# MAIN UI
# ===========================================================================

st.title("Sales Team Task Dashboard")
st.caption(
    "Manage and track daily, weekly, monthly and one-off tasks for the sales team. "
    "Use the checkboxes to mark tasks done. Performance is logged automatically."
)

df_master = load_tasks()

# ------- CREATE TASK --------------------------------------------------------
with st.expander("Add New Task", expanded=False):
    st.caption(
        "For multiple assignees separate names with comma or & — "
        "e.g.  SWATI , ARCHITA & RANGANATH"
    )
    with st.form("new_task_form"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Task Title *")
        assigned = c2.text_input("Assigned To * (comma or & separated)")

        c3, c4 = st.columns(2)
        freq = c3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        task_date = c4.date_input("Start Date", datetime.now())

        if st.form_submit_button("Add Task", use_container_width=True):
            if title.strip() and assigned.strip():
                df_latest = get_df("SALES_TEAM_TASK")
                if df_latest is None or df_latest.empty:
                    df_latest = pd.DataFrame()
                    next_id = 1
                else:
                    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]
                    try:
                        extracted = df_latest["TASK ID"].astype(str).str.extract(r"(\d+)")[0]
                        next_id = int(extracted.dropna().astype(int).max()) + 1
                    except Exception:
                        next_id = len(df_latest) + 1

                new_row = pd.DataFrame([{
                    "TASK ID":             str(next_id),
                    "TASK TITLE":          title.strip(),
                    "FREQUENCY":           freq,
                    "ASSIGNED TO":         assigned.strip().upper(),
                    "TASK DATE":           task_date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": "",
                }])
                df_latest = pd.concat([df_latest, new_row], ignore_index=True)
                write_df("SALES_TEAM_TASK", df_latest)
                st.success("Task added (ID: " + str(next_id) + ")")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Task Title and Assigned To are required.")

# ------- TIME PERIOD --------------------------------------------------------
st.write("---")
today = datetime.now()

c1, c2 = st.columns(2)
year = c1.selectbox("Year", [2024, 2025, 2026, 2027], index=2)
month = c2.selectbox(
    "Month",
    list(range(1, 13)),
    index=today.month - 1,
    format_func=lambda m: calendar.month_name[m],
)

tasks = generate_tasks(df_master, year, month)

EMPTY_COLS = [
    "TASK ID", "TASK TITLE", "FREQUENCY", "ASSIGNED TO",
    "EMPLOYEE", "DUE DATE", "STATUS", "LAST COMPLETED DATE",
]

if not tasks.empty:
    tasks["STATUS"] = tasks.apply(get_status, axis=1)
    tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])
else:
    tasks = pd.DataFrame(columns=EMPTY_COLS)
    tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

auto_log_tasks(tasks)

# ------- FREQUENCY SPLITS ---------------------------------------------------
start_week = today - timedelta(days=today.weekday())

if not tasks.empty:
    # Daily — only today's tasks (historical misses are in the log)
    daily_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "daily")
        & (tasks["DUE DATE"].dt.date == today.date())
    ].copy()

    # Adhoc — keep until done; hide completed ones (unless done today)
    adhoc_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "adhoc")
        & (tasks["DUE DATE"].dt.date <= today.date())
        & (
            (tasks["STATUS"] != "Done")
            | (tasks["DUE DATE"].dt.date == today.date())
        )
    ].copy()

    # Weekly — current week only
    weekly_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "weekly")
        & (tasks["DUE DATE"].dt.date >= start_week.date())
        & (tasks["DUE DATE"].dt.date <= today.date())
    ].copy()

    # Monthly — full selected month
    monthly_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "monthly")
        & (tasks["DUE DATE"].dt.month == month)
    ].copy()
else:
    daily_df = pd.DataFrame(columns=EMPTY_COLS)
    adhoc_df = pd.DataFrame(columns=EMPTY_COLS)
    weekly_df = pd.DataFrame(columns=EMPTY_COLS)
    monthly_df = pd.DataFrame(columns=EMPTY_COLS)

# ------- RENDER TASK SECTIONS -----------------------------------------------
st.write("---")

st.subheader("Daily Tasks")
render_task_table(
    daily_df,
    "daily",
    (
        "Shows only TODAY's tasks. Daily tasks must be completed on the same day — "
        "there is no grace period. "
        "Missed = not done on its scheduled day. "
        "Missed tasks are recorded in the performance log automatically."
    ),
    ["Done", "Pending", "Missed"],
)

st.write("")
st.subheader("Adhoc Tasks")
render_task_table(
    adhoc_df,
    "adhoc",
    (
        "One-time or unscheduled tasks. Remain visible and Overdue until marked done. "
        "Once completed they are hidden from this table."
    ),
    ["Done", "Pending", "Overdue"],
)

st.write("")
st.subheader("Weekly Tasks")
render_task_table(
    weekly_df,
    "weekly",
    (
        "Tasks due once a week on a fixed weekday. "
        "Pending = due this week, not yet done. "
        "Overdue = this week's deadline passed without completion."
    ),
    ["Done", "Pending", "Overdue"],
)

st.write("")
st.subheader("Monthly Tasks")
render_task_table(
    monthly_df,
    "monthly",
    (
        "Tasks due once a month on a fixed date. "
        "Pending = due date not yet reached. "
        "Overdue = due date passed without completion."
    ),
    ["Done", "Pending", "Overdue"],
)

# ===========================================================================
# SALES TEAM PERFORMANCE
# ===========================================================================
st.write("---")
st.subheader("Sales Team Performance")
st.caption(
    "Counts are pulled from the daily task log. "
    "Only salespersons with tasks in the selected period are shown. "
    "Click any row to drill down by status."
)

team_df = load_sales_team()
log_df = get_df("TASK_LOGS")

if log_df is None or log_df.empty:
    st.info("No task logs yet. Logs are built automatically each day this page is loaded.")
else:
    log_df.columns = [str(c).strip().upper() for c in log_df.columns]
    log_df["EMPLOYEE"] = log_df["EMPLOYEE"].str.strip().str.upper()
    log_df["DATE"] = pd.to_datetime(log_df["DATE"], dayfirst=True, errors="coerce")

    if "TASK TITLE" not in log_df.columns:
        log_df["TASK TITLE"] = log_df.get("TASK ID", "")
    if "FREQUENCY" not in log_df.columns:
        log_df["FREQUENCY"] = ""

    valid_employees = set(
        team_df["EMPLOYEE"].dropna().str.strip().str.upper().tolist()
    )

    pc1, pc2 = st.columns(2)
    start_date = pc1.date_input(
        "From", datetime(today.year, today.month, 1), key="perf_start"
    )
    end_date = pc2.date_input("To", today, key="perf_end")

    logs_filtered = log_df[
        (log_df["DATE"].dt.date >= start_date)
        & (log_df["DATE"].dt.date <= end_date)
        & (log_df["EMPLOYEE"].isin(valid_employees))
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

        # Inner join: only show employees who have logs in this period
        final = team_df.merge(summary, on="EMPLOYEE", how="inner")
        for col in ["Done", "Pending", "Overdue", "Missed"]:
            final[col] = final[col].astype(int)

        final["Total"] = (
            final["Done"] + final["Pending"] + final["Overdue"] + final["Missed"]
        )
        final["Completion %"] = final.apply(
            lambda r: (str(int(r["Done"] / r["Total"] * 100)) + "%")
            if r["Total"] > 0 else "-",
            axis=1,
        )

        display_cols = [
            c for c in
            ["EMPLOYEE", "Done", "Pending", "Overdue", "Missed", "Total", "Completion %"]
            if c in final.columns
        ]
        st.write("**Summary Table**")
        st.dataframe(final[display_cols], use_container_width=True, hide_index=True)

        st.write("---")
        st.write("**Drill-Down — click a salesperson to view their tasks:**")
        st.caption(
            "Done = completed on time  |  Pending = not yet actioned  |  "
            "Overdue = deadline passed, not done  |  Missed = daily task not done that day"
        )

        for _, erow in final.iterrows():
            employee = str(erow["EMPLOYEE"])
            done_cnt = int(erow.get("Done", 0))
            pending_cnt = int(erow.get("Pending", 0))
            overdue_cnt = int(erow.get("Overdue", 0))
            missed_cnt = int(erow.get("Missed", 0))
            rate = str(erow.get("Completion %", "-"))

            label = (
                "👤 " + employee + "   ·   "
                "✅ " + str(done_cnt) + " Done   "
                "📋 " + str(pending_cnt) + " Pending   "
                "🔴 " + str(overdue_cnt) + " Overdue   "
                "❌ " + str(missed_cnt) + " Missed   "
                "| " + rate + " completion"
            )

            with st.expander(label):
                emp_logs = logs_filtered[
                    logs_filtered["EMPLOYEE"] == employee
                ][["TASK TITLE", "FREQUENCY", "DATE", "STATUS"]].copy()

                emp_logs["DATE"] = emp_logs["DATE"].dt.strftime("%d-%b-%Y")
                emp_logs = emp_logs.sort_values("DATE", ascending=False)

                if emp_logs.empty:
                    st.info("No log entries found.")
                else:
                    tab_done, tab_pending, tab_overdue, tab_missed = st.tabs([
                        "✅ Done (" + str(done_cnt) + ")",
                        "📋 Pending (" + str(pending_cnt) + ")",
                        "🔴 Overdue (" + str(overdue_cnt) + ")",
                        "❌ Missed (" + str(missed_cnt) + ")",
                    ])

                    show_tab_content(
                        tab_done, emp_logs, "Done",
                        "No completed tasks in this range.",
                        "Tasks that were marked done.",
                    )
                    show_tab_content(
                        tab_pending, emp_logs, "Pending",
                        "No pending tasks in this range.",
                        "Tasks scheduled but not yet actioned.",
                    )
                    show_tab_content(
                        tab_overdue, emp_logs, "Overdue",
                        "No overdue tasks in this range.",
                        "Weekly / Monthly / Adhoc tasks past their deadline.",
                    )
                    show_tab_content(
                        tab_missed, emp_logs, "Missed",
                        "No missed daily tasks in this range.",
                        "Daily tasks not completed on their scheduled date.",
                    )

st.write("---")
st.info(
    "Daily automated emails are sent at 10 AM (morning brief) "
    "and 8 PM (end-of-day report)."
)
