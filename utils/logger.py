import logging
import queue
import threading
from datetime import datetime
from pathlib import Path

from config import LOGS_DIR


def get_logger(name: str = "qb_crawler") -> logging.Logger:
    """Return a logger that writes to both file and console."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler
    log_file = LOGS_DIR / f"crawler_{datetime.now().strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ── Thread-safe progress queue (crawler → Streamlit UI) ──────────────────────
class ProgressQueue:
    """
    A thread-safe message queue between the background crawler thread
    and the Streamlit UI thread.

    Message format:
        {
            "type":    "progress" | "log" | "result" | "done" | "error",
            "source":  str,           # which crawler / step
            "message": str,
            "percent": float,         # 0-100, only for type=="progress"
            "data":    dict | None,   # only for type=="result"
        }
    """

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def put(self, msg_type: str, source: str, message: str, percent: float = 0.0, data=None):
        self._q.put({
            "type":    msg_type,
            "source":  source,
            "message": message,
            "percent": percent,
            "data":    data,
            "ts":      datetime.now().strftime("%H:%M:%S"),
        })

    def get_all(self) -> list:
        """Drain the queue and return all pending messages."""
        messages = []
        while True:
            try:
                messages.append(self._q.get_nowait())
            except queue.Empty:
                break
        return messages

    def empty(self) -> bool:
        return self._q.empty()
