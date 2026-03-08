"""
Quick end-to-end test: crawl BCS WP API posts + AI extract + save JSON.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from utils import ProgressQueue
from crawler.wp_api_crawler import WPAPICrawler
from processors.ai_extractor import AIExtractor
from storage.store import QuestionStore
from config import CRAWL_TARGETS

pq = ProgressQueue()

# Crawl just the first BCS WP API target (MCQ Corner)
bcs_targets = CRAWL_TARGETS["BCS"][:1]  # Just first target
print(f"Testing with target: {bcs_targets[0]['name']}")
print(f"Base URL: {bcs_targets[0]['base_url']}")
print()

crawler = WPAPICrawler(pq)
records = crawler.crawl("BCS", bcs_targets)

print(f"\nCrawled {len(records)} records")
for r in records[:3]:
    print(f"\n  [{r['page_url']}]")
    print(f"  Year: {r['year']}")
    print(f"  Text length: {len(r['raw_text'])}")
    print(f"  Text preview: {r['raw_text'][:300]}")
    print(f"  PDF links: {r['pdf_links']}")

# Drain progress queue
msgs = pq.get_all()
for m in msgs:
    print(f"  [PQ] {m}")

if not records:
    print("\nNo records found! Check connectivity to pdf.exambd.net")
    sys.exit(1)

# AI extract first 3 records
print(f"\n{'='*60}")
print("Running AI extraction on first 3 records...")
extractor = AIExtractor(pq)
structured = extractor.extract_batch(records[:3])

print(f"\nExtracted {len(structured)} structured records")
for s in structured:
    print(f"\n  Exam: {s['exam_name']} ({s['year']})")
    print(f"  Subject: {s['subject']}")
    print(f"  Questions: {len(s['questions'])}")
    for q in s['questions'][:2]:
        print(f"    Q{q['q_no']}: {q['question'][:80]}")
        print(f"    Opts: {list(q['options'].values())[:2]}")
        print(f"    Answer: {q['answer']}")

# Save to store
if structured:
    print(f"\n{'='*60}")
    print("Saving to question store...")
    store = QuestionStore()
    for s in structured:
        store.save(s)
    print(f"Saved {len(structured)} records")
    print(f"Total in store: {store.count()}")

print("\nTest complete.")
