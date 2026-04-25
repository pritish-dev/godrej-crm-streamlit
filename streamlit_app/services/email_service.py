import smtplib
import os
from email.mime.text import MIMEText

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("EMAIL_PASSWORD")

TO_EMAILS = ["your-email@gmail.com"]  # change this


def send_email(subject, html_content):
    msg = MIMEText(html_content, "html")
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = ", ".join(TO_EMAILS)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL, PASSWORD)
            server.sendmail(EMAIL, TO_EMAILS, msg.as_string())
        print("✅ Email sent successfully")
    except Exception as e:
        print("❌ Email failed:", str(e))