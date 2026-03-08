"""Primary Teacher & NTRCA question crawler."""

from __future__ import annotations
import re

from config import CRAWL_TARGETS, MAX_PAGES_PER_SITE
from utils import get_logger, ProgressQueue
from .base_crawler import BaseCrawler, PageResult

logger = get_logger("teacher_crawler")

ARTICLE_URL_RE_PRIMARY = re.compile(
    r"/(20\d{2}/\d{2}/|primary[-/]|dpe[-/]|question[-/]|exam[-/]|solution[-/]|teacher[-/]|pradhomik[-/])",
    re.I,
)
ARTICLE_URL_RE_NTRCA = re.compile(
    r"/(20\d{2}/\d{2}/|ntrca[-/]|question[-/]|exam[-/]|solution[-/]|teacher[-/]|registration[-/])",
    re.I,
)


class TeacherCrawler:
    def __init__(self, progress_queue: ProgressQueue, use_playwright: bool = True):
        self.pq = progress_queue
        self.base = BaseCrawler(use_playwright=use_playwright)

    def crawl_primary(self, selected_sources: list[str] | None = None) -> list[dict]:
        return self._crawl_category("Primary Teacher", ARTICLE_URL_RE_PRIMARY, selected_sources)

    def crawl_ntrca(self, selected_sources: list[str] | None = None) -> list[dict]:
        return self._crawl_category("NTRCA", ARTICLE_URL_RE_NTRCA, selected_sources)

    def _crawl_category(self, category: str, url_re: re.Pattern, selected_sources) -> list[dict]:
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
                page_records = self._crawl_site(target, category, url_re)
                records.extend(page_records)
                self.pq.put("log", category,
                            f"  Found {len(page_records)} pages from {target['name']}")
            except Exception as exc:
                logger.error(f"[{category}] Error: {exc}")
                self.pq.put("error", category, f"Error: {target['name']} — {exc}")

        self.pq.put("log", category, f"{category} crawl done. Total raw pages: {len(records)}")
        return records

    def _crawl_site(self, target: dict, category: str, url_re: re.Pattern) -> list[dict]:
        records = []
        index_result = self.base.fetch(target["url"])
        if not index_result.success:
            return records

        sub_links = self.base.get_same_domain_links(
            index_result.html, target["url"], filter_pattern=url_re.pattern
        )

        if len(index_result.markdown) > 300:
            records.append(self._make_record(target, index_result, category))

        logger.info(f"[{category}] Found {len(sub_links)} article links on {target['name']}")
        for i, link in enumerate(sub_links[:MAX_PAGES_PER_SITE], 1):
            self.pq.put("log", category,
                        f"  [{i}/{min(len(sub_links), MAX_PAGES_PER_SITE)}] {link}")
            result = self.base.fetch(link)
            if result.success and len(result.markdown) > 200:
                records.append(self._make_record(target, result, category))

        return records

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
        match = re.search(r"\b(20\d{2})\b", text)
        return int(match.group()) if match else None
