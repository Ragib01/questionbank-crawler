"""Government Ministry Jobs question crawler."""

from __future__ import annotations
import re

from config import CRAWL_TARGETS, MAX_PAGES_PER_SITE
from utils import get_logger, ProgressQueue
from .base_crawler import BaseCrawler, PageResult

logger = get_logger("ministry_crawler")

ARTICLE_URL_RE = re.compile(
    r"/(20\d{2}/\d{2}/|ministry[-/]|question[-/]|exam[-/]|solution[-/]|job[-/]|circular[-/]|niyog[-/])",
    re.I,
)


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
                logger.error(f"[Ministry] Error: {exc}")
                self.pq.put("error", self.EXAM_TYPE, f"Error: {target['name']} — {exc}")

        self.pq.put("log", self.EXAM_TYPE, f"Ministry crawl done. Total raw pages: {len(records)}")
        return records

    def _crawl_site(self, target: dict) -> list[dict]:
        records = []
        index_result = self.base.fetch(target["url"])
        if not index_result.success:
            return records

        sub_links = self.base.get_same_domain_links(
            index_result.html, target["url"], filter_pattern=ARTICLE_URL_RE.pattern
        )

        if len(index_result.markdown) > 300:
            records.append(self._make_record(target, index_result))

        logger.info(f"[Ministry] Found {len(sub_links)} article links on {target['name']}")
        for i, link in enumerate(sub_links[:MAX_PAGES_PER_SITE], 1):
            self.pq.put("log", self.EXAM_TYPE,
                        f"  [{i}/{min(len(sub_links), MAX_PAGES_PER_SITE)}] {link}")
            result = self.base.fetch(link)
            if result.success and len(result.markdown) > 200:
                records.append(self._make_record(target, result))

        return records

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
        match = re.search(r"\b(20\d{2})\b", text)
        return int(match.group()) if match else None
