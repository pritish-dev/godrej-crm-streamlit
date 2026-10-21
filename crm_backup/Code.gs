/**
 * CRM + OPS Daily Backup — Google Apps Script version.
 *
 * Makes a duplicate Google Sheet of the CRM and OPS spreadsheets every night
 * at ~10 PM IST into the "B2C CRM BACKUP" folder, then trashes backups older
 * than 7 days.
 *
 * WHY APPS SCRIPT: the script runs as YOUR Google account, so the copies are
 * owned by you (your 15 GB quota) and there is no OAuth refresh token to
 * expire. The GitHub Actions job needed a refresh token, and while the OAuth
 * app is in "Testing" Google kills that token every 7 days.
 *
 * Setup (once): see crm_backup/SETUP.md
 *   1. Paste this file into a new Apps Script project (script.google.com).
 *   2. Fill in the three IDs below.
 *   3. Run `installDailyTrigger` once and approve access.
 */

// ── Fill these in ────────────────────────────────────────────────────────────
// Spreadsheet ID = the long part of the sheet URL between /d/ and /edit
var CRM_SPREADSHEET_ID = '1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54';
var OPS_SPREADSHEET_ID = 'PASTE_OPS_SPREADSHEET_ID_HERE';
// Folder ID = the last part of the "B2C CRM BACKUP" folder URL (after /folders/)
var BACKUP_FOLDER_ID   = 'PASTE_BACKUP_FOLDER_ID_HERE';
// ─────────────────────────────────────────────────────────────────────────────

var RETENTION_DAYS = 7;
var TIME_ZONE = 'Asia/Kolkata';

// Same naming as the old Python job: backup_<YYYY-MM-DD>_crm_sheet / _ops_sheet
var BACKUP_PREFIX = 'backup_';
var CRM_SUFFIX = '_crm_sheet';
var OPS_SUFFIX = '_ops_sheet';
// Older names still in the folder from earlier runs — purged under the same policy.
var LEGACY_PREFIXES = ['CRM Backup', 'OPS Backup'];


/** Main entry point — called by the daily trigger (or run by hand to test). */
function runDailyBackup() {
  var folder = DriveApp.getFolderById(BACKUP_FOLDER_ID);
  var today = Utilities.formatDate(new Date(), TIME_ZONE, 'yyyy-MM-dd');

  // 1) Purge first so retention always runs, even if a copy fails below.
  var deleted = purgeOldBackups_(folder);

  // 2) Copy each spreadsheet independently; one failure doesn't block the other.
  var made = [];
  var errors = [];
  var jobs = [
    { label: 'CRM', id: CRM_SPREADSHEET_ID, suffix: CRM_SUFFIX },
    { label: 'OPS', id: OPS_SPREADSHEET_ID, suffix: OPS_SUFFIX }
  ];
  jobs.forEach(function (job) {
    var name = BACKUP_PREFIX + today + job.suffix;
    try {
      // Re-running on the same day replaces that day's copy instead of duplicating it.
      trashByName_(folder, name);
      var copy = DriveApp.getFileById(job.id).makeCopy(name, folder);
      made.push(name);
      Logger.log('Backup created: %s (id: %s)', name, copy.getId());
    } catch (e) {
      errors.push(job.label + ' backup failed: ' + e.message);
      Logger.log('%s backup failed: %s', job.label, e.message);
    }
  });

  var status = 'Backup(s) created: ' + (made.length ? made.join(', ') : 'none') +
               '. Deleted ' + deleted + ' backup(s) older than ' + RETENTION_DAYS + ' days.';
  Logger.log(status);

  // Throwing makes Apps Script email you a failure notice for this trigger.
  if (errors.length) {
    throw new Error(status + ' | ' + errors.join(' | '));
  }
  return status;
}


/** Run ONCE: creates the daily ~10 PM IST trigger (removes any older copy of it). */
function installDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runDailyBackup') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('runDailyBackup')
    .timeBased()
    .everyDays(1)
    .atHour(22)            // runs between 10 and 11 PM in the project time zone
    .inTimezone(TIME_ZONE)
    .create();
  Logger.log('Daily backup trigger installed (10–11 PM IST).');
}


function isBackupName_(name) {
  if (name.indexOf(BACKUP_PREFIX) === 0 &&
      (endsWith_(name, CRM_SUFFIX) || endsWith_(name, OPS_SUFFIX))) {
    return true;
  }
  return LEGACY_PREFIXES.some(function (p) { return name.indexOf(p) === 0; });
}

function purgeOldBackups_(folder) {
  var cutoff = new Date(Date.now() - RETENTION_DAYS * 24 * 60 * 60 * 1000);
  var deleted = 0;
  var files = folder.getFiles();
  while (files.hasNext()) {
    var f = files.next();
    if (!isBackupName_(f.getName())) continue;
    if (f.getDateCreated() < cutoff) {
      try {
        f.setTrashed(true);
        Logger.log('Deleted old backup: %s (created %s)', f.getName(), f.getDateCreated());
        deleted++;
      } catch (e) {
        Logger.log('Could not delete %s: %s', f.getName(), e.message);
      }
    }
  }
  return deleted;
}

function trashByName_(folder, name) {
  var existing = folder.getFilesByName(name);
  while (existing.hasNext()) {
    existing.next().setTrashed(true);
  }
}

function endsWith_(s, suffix) {
  return s.length >= suffix.length && s.slice(-suffix.length) === suffix;
}
