"""
URL Crawler — crawl a user-supplied URL (+ sub-pages, PDFs, images).
Uses threading.Queue + worker pool for robust concurrent fetching.
"""
from __future__ import annotations
import os
import re
import time
import hashlib
import queue
import threading
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC, OUTPUT_DIR
from utils import get_logger, ProgressQueue
from .base_crawler import BaseCrawler

logger = get_logger("url_crawler")

IMAGE_DIR = OUTPUT_DIR / "images"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}

_RETRY_DELAYS = [1, 3, 7]   # seconds between retries (exponential-ish)


class URLCrawler:
    """
    Crawls a starting URL + same-domain subpages.
    Uses a threading.Queue + worker pool for concurrent, rate-limited fetching.
    Retries failed pages up to 3 times with backoff.
    """

    def __init__(
        self,
        progress_queue: ProgressQueue,
        use_playwright: bool = True,
        concurrency: int = 3,
    ):
        self.pq = progress_queue
        self.base = BaseCrawler(use_playwright=use_playwright)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        # Playwright is single-threaded — cap concurrency at 1 when using it
        self.concurrency = 1 if use_playwright else max(1, concurrency)

    # ── Public API ─────────────────────────────────────────────────────────────

    def crawl(
        self,
        start_url: str,
        exam_type: str = "General",
        max_pages: int = 10,
        download_pdfs: bool = True,
        download_images: bool = False,
    ) -> dict:
        """
        Crawl `start_url` and its sub-pages up to `max_pages`.

        Returns:
            {
              "raw_records": list[dict],   # text content per page
              "pdf_paths":   list[str],    # downloaded PDF file paths
              "image_paths": list[str],    # downloaded image file paths
            }
        """
        self.pq.put("log", "Crawler", f"Starting crawl: {start_url}")
        self.pq.put("log", "Crawler",
                    f"Settings: max_pages={max_pages}, pdfs={download_pdfs}, "
                    f"images={download_images}, workers={self.concurrency}")

        # ── Shared state (all protected by locks) ──────────────────────────
        work_queue: "queue.Queue[str | None]" = queue.Queue()
        visited_lock  = threading.Lock()
        results_lock  = threading.Lock()
        rate_lock     = threading.Lock()

        visited:      set[str]         = set()
        raw_records:  list[dict]       = []
        all_pdf_urls: list[tuple]      = []   # (url, exam_type)
        all_image_urls: list[str]      = []
        # per-domain last-request timestamp
        domain_last: dict[str, float]  = defaultdict(float)

        done_event = threading.Event()   # set when crawl limit is reached

        work_queue.put(self._normalize_url(start_url))

        # ── Worker ────────────────────────────────────────────────────────
        def worker():
            while not done_event.is_set():
                try:
                    url = work_queue.get(timeout=2)
                except Exception:
                    # Queue empty — check if we should stop
                    if work_queue.empty():
                        break
                    continue

                if url is None:   # poison pill
                    work_queue.task_done()
                    break

                # Skip if already visited or limit reached
                with visited_lock:
                    if url in visited:
                        work_queue.task_done()
                        continue
                    with results_lock:
                        if len(visited) >= max_pages:
                            done_event.set()
                            work_queue.task_done()
                            break
                    visited.add(url)
                    page_num = len(visited)

                self.pq.put("progress", "Crawler",
                            f"Fetching page {page_num}/{max_pages}: {url[:80]}",
                            percent=(page_num / max_pages) * 100)

                # Per-domain rate limiting
                domain = urlparse(url).netloc
                with rate_lock:
                    elapsed = time.time() - domain_last[domain]
                    wait    = REQUEST_DELAY_SEC - elapsed
                    if wait > 0:
                        time.sleep(wait)
                    domain_last[domain] = time.time()

                # Fetch with retry
                result = self._fetch_with_retry(url)

                if not result or not result.success:
                    self.pq.put("log", "Crawler", f"  ✗ Failed (all retries): {url}")
                    work_queue.task_done()
                    continue

                if len(result.markdown) < 100:
                    self.pq.put("log", "Crawler",
                                f"  ✗ Too short ({len(result.markdown)} chars): {url}")
                    work_queue.task_done()
                    continue

                self.pq.put("log", "Crawler",
                            f"  ✓ {len(result.markdown)} chars, "
                            f"{len(result.pdf_links)} PDFs — {url[:70]}")

                record = {
                    "exam_type":   exam_type,
                    "source_name": self._page_title(result.html) or urlparse(url).netloc,
                    "source_url":  start_url,
                    "page_url":    url,
                    "raw_text":    result.markdown,
                    "pdf_links":   result.pdf_links,
                    "year":        self._extract_year(url + " " + result.markdown[:300]),
                }

                with results_lock:
                    raw_records.append(record)
                    if download_pdfs:
                        for pdf_url in result.pdf_links:
                            all_pdf_urls.append((pdf_url, exam_type))
                    if download_images:
                        all_image_urls.extend(
                            self._extract_image_urls(result.html, url)
                        )

                # Enqueue sub-links (same domain)
                with visited_lock:
                    remaining = max_pages - len(visited)

                if remaining > 0:
                    sub_links = self.base.get_same_domain_links(result.html, url)
                    for link in sub_links:
                        norm = self._normalize_url(link)
                        with visited_lock:
                            if norm not in visited:
                                work_queue.put(norm)

                work_queue.task_done()

        # ── Launch worker pool ────────────────────────────────────────────
        threads = [
            threading.Thread(target=worker, daemon=True, name=f"crawler-{i}")
            for i in range(self.concurrency)
        ]
        for t in threads:
            t.start()

        # Wait for work to drain or limit to be hit
        work_queue.join()
        done_event.set()   # signal any still-running workers to stop

        # Send poison pills to unblock threads blocked on queue.get()
        for _ in threads:
            work_queue.put(None)
        for t in threads:
            t.join(timeout=5)

        self.pq.put("log", "Crawler",
                    f"Crawl done. Pages: {len(raw_records)} | "
                    f"PDFs found: {len(all_pdf_urls)} | "
                    f"Images found: {len(all_image_urls)}")

        # ── Download PDFs ─────────────────────────────────────────────────
        pdf_paths: list[str] = []
        if download_pdfs and all_pdf_urls:
            self.pq.put("log", "Crawler", f"Downloading {len(all_pdf_urls)} PDFs...")
            from processors.pdf_handler import PDFHandler
            handler = PDFHandler(self.pq)
            for pdf_url, etype in all_pdf_urls:
                path = handler.download(pdf_url, etype)
                if path:
                    pdf_paths.append(str(path))
                    self.pq.put("log", "Crawler", f"  PDF saved: {Path(path).name}")

        # ── Download images ────────────────────────────────────────────────
        image_paths: list[str] = []
        if download_images and all_image_urls:
            unique_imgs = list(dict.fromkeys(all_image_urls))[:100]
            self.pq.put("log", "Crawler", f"Downloading {len(unique_imgs)} images...")
            domain = urlparse(start_url).netloc.replace(".", "_")
            img_dir = IMAGE_DIR / domain
            img_dir.mkdir(parents=True, exist_ok=True)
            for img_url in unique_imgs:
                path = self._download_image(img_url, img_dir)
                if path:
                    image_paths.append(path)
            self.pq.put("log", "Crawler", f"  {len(image_paths)} images saved")

        self.pq.put("done", "Crawler",
                    f"Complete. {len(raw_records)} pages, "
                    f"{len(pdf_paths)} PDFs, {len(image_paths)} images")

        return {
            "raw_records":  raw_records,
            "pdf_paths":    pdf_paths,
            "image_paths":  image_paths,
        }

    # ── Fetch with retry ───────────────────────────────────────────────────────

    def _fetch_with_retry(self, url: str):
        """Fetch a URL with up to 3 retries and exponential backoff."""
        last_err = None
        for attempt, delay in enumerate([0] + _RETRY_DELAYS, start=1):
            if delay:
                logger.debug(f"Retry {attempt} for {url} after {delay}s")
                time.sleep(delay)
            try:
                result = self.base.fetch(url)
                if result.success:
                    return result
                last_err = f"fetch returned success=False"
            except Exception as exc:
                last_err = str(exc)
                logger.warning(f"Fetch attempt {attempt} failed for {url}: {exc}")
        logger.error(f"All retries exhausted for {url}: {last_err}")
        return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Remove fragment, trailing slash, and lowercase scheme+host."""
        url, _ = urldefrag(url)
        parsed  = urlparse(url)
        # lowercase scheme and host, preserve path case
        return parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
        ).geturl().rstrip("/") or url

    @staticmethod
    def _page_title(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        title = soup.find("title")
        return title.get_text(strip=True)[:80] if title else ""

    @staticmethod
    def _extract_year(text: str):
        m = re.search(r"\b(20\d{2})\b", text)
        return int(m.group()) if m else None

    @staticmethod
    def _extract_image_urls(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for tag in soup.find_all(["img", "source"], src=True):
            src = tag.get("src", "") or tag.get("srcset", "").split(",")[0].strip().split()[0]
            if not src:
                continue
            full = urljoin(base_url, src)
            ext  = Path(urlparse(full).path).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                urls.append(full)
        return list(dict.fromkeys(urls))

    def _download_image(self, url: str, save_dir: Path) -> str | None:
        try:
            r = self.session.get(url, timeout=15, stream=True, allow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "")
            if "image" not in ct:
                return None
            ext      = Path(urlparse(url).path).suffix.lower() or ".jpg"
            filename = hashlib.md5(url.encode()).hexdigest()[:12] + ext
            path     = save_dir / filename
            if path.exists():
                return str(path)
            with open(path, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            return str(path)
        except Exception as exc:
            logger.debug(f"Image download failed {url}: {exc}")
            return None
