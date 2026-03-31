import os
import io
import fitz  # PyMuPDF
import gspread
import pickle
import time
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

def authenticate_google_services():
    sheets_creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE, 
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
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
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, 
                scopes=["https://www.googleapis.com/auth/drive"]
            )
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
        return f"https://drive.google.com/uc?id={file.get('id')}"
    except Exception as e:
        print(f"      [!] Failed to upload {filename}: {e}")
        return ""

def extract_intelligent_layout(page):
    page_dict = page.get_text("dict")
    spans = []
    
    for block in page_dict["blocks"]:
        if block['type'] == 0:  
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text and "Download PDF" not in text and "interio by godrej" not in text.lower():
                        spans.append({
                            "text": text,
                            "size": span["size"],
                            "y0": span["bbox"][1], 
                            "x0": span["bbox"][0]  
                        })

    if not spans:
        return None, None, None, None

    page_height = page.rect.height
    top_half_spans = [s for s in spans if s["y0"] < (page_height / 2)]
    
    if not top_half_spans:
        return None, None, None, None
        
    max_size = max(s["size"] for s in top_half_spans)
    
    title_spans = [s for s in top_half_spans if abs(s["size"] - max_size) < 1.0]
    title_spans.sort(key=lambda s: s["x0"]) 
    product_name = " ".join([s["text"] for s in title_spans])
    title_y0 = min(s["y0"] for s in title_spans) 

    above_title = [s for s in spans if s["y0"] < (title_y0 - 2)]
    above_title.sort(key=lambda s: s["x0"]) 
    
    main_category = above_title[0]["text"] if len(above_title) >= 1 else "Unknown"
    sub_category = above_title[1]["text"] if len(above_title) >= 2 else "Unknown"

    features = []
    capture = False
    stop_words = ["Measurements", "Colour & Material", "Proportion", "Details", "In the set", "Fabric"]
    
    below_title = [s for s in spans if s["y0"] >= title_y0 and s not in title_spans]
    below_title.sort(key=lambda s: (s["y0"], s["x0"]))
    
    for s in below_title:
        txt = s["text"]
        
        if any(stop.lower() in txt.lower() for stop in stop_words):
            capture = False
            
        if capture:
            clean_txt = txt.lstrip("•*- ").strip()
            if clean_txt and s["size"] > 7.0: 
                features.append(clean_txt)
                
        if txt.lower() == "features":
            capture = True

    specs = " | ".join(features)
    return main_category, sub_category, product_name, specs

def live_process_and_upload(sheets_client, drive_service):
    # 1. Prepare the Google Sheet First
    print("\n=========================================")
    print("PREPARING GOOGLE SHEET...")
    sh = sheets_client.open_by_key(SPREADSHEET_ID)
    
    try:
        ws = sh.worksheet(CATALOG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=CATALOG_SHEET_NAME, rows=1000, cols=10)

    print("Clearing old data and setting up headers...")
    ws.clear()
    ws.append_row(["Main Category", "Sub Category", "Product Name", "Specifications", "Image URLs"])
    print("✅ Sheet is ready for Live Sync!")
    print("=========================================\n")

    # 2. Open PDF
    print(f"Opening PDF: {PDF_FILE_PATH}...")
    try:
        doc = fitz.open(PDF_FILE_PATH)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return

    # 3. Process Pages and Upload Instantly
    try:
        for page_num in range(8, len(doc)):
            print(f"\nProcessing Page {page_num + 1}/{len(doc)}...")
            page = doc.load_page(page_num)
            
            main_cat, sub_cat, product_name, specs = extract_intelligent_layout(page)
            
            if not product_name or "Unknown" in main_cat:
                print("   -> Skipping: Does not match standard product layout.")
                continue 
                
            print(f"   -> Found Product: {product_name} ({main_cat} > {sub_cat})")
                
            image_urls = []
            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                image_info = doc.extract_image(xref)
                
                if image_info["width"] > 300 and image_info["height"] > 300 and len(image_info["image"]) > 25000:
                    safe_name = "".join([c for c in product_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                    filename = f"{safe_name.replace(' ', '_')}_img{img_index}.png"
                    
                    print(f"      Uploading image {img_index + 1}...")
                    url = upload_image_to_drive(drive_service, image_info["image"], filename)
                    if url:
                        image_urls.append(url)
                        
            # Format row and append to Google Sheet instantly
            row_data = [main_cat, sub_cat, product_name, specs, ",".join(image_urls)]
            ws.append_row(row_data)
            print(f"   ✅ Saved '{product_name}' directly to Google Sheet!")
            
            # API Quota Safety Sleep
            time.sleep(1) 
            
    except KeyboardInterrupt:
        print("\n\n[!] Script stopped manually by user. All products processed so far have been saved.")
    except Exception as e:
        print(f"\n\n[!] An error occurred: {e}")
        print("All products processed up until this error have been safely saved to the sheet.")

def main():
    print("Starting Catalog Synchronization...")
    sheets_client, drive_service = authenticate_google_services()
    live_process_and_upload(sheets_client, drive_service)
    print("\n🎉 Synchronization Complete!")

if __name__ == "__main__":
    main()