# 📋 Sales Team Task Generation Logic

## Overview
Tasks are generated dynamically based on their frequency and assigned to sales persons according to the pattern established when they were created.

---

## Task Frequency Types

### 1. **Daily Tasks** 🟣
- **Definition:** Task repeats every single day
- **Generation:** Creates an instance for every day of the selected month
- **Assignment:** Assigned to the same sales person who was originally assigned
- **Display:** Shows only tasks due today or earlier (in Daily & Adhoc table)
- **Example:** 
  - Created: 1 Apr 2026, Assigned to: John
  - Generated for April: 1, 2, 3, 4, ... 30 (every day)
  - John gets the task every single day

**Code Logic:**
```python
if freq == "daily":
    pass  # Adds task for every day in the loop
```

---

### 2. **Weekly Tasks** 📅
- **Definition:** Task repeats on the same day of the week
- **Generation:** Creates instances for the same weekday each week of the selected month
- **Assignment:** Assigned to the same sales person
- **Display:** Shows only tasks from start of current week to today
- **Example:**
  - Created: Monday, 1 Apr 2026, Assigned to: Sarah
  - Generated for April: Mon 1, Mon 8, Mon 15, Mon 22, Mon 29
  - Sarah gets the task every Monday

**Code Logic:**
```python
elif freq == "weekly":
    if current.weekday() != start.weekday():
        continue  # Only add on matching weekday
```

---

### 3. **Monthly Tasks** 🗓️
- **Definition:** Task repeats on the same day of each month
- **Generation:** Creates instances for the same date each month
- **Assignment:** Assigned to the same sales person
- **Display:** Shows all monthly task instances for the selected month
- **Example:**
  - Created: 15 Apr 2026, Assigned to: Mike
  - Generated for each month: 15th
  - Mike gets the task on the 15th of every month

**Code Logic:**
```python
elif freq == "monthly":
    if current.day != start.day:
        continue  # Only add on matching day of month
```

---

### 4. **Ad-Hoc Tasks** (One-time)
- **Definition:** Task is created for a specific date, does not repeat
- **Generation:** Creates a single instance on the specified date
- **Assignment:** Assigned to the specified sales person
- **Display:** Shows in Daily & Adhoc table if due today or earlier
- **Example:**
  - Created: 5 Apr 2026, Assigned to: Lisa
  - Generated: Only 5 Apr 2026 (no repeating)
  - Lisa gets this task only once

**Code Logic:**
```python
if freq == "adhoc":
    new_row = row.copy()
    new_row["DUE DATE"] = start
    rows.append(new_row)
    continue  # Don't loop, just add this one instance
```

---

## Task Display Logic

### Daily & Adhoc Tasks Table
Shows **today's due tasks and overdue tasks** (due date ≤ today)

```python
daily_df = tasks[
    (tasks["FREQUENCY"].str.lower().isin(["daily", "adhoc"])) &
    (tasks["DUE DATE"].dt.date <= today.date())
]
```

**Use Case:** See what needs to be done TODAY

---

### Weekly Tasks Table
Shows **current week's tasks** (from Monday to today)

```python
start_week = today - timedelta(days=today.weekday())

weekly_df = tasks[
    (tasks["FREQUENCY"].str.lower() == "weekly") &
    (tasks["DUE DATE"].dt.date >= start_week.date()) &
    (tasks["DUE DATE"].dt.date <= today.date())
]
```

**Use Case:** See what weekly tasks are currently active this week

---

### Monthly Tasks Table
Shows **all monthly task instances for the selected month**

```python
monthly_df = tasks[
    (tasks["FREQUENCY"].str.lower() == "monthly") &
    (tasks["DUE DATE"].dt.month == month)
]
```

**Use Case:** See all monthly tasks assigned in the dashboard month view

---

## Task Marking & Status

### Automatic Status Assignment
When a task is displayed, it gets one of these statuses:

1. **🟢 Done** - Task completed before due date
2. **🔴 Overdue** - Task due date passed but not completed  
3. **🟡 Pending** - Task not yet due and not completed
4. **🔴 Missed** - Task completed after due date

### Marking Tasks as Done
- Click the **✓** checkbox next to any task to mark it complete
- The "Last Completed Date" is updated to today
- Status automatically changes to 🟢 Done

### Logging
- Every task completion/status is logged to TASK_LOGS sheet
- Tracks: Task ID, Employee, Date, Status
- Used for performance reporting and analytics

---

## Example Scenario

**Setup:**
- Sales person: "John"
- Daily task created: "Follow up calls" on 1 Apr 2026
- Weekly task created: "Status report" on every Monday, starting 1 Apr
- Monthly task created: "Team meeting" on 15th of each month, starting 15 Apr

**What John will see in April 2026:**

| Task | Type | Dates | Status |
|------|------|-------|--------|
| Follow up calls | Daily | 1,2,3...30 Apr | Depends on completion |
| Status report | Weekly | 1,8,15,22,29 Apr (Mondays) | Depends on completion |
| Team meeting | Monthly | 15 Apr | Depends on completion |

**What John will see in May 2026:**

| Task | Type | Dates | Status |
|------|------|-------|--------|
| Follow up calls | Daily | 1,2,3...31 May | Depends on completion |
| Status report | Weekly | 5,12,19,26 May (Mondays) | Depends on completion |
| Team meeting | Monthly | 15 May | Depends on completion |

---

## Key Points

✅ **Assignments stick:** Once assigned to a sales person, they get the task every recurring cycle  
✅ **No manual re-creation:** Daily/Weekly/Monthly tasks create themselves automatically  
✅ **Date-smart:** Tasks are generated for the selected month in the dashboard  
✅ **Status tracking:** Every task instance is tracked separately for reporting  
✅ **One-time tasks:** Ad-hoc tasks don't repeat, they appear once

---

## Troubleshooting

**Q: I created a daily task but it's not showing?**
- Check if the task's start date is in the selected month
- Daily tasks only show if due today or earlier (not future dates)

**Q: Weekly task is not appearing on the right day?**
- Verify the day of week when you created the task
- Weekly tasks repeat on the same weekday, not day of month

**Q: Monthly task not showing?**
- Monthly tasks only show for the selected month view
- If created on the 31st, it won't appear in months with fewer days

---

Last Updated: 29 Apr 2026
