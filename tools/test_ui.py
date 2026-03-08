"""
Quick smoke-test of the running Streamlit app via HTTP.
Checks the app is up and key elements are present.
"""
import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8501"

checks = [
    ("/",              200, "BD Govt Question Bank Crawler"),
    ("/healthz",       200, None),
]

all_ok = True
for path, expected_status, expected_text in checks:
    try:
        r = requests.get(BASE + path, timeout=10)
        status_ok = r.status_code == expected_status
        text_ok   = (expected_text is None) or (expected_text in r.text)
        ok = status_ok and text_ok
        print(f"{'✅' if ok else '❌'} GET {path}  →  {r.status_code}  text_match={text_ok}")
        if not ok:
            all_ok = False
    except Exception as e:
        print(f"❌ GET {path} → ERROR: {e}")
        all_ok = False

# Verify MongoDB has data
import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
from storage.mongo_store import MongoStore
store = MongoStore()
stats = store.get_stats()
print(f"\n📊 MongoDB stats:")
print(f"   total_exams:     {stats['total_exams']}")
print(f"   total_questions: {stats['total_questions']}")
print(f"   by_exam_type:    {stats['by_exam_type']}")

sessions = store.get_recent_sessions(3)
print(f"\n🕐 Recent crawl sessions: {len(sessions)}")
for s in sessions:
    print(f"   {s.get('url','')[:60]}  pages={s.get('pages_crawled')}  q={s.get('questions_saved')}")

index = store.load_index()
print(f"\n📖 Exam index ({len(index)} records):")
for e in index[:5]:
    print(f"   {e['exam_type']:20s} | {e['exam_name'][:40]:40s} | {e['question_count']} questions")

# Search test
results = store.search("কোচ")
print(f"\n🔍 Search 'কোচ' → {len(results)} results")
if results:
    q = results[0]['matched_question']
    print(f"   Q: {q['question'][:60]}")
    print(f"   A: {q['answer']}")

print(f"\n{'✅ App & MongoDB OK' if all_ok and stats['total_questions'] > 0 else '❌ Issues found'}")
