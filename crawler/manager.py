"""
CrawlerManager — orchestrates all exam-type crawlers.
Runs in a background thread; sends progress to a ProgressQueue.
"""

from __future__ import annotations
import threading
from datetime import datetime

from config import EXAM_TYPES, CRAWL_TARGETS
from utils import get_logger, ProgressQueue
from .bcs_crawler import BCSCrawler
from .bank_crawler import BankCrawler
from .ministry_crawler import MinistryCrawler
from .teacher_crawler import TeacherCrawler
from .wp_api_crawler import WPAPICrawler

logger = get_logger("crawler_manager")


class CrawlerManager:
    """
    Coordinates all crawlers and returns a unified list of raw page records.

    Usage:
        pq = ProgressQueue()
        mgr = CrawlerManager(pq, exam_types=["BCS", "Bank"])
        mgr.start()          # runs in background thread
        while mgr.is_running():
            msgs = pq.get_all()
            ...
        records = mgr.get_results()
    """

    def __init__(
        self,
        progress_queue: ProgressQueue,
        exam_types: list[str] | None = None,
        use_playwright: bool = True,
        download_pdfs: bool = True,
    ):
        self.pq = progress_queue
        self.exam_types = exam_types or EXAM_TYPES
        self.use_playwright = use_playwright
        self.download_pdfs = download_pdfs

        self._results: list[dict] = []
        self._thread: threading.Thread | None = None
        self._running = False
        self._done = False

    # ── Control ────────────────────────────────────────────────────────────────

    def start(self):
        """Start crawling in a background daemon thread."""
        self._running = True
        self._done = False
        self._results = []
        self._thread = threading.Thread(target=self._run, daemon=True, name="CrawlerThread")
        self._thread.start()

    def is_running(self) -> bool:
        return self._running and not self._done

    def is_done(self) -> bool:
        return self._done

    def get_results(self) -> list[dict]:
        return self._results

    # ── Internal ───────────────────────────────────────────────────────────────

    def _run(self):
        try:
            self.pq.put("log", "Manager", f"Starting crawl at {datetime.now().strftime('%H:%M:%S')}")
            self.pq.put("log", "Manager", f"Exam types: {', '.join(self.exam_types)}")

            total_types = len(self.exam_types)
            for type_idx, exam_type in enumerate(self.exam_types, 1):
                base_pct = ((type_idx - 1) / total_types) * 100
                self.pq.put("progress", "Manager",
                            f"[{type_idx}/{total_types}] Starting {exam_type}",
                            percent=base_pct)

                records = self._run_one(exam_type)
                self._results.extend(records)

                self.pq.put("progress", "Manager",
                            f"[{type_idx}/{total_types}] {exam_type} done — {len(records)} pages",
                            percent=(type_idx / total_types) * 100)

            self.pq.put("progress", "Manager",
                        f"All crawls complete. Total pages: {len(self._results)}",
                        percent=100)
            self.pq.put("done", "Manager",
                        f"Finished at {datetime.now().strftime('%H:%M:%S')}. "
                        f"Total raw pages collected: {len(self._results)}")

        except Exception as exc:
            logger.exception(f"CrawlerManager fatal error: {exc}")
            self.pq.put("error", "Manager", f"Fatal error: {exc}")
        finally:
            self._running = False
            self._done = True

    def _run_one(self, exam_type: str) -> list[dict]:
        logger.info(f"Running crawler for: {exam_type}")
        targets = CRAWL_TARGETS.get(exam_type, [])

        # Route to WP API crawler if all/any targets are wp_api type
        wp_targets = [t for t in targets if t.get("type") == "wp_api"]
        html_targets = [t for t in targets if t.get("type") != "wp_api"]

        records: list[dict] = []

        # Run WP API crawler for wp_api targets
        if wp_targets:
            records.extend(WPAPICrawler(self.pq).crawl(exam_type, wp_targets))

        # Run legacy HTML crawlers for html targets (if any remain)
        if html_targets:
            if exam_type == "BCS":
                records.extend(BCSCrawler(self.pq, self.use_playwright).crawl())
            elif exam_type == "Bank":
                records.extend(BankCrawler(self.pq, self.use_playwright).crawl())
            elif exam_type == "Ministry":
                records.extend(MinistryCrawler(self.pq, self.use_playwright).crawl())
            elif exam_type == "Primary Teacher":
                records.extend(TeacherCrawler(self.pq, self.use_playwright).crawl_primary())
            elif exam_type == "NTRCA":
                records.extend(TeacherCrawler(self.pq, self.use_playwright).crawl_ntrca())

        if not targets:
            logger.warning(f"Unknown exam type: {exam_type}")

        return records
