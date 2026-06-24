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

# ── Helpers ───────────────────────────────────────────────────────────────────
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

# ── Scan both spreadsheets ────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner="Scanning spreadsheets…")
def _scan_both():
    import gspread
    gc = _get_gc()
    src = gc.open_by_key(CRM_SPREADSHEET_ID)
    dst = gc.open_by_key(OPS_SPREADSHEET_ID)

    src_tabs = {ws.title: ws for ws in src.worksheets()}
    dst_tabs = {ws.title: ws for ws in dst.worksheets()}

    crm_tabs = [t for t in src_tabs if not _is_ops_sheet(t)]
    ops_tabs  = [t for t in src_tabs if _is_ops_sheet(t)]

    # Row counts: read values length (minus header row) for each ops sheet
    verification = []
    for name in ops_tabs:
        src_rows = len(src_tabs[name].get_all_values())
        if name in dst_tabs:
            dst_rows = len(dst_tabs[name].get_all_values())
        else:
            dst_rows = None   # sheet doesn't exist in dst yet
        verification.append({
            "sheet": name,
            "src_rows": src_rows,
            "dst_rows": dst_rows,
        })

    return crm_tabs, ops_tabs, verification

try:
    crm_tabs, ops_tabs, verification = _scan_both()
except PermissionError:
    # Find the service account email to show in the error message
    sa_email = "your service account email"
    try:
        import json
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            sa_email = json.loads(raw).get("client_email", sa_email)
        else:
            sa_email = st.secrets["google"].get("client_email", sa_email)
    except Exception:
        pass
    st.error(
        "**Permission denied on the OPS spreadsheet.**\n\n"
        f"The service account **`{sa_email}`** does not have access to Sheet 2.\n\n"
        "**Fix:** Open the OPS spreadsheet in Google Sheets → Share → "
        f"add `{sa_email}` as an **Editor** → Save.\n\n"
        "Then click **Refresh verification** or reload this page."
    )
    st.stop()
except Exception as e:
    st.error(f"Could not read spreadsheets: {e}")
    st.stop()

# ── Step 1: Preview ───────────────────────────────────────────────────────────
st.subheader("Step 1 — Preview")
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

# ── Step 2: Verification status ───────────────────────────────────────────────
st.subheader("Step 2 — Verification: what's already in Sheet 2?")

import pandas as pd

rows_data = []
all_done = True
for v in verification:
    src_rows = v["src_rows"]
    dst_rows = v["dst_rows"]

    if dst_rows is None:
        status = "❌ Not in Sheet 2 yet"
        all_done = False
    elif dst_rows == 0:
        status = "⚠️ Sheet exists but is empty"
        all_done = False
    elif dst_rows < src_rows:
        status = f"⚠️ Partial — {dst_rows} / {src_rows} rows"
        all_done = False
    else:
        status = "✅ Matches"

    rows_data.append({
        "Sheet name": v["sheet"],
        "Rows in Sheet 1": src_rows,
        "Rows in Sheet 2": dst_rows if dst_rows is not None else "—",
        "Status": status,
    })

df_status = pd.DataFrame(rows_data)
st.dataframe(df_status, use_container_width=True, hide_index=True)

if all_done:
    st.success("🎉 All OPS sheets are present in Sheet 2 with matching row counts. Migration is complete!")
else:
    pending = sum(1 for r in rows_data if "✅" not in r["Status"])
    st.warning(f"{pending} sheet(s) still need to be migrated or re-checked. Run the migration below.")

if st.button("🔄 Refresh verification", type="secondary"):
    _scan_both.clear()
    st.rerun()

st.divider()

# ── Step 3: Run migration ─────────────────────────────────────────────────────
st.subheader("Step 3 — Run migration")

force = st.checkbox(
    "Force overwrite — re-copy sheets that already have data in Sheet 2",
    value=False,
    help="Leave unchecked on first run. Use only if you want to re-sync a sheet from scratch.",
)

if st.button("▶️ Start Migration", type="primary"):
    import time, gspread
    from gspread.exceptions import APIError

    gc = _get_gc()
    src_sh = gc.open_by_key(CRM_SPREADSHEET_ID)
    dst_sh = gc.open_by_key(OPS_SPREADSHEET_ID)

    # ── Pre-flight: verify write access on the OPS spreadsheet ───────────────
    try:
        dst_sh.worksheets()   # lightweight read
        # Try a harmless title update on the spreadsheet object to probe write
        test_title = dst_sh.title  # just fetch title to confirm access level
    except Exception:
        pass

    try:
        # Attempt to list + touch the first sheet to detect Viewer-only access
        _probe = dst_sh.get_worksheet(0)
        _probe.get("A1")   # read is fine
        # A real write probe — try updating a cell with its current value
        _val = _probe.acell("A1").value or ""
        _probe.update("A1", [[_val]])
    except APIError as api_err:
        if "403" in str(api_err):
            sa_email = "your service account email"
            try:
                import json
                raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
                if raw:
                    sa_email = json.loads(raw).get("client_email", sa_email)
                else:
                    sa_email = st.secrets["google"].get("client_email", sa_email)
            except Exception:
                pass
            st.error(
                "**Cannot write to Sheet 2 — service account has Viewer access only.**\n\n"
                f"Open the OPS spreadsheet → **Share** → find `{sa_email}` → "
                "change role from **Viewer** to **Editor** → Save.\n\n"
                "Then click **▶️ Start Migration** again."
            )
            st.stop()
    except Exception:
        pass  # ignore other probe errors, let the actual copy surface them

    progress = st.progress(0, text="Starting…")
    log = st.container()
    results = {"ok": 0, "skip": 0, "error": 0}

    for i, sheet_name in enumerate(ops_tabs):
        progress.progress(i / len(ops_tabs), text=f"Processing '{sheet_name}'…")
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

        except APIError as api_err:
            if "403" in str(api_err):
                log.error(f"❌ **{sheet_name}** — Permission denied (403). Service account needs Editor access on Sheet 2.")
            else:
                log.error(f"❌ **{sheet_name}** — {api_err}")
            results["error"] += 1

        except Exception as exc:
            log.error(f"❌ **{sheet_name}** — {exc}")
            results["error"] += 1

        time.sleep(1.2)  # respect Google Sheets rate limits

    progress.progress(1.0, text="Done")
    st.divider()
    st.markdown(f"### Results: {results['ok']} copied · {results['skip']} skipped · {results['error']} error(s)")

    if results["error"]:
        st.warning("Some sheets failed. Check errors above — most likely the service account still needs **Editor** access on Sheet 2.")
    else:
        st.success(
            "Migration complete! Click **Refresh verification** above to confirm all row counts match. "
            "Once verified, you can delete the OPS tabs from Sheet 1 to keep it clean, "
            "and remove this page (`pages/00_OPS_Migration.py`) from the codebase."
        )

    _scan_both.clear()
