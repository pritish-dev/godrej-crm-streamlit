"""
services/catalog_pdf_service.py

Standalone automation that reads the B2C product catalogue PDFs from a Google
Drive folder, extracts one structured record per product using Claude vision,
extracts + uploads each product's photos and colour swatches to a Google Drive
folder, and UPSERTS the result into the "Product Catalog" Google Sheet (OPS
spreadsheet) that the Product Catalogue dashboard page reads.

The output columns match the existing sheet exactly:

    Main Category | Sub Category | Product Name | Features |
    Measurements | Colour & Material | Product Image URLs | Swatch Image URLs

Idempotency contract (as requested):
  * New products are APPENDED beneath the existing rows — existing rows and
    their order are never disturbed.
  * An existing product is only re-written when its text content actually
    changed (compared on a punctuation/whitespace-insensitive signature so
    harmless LLM wording drift does not cause churn).
  * Unchanged products are left completely untouched — no writes.
  * Images are extracted + uploaded for NEW products, and a MISSING product
    image is backfilled onto an existing row (its "Product Image URLs" cell is
    blank) by extracting the catalogue photo, uploading it to Drive, and filling
    in the link — without touching any other column. This backfill runs on every
    scan (it does not require the "update existing" switch). The hand-curated
    image URLs already in the sheet are always preserved, and images are never
    re-uploaded on a re-run (uploads are idempotent by deterministic filename).

WHY Claude vision: the catalogue PDFs are two-column marketing layouts whose
plain-text extraction is badly interleaved between the two columns. A rendered
page image sent to Claude yields clean, per-product fields plus a bounding box
for each product's block, which we use to associate the raster images extracted
from the PDF with the right product.

Required configuration
----------------------
  B2C_CATALOGUE            Drive folder ID holding the catalogue PDFs.
     - .streamlit/secrets.toml -> [drive] B2C_CATALOGUE = "..."
     - GitHub Secret / env var -> B2C_CATALOGUE
  ANTHROPIC_API_KEY        Anthropic API key for the vision parse.
     - .streamlit/secrets.toml -> ANTHROPIC_API_KEY = "..."  (or [anthropic] api_key)
     - env var -> ANTHROPIC_API_KEY
  Google service-account    same [google] secret / GOOGLE_CREDENTIALS the rest
                            of the CRM uses. Used to READ the catalogue PDFs and
                            to write the Google Sheet.
  Drive uploads             A service account has NO Drive storage quota, so it
                            cannot own/upload files in My Drive — image uploads
                            403 with 'storageQuotaExceeded'. Pick ONE identity
                            that CAN own files (in priority order):
                              1. Service account + Shared Drive — put the image
                                 folder on a Shared Drive and add the SA as a
                                 member. No extra config; files are owned by the
                                 drive. (Needs Google Workspace.)
                              2. Service account + domain-wide delegation —
                                 [drive] impersonate_user = "user@yourdomain"
                                 (or env DRIVE_IMPERSONATE_USER). Uploads run as
                                 that real user; files use their quota.
                              3. OAuth user credentials —
                                 [drive_oauth] client_id / client_secret /
                                 refresh_token (or DRIVE_OAUTH_* env). Mint once
                                 with tools/generate_drive_oauth_token.py.
                            The owning identity must have Editor access to the
                            image folder (CATALOG_IMAGE_FOLDER_ID). With none of
                            these, text still syncs; only images fail.

Optional configuration
----------------------
  CATALOG_IMAGE_FOLDER_ID  Drive folder that hosts the extracted images.
                           Defaults to the existing folder used by the current
                           rows. ([drive] CATALOG_IMAGE_FOLDER_ID or env)
  CATALOG_LLM_MODEL        Claude model id (default "claude-opus-5"). Set to
                           "claude-sonnet-5" for a cheaper/faster scan.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re

import pandas as pd

# ── Sheet + column config ────────────────────────────────────────────────────
CATALOG_SHEET_NAME = "Product Catalog"

CATALOG_COLUMNS = [
    "Main Category",
    "Sub Category",
    "Product Name",
    "Features",
    "Measurements",
    "Colour & Material",
    "Product Image URLs",
    "Swatch Image URLs",
]

# Drive folder that already hosts the catalogue images referenced by the current
# rows (files named like "Nebula_V3_main_1.png" / "Nebula_V3_swatch_1.png").
DEFAULT_IMAGE_FOLDER_ID = "1PGdL47AQXliSpX9i8MIQz3oeAknxJM8I"

# Thumbnail URL scheme used by every existing image cell in the sheet.
_THUMB_URL = "https://drive.google.com/thumbnail?id={id}&sz=w1000"

DEFAULT_LLM_MODEL = "claude-sonnet-5"

# Drive write access is required to upload images and make them link-viewable.
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Feature bullets are prefixed with this sparkle to match the existing rows.
_BULLET = "✨ "  # "✨ "

# Render pages at ~130 DPI — enough for the model to read the text cleanly while
# staying under the model's long-edge image limit.
_RENDER_DPI = 130

# A raster placement smaller than this fraction of the page (per side) is treated
# as a colour swatch rather than a product photo.
_SWATCH_MAX_SIDE_FRAC = 0.10
# A placement larger than this fraction of the page area is treated as a
# full-bleed background and ignored.
_BACKGROUND_MIN_AREA_FRAC = 0.85
# A placement smaller than this fraction of the page area is treated as an icon
# / rule / logo and ignored.
_MIN_AREA_FRAC = 0.0008


# ═════════════════════════════════════════════════════════════════════════════
# CONFIG / CREDENTIAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _secret(*path):
    """Read a nested Streamlit secret, returning "" on any miss."""
    try:
        import streamlit as st
        node = st.secrets
        for key in path:
            node = node[key]
        return str(node).strip()
    except Exception:
        return ""


def _get_catalog_folder_id() -> str:
    fid = _secret("drive", "B2C_CATALOGUE") or os.getenv("B2C_CATALOGUE", "").strip()
    if fid:
        return fid
    raise RuntimeError(
        "B2C_CATALOGUE not set.\n"
        "  - secrets.toml -> [drive] B2C_CATALOGUE = 'your-folder-id'\n"
        "  - GitHub secret / env var -> B2C_CATALOGUE"
    )


def _get_image_folder_id() -> str:
    return (
        _secret("drive", "CATALOG_IMAGE_FOLDER_ID")
        or os.getenv("CATALOG_IMAGE_FOLDER_ID", "").strip()
        or DEFAULT_IMAGE_FOLDER_ID
    )


def _get_model() -> str:
    return (
        _secret("anthropic", "model")
        or _secret("CATALOG_LLM_MODEL")
        or os.getenv("CATALOG_LLM_MODEL", "").strip()
        or DEFAULT_LLM_MODEL
    )


def _get_impersonate_user() -> str:
    """Return the Workspace user the service account should impersonate, if any.

    Set this when the service account has **domain-wide delegation**: uploads
    then run as this real user, so the created files are owned by them (with
    their storage quota) instead of the quota-less service account.
      * secrets.toml -> [drive] impersonate_user  (or [google] impersonate_user)
      * env var       -> DRIVE_IMPERSONATE_USER
    """
    return (
        _secret("drive", "impersonate_user")
        or _secret("google", "impersonate_user")
        or os.getenv("DRIVE_IMPERSONATE_USER", "").strip()
    )


def _get_drive_creds():
    from google.oauth2.service_account import Credentials
    creds = None
    # 1. Streamlit secrets
    try:
        import streamlit as st
        creds = Credentials.from_service_account_info(dict(st.secrets["google"]), scopes=_SCOPES)
    except Exception:
        creds = None
    # 2. GOOGLE_CREDENTIALS env (JSON blob — GitHub Actions)
    if creds is None:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            creds = Credentials.from_service_account_info(json.loads(raw), scopes=_SCOPES)
    # 3. GOOGLE_APPLICATION_CREDENTIALS path
    if creds is None:
        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if path and os.path.exists(path):
            creds = Credentials.from_service_account_file(path, scopes=_SCOPES)
    # 4. Local file
    if creds is None and os.path.exists("config/credentials.json"):
        creds = Credentials.from_service_account_file("config/credentials.json", scopes=_SCOPES)
    if creds is None:
        raise RuntimeError(
            "No valid Google credentials. Set [google] in secrets.toml or GOOGLE_CREDENTIALS."
        )
    # Domain-wide delegation: act as a real user so uploaded files are owned by
    # them (a bare service account has no Drive storage quota and can't own
    # files in My Drive — every upload would 403 storageQuotaExceeded).
    subject = _get_impersonate_user()
    if subject:
        try:
            creds = creds.with_subject(subject)
        except Exception:
            pass
    return creds


def _get_drive_oauth_config() -> dict:
    """Return {client_id, client_secret, refresh_token} for OAuth Drive uploads.

    A Google **service account has no Drive storage quota of its own**, so it
    cannot create/own files in a normal (My Drive) folder — every upload fails
    with 403 storageQuotaExceeded. To upload into the existing image folder we
    act as a real Google user via OAuth; the files are then owned by that user
    and draw on their 15 GB quota.

    Looked up (first hit wins):
      * secrets.toml -> [drive_oauth] client_id / client_secret / refresh_token
      * env DRIVE_OAUTH_TOKEN = '{"client_id":..,"client_secret":..,"refresh_token":..}'
      * env DRIVE_OAUTH_CLIENT_ID / DRIVE_OAUTH_CLIENT_SECRET / DRIVE_OAUTH_REFRESH_TOKEN

    Returns {} when OAuth is not configured (caller falls back to the service
    account, which is still fine for read-only listing/downloading).
    """
    # 1. Streamlit secrets table
    try:
        import streamlit as st
        node = dict(st.secrets["drive_oauth"])
        cfg = {
            "client_id": str(node.get("client_id", "")).strip(),
            "client_secret": str(node.get("client_secret", "")).strip(),
            "refresh_token": str(node.get("refresh_token", "")).strip(),
        }
        if all(cfg.values()):
            return cfg
    except Exception:
        pass
    # 2. Single JSON env blob
    raw = os.getenv("DRIVE_OAUTH_TOKEN", "").strip()
    if raw:
        try:
            node = json.loads(raw)
            cfg = {
                "client_id": str(node.get("client_id", "")).strip(),
                "client_secret": str(node.get("client_secret", "")).strip(),
                "refresh_token": str(node.get("refresh_token", "")).strip(),
            }
            if all(cfg.values()):
                return cfg
        except Exception:
            pass
    # 3. Individual env vars
    cfg = {
        "client_id": os.getenv("DRIVE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("DRIVE_OAUTH_CLIENT_SECRET", "").strip(),
        "refresh_token": os.getenv("DRIVE_OAUTH_REFRESH_TOKEN", "").strip(),
    }
    if all(cfg.values()):
        return cfg
    return {}


def _get_drive_oauth_creds():
    """Build refreshable OAuth user credentials for Drive, or None if unset."""
    cfg = _get_drive_oauth_config()
    if not cfg:
        return None
    from google.oauth2.credentials import Credentials as UserCredentials
    from google.auth.transport.requests import Request
    creds = UserCredentials(
        None,
        refresh_token=cfg["refresh_token"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    creds.refresh(Request())   # mint an access token now; raises clearly if bad
    return creds


def _build_drive_service():
    from googleapiclient.discovery import build
    # Prefer OAuth user creds for writes (service accounts can't own files);
    # fall back to the service account (fine for read-only listing/download).
    creds = _get_drive_oauth_creds() or _get_drive_creds()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_anthropic_client():
    try:
        import anthropic
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "The 'anthropic' package is required for catalogue extraction. "
            "Add it to requirements.txt and redeploy."
        ) from exc

    api_key = (
        _secret("ANTHROPIC_API_KEY")
        or _secret("anthropic", "api_key")
        or os.getenv("ANTHROPIC_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set.\n"
            "  - secrets.toml -> ANTHROPIC_API_KEY = '...'  (or [anthropic] api_key)\n"
            "  - env var -> ANTHROPIC_API_KEY"
        )
    return anthropic.Anthropic(api_key=api_key)


# ═════════════════════════════════════════════════════════════════════════════
# DRIVE — LIST / DOWNLOAD PDFs
# ═════════════════════════════════════════════════════════════════════════════

def _sort_key(name: str):
    """Sort catalogue PDFs so the LIVING ROOM catalogue is processed first.

    The initial sheet rows came from the living-room catalogue, so we start
    there for continuity; everything else follows alphabetically.
    """
    lowered = name.lower()
    return (0 if "living" in lowered else 1, lowered)


def _list_pdfs_in_folder(folder_id: str) -> list:
    service = _build_drive_service()
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/pdf' "
        "and trashed=false"
    )
    files = []
    page_token = None
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageSize=100,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    files.sort(key=lambda f: _sort_key(f.get("name", "")))
    return files


def _download_pdf_bytes(file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    service = _build_drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# DRIVE — UPLOAD IMAGES (idempotent) + MAKE LINK-VIEWABLE
# ═════════════════════════════════════════════════════════════════════════════

def _find_image_by_name(service, folder_id: str, name: str):
    """Return an existing file id for `name` in the folder, else None.

    Makes re-runs idempotent — if a previous run already uploaded an image with
    this deterministic name we reuse it instead of creating a duplicate.
    """
    safe = name.replace("'", "\\'")
    resp = service.files().list(
        q=(
            f"'{folder_id}' in parents and name = '{safe}' "
            "and trashed = false"
        ),
        fields="files(id)",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _upload_image(service, folder_id: str, name: str, data: bytes, mime: str) -> str:
    """Upload one image, make it link-viewable, and return its thumbnail URL.

    Reuses an existing file of the same name (idempotent re-runs).
    """
    from googleapiclient.http import MediaIoBaseUpload

    existing = _find_image_by_name(service, folder_id, name)
    if existing:
        file_id = existing
    else:
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
        created = service.files().create(
            body={"name": name, "parents": [folder_id]},
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        file_id = created["id"]

    # Ensure "anyone with the link can view" so the thumbnail URL renders.
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception:
        pass  # already shared, or shared-drive policy — thumbnail still works

    return _THUMB_URL.format(id=file_id)


# ═════════════════════════════════════════════════════════════════════════════
# PDF — RENDER PAGES + EXTRACT RASTER IMAGES (PyMuPDF / fitz)
# ═════════════════════════════════════════════════════════════════════════════

def _render_page_png(page) -> bytes:
    import fitz
    zoom = _RENDER_DPI / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return pix.tobytes("png")


# DPI used when cropping a product photo out of the page. Higher than the
# vision-parse DPI so the saved product image is crisp in the catalogue UI.
_CROP_DPI = 220
# Padding (page fractions) added around the model's photo box before cropping,
# so a slightly-tight box doesn't clip the edges of the furniture.
_CROP_PAD = 0.012
# A photo box smaller than this on either side is treated as degenerate/unusable.
_CROP_MIN_SIDE = 0.03


def _norm_box(region):
    """Return (x0, y0, x1, y1) as ordered floats in 0..1, or None if unusable."""
    try:
        x0, y0 = float(region["x0"]), float(region["y0"])
        x1, y1 = float(region["x1"]), float(region["y1"])
    except (TypeError, KeyError, ValueError):
        return None
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    # Some models emit 0..100 instead of 0..1 — normalise if clearly out of range.
    if max(x1, y1) > 1.5:
        x0, y0, x1, y1 = x0 / 100.0, y0 / 100.0, x1 / 100.0, y1 / 100.0
    x0 = min(max(x0, 0.0), 1.0)
    y0 = min(max(y0, 0.0), 1.0)
    x1 = min(max(x1, 0.0), 1.0)
    y1 = min(max(y1, 0.0), 1.0)
    if (x1 - x0) < _CROP_MIN_SIDE or (y1 - y0) < _CROP_MIN_SIDE:
        return None
    return x0, y0, x1, y1


def _crop_region_png(page, region, dpi: int = _CROP_DPI, pad: float = _CROP_PAD):
    """Render just ``region`` (normalised box) of the page to PNG bytes.

    This crops the product photo straight out of the rendered page, so it works
    no matter how the PDF embeds its art (flattened full-page raster, placed
    vector, or individual images) — unlike raster extraction, which misses
    flattened/vector layouts entirely. Returns None on any unusable box.
    """
    import fitz
    box = _norm_box(region)
    if not box:
        return None
    x0, y0, x1, y1 = box
    pw = float(page.rect.width) or 1.0
    ph = float(page.rect.height) or 1.0
    cx0 = max(0.0, x0 - pad) * pw
    cy0 = max(0.0, y0 - pad) * ph
    cx1 = min(1.0, x1 + pad) * pw
    cy1 = min(1.0, y1 + pad) * ph
    clip = fitz.Rect(cx0, cy0, cx1, cy1)
    if clip.is_empty or clip.is_infinite:
        return None
    zoom = dpi / 72.0
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
        if pix.width < 8 or pix.height < 8:
            return None
        return pix.tobytes("png")
    except Exception:
        return None


def _extract_page_images(doc, page) -> list:
    """Return a list of placed raster images on the page.

    Each item: {bytes, ext, cx, cy, area_frac, side_frac} where cx/cy are the
    placement centre normalised to the page (0..1), area_frac is the placement
    area / page area, and side_frac is max(width,height)/page-side.
    """
    pw = float(page.rect.width) or 1.0
    ph = float(page.rect.height) or 1.0
    page_area = pw * ph

    out = []
    seen = set()
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        if not rects:
            continue

        raw = None  # extracted lazily once we know a placement is worth keeping
        for rect in rects:
            w = float(rect.width)
            h = float(rect.height)
            if w <= 0 or h <= 0:
                continue
            area_frac = (w * h) / page_area
            side_frac = max(w / pw, h / ph)
            if area_frac > _BACKGROUND_MIN_AREA_FRAC or area_frac < _MIN_AREA_FRAC:
                continue

            cx = (float(rect.x0) + float(rect.x1)) / 2.0 / pw
            cy = (float(rect.y0) + float(rect.y1)) / 2.0 / ph
            key = (xref, round(cx, 3), round(cy, 3))
            if key in seen:
                continue
            seen.add(key)

            if raw is None:
                try:
                    raw = doc.extract_image(xref)
                except Exception:
                    raw = {}
            data = raw.get("image")
            if not data:
                continue

            out.append({
                "bytes": data,
                "ext": (raw.get("ext") or "png").lower(),
                "cx": cx,
                "cy": cy,
                "area_frac": area_frac,
                "side_frac": side_frac,
            })
    return out


# ═════════════════════════════════════════════════════════════════════════════
# CLAUDE VISION — PARSE ONE PAGE INTO PRODUCT RECORDS
# ═════════════════════════════════════════════════════════════════════════════

_PAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "main_category": {"type": "string"},
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "product_name": {"type": "string"},
                    "sub_category": {"type": "string"},
                    "features": {"type": "array", "items": {"type": "string"}},
                    "measurements": {"type": "string"},
                    "colour": {"type": "string"},
                    "material": {"type": "string"},
                    "region": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "x0": {"type": "number"},
                            "y0": {"type": "number"},
                            "x1": {"type": "number"},
                            "y1": {"type": "number"},
                        },
                        "required": ["x0", "y0", "x1", "y1"],
                    },
                    "photo_region": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "x0": {"type": "number"},
                            "y0": {"type": "number"},
                            "x1": {"type": "number"},
                            "y1": {"type": "number"},
                        },
                        "required": ["x0", "y0", "x1", "y1"],
                    },
                },
                "required": [
                    "product_name", "sub_category", "features",
                    "measurements", "colour", "material", "region", "photo_region",
                ],
            },
        },
    },
    "required": ["main_category", "products"],
}

_PAGE_PROMPT = """You are reading ONE page from a Godrej Interio furniture catalogue (a two-column marketing layout). Extract every distinct PRODUCT shown on this page as structured data.

If this page is a cover, index, contents, care-booklet, or a page with no actual product (name + specs), return an empty products list.

Room hint for this catalogue: "{hint}". Use it as the main_category (e.g. "Living Room", "Dining Room", "Bedroom") unless the page clearly indicates a different room.

For each product return:
- product_name: the model name exactly as printed (e.g. "Harmony V2", "Orlando Plus", "Salt & Pepper Dining Table"). Do NOT include the category words.
- sub_category: the specific product type shown near the name (e.g. "Sofa", "Recliner", "Coffee Table", "HEC & TV Unit", "Dining Table", "Wardrobe"). Keep it short.
- features: each bullet under "Features" / "Details" as ONE clean, complete sentence. Remove bullet symbols and fix words split across line breaks. Keep the original wording.
- measurements: combine the dimensions into a single string using centimetres.
    * If the product has seater / size variants, put each on its own line like:
      "1 Seater: Width: 101cm | Depth: 97.5cm | Height: 93cm | Seat Height: 46cm\\n3 Seater: Width: 231cm | Depth: 97.5cm | Height: 93cm | Seat Height: 46cm"
    * Otherwise use a single line like "Width: 174cm | Depth: 98cm | Height: 93cm".
    * If only loose numbers are shown, join them with " | ". Omit values you cannot read.
- colour: the colour option name(s) shown, comma separated (e.g. "Fab Grey" or "Brown, Black").
- material: the upholstery / material text (e.g. "Fabric", "Pure Leather", "Fabric & Leatherette", "Glass + Metal").
- region: the normalised bounding box (x0,y0,x1,y1 each between 0 and 1, origin top-left) of the area on THIS page occupied by this product's photo(s), name, and specs. Be generous so it covers the product's photos.
- photo_region: the normalised bounding box (x0,y0,x1,y1 each between 0 and 1, origin top-left) of JUST the main/hero PRODUCT PHOTO for this product — the large lifestyle image of the furniture itself. Draw it as tightly as you can around only the photo: EXCLUDE the product name, the feature text, the dimension/specs text, page numbers, logos, and the small colour swatch chips. If the product has several photos, pick the single largest hero shot. This box is used to crop the product image out of the page, so accuracy matters.

Return ONLY the structured JSON."""


def _loads_lenient(text: str):
    """Parse JSON from a model reply, tolerating markdown fences / stray prose.

    Returns the parsed object, or None if no JSON object can be recovered.
    """
    t = str(text or "").strip()
    if not t:
        return None
    if t.startswith("```"):                      # ```json … ``` fences
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)       # first {...} block anywhere
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _resp_text(resp) -> str:
    """Concatenate all text blocks of a Messages response (order preserved)."""
    parts = []
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", None) == "text" and getattr(b, "text", None):
            parts.append(b.text)
    return "".join(parts)


def _parse_page(client, model: str, png_bytes: bytes, hint: str,
                say=None, label: str = "") -> dict:
    b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
    prompt = _PAGE_PROMPT.format(hint=hint)
    # NB: client.messages.create() may raise (e.g. 400/timeout). We let it
    # propagate so the caller logs it — a swallowed error is exactly what made
    # the previous version bill the API yet report "no products".
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        thinking={"type": "disabled"},
        output_config={"format": {"type": "json_schema", "schema": _PAGE_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": b64,
                }},
                {"type": "text", "text": prompt},
            ],
        }],
    )

    def _diag(msg):
        if say:
            say(f"   ⚠️ {label}: {msg}")

    if getattr(resp, "stop_reason", None) == "refusal":
        _diag("model refused this page (skipped)")
        return {"main_category": hint, "products": []}

    text = _resp_text(resp)
    if not text.strip():
        _diag(f"empty response (stop_reason={getattr(resp, 'stop_reason', '?')})")
        return {"main_category": hint, "products": []}

    data = _loads_lenient(text)
    if not isinstance(data, dict):
        snippet = text.strip().replace("\n", " ")[:200]
        _diag(f"could not read product JSON from {len(text)} chars: {snippet!r}")
        return {"main_category": hint, "products": []}

    if not isinstance(data.get("products"), list):
        data["products"] = []
    return data


# ═════════════════════════════════════════════════════════════════════════════
# ASSOCIATE EXTRACTED IMAGES WITH PARSED PRODUCTS
# ═════════════════════════════════════════════════════════════════════════════

def _point_in_region(cx, cy, region) -> bool:
    try:
        x0, y0 = float(region["x0"]), float(region["y0"])
        x1, y1 = float(region["x1"]), float(region["y1"])
    except Exception:
        return False
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    # small tolerance so images that overhang the model's box still match
    pad = 0.03
    return (x0 - pad) <= cx <= (x1 + pad) and (y0 - pad) <= cy <= (y1 + pad)


def _assign_images(products: list, images: list) -> list:
    """Attach {main_images, swatch_images} (lists of raw image dicts) to each
    product based on the model's per-product region boxes.

    Fallback when regions don't line up: split the images across products in
    reading order (left-to-right, top-to-bottom) so nothing is silently lost.
    """
    for p in products:
        p["main_images"] = []
        p["swatch_images"] = []

    if not products:
        return products

    matched_any = False
    for img in images:
        target = None
        for p in products:
            if _point_in_region(img["cx"], img["cy"], p.get("region", {})):
                target = p
                break
        if target is None:
            continue
        matched_any = True
        if img["side_frac"] <= _SWATCH_MAX_SIDE_FRAC:
            target["swatch_images"].append(img)
        else:
            target["main_images"].append(img)

    if not matched_any and images:
        # Regions unusable — distribute by reading order across products.
        ordered = sorted(images, key=lambda i: (round(i["cy"], 2), i["cx"]))
        n = len(products)
        for idx, img in enumerate(ordered):
            target = products[min(idx * n // max(len(ordered), 1), n - 1)]
            if img["side_frac"] <= _SWATCH_MAX_SIDE_FRAC:
                target["swatch_images"].append(img)
            else:
                target["main_images"].append(img)

    # Stable ordering within each product: top-to-bottom, left-to-right.
    for p in products:
        p["main_images"].sort(key=lambda i: (round(i["cy"], 2), i["cx"]))
        p["swatch_images"].sort(key=lambda i: (round(i["cy"], 2), i["cx"]))
    return products


# ═════════════════════════════════════════════════════════════════════════════
# FORMAT FIELDS TO MATCH THE SHEET
# ═════════════════════════════════════════════════════════════════════════════

def _clean_line(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _format_features(features) -> str:
    lines = []
    for f in features or []:
        c = _clean_line(f)
        if c:
            lines.append(_BULLET + c)
    return "\n".join(lines)


def _format_colour_material(colour: str, material: str) -> str:
    colour = _clean_line(colour)
    material = _clean_line(material)
    if colour and material:
        return f"{colour}\n{material}"
    return colour or material


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "").strip())
    return s.strip("_") or "Product"


def _norm_key(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _sig(text: str) -> str:
    """Punctuation/whitespace/case-insensitive signature used to decide whether
    an existing product's text truly changed (ignores harmless LLM drift)."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API — SCAN DRIVE, UPSERT SHEET
# ═════════════════════════════════════════════════════════════════════════════

def _empty_df():
    return pd.DataFrame(columns=CATALOG_COLUMNS)


def _load_existing():
    """Return the current 'Product Catalog' sheet as a DataFrame (8 columns)."""
    try:
        from services.sheets import get_df
        df = get_df(CATALOG_SHEET_NAME)
    except Exception:
        return _empty_df()
    if df is None or df.empty:
        return _empty_df()
    for col in CATALOG_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[CATALOG_COLUMNS].fillna("")


def _upload_product_images(service, image_folder_id, product, *,
                           want_main=True, want_swatch=True, say=None) -> tuple[str, str]:
    """Upload a product's main + swatch images; return (main_urls, swatch_urls).

    ``want_main`` / ``want_swatch`` let a caller upload only one kind — used by
    the backfill path, which needs to fill a missing product photo on a row
    whose swatch URLs are already present (so it must not re-upload swatches).

    The MAIN product image is the photo cropped straight off the rendered page
    (``product["main_crop"]``); if that isn't present we fall back to any raster
    images extracted from the PDF (``product["main_images"]``). Upload failures
    are logged via ``say`` rather than swallowed, so a broken run is diagnosable.
    """
    slug = _slug(product["product_name"])
    main_urls, swatch_urls = [], []

    def _warn(msg):
        if say:
            say(f"      ⚠️ image upload: {msg}")

    if want_main:
        crop = product.get("main_crop")
        if crop and crop.get("bytes"):
            try:
                main_urls.append(_upload_image(
                    service, image_folder_id, f"{slug}_main_1.png",
                    crop["bytes"], "image/png",
                ))
            except Exception as exc:
                _warn(f"{slug} main crop failed: {exc}")
        else:
            # Fallback: raster images extracted from the PDF (older path).
            for i, img in enumerate(product.get("main_images", []), start=1):
                name = f"{slug}_main_{i}.png"
                mime = f"image/{'jpeg' if img['ext'] in ('jpg', 'jpeg') else 'png'}"
                try:
                    main_urls.append(_upload_image(service, image_folder_id, name, img["bytes"], mime))
                except Exception as exc:
                    _warn(f"{name} failed: {exc}")

    if want_swatch:
        for i, img in enumerate(product.get("swatch_images", []), start=1):
            name = f"{slug}_swatch_{i}.png"
            mime = f"image/{'jpeg' if img['ext'] in ('jpg', 'jpeg') else 'png'}"
            try:
                swatch_urls.append(_upload_image(service, image_folder_id, name, img["bytes"], mime))
            except Exception as exc:
                _warn(f"{name} failed: {exc}")

    return ", ".join(main_urls), ", ".join(swatch_urls)


def _sheets_retry(fn, *args, **kwargs):
    """Call a gspread write and retry on transient rate-limit / server errors.

    The Sheets API caps writes per minute per user; batching plus this backoff
    keeps a big catalogue sync from tripping the 429 'Write requests per minute'
    quota.
    """
    import time as _time
    try:
        from gspread.exceptions import APIError
    except Exception:                       # gspread always present in this app
        APIError = Exception               # noqa: N806
    delay = 2.0
    last = None
    for attempt in range(6):
        try:
            return fn(*args, **kwargs)
        except APIError as exc:
            last = exc
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (429, 500, 503) and attempt < 5:
                _time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            raise
    if last:
        raise last


def fetch_and_sync_catalog_from_drive(progress=None, page_start=1, page_end=None,
                                      update_existing=False):
    """Scan the B2C_CATALOGUE Drive folder, parse every catalogue PDF, and
    upsert the products into the 'Product Catalog' sheet.

    Parameters
    ----------
    progress : optional callable(str) invoked with human-readable status lines
               (e.g. a Streamlit ``st.write`` / status callback).
    page_start : 1-based first page to read per catalogue (default 1).
    page_end   : 1-based last page to read (inclusive); None = to the end.
                 Pass a window (e.g. 11..20) so re-runs don't re-read/re-bill
                 the pages you already processed.
    update_existing : when False (default) products already in the sheet are
                 left untouched — only genuinely new products are appended.
                 Set True to also rewrite an existing product when its text
                 content actually changed.

    Returns (added_count, updated_count, status_message).
    """
    log = []

    def _say(msg):
        log.append(msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    # -- resolve config early so failures are clear --------------------------
    try:
        folder_id = _get_catalog_folder_id()
        image_folder_id = _get_image_folder_id()
        model = _get_model()
        client = _get_anthropic_client()
    except RuntimeError as exc:
        return 0, 0, f"❌ {exc}"

    try:
        import fitz  # noqa: F401  (PyMuPDF — imported for the clear error if missing)
    except Exception:
        return 0, 0, "❌ PyMuPDF (fitz) is required. Add 'PyMuPDF' to requirements.txt."

    # Report which identity uploads will run as, so a quota failure is easy to
    # diagnose. A bare service account cannot own files in My Drive (it will 403
    # storageQuotaExceeded) — it only works when the image folder is on a Shared
    # Drive, or when domain-wide delegation impersonates a real user, or when
    # OAuth user credentials are configured.
    if _get_drive_oauth_config():
        _say("🔑 Drive uploads: OAuth user credentials.")
    elif _get_impersonate_user():
        _say(f"🔑 Drive uploads: service account impersonating {_get_impersonate_user()}.")
    else:
        _say(
            "🔑 Drive uploads: service account (no impersonation). This only "
            "works if the image folder is on a Shared Drive; a plain service "
            "account cannot own files in My Drive and will 403 "
            "(storageQuotaExceeded). If uploads fail, set [drive] "
            "impersonate_user (domain-wide delegation) or move the folder to a "
            "Shared Drive. Text still syncs regardless."
        )

    try:
        pdf_files = _list_pdfs_in_folder(folder_id)
    except Exception as exc:
        return 0, 0, f"❌ Failed to list the B2C_CATALOGUE folder: {exc}"
    if not pdf_files:
        return 0, 0, (
            "⚠️ No PDF files found in the B2C_CATALOGUE folder. Check the folder "
            "ID and that the service account has Viewer access."
        )

    existing = _load_existing()
    existing_keys = {_norm_key(n): idx for idx, n in enumerate(existing["Product Name"])}

    drive_service = _build_drive_service()

    to_append = []          # list[list[str]]  new rows
    to_update = {}          # sheet_row_number(int) -> list[str] full row
    seen_this_run = set()   # products already handled this run (dedupe across pages)
    added = updated = skipped = backfilled = 0
    total_parsed = 0        # product blocks the model returned across all PDFs

    for file_info in pdf_files:
        fname = file_info["name"]
        hint = _filename_to_room_hint(fname)
        _say(f"📄 {fname} …")
        try:
            pdf_bytes = _download_pdf_bytes(file_info["id"])
        except Exception as exc:
            _say(f"   ⚠️ download failed: {exc}")
            continue

        try:
            products = _extract_products_from_pdf(
                client, model, pdf_bytes, hint, _say,
                page_start=page_start, page_end=page_end,
            )
        except Exception as exc:
            _say(f"   ⚠️ parse failed: {exc}")
            continue

        _say(f"   → {len(products)} product(s) parsed")
        total_parsed += len(products)

        for product in products:
            name = _clean_line(product.get("product_name"))
            if not name:
                continue
            key = _norm_key(name)
            if key in seen_this_run:
                continue
            seen_this_run.add(key)

            main_cat = _clean_line(product.get("main_category") or hint)
            sub_cat = _clean_line(product.get("sub_category"))
            features = _format_features(product.get("features"))
            measurements = _clean_line_multiline(product.get("measurements"))
            colour_material = _format_colour_material(
                product.get("colour"), product.get("material")
            )

            if key in existing_keys:
                # Product already in the sheet.
                row_idx = existing_keys[key]
                ex = existing.iloc[row_idx]
                # Preserve the hand-curated / previously-generated image URLs.
                main_urls = str(ex["Product Image URLs"]).strip()
                swatch_urls = str(ex["Swatch Image URLs"]).strip()

                # ── Backfill a MISSING product image ────────────────────────
                # If the row has no Product Image URL yet, extract the main
                # catalogue photo, upload it to Drive, and fill in the link.
                # This runs regardless of `update_existing`, never disturbs a
                # row that already has a product image, and touches ONLY the
                # image cell(s) (all text columns are preserved verbatim). If
                # the product has no extractable photo, the cell is left blank.
                did_backfill = False
                if not main_urls and (product.get("main_crop") or product.get("main_images")):
                    new_main, _ = _upload_product_images(
                        drive_service, image_folder_id, product,
                        want_main=True, want_swatch=False, say=_say,
                    )
                    if new_main:
                        main_urls = new_main
                        did_backfill = True

                # By default we never rewrite an existing product's TEXT — this
                # avoids churn (and wasted Sheets writes) from harmless LLM
                # wording drift. Only when the caller opts in do we refresh a
                # row's text, and only if it truly changed.
                changed = False
                if update_existing:
                    changed = (
                        _sig(ex["Main Category"]) != _sig(main_cat)
                        or _sig(ex["Sub Category"]) != _sig(sub_cat)
                        or _sig(ex["Features"]) != _sig(features)
                        or _sig(ex["Measurements"]) != _sig(measurements)
                        or _sig(ex["Colour & Material"]) != _sig(colour_material)
                    )

                if changed:
                    # Refreshing the text. If the row still has no swatches,
                    # generate them now too (main photo already handled above).
                    if not swatch_urls:
                        _, swatch_urls = _upload_product_images(
                            drive_service, image_folder_id, product,
                            want_main=False, want_swatch=True, say=_say,
                        )
                    to_update[row_idx + 2] = [
                        main_cat, sub_cat, name, features, measurements,
                        colour_material, main_urls, swatch_urls,
                    ]
                    updated += 1
                    _say(f"   ✏️  updated: {name}")
                elif did_backfill:
                    # Text unchanged (or refresh disabled) — write back only the
                    # newly filled image cell, preserving every other column.
                    to_update[row_idx + 2] = [
                        str(ex["Main Category"]),
                        str(ex["Sub Category"]),
                        str(ex["Product Name"]),
                        str(ex["Features"]),
                        str(ex["Measurements"]),
                        str(ex["Colour & Material"]),
                        main_urls,
                        swatch_urls,
                    ]
                    backfilled += 1
                    _say(f"   🖼️  backfilled product image: {name}")
                else:
                    skipped += 1
            else:
                main_urls, swatch_urls = _upload_product_images(
                    drive_service, image_folder_id, product, say=_say
                )
                to_append.append([
                    main_cat, sub_cat, name, features, measurements,
                    colour_material, main_urls, swatch_urls,
                ])
                added += 1
                _img_note = "" if main_urls else "  (no product image found)"
                _say(f"   ➕ new: {name}{_img_note}")

    # -- write back ----------------------------------------------------------
    if not to_append and not to_update:
        if total_parsed == 0:
            headline = (
                "⚠️ Catalogue scan finished but the AI returned 0 products from "
                "any page — nothing to write. Check the log below for the reason "
                "(refusal / unreadable JSON / wrong folder)."
            )
        else:
            headline = (
                f"✅ Catalogue scan complete — {total_parsed} product(s) read, all "
                f"already present and unchanged ({skipped} matched). Nothing to write."
            )
        return 0, 0, headline + "\n" + "\n".join(log)

    try:
        from services.sheets import get_sheet, get_df
        ws = get_sheet(CATALOG_SHEET_NAME)

        # Ensure the header row exists (fresh/empty sheet) — one call.
        if existing.empty:
            header = ws.row_values(1)
            if [h.strip() for h in header][: len(CATALOG_COLUMNS)] != CATALOG_COLUMNS:
                _sheets_retry(ws.update, "A1", [CATALOG_COLUMNS])

        # Batch ALL updated rows into a single Sheets write instead of one call
        # per row — this is what previously tripped the "Write requests per
        # minute" 429 quota.
        if to_update:
            batch = [
                {"range": f"A{row_number}:H{row_number}", "values": [values]}
                for row_number, values in sorted(to_update.items())
            ]
            _sheets_retry(ws.batch_update, batch, value_input_option="USER_ENTERED")

        # All new rows in a single append call.
        if to_append:
            _sheets_retry(ws.append_rows, to_append, value_input_option="USER_ENTERED")

        try:
            get_df.clear()  # bust the sheets cache so the page shows updates
        except Exception:
            pass
    except Exception as exc:
        return added, updated, (
            f"⚠️ Parsed products but writing to the sheet failed: {exc}\n"
            + "\n".join(log)
        )

    summary = (
        f"✅ Catalogue sync complete — {added} added, {updated} updated, "
        f"{backfilled} product image(s) backfilled, {skipped} unchanged."
    )
    return added, updated, summary + "\n" + "\n".join(log)


def _clean_line_multiline(s: str) -> str:
    """Collapse whitespace but keep intentional newlines (seater variants)."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in str(s or "").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _filename_to_room_hint(filename: str) -> str:
    name = filename[:-4] if filename.lower().endswith(".pdf") else filename
    name = re.sub(r"(?i)\b(cataloue|catalouge|catalogue|catalog|range|b2c)\b", "", name)
    name = re.sub(r"[_\-]+", " ", name)
    return re.sub(r"\s+", " ", name).strip() or "Furniture"


def _extract_products_from_pdf(client, model, pdf_bytes, hint, say,
                               page_start=1, page_end=None) -> list:
    """Render each page, ask Claude for the products, and attach the page's
    raster images to the right product. Returns a flat list of product dicts,
    each carrying main_images / swatch_images (raw bytes) + main_category.

    Only pages in the inclusive 1-based window ``page_start``..``page_end`` are
    sent to the model. Pass a moving window across runs so you never re-read
    (or re-bill) pages you already processed. ``page_end=None`` reads to the end.
    """
    import fitz

    all_products = []
    pages_with_products = 0
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        n_pages = doc.page_count
        start0 = max(0, int(page_start) - 1)                 # 0-based, inclusive
        end0 = n_pages if not page_end else min(n_pages, int(page_end))  # exclusive
        for pno in range(start0, end0):
            page = doc[pno]
            label = f"page {pno + 1}"
            try:
                png = _render_page_png(page)
            except Exception as exc:
                say(f"   ⚠️ {label}: render failed: {exc}")
                continue
            try:
                parsed = _parse_page(client, model, png, hint, say=say, label=label)
            except Exception as exc:
                say(f"   ⚠️ {label}: vision error: {exc}")
                continue

            products = parsed.get("products") or []
            if not products:
                continue

            pages_with_products += 1
            page_main = _clean_line(parsed.get("main_category") or hint)
            # Raster extraction (best-effort) still feeds swatch detection.
            images = _extract_page_images(doc, page)
            _assign_images(products, images)
            crops_ok = 0
            for p in products:
                p["main_category"] = page_main
                # PRIMARY product photo: crop the model's photo box straight out
                # of the rendered page. Robust to flattened/vector PDFs where
                # raster extraction finds nothing. Falls back to the raster
                # region box if photo_region is missing/degenerate.
                crop = _crop_region_png(page, p.get("photo_region") or {})
                if not crop:
                    crop = _crop_region_png(page, p.get("region") or {})
                if crop:
                    p["main_crop"] = {"bytes": crop, "ext": "png"}
                    crops_ok += 1
                all_products.append(p)
            say(
                f"   {label}: {len(products)} product(s), "
                f"{crops_ok} photo crop(s), {len(images)} raster image(s)"
            )

        say(
            f"   scanned pages {start0 + 1}-{end0} of {n_pages} → "
            f"{len(all_products)} product block(s) on {pages_with_products} page(s)"
        )
    return all_products
