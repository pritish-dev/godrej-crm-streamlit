"""
Scheduled Job: Combined Godrej + 4S Interiors Pending Delivery Email (10 AM IST)

Sends daily email at 10 AM with:
- Godrej pending delivery data
- 4S Interiors pending delivery data
- Combined in single email for better visibility

Replaces separate godrej and 4s email jobs
"""

import sys
import os

# Make sure services/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from datetime import datetime, timezone, timedelta


# ── IST time ─────────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today_str = now_ist.strftime("%d-%m-%Y")

print(f"[Combined Email Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


# ── Load data from both franchises ───────────────────────────────────────────
def load_franchise_data():
    """Load pending delivery data from both Godrej and 4S sheets"""
    godrej_data = pd.DataFrame()
    fours_data = pd.DataFrame()

    try:
        # Load Godrej data
        godrej_df = get_df("GODREJ")
        if godrej_df is not None and not godrej_df.empty:
            godrej_df.columns = [str(c).strip().upper() for c in godrej_df.columns]
            # Filter for pending delivery
            if "STATUS" in godrej_df.columns:
                godrej_data = godrej_df[godrej_df["STATUS"].astype(str).str.contains("Pending", case=False, na=False)].copy()
            godrej_data["FRANCHISE"] = "Godrej"
            print(f"  → Godrej: {len(godrej_data)} pending items")
        else:
            print(f"  → Godrej: No data found")

        # Load 4S data
        fours_df = get_df("4S")
        if fours_df is not None and not fours_df.empty:
            fours_df.columns = [str(c).strip().upper() for c in fours_df.columns]
            # Filter for pending delivery
            if "STATUS" in fours_df.columns:
                fours_data = fours_df[fours_df["STATUS"].astype(str).str.contains("Pending", case=False, na=False)].copy()
            fours_data["FRANCHISE"] = "4S Interiors"
            print(f"  → 4S: {len(fours_data)} pending items")
        else:
            print(f"  → 4S: No data found")

    except Exception as e:
        print(f"  ❌ Error loading data: {e}")

    return godrej_data, fours_data


# ── Generate HTML email ──────────────────────────────────────────────────────
def generate_combined_email_html(godrej_data, fours_data):
    """Generate combined HTML email with both franchises"""

    html = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
            .header { background: #003366; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
            .franchise-section { margin: 20px 0; }
            .franchise-title { background: #0066cc; color: white; padding: 15px; border-radius: 3px; margin-bottom: 10px; }
            .section-4s { border-left: 5px solid #ff6600; }
            table { width: 100%; border-collapse: collapse; margin: 15px 0; }
            th { background: #f0f0f0; padding: 10px; text-align: left; border: 1px solid #ddd; font-weight: bold; }
            td { padding: 10px; border: 1px solid #ddd; }
            tr:nth-child(even) { background: #f9f9f9; }
            .summary { background: #e8f4f8; padding: 15px; border-radius: 3px; margin-bottom: 20px; }
            .no-data { color: #999; font-style: italic; padding: 20px; text-align: center; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>📦 Pending Delivery Status Report</h2>
                <p>Date: {date}</p>
            </div>
    """

    # Godrej Section
    if not godrej_data.empty:
        html += f"""
            <div class="franchise-section">
                <div class="franchise-title">🏢 Godrej - Pending Deliveries ({len(godrej_data)} items)</div>
                <table>
                    <tr>
                        <th>Item</th>
                        <th>Customer</th>
                        <th>Status</th>
                        <th>Due Date</th>
                        <th>Notes</th>
                    </tr>
        """
        for _, row in godrej_data.iterrows():
            html += f"""
                    <tr>
                        <td>{row.get('ITEM', 'N/A')}</td>
                        <td>{row.get('CUSTOMER', 'N/A')}</td>
                        <td>{row.get('STATUS', 'N/A')}</td>
                        <td>{row.get('DUE DATE', 'N/A')}</td>
                        <td>{row.get('NOTES', '')}</td>
                    </tr>
            """
        html += """
                </table>
            </div>
        """
    else:
        html += """
            <div class="franchise-section">
                <div class="franchise-title">🏢 Godrej</div>
                <div class="no-data">✅ No pending deliveries</div>
            </div>
        """

    # 4S Section
    if not fours_data.empty:
        html += f"""
            <div class="franchise-section section-4s">
                <div class="franchise-title" style="background: #ff6600;">🏠 4S Interiors - Pending Deliveries ({len(fours_data)} items)</div>
                <table>
                    <tr>
                        <th>Item</th>
                        <th>Customer</th>
                        <th>Status</th>
                        <th>Due Date</th>
                        <th>Notes</th>
                    </tr>
        """
        for _, row in fours_data.iterrows():
            html += f"""
                    <tr>
                        <td>{row.get('ITEM', 'N/A')}</td>
                        <td>{row.get('CUSTOMER', 'N/A')}</td>
                        <td>{row.get('STATUS', 'N/A')}</td>
                        <td>{row.get('DUE DATE', 'N/A')}</td>
                        <td>{row.get('NOTES', '')}</td>
                    </tr>
            """
        html += """
                </table>
            </div>
        """
    else:
        html += """
            <div class="franchise-section section-4s">
                <div class="franchise-title" style="background: #ff6600;">🏠 4S Interiors</div>
                <div class="no-data">✅ No pending deliveries</div>
            </div>
        """

    # Summary
    total_pending = len(godrej_data) + len(fours_data)
    html += f"""
            <div class="summary">
                <h3>📊 Summary</h3>
                <p><strong>Total Pending Deliveries:</strong> {total_pending}</p>
                <p><strong>Godrej:</strong> {len(godrej_data)} items</p>
                <p><strong>4S Interiors:</strong> {len(fours_data)} items</p>
            </div>

            <hr style="border: none; border-top: 2px solid #ddd; margin: 20px 0;">
            <p style="color: #999; font-size: 12px;">
                This is an automated report. For more details, access the CRM dashboard.
            </p>
        </div>
    </body>
    </html>
    """

    return html.format(date=today_str)


# ── Send email ───────────────────────────────────────────────────────────────
def send_combined_email(godrej_data, fours_data):
    """Send combined email to recipients"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    email_sender = os.getenv("EMAIL_SENDER", "").strip()
    email_password = os.getenv("EMAIL_PASSWORD", "").strip()
    email_recipients = os.getenv("EMAIL_RECIPIENTS", "").strip()

    if not email_sender or not email_password or not email_recipients:
        print("  ❌ Email credentials not configured")
        return False

    try:
        # Generate email content
        html_content = generate_combined_email_html(godrej_data, fours_data)

        # Create email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[4s CRM] Pending Delivery Status - 10:00 AM"
        msg["From"] = email_sender
        msg["To"] = email_recipients

        msg.attach(MIMEText(html_content, "html"))

        # Send email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_sender, email_password)
            server.sendmail(email_sender, email_recipients.split(","), msg.as_string())

        print(f"  ✅ Email sent to {email_recipients}")
        return True

    except Exception as e:
        print(f"  ❌ Error sending email: {e}")
        return False


# ── Main execution ───────────────────────────────────────────────────────────
godrej_data, fours_data = load_franchise_data()
send_combined_email(godrej_data, fours_data)

print("✅ Combined Franchise Email (10 AM) job completed")
