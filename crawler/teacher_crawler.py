"""Primary Teacher & NTRCA question crawler."""

from __future__ import annotations
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import CRAWL_TARGETS, MAX_PAGES_PER_SITE
from utils import get_logger, ProgressQueue
from .base_crawler import BaseCrawler, PageResult

logger = get_logger("teacher_crawler")


class TeacherCrawler:
    """Handles both Primary Teacher (DPE) and NTRCA exam questions."""

    def __init__(self, progress_queue: ProgressQueue, use_playwright: bool = True):
        self.pq = progress_queue
        self.base = BaseCrawler(use_playwright=use_playwright)

    def crawl_primary(self, selected_sources: list[str] | None = None) -> list[dict]:
        return self._crawl_category("Primary Teacher", selected_sources)

    def crawl_ntrca(self, selected_sources: list[str] | None = None) -> list[dict]:
        return self._crawl_category("NTRCA", selected_sources)

    def _crawl_category(self, category: str, selected_sources: list[str] | None) -> list[dict]:
        targets = CRAWL_TARGETS[category]
        if selected_sources:
            targets = [t for t in targets if t["name"] in selected_sources]

        records: list[dict] = []
        total = len(targets)

        for idx, target in enumerate(targets, 1):
            self.pq.put("progress", category,
                        f"Crawling: {target['name']} ({idx}/{total})",
                        percent=(idx / total) * 100)
            logger.info(f"[{category}] Starting {target['name']} — {target['url']}")
            try:
                page_records = self._crawl_site(target, category)
                records.extend(page_records)
                self.pq.put("log", category, f"  Found {len(page_records)} pages from {target['name']}")
            except Exception as exc:
                logger.error(f"[{category}] Error: {target['name']}: {exc}")
                self.pq.put("error", category, f"Error: {target['name']} — {exc}")

        self.pq.put("log", category, f"{category} crawl done. Total raw pages: {len(records)}")
        return records

    def _crawl_site(self, target: dict, category: str) -> list[dict]:
        records = []
        index_result = self.base.fetch(target["url"])
        if not index_result.success:
            return records

        if len(index_result.markdown) > 200:
            records.append(self._make_record(target, index_result, category))

        sub_links = self._find_question_links(index_result.html, target["url"], category)
        logger.info(f"[{category}] Found {len(sub_links)} links on {target['name']}")

        for i, link in enumerate(sub_links[:MAX_PAGES_PER_SITE], 1):
            self.pq.put("log", category, f"  Fetching {i}/{min(len(sub_links), MAX_PAGES_PER_SITE)}: {link}")
            result = self.base.fetch(link)
            if result.success and len(result.markdown) > 100:
                records.append(self._make_record(target, result, category))

        return records

    def _find_question_links(self, html: str, base_url: str, category: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        if category == "NTRCA":
            keywords = ["ntrca", "question", "exam", "teacher", "registration", "paper", "শিক্ষক", "প্রশ্ন"]
        else:
            keywords = ["primary", "dpe", "teacher", "question", "exam", "paper", "circular", "প্রাথমিক", "প্রশ্ন"]
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            text = tag.get_text(strip=True).lower()
            full_url = urljoin(base_url, href)
            if any(kw in full_url.lower() or kw in text for kw in keywords):
                if full_url not in links and not full_url.endswith((".jpg", ".png", ".gif")):
                    links.append(full_url)
        return links

    def _make_record(self, target: dict, result: PageResult, category: str) -> dict:
        year = self._extract_year(result.url + " " + result.markdown[:500])
        return {
            "exam_type":   category,
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
