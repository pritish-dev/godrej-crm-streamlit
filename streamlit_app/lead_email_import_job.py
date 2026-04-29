"""
Scheduled Job: Lead Email Import via IMAP

Runs every 30 minutes to check for new leads in 4sinteriorsbbsr@gmail.com
and automatically imports them to the LEADS sheet.

Triggered by: GitHub Actions workflow (cron schedule)
Schedule: Every 30 minutes (*/30 * * * *)
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.imap_lead_import import process_lead_emails


def main():
    """Execute lead email import"""
    print("\n🚀 Lead Email Import Job Started")
    print(f"Time: {__import__('datetime').datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")

    # Run the import process
    imported = process_lead_emails()

    print(f"\n📊 Import Summary:")
    print(f"   • Leads imported: {imported}")
    print(f"   • Status: ✅ Success")
    print(f"   • Next run: In 30 minutes")

    return imported


if __name__ == "__main__":
    main()
