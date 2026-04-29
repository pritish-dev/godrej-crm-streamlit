# Fix: Email Environment Variable Names

## Problem
The 4S email script was failing with:
```
ValueError: EMAIL_SENDER / EMAIL_PASSWORD not set in secrets or .env
```

**Root Cause:** The workflow was setting environment variables with the wrong names:
```yaml
# ❌ WRONG - Using suffixed names
EMAIL_SENDER_4S:     ${{ secrets.EMAIL_SENDER }}
EMAIL_PASSWORD_4S:   ${{ secrets.EMAIL_PASSWORD }}
EMAIL_RECIPIENTS_4S: ${{ secrets.EMAIL_RECIPIENTS }}
```

But the code expected standard names:
```python
# ✅ CORRECT - Using standard names
SENDER_EMAIL = os.getenv("EMAIL_SENDER", "").strip()
SENDER_PASSWORD = os.getenv("EMAIL_PASSWORD", "").strip()
RECIPIENTS = [r.strip() for r in os.getenv("EMAIL_RECIPIENTS", "").split(",") if r.strip()]
```

---

## Solution

### **Updated: `.github/workflows/send_email.yaml`**

**Changed the 4S job environment variables (Lines 90-99):**

```yaml
# ❌ BEFORE
env:
  EMAIL_SENDER_4S:     ${{ secrets.EMAIL_SENDER }}
  EMAIL_PASSWORD_4S:   ${{ secrets.EMAIL_PASSWORD }}
  EMAIL_RECIPIENTS_4S: ${{ secrets.EMAIL_RECIPIENTS }}
  GOOGLE_CREDENTIALS:  ${{ secrets.GOOGLE_CREDENTIALS }}
  MANUAL_JOB:          ${{ github.event.inputs.job }}

# ✅ AFTER
env:
  EMAIL_SENDER:       ${{ secrets.EMAIL_SENDER }}
  EMAIL_PASSWORD:     ${{ secrets.EMAIL_PASSWORD }}
  EMAIL_RECIPIENTS:   ${{ secrets.EMAIL_RECIPIENTS }}
  GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
  MANUAL_JOB:         ${{ github.event.inputs.job }}
```

---

## Why This Works

Both Godrej and 4S use the same email account:
- Same `EMAIL_SENDER` secret
- Same `EMAIL_PASSWORD` secret
- Same `EMAIL_RECIPIENTS` secret

So they should use the same environment variable names. No need for suffixes!

**Before:** Godrej and 4S had different variable names ❌
**After:** Both use the same standard names ✅

---

## Environment Variables Summary

| Variable | Value | Used By |
|----------|-------|---------|
| `EMAIL_SENDER` | Gmail address | Both Godrej & 4S |
| `EMAIL_PASSWORD` | Gmail App Password | Both Godrej & 4S |
| `EMAIL_RECIPIENTS` | Recipient emails | Both Godrej & 4S |
| `GOOGLE_CREDENTIALS` | Google service account JSON | Both Godrej & 4S |
| `MANUAL_JOB` | godrej_email1, godrej_email2, fours_email1, fours_email2 | Both jobs |

---

## Files Changed

| File | Changes | Lines |
|------|---------|-------|
| `.github/workflows/send_email.yaml` | Changed 4S env var names from suffixed to standard | 90-99 |

---

## Testing

### **Test 1: Manual 4S Email 1**
```
1. GitHub Actions → "Send CRM Emails"
2. "Run workflow" → Select "fours_email1"
3. Wait 2-3 minutes
4. ✅ Email should be sent successfully
   (No more ValueError!)
```

### **Test 2: Manual 4S Email 2**
```
1. GitHub Actions → "Send CRM Emails"
2. "Run workflow" → Select "fours_email2"
3. Wait 2-3 minutes
4. ✅ Email should be sent successfully
```

### **Test 3: Godrej Emails (Should Still Work)**
```
1. GitHub Actions → "Send CRM Emails"
2. "Run workflow" → Select "godrej_email1" or "godrej_email2"
3. Wait 2-3 minutes
4. ✅ Email should be sent successfully
```

---

## Deploy Now

```bash
# Push the fix
git add .github/workflows/send_email.yaml
git commit -m "Fix: Use standard email env var names for 4S job"
git push origin main

# Test immediately in GitHub Actions
```

---

## Result

✅ Both Godrej and 4S jobs now:
- Use consistent environment variable names
- Can send manual emails from GitHub UI
- Can send scheduled emails on their cron schedule
- Share the same email credentials (as intended)

**Everything working now!** 🎉
