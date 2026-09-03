import os
import time
import json
import uuid
import threading
import io
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import xlsxwriter

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import urllib.parse
from modules.helpers import get_website_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# Global storage for background tasks
tasks = {}

JS_EXTRACT_ALL_CARDS = r'''
const cards = document.querySelectorAll('div.Nv2PK');
const results = [];
cards.forEach(card => {
    const text = card.innerText || '';
    const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    if (!lines.length) return;
    
    // Title/Name
    let name = lines[0];
    const nameEl = card.querySelector('div.qBF1Pd');
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
    const webEl = card.querySelector('a[data-value="Website"], a[aria-label*="Website"]');
    if (webEl && webEl.href) {
        website = webEl.href;
    }
    
    // Phone Number Regex
    let phone = '';
    const phoneMatches = text.match(/(\+?92[\s\d-]{8,}|\(0\d{2,3}\)[\s\d-]+|03\d{2}[\s\d-]{7,}|\+?\d{1,3}[\s-]\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{3,4})/);
    if (phoneMatches) {
        phone = phoneMatches[0].trim();
    }
    
    // Address Extraction
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

def run_scraper_thread(task_id, params):
    task = tasks[task_id]
    task["status"] = "running"
    task["started_at"] = time.time()
    task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Launching browser...")

    query_base = params.get("query", "").strip()
    places_raw = params.get("places", "").strip()
    places = [p.strip() for p in places_raw.split(",") if p.strip()] or [""]
    pages = int(params.get("pages", 2))
    scrape_website = params.get("scrape_website", False)
    skip_duplicates = params.get("skip_duplicates", True)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        task["driver"] = driver
        wait = WebDriverWait(driver, 10)

        addresses_seen = set()
        names_seen = set()

        for place in places:
            if task.get("aborted"):
                break

            full_query = f"{query_base} {place}".strip()
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Searching: '{full_query}'")

            encoded_query = urllib.parse.quote_plus(full_query)
            search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
            driver.get(search_url)

            # Short wait for results
            time.sleep(2.5)

            # Accept consent if present
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    if btn.text in ["Accept all", "Agree", "I agree"]:
                        btn.click()
                        time.sleep(1)
                        break
            except Exception:
                pass

            # Find feed
            feed = None
            try:
                feed = wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]')))
            except Exception:
                try:
                    feed = driver.find_element(By.XPATH, '//div[contains(@aria-label, "Results for")]')
                except Exception:
                    pass

            # Fast scrolling
            scroll_count = max(1, pages * 3)
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Scrolling feed for deep results...")

            if feed:
                for s in range(scroll_count):
                    if task.get("aborted"):
                        break
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
                    time.sleep(0.7)

            if task.get("aborted"):
                break

            # Lightning-fast JS extraction
            extracted = driver.execute_script(JS_EXTRACT_ALL_CARDS) or []
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Extracted {len(extracted)} places.")

            for item in extracted:
                if task.get("aborted"):
                    break
                addr = item.get("address", "").strip()
                name = item.get("name", "").strip()

                if skip_duplicates:
                    if addr and addr in addresses_seen:
                        continue
                    if not addr and name in names_seen:
                        continue

                if addr:
                    addresses_seen.add(addr)
                names_seen.add(name)

                task["results"].append(item)
                task["count"] = len(task["results"])

        # Asynchronous Email discovery if requested
        if scrape_website and not task.get("aborted"):
            websites_to_crawl = [
                (idx, item["website"]) for idx, item in enumerate(task["results"]) if item.get("website")
            ]
            if websites_to_crawl:
                task["logs"].append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Checking {len(websites_to_crawl)} websites for emails in parallel..."
                )

                def check_email_worker(target):
                    if task.get("aborted"):
                        return
                    idx, url = target
                    try:
                        _, emails = get_website_data(url)
                        if emails:
                            task["results"][idx]["email"] = ", ".join(emails)
                    except Exception:
                        pass

                with ThreadPoolExecutor(max_workers=8) as executor:
                    list(executor.map(check_email_worker, websites_to_crawl))

        if task.get("aborted"):
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Stopped by user. {len(task['results'])} leads saved.")
            task["status"] = "stopped"
        else:
            task["logs"].append(
                f"[{datetime.now().strftime('%H:%M:%S')}] Finished! Scraped {len(task['results'])} leads."
            )
            task["status"] = "completed"

    except Exception as e:
        err_msg = str(e)
        if task.get("aborted"):
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Scraping stopped by user.")
            task["status"] = "stopped"
        elif "Unable to obtain driver for chrome" in err_msg or "chromedriver" in err_msg or "NoSuchDriver" in err_msg:
            task["logs"].append(
                f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Chrome Browser is not installed in this Serverless environment (Vercel Lambda)."
            )
            task["logs"].append(
                f"[{datetime.now().strftime('%H:%M:%S')}] 👉 To scrape live Google Maps leads, run the app locally on your Mac ('python3 app.py') or deploy with Docker/Render."
            )
            task["status"] = "failed"
            task["error"] = "Chrome binary not available in serverless environment"
        else:
            task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {err_msg}")
            task["status"] = "failed"
            task["error"] = err_msg
    finally:
        task["finished_at"] = time.time()
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        task["driver"] = None


@app.route("/")
@app.route("/index")
@app.route("/api")
@app.route("/api/index")
@app.route("/api/index.py")
def index():
    return render_template("index.html")


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)


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
        "driver": None,
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
        task = tasks[task_id]
        task["aborted"] = True
        task["status"] = "stopped"
        if task.get("driver"):
            try:
                task["driver"].quit()
            except Exception:
                pass
            task["driver"] = None
        task["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Stop command received.")
        return jsonify({"success": True, "message": "Stopped"})
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


def find_available_port(start_port=5001, max_tries=10):
    import socket
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start_port


if __name__ == "__main__":
    requested_port = int(os.environ.get("PORT", 5001))
    port = find_available_port(requested_port)
    print(f"Server starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
