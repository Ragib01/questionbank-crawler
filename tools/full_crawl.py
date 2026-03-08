"""
Full crawl: all exam types via the CrawlerManager + AI extraction + save.
"""
import sys, io, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from utils import ProgressQueue
from crawler import CrawlerManager
from processors.ai_extractor import AIExtractor
from processors.pdf_handler import PDFHandler
from storage.store import QuestionStore
from config import EXAM_TYPES

pq = ProgressQueue()
store = QuestionStore()

print("Starting full crawl for all exam types...")
print(f"Exam types: {EXAM_TYPES}")
print()

mgr = CrawlerManager(
    pq,
    exam_types=EXAM_TYPES,
    use_playwright=False,   # WP API doesn't need Playwright
    download_pdfs=False,    # Skip PDFs for speed
)
mgr.start()

# Wait + print progress
while mgr.is_running():
    msgs = pq.get_all()
    for m in msgs:
        t = m.get("type", "")
        src = m.get("source", "")
        msg = m.get("message", "")
        pct = m.get("percent", 0)
        if t in ("progress", "log", "error", "done"):
            pct_str = f" [{pct:.0f}%]" if pct else ""
            print(f"[{t.upper()}] {src}{pct_str}: {msg}")
    time.sleep(1)

# Final messages
for m in pq.get_all():
    t = m.get("type", "")
    src = m.get("source", "")
    msg = m.get("message", "")
    print(f"[{t.upper()}] {src}: {msg}")

raw_records = mgr.get_results()
print(f"\n{'='*60}")
print(f"Total raw records collected: {len(raw_records)}")

if not raw_records:
    print("No records! Exiting.")
    sys.exit(1)

# AI extraction
print(f"\nStarting AI extraction ({len(raw_records)} records)...")
extractor = AIExtractor(pq)
structured = extractor.extract_batch(raw_records)

# Print AI progress messages
for m in pq.get_all():
    t = m.get("type", "")
    src = m.get("source", "")
    msg = m.get("message", "")
    if t in ("progress", "error"):
        print(f"[{t.upper()}] {src}: {msg}")

print(f"\nExtracted {len(structured)} structured records")
usage = extractor.usage_stats
print(f"API calls: {usage['api_calls']}, approx tokens: {usage['approx_tokens']}")

# Save
paths = store.save_batch(structured)
print(f"\nSaved {len(paths)} files")

# Stats
stats = store.get_stats()
print(f"\n{'='*60}")
print(f"QUESTION BANK STATS:")
print(f"  Total exams:     {stats['total_exams']}")
print(f"  Total questions: {stats['total_questions']}")
print(f"  By exam type:    {stats['by_exam_type']}")
print(f"  By year:         {dict(list(stats['by_year'].items())[:5])}")
print(f"\nDone! Run the Streamlit app to browse questions.")
