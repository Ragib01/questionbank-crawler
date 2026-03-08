"""
MongoDB storage layer for the Question Bank.
Uses the Atlas DSN from .env (MONGODB_DSN).
Database: MONGODB_DATABASE_QB (default: "questionbank").
Collections:
  - exams       : full exam records with embedded questions array
  - crawl_sessions : metadata for each crawl session
"""
from __future__ import annotations
import os
from datetime import datetime
from typing import Optional

from pymongo import MongoClient, DESCENDING, TEXT
from pymongo.errors import ServerSelectionTimeoutError
from dotenv import load_dotenv

from utils import get_logger

load_dotenv()
logger = get_logger("mongo_store")


def _get_client() -> MongoClient:
    dsn = os.getenv("MONGODB_DSN", "")
    if not dsn:
        raise ValueError("MONGODB_DSN is not set in .env")
    return MongoClient(dsn, serverSelectionTimeoutMS=10000)


class MongoStore:
    """Persists question records to MongoDB Atlas."""

    def __init__(self):
        self.client = _get_client()
        db_name = os.getenv("MONGODB_DATABASE_QB", "questionbank")
        self.db = self.client[db_name]
        self.exams     = self.db["exams"]
        self.sessions  = self.db["crawl_sessions"]
        self.watchlist = self.db["url_watchlist"]
        self._ensure_indexes()

    # ── Connection check ───────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if MongoDB is reachable."""
        try:
            self.client.admin.command("ping")
            return True
        except ServerSelectionTimeoutError:
            return False

    # ── Save ───────────────────────────────────────────────────────────────────

    def save_exam(self, record: dict) -> Optional[str]:
        """
        Upsert a full exam record.
        Returns the exam_id on success, None on failure.
        """
        questions = record.get("questions", [])
        if not questions:
            logger.debug(f"Skipping empty record: {record.get('exam_id', '?')}")
            return None

        exam_id = record.get("exam_id") or self._generate_id(record)
        doc = {**record, "exam_id": exam_id, "updated_at": datetime.utcnow()}

        self.exams.update_one(
            {"exam_id": exam_id},
            {"$set": doc},
            upsert=True,
        )
        logger.info(f"Saved {len(questions)} questions → MongoDB exams/{exam_id}")
        return exam_id

    def save_batch(self, records: list[dict]) -> list[str]:
        """Save multiple exam records; return list of saved exam_ids."""
        ids = []
        for rec in records:
            eid = self.save_exam(rec)
            if eid:
                ids.append(eid)
        return ids

    def save_session(self, session: dict) -> str:
        """Save a crawl session record. Returns inserted id."""
        session["created_at"] = datetime.utcnow()
        result = self.sessions.insert_one(session)
        return str(result.inserted_id)

    # ── Load ───────────────────────────────────────────────────────────────────

    def load_all(self, exam_type: Optional[str] = None) -> list[dict]:
        """Load exam records, optionally filtered by exam_type."""
        query = {}
        if exam_type:
            query["exam_type"] = exam_type
        docs = list(self.exams.find(query, {"_id": 0}).sort("crawled_at", DESCENDING))
        return docs

    def load_index(self) -> list[dict]:
        """Lightweight index — metadata only, no questions array."""
        docs = list(self.exams.find(
            {},
            {"_id": 0, "exam_id": 1, "exam_type": 1, "exam_name": 1, "year": 1,
             "subject": 1, "source_url": 1, "crawled_at": 1, "questions": 1},
        ).sort("crawled_at", DESCENDING))
        # Add question_count
        for d in docs:
            d["question_count"] = len(d.pop("questions", []))
        return docs

    def get_exam(self, exam_id: str) -> Optional[dict]:
        """Load a single exam record by exam_id."""
        doc = self.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        return doc

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, query: str, exam_types: Optional[list[str]] = None,
               limit: int = 200) -> list[dict]:
        """
        Search question text using MongoDB $text index (exact match) or
        $regex for Bengali/partial match. Returns flat list of matched questions.
        """
        query_lower = query.lower()
        base_filter = {}
        if exam_types:
            base_filter["exam_type"] = {"$in": exam_types}

        results = []
        for doc in self.exams.find(base_filter, {"_id": 0}):
            for q in doc.get("questions", []):
                q_text = (q.get("question", "") + " " +
                          " ".join(str(v) for v in q.get("options", {}).values())).lower()
                if query_lower in q_text:
                    results.append({
                        "exam_type":      doc.get("exam_type", ""),
                        "exam_name":      doc.get("exam_name", ""),
                        "year":           doc.get("year"),
                        "source_url":     doc.get("source_url", ""),
                        "matched_question": q,
                    })
                    if len(results) >= limit:
                        return results
        return results

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return summary statistics."""
        total_exams = self.exams.count_documents({})
        pipeline_type = [
            {"$group": {"_id": "$exam_type",
                        "count": {"$sum": {"$size": {"$ifNull": ["$questions", []]}}}}},
        ]
        pipeline_year = [
            {"$group": {"_id": "$year",
                        "count": {"$sum": {"$size": {"$ifNull": ["$questions", []]}}}}},
            {"$sort": {"_id": DESCENDING}},
        ]
        by_type = {r["_id"]: r["count"] for r in self.exams.aggregate(pipeline_type) if r["_id"]}
        by_year = {str(r["_id"] or "Unknown"): r["count"] for r in self.exams.aggregate(pipeline_year)}
        total_questions = sum(by_type.values())

        return {
            "total_exams":     total_exams,
            "total_questions": total_questions,
            "by_exam_type":    by_type,
            "by_year":         by_year,
        }

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_all_json(self) -> str:
        import json
        docs = self.load_all()
        return json.dumps(docs, ensure_ascii=False, indent=2, default=str)

    def export_by_type(self, exam_type: str) -> str:
        import json
        docs = self.load_all(exam_type=exam_type)
        return json.dumps(docs, ensure_ascii=False, indent=2, default=str)

    # ── URL Watchlist ──────────────────────────────────────────────────────────

    def watchlist_add(self, url: str, exam_type: str = "General") -> None:
        """Add a URL to the watchlist (ignored if already present)."""
        self.watchlist.update_one(
            {"url": url},
            {"$setOnInsert": {
                "url":            url,
                "exam_type":      exam_type,
                "added_at":       datetime.utcnow(),
                "last_crawled_at": None,
                "crawl_count":    0,
                "questions_saved": 0,
            }},
            upsert=True,
        )

    def watchlist_mark_crawled(self, url: str, questions_saved: int = 0) -> None:
        """Update crawl timestamp and question count for a watchlist entry."""
        self.watchlist.update_one(
            {"url": url},
            {"$set":  {"last_crawled_at": datetime.utcnow(),
                        "questions_saved":  questions_saved},
             "$inc":  {"crawl_count": 1}},
            upsert=True,
        )

    def watchlist_remove(self, url: str) -> None:
        self.watchlist.delete_one({"url": url})

    def watchlist_get(self) -> list[dict]:
        """Return all watchlist entries sorted: pending first, then by added_at desc."""
        docs = list(self.watchlist.find({}, {"_id": 0}).sort(
            [("last_crawled_at", 1), ("added_at", -1)]
        ))
        return docs

    # ── Recent sessions ────────────────────────────────────────────────────────

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        docs = list(self.sessions.find(
            {}, {"_id": 0}
        ).sort("created_at", DESCENDING).limit(limit))
        return docs

    # ── Internal ───────────────────────────────────────────────────────────────

    def _ensure_indexes(self):
        try:
            self.exams.create_index("exam_id", unique=True, background=True)
            self.exams.create_index("exam_type", background=True)
            self.exams.create_index("crawled_at", background=True)
            self.watchlist.create_index("url", unique=True, background=True)
        except Exception as exc:
            logger.warning(f"Index creation warning: {exc}")

    @staticmethod
    def _generate_id(record: dict) -> str:
        import re
        parts = [
            record.get("exam_type", "unknown").replace(" ", "_"),
            re.sub(r"\W+", "_", record.get("exam_name", "unnamed"))[:20],
            str(record.get("year") or datetime.now().year),
        ]
        return "_".join(p for p in parts if p)
