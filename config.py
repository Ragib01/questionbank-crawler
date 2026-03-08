import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
OUTPUT_DIR     = BASE_DIR / "output"
PDF_DIR        = OUTPUT_DIR / "pdfs"
QUESTIONS_DIR  = OUTPUT_DIR / "questions"
LOGS_DIR       = OUTPUT_DIR / "logs"

for _d in [OUTPUT_DIR, PDF_DIR, QUESTIONS_DIR, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── API Keys ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── AI Models ─────────────────────────────────────────────────────────────────
AI_MODEL_FAST   = "claude-haiku-4-5-20251001"   # cheap, fast — for bulk extraction
AI_MODEL_SMART  = "claude-sonnet-4-6"            # smarter — for tricky pages

# ── Crawler Settings ──────────────────────────────────────────────────────────
REQUEST_DELAY_SEC   = 1.5     # polite delay between requests
MAX_PAGES_PER_SITE  = 30
MAX_PDF_SIZE_MB     = 50
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES         = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

# ── Exam Types ─────────────────────────────────────────────────────────────────
EXAM_TYPES = ["BCS", "Bank", "Ministry", "Primary Teacher", "NTRCA"]

# ── Crawl Targets ──────────────────────────────────────────────────────────────
# Source: pdf.exambd.net (WordPress site with REST API)
# Category IDs: mcq-corner=23, daily-gk=20, monthly-gk=26, general-knowledge=19,
#               job-solution-pdf=11, job-question=41, daily-exam=69
#
# type="wp_api"  → uses WPAPICrawler (WordPress REST API)
# type="html"    → uses domain-specific HTML crawlers (legacy)

EXAMBD_PDF_BASE = "https://pdf.exambd.net"

CRAWL_TARGETS = {
    # BCS pulls from MCQ Corner (structured MCQ) + Monthly GK (comprehensive sets)
    "BCS": [
        {
            "name": "MCQ Corner — Current Affairs MCQ",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 23,   # mcq-corner — daily/weekly/monthly MCQ posts
            "per_page": 10,
            "max_pages": 3,
            "notes": "MCQ posts with a/b/c/d options and answers",
        },
        {
            "name": "Monthly GK — Comprehensive MCQ",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 26,   # monthly-gk
            "per_page": 5,
            "max_pages": 2,
            "notes": "Monthly comprehensive MCQ/GK posts",
        },
    ],
    # Bank pulls from Job Question category (actual job solution posts) + MCQ Corner
    "Bank": [
        {
            "name": "Job Question — Bank Solutions",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 41,   # job-question
            "per_page": 5,
            "max_pages": 2,
            "notes": "Bank job solution posts",
        },
        {
            "name": "MCQ Corner — Current Affairs",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 23,   # mcq-corner
            "per_page": 8,
            "max_pages": 2,
            "notes": "MCQ questions relevant for bank exams",
        },
    ],
    # Ministry pulls from General Knowledge + MCQ Corner
    "Ministry": [
        {
            "name": "General Knowledge — Q&A",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 19,   # general-knowledge
            "per_page": 8,
            "max_pages": 2,
            "notes": "GK Q&A posts relevant for ministry exams",
        },
        {
            "name": "MCQ Corner — Current Affairs",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 23,   # mcq-corner
            "per_page": 8,
            "max_pages": 2,
            "notes": "MCQ questions for ministry exams",
        },
    ],
    # Primary Teacher pulls from Daily GK + MCQ Corner
    "Primary Teacher": [
        {
            "name": "Daily GK — Q&A",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 20,   # daily-gk
            "per_page": 8,
            "max_pages": 2,
            "notes": "Daily GK Q&A for primary teacher prep",
        },
        {
            "name": "MCQ Corner — Current Affairs",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 23,   # mcq-corner
            "per_page": 8,
            "max_pages": 2,
            "notes": "MCQ questions for primary teacher exams",
        },
    ],
    # NTRCA pulls from Job Question + Daily GK
    "NTRCA": [
        {
            "name": "Job Question — NTRCA Solutions",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 41,   # job-question
            "per_page": 5,
            "max_pages": 2,
            "notes": "NTRCA job solution posts",
        },
        {
            "name": "Daily GK — Q&A",
            "base_url": EXAMBD_PDF_BASE,
            "type": "wp_api",
            "category_id": 20,   # daily-gk
            "per_page": 8,
            "max_pages": 2,
            "notes": "Daily GK Q&A for NTRCA prep",
        },
    ],
}

# ── JSON Output Schema (reference) ────────────────────────────────────────────
QUESTION_SCHEMA = {
    "exam_id": "str — e.g. BCS_44_2023",
    "exam_type": "BCS | Bank | Ministry | Primary Teacher | NTRCA",
    "exam_name": "str — full exam name",
    "year": "int",
    "subject": "str",
    "source_url": "str",
    "pdf_path": "str | null",
    "crawled_at": "ISO datetime str",
    "ai_processed": "bool",
    "questions": [
        {
            "q_no": "int",
            "question": "str",
            "options": {"A": "str", "B": "str", "C": "str", "D": "str"},
            "answer": "A|B|C|D | str",
            "explanation": "str",
            "topic": "str",
        }
    ],
}
