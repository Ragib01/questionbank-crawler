"""
Explore pdf.exambd.net MCQ/Daily GK categories and sattacademy.com job-solution.
"""
import sys, io, re, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def html_to_text(html):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    return soup.get_text(separator="\n", strip=True)


def wp_get(endpoint, params=None):
    r = requests.get(f"https://pdf.exambd.net/wp-json/wp/v2/{endpoint}",
                     headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ── 1. MCQ Corner category (id=23, 15 posts) ─────────────────────────────────
print("=== MCQ Corner posts (cat 23) ===")
posts = wp_get("posts", {"categories": 23, "per_page": 5,
                          "_fields": "id,title,link,content"})
for p in posts:
    txt = html_to_text(p['content']['rendered'])
    print(f"\n  [{p['id']}] {p['title']['rendered']}")
    print(f"  {p['link']}")
    print(f"  {len(txt)} chars")
    print(f"  {txt[:400]}")

# ── 2. Daily GK (cat 20) - get 3 recent posts ─────────────────────────────────
print("\n\n=== Daily GK posts (cat 20, 3 posts) ===")
posts = wp_get("posts", {"categories": 20, "per_page": 3,
                          "_fields": "id,title,link,content"})
for p in posts:
    txt = html_to_text(p['content']['rendered'])
    print(f"\n  [{p['id']}] {p['title']['rendered']}")
    print(f"  {p['link']}")
    print(f"  {len(txt)} chars")
    print(f"  {txt[:600]}")

# ── 3. Job Question (cat 41, 5 posts) ────────────────────────────────────────
print("\n\n=== Job Question posts (cat 41) ===")
posts = wp_get("posts", {"categories": 41, "per_page": 5,
                          "_fields": "id,title,link,content"})
for p in posts:
    txt = html_to_text(p['content']['rendered'])
    print(f"\n  [{p['id']}] {p['title']['rendered']}")
    print(f"  {p['link']}")
    print(f"  {len(txt)} chars | Has MCQ: {bool(re.search(r'ক\)|খ\)|গ\)|ঘ\)|A\)|B\)|C\)|D\)', txt))}")
    print(f"  {txt[:600]}")

# ── 4. Sattacademy job-solution ───────────────────────────────────────────────
print("\n\n=== sattacademy.com/job-solution/ ===")
r = requests.get("https://sattacademy.com/job-solution/", headers=HEADERS, timeout=20)
soup = BeautifulSoup(r.text, "lxml")
for t in soup(["script", "style"]):
    t.decompose()
txt = soup.get_text(separator="\n", strip=True)
print(f"  {len(txt)} chars")
print(txt[:2000])

# Look for BCS-related links
bcs_links = [(a.get_text(strip=True), a['href']) for a in soup.find_all('a', href=True)
             if 'bcs' in a.get_text(strip=True).lower() or 'bcs' in a['href'].lower()]
print(f"\nBCS links on job-solution page: {len(bcs_links)}")
for txt2, href in bcs_links[:10]:
    print(f"  {txt2!r} → {href}")

# ── 5. Sattacademy API discovery ─────────────────────────────────────────────
print("\n\n=== sattacademy.com API discovery ===")
api_paths = [
    "/api/v1/",
    "/api/v1/subjects",
    "/api/v1/jobs",
    "/api/v1/bcs",
    "/api/questions",
    "/api/v2/",
    "/api/exams",
    "/api/job-assistant",
]
for path in api_paths:
    url = f"https://sattacademy.com{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        preview = r.text[:200]
        print(f"  {path} → {r.status_code} | {preview[:100]}")
    except Exception as e:
        print(f"  {path} → ERROR: {e}")
