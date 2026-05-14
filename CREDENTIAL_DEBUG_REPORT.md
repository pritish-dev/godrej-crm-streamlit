# Email Workflows & MIS Update — Credential Issues Report

**Date:** May 14, 2026  
**Status:** CRITICAL — Invalid credentials blocking email sends and MIS fetches

---

## Problem Summary

All email sending workflows and the MIS Update Gmail fetch are failing with **"invalid credentials"** errors. This started happening after recent changes to the credential loading system.

---

## Root Cause Analysis

### 1. **Credential Loading Priority Chain Changed**
**Commit:** `5be9d1c` (Apr 29, 2026) — "Fix: Environment-agnostic credentials"

This commit introduced a multi-source fallback pattern for credentials:

```python
# Priority order:
# 1. Environment Variables (GitHub Actions)
# 2. Streamlit Secrets - nested "admin" key (LOCAL/STREAMLIT CLOUD)
# 3. Streamlit Secrets - flat structure (LOCAL/STREAMLIT CLOUD)  
# 4. .env file (LOCAL DEVELOPMENT)
```

**Problem:** The nested `admin` key in `.streamlit/secrets.toml` is now loaded **FIRST** (highest priority), but it contains a **REDACTED** password.

---

## Current Configuration Issues

### **File:** `.streamlit/secrets.toml`

#### ❌ BROKEN — Nested Admin Section (Lines 24-30)
```toml
"admin": {
    "EMAIL_SENDER": "4sinteriorsbbsr@gmail.com",
    "EMAIL_PASSWORD": "REDACTED",  # ← INVALID CREDENTIAL!
    "EMAIL_RECIPIENTS": [
      "4sinteriorsbbsr@gmail.com"
    ]
}
```

**Impact:**
- `email_sender.py` (Line 34-36): Loads from `st.secrets["admin"]` and gets "REDACTED"
- `mis_email_import.py` (Line 47-48): Loads from `st.secrets["admin"]` and gets "REDACTED"
- **Both SMTP and IMAP login attempts fail**

#### ✅ CORRECT — Flat Structure (Lines 5-7)
```toml
EMAIL_SENDER = "4sinteriorsbbsr@gmail.com"
EMAIL_PASSWORD = "jcfz rhfw mkxt xttc"  # Valid app password
EMAIL_RECIPIENTS = "4sinteriorsbbsr@gmail.com"
```

---

## Affected Components

### Email Workflows (6 total)
| Workflow | File | Status |
|----------|------|--------|
| Pending Delivery Report | `email_job.py` | ❌ FAILING |
| Overdue Delivery Reminder | `email_job.py` | ❌ FAILING |
| Happy Calling Email | `happy_calling_email_job.py` | ❌ FAILING |
| Monthly Performance Report | `monthly_performance_email_job.py` | ❌ FAILING |
| Payment Email | `payment_email_job.py` | ❌ FAILING |
| Sales Tasks Email | `sales_tasks_email_job.py` | ❌ FAILING |

### MIS Updates
| Process | File | Status |
|---------|------|--------|
| MIS Daily Import (11 AM) | `mis_email_import.py` | ❌ FAILING |
| MIS Force Fetch | Dashboard `50_MIS_Update.py` | ❌ FAILING |

---

## Why This Happened

### Commit Timeline:
1. **Apr 29** (`5be9d1c`): Changed credential loading to environment-agnostic pattern
2. **May 1** (`5a95a4a`): Email formatting fixes (not related to credentials)
3. **May 7** (`88e8d1f`): Added MIS Update page with same credential loading pattern
4. **May 14**: Someone updated `.streamlit/secrets.toml` with REDACTED value in nested admin section

The nested admin structure was likely added for Streamlit Cloud compatibility, but the password wasn't updated when credentials were rotated.

---

## Solution

### **Fix Required:**

Update `.streamlit/secrets.toml` line 26 with the actual app password:

```diff
"admin": {
    "EMAIL_SENDER": "4sinteriorsbbsr@gmail.com",
-   "EMAIL_PASSWORD": "REDACTED",
+   "EMAIL_PASSWORD": "jcfz rhfw mkxt xttc",
    "EMAIL_RECIPIENTS": [
      "4sinteriorsbbsr@gmail.com"
    ]
}
```

### **Verification Steps:**

1. ✅ Update the nested admin password in `.streamlit/secrets.toml`
2. ✅ Test email send workflow (run any email job manually)
3. ✅ Test MIS fetch (click "Force Fetch" in MIS Update dashboard)
4. ✅ Verify both SMTP (port 465) and IMAP (imap.gmail.com) logins succeed

---

## Files Modified in Recent Changes

### Commit `5be9d1c` (Apr 29)
- `streamlit_app/services/email_sender.py` — Credential loading logic
- `streamlit_app/services/email_sender_4s.py` — Credential loading logic

### Commit `88e8d1f` (May 7)
- `streamlit_app/pages/50_MIS_Update.py` — New MIS dashboard (uses same credentials)
- `streamlit_app/services/mis_email_import.py` — Gmail IMAP fetch (uses same credentials)

### Current Issue
- `.streamlit/secrets.toml` — Contains REDACTED password in admin section

---

## Credential Loading Code Review

### `email_sender.py` (Lines 30-44)
```python
# 2. Try Streamlit secrets (local development with Streamlit or Streamlit Cloud)
if SENDER_EMAIL is None:
    try:
        import streamlit as st
        # Try nested structure first (admin key)
        SENDER_EMAIL = st.secrets["admin"]["EMAIL_SENDER"]
        SENDER_PASSWORD = st.secrets["admin"]["EMAIL_PASSWORD"]  # ← GETS "REDACTED"
        RECIPIENTS = [r.strip() for r in st.secrets["admin"]["EMAIL_RECIPIENTS"].split(",")]
    except Exception:
        # Falls back to flat structure only if exception occurs
        # Since "REDACTED" is a valid string, no exception is raised!
```

**Issue:** Even if the password is invalid ("REDACTED"), no exception is raised during loading. The error only appears when SMTP/IMAP login is attempted.

### `mis_email_import.py` (Lines 43-51)
Same issue — loads REDACTED password from nested admin section.

---

## Summary of Changes Needed

| Action | File | Change | Priority |
|--------|------|--------|----------|
| Update Password | `.streamlit/secrets.toml` | Replace "REDACTED" with actual app password | **CRITICAL** |
| No Code Changes Needed | `email_sender.py` | Logic is correct, credentials are the issue | N/A |
| No Code Changes Needed | `mis_email_import.py` | Logic is correct, credentials are the issue | N/A |

---

## Additional Recommendations

1. **Protect Secrets:** Never commit actual passwords to version control, even in comments
2. **Use Environment Variables:** For Streamlit Cloud, use App Settings → Secrets (environment variables)
3. **Test Credentials:** Add a credential validation function on app startup
4. **Error Logging:** Log WHICH credential source succeeded (helps with future debugging)
5. **Separate Secrets File:** Keep a `.streamlit/secrets.toml.example` with placeholder values

---

## Testing Commands

Once credentials are fixed:

```bash
# Test email send (run email job)
python streamlit_app/email_job.py

# Test MIS fetch (run MIS import)
python streamlit_app/services/mis_email_import.py

# Or access via dashboard:
# 1. Open Streamlit dashboard
# 2. Go to "MIS Update" page
# 3. Click "Force Fetch MIS from Gmail"
```
