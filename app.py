import os
import time
import json
import uuid
import threading
import io
import csv
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
import xlsxwriter

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import urllib.parse
import re
from modules.helpers import get_website_data

app = Flask(__name__)

# Global storage for background tasks
tasks = {}

def run_scraper_thread(task_id, params):
    task = tasks[task_id]
    task["status"] = "running"
    task["started_at"] = time.time()
    task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing Chrome WebDriver...")

    query_base = params.get("query", "").strip()
    places_raw = params.get("places", "").strip()
    places = [p.strip() for p in places_raw.split(",") if p.strip()] or [""]
    pages = int(params.get("pages", 1))
    scrape_website = params.get("scrape_website", False)
    skip_duplicates = params.get("skip_duplicates", True)
    headless = params.get("headless", True)

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 15)

        addresses_seen = set()
        names_seen = set()

        for place in places:
            if task.get("aborted"):
                task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task cancelled by user.")
                break

            full_query = f"{query_base} {place}".strip()
            task["current_query"] = full_query
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Searching Google Maps for: '{full_query}'")

            encoded_query = urllib.parse.quote_plus(full_query)
            search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
            driver.get(search_url)

            time.sleep(3)

            # Accept consent if present
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    if btn.text in ["Accept all", "Agree", "I agree"]:
                        btn.click()
                        time.sleep(1.5)
                        break
            except Exception:
                pass

            feed = None
            try:
                feed = wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]')))
            except Exception:
                try:
                    feed = driver.find_element(By.XPATH, '//div[contains(@aria-label, "Results for")]')
                except Exception:
                    pass

            scroll_times = max(1, pages * 3)
            if feed:
                task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Scrolling results feed ({scroll_times} scrolls)...")
                for s in range(scroll_times):
                    if task.get("aborted"):
                        break
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
                    time.sleep(1.5)

            cards = driver.find_elements(By.XPATH, '//div[contains(@class, "Nv2PK")]')
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(cards)} items for '{place}'. Extracting data...")

            for box in cards:
                if task.get("aborted"):
                    break
                try:
                    text = box.text
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
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

                    # Google Maps link
                    maps_link = ""
                    try:
                        link_el = box.find_element(By.XPATH, './/a[contains(@class, "hfpxzc")]')
                        maps_link = link_el.get_attribute("href") or ""
                    except Exception:
                        pass

                    # Website
                    website = ""
                    try:
                        web_el = box.find_element(
                            By.XPATH, './/a[@data-value="Website" or contains(@aria-label, "Website")]'
                        )
                        website = web_el.get_attribute("href") or ""
                    except Exception:
                        pass

                    has_website = "Yes" if bool(website) else "No"

                    # Phone number
                    phone = ""
                    phone_matches = re.findall(
                        r"(\+?92[\s\d-]{8,}|\(0\d{2,3}\)[\s\d-]+|03\d{2}[\s\d-]{7,}|\+?\d{1,3}[\s-]\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{3,4})",
                        text,
                    )
                    if phone_matches:
                        phone = phone_matches[0].strip()

                    # Address
                    address = ""
                    for line in lines:
                        if "·" in line and not any(k in line for k in ["Open", "Closed", "Opens", "Closes", "24 hours"]) and line != lines[0]:
                            parts = [p.strip() for p in line.split("·") if p.strip()]
                            if len(parts) > 1:
                                address = parts[-1]
                    if not address and len(lines) > 2:
                        for candidate in lines[1:]:
                            if not any(
                                k in candidate
                                for k in ["Open", "Closed", "Directions", "Website", "reviews", "★", "Reviews"]
                            ) and not re.match(r"^\d\.\d$", candidate):
                                address = candidate
                                break

                    # Duplication check
                    if skip_duplicates:
                        if address and address in addresses_seen:
                            continue
                        if not address and name in names_seen:
                            continue

                    if address:
                        addresses_seen.add(address)
                    names_seen.add(name)

                    email = ""
                    if scrape_website and website:
                        try:
                            web_url, emails = get_website_data(website)
                            if emails:
                                email = ", ".join(emails)
                        except Exception:
                            pass

                    item = {
                        "name": name,
                        "phone": phone,
                        "address": address,
                        "has_website": has_website,
                        "website": website,
                        "maps_link": maps_link,
                        "email": email,
                    }
                    task["results"].append(item)
                    task["count"] = len(task["results"])
                except Exception:
                    continue

        task["logs"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] Scraping completed successfully! Total records: {len(task['results'])}"
        )
        task["status"] = "completed"

    except Exception as e:
        task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Error during scraping: {str(e)}")
        task["status"] = "failed"
        task["error"] = str(e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        task["finished_at"] = time.time()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def start_scrape():
    data = request.json or {}
    task_id = str(uuid.uuid4())[:8]

    tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "params": data,
        "results": [],
        "count": 0,
        "logs": [],
        "started_at": None,
        "finished_at": None,
        "aborted": False,
    }

    t = threading.Thread(target=run_scraper_thread, args=(task_id, data), daemon=True)
    t.start()

    return jsonify({"success": True, "task_id": task_id})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({"success": False, "error": "Task not found"}), 404
    task = tasks[task_id]
    elapsed = 0
    if task["started_at"]:
        end = task["finished_at"] or time.time()
        elapsed = round(end - task["started_at"], 1)

    return jsonify(
        {
            "success": True,
            "status": task["status"],
            "count": len(task["results"]),
            "elapsed": elapsed,
            "logs": task["logs"][-20:],
            "results": task["results"],
        }
    )


@app.route("/api/stop/<task_id>", methods=["POST"])
def stop_task(task_id):
    if task_id in tasks:
        tasks[task_id]["aborted"] = True
        return jsonify({"success": True, "message": "Stopping task..."})
    return jsonify({"success": False, "error": "Task not found"}), 404


@app.route("/api/download/<task_id>")
def download_excel(task_id):
    if task_id not in tasks:
        return "Task not found", 404
    task = tasks[task_id]
    results = task["results"]

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("Leads")

    # Header format
    header_fmt = workbook.add_format(
        {"bold": True, "bg_color": "#1E293B", "font_color": "#F8FAFC", "border": 1, "align": "center"}
    )
    cell_fmt = workbook.add_format({"border": 1, "valign": "vcenter"})
    link_fmt = workbook.add_format({"font_color": "#2563EB", "underline": True, "border": 1})

    headers = ["#", "Name", "Phone", "Address", "Has Website", "Website", "Google Maps Link", "Email"]
    for col, h in enumerate(headers):
        worksheet.write(0, col, h, header_fmt)

    for row_idx, item in enumerate(results, start=1):
        worksheet.write(row_idx, 0, row_idx, cell_fmt)
        worksheet.write(row_idx, 1, item.get("name", ""), cell_fmt)
        worksheet.write(row_idx, 2, item.get("phone", ""), cell_fmt)
        worksheet.write(row_idx, 3, item.get("address", ""), cell_fmt)
        worksheet.write(row_idx, 4, item.get("has_website", ""), cell_fmt)

        web = item.get("website", "")
        if web:
            worksheet.write_url(row_idx, 5, web, link_fmt, string=web)
        else:
            worksheet.write(row_idx, 5, "", cell_fmt)

        maps = item.get("maps_link", "")
        if maps:
            worksheet.write_url(row_idx, 6, maps, link_fmt, string="View on Maps")
        else:
            worksheet.write(row_idx, 6, "", cell_fmt)

        worksheet.write(row_idx, 7, item.get("email", ""), cell_fmt)

    worksheet.set_column(0, 0, 5)
    worksheet.set_column(1, 1, 30)
    worksheet.set_column(2, 2, 20)
    worksheet.set_column(3, 3, 35)
    worksheet.set_column(4, 4, 14)
    worksheet.set_column(5, 5, 30)
    worksheet.set_column(6, 6, 20)
    worksheet.set_column(7, 7, 25)

    workbook.close()
    output.seek(0)

    filename = f"BusinessLeads_{task.get('params', {}).get('places', 'data')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/download-csv/<task_id>")
def download_csv(task_id):
    if task_id not in tasks:
        return "Task not found", 404
    task = tasks[task_id]
    results = task["results"]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Phone", "Address", "Has Website", "Website", "Google Maps Link", "Email"])

    for item in results:
        writer.writerow(
            [
                item.get("name", ""),
                item.get("phone", ""),
                item.get("address", ""),
                item.get("has_website", ""),
                item.get("website", ""),
                item.get("maps_link", ""),
                item.get("email", ""),
            ]
        )

    output.seek(0)
    filename = f"BusinessLeads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        download_name=filename,
        as_attachment=True,
        mimetype="text/csv",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Server starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
