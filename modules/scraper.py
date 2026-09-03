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

    # Created driver and wait
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

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

    # Start from second row in xlsx, as first one is reserved for headers
    row = 1

    # Remember scraped addresses to skip duplicates
    addresses_scraped = {}
    scraped_names = set()

    start_time = time.time()

    for place in SETTINGS["PLACES"]:
        query = f"{SETTINGS['BASE_QUERY']} {place}".strip()
        print(f"{fore.GREEN}Moving on to search query: {query}{fore.RESET}")

        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
        driver.get(search_url)

        # Wait for page or feed to load
        time.sleep(4)

        # Handle consent popup if present
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                if btn.text in ['Accept all', 'Agree', 'I agree']:
                    btn.click()
                    time.sleep(2)
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

        # Scroll to load requested depth of results
        # Each scroll loads ~10-20 more results
        scroll_iterations = max(1, SETTINGS["PAGE_DEPTH"] * 3)
        if feed:
            for s in range(scroll_iterations):
                driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', feed)
                time.sleep(2)

        # Find all cards
        cards = driver.find_elements(By.XPATH, '//div[contains(@class, "Nv2PK")]')
        print(f"{fore.GREEN}Found {len(cards)} places for {place}{fore.RESET}")

        for box in cards:
            try:
                text = box.text
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                if not lines:
                    continue

                # Name
                name = lines[0]
                try:
                    title_el = box.find_element(By.XPATH, './/div[contains(@class, "qBF1Pd")]')
                    if title_el and title_el.text.strip():
                        name = title_el.text.strip()
                except Exception:
                    pass

                # Google Maps Link
                maps_link = ""
                try:
                    link_el = box.find_element(By.XPATH, './/a[contains(@class, "hfpxzc")]')
                    maps_link = link_el.get_attribute('href') or ""
                except Exception:
                    pass

                # Website
                website = ""
                try:
                    web_el = box.find_element(By.XPATH, './/a[@data-value="Website" or contains(@aria-label, "Website")]')
                    website = web_el.get_attribute('href') or ""
                except Exception:
                    pass

                has_website = "Yes" if bool(website) else "No"

                # Phone number
                phone = ""
                phone_matches = re.findall(r'(\+?92[\s\d-]{8,}|\(0\d{2,3}\)[\s\d-]+|03\d{2}[\s\d-]{7,}|\+?\d{1,3}[\s-]\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{3,4})', text)
                if phone_matches:
                    phone = phone_matches[0].strip()

                # Address
                address = ""
                for line in lines:
                    if '·' in line and not any(k in line for k in ['Open', 'Closed', 'Opens', 'Closes', '24 hours']) and line != lines[0]:
                        parts = [p.strip() for p in line.split('·') if p.strip()]
                        if len(parts) > 1:
                            address = parts[-1]
                if not address and len(lines) > 2:
                    # Fallback address guess
                    for candidate in lines[1:]:
                        if not any(k in candidate for k in ['Open', 'Closed', 'Directions', 'Website', 'reviews', '★', 'Reviews']) and not re.match(r'^\d\.\d$', candidate):
                            address = candidate
                            break

                scraped = address in addresses_scraped if address else (name in scraped_names)

                if scraped and args.skip_duplicate_addresses:
                    print(f"{fore.WARNING}Skipping {name} as duplicate{fore.RESET}")
                    continue

                if address:
                    addresses_scraped[address] = addresses_scraped.get(address, 0) + 1
                scraped_names.add(name)

                print(f"{fore.GREEN}Currently scraping{fore.RESET}: {name} | Has Website: {has_website} | Phone: {phone or 'N/A'}")

                current_data = {
                    "name": name,
                    "phone": phone,
                    "address": address,
                    "has_website": has_website,
                    "website": website,
                    "maps_link": maps_link,
                    "email": ""
                }

                if args.scrape_website and website:
                    try:
                        web_url, emails = get_website_data(website)
                        if web_url:
                            current_data["website"] = web_url
                        if emails:
                            current_data["email"] = ','.join(emails)
                    except Exception as e:
                        pass
                elif not args.scrape_website:
                    current_data.pop("email", None)

                if args.verbose:
                    print(json.dumps(current_data, indent=1))

                write_data_row(worksheet, current_data, row)
                row += 1

            except Exception as item_err:
                continue

        print("-------------------")

    workbook.close()
    driver.quit()

    end_time = time.time()
    elapsed = round(end_time - start_time, 2)
    print(f"{fore.GREEN}Done! Scraped {row - 1} records into ScrapedData_GoogleMaps.xlsx in {elapsed}s{fore.RESET}")