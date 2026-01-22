import requests
import fitz  # PyMuPDF
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= CONFIG =================

BASE_URL = "https://pxwell.co/today-result/"

# Sequence of draw times as they appear on the website
TIME_ORDER = [
    ("12.30", "mor"),
    ("16.30", "day"),
    ("20.30", "evn"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

# ---- APIs ----
API_BASE = "https://supervillain.pythonanywhere.com/api/singapore/"
API_LAST_1 = f"{API_BASE}last-digit/"
API_LAST_2 = f"{API_BASE}last-two-digit/"
API_LAST_3 = f"{API_BASE}last-three-digit/"
API_FAX = "https://supervillain.pythonanywhere.com/api/fax/"
API_GET_STATE = API_LAST_3  # Endpoint to check existing data

# ================= HELPERS =================

def get_now_ist():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def create_session():
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)
    return session

# ================= API & DB LOGIC =================

def api_get_today_state(session, today):
    try:
        r = session.get(API_GET_STATE, params={"date": today}, timeout=10)
        if r.status_code == 404:
            return {"date": today, "mor": "-", "day": "-", "evn": "-"}
        r.raise_for_status()
        
        data = r.json()
        if isinstance(data, list):
            for entry in data:
                if entry.get("date") == today:
                    print(f"[DEBUG] Found today's record: {entry}")
                    return entry
            return {"date": today, "mor": "-", "day": "-", "evn": "-"}
        return data 
    except Exception as e:
        print(f"[WARN] DB Fetch error: {e}")
        return {"date": today, "mor": "-", "day": "-", "evn": "-"}

def slots_to_crawl(db, current_slot):
    result = []
    for _, slot in TIME_ORDER:
        if db.get(slot) == "-":
            result.append(slot)
        if slot == current_slot:
            break
    return result

# ================= EXTRACTION & POSTING =================

def extract_digits_from_pdf_bytes(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in doc)

    # Looking for the 1st Prize number
    match = re.search(r"1st\s*Prize.*?(\d{4,})", text, re.IGNORECASE)
    if not match:
        raise ValueError("1st Prize number not found in PDF")

    num = match.group(1)
    return {
        "last_1": num[-1],
        "last_2": num[-2:],
        "last_3": num[-3:],
    }

def post_digit(api, today, slot, value):
    # Sends data to update specific slot while keeping others as "-"
    payload = {"date": today, "mor": "-", "day": "-", "evn": "-"}
    payload[slot] = value
    r = requests.post(api, json=payload, timeout=10)
    r.raise_for_status()

def post_image(pdf_bytes, today, slot):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("jpeg")

    files = {"image": ("result.jpg", img_bytes, "image/jpeg")}
    data = {"type": "singapore", "date": today, "time": slot}

    r = requests.post(API_FAX, files=files, data=data, timeout=15)
    r.raise_for_status()

# ================= CORE PROCESS =================

def crawl_and_process(current_slot):
    session = create_session()
    ist_now = get_now_ist()
    today = ist_now.strftime("%Y-%m-%d")

    # 1. Check current DB state
    db = api_get_today_state(session, today)

    # 2. Determine what needs crawling
    needed_slots = slots_to_crawl(db, current_slot)
    
    if not needed_slots:
        print(f"✅ Data for {today} {current_slot} is already up to date.")
        return

    print(f"[INFO] Need to crawl: {needed_slots}")

    # 3. Get PDF links from the website
    try:
        page = session.get(BASE_URL, timeout=15)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        # Finds all PDF buttons in order
        pdf_links = [
            a["href"]
            for a in soup.select("a.elementor-button-link[href$='.pdf']")
        ]
    except Exception as e:
        print(f"❌ Failed to fetch website: {e}")
        return

    # 4. Corrected Loop Logic: Match slot to PDF by index
    for i, (label, slot) in enumerate(TIME_ORDER):
        # Only process if this slot is in our 'needed' list
        if slot not in needed_slots:
            continue
            
        # Check if the PDF button actually exists on the page for this slot
        if i >= len(pdf_links):
            print(f"⏳ PDF for {slot} ({label}) not uploaded to website yet.")
            continue

        pdf_url = pdf_links[i]
        
        try:
            print(f"[CRAWL] Fetching {slot} PDF: {pdf_url}")
            pdf = session.get(pdf_url, timeout=20)
            pdf.raise_for_status()

            digits = extract_digits_from_pdf_bytes(pdf.content)

            # Update all 3 digit APIs
            post_digit(API_LAST_1, today, slot, digits["last_1"])
            post_digit(API_LAST_2, today, slot, digits["last_2"])
            post_digit(API_LAST_3, today, slot, digits["last_3"])

            # Upload JPEG result to Fax API
            post_image(pdf.content, today, slot)
            print(f"✔️ {slot.upper()} processed successfully.")
            
        except Exception as e:
            print(f"❌ Error processing {slot}: {e}")

# ================= ENTRY =================

def detect_time_slot():
    now = get_now_ist()
    current_total_minutes = (now.hour * 60) + now.minute
    
    # 12:30 IST = 750 mins | 16:30 IST = 990 mins | 20:30 IST = 1230 mins
    if current_total_minutes < 750:
        return None 
    elif current_total_minutes < 990:
        return "mor"
    elif current_total_minutes < 1230:
        return "day"
    else:
        return "evn"

if __name__ == "__main__":
    slot = detect_time_slot()
    if slot is None:
        print("⏳ Too early. Morning results available after 12:30 PM IST.")
    else:
        print(f"🚀 System active. Current window: {slot}")
        crawl_and_process(slot)