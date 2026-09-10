import requests
import re
from bs4 import BeautifulSoup

def generate_headers(args, example_dict):
    '''
    Generates headers from the data dictionary by capitalizing its keys.

    Parameters:
            args (object): Object containing CLI arguments
            example_dict (dict): Data dictionary with keys

    Returns:
            list (list): List of capitalized/formatted strings representing headers
    '''
    if not args.scrape_website and "email" in example_dict:
        del example_dict["email"]

    header_names = {
        "name": "Name",
        "phone": "Phone",
        "address": "Address",
        "has_website": "Has Website",
        "website": "Website",
        "maps_link": "Google Maps Link",
        "email": "Email"
    }

    return [header_names.get(k, k.replace("_", " ").title()) for k in example_dict.keys()]

def print_table_headers(worksheet, headers):
    '''
    Writes headers to the worksheet.

    Parameters:
            worksheet (worksheet object): Worksheet where headsers should be written
            headers (list): List of headers to vrite
    '''
    col = 0
    for header in headers:
        worksheet.write(0, col, header)
        col += 1

def get_website_data(url):
    '''
    Returns the website URL and email addresses found on the target website.
    Uses strict 3s timeouts to prevent slowing down scraping.
    '''
    if not url:
        return None, []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, allow_redirects=True, timeout=3.5, headers=headers)
        if response.status_code >= 400:
            return url, []

        content = response.text
        emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', content)
        clean_emails = []
        for em in set(emails):
            if not any(em.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.js', '.css', '.woff']):
                clean_emails.append(em)

        return response.url or url, clean_emails
    except Exception:
        return url, []

GENERIC_CATEGORIES = {
    "gas station", "service station", "petrol station", "store", "restaurant", "cafe", "hotel", "bank",
    "hospital", "clinic", "pharmacy", "gym", "school", "university", "dentist",
    "doctor", "lawyer", "agency", "bakery", "bar", "supermarket", "grocery store",
    "car repair", "car dealer", "mechanic", "shopping mall", "park", "convenience store"
}

def is_incomplete_address(addr):
    '''Checks if address is missing, a plus code, or an incomplete short code or category name.'''
    if not addr or addr.strip().upper() in ["N/A", "NONE", "NULL", ""]:
        return True
    addr = addr.strip()
    if addr.lower() in GENERIC_CATEGORIES:
        return True
    if re.search(r'\b[2-9CFGHJMPQRVWX]{4,8}\+[2-9CFGHJMPQRVWX]{2,3}\b', addr, re.IGNORECASE):
        return True
    if len(addr) <= 5 or re.match(r'^[A-Z]\d{1,3}$', addr):
        return True
    return False

def resolve_full_address(maps_link, current_address="", business_name="", default_place=""):
    '''
    Enriches missing or incomplete addresses (like plus codes or short codes)
    by extracting precise coordinates from the Google Maps link and reverse geocoding.
    '''
    if not is_incomplete_address(current_address):
        return current_address.strip()

    # Extract location name from business title if delimited by | or - (e.g. ADNOC | Al Barsha (528))
    candidate_name_loc = ""
    if business_name:
        parts = re.split(r'[|\-–—]', business_name)
        if len(parts) > 1:
            cand = parts[-1].strip()
            cand = re.sub(r'\s*\(\d+\)\s*', '', cand).strip()
            if cand and len(cand) > 2 and not cand.isdigit():
                candidate_name_loc = cand

    # Try reverse geocoding from maps_link coordinates
    if maps_link:
        lat_match = re.search(r"!3d(-?\d+\.\d+)", maps_link)
        lon_match = re.search(r"!4d(-?\d+\.\d+)", maps_link)
        if lat_match and lon_match:
            lat, lon = lat_match.group(1), lon_match.group(1)
            # Try OpenStreetMap Nominatim with English locale
            try:
                geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=en"
                headers = {"User-Agent": "BusinessLeadsScraper/2.0 (leadgen@app.io)"}
                res = requests.get(geo_url, headers=headers, timeout=2.5)
                if res.status_code == 200:
                    display = res.json().get("display_name", "")
                    if display:
                        return display
            except Exception:
                pass

            # Fast fallback to BigDataCloud
            try:
                res = requests.get(
                    f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en",
                    timeout=2.0
                )
                if res.status_code == 200:
                    d = res.json()
                    parts = [d.get("locality"), d.get("city"), d.get("principalSubdivision"), d.get("countryName")]
                    seen = set()
                    cleaned = []
                    for p in parts:
                        if p and p not in seen:
                            cleaned.append(p)
                            seen.add(p)
                    if cleaned:
                        return ", ".join(cleaned)
            except Exception:
                pass

    if candidate_name_loc:
        if default_place and default_place.lower() not in candidate_name_loc.lower():
            return f"{candidate_name_loc}, {default_place}"
        return candidate_name_loc

    if current_address and current_address.upper() != "N/A":
        if default_place and default_place.lower() not in current_address.lower():
            return f"{current_address}, {default_place}"
        return current_address

    return default_place or "N/A"