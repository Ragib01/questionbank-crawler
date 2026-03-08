"""
Base crawler — uses crawl4ai (Playwright) for JS-heavy pages,
falls back to requests + BeautifulSoup for plain HTML.
Windows-compatible async setup included.
"""

import asyncio
import sys
import threading
import time
import re
import warnings
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_SEC, REQUEST_TIMEOUT_SEC, MAX_RETRIES
from utils import get_logger

# Suppress SSL warnings for govt sites with self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ── Windows asyncio fix ───────────────────────────────────────────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = get_logger("base_crawler")

# ── crawl4ai import with graceful fallback ────────────────────────────────────
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
    logger.info("crawl4ai loaded successfully.")
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.warning("crawl4ai not found — using requests+BS4 fallback.")

# Domains known to have self-signed / invalid SSL certs
SSL_SKIP_VERIFY_DOMAINS = {
    "bpsc.gov.bd",
    "dpe.gov.bd",
    "ntrca.gov.bd",
    "mopa.gov.bd",
    "erecruitment.bb.org.bd",
    "bb.org.bd",
}


class PageResult:
    """Normalised result returned by any crawl strategy."""
    def __init__(self, url: str, html: str, markdown: str, pdf_links: list[str], success: bool, error: str = ""):
        self.url = url
        self.html = html
        self.markdown = markdown
        self.pdf_links = pdf_links
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
        """Sync wrapper — always safe to call from any thread."""
        if self.use_playwright:
            # asyncio.run() + Playwright subprocess spawning is unreliable in
            # non-main threads on Windows (ProactorEventLoop / process_title assert).
            # Skip Playwright in worker threads and use requests directly.
            in_main = threading.current_thread() is threading.main_thread()
            if in_main:
                try:
                    return asyncio.run(self._fetch_playwright(url))
                except Exception as exc:
                    logger.warning(f"Playwright fetch failed ({exc}), falling back to requests.")
            else:
                logger.debug("Worker thread — using requests fallback (Playwright skipped).")
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

    def _fetch_requests(self, url: str, attempt: int = 1, verify_ssl: bool = True) -> PageResult:
        domain = urlparse(url).netloc
        ssl_verify = False if domain in SSL_SKIP_VERIFY_DOMAINS else verify_ssl
        try:
            resp = self.session.get(
                url,
                timeout=REQUEST_TIMEOUT_SEC,
                allow_redirects=True,
                verify=ssl_verify,
            )
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
            markdown = self._html_to_markdown(html)
            pdf_links = self._extract_pdf_links(html, url)
            time.sleep(self.delay)
            return PageResult(url=url, html=html, markdown=markdown, pdf_links=pdf_links, success=True)
        except requests.exceptions.SSLError:
            # Retry once without SSL verification
            if verify_ssl:
                logger.warning(f"SSL error on {url} — retrying without SSL verification.")
                return self._fetch_requests(url, attempt, verify_ssl=False)
            logger.error(f"SSL error even without verification: {url}")
            return PageResult(url=url, html="", markdown="", pdf_links=[], success=False, error="SSL Error")
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                wait = attempt * 2
                logger.warning(f"Retry {attempt}/{MAX_RETRIES} for {url} after {wait}s — {exc}")
                time.sleep(wait)
                return self._fetch_requests(url, attempt + 1, verify_ssl)
            logger.error(f"Failed to fetch {url}: {exc}")
            return PageResult(url=url, html="", markdown="", pdf_links=[], success=False, error=str(exc))

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _extract_pdf_links(self, html: str, base_url: str) -> list[str]:
        """Find links that point to actual .pdf files (strict — URL must end in .pdf)."""
        soup = BeautifulSoup(html, "lxml")
        pdf_links = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            # Only include links where the PATH ends with .pdf (not just contains 'pdf')
            path = urlparse(href).path.lower()
            if path.endswith(".pdf"):
                absolute = urljoin(base_url, href)
                pdf_links.append(absolute)
        for tag in soup.find_all(["embed", "iframe"], src=True):
            src = tag["src"].strip()
            if urlparse(src).path.lower().endswith(".pdf"):
                pdf_links.append(urljoin(base_url, src))
        return list(dict.fromkeys(pdf_links))

    def _html_to_markdown(self, html: str) -> str:
        """Lightweight HTML→readable plain-text."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    def get_same_domain_links(self, html: str, base_url: str, filter_pattern: Optional[str] = None) -> list[str]:
        """Return all internal hrefs from a page on the same domain, optionally filtered by regex."""
        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(base_url).netloc
        links = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            # Skip anchors, javascript, mailto
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            full = urljoin(base_url, href)
            parsed = urlparse(full)
            # Must be same domain and not a fragment-only link
            if parsed.netloc == base_domain and parsed.path not in ("", "/"):
                clean = parsed._replace(fragment="").geturl()  # strip #anchor
                if filter_pattern is None or re.search(filter_pattern, clean, re.I):
                    links.append(clean)
        return list(dict.fromkeys(links))

    # Keep old name as alias for backwards compat
    def get_links_from_page(self, html: str, base_url: str, filter_pattern: Optional[str] = None) -> list[str]:
        return self.get_same_domain_links(html, base_url, filter_pattern)
