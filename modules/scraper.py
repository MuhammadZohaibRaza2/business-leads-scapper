from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from modules.helpers import *
from modules.const.settings import SETTINGS
from modules.const.colors import fore

import time
import json
import re
import urllib.parse
import xlsxwriter

JS_EXTRACT_ALL_CARDS = r'''
const cards = document.querySelectorAll('div.Nv2PK');
const results = [];
cards.forEach(card => {
    const text = card.innerText || '';
    const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    if (!lines.length) return;
    
    // Title/Name
    let name = lines[0];
    const nameEl = card.querySelector('div.qBF1Pd, div.fontHeadlineSmall');
    if (nameEl && nameEl.innerText.trim()) {
        name = nameEl.innerText.trim();
    }
    
    // Google Maps Link
    let mapsLink = '';
    const linkEl = card.querySelector('a.hfpxzc');
    if (linkEl && linkEl.href) {
        mapsLink = linkEl.href;
    }
    
    // Website Link
    let website = '';
    const webEl = card.querySelector('a[data-value="Website"], a[aria-label*="Website"], a[aria-label*="website"]');
    if (webEl && webEl.href) {
        website = webEl.href;
    }
    
    // Phone Number Extraction
    let phone = '';
    const phoneEl = card.querySelector('span.UsdlK, [data-phone-number], a[href^="tel:"]');
    if (phoneEl) {
        phone = phoneEl.innerText.trim() || phoneEl.getAttribute('href').replace('tel:', '').trim();
    }
    
    if (!phone) {
        for (let line of lines) {
            const parts = line.split(/[·•]/);
            for (let part of parts) {
                part = part.trim();
                const digits = part.replace(/\D/g, '');
                if (digits.length >= 6 && digits.length <= 15 && !part.includes('★') && !part.toLowerCase().includes('review') && !part.toLowerCase().includes('min') && !part.toLowerCase().includes('km') && !part.toLowerCase().includes('mi')) {
                    if (/^(\+?\d{1,4}[\s.-]?)?\(?\d{1,4}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,5}([\s.-]?\d{1,4})?$/.test(part)) {
                        phone = part;
                        break;
                    }
                }
            }
            if (phone) break;
        }
    }
    
    if (!phone) {
        const matches = text.match(/(\+\d{1,4}[\s.-]\d{2,4}[\s.-]\d{2,5}([\s.-]\d{1,5})?|\+?\d{1,4}[\s.-]\d{3}[\s.-]\d{3,4}|0\d{1,3}[\s.-]\d{3,4}[\s.-]?\d{3,4}|\b800[\s.-]\d{3,6}\b|\(\d{3}\)[\s.-]?\d{3}[\s.-]?\d{4}|\+\d{10,14})/);
        if (matches) {
            phone = matches[0].trim();
        }
    }
    
    // Address Extraction
    let address = '';
    for (let line of lines) {
        if (line.includes('·') && !line.includes('Open') && !line.includes('Closed') && line !== lines[0] && !line.includes(name)) {
            const parts = line.split('·').map(p => p.trim()).filter(Boolean);
            for (let i = parts.length - 1; i >= 0; i--) {
                const p = parts[i].replace(/[\ue000-\uf8ff]/g, '').trim();
                if (p.length > 2 && !p.includes('★') && !/^\d+\.?\d*\s*\([\d,]+\)$/.test(p) && p !== phone && !p.toLowerCase().includes('review')) {
                    address = p;
                    break;
                }
            }
        }
    }
    if (!address) {
        for (let line of lines) {
            if (line !== name && !line.includes('Open') && !line.includes('Closed') && !line.includes('Directions') && !line.includes('Website') && !line.includes('★') && !line.includes(phone) && line.length > 3) {
                const clean = line.replace(/[\ue000-\uf8ff]/g, '').trim();
                if (clean && clean !== name && !/^\d+\.?\d*\s*\([\d,]+\)$/.test(clean) && !clean.includes('Gas station') && !clean.includes('store') && !clean.includes('restaurant') && !clean.includes('$$')) {
                    address = clean;
                    break;
                }
            }
        }
    }
    
    // If address is still empty or looks like plus code / code, attempt extracting location from name
    if (!address || address.length <= 5 || /[A-Z0-9]{4}\+[A-Z0-9]{2}/i.test(address)) {
        const titleParts = name.split(/[|\-–—]/).map(s => s.trim()).filter(Boolean);
        if (titleParts.length > 1) {
            let cand = titleParts[titleParts.length - 1];
            cand = cand.replace(/\s*\(\d+\)\s*/g, '').trim();
            if (cand && cand.length > 2 && !/^\d+$/.test(cand)) {
                address = cand;
            }
        }
    }
    
    results.push({
        name: name,
        phone: phone,
        address: address,
        has_website: website ? 'Yes' : 'No',
        website: website,
        maps_link: mapsLink,
        email: ''
    });
});
return results;
'''

def scrape(args):
    '''
    Scrapes the results and puts them in the excel spreadsheet.

    Parameters:
            args (object): CLI arguments
    '''
    if args.pages is not None:
        SETTINGS["PAGE_DEPTH"] = args.pages
    SETTINGS["BASE_QUERY"] = args.query
    SETTINGS["PLACES"] = [p.strip() for p in args.places.split(',') if p.strip()]

    # Chrome Options for reliable headless scraping
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--lang=en-US')
    options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    # Initialize workbook / worksheet
    workbook = xlsxwriter.Workbook('ScrapedData_GoogleMaps.xlsx')
    worksheet = workbook.add_worksheet()

    # Headers and data template
    data_template = {
        "name": "",
        "phone": "",
        "address": "",
        "has_website": "",
        "website": "",
        "maps_link": "",
        "email": ""
    }
    headers = generate_headers(args, data_template.copy())
    print_table_headers(worksheet, headers)

    row = 1
    addresses_scraped = set()
    names_scraped = set()

    start_time = time.time()

    for place in SETTINGS["PLACES"]:
        query = f"{SETTINGS['BASE_QUERY']} {place}".strip()
        print(f"{fore.GREEN}Moving on to search query: {query}{fore.RESET}")

        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
        driver.get(search_url)

        time.sleep(2.5)

        # Handle consent popup if present
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                if btn.text in ['Accept all', 'Agree', 'I agree']:
                    btn.click()
                    time.sleep(1)
                    break
        except Exception:
            pass

        # Try to locate feed
        feed = None
        try:
            feed = wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]')))
        except Exception:
            try:
                feed = driver.find_element(By.XPATH, '//div[contains(@aria-label, "Results for")]')
            except Exception:
                pass

        # Fast Scrolling
        scroll_iterations = max(1, SETTINGS["PAGE_DEPTH"] * 3)
        if feed:
            for s in range(scroll_iterations):
                driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', feed)
                time.sleep(0.7)

        # Batch extraction via JS
        cards = driver.execute_script(JS_EXTRACT_ALL_CARDS) or []
        print(f"{fore.GREEN}Found {len(cards)} places for {place}{fore.RESET}")

        # Deep detail enrichment for places where contact details are hidden (e.g. hotels)
        missing_details = [
            item for item in cards if not item.get("phone") or not item.get("website")
        ]
        if missing_details:
            print(f"{fore.GREEN}Fetching deep contact details for {len(missing_details)} places...{fore.RESET}")
            for item in missing_details:
                maps_url = item.get("maps_link")
                if not maps_url:
                    continue
                try:
                    driver.get(maps_url)
                    time.sleep(1.0)
                    detail_res = driver.execute_script(r'''
                    const res = {};
                    const phoneEl = document.querySelector("button[data-item-id^='phone:'], button[aria-label*='Phone:'], a[href^='tel:'], [data-tooltip*='phone' i]");
                    if (phoneEl) {
                        const raw = phoneEl.getAttribute('aria-label') || phoneEl.innerText || phoneEl.getAttribute('data-item-id') || '';
                        res.phone = raw.replace(/^Phone:\s*/i, '').replace(/^phone:tel:/i, '').trim();
                    }
                    const webEl = document.querySelector("a[data-item-id='authority'], a[aria-label*='Website:' i], a[aria-label='Open website' i], [data-tooltip*='website' i]");
                    if (webEl) {
                        res.website = webEl.href;
                    }
                    const addrEl = document.querySelector("button[data-item-id='address'], button[aria-label*='Address:' i]");
                    if (addrEl) {
                        const raw = addrEl.getAttribute('aria-label') || addrEl.innerText || '';
                        res.address = raw.replace(/^Address:\s*/i, '').trim();
                    }
                    return res;
                    ''')
                    if detail_res.get("phone") and not item.get("phone"):
                        item["phone"] = detail_res["phone"]
                    if detail_res.get("website") and not item.get("website"):
                        item["website"] = detail_res["website"]
                        item["has_website"] = "Yes"
                    if detail_res.get("address") and (not item.get("address") or len(item.get("address", "")) < 10):
                        item["address"] = detail_res["address"]
                except Exception:
                    pass

        # Parallel address resolution
        incomplete_batch = [
            itm for itm in cards if is_incomplete_address(itm.get("address", ""))
        ]
        if incomplete_batch:
            from concurrent.futures import ThreadPoolExecutor
            def enrich_addr(itm):
                resolved = resolve_full_address(
                    itm.get("maps_link", ""),
                    itm.get("address", ""),
                    itm.get("name", ""),
                    place
                )
                if resolved:
                    itm["address"] = resolved

            with ThreadPoolExecutor(max_workers=8) as addr_exec:
                list(addr_exec.map(enrich_addr, incomplete_batch))

        for current_data in cards:
            name = current_data.get("name", "")
            address = current_data.get("address", "")
            website = current_data.get("website", "")
            phone = current_data.get("phone", "")

            scraped = address in addresses_scraped if address else (name in names_scraped)

            if scraped and args.skip_duplicate_addresses:
                print(f"{fore.WARNING}Skipping {name} as duplicate{fore.RESET}")
                continue

            if address:
                addresses_scraped.add(address)
            names_scraped.add(name)

            print(f"{fore.GREEN}Scraped{fore.RESET}: {name} | Phone: {phone or 'N/A'} | Web: {current_data.get('has_website')}")

            if args.scrape_website and website:
                try:
                    web_url, emails = get_website_data(website)
                    if emails:
                        current_data["email"] = ', '.join(emails)
                except Exception:
                    pass
            elif not args.scrape_website:
                current_data.pop("email", None)

            if args.verbose:
                print(json.dumps(current_data, indent=1))

            write_data_row(worksheet, current_data, row)
            row += 1

        print("-------------------")

    workbook.close()
    driver.quit()

    end_time = time.time()
    elapsed = round(end_time - start_time, 2)
    print(f"{fore.GREEN}Done! Scraped {row - 1} records into ScrapedData_GoogleMaps.xlsx in {elapsed}s{fore.RESET}")