import datetime
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

FREEJOBALERT_URL = "https://www.freejobalert.com/"
SARKARIRESULT_URLS = [
    "https://www.sarkariresult.com/",
    "https://www.sarkariresult.com/latestjob.php",
    "https://www.sarkariresult.com/admitcard.php",
    "https://www.sarkariresult.com/result.php",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
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
    """Pehle se maujood data.json ko load karta hai taaki purana data delete na ho"""
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
            print(f"Error reading existing data.json: {e}")
    return default_data


def extract_official_link_from_sr_post(post_url):
    """Sarkari Result ke post page ke andar se asli .gov.in / .nic.in link nikalta hai"""
    try:
        res = requests.get(post_url, headers=HEADERS, timeout=12, verify=False)
        if res.status_code != 200:
            return None
        post_soup = BeautifulSoup(res.text, "html.parser")
        official_candidates = []

        for a in post_soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(" ", strip=True).lower()
            if is_official_gov_url(href):
                if any(k in text for k in ["apply", "official", "notification", "download", "admit", "result", "click here"]):
                    return href
                official_candidates.append(href)

        return official_candidates[0] if official_candidates else None
    except Exception:
        return None


def fetch_sarkari_result(new_items, seen_titles, seen_urls):
    print("Discovering updates from Sarkari Result...")
    discovered_links = []

    for sr_url in SARKARIRESULT_URLS:
        try:
            res = requests.get(sr_url, headers=HEADERS, timeout=15, verify=False)
            if res.status_code != 200:
                print(f"Sarkari Result status {res.status_code} for {sr_url}")
                continue
            soup = BeautifulSoup(res.text, "html.parser")

            for a in soup.select("#post ul li a, table a"):
                raw_title = a.get_text(" ", strip=True)
                href = urljoin(sr_url, a.get("href", ""))

                if (
                    not raw_title
                    or len(raw_title) < 10
                    or raw_title.lower() in seen_titles
                    or "sarkariresult.com" not in href
                ):
                    continue

                if not re.search(
                    r"(online-form|recruitment|vacancy|bharti|admit-card|result|answer-key|notification|exam)",
                    href,
                    re.I,
                ):
                    continue

                discovered_links.append((raw_title, href))
        except Exception as e:
            print(f"Error fetching {sr_url}: {e}")

    added_count = 0
    for raw_title, post_url in discovered_links:
        if raw_title.lower() in seen_titles or added_count >= 25:
            continue

        official_url = extract_official_link_from_sr_post(post_url)
        if not official_url or official_url in seen_urls:
            continue

        category = categorize_item(raw_title)
        clean_title = make_copyright_free(raw_title)

        if clean_title.lower() in seen_titles:
            continue

        seen_titles.add(raw_title.lower())
        seen_titles.add(clean_title.lower())
        seen_urls.add(official_url)

        new_items[category].append({
            "title": clean_title,
            "url": official_url,
            "department": clean_title.split()[0] + " Recruitment Board",
            "date": datetime.datetime.now().strftime("%d/%m/%Y"),
        })
        added_count += 1
        print(f"[NEW SR -> {category.upper()}] {clean_title}")


def fetch_freejobalert(new_items, seen_titles, seen_urls):
    print("Fetching updates from FreeJobAlert...")
    try:
        response = requests.get(FREEJOBALERT_URL, headers=HEADERS, timeout=15, verify=False)
        soup = BeautifulSoup(response.text, "html.parser")

        links = soup.select("table.qltpmnu a, .gb-inside-container a")
        added_count = 0
        for link in links:
            raw_title = link.text.strip()
            href = link.get("href", "#")

            if (
                not raw_title
                or len(raw_title) < 10
                or raw_title.lower() in seen_titles
                or href in seen_urls
                or not href.startswith("http")
                or added_count >= 15
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
            added_count += 1
            print(f"[NEW FJA -> {category.upper()}] {clean_title}")
    except Exception as e:
        print(f"Error fetching FreeJobAlert: {e}")


def run_scraper():
    # 1. Pehle purana data.json load karein (kuch bhi delete nahi hoga)
    existing_data = load_existing_data()

    seen_titles = set()
    seen_urls = set()
    for cat in ["latest_jobs", "admit_cards", "results", "answer_keys"]:
        for item in existing_data[cat]:
            seen_titles.add(item.get("title", "").lower())
            seen_urls.add(item.get("url", ""))

    new_items = {
        "latest_jobs": [],
        "admit_cards": [],
        "results": [],
        "answer_keys": [],
    }

    # 2. Naye updates fetch karein
    fetch_sarkari_result(new_items, seen_titles, seen_urls)
    fetch_freejobalert(new_items, seen_titles, seen_urls)

    # 3. Naye items ko sabse upar jodein aur purane neeche safe rakhein
    existing_data["updated_at"] = datetime.datetime.now().strftime("%d/%m/%Y")
    for cat in ["latest_jobs", "admit_cards", "results", "answer_keys"]:
        existing_data[cat] = new_items[cat] + existing_data[cat]

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
    print("data.json updated safely without deleting old records!")


if __name__ == "__main__":
    run_scraper()
