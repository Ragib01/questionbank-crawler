"""
URL Crawler — crawl a user-supplied URL (+ sub-pages, PDFs, images).
General-purpose; works for any website.
"""
from __future__ import annotations
import os
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC, OUTPUT_DIR
from utils import get_logger, ProgressQueue
from .base_crawler import BaseCrawler

logger = get_logger("url_crawler")

IMAGE_DIR = OUTPUT_DIR / "images"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


class URLCrawler:
    """
    Crawls a starting URL + same-domain subpages.
    Optionally downloads PDFs and images.
    """

    def __init__(self, progress_queue: ProgressQueue, use_playwright: bool = True):
        self.pq = progress_queue
        self.base = BaseCrawler(use_playwright=use_playwright)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

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
        Crawl `start_url` and its sub-pages.

        Returns:
            {
              "raw_records": list[dict],   # text content per page
              "pdf_paths":   list[str],    # downloaded PDF file paths
              "image_paths": list[str],    # downloaded image file paths
            }
        """
        self.pq.put("log", "Crawler", f"Starting crawl: {start_url}")
        self.pq.put("log", "Crawler", f"Settings: max_pages={max_pages}, "
                                       f"pdfs={download_pdfs}, images={download_images}")

        visited: set[str] = set()
        raw_records: list[dict] = []
        all_pdf_urls: list[tuple[str, str]] = []   # (url, exam_type)
        all_image_urls: list[str] = []

        # Queue of URLs to visit
        queue = [start_url]

        while queue and len(visited) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            page_num = len(visited)
            self.pq.put("progress", "Crawler",
                        f"Fetching page {page_num}/{max_pages}: {url[:80]}",
                        percent=(page_num / max_pages) * 100)

            result = self.base.fetch(url)
            if not result.success:
                self.pq.put("log", "Crawler", f"  ✗ Failed: {url}")
                continue

            if len(result.markdown) < 100:
                self.pq.put("log", "Crawler", f"  ✗ Too short ({len(result.markdown)} chars): {url}")
                continue

            self.pq.put("log", "Crawler",
                        f"  ✓ {len(result.markdown)} chars, {len(result.pdf_links)} PDFs — {url[:70]}")

            raw_records.append({
                "exam_type":   exam_type,
                "source_name": self._page_title(result.html) or urlparse(url).netloc,
                "source_url":  start_url,
                "page_url":    url,
                "raw_text":    result.markdown,
                "pdf_links":   result.pdf_links,
                "year":        self._extract_year(url + " " + result.markdown[:300]),
            })

            # Collect PDF URLs
            if download_pdfs:
                for pdf_url in result.pdf_links:
                    all_pdf_urls.append((pdf_url, exam_type))

            # Collect image URLs
            if download_images:
                img_urls = self._extract_image_urls(result.html, url)
                all_image_urls.extend(img_urls)

            # Enqueue sub-links (same domain only)
            if len(visited) < max_pages:
                sub_links = self.base.get_same_domain_links(result.html, url)
                for link in sub_links:
                    if link not in visited and link not in queue:
                        queue.append(link)

        self.pq.put("log", "Crawler",
                    f"Crawl done. Pages: {len(raw_records)} | "
                    f"PDFs found: {len(all_pdf_urls)} | Images found: {len(all_image_urls)}")

        # Download PDFs
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

        # Download images
        image_paths: list[str] = []
        if download_images and all_image_urls:
            unique_imgs = list(dict.fromkeys(all_image_urls))[:100]  # cap at 100
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
                    f"Complete. {len(raw_records)} pages, {len(pdf_paths)} PDFs, "
                    f"{len(image_paths)} images")

        return {
            "raw_records":  raw_records,
            "pdf_paths":    pdf_paths,
            "image_paths":  image_paths,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

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
            ext = Path(urlparse(full).path).suffix.lower()
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
            ext = Path(urlparse(url).path).suffix.lower() or ".jpg"
            filename = hashlib.md5(url.encode()).hexdigest()[:12] + ext
            path = save_dir / filename
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
