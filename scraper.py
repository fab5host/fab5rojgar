import datetime
import json
import os
from bs4 import BeautifulSoup
import google.generativeai as genai
import requests

# Gemini API Setup
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
else:
    model = None

TARGET_URL = "https://www.freejobalert.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def make_copyright_free(text):
    if not model:
        return text
    try:
        prompt = f"Rewrite this Indian government exam/job headline cleanly in English without changing department names, post names, or numbers. Keep it concise (under 10 words) and unique: '{text}'"
        response = model.generate_content(prompt)
        return response.text.strip().replace('"', "").replace("*", "")
    except Exception:
        return text


def categorize_item(title):
    t = title.lower()
    if "admit card" in t or "call letter" in t or "hall ticket" in t:
        return "admit_cards"
    elif "result" in t or "merit list" in t or "cut off" in t:
        return "results"
    elif "answer key" in t or "response sheet" in t:
        return "answer_keys"
    else:
        return "latest_jobs"


def run_scraper():
    print("Fetching updates...")
    response = requests.get(TARGET_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    data = {
        "updated_at": datetime.datetime.now().strftime("%d/%m/%Y"),
        "latest_jobs": [],
        "admit_cards": [],
        "results": [],
        "answer_keys": [],
    }

    # Sabhi main links aur quick links table se data uthana
    links = soup.select("table.qltpmnu a, .gb-inside-container a")
    seen_titles = set()

    for link in links:
        raw_title = link.text.strip()
        href = link.get("href", "#")

        if (
            not raw_title
            or len(raw_title) < 10
            or raw_title in seen_titles
            or not href.startswith("http")
        ):
            continue

        seen_titles.add(raw_title)
        category = categorize_item(raw_title)

        # Har category mein max 6 latest items rakhein
        if len(data[category]) >= 6:
            continue

        clean_title = make_copyright_free(raw_title)

        data[category].append({
            "title": clean_title,
            "url": href,
            "department": clean_title.split()[0] + " Recruitment Board",
            "date": datetime.datetime.now().strftime("%d/%m/%Y"),
        })
        print(f"[{category.upper()}] {clean_title}")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("data.json updated successfully!")


if __name__ == "__main__":
    run_scraper()
