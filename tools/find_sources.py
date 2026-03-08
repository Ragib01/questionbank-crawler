"""
Test multiple BD exam question sites to find ones with accessible static HTML content.
"""
import asyncio, sys, io, re, requests
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CANDIDATES = [
    # pdf.exambd.net - WordPress PDF site we saw in the HTML
    ("pdf.exambd.net BCS", "https://pdf.exambd.net/?s=bcs+preliminary"),
    ("pdf.exambd.net category", "https://pdf.exambd.net/category/bcs/"),
    # WordPress REST API for pdf.exambd.net
    ("pdf.exambd.net WP API", "https://pdf.exambd.net/wp-json/wp/v2/posts?search=bcs&per_page=5"),
    # Satta Academy
    ("sattacademy.com home", "https://sattacademy.com/"),
    ("sattacademy.com bcs", "https://sattacademy.com/bcs/"),
    ("sattacademy.com exam", "https://sattacademy.com/exam/bcs"),
    # BCS question bank sites
    ("bcsquestionbank.com", "https://www.bcsquestionbank.com/"),
    ("bcspreli.com", "https://www.bcspreli.com/"),
    # Study press
    ("studypress.net", "https://studypress.net/"),
    ("studypress.net bcs", "https://studypress.net/bcs-preli/"),
    # Others
    ("jobtestbd.com", "https://jobtestbd.com/"),
    ("jobtestbd.com bcs", "https://jobtestbd.com/bcs-preliminary-question/"),
    ("examtray.com bd", "https://www.examtray.com/bcs"),
    ("prepeasy.com", "https://prepeasy.com/"),
    # Edu sites with static pages
    ("bdjobsinfo.com bcs", "https://www.bdjobsinfo.com/bcs-question/"),
    ("allbdresult.com", "https://www.allbdresult.com/bcs-question/"),
]


def test_url(name, url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        final = r.url
        ct = r.headers.get("Content-Type", "")
        text = r.text[:3000]

        # Check if it's real content
        word_count = len(re.findall(r'\w+', text))
        has_question = bool(re.search(r'question|mcq|bcs|answer|exam', text, re.I))
        has_bengali = bool(re.search(r'[\u0980-\u09FF]', text))

        print(f"\n[{name}]")
        print(f"  URL: {url}")
        print(f"  Final: {final}")
        print(f"  Status: {r.status_code} | CT: {ct[:50]}")
        print(f"  Words: {word_count} | Has question kw: {has_question} | Has Bengali: {has_bengali}")

        if r.status_code == 200 and word_count > 100:
            # Show a snippet of meaningful text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "lxml")
            for t in soup(["script", "style", "nav"]):
                t.decompose()
            clean = soup.get_text(separator=" ", strip=True)
            print(f"  Text snippet: {clean[:300]}")
            return True
    except Exception as e:
        print(f"\n[{name}] FAILED: {e}")
    return False


if __name__ == "__main__":
    working = []
    for name, url in CANDIDATES:
        ok = test_url(name, url)
        if ok:
            working.append((name, url))

    print(f"\n\n{'='*60}")
    print(f"WORKING SITES ({len(working)}):")
    for name, url in working:
        print(f"  {name}: {url}")
