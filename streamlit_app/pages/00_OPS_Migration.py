"""
pages/00_OPS_Migration.py

One-time admin page to migrate OPS sheets from Sheet 1 (CRM spreadsheet)
into Sheet 2 (OPS spreadsheet).  Hidden behind a sidebar toggle in app.py.
Remove this file once migration is complete.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="OPS Data Migration", layout="wide")
st.title("OPS Data Migration")
st.caption("One-time utility — migrate data from Sheet 1 to the new Sheet 2 (OPS spreadsheet). Remove this page after use.")

from services.sheet_config import CRM_SPREADSHEET_ID, OPS_SPREADSHEET_ID, _OPS_SHEETS, _OPS_PREFIXES

# ── Guard: ensure OPS sheet is configured ────────────────────────────────────
if CRM_SPREADSHEET_ID == OPS_SPREADSHEET_ID:
    st.error(
        "**OPS_SPREADSHEET_ID is not configured.**\n\n"
        "It is currently falling back to the same spreadsheet as CRM. "
        "Add `OPS_SPREADSHEET_ID` to your Streamlit secrets (`[admin]` section) "
        "or as an environment variable before running the migration."
    )
    st.stop()

st.success(f"**Sheet 1 (CRM):** `{CRM_SPREADSHEET_ID}`")
st.success(f"**Sheet 2 (OPS):** `{OPS_SPREADSHEET_ID}`")
st.divider()

# ── Helper ────────────────────────────────────────────────────────────────────
def _is_ops_sheet(name: str) -> bool:
    if name in _OPS_SHEETS:
        return True
    return any(name.startswith(p) for p in _OPS_PREFIXES)

@st.cache_resource(show_spinner=False)
def _get_gc():
    import json, gspread
    from google.oauth2.service_account import Credentials
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        return gspread.authorize(creds)
    try:
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception:
        pass
    cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "credentials.json")
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(cfg, scopes=SCOPES)
    return gspread.authorize(creds)

# ── Scan source spreadsheet ───────────────────────────────────────────────────
st.subheader("Step 1 — Preview what will be migrated")

@st.cache_data(ttl=30, show_spinner="Scanning source spreadsheet…")
def _scan_source():
    gc = _get_gc()
    src = gc.open_by_key(CRM_SPREADSHEET_ID)
    tabs = src.worksheets()
    crm_tabs = [ws.title for ws in tabs if not _is_ops_sheet(ws.title)]
    ops_tabs = [ws.title for ws in tabs if _is_ops_sheet(ws.title)]
    return crm_tabs, ops_tabs

try:
    crm_tabs, ops_tabs = _scan_source()
except Exception as e:
    st.error(f"Could not read source spreadsheet: {e}")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Stay in Sheet 1 (CRM) — not touched**")
    for t in crm_tabs:
        st.markdown(f"- {t}")
with col2:
    st.markdown("**Copy to Sheet 2 (OPS)**")
    for t in ops_tabs:
        st.markdown(f"- {t}")

if not ops_tabs:
    st.info("No OPS sheets found in Sheet 1. Nothing to migrate.")
    st.stop()

st.divider()

# ── Migration controls ────────────────────────────────────────────────────────
st.subheader("Step 2 — Run migration")

force = st.checkbox(
    "Force overwrite — re-copy sheets that already have data in Sheet 2",
    value=False,
    help="Leave unchecked on first run. Use only if you want to re-sync a sheet from scratch.",
)

if st.button("▶️ Start Migration", type="primary"):
    import time, gspread

    gc = _get_gc()
    src_sh = gc.open_by_key(CRM_SPREADSHEET_ID)
    dst_sh = gc.open_by_key(OPS_SPREADSHEET_ID)

    progress = st.progress(0, text="Starting…")
    log = st.container()
    results = {"ok": 0, "skip": 0, "error": 0}

    for i, sheet_name in enumerate(ops_tabs):
        progress.progress((i) / len(ops_tabs), text=f"Processing '{sheet_name}'…")
        try:
            src_ws = src_sh.worksheet(sheet_name)
            all_values = src_ws.get_all_values()

            if not all_values:
                log.info(f"⏭️ **{sheet_name}** — source is empty, skipped")
                results["skip"] += 1
                continue

            row_count = len(all_values)
            col_count = max(len(r) for r in all_values)

            try:
                dst_ws = dst_sh.worksheet(sheet_name)
                existing = dst_ws.get_all_values()
                if existing and not force:
                    log.warning(f"⏭️ **{sheet_name}** — already has {len(existing)} row(s) in Sheet 2, skipped (enable Force to overwrite)")
                    results["skip"] += 1
                    continue
                dst_ws.clear()
            except gspread.WorksheetNotFound:
                dst_ws = dst_sh.add_worksheet(
                    title=sheet_name,
                    rows=max(row_count + 50, 200),
                    cols=max(col_count + 5, 26),
                )

            dst_ws.update("A1", all_values)
            log.success(f"✅ **{sheet_name}** — {row_count} rows × {col_count} cols copied")
            results["ok"] += 1

        except Exception as exc:
            log.error(f"❌ **{sheet_name}** — {exc}")
            results["error"] += 1

        time.sleep(1.2)  # respect Google Sheets rate limits

    progress.progress(1.0, text="Done")

    st.divider()
    st.markdown(f"### Results: {results['ok']} copied · {results['skip']} skipped · {results['error']} error(s)")

    if results["error"]:
        st.warning("Some sheets failed. Fix the errors above and re-run.")
    else:
        st.success(
            "Migration complete! "
            "Restart the app to confirm everything reads from the correct spreadsheet. "
            "Once verified, you can delete the OPS tabs from Sheet 1 to keep it clean, "
            "and remove this page (`pages/00_OPS_Migration.py`) from the codebase."
        )
        _scan_source.clear()
