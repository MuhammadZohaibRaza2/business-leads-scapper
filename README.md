# Business Leads Scraper

A fast and automated Python tool built with **Selenium** to scrape comprehensive business leads and place information directly from Google Maps search results into structured Excel (`.xlsx`) spreadsheets.

---

## 🌟 Features

- **Business Details Extraction**:
  - 🏢 **Name**: Business or clinic/company name
  - 📞 **Phone Number**: Direct contact / business phone number
  - 📍 **Address**: Location / street / market address
  - 🌐 **Has Website**: Instant `Yes` / `No` status indicator
  - 🔗 **Website URL**: Direct link to the business website (if available)
  - 🗺️ **Google Maps Link**: Direct URL to the business Google Maps place card
  - ✉️ **Email Address**: Crawls target websites to extract contact emails (optional)
- **Multi-Location Search**: Query multiple cities, areas, or zip codes in a single command.
- **Configurable Scroll & Pagination Depth**: Control how many batches/pages of results to fetch per location.
- **Duplicate Filtering**: Built-in address and place deduplication.
- **Excel Export**: Exports cleanly formatted data directly to `ScrapedData_GoogleMaps.xlsx`.
- **Headless Chrome Execution**: Runs quietly in the background without popups.

---

## 🚀 Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/MuhammadZohaibRaza2/business-leads-scapper.git
cd business-leads-scapper
```

### 2. Install dependencies
Ensure Python 3.8+ and Google Chrome are installed on your system.
```bash
pip install -r requirements.txt
```

---

## 🛠️ Usage & CLI Arguments

Run the scraper using `script.py`:

```bash
python script.py --query="<search query>" --places="<comma,separated,places>" [options]
```

### Available Arguments:

| Argument | Type | Required | Description |
| :--- | :---: | :---: | :--- |
| `--query` | `str` | **Yes** | Base search keyword/query (e.g. `"clinics in"`, `"restaurants near"`, `"lawyers in"`). |
| `--places` | `str` | **Yes** | Comma-separated list of cities, towns, or zip codes (e.g. `"Islamabad,Rawalpindi,Lahore"`). |
| `--pages` | `int` | No | Depth / scroll level for search results (default: `1`). |
| `--scrape-website` | `flag` | No | Enables crawling target websites to discover email addresses. |
| `--skip-duplicate-addresses` | `flag` | No | Automatically ignores businesses that share an already-scraped address. |
| `--verbose` | `flag` | No | Prints real-time JSON payloads in the terminal for each result. |

---

## 📖 Examples

### 1. Basic Search
Scrape clinics in Islamabad:
```bash
python script.py --query="clinics in" --places="Islamabad" --pages=2
```

### 2. Multi-City Search
Scrape hotels across multiple cities:
```bash
python script.py --query="hotels in" --places="Islamabad,Lahore,Karachi" --pages=3
```

### 3. Website & Email Extraction
Scrape digital marketing agencies and scan their websites for contact emails:
```bash
python script.py --query="digital marketing agencies in" --places="Islamabad" --scrape-website --verbose
```

---

## 📊 Output Format

The scraper automatically writes results to `ScrapedData_GoogleMaps.xlsx` with the following columns:

| Name | Phone | Address | Has Website | Website | Google Maps Link | Email (Optional) |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- |

---

## 📄 License
MIT License
