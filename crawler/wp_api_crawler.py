"""
WordPress REST API crawler — fetches post content from WordPress sites.
Used for pdf.exambd.net which has accessible WP JSON API with MCQ content.
"""
from __future__ import annotations
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC
from utils import get_logger, ProgressQueue

logger = get_logger("wp_api_crawler")


class WPAPICrawler:
    """
    Fetches posts from a WordPress site's REST API and returns raw records
    compatible with the AI extractor.
    """

    def __init__(self, progress_queue: ProgressQueue):
        self.pq = progress_queue
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ── Public API ─────────────────────────────────────────────────────────────

    def crawl(self, exam_type: str, targets: list[dict]) -> list[dict]:
        """
        Crawl all WP API targets for an exam type.
        Each target must have: name, base_url, type="wp_api",
        and one of: category_id, search, or both.
        """
        records: list[dict] = []
        total = len(targets)
        for idx, target in enumerate(targets, 1):
            self.pq.put("progress", exam_type,
                        f"Crawling: {target['name']} ({idx}/{total})",
                        percent=(idx / total) * 100)
            logger.info(f"[{exam_type}] WP API: {target['name']}")
            try:
                batch = self._crawl_target(target, exam_type)
                records.extend(batch)
                self.pq.put("log", exam_type,
                            f"  Found {len(batch)} posts from {target['name']}")
            except Exception as exc:
                logger.error(f"[{exam_type}] WP API error on {target['name']}: {exc}")
                self.pq.put("error", exam_type, f"WP API error: {target['name']} — {exc}")

        self.pq.put("log", exam_type, f"{exam_type} WP API crawl done. Total posts: {len(records)}")
        return records

    # ── Internal ───────────────────────────────────────────────────────────────

    def _crawl_target(self, target: dict, exam_type: str) -> list[dict]:
        base_url = target["base_url"].rstrip("/")
        api_base = f"{base_url}/wp-json/wp/v2"
        category_id = target.get("category_id")
        search = target.get("search")
        per_page = target.get("per_page", 10)
        max_pages = target.get("max_pages", 3)

        records = []
        for page in range(1, max_pages + 1):
            params: dict = {
                "per_page": per_page,
                "page": page,
                "_fields": "id,title,link,content,date",
            }
            if category_id:
                params["categories"] = category_id
            if search:
                params["search"] = search

            posts = self._wp_get(f"{api_base}/posts", params)
            if not posts:
                logger.info(f"  No posts on page {page}, stopping.")
                break

            for post in posts:
                content_html = post.get("content", {}).get("rendered", "")
                title = post.get("title", {}).get("rendered", "")
                link = post.get("link", "")
                date_str = post.get("date", "")

                raw_text = self._html_to_text(content_html)
                if len(raw_text) < 100:
                    logger.debug(f"  Skipping short post: {title[:50]}")
                    continue

                year = self._extract_year(date_str + " " + title)
                # Include the title in the text for context
                full_text = f"Title: {title}\nDate: {date_str}\nSource: {link}\n\n{raw_text}"

                records.append({
                    "exam_type":   exam_type,
                    "source_name": target["name"],
                    "source_url":  base_url,
                    "page_url":    link,
                    "raw_text":    full_text,
                    "pdf_links":   self._extract_pdf_links(content_html),
                    "year":        year,
                })
                logger.debug(f"  Added: {title[:60]} ({len(raw_text)} chars)")

            logger.info(f"  Page {page}: {len(posts)} posts fetched")
            time.sleep(REQUEST_DELAY_SEC)

        return records

    def _wp_get(self, url: str, params: dict) -> list:
        try:
            r = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC)
            if r.status_code == 400:
                # Bad page number — no more pages
                return []
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error(f"WP API request failed: {url} — {exc}")
            return []

    @staticmethod
    def _html_to_text(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for t in soup(["script", "style", "iframe"]):
            t.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _extract_pdf_links(html: str) -> list[str]:
        return re.findall(r'https?://[^\s"<>]+\.pdf', html, re.I)

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        m = re.search(r"\b(20\d{2})\b", text)
        return int(m.group()) if m else None
