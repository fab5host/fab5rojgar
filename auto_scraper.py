
import os
import re
import json
import html
import hashlib
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, parse_qs
from pathlib import Path

import requests
import feedparser
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
OUT = ROOT / "auto_jobs"
PAGES = OUT / "pages"
OUT.mkdir(exist_ok=True)
PAGES.mkdir(exist_ok=True)

JSON_FILE = OUT / "jobs.json"
INDEX_FILE = OUT / "index.html"

HEADERS = {
    "User-Agent": "FAB5HOST Vacancy Monitor/1.0 (public job information)"
}

SEARCHES = [
    'site:freejobalert.com latest recruitment vacancy',
    'site:sarkariresult.com latest recruitment vacancy',
    'government recruitment notification India latest',
    'site:gov.in recruitment notification latest',
    'site:nic.in recruitment notification latest'
]

# Official application domains only.
OFFICIAL_DOMAINS = {
    "ssc.gov.in",
    "upsc.gov.in",
    "nta.ac.in",
    "ibps.in",
    "rrbapply.gov.in",
    "indianrailways.gov.in",
    "joinindianarmy.nic.in",
    "joinindiannavy.gov.in",
    "agnipathvayu.cdac.in",
    "drdo.gov.in",
    "esic.gov.in",
    "epfindia.gov.in",
    "indiapost.gov.in",
    "sbi.co.in",
    "hssc.gov.in",
    "hpsc.gov.in",
    "psc.gov.in",
}

BLOCKED_PUBLIC_DOMAINS = {
    "freejobalert.com",
    "sarkariresult.com",
    "sarkariresult.com.cm",
}

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def domain(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def is_blocked(url):
    d = domain(url)
    return any(d == x or d.endswith("." + x)
               for x in BLOCKED_PUBLIC_DOMAINS)

def is_official(url):
    d = domain(url)

    if not d or is_blocked(url):
        return False

    if d in OFFICIAL_DOMAINS:
        return True

    # Government domains
    if d.endswith(".gov.in"):
        return True

    if d.endswith(".nic.in"):
        return True

    return False

def slugify(title):
    title = title.lower()
    title = re.sub(r"[^a-z0-9]+", "-", title)
    title = title.strip("-")[:90]

    if not title:
        title = hashlib.md5(
            str(time.time()).encode()
        ).hexdigest()[:12]

    return title

def fetch(url, timeout=20):
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        print("Fetch error:", url, e)
        return ""

def google_news_rss(query):
    url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=en-IN&gl=IN&ceid=IN:en"
    )

    feed = feedparser.parse(url)
    items = []

    for entry in feed.entries[:20]:
        items.append({
            "title": clean_text(entry.get("title")),
            "url": entry.get("link", ""),
            "date": entry.get("published", "")
        })

    return items

def resolve_google_url(url):
    # RSS URLs sometimes redirect to the real article.
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True
        )
        return r.url
    except Exception:
        return url

def extract_article(url):
    page = fetch(url)

    if not page:
        return "", [], ""

    soup = BeautifulSoup(page, "html.parser")

    for tag in soup([
        "script", "style", "noscript",
        "iframe", "nav", "footer", "header"
    ]):
        tag.decompose()

    title = ""
    if soup.title:
        title = clean_text(soup.title.get_text())

    paragraphs = []

    for p in soup.find_all(["p", "li"]):
        text = clean_text(p.get_text(" ", strip=True))

        if len(text) > 35:
            paragraphs.append(text)

    paragraphs = list(dict.fromkeys(paragraphs))

    official_links = []

    for a in soup.find_all("a", href=True):
        link = a["href"]
        text = clean_text(a.get_text(" ", strip=True))

        if link.startswith("http") and is_official(link):
            official_links.append({
                "text": text,
                "url": link
            })

    return title, paragraphs[:100], official_links

def vacancy_like(title, text):
    content = (title + " " + text).lower()

    keywords = [
        "recruitment", "vacancy", "jobs", "job",
        "apply online", "notification", "admit card",
        "result", "government", "bharti", " भर्ती",
        "rojgar", "application form"
    ]

    return any(k in content for k in keywords)

def find_official_apply(links):
    for item in links:
        if is_official(item["url"]):
            text = item["text"].lower()

            if any(k in text for k in [
                "apply", "online", "registration",
                "application", "official website"
            ]):
                return item["url"]

    # If we cannot confidently identify an Apply link,
    # use no link rather than an unofficial one.
    return ""

def make_page(job):
    title = html.escape(job["title"])
    details = job["details"]
    paragraphs = "".join(
        "<p>" + html.escape(p) + "</p>"
        for p in details[:45]
    )

    apply_button = ""

    if job.get("official_apply"):
        apply_button = f"""
        <a class="apply"
           href="{html.escape(job['official_apply'], quote=True)}"
           target="_blank"
           rel="noopener noreferrer">
           Official Apply Website
        </a>
        """

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | FAB5HOST</title>
<meta name="description"
content="{html.escape(title)} government vacancy information and notification details.">
<link rel="canonical"
href="https://fab5host.page.gd/auto_jobs/pages/{job['slug']}.html">
<style>
body{{font-family:Arial,sans-serif;background:#f4f7fb;
margin:0;color:#182238}}
header{{background:#101c3b;color:white;padding:22px}}
main{{max-width:900px;margin:20px auto;padding:20px;
background:white;border-radius:12px}}
h1{{line-height:1.4}}
p{{line-height:1.8}}
.apply{{display:inline-block;background:#087b42;color:white;
padding:14px 20px;border-radius:8px;text-decoration:none;
font-weight:bold;margin:15px 0}}
.notice{{padding:12px;background:#fff3cd;border-radius:8px}}
footer{{padding:20px;text-align:center}}
</style>
</head>
<body>
<header>
<a href="../../index.html" style="color:white">FAB5HOST</a>
</header>
<main>
<h1>{title}</h1>
<p>Information updated:
{html.escape(job["updated"])}</p>
<div class="notice">
Please verify dates, eligibility and documents
from the official notification before applying.
</div>
{apply_button}
<h2>Recruitment Details</h2>
{paragraphs}
{apply_button}
</main>
<footer>FAB5HOST — Government Job Updates</footer>
</body>
</html>
"""

    (PAGES / f"{job['slug']}.html").write_text(
        page, encoding="utf-8"
    )

def create_index(jobs):
    cards = []

    for job in jobs:
        cards.append(f"""
        <article>
        <h3>
        <a href="pages/{html.escape(job['slug'])}.html">
        {html.escape(job['title'])}
        </a>
        </h3>
        <p>{html.escape(job['updated'])}</p>
        </article>
        """)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Latest Government Jobs | FAB5HOST</title>
<style>
body{{font-family:Arial;background:#f3f6fb;padding:15px}}
article{{background:white;padding:16px;margin:12px 0;
border-radius:10px}}
a{{color:#075bb5}}
</style>
</head>
<body>
<h1>Latest Government Jobs</h1>
{''.join(cards)}
</body>
</html>"""

    INDEX_FILE.write_text(page, encoding="utf-8")

def main():
    existing = []

    if JSON_FILE.exists():
        try:
            existing = json.loads(
                JSON_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            existing = []

    if not isinstance(existing, list):
        existing = []

    known = {
        j.get("id")
        for j in existing
        if isinstance(j, dict)
    }

    added = 0

    for query in SEARCHES:
        print("Searching:", query)

        for item in google_news_rss(query):
            url = resolve_google_url(item["url"])

            # Do not publish source-site URLs.
            if is_blocked(url):
                # Still inspect internally, but never use it as
                # a public link.
                pass

            article_title, paragraphs, links = extract_article(url)

            title = item["title"] or article_title

            combined = " ".join(paragraphs)

            if not vacancy_like(title, combined):
                continue

            if len(combined) < 100:
                continue

            job_id = hashlib.sha256(
                title.lower().encode()
            ).hexdigest()[:16]

            if job_id in known:
                continue

            official = find_official_apply(links)

            slug = slugify(title)

            job = {
                "id": job_id,
                "slug": slug,
                "title": title,
                "details": paragraphs,
                "official_apply": official,
                "updated": datetime.now(
                    timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC")
            }

            existing.insert(0, job)
            known.add(job_id)

            make_page(job)
            added += 1

            print("Added:", title)

            time.sleep(2)

    # Preserve existing entries; only add new ones.
    JSON_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    create_index(existing)

    print("New jobs:", added)
    print("Total:", len(existing))

if __name__ == "__main__":
    main()
