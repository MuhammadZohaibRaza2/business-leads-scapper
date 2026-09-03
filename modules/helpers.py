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

def write_data_row(worksheet, data, row):
    '''
    Writes data dictionary to row.

    Parameters:
            worksheet (worksheet object): Worksheet where data should be written
            data (dict): Dictionary containing data to write
            row (int): No. of row to write to
    '''
    col = 0
    for key in data:
        worksheet.write(row, col, data[key])
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
        # Direct regex search on page text
        emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', content)
        # Filter out obvious non-email false positives (e.g. image extensions, svg, font)
        clean_emails = []
        for em in set(emails):
            if not any(em.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.js', '.css', '.woff']):
                clean_emails.append(em)

        return response.url or url, clean_emails
    except Exception:
        return url, []