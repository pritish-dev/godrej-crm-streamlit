"""
pages/90_Sales_Team_Tasks.py  —  Sales Team Task Dashboard
========================================================
Design decisions:
- "ASSIGNED TO" supports mixed separators: comma (,) and ampersand (&)
  e.g. "SWATI , ARCHITA & RANGANATH" → ['SWATI', 'ARCHITA', 'RANGANATH']
- Each task is expanded into ONE ROW PER EMPLOYEE in the task tables
  so every salesperson sees only their own tasks.
- Status rules by frequency:
    DAILY  → Done | Missed | Pending       (never Overdue — must act same day)
    WEEKLY / MONTHLY / ADHOC → Done | Overdue | Pending
- Performance logs one row per (TASK ID, EMPLOYEE, DATE) and upserts on change.
"""
import re
import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, write_df

st.set_page_config(layout="wide", page_title="Sales Team Tasks")

# ── helpers ──────────────────────────────────────────────────────────────────

def parse_employees(assigned_str):
    """Split 'SWATI , ARCHITA & RANGANATH' → ['SWATI', 'ARCHITA', 'RANGANATH']"""
    parts = re.split(r"[,&]", str(assigned_str))
    return [p.strip().upper() for p in parts if p.strip()]


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


# ── data loaders ─────────────────────────────────────────────────────────────

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


# ── task generation ───────────────────────────────────────────────────────────

def generate_tasks(df, year, month):
    """Expand master task rows into (task × occurrence × employee) rows."""
    rows = []
    for _, row in df.iterrows():
        freq  = str(row["FREQUENCY"]).strip().lower()
        start = row["START DATE"]
        if pd.isna(start):
            continue

        employees = parse_employees(row.get("ASSIGNED TO", ""))
        if not employees:
            continue

        # Build list of due-dates for this task in the requested month
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

        # One row per (due-date × employee)
        for due in due_dates:
            for emp in employees:
                new_row = row.copy()
                new_row["DUE DATE"]   = due
                new_row["EMPLOYEE"]   = emp          # individual employee name
                rows.append(new_row)

    return pd.DataFrame(rows)


# ── status logic ──────────────────────────────────────────────────────────────
#
#  DAILY  : LCD == DUE → Done | due < today → Missed | else → Pending
#  OTHERS : LCD >= DUE → Done | due < today → Overdue | else → Pending
#
# ─────────────────────────────────────────────────────────────────────────────

def get_status(row):
    today = datetime.now().date()
    freq  = str(row.get("FREQUENCY", "")).strip().lower()
    due   = row["DUE DATE"].date() if pd.notna(row["DUE DATE"]) else None
    lcd   = row["LAST COMPLETED DATE"].date() if pd.notna(row["LAST COMPLETED DATE"]) else None

    if due is None:
        return "Pending"

    if freq == "daily":
        if lcd is not None and lcd == due:
            return "Done"
        return "Missed" if due < today else "Pending"
    else:   # weekly / monthly / adhoc
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
    "Done":    "✅ Done",
    "Pending": "🟡 Pending",
    "Overdue": "🔴 Overdue",
    "Missed":  "❌ Missed",
}


# ── task update ───────────────────────────────────────────────────────────────

def update_task(task_id):
    today_str = datetime.now().strftime("%d-%m-%Y")
    df = get_df("SALES_TEAM_TASK")
    if df is None or df.empty:
        return
    df.columns = [str(c).strip().upper() for c in df.columns]
    df.loc[df["TASK ID"].astype(str).str.strip() == str(task_id).strip(),
           "LAST COMPLETED DATE"] = today_str
    write_df("SALES_TEAM_TASK", df)
    st.cache_data.clear()


# ── auto-log ──────────────────────────────────────────────────────────────────

def auto_log_tasks(tasks):
    """Upsert one TASK_LOGS row per (TASK ID, EMPLOYEE, DATE=today)."""
    log_df = get_df("TASK_LOGS")
    COLS   = ["TASK ID", "TASK TITLE", "FREQUENCY", "EMPLOYEE", "DATE", "STATUS"]

    if log_df is None or log_df.empty:
        log_df = pd.DataFrame(columns=COLS)
    else:
        log_df.columns = [str(c).strip().upper() for c in log_df.columns]
        for col in COLS:
            if col not in log_df.columns:
                log_df[col] = ""

    today_str  = datetime.now().strftime("%d-%m-%Y")
    today_date = datetime.now().date()
    changed    = False

    for _, row in tasks.iterrows():
        due_date = row["DUE DATE"].date() if pd.notna(row["DUE DATE"]) else None
        if due_date is None or due_date > today_date:
            continue

        raw    = row.get("STATUS", "Pending")
        status = raw if raw in ("Done", "Pending", "Overdue", "Missed") else "Pending"

        task_id    = str(row.get("TASK ID", "")).strip()
        task_title = str(row.get("TASK TITLE", "")).strip()
        frequency  = str(row.get("FREQUENCY", "")).strip()
        emp        = str(row.get("EMPLOYEE", "")).strip().upper()

        if not emp:
            continue

        mask = (
            (log_df["TASK ID"].astype(str).str.strip() == task_id) &
            (log_df["EMPLOYEE"].str.strip().str.upper() == emp) &
            (log_df["DATE"].astype(str).str.strip() == today_str)
        )

        if mask.any():
            if log_df.loc[mask, "STATUS"].values[0] != status:
                log_df.loc[mask, "STATUS"]     = status
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
                "STATUS":     status,
            }])], ignore_index=True)
            changed = True

    if changed:
        write_df("TASK_LOGS", log_df)


# ── render table ──────────────────────────────────────────────────────────────

def render_task_table(df, freq_type, helper_text, valid_statuses):
    """
    df           : already-expanded per-employee DataFrame
    freq_type    : 'daily' | 'weekly' | 'monthly'
    helper_text  : caption shown below section title
    valid_statuses: list of status values that can appear in this section
    """
    st.caption(helper_text)

    if df.empty:
        st.info("No tasks for this period.")
        return

    # Individual employee filter — extracted from the EMPLOYEE column (already split)
    all_employees = sorted(df["EMPLOYEE"].dropna().unique().tolist())
    emp_options   = ["All"] + all_employees
    status_opts   = ["All"] + sorted(df["STATUS"].unique().tolist())

    fc1, fc2 = st.columns([2, 2])
    sel_emp = fc1.selectbox(
        "👤 Filter by Salesperson", emp_options,
        key=f"emp_{freq_type}", label_visibility="visible"
    )
    sel_status = fc2.selectbox(
        "🔍 Filter by Status", status_opts,
        key=f"st_{freq_type}", label_visibility="visible"
    )

    fdf = df.copy()
    if sel_emp != "All":
        fdf = fdf[fdf["EMPLOYEE"] == sel_emp]
    if sel_status != "All":
        fdf = fdf[fdf["STATUS"] == sel_status]

    if fdf.empty:
        st.warning("No tasks match the selected filters.")
        return

    # ── metrics ──
    mc = st.columns(len(valid_statuses))
    icons_map = {"Done": "✅ Done", "Pending": "📋 Pending",
                 "Overdue": "🔴 Overdue", "Missed": "❌ Missed"}
    for i, s in enumerate(valid_statuses):
        mc[i].metric(icons_map.get(s, s), int((fdf["STATUS"] == s).sum()))

    st.write("")
    # ── column headers ──
    h1, h2, h3, h4, h5, h6 = st.columns([0.7, 2.8, 1.8, 1.5, 1.8, 1.4])
    h1.markdown("**✓**"); h2.markdown("**Task**"); h3.markdown("**Salesperson**")
    h4.markdown("**Due Date**"); h5.markdown("**Status**"); h6.markdown("**Frequency**")
    st.divider()

    for _, row in fdf.iterrows():
        task_id  = str(row["TASK ID"]).strip()
        due_dt   = row["DUE DATE"]
        due_key  = due_dt.strftime("%Y%m%d") if pd.notna(due_dt) else "na"
        emp_key  = row["EMPLOYEE"].replace(" ", "_")
        cb_key   = f"cb_{freq_type}_{task_id}_{due_key}_{emp_key}"
        status   = row["STATUS"]
        is_done  = (status == "Done")

        r1, r2, r3, r4, r5, r6 = st.columns([0.7, 2.8, 1.8, 1.5, 1.8, 1.4])

        with r1:
            if is_done:
                st.write("✅")
            else:
                if st.checkbox("done", key=cb_key,
                               label_visibility="collapsed", help="Mark this task as done"):
                    update_task(task_id)
                    st.rerun()

        r2.write(row["TASK TITLE"])
        r3.write(row["EMPLOYEE"])
        r4.write(due_dt.strftime("%d-%b-%Y") if pd.notna(due_dt) else "N/A")

        with r5:
            color = STATUS_COLOR.get(status, "#FFFFFF")
            label = STATUS_ICON.get(status, status)
            st.markdown(
                f'<div style="background:{color};padding:5px 8px;border-radius:5px;'
                f'text-align:center;font-weight:bold;font-size:12px;">{label}</div>',
                unsafe_allow_html=True,
            )

        r6.write(str(row["FREQUENCY"]).capitalize())
        st.divider()


# =============================================================================
# MAIN UI
# =============================================================================
st.title("📋 Sales Team Task Dashboard")
st.caption(
    "Manage, track and monitor daily/weekly/monthly tasks for the sales team. "
    "Use the checkboxes to mark tasks as done. The performance section at the bottom "
    "tracks each salesperson's completion record."
)

df_master = load_tasks()

# ── CREATE TASK ───────────────────────────────────────────────────────────────
with st.expander("➕ Add New Task", expanded=False):
    st.caption(
        "Create a new recurring or one-time task. "
        "For multiple assignees use comma (,) or & to separate names — "
        "e.g.  SWATI , ARCHITA & RANGANATH"
    )
    with st.form("new_task_form"):
        c1, c2 = st.columns(2)
        title    = c1.text_input("Task Title *")
        assigned = c2.text_input("Assigned To * (comma or & separated)")

        c3, c4, c5 = st.columns(3)
        freq      = c3.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "ADHOC"])
        task_date = c4.date_input("Start Date", datetime.now())
        _         = c5.empty()   # spacer

        if st.form_submit_button("➕ Add Task", use_container_width=True):
            if title.strip() and assigned.strip():
                df_latest = get_df("SALES_TEAM_TASK")
                if df_latest is None or df_latest.empty:
                    df_latest = pd.DataFrame()
                    next_id   = 1
                else:
                    df_latest.columns = [str(c).strip().upper() for c in df_latest.columns]
                    try:
                        next_id = int(
                            df_latest["TASK ID"].astype(str)
                            .str.extract(r"(\d+)")[0].dropna().astype(int).max()
                        ) + 1
                    except Exception:
                        next_id = len(df_latest) + 1

                df_latest = pd.concat([df_latest, pd.DataFrame([{
                    "TASK ID":             str(next_id),
                    "TASK TITLE":          title.strip(),
                    "FREQUENCY":           freq,
                    "ASSIGNED TO":         assigned.strip().upper(),
                    "TASK DATE":           task_date.strftime("%d-%m-%Y"),
                    "LAST COMPLETED DATE": "",
                }])], ignore_index=True)
                write_df("SALES_TEAM_TASK", df_latest)
                st.success(f"✅ Task '{title.strip()}' created (ID: {next_id})")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Task Title and Assigned To are required.")

# ── TIME PERIOD ───────────────────────────────────────────────────────────────
st.write("---")
today = datetime.now()

c1, c2 = st.columns(2)
year  = c1.selectbox("Year",  [2024, 2025, 2026, 2027], index=2)
month = c2.selectbox(
    "Month",
    list(range(1, 13)),
    index=today.month - 1,
    format_func=lambda m: calendar.month_name[m],
)

# Generate expanded rows (one per task × employee occurrence)
tasks = generate_tasks(df_master, year, month)

EMPTY_COLS = ["TASK ID", "TASK TITLE", "FREQUENCY", "ASSIGNED TO",
              "EMPLOYEE", "DUE DATE", "STATUS", "LAST COMPLETED DATE"]

if not tasks.empty:
    tasks["STATUS"]   = tasks.apply(get_status, axis=1)
    tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])
else:
    tasks = pd.DataFrame(columns=EMPTY_COLS)
    tasks["DUE DATE"] = pd.to_datetime(tasks["DUE DATE"])

# Auto-log today's statuses to TASK_LOGS
auto_log_tasks(tasks)

# ── FREQUENCY SPLITS ──────────────────────────────────────────────────────────
start_week = today - timedelta(days=today.weekday())   # Monday of this week

if not tasks.empty:
    # Daily — show ONLY today's tasks (must act same day; history is in the log)
    daily_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "daily") &
        (tasks["DUE DATE"].dt.date == today.date())
    ].copy()

    # Adhoc — keep in table until done; once done hide (unless completed today)
    adhoc_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "adhoc") &
        (tasks["DUE DATE"].dt.date <= today.date()) &
        (
            (tasks["STATUS"] != "Done") |                              # still open
            (tasks["DUE DATE"].dt.date == today.date())                # or due today (just done)
        )
    ].copy()

    weekly_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "weekly") &
        (tasks["DUE DATE"].dt.date >= start_week.date()) &
        (tasks["DUE DATE"].dt.date <= today.date())
    ].copy()

    monthly_df = tasks[
        (tasks["FREQUENCY"].str.lower() == "monthly") &
        (tasks["DUE DATE"].dt.month == month)
    ].copy()
else:
    daily_df = adhoc_df = weekly_df = monthly_df = pd.DataFrame(columns=EMPTY_COLS)

# ── RENDER SECTION: DAILY ────────────────────────────────────────────────────
st.write("---")
st.subheader("🟣 Daily Tasks")
render_task_table(
    daily_df, "daily",
    helper_text=(
        "These tasks must be completed **on the same day**. There is no grace period. "
        "✅ Done = marked done today  |  ❌ Missed = not done on that day  |  🟡 Pending = today's task, not yet done. "
        "Missed tasks cannot be converted to Overdue — they are simply logged as missed."
    ),
    valid_statuses=["Done", "Pending", "Missed"],
)

# ── RENDER SECTION: ADHOC ─────────────────────────────────────────────────────
st.write("")
st.subheader("📌 Adhoc Tasks")
render_task_table(
    adhoc_df, "adhoc",
    helper_text=(
        "One-time or unscheduled tasks. They remain 🔴 Overdue until completed. "
        "Mark them done as soon as the action is taken."
    ),
    valid_statuses=["Done", "Pending", "Overdue"],
)

# ── RENDER SECTION: WEEKLY ───────────────────────────────────────────────────
st.write("")
st.subheader("📅 Weekly Tasks")
render_task_table(
    weekly_df, "weekly",
    helper_text=(
        "Tasks to be completed once a week on a fixed day. "
        "🟡 Pending = due this week, not yet done  |  🔴 Overdue = missed this week's deadline. "
        "Completing an overdue task still marks it ✅ Done."
    ),
    valid_statuses=["Done", "Pending", "Overdue"],
)

# ── RENDER SECTION: MONTHLY ──────────────────────────────────────────────────
st.write("")
st.subheader("🗓️ Monthly Tasks")
render_task_table(
    monthly_df, "monthly",
    helper_text=(
        "Tasks to be completed once a month on a fixed date. "
        "🟡 Pending = due date not yet passed  |  🔴 Overdue = due date passed without completion. "
        "Completing an overdue task still marks it ✅ Done."
    ),
    valid_statuses=["Done", "Pending", "Overdue"],
)

# =============================================================================
# SALES TEAM PERFORMANCE
# =============================================================================
st.write("---")
st.subheader("📊 Sales Team Performance")
st.caption(
    "Tracks cumulative task completion for each salesperson over a selected date range. "
    "The log is updated automatically every time this page loads. "
    "Click any employee row to expand and see the exact tasks by status."
)

team_df = load_sales_team()
log_df  = get_df("TASK_LOGS")

if log_df is None or log_df.empty:
    st.info("No task logs found. Logs are generated automatically each day this page is viewed.")
else:
    log_df.columns = [str(c).strip().upper() for c in log_df.columns]
    log_df["EMPLOYEE"] = log_df["EMPLOYEE"].str.strip().str.upper()
    log_df["DATE"]     = pd.to_datetime(log_df["DATE"], dayfirst=True, errors="coerce")

    # Backward compat — old logs may lack TASK TITLE / FREQUENCY
    if "TASK TITLE" not in log_df.columns:
        log_df["TASK TITLE"] = log_df.get("TASK ID", "—")
    if "FREQUENCY" not in log_df.columns:
        log_df["FREQUENCY"] = ""

    pc1, pc2 = st.columns(2)
    start_date = pc1.date_input(
        "📅 From", datetime(today.year, today.month, 1), key="perf_start"
    )
    end_date = pc2.date_input(
        "📅 To", today, key="perf_end"
    )

    # Valid individual employee names from the Sales Team sheet
    valid_employees = set(team_df["EMPLOYEE"].dropna().str.strip().str.upper().tolist())

    logs_filtered = log_df[
        (log_df["DATE"].dt.date >= start_date) &
        (log_df["DATE"].dt.date <= end_date) &
        # Only rows where EMPLOYEE is a valid individual name (strips old combined entries
        # like "ARCHITA & RANGANATH" that were logged by the previous code version)
        (log_df["EMPLOYEE"].isin(valid_employees))
    ].copy()

    if logs_filtered.empty:
        st.info("No task data in the selected date range.")
    else:
        # ── summary pivot ────────────────────────────────────────────────────
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

        # Inner join — only show salespeople who actually have tasks in this period
        final = team_df.merge(summary, on="EMPLOYEE", how="inner")
        for col in ["Done", "Pending", "Overdue", "Missed"]:
            final[col] = final[col].astype(int)

        # Completion rate
        final["Total"] = final["Done"] + final["Pending"] + final["Overdue"] + final["Missed"]
        final["Completion %"] = final.apply(
            lambda r: f"{int(r['Done'] / r['Total'] * 100)}%" if r["Total"] > 0 else "—", axis=1
        )

        display_cols = ["EMPLOYEE", "Done", "Pending", "Overdue", "Missed", "Total", "Completion %"]
        display_cols = [c for c in display_cols if c in final.columns]

        st.write("**Summary Table** — only salespersons with tasks assigned in this period are shown")
        st.dataframe(final[display_cols], use_container_width=True, hide_index=True)

        # ── per-employee drill-down ───────────────────────────────────────────
        st.write("---")
        st.write("**🔍 Drill-Down — click a salesperson to view their tasks:**")
        st.caption(
            "Done = completed on time  |  Pending = not yet actioned  |  "
            "Overdue = deadline passed, not done  |  Missed = daily task not done that day"
        )

        for _, erow in final.iterrows():
            employee    = erow["EMPLOYEE"]
            done_cnt    = int(erow.get("Done",    0))
            pending_cnt = int(erow.get("Pending", 0))
            overdue_cnt = int(erow.get("Overdue", 0))
            missed_cnt  = int(erow.get("Missed",  0))
            total       = int(erow.get("Total",   0))
            rate        = erow.get("Completion %", "—")

            label = (
                f"👤 {employee}   ·   "
                f"✅ {done_cnt} Done   "
                f"📋 {pending_cnt} Pending   "
                f"🔴 {overdue_cnt} Overdue   "
                f"❌ {missed_cnt} Missed   "
                f"| {rate} completion"
            )

            with st.expander(label):
                emp_logs = logs_filtered[
                    logs_filtered["EMPLOYEE"] == employee
                ][["TASK TITLE", "FREQUENCY", "DATE", "STATUS"]].copy()

                emp_logs["DATE"] = emp_logs["DATE"].dt.strftime("%d-%b-%Y")
                emp_logs = emp_logs.sort_values("DATE", ascending=False)

                if emp_logs.empty:
                    st.info("No log entries found for this salesperson in the selected range.")
                else:
                    tab_done, tab_pending, tab_overdue, tab_missed = st.tabs(
                        [f"✅ Done ({done_cnt})",
                         f"📋 Pending ({pending_cnt})",
                         f"🔴 Overdue ({overdue_cnt})",
                         f"❌ Missed ({missed_cnt})"]
                    )

                    def _show_tab(tab, status_val, empty_msg, help_text=""):
                        with tab:
                            if help_text:
                                st.caption(help_text)
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

                    _show_tab(tab_done,    "Done",
                              "No completed tasks in this range.",
                              "Tasks that were marked done within the deadline.")
                    _show_tab(tab_pending, "Pending",
                              "No pending tasks in this range.",
                              "Tasks that are scheduled but not yet actioned.")
                    _show_tab(tab_overdue, "Overdue",
                              "No overdue tasks in this range.",
                              "Weekly / Monthly / Adhoc tasks whose deadline has passed without completion.")
                    _show_tab(tab_missed,  "Missed",
                              "No missed daily tasks in this range.",
                              "Daily tasks that were not completed on their scheduled date.")

st.write("---")
st.info(
    "ℹ️  Daily automated summary emails are sent at **10 AM** (morning brief) and "
    "**8 PM** (end-of-day status report) to the team."
)
adline.")
                    _show_tab(tab_pending, "Pending",
                              "No pending tasks in this range.",
                              "Tasks that are scheduled but not yet actioned.")
                    _show_tab(tab_overdue, "Overdue",
                              "No overdue tasks in this range.",
                              "Weekly / Monthly / Adhoc tasks whose deadline has passed without completion.")
                    _show_tab(tab_missed,  "Missed",
                              "No missed daily tasks in this range.",
                              "Daily tasks that were not completed on their scheduled date.")

st.write("---")
st.info(
    "ℹ️  Daily automated summary emails are sent at **10 AM** (morning brief) and "
    "**8 PM** (end-of-day status report) to the team."
)
