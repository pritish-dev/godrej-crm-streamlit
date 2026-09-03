# WhatsApp Auto-Reply Bot

Free WhatsApp auto-responder for **Interio by Godrej (4S Interiors, Patia)**. Every
customer who messages the bot's number gets an **instant, intelligent reply** driven
by your CRM. On the first message the bot greets them and shows a menu:

1. **📦 Order status** — customer sends an Order No / Contact Number / Name and gets
   their **committed status** and **expected commitment date** in **English, Hindi,
   or Odia** — pulled live from the CRM order tabs and `MIS_Daily`. No price is shown.
   (Order details are gated behind registered-mobile verification.)
2. **🛋️ Product enquiry** — captures name + what they're looking for and writes a
   **new CRM lead** into the `LEADS` tab (source = *WhatsApp Bot*), so your sales
   team can follow up.
3. **📍 Showroom info** — address, timings, phone, Google Maps directions, Instagram.
4. **🧑‍💼 Talk to a person** — hands off to your **staffed WhatsApp Business App
   number** via a `wa.me` link (and logs the request as a lead so nothing is lost).

- `Code.gs` — the entire bot (Google Apps Script webhook).
- `appsscript.json` — Apps Script manifest (scopes + web-app config).
- `SETUP_GUIDE.md` — step-by-step: deploy the script + connect WhatsApp Cloud API.

**Stack:** WhatsApp Cloud API (Meta, free tier) + Google Apps Script (free) + your
existing Google Sheets. Total hosting cost: ₹0.

> **One number = one channel.** A phone number can be on the WhatsApp Business *App*
> **or** the Cloud API, never both. Run this bot on a **separate/new number** and
> keep your staffed app number (e.g. 9937423954) for the "Talk to a person" handoff —
> or migrate your main number onto the Cloud API. Set the handoff number in
> `CONFIG.HUMAN_HANDOFF_NUMBER` in `Code.gs`.

👉 Start with [`SETUP_GUIDE.md`](./SETUP_GUIDE.md).
