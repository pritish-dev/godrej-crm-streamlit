# WhatsApp Order-Status Chatbot — Setup Guide

A free WhatsApp chatbot for **Interio by Godrej (4S Interiors, Patia)** that lets
customers check their **order committed status** in **English / Hindi / Odia**.

- **Channel:** WhatsApp Cloud API (official Meta) — free tier, no monthly fee
- **Brain/hosting:** Google Apps Script — free, always-on, reads your Sheets natively
- **Data:** your existing CRM order tabs + `MIS_Daily` (no new data entry)
- **Cost:** ₹0

The customer sends an **Order No**, **Contact Number**, or **Name**; the bot finds
the **Godrej SO No** in the order tabs, looks it up in **`MIS_Daily`**, and replies
with the **committed status** and the **expected commitment date**. No price is
ever shown.

---

## How it works (flow)

```
Customer msg ─▶ Meta Cloud API ─▶ (webhook) Apps Script doPost
                                      │
                                      ├─ ask language (English / हिंदी / ଓଡ଼ିଆ)
                                      ├─ ask Order No / Contact / Name
                                      ├─ find row in CRM order tabs → GODREJ SO NO
                                      ├─ look up SO in MIS_Daily:
                                      │     all lines  Qty == Committed Qty ? → COMMITTED
                                      │     else → expected date = max Inventory Commitment Date
                                      └─ reply in chosen language
```

**Committed logic** mirrors `services/delivery_readiness.py`: an SO is *fully
committed* only when **every** line item has `Sales Order Qty == Sales Order
Committed Qty`; the commitment date is the **latest `Inventory Commitment Date`**
across that SO's items.

---

## Part A — Google Apps Script (the bot)

1. Open the **Google account that owns the CRM/MIS spreadsheets**.
2. Go to <https://script.google.com> → **New project**.
3. Delete the default `Code.gs` content and paste the contents of
   [`Code.gs`](./Code.gs).
4. (Recommended) Project Settings ⚙ → **Script Properties** → add:
   - `WHATSAPP_TOKEN` = *(fill after Part B)*
   - `PHONE_NUMBER_ID` = *(fill after Part B)*
   - `VERIFY_TOKEN` = any string you invent, e.g. `interio4s-verify`
   (If you skip this, fill the same values in the `CONFIG` block at the top of `Code.gs`.)
5. Check the spreadsheet IDs in `CONFIG`:
   - `CRM_SPREADSHEET_ID` — already set to your CRM sheet.
   - `OPS_SPREADSHEET_ID` — set to the file that holds `MIS_Daily` and
     `SHEET_DETAILS`. If everything is in one file, keep it the same as the CRM ID.
6. In the editor, select the function **`testConfig`** and click **Run**.
   Approve the permissions prompt (it needs Sheets + external requests).
   The Execution Log should list your order tabs and confirm `MIS_Daily` is found.
   - Then set `q` inside **`testLookup`** to a real order/name/number and Run it
     to confirm the reply text looks right.
7. **Deploy** → **New deployment** → type **Web app**:
   - *Execute as:* **Me**
   - *Who has access:* **Anyone**
   - Click **Deploy**, authorize, and **copy the Web app URL**
     (looks like `https://script.google.com/macros/s/AKfy.../exec`).
   Keep this URL for Part B.

> Re-deploy after any code edit: **Deploy → Manage deployments → Edit ✏ →
> Version: New version → Deploy.** (The URL stays the same.)

---

## Part B — WhatsApp Cloud API (the channel)

You need a **Meta Business account** and a **spare phone number** that is **not**
currently registered on any WhatsApp / WhatsApp Business app.

1. Go to <https://developers.facebook.com> → **My Apps** → **Create App** →
   type **Business** → name it (e.g. "4S Interio Bot").
2. On the app dashboard, add the **WhatsApp** product.
3. In **WhatsApp → API Setup** you get:
   - a free **test number** (send-from),
   - a temporary **access token**,
   - the **Phone number ID**.
   Copy the **Phone number ID** into your Script Property `PHONE_NUMBER_ID`.
4. Add your own mobile as a **recipient** (test mode allows up to 5) and send the
   sample message to confirm delivery works.
5. **Access token:** the API-Setup token expires in 24h. For production create a
   **permanent token**: Business Settings → **System Users** → add a system user →
   *Generate token* → app = your app, scopes = **`whatsapp_business_messaging`**
   and **`whatsapp_business_management`**. Put this token in `WHATSAPP_TOKEN`.
   Re-deploy the Apps Script so it picks up the new property (or just save — Script
   Properties are read live).
6. **Connect the webhook:** WhatsApp → **Configuration** → **Edit** under Webhook:
   - *Callback URL:* your Apps Script **Web app URL** from Part A.
   - *Verify token:* the exact `VERIFY_TOKEN` string you set.
   - Click **Verify and save** (Meta calls `doGet` and expects the challenge back).
   - Under **Webhook fields**, **Subscribe** to **`messages`**.
7. From your phone, message the test number **"hi"** — the bot should reply with
   the language buttons. 🎉

---

## Part C — Go live (still free)

- Test mode only messages the 5 numbers you add. To serve **all customers**, in
  App Dashboard switch the app from **Development** to **Live**, and complete
  **Meta Business Verification** (free; needs basic business documents). Until
  then, customers who message you first can still be replied to within the
  24-hour service window on the test number for the allowed recipients.
- Add your **own business phone number** (not the test number) in WhatsApp →
  API Setup → *Add phone number*, verify it, and use its Phone number ID.
- Meta gives a monthly free allotment of **service conversations**
  (customer-initiated). A single showroom's volume typically stays free; beyond
  that the per-conversation charge is very small.

---

## Customising

Everything is in `Code.gs`:

| Want to change | Where |
|---|---|
| Which fields are shown / wording | `STR` (en/hi/or templates) |
| Column names (if your headers differ) | `CONFIG.COL_*` and `CONFIG.MIS_*` |
| Order tabs source | `CONFIG.SHEET_DETAILS_TAB` (reads `Franchise_sheets` + `four_s_sheets`) |
| Add a 4th language | add a key to `STR` + a button in `askLanguage()` + `parseLang()` |
| Session length | `CONFIG.SESSION_TTL` (seconds) |

### Privacy note
The bot matches on Order No, Contact Number, or Name as the customer types them.
If you want stricter privacy (only reveal an order to the phone that placed it),
we can match the sender's WhatsApp number against `CONTACT NUMBER` before
replying — say the word and we'll add it.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Webhook "Verify" fails | `VERIFY_TOKEN` must match exactly; Web app access must be **Anyone**; use the `/exec` URL. |
| Bot never replies | `messages` field not subscribed; or token expired — regenerate a permanent token. |
| "not found" for a real order | Run `testConfig` — is the order's tab listed in `SHEET_DETAILS`? Check `COL_*` header names. |
| No committed date shown | The SO isn't in the current `MIS_Daily` snapshot (may already be dispatched), or `Inventory Commitment Date` is blank. |
| Permission error on Run | Re-run and approve the OAuth prompt (Sheets + external request scopes). |
