"""Debug WP API calls."""
import sys, io, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://pdf.exambd.net/wp-json/wp/v2/posts"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def try_query(label, params):
    r = requests.get(BASE, headers=HEADERS, params=params, timeout=20)
    try:
        data = r.json()
        count = len(data) if isinstance(data, list) else "error"
    except Exception:
        data = r.text[:200]
        count = "parse_err"
    print(f"[{label}] status={r.status_code} count={count}")
    if isinstance(data, list) and data:
        print(f"  First: {data[0].get('title', {}).get('rendered', '?')[:60]}")
    elif isinstance(data, dict) and 'message' in data:
        print(f"  Error: {data['message']}")

try_query("cat23 only", {"categories": 23, "per_page": 5})
try_query("cat23 + search=bcs", {"categories": 23, "search": "bcs", "per_page": 5})
try_query("cat23 + search=mcq", {"categories": 23, "search": "mcq", "per_page": 5})
try_query("search=bcs only", {"search": "bcs", "per_page": 5})
try_query("cat26 only", {"categories": 26, "per_page": 5})
try_query("cat20 only", {"categories": 20, "per_page": 5})
try_query("cat19 only", {"categories": 19, "per_page": 5})
try_query("cat41 only", {"categories": 41, "per_page": 5})
try_query("search=bank", {"search": "bank", "per_page": 5})
try_query("search=ntrca", {"search": "ntrca", "per_page": 5})
try_query("all posts p1", {"per_page": 5, "page": 1, "_fields": "id,title"})
