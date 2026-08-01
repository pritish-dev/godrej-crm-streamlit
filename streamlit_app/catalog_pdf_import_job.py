"""
catalog_pdf_import_job.py

Standalone automation — reads the B2C product catalogue PDFs from the
B2C_CATALOGUE Google Drive folder, extracts one structured record per product
with Claude vision, uploads each product's photos/swatches to Drive, and
UPSERTS them into the "Product Catalog" Google Sheet.

Idempotent: only new products are appended and only genuinely-changed products
are rewritten; existing rows (and their curated image URLs) are preserved. A row
that is missing its Product Image is backfilled — the catalogue photo is uploaded
to Drive and the link filled in — without touching any other column.

Run it manually or from a scheduler:
    python streamlit_app/catalog_pdf_import_job.py
    python streamlit_app/catalog_pdf_import_job.py --start-page 1 --end-page 20
    python streamlit_app/catalog_pdf_import_job.py --start-page 21 --end-page 40 --update-existing

Required environment / secrets:
    GOOGLE_CREDENTIALS   service-account JSON (Editor on the image folder)
    OPS_SPREADSHEET_ID   OPS spreadsheet id (routing for 'Product Catalog')
    B2C_CATALOGUE        Drive folder id holding the catalogue PDFs
    ANTHROPIC_API_KEY    Anthropic API key for the vision parse
Optional:
    CATALOG_IMAGE_FOLDER_ID   Drive folder to host extracted images
    CATALOG_LLM_MODEL         Claude model id (default claude-opus-5)
"""

import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.catalog_pdf_service import (
    fetch_and_sync_catalog_from_drive,
    CATALOG_SHEET_NAME,
)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Import catalogue PDFs into the Product Catalog sheet.")
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="1-based first page to read per catalogue (default 1).",
    )
    parser.add_argument(
        "--end-page", type=int, default=0,
        help="1-based last page to read, inclusive (0 = to the end).",
    )
    parser.add_argument(
        "--update-existing", action="store_true",
        help="Also rewrite existing products whose text changed (default: leave them).",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f"  Product Catalogue Import — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target sheet : {CATALOG_SHEET_NAME}")
    print(f"  Page window  : {args.start_page}..{args.end_page or 'end'}"
          + ("  (update existing: on)" if args.update_existing else ""))
    print("=" * 60)

    added, updated, status = fetch_and_sync_catalog_from_drive(
        progress=print,
        page_start=args.start_page,
        page_end=(args.end_page or None),
        update_existing=args.update_existing,
    )

    print("\n" + "=" * 60)
    print(status)
    print("=" * 60)

    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="Product Catalogue Import",
            records_count=int(added + updated),
            recipients=[CATALOG_SHEET_NAME],
            status="success" if status.startswith("✅") else "warning",
            error="" if status.startswith("✅") else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    # A clean scan with nothing to do is still success.
    return 0 if status.startswith("✅") else 1


if __name__ == "__main__":
    sys.exit(main())
