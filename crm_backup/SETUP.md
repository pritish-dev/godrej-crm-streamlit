# CRM + OPS Daily Backup — Apps Script setup (one time, ~5 minutes)

This replaces the GitHub Actions backup job. It runs inside Google as **your**
account, so:

- the duplicate sheets are owned by you (no service-account quota problem), and
- there is **no OAuth refresh token** to expire — no need to publish the OAuth app.

Every night at about 10 PM IST it creates `backup_<date>_crm_sheet` and
`backup_<date>_ops_sheet` in the **B2C CRM BACKUP** folder and moves backups
older than 7 days to the trash.

## Steps

1. Sign in to Google with the account that **owns the B2C CRM BACKUP folder**
   and can open both the CRM and OPS sheets.
2. Open <https://script.google.com> → **New project**. Rename it to
   `CRM Daily Backup`.
3. Delete the sample code and paste the full contents of
   [`crm_backup/Code.gs`](Code.gs).
4. Fill in the three IDs at the top of the file:
   - `CRM_SPREADSHEET_ID` — already filled in (same ID as in
     `streamlit_app/services/sheet_config.py`).
   - `OPS_SPREADSHEET_ID` — from the OPS sheet URL:
     `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`
   - `BACKUP_FOLDER_ID` — from the backup folder URL:
     `drive.google.com/drive/folders/`**`THIS_PART`**

   (These are the same values as the GitHub secrets `OPS_SPREADSHEET_ID` and
   `CRM_BACKUP_DRIVE_FOLDER_ID`.)
5. Click 💾 **Save**.
6. In the function dropdown pick **`runDailyBackup`** → **Run**.
   - Google asks for permission → **Review permissions** → choose your account.
   - If it says *"Google hasn't verified this app"*: **Advanced** →
     **Go to CRM Daily Backup (unsafe)** → **Allow**. (It's your own script.)
   - Check the backup folder: today's two `backup_…` sheets should be there.
7. In the dropdown pick **`installDailyTrigger`** → **Run**. That's it — it
   now runs every night.

## Checking on it

- **Executions** (left sidebar, ▶ icon) shows each nightly run and its log.
- If a run fails, Google emails you automatically.
- To stop it: **Triggers** (⏰ icon) → delete the `runDailyBackup` trigger.
