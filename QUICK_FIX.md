# Quick Fix: Google Reviews Authentication Error

## ⚠️ Problem
```
❌ Auth failure. Add GOOGLE_PLACES_API_KEY and GOOGLE_PLACE_ID to Streamlit secrets...
```

---

## ✅ Quick Fix (5 Minutes)

### 1. Get API Key & Place ID

**Step A: Get Google Places API Key**
- Open [Google Cloud Console](https://console.cloud.google.com/)
- Project: `crm4sinteriors`
- Enable "Places API" (search for it in API Library)
- Credentials → Create API Key
- Copy the key

**Step B: Get Your Business Place ID**
- Search for your business on [Google Maps](https://maps.google.com/)
- Find: **4S Interiors Bhubaneswar**
- Copy the number from the URL: `maps.google.com/?cid=PLACE_ID`

### 2. Add to Secrets File

Edit `.streamlit/secrets.toml` and add:

```toml
GOOGLE_PLACES_API_KEY = "AIzaSyD_YOUR_KEY_HERE"
GOOGLE_PLACE_ID = "ChIJ_YOUR_PLACE_ID_HERE"
```

### 3. Restart App

Stop the Streamlit app (Ctrl+C) and run it again:
```bash
streamlit run streamlit_app/app.py
```

---

## 🎯 That's It!

The error should be gone. Your reviews feature is now working!

---

## 📚 Need More Help?

See **GOOGLE_REVIEWS_SETUP.md** for:
- Detailed step-by-step instructions
- Alternative GMB v4 API setup (full review history)
- Troubleshooting tips
- How reviews are matched to customers

---

## 🔐 Security Notes

✅ **DO:**
- Add credentials to `.streamlit/secrets.toml`
- Keep secrets.toml in .gitignore (don't commit to GitHub)
- Use Google Cloud to manage API key restrictions

❌ **DON'T:**
- Commit secrets.toml to version control
- Share credentials via email
- Use service account keys for Places API (use API keys instead)
