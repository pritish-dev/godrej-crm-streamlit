# WhatsApp Order-Status Chatbot

Free WhatsApp bot for **Interio by Godrej (4S Interiors, Patia)**. Customers send an
**Order No / Contact Number / Name** and get their **order committed status** and
**expected commitment date** in **English, Hindi, or Odia** — pulled live from the
CRM order tabs and `MIS_Daily`. No price is shown.

- `Code.gs` — the entire bot (Google Apps Script webhook).
- `appsscript.json` — Apps Script manifest (scopes + web-app config).
- `SETUP_GUIDE.md` — step-by-step: deploy the script + connect WhatsApp Cloud API.

**Stack:** WhatsApp Cloud API (Meta, free tier) + Google Apps Script (free) + your
existing Google Sheets. Total hosting cost: ₹0.

👉 Start with [`SETUP_GUIDE.md`](./SETUP_GUIDE.md).
