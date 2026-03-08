"""Government Ministry Jobs question crawler."""

from __future__ import annotations
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import CRAWL_TARGETS, MAX_PAGES_PER_SITE
from utils import get_logger, ProgressQueue
from .base_crawler import BaseCrawler, PageResult

logger = get_logger("ministry_crawler")


class MinistryCrawler:
    EXAM_TYPE = "Ministry"

    def __init__(self, progress_queue: ProgressQueue, use_playwright: bool = True):
        self.pq = progress_queue
        self.base = BaseCrawler(use_playwright=use_playwright)

    def crawl(self, selected_sources: list[str] | None = None) -> list[dict]:
        targets = CRAWL_TARGETS["Ministry"]
        if selected_sources:
            targets = [t for t in targets if t["name"] in selected_sources]

        records: list[dict] = []
        total = len(targets)

        for idx, target in enumerate(targets, 1):
            self.pq.put("progress", self.EXAM_TYPE,
                        f"Crawling: {target['name']} ({idx}/{total})",
                        percent=(idx / total) * 100)
            logger.info(f"[Ministry] Starting {target['name']} — {target['url']}")
            try:
                page_records = self._crawl_site(target)
                records.extend(page_records)
                self.pq.put("log", self.EXAM_TYPE,
                            f"  Found {len(page_records)} pages from {target['name']}")
            except Exception as exc:
                logger.error(f"[Ministry] Error: {target['name']}: {exc}")
                self.pq.put("error", self.EXAM_TYPE, f"Error: {target['name']} — {exc}")

        self.pq.put("log", self.EXAM_TYPE, f"Ministry crawl done. Total raw pages: {len(records)}")
        return records

    def _crawl_site(self, target: dict) -> list[dict]:
        records = []
        index_result = self.base.fetch(target["url"])
        if not index_result.success:
            return records

        if len(index_result.markdown) > 200:
            records.append(self._make_record(target, index_result))

        sub_links = self._find_question_links(index_result.html, target["url"])
        logger.info(f"[Ministry] Found {len(sub_links)} links on {target['name']}")

        for i, link in enumerate(sub_links[:MAX_PAGES_PER_SITE], 1):
            self.pq.put("log", self.EXAM_TYPE, f"  Fetching {i}/{min(len(sub_links), MAX_PAGES_PER_SITE)}: {link}")
            result = self.base.fetch(link)
            if result.success and len(result.markdown) > 100:
                records.append(self._make_record(target, result))

        return records

    def _find_question_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        keywords = ["ministry", "question", "exam", "circular", "job", "paper",
                    "mcq", "written", "recruitment", "নিয়োগ", "প্রশ্ন"]
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            text = tag.get_text(strip=True).lower()
            full_url = urljoin(base_url, href)
            if any(kw in full_url.lower() or kw in text for kw in keywords):
                if full_url not in links and not full_url.endswith((".jpg", ".png", ".gif")):
                    links.append(full_url)
        return links

    def _make_record(self, target: dict, result: PageResult) -> dict:
        year = self._extract_year(result.url + " " + result.markdown[:500])
        return {
            "exam_type":   self.EXAM_TYPE,
            "source_name": target["name"],
            "source_url":  target["url"],
            "page_url":    result.url,
            "raw_text":    result.markdown,
            "pdf_links":   result.pdf_links,
            "year":        year,
        }

    @staticmethod
    def _extract_year(text: str) -> int | None:
        match = re.search(r"\b(19|20)\d{2}\b", text)
        return int(match.group()) if match else None
