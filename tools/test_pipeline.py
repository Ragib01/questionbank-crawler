"""
End-to-end pipeline test that mirrors exactly what the Streamlit UI does.
Crawl URL → AI extract → Save to MongoDB → Verify.
"""
import sys, io, os, warnings
warnings.filterwarnings("ignore")
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from utils import ProgressQueue
from crawler.url_crawler import URLCrawler
from processors.ai_extractor import AIExtractor
from storage.mongo_store import MongoStore
from config import AI_MODEL_FAST

TEST_URL   = "https://pdf.exambd.net/2024/11/daily-mcq-6-november-2024.html"
EXAM_TYPE  = "BCS"
MAX_PAGES  = 1

print("=" * 60)
print("STEP 1 — MongoDB connectivity")
store = MongoStore()
print(f"  ping: {store.ping()}")
stats_before = store.get_stats()
print(f"  before: {stats_before['total_questions']} questions in DB")

print()
print("STEP 2 — Crawl URL")
pq = ProgressQueue()
crawler = URLCrawler(pq, use_playwright=False)
crawl_out = crawler.crawl(
    start_url=TEST_URL,
    exam_type=EXAM_TYPE,
    max_pages=MAX_PAGES,
    download_pdfs=False,
    download_images=False,
)
raw_records = crawl_out["raw_records"]
print(f"  raw_records: {len(raw_records)}")
for r in raw_records:
    print(f"  → {r['page_url'][:70]}  ({len(r['raw_text'])} chars)")

# drain pq
for m in pq.get_all():
    print(f"  [PQ] {m['type']} | {m['source']} | {m['message'][:80]}")

if not raw_records:
    print("  ERROR: No pages crawled. Aborting.")
    sys.exit(1)

print()
print("STEP 3 — AI extraction")
extractor = AIExtractor(pq, model=AI_MODEL_FAST)
structured = extractor.extract_batch(raw_records)
print(f"  structured records: {len(structured)}")
for s in structured:
    q_count = len(s.get("questions", []))
    print(f"  → {s['exam_name']} ({s['year']})  — {q_count} questions")
    if s.get("questions"):
        q = s["questions"][0]
        print(f"     Sample Q1: {q['question'][:70]}")
        print(f"     Answer: {q['answer']}")

for m in pq.get_all():
    if m["type"] in ("error", "log"):
        print(f"  [PQ] {m['type']} | {m['source']} | {m['message'][:80]}")

if not structured:
    print("  ERROR: AI returned no structured records. Check API key.")
    sys.exit(1)

print()
print("STEP 4 — Save to MongoDB")
saved_ids = store.save_batch(structured)
print(f"  saved exam IDs: {saved_ids}")

session_id = store.save_session({
    "url":             TEST_URL,
    "exam_type":       EXAM_TYPE,
    "max_pages":       MAX_PAGES,
    "pages_crawled":   len(raw_records),
    "exams_saved":     len(saved_ids),
    "questions_saved": sum(len(s.get("questions", [])) for s in structured),
    "pdf_paths":       [],
    "image_paths":     [],
    "test_run":        True,
})
print(f"  session saved: {session_id}")

print()
print("STEP 5 — Verify in MongoDB")
stats_after = store.get_stats()
print(f"  total_exams:     {stats_after['total_exams']}")
print(f"  total_questions: {stats_after['total_questions']}")
print(f"  by_exam_type:    {stats_after['by_exam_type']}")
print(f"  delta questions: {stats_after['total_questions'] - stats_before['total_questions']} new")

# Fetch back and confirm
if saved_ids:
    record = store.get_exam(saved_ids[0])
    if record:
        print(f"\n  Fetched back: {record['exam_name']} — {len(record['questions'])} questions ✅")
    else:
        print("  ERROR: Could not fetch back saved record!")

print()
print("=" * 60)
print("ALL STEPS PASSED ✅" if saved_ids else "FAILED ❌")
