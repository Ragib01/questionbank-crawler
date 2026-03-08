"""
Query the pdf.exambd.net WordPress REST API for exam question content.
Also explore sattacademy.com.
"""
import sys, io, re, json, requests
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE = "https://pdf.exambd.net/wp-json/wp/v2"


def wp_query(endpoint, params=None):
    url = f"{BASE}/{endpoint}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def html_to_text(html):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    return soup.get_text(separator="\n", strip=True)


# ── 1. Get categories ─────────────────────────────────────────────────────────
print("=== CATEGORIES ===")
try:
    cats = wp_query("categories", {"per_page": 20})
    for c in cats:
        print(f"  id={c['id']} slug={c['slug']} name={c['name']} count={c['count']}")
except Exception as e:
    print(f"Error: {e}")

# ── 2. BCS posts ──────────────────────────────────────────────────────────────
print("\n=== BCS POSTS (search=bcs) ===")
try:
    posts = wp_query("posts", {"search": "bcs", "per_page": 10, "_fields": "id,title,slug,link,content"})
    for p in posts:
        title = p['title']['rendered']
        link = p['link']
        content_html = p['content']['rendered']
        content_text = html_to_text(content_html)
        # Check if content has question-like data
        has_q = bool(re.search(r'question|mcq|answer|option|[\u0980-\u09FF].*\?', content_text, re.I))
        pdf_links = re.findall(r'https?://[^\s"<>]+\.pdf', content_html)
        print(f"\n  [{p['id']}] {title}")
        print(f"  Link: {link}")
        print(f"  Content chars: {len(content_text)} | Has Q?: {has_q} | PDF links: {len(pdf_links)}")
        print(f"  Content preview: {content_text[:300]}")
        if pdf_links:
            print(f"  PDFs: {pdf_links[:3]}")
except Exception as e:
    print(f"Error: {e}")

# ── 3. Bank/Ministry/Teacher posts ───────────────────────────────────────────
for search_term in ["bank mcq", "ntrca", "primary teacher", "ministry"]:
    print(f"\n=== POSTS: {search_term} ===")
    try:
        posts = wp_query("posts", {"search": search_term, "per_page": 3, "_fields": "id,title,link,content"})
        for p in posts:
            title = p['title']['rendered']
            content_html = p['content']['rendered']
            content_text = html_to_text(content_html)
            pdf_links = re.findall(r'https?://[^\s"<>]+\.pdf', content_html)
            print(f"  [{p['id']}] {title} — {p['link']}")
            print(f"  Content: {len(content_text)} chars | PDFs: {pdf_links[:2]}")
            if len(content_text) > 200:
                print(f"  Preview: {content_text[:200]}")
    except Exception as e:
        print(f"Error: {e}")

# ── 4. Sattacademy.com ────────────────────────────────────────────────────────
print("\n=== SATTACADEMY.COM ===")
SATT_PATHS = [
    "https://sattacademy.com/",
    "https://sattacademy.com/api/subjects/",
    "https://sattacademy.com/api/",
    "https://sattacademy.com/job-solution/",
    "https://sattacademy.com/question/",
    "https://sattacademy.com/mcq/",
    "https://sattacademy.com/admission/",
    "https://sattacademy.com/bcs-preliminary/",
]
for url in SATT_PATHS:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        for t in soup(["script", "style"]):
            t.decompose()
        text = soup.get_text(separator=" ", strip=True)
        has_q = bool(re.search(r'question|mcq|answer|exam|[\u0980-\u09FF]', text[:500], re.I))
        print(f"  {url} → {r.status_code} | {len(text)} chars | Q? {has_q}")
        if r.status_code == 200 and len(text) > 200:
            print(f"    {text[:200]}")
        # Check if JSON API
        try:
            jdata = r.json()
            print(f"    JSON keys: {list(jdata.keys())[:5] if isinstance(jdata, dict) else 'list'}")
        except Exception:
            pass
    except Exception as e:
        print(f"  {url} → ERROR: {e}")
