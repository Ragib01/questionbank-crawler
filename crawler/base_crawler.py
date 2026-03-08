"""
Base crawler — uses crawl4ai (Playwright) for JS-heavy pages,
falls back to requests + BeautifulSoup for plain HTML.
Windows-compatible async setup included.
"""

import asyncio
import sys
import time
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC, MAX_RETRIES
from utils import get_logger

# ── Windows asyncio fix ───────────────────────────────────────────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = get_logger("base_crawler")

# ── crawl4ai import with graceful fallback ────────────────────────────────────
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    CRAWL4AI_AVAILABLE = True
    logger.info("crawl4ai loaded successfully.")
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.warning("crawl4ai not found — using requests+BS4 fallback.")


class PageResult:
    """Normalised result returned by any crawl strategy."""
    def __init__(self, url: str, html: str, markdown: str, pdf_links: list[str], success: bool, error: str = ""):
        self.url = url
        self.html = html
        self.markdown = markdown
        self.pdf_links = pdf_links          # absolute URLs to .pdf files found on page
        self.success = success
        self.error = error


class BaseCrawler:
    """
    Fetches a page and returns a PageResult.
    Tries crawl4ai first; falls back to requests+BS4.
    """

    def __init__(self, use_playwright: bool = True, delay: float = REQUEST_DELAY_SEC):
        self.use_playwright = use_playwright and CRAWL4AI_AVAILABLE
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ── Public API ─────────────────────────────────────────────────────────────

    def fetch(self, url: str) -> PageResult:
        """Sync wrapper — always safe to call."""
        if self.use_playwright:
            try:
                return asyncio.run(self._fetch_playwright(url))
            except Exception as exc:
                logger.warning(f"Playwright fetch failed ({exc}), falling back to requests.")
        return self._fetch_requests(url)

    async def fetch_async(self, url: str) -> PageResult:
        """Async version — use inside an async context."""
        if self.use_playwright:
            try:
                return await self._fetch_playwright(url)
            except Exception as exc:
                logger.warning(f"Playwright fetch failed ({exc}), falling back to requests.")
        return self._fetch_requests(url)

    # ── Playwright (crawl4ai) strategy ─────────────────────────────────────────

    async def _fetch_playwright(self, url: str) -> PageResult:
        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            wait_until="networkidle",
            page_timeout=REQUEST_TIMEOUT_SEC * 1000,
            exclude_external_links=True,
            remove_forms=True,
        )
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
        if not result.success:
            raise RuntimeError(result.error_message or "crawl4ai returned no content")
        html = result.html or ""
        markdown = result.markdown or ""
        pdf_links = self._extract_pdf_links(html, url)
        await asyncio.sleep(self.delay)
        return PageResult(url=url, html=html, markdown=markdown, pdf_links=pdf_links, success=True)

    # ── requests + BS4 strategy ────────────────────────────────────────────────

    def _fetch_requests(self, url: str, attempt: int = 1) -> PageResult:
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT_SEC, allow_redirects=True)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
            markdown = self._html_to_markdown(html)
            pdf_links = self._extract_pdf_links(html, url)
            time.sleep(self.delay)
            return PageResult(url=url, html=html, markdown=markdown, pdf_links=pdf_links, success=True)
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                wait = attempt * 2
                logger.warning(f"Retry {attempt}/{MAX_RETRIES} for {url} after {wait}s — {exc}")
                time.sleep(wait)
                return self._fetch_requests(url, attempt + 1)
            logger.error(f"Failed to fetch {url}: {exc}")
            return PageResult(url=url, html="", markdown="", pdf_links=[], success=False, error=str(exc))

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _extract_pdf_links(self, html: str, base_url: str) -> list[str]:
        """Find all PDF links on the page."""
        soup = BeautifulSoup(html, "lxml")
        pdf_links = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if href.lower().endswith(".pdf") or "pdf" in href.lower():
                absolute = urljoin(base_url, href)
                pdf_links.append(absolute)
        # Also look in <embed> and <iframe>
        for tag in soup.find_all(["embed", "iframe"], src=True):
            src = tag["src"].strip()
            if src.lower().endswith(".pdf"):
                pdf_links.append(urljoin(base_url, src))
        return list(dict.fromkeys(pdf_links))  # deduplicate preserving order

    def _html_to_markdown(self, html: str) -> str:
        """Very lightweight HTML→plain-text (not full markdown, but readable)."""
        soup = BeautifulSoup(html, "lxml")
        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        # Convert tables to pipe format (best effort)
        text = soup.get_text(separator="\n")
        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    def get_links_from_page(self, html: str, base_url: str, filter_pattern: Optional[str] = None) -> list[str]:
        """Return all internal hrefs from a page, optionally filtered by regex."""
        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(base_url).netloc
        links = []
        for tag in soup.find_all("a", href=True):
            href = urljoin(base_url, tag["href"].strip())
            if urlparse(href).netloc == base_domain:
                if filter_pattern is None or re.search(filter_pattern, href, re.I):
                    links.append(href)
        return list(dict.fromkeys(links))
