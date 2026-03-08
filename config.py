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
# Each entry: name, url, type (html | pdf_index), exam_type, pdf_patterns (optional)
CRAWL_TARGETS = {
    "BCS": [
        {
            "name": "BPSC Official Question Papers",
            "url": "https://www.bpsc.gov.bd/site/page/b0e2c6d9-e21e-40c4-a823-3a86c041c5e2/-",
            "type": "html",
            "notes": "Official BPSC question archive",
        },
        {
            "name": "BCS Question Bank (ExamBD)",
            "url": "https://www.exambd.net/bcs/",
            "type": "html",
            "notes": "BCS exam question archive",
        },
        {
            "name": "BCS Preliminary Questions (StudyPress)",
            "url": "https://studypress.net/bcs-question-bank/",
            "type": "html",
            "notes": "BCS question bank",
        },
        {
            "name": "BCS Questions (BD Jobs Today)",
            "url": "https://www.bdjobstoday.info/category/bcs-question/",
            "type": "html",
            "notes": "BCS question papers",
        },
        {
            "name": "Satt Academy BCS",
            "url": "https://sattacademy.com/job-solution/bcs",
            "type": "html",
            "notes": "BCS solution archive",
        },
    ],
    "Bank": [
        {
            "name": "Bangladesh Bank Recruitment",
            "url": "https://erecruitment.bb.org.bd/",
            "type": "html",
            "notes": "Bangladesh Bank official recruitment",
        },
        {
            "name": "Bank Exam Questions (ExamBD)",
            "url": "https://www.exambd.net/bank/",
            "type": "html",
            "notes": "Bank job exam questions",
        },
        {
            "name": "Bank MCQ (BD Jobs Today)",
            "url": "https://www.bdjobstoday.info/category/bank-question/",
            "type": "html",
            "notes": "Bank exam question papers",
        },
    ],
    "Ministry": [
        {
            "name": "BPSC Non-Cadre / Ministry",
            "url": "https://www.bpsc.gov.bd/site/view/noncadre_job_circular",
            "type": "html",
            "notes": "Ministry and govt dept exam questions",
        },
        {
            "name": "Ministry Questions (ExamBD)",
            "url": "https://www.exambd.net/ministry/",
            "type": "html",
            "notes": "Govt ministry exam questions",
        },
        {
            "name": "Ministry Jobs (BD Jobs Today)",
            "url": "https://www.bdjobstoday.info/category/ministry-question/",
            "type": "html",
            "notes": "Ministry job question papers",
        },
    ],
    "Primary Teacher": [
        {
            "name": "DPE Official",
            "url": "https://dpe.gov.bd/",
            "type": "html",
            "notes": "Directorate of Primary Education",
        },
        {
            "name": "Primary Teacher Questions (ExamBD)",
            "url": "https://www.exambd.net/primary/",
            "type": "html",
            "notes": "Primary teacher exam questions",
        },
        {
            "name": "Primary Exam (BD Jobs Today)",
            "url": "https://www.bdjobstoday.info/category/primary-question/",
            "type": "html",
            "notes": "Primary teacher question papers",
        },
    ],
    "NTRCA": [
        {
            "name": "NTRCA Official",
            "url": "https://ntrca.gov.bd/",
            "type": "html",
            "notes": "NTRCA official site",
        },
        {
            "name": "NTRCA Questions (ExamBD)",
            "url": "https://www.exambd.net/ntrca/",
            "type": "html",
            "notes": "NTRCA exam questions",
        },
        {
            "name": "NTRCA Question Papers (BD Jobs Today)",
            "url": "https://www.bdjobstoday.info/category/ntrca-question/",
            "type": "html",
            "notes": "NTRCA question papers",
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
