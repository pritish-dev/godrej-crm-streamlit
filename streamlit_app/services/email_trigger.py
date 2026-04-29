"""
Email Trigger Service - Send emails directly from Streamlit dashboard

Allows manual triggering of emails without GitHub Actions
Used by franchise and 4S dashboards
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import pandas as pd
from services.sheets import get_df
from datetime import datetime, timezone, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ═════════════════════════════════════════════════════════════════════════════
# SEND COMBINED PENDING DELIVERY EMAIL (Godrej + 4S)
# ═════════════════════════════════════════════════════════════════════════════

def send_combined_pending_delivery_email():
    """
    Send combined Godrej + 4S pending delivery email immediately
    Used when triggered from dashboard button

    Returns:
        dict: {
            'success': bool,
            'message': str,
            'godrej_count': int,
            'fours_count': int
        }
    """
    result = {
        'success': False,
        'message': '',
        'godrej_count': 0,
        'fours_count': 0
    }

    try:
        # Get email credentials
        email_sender = os.getenv("EMAIL_SENDER", "").strip()
        email_password = os.getenv("EMAIL_PASSWORD", "").strip()
        email_recipients = os.getenv("EMAIL_RECIPIENTS", "").strip()

        if not email_sender or not email_password or not email_recipients:
            result['message'] = "❌ Email credentials not configured in GitHub Secrets"
            return result

        # Load franchise data
        godrej_data = pd.DataFrame()
        fours_data = pd.DataFrame()

        # Load Godrej data
        try:
            godrej_df = get_df("GODREJ")
            if godrej_df is not None and not godrej_df.empty:
                godrej_df.columns = [str(c).strip().upper() for c in godrej_df.columns]
                # Filter for pending delivery
                if "STATUS" in godrej_df.columns:
                    godrej_data = godrej_df[godrej_df["STATUS"].astype(str).str.contains("Pending", case=False, na=False)].copy()
                godrej_data["FRANCHISE"] = "Godrej"
                result['godrej_count'] = len(godrej_data)
        except Exception as e:
            result['message'] += f"⚠️ Error loading Godrej data: {str(e)}\n"

        # Load 4S data
        try:
            fours_df = get_df("4S")
            if fours_df is not None and not fours_df.empty:
                fours_df.columns = [str(c).strip().upper() for c in fours_df.columns]
                # Filter for pending delivery
                if "STATUS" in fours_df.columns:
                    fours_data = fours_df[fours_df["STATUS"].astype(str).str.contains("Pending", case=False, na=False)].copy()
                fours_data["FRANCHISE"] = "4S Interiors"
                result['fours_count'] = len(fours_data)
        except Exception as e:
            result['message'] += f"⚠️ Error loading 4S data: {str(e)}\n"

        # Generate HTML email
        html_content = generate_combined_email_html(godrej_data, fours_data)

        # Create email message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[4s CRM] Pending Delivery Status - Franchise and 4s Items"
        msg["From"] = email_sender
        msg["To"] = email_recipients

        msg.attach(MIMEText(html_content, "html"))

        # Send email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_sender, email_password)
            server.sendmail(email_sender, email_recipients.split(","), msg.as_string())

        result['success'] = True
        result['message'] = f"✅ Email sent successfully!\n• Godrej: {result['godrej_count']} pending items\n• 4S: {result['fours_count']} pending items"

        return result

    except smtplib.SMTPAuthenticationError:
        result['message'] = "❌ Email authentication failed. Check EMAIL_PASSWORD and EMAIL_SENDER secrets"
        return result
    except Exception as e:
        result['message'] = f"❌ Error sending email: {str(e)}"
        return result


def generate_combined_email_html(godrej_data, fours_data):
    """Generate HTML content for combined email"""

    today_str = datetime.now().strftime("%d-%m-%Y")

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #003366; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
            .franchise-section {{ margin: 20px 0; }}
            .franchise-title {{ background: #0066cc; color: white; padding: 15px; border-radius: 3px; margin-bottom: 10px; }}
            .section-4s {{ border-left: 5px solid #ff6600; }}
            table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            th {{ background: #f0f0f0; padding: 10px; text-align: left; border: 1px solid #ddd; font-weight: bold; }}
            td {{ padding: 10px; border: 1px solid #ddd; }}
            tr:nth-child(even) {{ background: #f9f9f9; }}
            .summary {{ background: #e8f4f8; padding: 15px; border-radius: 3px; margin-bottom: 20px; }}
            .no-data {{ color: #999; font-style: italic; padding: 20px; text-align: center; }}
            .trigger-info {{ background: #fffacd; padding: 10px; margin-bottom: 15px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>📦 Pending Delivery Status Report</h2>
                <p>Date: {today_str}</p>
                <p style="font-size: 12px; margin-top: 10px;">Manual Trigger from Dashboard</p>
            </div>

            <div class="trigger-info">
                <strong>📱 Triggered:</strong> Manual request from dashboard
                <br><strong>⏰ Time:</strong> {datetime.now().strftime('%H:%M:%S IST')}
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
                This is an automated report triggered from the dashboard. For more details, access the CRM system.
            </p>
        </div>
    </body>
    </html>
    """

    return html
