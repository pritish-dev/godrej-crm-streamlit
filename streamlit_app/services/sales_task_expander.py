"""
services/sales_task_expander.py

Expands the SALES_TEAM_TASK master sheet into per-day, per-employee rows
the same way pages/90_Sales_Team_Tasks.py does.

Master sheet stores TEMPLATES (TASK DATE = start date, FREQUENCY = daily/weekly/
monthly/adhoc, ASSIGNED TO = comma/&-separated names). Real occurrences are
generated dynamically — they are NOT saved to the sheet — so the email jobs
must replicate the same expansion before filtering by today's date.
"""

import re
import calendar
import pandas as pd
from datetime import datetime, date, timedelta

# Weekday-name → Python weekday() index (Mon=0 … Sun=6)
WEEKDAY_NAME_TO_IDX = {
    "MON": 0, "MONDAY": 0,
    "TUE": 1, "TUES": 1, "TUESDAY": 1,
    "WED": 2, "WEDS": 2, "WEDNESDAY": 2,
    "THU": 3, "THURS": 3, "THURSDAY": 3,
    "FRI": 4, "FRIDAY": 4,
    "SAT": 5, "SATURDAY": 5,
    "SUN": 6, "SUNDAY": 6,
}


def load_employee_weekoff_map() -> dict:
    """
    Returns {EMPLOYEE_NAME_UPPER: weekday_idx (0-6)} for every Sales-team
    member who has a "WEEKOFF" entry in the "Sales Team" sheet.

    Empty / unrecognised values are skipped (no weekoff applied).
    """
    try:
        from services.sheets import get_df
        team = get_df("Sales Team")
    except Exception:
        return {}

    if team is None or team.empty:
        return {}

    team.columns = [str(c).strip().upper() for c in team.columns]
    name_col = "NAME" if "NAME" in team.columns else (
        "EMPLOYEE" if "EMPLOYEE" in team.columns else None)
    if name_col is None or "WEEKOFF" not in team.columns:
        return {}

    out = {}
    for _, row in team.iterrows():
        name = str(row.get(name_col, "")).strip().upper()
        wk   = str(row.get("WEEKOFF", "")).strip().upper()
        if not name or not wk:
            continue
        idx = WEEKDAY_NAME_TO_IDX.get(wk)
        if idx is None:
            # Try first 3 letters as fallback (e.g. "Sunday Night")
            idx = WEEKDAY_NAME_TO_IDX.get(wk[:3])
        if idx is not None:
            out[name] = idx
    return out


# ── helpers ──────────────────────────────────────────────────────────────────
def parse_employees(assigned_str):
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


# ── core expansion ───────────────────────────────────────────────────────────
def expand_master_tasks(df_master: pd.DataFrame, year: int, month: int,
                        weekoff_map: dict | None = None) -> pd.DataFrame:
    """
    Given the master sheet, return a DataFrame of one row per
    (TASK ID, EMPLOYEE, DUE DATE) for the given year/month.

    If `weekoff_map` is provided ({EMP_UPPER: weekday_idx}) DAILY tasks are
    NOT generated for an employee on their weekoff day. Weekly / Monthly /
    Adhoc tasks are not affected by weekoff.
    """
    if df_master is None or df_master.empty:
        return pd.DataFrame()

    df = df_master.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]

    if "TASK DATE" not in df.columns:
        return pd.DataFrame()
    if "LAST COMPLETED DATE" not in df.columns:
        df["LAST COMPLETED DATE"] = ""

    df["START DATE"] = df["TASK DATE"].apply(parse_date)
    df["LAST COMPLETED DATE"] = df["LAST COMPLETED DATE"].apply(parse_date)

    if weekoff_map is None:
        weekoff_map = {}

    rows = []
    for _, row in df.iterrows():
        freq = str(row.get("FREQUENCY", "")).strip().lower()
        start = row["START DATE"]
        if pd.isna(start):
            continue
        employees = parse_employees(row.get("ASSIGNED TO", ""))
        if not employees:
            continue

        if freq == "adhoc":
            due_dates = [start.to_pydatetime() if hasattr(start, "to_pydatetime") else start]
        else:
            due_dates = []
            for day in range(1, 32):
                try:
                    current = datetime(year, month, day)
                except ValueError:
                    continue
                if current.date() < start.date():
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
                # Skip daily tasks if this is the employee's weekoff day
                if freq == "daily":
                    wk = weekoff_map.get(emp.upper())
                    if wk is not None and due.weekday() == wk:
                        continue

                new_row = row.copy()
                new_row["DUE DATE"] = due
                new_row["EMPLOYEE"] = emp
                rows.append(new_row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out["DUE DATE"] = pd.to_datetime(out["DUE DATE"], errors="coerce")
    return out


# ── status (mirrors pages/90 logic) ──────────────────────────────────────────
def compute_status(row, today: date) -> str:
    freq = str(row.get("FREQUENCY", "")).strip().lower()
    due = row["DUE DATE"].date() if pd.notna(row["DUE DATE"]) else None
    lcd = row["LAST COMPLETED DATE"].date() if pd.notna(row.get("LAST COMPLETED DATE")) else None

    if due is None:
        return "🟡 Pending"

    if freq == "daily":
        if lcd is not None and lcd == due:
            return "🟢 Done"
        return "🔴 Missed" if due < today else "🟡 Pending"
    else:
        if lcd is not None and lcd >= due:
            return "🟢 Done"
        return "🔴 Overdue" if due < today else "🟡 Pending"


def expand_with_status(df_master: pd.DataFrame, today: date,
                       weekoff_map: dict | None = None) -> pd.DataFrame:
    """Expand master sheet for today's month and attach STATUS column."""
    if weekoff_map is None:
        weekoff_map = load_employee_weekoff_map()
    expanded = expand_master_tasks(df_master, today.year, today.month, weekoff_map=weekoff_map)
    if expanded.empty:
        return expanded
    expanded["STATUS"] = expanded.apply(lambda r: compute_status(r, today), axis=1)
    return expanded


def get_missed_tasks(df_master: pd.DataFrame, today: date,
                     weekoff_map: dict | None = None) -> pd.DataFrame:
    """
    Return ALL un-completed tasks across the current month grouped under
    'missed' status:
      - Daily   tasks past their due date and never completed → Missed
      - Weekly/Monthly/Adhoc tasks past their due date & never completed → Overdue
    Used by the end-of-day status email and the monthly performance email.
    """
    if weekoff_map is None:
        weekoff_map = load_employee_weekoff_map()
    expanded = expand_with_status(df_master, today, weekoff_map=weekoff_map)
    if expanded.empty:
        return expanded

    missed = expanded[
        expanded["STATUS"].str.contains("Missed|Overdue", na=False)
        & (expanded["DUE DATE"].dt.date <= today)
    ].copy()
    return missed


def get_today_and_overdue(df_master: pd.DataFrame, today: date):
    """
    Return (today_tasks, overdue_pending) — ready for the email senders.

    today_tasks    : all expanded rows whose DUE DATE == today
    overdue_pending: weekly/monthly/adhoc rows with DUE DATE < today AND not done
                     (daily misses are tracked separately as 'Missed')
    """
    weekoff_map = load_employee_weekoff_map()
    expanded = expand_with_status(df_master, today, weekoff_map=weekoff_map)
    if expanded.empty:
        return pd.DataFrame(), pd.DataFrame()

    today_tasks = expanded[expanded["DUE DATE"].dt.date == today].copy()

    # Overdue = past-due, still pending (excludes daily — those become Missed)
    overdue = expanded[
        (expanded["DUE DATE"].dt.date < today)
        & (expanded["STATUS"].str.contains("Pending|Overdue", na=False))
        & (expanded["FREQUENCY"].astype(str).str.strip().str.lower() != "daily")
    ].copy()

    # If someone is staring at the email a week later, monthly tasks could
    # accumulate forever — keep overdue limited to the current month + last 30 days
    cutoff = today - timedelta(days=30)
    overdue = overdue[overdue["DUE DATE"].dt.date >= cutoff]

    return today_tasks, overdue
