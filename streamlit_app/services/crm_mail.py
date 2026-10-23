"""
services/crm_mail.py

Single delivery point for every email the CRM sends.

1. Dedicated sender account
   All CRM mail goes out from a separate Gmail account (4sinteriors.crm@gmail.com)
   configured through:
       CRM_EMAIL_SENDER   = 4sinteriors.crm@gmail.com
       CRM_EMAIL_PASSWORD = <16-char Gmail App Password of that account>
   (env vars → Streamlit secrets [admin] / top-level → .env).
   If those are not configured yet, it falls back to the legacy
   EMAIL_SENDER / EMAIL_PASSWORD so nothing breaks during the switch-over.

   EMAIL_SENDER / EMAIL_PASSWORD are still used — but only for READING the
   official inbox over IMAP (MIS, stock, RPL, invoice and lead imports), because
   that is where Godrej sends those mails.

   Exception — mail to anyone other than the official showroom inbox
   (4sinteriorsbbsr@gmail.com) is sent FROM 4sinteriorsbbsr@gmail.com, using
   EMAIL_SENDER / EMAIL_PASSWORD (which must be that account). Only mail whose
   recipients are all 4sinteriorsbbsr@gmail.com itself uses the CRM account.

2. Night-only send window (automated mail only)
   Emails triggered MANUALLY from the CRM dashboard (any deliver() call made
   while a Streamlit page is running) are sent immediately.
   AUTOMATED mail (scheduled jobs / GitHub Actions) is only handed to SMTP
   between 21:00 and 23:59 IST; outside that window it is parked in the
   "CRM-Outbox" Gmail label of the CRM sender account and released by
   email_outbox_flush_job.py, which runs nightly after the scheduled jobs.

3. Fewer emails
   When the outbox is flushed, repeated triggers of the same email (same job,
   subject and recipients) collapse to the most recent one, and a queued report
   is dropped altogether if its scheduled job sent a fresher copy (one sent
   after the click) that day.

Overrides (env var or Streamlit secret):
    EMAIL_SEND_WINDOW_START  — IST hour the window opens   (default 21)
    EMAIL_SEND_WINDOW_END    — IST hour the window closes  (default 24 = midnight)
    CRM_EMAIL_SEND_NOW=1     — ignore the window and send immediately (set by the
                               7 AM Pending Delivery Alert workflow; also for testing)
"""
from __future__ import annotations

import imaplib
import os
import smtplib
import time
import email
from email.utils import parseaddr
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

SMTP_HOST = "smtp.gmail.com"
IMAP_HOST = "imap.gmail.com"
OUTBOX_FOLDER = "CRM-Outbox"

# Official showroom account — every email to anyone else is sent from it.
OFFICIAL_SENDER = "4sinteriorsbbsr@gmail.com"

# Private headers carried by a queued message; stripped before it is sent.
H_RCPTS   = "X-CRM-Envelope-To"
H_JOB     = "X-CRM-Job"
H_RECORDS = "X-CRM-Records"
H_KEY     = "X-CRM-Dedup-Key"
H_REPORT  = "X-CRM-Report"
H_QUEUED  = "X-CRM-Queued-At"
_PRIVATE_HEADERS = (H_RCPTS, H_JOB, H_RECORDS, H_KEY, H_REPORT, H_QUEUED)

QUEUED_NOTICE = ("🕘 Queued — automated CRM emails go out only after 9 PM IST. "
                 "This one will be sent with tonight's batch.")


# ═══════════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════════

_dotenv_loaded = False


def _setting(key: str) -> str:
    """env var → st.secrets['admin'][key] → st.secrets[key] → .env"""
    global _dotenv_loaded
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        import streamlit as st
        try:
            v = str(st.secrets["admin"][key]).strip()
        except Exception:
            v = str(st.secrets[key]).strip()
        if v:
            return v
    except Exception:
        pass
    if not _dotenv_loaded:
        _dotenv_loaded = True
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        except Exception:
            pass
        return os.getenv(key, "").strip()
    return ""


def sender_credentials(fallback_email: str | None = None,
                       fallback_password: str | None = None) -> tuple[str | None, str | None]:
    """
    (email, app_password) of the dedicated CRM sender account.
    Falls back to the legacy EMAIL_SENDER / EMAIL_PASSWORD when the CRM_* pair
    is not configured.
    """
    e, p = _setting("CRM_EMAIL_SENDER"), _setting("CRM_EMAIL_PASSWORD")
    if e and p:
        return e, p
    if not fallback_email or not fallback_password:
        fallback_email, fallback_password = _setting("EMAIL_SENDER"), _setting("EMAIL_PASSWORD")
    if fallback_email:
        print("[crm_mail] CRM_EMAIL_SENDER / CRM_EMAIL_PASSWORD not set — "
              f"falling back to EMAIL_SENDER ({fallback_email}).")
    return fallback_email or None, fallback_password or None


def official_credentials() -> tuple[str | None, str | None]:
    """(email, app_password) of the official 4sinteriorsbbsr@gmail.com account."""
    e, p = _setting("EMAIL_SENDER"), _setting("EMAIL_PASSWORD")
    if e and e.lower() != OFFICIAL_SENDER:
        print(f"[crm_mail] ⚠️ EMAIL_SENDER is {e}, expected {OFFICIAL_SENDER}.")
    return e or None, p or None


def _bare(addr: str) -> str:
    return (parseaddr(addr)[1] or addr).strip().lower()


def credentials_for(recipients: list[str]) -> tuple[str | None, str | None]:
    """
    Sender account for a message: 4sinteriorsbbsr@gmail.com whenever any
    recipient is someone else; the CRM account when the mail only goes to
    4sinteriorsbbsr@gmail.com itself (or the official login is missing).
    """
    if any(_bare(r) != OFFICIAL_SENDER for r in recipients):
        e, p = official_credentials()
        if e and p:
            return e, p
    return sender_credentials()


def triggered_manually() -> bool:
    """True when called from a running Streamlit page (a dashboard button)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        try:
            return get_script_run_ctx(suppress_warning=True) is not None
        except TypeError:
            return get_script_run_ctx() is not None
    except Exception:
        return False


def _window() -> tuple[int, int]:
    try:
        start = int(_setting("EMAIL_SEND_WINDOW_START") or 21)
    except ValueError:
        start = 21
    try:
        end = int(_setting("EMAIL_SEND_WINDOW_END") or 24)
    except ValueError:
        end = 24
    return start, end


def in_send_window(now: datetime | None = None) -> bool:
    if _setting("CRM_EMAIL_SEND_NOW") in ("1", "true", "yes"):
        return True
    hour = (now or datetime.now(IST)).astimezone(IST).hour
    start, end = _window()
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end        # window that wraps past midnight


# ═══════════════════════════════════════════════════════════════════════════════
# Send / queue
# ═══════════════════════════════════════════════════════════════════════════════

def _smtp_send(server: smtplib.SMTP, sender: str, msg, rcpts: list[str]) -> None:
    for h in _PRIVATE_HEADERS:
        del msg[h]
    del msg["From"]
    msg["From"] = sender
    server.sendmail(sender, rcpts, msg.as_bytes())


def _imap_login(sender: str, password: str) -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(sender, password)
    return mail


def deliver(msg, recipients: list[str], *, job_name: str = "",
            records_count: int = 0, report: bool = True,
            immediate: bool | None = None) -> str:
    """
    Send `msg` (an email.message.Message) to `recipients` (the full envelope
    list: To + Cc + Bcc) — from 4sinteriorsbbsr@gmail.com, or from the CRM
    account when the mail only goes to 4sinteriorsbbsr@gmail.com.

    Manually triggered mail (immediate=None → auto-detected: called from a
    Streamlit page) and mail inside the send window is sent right away;
    automated mail outside the window is queued in the CRM account's
    CRM-Outbox label. Returns "sent" or "queued"; raises on failure.

    report=True marks a recurring report that a scheduled job also produces —
    a queued copy is skipped at flush time if that job sent after it was queued. Pass report=False for one-off mails (e.g. customer delivery emails).
    """
    sender, password = sender_credentials()
    if not sender or not password:
        raise ValueError("CRM_EMAIL_SENDER / CRM_EMAIL_PASSWORD (or EMAIL_SENDER / "
                         "EMAIL_PASSWORD) not set in env vars or secrets.")
    rcpts = [r for r in dict.fromkeys(r.strip() for r in recipients) if r]
    if not rcpts:
        raise ValueError("No recipients given.")

    if immediate is None:
        immediate = triggered_manually()
    if immediate or in_send_window():
        from_addr, from_pw = credentials_for(rcpts)
        with smtplib.SMTP_SSL(SMTP_HOST, 465) as server:
            server.login(from_addr, from_pw)
            _smtp_send(server, from_addr, msg, rcpts)
        return "sent"

    for h in _PRIVATE_HEADERS:
        del msg[h]
    del msg["From"]
    msg["From"] = sender
    msg[H_RCPTS]   = ", ".join(rcpts)
    msg[H_JOB]     = job_name or str(msg.get("Subject", ""))[:60]
    msg[H_RECORDS] = str(int(records_count or 0))
    msg[H_KEY]     = " | ".join([msg[H_JOB], str(msg.get("Subject", "")), ",".join(sorted(rcpts))])
    msg[H_REPORT]  = "1" if report else "0"
    msg[H_QUEUED]  = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    mail = _imap_login(sender, password)
    try:
        mail.create(OUTBOX_FOLDER)            # harmless "already exists" if present
        typ, data = mail.append(OUTBOX_FOLDER, "", imaplib.Time2Internaldate(time.time()),
                                msg.as_bytes())
        if typ != "OK":
            raise RuntimeError(f"IMAP append to {OUTBOX_FOLDER} failed: {data}")
    finally:
        try:
            mail.logout()
        except Exception:
            pass
    print(f"[crm_mail] 🕘 Queued '{msg.get('Subject', '')}' → {rcpts} (outside send window)")
    return "queued"


def _drafts_folder(mail: imaplib.IMAP4_SSL) -> str:
    """Gmail's Drafts mailbox (special-use \\Drafts; name can be localised)."""
    try:
        _, boxes = mail.list()
        for b in boxes or []:
            line = b.decode(errors="ignore") if isinstance(b, bytes) else str(b)
            if "\\Drafts" in line:
                return line.rsplit(' "/" ', 1)[-1].strip()
    except Exception:
        pass
    return '"[Gmail]/Drafts"'


def save_draft(msg, recipients: list[str]) -> str:
    """
    Save `msg` as a Gmail draft (not sent) in the account it would be sent from
    (see credentials_for). Returns that account's address; raises on failure.
    """
    rcpts = [r for r in dict.fromkeys(r.strip() for r in recipients) if r]
    if not rcpts:
        raise ValueError("No recipients given.")
    sender, password = credentials_for(rcpts)
    if not sender or not password:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in env vars or secrets.")
    for h in _PRIVATE_HEADERS:
        del msg[h]
    del msg["From"]
    msg["From"] = sender

    mail = _imap_login(sender, password)
    try:
        folder = _drafts_folder(mail)
        typ, data = mail.append(folder, "(\\Draft)", imaplib.Time2Internaldate(time.time()),
                                msg.as_bytes())
        if typ != "OK":
            raise RuntimeError(f"IMAP append to {folder} failed: {data}")
    finally:
        try:
            mail.logout()
        except Exception:
            pass
    print(f"[crm_mail] 📝 Draft saved '{msg.get('Subject', '')}' in {sender}")
    return sender


def log_outcome(outcome: str, job_name: str, records_count: int, recipients: list[str]) -> None:
    """EMAIL_LOG row for a deliver() outcome ("sent" → success, "queued" → queued)."""
    try:
        from services.sheets import append_email_log
        append_email_log(job_name=job_name, records_count=records_count,
                         recipients=list(recipients),
                         status="success" if outcome == "sent" else "queued")
    except Exception as log_err:
        print(f"[EMAIL_LOG] Warning: {log_err}")


# ═══════════════════════════════════════════════════════════════════════════════
# Nightly flush
# ═══════════════════════════════════════════════════════════════════════════════

def flush_outbox(dry_run: bool = False) -> dict:
    """
    Send everything waiting in CRM-Outbox. Duplicates (same dedup key) collapse
    to the newest copy; queued reports whose scheduled job already sent today
    after they were queued are dropped. Every handled message is removed from
    the outbox.
    """
    sender, password = sender_credentials()
    if not sender or not password:
        raise ValueError("CRM sender credentials not configured.")

    result = {"sent": [], "duplicates": [], "superseded": [], "failed": []}
    mail = _imap_login(sender, password)
    try:
        typ, _ = mail.select(OUTBOX_FOLDER)
        if typ != "OK":
            print(f"[crm_mail] No {OUTBOX_FOLDER} label yet — nothing queued.")
            return result
        _, data = mail.uid("search", None, "ALL")
        uids = [u for u in (data[0] or b"").split()]

        queued = []
        for uid in uids:
            _, parts = mail.uid("fetch", uid, "(RFC822)")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                queued.append((int(uid), uid, email.message_from_bytes(raw)))
        queued.sort(key=lambda q: q[0])            # oldest → newest

        latest: dict[str, tuple] = {}
        for item in queued:
            key = item[2].get(H_KEY) or item[2].get("Message-ID") or str(item[0])
            if key in latest:
                result["duplicates"].append(latest[key][2].get("Subject", ""))
                _mark_done(mail, latest[key][1], dry_run)
            latest[key] = item

        from services.sheets import append_email_log, last_email_success_today

        servers: dict[str, smtplib.SMTP] = {}
        try:
            for _, uid, msg in latest.values():
                subj    = str(msg.get("Subject", ""))
                job     = str(msg.get(H_JOB, "") or subj[:60])
                rcpts   = [r.strip() for r in str(msg.get(H_RCPTS, "")).split(",") if r.strip()]
                records = int(str(msg.get(H_RECORDS, "0") or 0))

                last_sent = last_email_success_today(job) if msg.get(H_REPORT) == "1" else None
                if last_sent and last_sent >= str(msg.get(H_QUEUED, "")):
                    result["superseded"].append(subj)
                    append_email_log(job, records, rcpts, "superseded",
                                     f"Fresher copy already sent at {last_sent}")
                    _mark_done(mail, uid, dry_run)
                    continue
                if dry_run:
                    result["sent"].append(subj)
                    continue
                try:
                    from_addr, from_pw = credentials_for(rcpts)
                    server = servers.get(from_addr)
                    if server is None:
                        server = smtplib.SMTP_SSL(SMTP_HOST, 465)
                        server.login(from_addr, from_pw)
                        servers[from_addr] = server
                    _smtp_send(server, from_addr, msg, rcpts)
                    result["sent"].append(subj)
                    append_email_log(job, records, rcpts, "success")
                    _mark_done(mail, uid, dry_run)
                except Exception as e:
                    result["failed"].append(f"{subj}: {e}")
                    append_email_log(job, records, rcpts, "error", str(e))
        finally:
            for server in servers.values():
                try:
                    server.quit()
                except Exception:
                    pass
        if not dry_run:
            mail.expunge()
    finally:
        try:
            mail.logout()
        except Exception:
            pass
    return result


def _mark_done(mail: imaplib.IMAP4_SSL, uid: bytes, dry_run: bool) -> None:
    if not dry_run:
        mail.uid("store", uid, "+FLAGS", "(\\Deleted)")
