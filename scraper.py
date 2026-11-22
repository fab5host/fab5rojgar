import csv
import datetime
import io
import json
import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import google.generativeai as genai
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Gemini API Setup
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
else:
    model = None

# Apni Google Sheet ka Publish-to-Web CSV link yahan paste karein:
GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPVncNeZZvPTkyWLcog4jVRl2SqR2UNtjSPOY_ULlEZE-zY7eS5kwcrLMrPPTdFGPV0Jj3LmSsCWUS/pub?gid=0&single=true&output=csv"

FREEJOBALERT_URL = "https://www.freejobalert.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}

OFFICIAL_DOMAINS = (
    ".gov.in",
    ".nic.in",
    ".ac.in",
    ".org.in",
    "ibps.in",
    "ssc.gov.in",
    "upsc.gov.in",
    "rrbcdg.gov.in",
    "nta.ac.in",
)


def is_official_gov_url(url):
    if not url or not url.startswith("http"):
        return False
    domain = urlparse(url).netloc.lower()
    return any(domain.endswith(ext) or domain == ext.lstrip(".") for ext in OFFICIAL_DOMAINS)


def make_copyright_free(text):
    if not model:
        return text
    try:
        prompt = (
            "Rewrite this Indian government exam/job headline cleanly in English "
            "without changing department names, post names, or numbers. "
            f"Keep it concise (under 10 words) and unique: '{text}'"
        )
        response = model.generate_content(prompt)
        return response.text.strip().replace('"', "").replace("*", "")
    except Exception:
        return text


def categorize_item(title):
    t = title.lower()
    if "admit card" in t or "call letter" in t or "hall ticket" in t or "exam city" in t:
        return "admit_cards"
    elif "result" in t or "merit list" in t or "cut off" in t or "score card" in t:
        return "results"
    elif "answer key" in t or "response sheet" in t:
        return "answer_keys"
    else:
        return "latest_jobs"


def load_existing_data():
    default_data = {
        "updated_at": datetime.datetime.now().strftime("%d/%m/%Y"),
        "latest_jobs": [],
        "admit_cards": [],
        "results": [],
        "answer_keys": [],
    }
    if os.path.exists("data.json"):
        try:
            with open("data.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for key in ["latest_jobs", "admit_cards", "results", "answer_keys"]:
                    if key not in loaded or not isinstance(loaded[key], list):
                        loaded[key] = []
                return loaded
        except Exception as e:
            print(f"Error reading data.json: {e}")
    return default_data


def extract_official_link_if_needed(url):
    """Agar sheet mein sarkariresult ka link hai to andar se asli .gov.in link nikalta hai"""
    if is_official_gov_url(url):
        return url
    if "sarkariresult.com" not in url:
        return None
    try:
        res = requests.get(url, headers=HEADERS, timeout=12, verify=False)
        if res.status_code != 200:
            return None
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if is_official_gov_url(href):
                return href
    except Exception:
        pass
    return None


def fetch_from_google_sheet(new_items, seen_titles, seen_urls):
    if not GOOGLE_SHEET_CSV_URL.startswith("http"):
        print("Google Sheet CSV URL not set yet.")
        return

    print("Fetching Sarkari Result data from Google Sheet...")
    try:
        res = requests.get(GOOGLE_SHEET_CSV_URL, timeout=15)
        res.raise_for_status()
        reader = csv.reader(io.StringIO(res.text))
        rows = list(reader)

        # Header row skip karein agar pehli row mein 'Title' ya 'Post' likha ho
        start_idx = 1 if rows and any("title" in c.lower() or "post" in c.lower() for c in rows[0]) else 0

        for row in rows[start_idx:]:
            if len(row) < 2:
                continue

            # Row ke columns se Title aur URL auto-detect karein
            raw_title = ""
            raw_url = ""
            for cell in row:
                cell = cell.strip()
                if cell.startswith("http") and not raw_url:
                    raw_url = cell
                elif len(cell) > 10 and not raw_title:
                    raw_title = cell

            if not raw_title or not raw_url or raw_title.lower() in seen_titles:
                continue

            # Official .gov.in / .nic.in link verify karein
            verified_url = extract_official_link_if_needed(raw_url)
            if not verified_url or verified_url in seen_urls:
                continue

            category = categorize_item(raw_title)
            clean_title = make_copyright_free(raw_title)
            if clean_title.lower() in seen_titles:
                continue

            seen_titles.add(raw_title.lower())
            seen_titles.add(clean_title.lower())
            seen_urls.add(verified_url)

            new_items[category].append({
                "title": clean_title,
                "url": verified_url,
                "department": clean_title.split()[0] + " Recruitment Board",
                "date": datetime.datetime.now().strftime("%d/%m/%Y"),
            })
            print(f"[SHEET -> {category.upper()}] {clean_title} -> {verified_url}")
    except Exception as e:
        print(f"Google Sheet Fetch Error: {e}")


def fetch_freejobalert(new_items, seen_titles, seen_urls):
    print("Fetching updates from FreeJobAlert...")
    try:
        response = requests.get(FREEJOBALERT_URL, headers=HEADERS, timeout=15, verify=False)
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.select("table.qltpmnu a, .gb-inside-container a")

        for link in links:
            raw_title = link.text.strip()
            href = link.get("href", "#")
            if (
                not raw_title
                or len(raw_title) < 10
                or raw_title.lower() in seen_titles
                or href in seen_urls
                or not href.startswith("http")
            ):
                continue

            category = categorize_item(raw_title)
            clean_title = make_copyright_free(raw_title)
            if clean_title.lower() in seen_titles:
                continue

            seen_titles.add(raw_title.lower())
            seen_titles.add(clean_title.lower())
            seen_urls.add(href)

            new_items[category].append({
                "title": clean_title,
                "url": href,
                "department": clean_title.split()[0] + " Recruitment Board",
                "date": datetime.datetime.now().strftime("%d/%m/%Y"),
            })
    except Exception as e:
        print(f"Error fetching FreeJobAlert: {e}")


def run_scraper():
    existing_data = load_existing_data()
    seen_titles = set()
    seen_urls = set()

    for cat in ["latest_jobs", "admit_cards", "results", "answer_keys"]:
        for item in existing_data[cat]:
            seen_titles.add(item.get("title", "").lower())
            seen_urls.add(item.get("url", ""))

    new_items = {"latest_jobs": [], "admit_cards": [], "results": [], "answer_keys": []}

    # 1. Google Sheet se Sarkari Result ka data
    fetch_from_google_sheet(new_items, seen_titles, seen_urls)

    # 2. FreeJobAlert ka pehle se chal raha data
    fetch_freejobalert(new_items, seen_titles, seen_urls)

    existing_data["updated_at"] = datetime.datetime.now().strftime("%d/%m/%Y")
    for cat in ["latest_jobs", "admit_cards", "results", "answer_keys"]:
        existing_data[cat] = new_items[cat] + existing_data[cat]

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
    print("data.json updated safely!")


if __name__ == "__main__":
    run_scraper()
