import os
import io
import fitz  # PyMuPDF
import gspread
import pickle
import time
import json
import re
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# CONFIGURATION
# ==========================================
PDF_FILE_PATH = r"C:\Users\User\Desktop\AI_Business_Agent\b2c_catalog.pdf" 
CREDENTIALS_FILE = "../../config/credentials.json"
CLIENT_SECRET_FILE = "../../config/client_secret.json" 
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
CATALOG_SHEET_NAME = "Product Catalog"
DRIVE_IMAGE_FOLDER_ID = "1PGdL47AQXliSpX9i8MIQz3oeAknxJM8I" 

# --- NEW: ADD YOUR GEMINI API KEY HERE ---
GEMINI_API_KEY = "AIzaSyAihFdaJwp4FaMF1wfgKXhXp_MUMmzAowA"
genai.configure(api_key=GEMINI_API_KEY)
# Using Gemini 2.5 Flash - extremely fast and cheap/free for this type of text extraction
ai_model = genai.GenerativeModel('gemini-2.5-flash')

def authenticate_google_services():
    sheets_creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheets_client = gspread.authorize(sheets_creds)

    drive_creds = None
    token_path = "../../config/token.pickle"
    
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            drive_creds = pickle.load(token)
            
    if not drive_creds or not drive_creds.valid:
        if drive_creds and drive_creds.expired and drive_creds.refresh_token:
            drive_creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, scopes=["https://www.googleapis.com/auth/drive"])
            drive_creds = flow.run_local_server(port=0)
        with open(token_path, 'wb') as token:
            pickle.dump(drive_creds, token)

    drive_service = build('drive', 'v3', credentials=drive_creds)
    return sheets_client, drive_service

def upload_image_to_drive(drive_service, image_bytes, filename):
    file_metadata = {'name': filename, 'parents': [DRIVE_IMAGE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/png', resumable=True)
    try:
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return f"https://drive.google.com/thumbnail?id={file.get('id')}&sz=w1000"
    except Exception as e:
        print(f"      [!] Failed to upload {filename}: {e}")
        return ""

def ask_ai_to_parse_text(raw_text):
    """Sends the messy PDF text to Gemini AI to intelligently structure it."""
    prompt = f"""
    You are a data extraction assistant. I am giving you raw, messy text scraped from a furniture catalog PDF. 
    Analyze the text and extract the details. 
    
    Return ONLY a valid JSON object with the following keys. Do not use markdown blocks, just return the JSON:
    {{
      "main_category": "The broad category (e.g., 'Living Room', 'Bedroom'). If none, return 'Unknown'.",
      "sub_category": "The specific category (e.g., 'Sofa', 'Bed'). If none, return 'Unknown'.",
      "product_name": "The actual name of the furniture product.",
      "features": "A string of the product features, bulleted. Put '✨ ' before each distinct feature and separate them with a newline.",
      "measurements": "A pipe-separated string of the measurements so they can be read as a table. (e.g., 'Width: 100cm | Depth: 90cm | Height: 80cm').",
      "colour_material": "The colors and materials mentioned. Separate them with a newline if there are multiple."
    }}
    
    Raw Text to Analyze:
    {raw_text}
    """
    try:
        response = ai_model.generate_content(prompt)
        text_response = response.text
        
        # Clean up the response in case the AI wraps it in markdown (```json ... ```)
        json_match = re.search(r'\{.*\}', text_response, re.DOTALL)
        if json_match:
            clean_json = json_match.group(0)
            return json.loads(clean_json)
        return None
    except Exception as e:
        print(f"      [!] AI Parsing Error: {e}")
        return None

def process_page_half(page, min_x, max_x, drive_service, doc):
    page_dict = page.get_text("dict")
    half_spans = []
    
    # 1. Grab all text elements strictly inside this half of the page
    for block in page_dict["blocks"]:
        if block['type'] == 0:  
            for line in block["lines"]:
                for span in line["spans"]:
                    span_center_x = (span["bbox"][0] + span["bbox"][2]) / 2
                    if min_x <= span_center_x < max_x:
                        text = span["text"].strip()
                        if text and "Download PDF" not in text and "interio by godrej" not in text.lower():
                            # We keep the y0 coordinate just to find the title height for images later
                            half_spans.append({"text": text, "y0": span["bbox"][1], "size": span["size"]})

    if not half_spans: return None

    # Determine Title Height (so we can filter out top-page logos later)
    page_height = page.rect.height
    top_half_spans = [s for s in half_spans if s["y0"] < (page_height / 3)]
    title_y0 = 0
    if top_half_spans:
        max_size = max(s["size"] for s in top_half_spans)
        title_spans = [s for s in top_half_spans if abs(s["size"] - max_size) < 1.0]
        if title_spans: title_y0 = min(s["y0"] for s in title_spans) 

    # 2. Mash all the text together and give it to the AI
    raw_text_blob = "\n".join([s["text"] for s in half_spans])
    
    if len(raw_text_blob) < 20: 
        return None # Page is empty

    # Call the Gemini AI
    ai_data = ask_ai_to_parse_text(raw_text_blob)
    
    if not ai_data or not ai_data.get("product_name") or "Unknown" in ai_data.get("product_name", "Unknown"):
        return None

    main_category = ai_data.get("main_category", "Unknown")
    sub_category = ai_data.get("sub_category", "Unknown")
    product_name = ai_data.get("product_name", "Unknown Product")
    specs_str = ai_data.get("features", "")
    measurements_str = ai_data.get("measurements", "")
    colors_str = ai_data.get("colour_material", "")

    # 3. Grab Images & Sort by Size (Product vs Swatch)
    product_images = []
    swatch_images = []
    
    for img_info in page.get_image_info(xrefs=True):
        img_bbox = img_info["bbox"]
        img_center_x = (img_bbox[0] + img_bbox[2]) / 2
        
        if min_x <= img_center_x < max_x:
            if img_bbox[1] < (title_y0 - 20): # Ignore logos at the very top
                continue
                
            xref = img_info.get("xref")
            if not xref: continue
            
            try:
                base_image = doc.extract_image(xref)
                w, h = base_image["width"], base_image["height"]
                img_bytes = base_image["image"]
                
                safe_name = "".join([c for c in product_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                
                # LARGE IMAGES -> Product Gallery
                if w > 300 and h > 300 and len(img_bytes) > 20000:
                    print(f"      Uploading Product Image ({w}x{h}) for {product_name}...")
                    url = upload_image_to_drive(drive_service, img_bytes, f"{safe_name.replace(' ', '_')}_main_{xref}.png")
                    if url: product_images.append(url)
                
                # SMALL IMAGES -> Swatches / Materials
                elif w > 40 and h > 40 and len(img_bytes) > 2000:
                    print(f"      Uploading Swatch Image ({w}x{h}) for {product_name}...")
                    url = upload_image_to_drive(drive_service, img_bytes, f"{safe_name.replace(' ', '_')}_swatch_{xref}.png")
                    if url: swatch_images.append(url)
                    
            except Exception:
                pass

    return [
        main_category, sub_category, product_name, 
        specs_str, measurements_str, colors_str, 
        ",".join(product_images), ",".join(swatch_images)
    ]

def live_process_and_upload(sheets_client, drive_service):
    print("\n=========================================")
    print("PREPARING GOOGLE SHEET...")
    sh = sheets_client.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(CATALOG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=CATALOG_SHEET_NAME, rows=1000, cols=10)

    ws.clear()
    ws.append_row([
        "Main Category", "Sub Category", "Product Name", 
        "Specifications", "Measurements", "Colour & Material", 
        "Product Image URLs", "Swatch Image URLs"
    ])
    print("✅ Sheet is ready for Live Sync!")
    print("=========================================\n")

    print(f"Opening PDF: {PDF_FILE_PATH}...")
    try:
        doc = fitz.open(PDF_FILE_PATH)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return

    try:
        for page_num in range(8, len(doc)):
            print(f"\nProcessing Page {page_num + 1}/{len(doc)}...")
            page = doc.load_page(page_num)
            
            page_width = page.rect.width
            mid_x = page_width / 2
            
            # Process Left Side
            left_product = process_page_half(page, 0, mid_x, drive_service, doc)
            if left_product:
                ws.append_row(left_product)
                print(f"   ✅ Saved Left Product: '{left_product[2]}'")
                
            # Process Right Side
            right_product = process_page_half(page, mid_x, page_width, drive_service, doc)
            if right_product:
                ws.append_row(right_product)
                print(f"   ✅ Saved Right Product: '{right_product[2]}'")
            
            # API Safety Sleep - Gives the Google Sheets & Gemini APIs time to breathe
            time.sleep(4) 
            
    except KeyboardInterrupt:
        print("\n\n[!] Script stopped manually. Data saved.")

def main():
    print("Starting AI Catalog Synchronization...")
    sheets_client, drive_service = authenticate_google_services()
    live_process_and_upload(sheets_client, drive_service)
    print("\n🎉 Synchronization Complete!")

if __name__ == "__main__":
    main()