"""
PDF Handler — downloads PDF files and extracts text from them.
Works on Windows; uses pdfplumber for reliable text extraction.
"""

from __future__ import annotations
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import urllib3
import requests
import pdfplumber

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import PDF_DIR, HEADERS, MAX_PDF_SIZE_MB, REQUEST_TIMEOUT_SEC, REQUEST_DELAY_SEC
from utils import get_logger, ProgressQueue

logger = get_logger("pdf_handler")


class PDFHandler:
    """Download PDFs and extract their text content."""

    def __init__(self, progress_queue: ProgressQueue | None = None):
        self.pq = progress_queue
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ── Download ───────────────────────────────────────────────────────────────

    def download(self, url: str, exam_type: str = "misc") -> Path | None:
        """
        Download a PDF from `url` and save it to PDF_DIR/<exam_type>/.
        Returns the local Path on success, None on failure.
        """
        try:
            # Check file size before full download (HEAD request)
            try:
                head = self.session.head(url, timeout=10, allow_redirects=True)
                content_length = int(head.headers.get("Content-Length", 0))
                if content_length > MAX_PDF_SIZE_MB * 1024 * 1024:
                    logger.warning(f"PDF too large ({content_length // (1024*1024)} MB), skipping: {url}")
                    return None
            except Exception:
                pass  # HEAD not always supported — continue

            resp = self.session.get(url, timeout=REQUEST_TIMEOUT_SEC, stream=True, verify=False)
            resp.raise_for_status()

            # Verify it's actually a PDF via Content-Type header
            content_type = resp.headers.get("Content-Type", "").lower()
            if "pdf" not in content_type and "octet-stream" not in content_type:
                logger.debug(f"Skipping non-PDF response ({content_type}): {url}")
                return None


            # Determine save path
            save_dir = PDF_DIR / exam_type.replace(" ", "_")
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = self._safe_filename(url)
            save_path = save_dir / filename

            if save_path.exists():
                logger.info(f"PDF already exists: {save_path.name}")
                return save_path

            # Stream-download
            downloaded = 0
            chunks = []
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > MAX_PDF_SIZE_MB * 1024 * 1024:
                        logger.warning(f"PDF exceeded size limit while downloading: {url}")
                        return None
                    chunks.append(chunk)

            with open(save_path, "wb") as f:
                for chunk in chunks:
                    f.write(chunk)

            logger.info(f"Downloaded PDF: {save_path.name} ({downloaded // 1024} KB)")
            if self.pq:
                self.pq.put("log", "PDF", f"Downloaded: {save_path.name}")

            time.sleep(REQUEST_DELAY_SEC)
            return save_path

        except requests.RequestException as exc:
            logger.error(f"Failed to download PDF {url}: {exc}")
            if self.pq:
                self.pq.put("error", "PDF", f"Download failed: {url} — {exc}")
            return None

    def download_batch(self, urls: list[str], exam_type: str = "misc") -> list[Path]:
        """Download multiple PDFs. Returns list of successfully saved paths."""
        paths = []
        total = len(urls)
        for i, url in enumerate(urls, 1):
            if self.pq:
                self.pq.put("progress", "PDF",
                            f"Downloading PDF {i}/{total}",
                            percent=(i / total) * 100)
            path = self.download(url, exam_type)
            if path:
                paths.append(path)
        return paths

    # ── Extraction ─────────────────────────────────────────────────────────────

    def extract_text(self, pdf_path: Path) -> str:
        """Extract all text from a PDF file using pdfplumber."""
        try:
            text_parts = []
            with pdfplumber.open(str(pdf_path)) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"Extracting {total_pages} pages from {pdf_path.name}")
                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text() or ""
                    # Also extract tables (common in exam papers)
                    tables = page.extract_tables()
                    table_text = self._tables_to_text(tables)
                    combined = f"--- Page {page_num} ---\n{page_text}\n{table_text}"
                    text_parts.append(combined)
            full_text = "\n\n".join(text_parts)
            logger.info(f"Extracted {len(full_text)} chars from {pdf_path.name}")
            return full_text
        except Exception as exc:
            logger.error(f"Failed to extract text from {pdf_path}: {exc}")
            return ""

    def extract_text_from_url(self, url: str, exam_type: str = "misc") -> tuple[str, Path | None]:
        """Download and extract text. Returns (text, local_path)."""
        path = self.download(url, exam_type)
        if path:
            return self.extract_text(path), path
        return "", None

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_filename(url: str) -> str:
        """Convert a URL to a safe local filename."""
        parsed = urlparse(url)
        name = unquote(parsed.path.split("/")[-1])
        # Remove unsafe characters
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        if not name.endswith(".pdf"):
            name += ".pdf"
        # If name is too generic, add a hash suffix
        if len(name) < 6 or name == ".pdf":
            name = hashlib.md5(url.encode()).hexdigest()[:12] + ".pdf"
        return name

    @staticmethod
    def _tables_to_text(tables: list) -> str:
        if not tables:
            return ""
        lines = []
        for table in tables:
            for row in table:
                if row:
                    lines.append(" | ".join(str(cell or "").strip() for cell in row))
        return "\n".join(lines)

    @staticmethod
    def get_exam_type_from_path(pdf_path: Path) -> str:
        """Infer exam type from the PDF's parent directory name."""
        return pdf_path.parent.name.replace("_", " ")
