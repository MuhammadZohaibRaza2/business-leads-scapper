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
    
    let name = lines[0];
    const nameEl = card.querySelector('div.qBF1Pd');
    if (nameEl && nameEl.innerText.trim()) {
        name = nameEl.innerText.trim();
    }
    
    let mapsLink = '';
    const linkEl = card.querySelector('a.hfpxzc');
    if (linkEl && linkEl.href) {
        mapsLink = linkEl.href;
    }
    
    let website = '';
    const webEl = card.querySelector('a[data-value="Website"], a[aria-label*="Website"]');
    if (webEl && webEl.href) {
        website = webEl.href;
    }
    
    let phone = '';
    const phoneMatches = text.match(/(\+?92[\s\d-]{8,}|\(0\d{2,3}\)[\s\d-]+|03\d{2}[\s\d-]{7,}|\+?\d{1,3}[\s-]\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{3,4})/);
    if (phoneMatches) {
        phone = phoneMatches[0].trim();
    }
    
    let address = '';
    for (let line of lines) {
        if (line.includes('·') && !line.includes('Open') && !line.includes('Closed') && line !== lines[0]) {
            const parts = line.split('·').map(p => p.trim()).filter(Boolean);
            if (parts.length > 1) {
                address = parts[parts.length - 1];
            }
        }
    }
    if (!address && lines.length > 2) {
        for (let i = 1; i < lines.length; i++) {
            const c = lines[i];
            if (!c.includes('Open') && !c.includes('Closed') && !c.includes('Directions') && !c.includes('Website') && !c.includes('★') && !/^\d\.\d$/.test(c)) {
                address = c;
                break;
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