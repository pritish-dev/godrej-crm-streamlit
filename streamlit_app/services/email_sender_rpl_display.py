"""
services/email_sender_rpl_display.py

"Request for Delivery — 34S RPL for Showroom Display" email.

Triggered from the RPL Stock page: the user ticks the ZBF34S (Destination
Warehouse) RPL items wanted for showroom display, sets a Req Qty for each, and
this module sends ONE email listing them in a table:

    Item Code | Item Description | Wh Order No. | WH Order Pos. | Req Qty

Subject line (fixed): "REQUEST FOR DELIVERY 34S RPL FOR SHOWROOM DISPLAY".

Signed off "Thanks & Regards," + the sales person chosen on the page.
The page can either send the email or save it as a Gmail draft (in the account
it would be sent from) for a final review in Gmail.

Recipients:
  To — the "TO" column of the OPS sheet "RPL_DISPLAY_REQUEST".
  CC — the "CC" column of that same sheet.
  Entries may be plain addresses or "Name <address>"; several per cell may be
  separated with "," or ";".
"""
from __future__ import annotations

import html
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import getaddresses

import pandas as pd

from services import crm_mail

SUBJECT          = "REQUEST FOR DELIVERY 34S RPL FOR SHOWROOM DISPLAY"
RECIPIENTS_SHEET = "RPL_DISPLAY_REQUEST"
JOB_NAME         = "RPL Showroom Display Request"
DISPLAY_WH_CODE  = "ZBF34S"

# Email table columns (in order) — also the keys expected in each item dict.
EMAIL_COLS = ["Item Code", "Item Description", "Wh Order No.", "WH Order Pos.", "Req Qty"]

IST = timezone(timedelta(hours=5, minutes=30))

GREETING = "Dear Sir,"
INTRO = ("Kindly plan the delivery of the following products to our store.<br>"
         "The product details are mentioned below for your reference.")
SIGN_OFF = "Thanks & Regards,"


# ═══════════════════════════════════════════════════════════════════════════════
# Recipients
# ═══════════════════════════════════════════════════════════════════════════════

def _split_entries(values) -> list[str]:
    """Cell values → unique, non-empty 'Name <addr>' / 'addr' entries."""
    out: list[str] = []
    for v in values:
        for part in str(v).replace(";", ",").split(","):
            p = part.strip()
            if p and p.lower() not in ("nan", "none") and p not in out:
                out.append(p)
    return out


def get_display_request_recipients() -> dict:
    """
    Read To/CC from the OPS sheet 'RPL_DISPLAY_REQUEST'.
    Returns {"to": [...], "cc": [...], "error": str}.
    """
    try:
        from services.sheets import get_df
        df = get_df(RECIPIENTS_SHEET)
    except Exception as e:
        return {"to": [], "cc": [], "error": f"Could not read '{RECIPIENTS_SHEET}': {e}"}
    if df is None or df.empty:
        return {"to": [], "cc": [],
                "error": f"No recipients configured in the '{RECIPIENTS_SHEET}' sheet."}

    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    to_col = next((c for c in df.columns if c in ("TO", "EMAIL", "TO EMAIL")), None)
    cc_col = next((c for c in df.columns if c in ("CC", "CC EMAIL")), None)

    to = _split_entries(df[to_col]) if to_col else []
    cc = _split_entries(df[cc_col]) if cc_col else []
    err = "" if to else f"No 'TO' recipient configured in the '{RECIPIENTS_SHEET}' sheet."
    return {"to": to, "cc": cc, "error": err}


def _bare_addresses(entries: list[str]) -> list[str]:
    """'Ashis Dash <ashisd@godrej.com>' → 'ashisd@godrej.com' (SMTP envelope)."""
    return [addr for _, addr in getaddresses(entries) if addr]


# ═══════════════════════════════════════════════════════════════════════════════
# Body builders
# ═══════════════════════════════════════════════════════════════════════════════

def build_html_body(items: list[dict], sender_name: str = "") -> str:
    """HTML email body — yellow header row / green item rows, like the sample."""
    cell = ("padding:6px 12px;border:1px solid #444;font-family:Calibri,Arial,sans-serif;"
            "font-size:14px;font-weight:bold;text-align:center")
    head = "".join(
        f"<th style='{cell};background:#ffff00'>{html.escape(h)}</th>" for h in EMAIL_COLS
    )
    rows = "".join(
        "<tr>" + "".join(
            f"<td style='{cell};background:#c6e0b4'>{html.escape(str(it.get(c, '')))}</td>"
            for c in EMAIL_COLS
        ) + "</tr>"
        for it in items
    )
    table = (f"<table style='border-collapse:collapse'>"
             f"<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
    text = "font-family:Calibri,Arial,sans-serif;font-size:14px"
    return (
        f"<div style='{text}'>"
        f"<p>{GREETING}</p>"
        f"<p>{INTRO}</p>"
        f"{table}"
        f"<p>{SIGN_OFF}<br>{html.escape(sender_name.strip())}</p>"
        f"</div>"
    )


def build_plain_body(items: list[dict], sender_name: str = "") -> str:
    """Plain-text alternative of the email (tab-separated table)."""
    lines = [GREETING,
             INTRO.replace("<br>", "\n"),
             "",
             "\t".join(EMAIL_COLS)]
    lines += ["\t".join(str(it.get(c, "")) for c in EMAIL_COLS) for it in items]
    lines += ["", SIGN_OFF, sender_name.strip()]
    return "\n".join(lines).rstrip() + "\n"


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY-POINT
# ═══════════════════════════════════════════════════════════════════════════════

def _build_message(items: list[dict], sender_name: str, to: list[str], cc: list[str]):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = SUBJECT
    msg["To"]      = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(build_plain_body(items, sender_name), "plain"))
    msg.attach(MIMEText(build_html_body(items, sender_name), "html"))
    return msg


def send_rpl_display_request_email(items: list[dict], sender_name: str = "",
                                   as_draft: bool = False) -> dict:
    """
    Send the showroom-display delivery request for `items` (dicts keyed by
    EMAIL_COLS), signed by `sender_name` — or, with as_draft=True, only save it
    as a Gmail draft. Returns {"sent", "queued", "draft", "draft_account",
    "to", "cc", "records", "error"}.
    """
    summary = {"sent": False, "queued": False, "draft": False, "draft_account": "",
               "to": [], "cc": [], "records": len(items), "error": ""}
    if not items:
        summary["error"] = "No items selected."
        return summary

    r = get_display_request_recipients()
    summary["to"], summary["cc"] = r["to"], r["cc"]
    if r["error"]:
        summary["error"] = r["error"]
        return summary

    msg = _build_message(items, sender_name, r["to"], r["cc"])
    all_rcpts = _bare_addresses(r["to"] + r["cc"])

    if as_draft:
        try:
            summary["draft_account"] = crm_mail.save_draft(msg, all_rcpts)
            summary["draft"] = True
        except Exception as e:
            summary["error"] = str(e)
        return summary

    try:
        outcome = crm_mail.deliver(msg, all_rcpts, job_name=JOB_NAME,
                                   records_count=len(items), report=False)
        summary["sent"]   = outcome == "sent"
        summary["queued"] = outcome == "queued"
        print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M')}] ✅ RPL display request "
              f"{outcome} → To:{r['to']} Cc:{r['cc']}")
        crm_mail.log_outcome(outcome, JOB_NAME, len(items), all_rcpts)
    except Exception as send_err:
        summary["error"] = str(send_err)
        try:
            from services.sheets import append_email_log
            append_email_log(job_name=JOB_NAME, records_count=len(items),
                             recipients=all_rcpts, status="error", error=str(send_err))
        except Exception:
            pass
    return summary
