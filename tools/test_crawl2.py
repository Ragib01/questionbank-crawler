"""Crawl a few more pages to build up the question bank."""
import sys, io, os, warnings
warnings.filterwarnings("ignore")
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from utils import ProgressQueue
from crawler.url_crawler import URLCrawler
from processors.ai_extractor import AIExtractor
from storage.mongo_store import MongoStore
from config import AI_MODEL_FAST

TESTS = [
    ("https://pdf.exambd.net/2024/11/weekly-mcq-1-november-2024.html",  "BCS",  1),
    ("https://pdf.exambd.net/2025/04/monthly-mcq-questions-and-answers-april-2025.html", "BCS", 1),
    ("https://pdf.exambd.net/2024/11/daily-mcq-5-november-2024.html",   "Bank", 1),
]

store = MongoStore()
total_saved = 0

for url, exam_type, max_pages in TESTS:
    print(f"\n{'─'*60}")
    print(f"Crawling [{exam_type}]: {url[:70]}")
    pq = ProgressQueue()
    crawler = URLCrawler(pq, use_playwright=False)
    crawl_out = crawler.crawl(url, exam_type=exam_type,
                               max_pages=max_pages, download_pdfs=False)

    if not crawl_out["raw_records"]:
        print("  No content — skipped")
        continue

    extractor = AIExtractor(pq, model=AI_MODEL_FAST)
    structured = extractor.extract_batch(crawl_out["raw_records"])
    if not structured:
        print("  AI returned nothing — skipped")
        continue

    saved_ids = store.save_batch(structured)
    q_count = sum(len(s.get("questions", [])) for s in structured)
    total_saved += q_count
    print(f"  ✅ {len(saved_ids)} records, {q_count} questions saved")
    for s in structured:
        print(f"     {s['exam_name']} ({s['year']}) — {len(s.get('questions',[]))} questions")

print(f"\n{'='*60}")
stats = store.get_stats()
print(f"Total in MongoDB: {stats['total_exams']} exams, {stats['total_questions']} questions")
print(f"By type: {stats['by_exam_type']}")
print(f"By year: {dict(list(stats['by_year'].items())[:4])}")
