# 🔐 Streamlit Secrets Setup (For Dashboard Email Triggers)

Your Streamlit dashboard buttons need credentials to send emails. This file configures them locally.

## 📍 File Location
```
.streamlit/secrets.toml
```

This file was created in your repo. Now you need to fill it with your actual credentials.

---

## 🔑 How to Fill in the Values

### **1. EMAIL_SENDER**
Replace `your-email@gmail.com` with your actual Gmail address:
```toml
EMAIL_SENDER = "pritish.sec@gmail.com"
```

### **2. EMAIL_PASSWORD**
Replace `your-app-password-16-chars` with your Gmail App Password:
```toml
EMAIL_PASSWORD = "xxxx xxxx xxxx xxxx"
```

⚠️ **IMPORTANT**: This is your **Gmail App Password**, NOT your regular Gmail password!
- Get it from: https://myaccount.google.com/apppasswords
- It's a 16-character password (with spaces)

### **3. EMAIL_RECIPIENTS**
Replace with your actual recipient emails (comma-separated):
```toml
EMAIL_RECIPIENTS = "pritish@gmail.com,team@company.com"
```

### **4. GOOGLE_CREDENTIALS**
Replace the entire JSON object with your Google Service Account JSON:

Get this from:
1. Google Cloud Console → Create Service Account
2. Download the JSON file
3. Copy the ENTIRE JSON content
4. Paste it between the triple quotes:

```toml
GOOGLE_CREDENTIALS = """{
  "type": "service_account",
  "project_id": "your-actual-project-id",
  ... (rest of JSON)
}"""
```

---

## ✅ Final secrets.toml Should Look Like:

```toml
EMAIL_SENDER = "pritish.sec@gmail.com"
EMAIL_PASSWORD = "abcd efgh ijkl mnop"
EMAIL_RECIPIENTS = "pritish@gmail.com,manager@company.com"
GOOGLE_CREDENTIALS = """{
  "type": "service_account",
  "project_id": "my-gcp-project",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "my-service@my-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/my-service%40my-project.iam.gserviceaccount.com"
}"""
```

---

## 🚨 IMPORTANT SECURITY NOTES

⚠️ **DO NOT COMMIT THIS FILE TO GIT!**

The `.streamlit/secrets.toml` file is already in `.gitignore`, so it won't be committed. But:
- ✅ Keep this file only on your local machine
- ✅ Never share this file publicly
- ✅ In Streamlit Cloud, use Settings → Secrets instead of this file
- ✅ In GitHub Actions, use GitHub Secrets (which you already set up)

---

## ✅ Testing Dashboard Email Triggers

After filling in the secrets:

1. **Save the file**
2. **Restart Streamlit**: Press `Ctrl+C` and run `streamlit run streamlit_app/App.py` again
3. **Go to 4S Dashboard**: Click the 4SINTERIORS page
4. **Scroll to Pending Deliveries** section
5. **Click "📧 Send Delivery Email"** button
6. **Check inbox** for email

If email is received ✅ — all dashboard buttons will work!

---

## 🔍 Troubleshooting

| Error | Solution |
|-------|----------|
| "EMAIL_SENDER not set in secrets" | Fill in EMAIL_SENDER value in secrets.toml |
| "Gmail auth failed" | Use App Password, not regular password |
| "Email not received" | Check EMAIL_RECIPIENTS, check spam folder |
| "Changes not applied" | Restart Streamlit after editing secrets.toml |

---

## 📋 Checklist

- [ ] Edit `.streamlit/secrets.toml`
- [ ] Add EMAIL_SENDER
- [ ] Add EMAIL_PASSWORD (App Password)
- [ ] Add EMAIL_RECIPIENTS
- [ ] Add GOOGLE_CREDENTIALS (full JSON)
- [ ] Save file
- [ ] Restart Streamlit
- [ ] Test "Send Delivery Email" button on 4S Dashboard
- [ ] Verify email received in inbox

Once done, all dashboard email buttons will work! ✅
