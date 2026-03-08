"""
Question Store — saves and loads question records as JSON.
Index file keeps a lightweight catalogue for the Streamlit UI.
"""

from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path

from config import QUESTIONS_DIR
from utils import get_logger

logger = get_logger("store")

INDEX_FILE = QUESTIONS_DIR / "_index.json"


class QuestionStore:
    """
    Persists question records as individual JSON files per exam.
    Maintains a master index for fast search and filtering.
    """

    def __init__(self):
        self._ensure_dirs()

    # ── Save ───────────────────────────────────────────────────────────────────

    def save(self, record: dict) -> Path | None:
        """
        Save a single question record.  Returns the saved file path.
        Skips records with no questions.
        """
        questions = record.get("questions", [])
        if not questions:
            logger.debug(f"Skipping empty record: {record.get('exam_id', '?')}")
            return None

        exam_id   = record.get("exam_id") or self._generate_id(record)
        exam_type = record.get("exam_type", "misc").replace(" ", "_")

        save_dir = QUESTIONS_DIR / exam_type
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = self._safe_filename(exam_id) + ".json"
        path = save_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(questions)} questions → {path.name}")
        self._update_index(record, path)
        return path

    def save_batch(self, records: list[dict]) -> list[Path]:
        """Save multiple records; return list of saved paths."""
        paths = []
        for rec in records:
            p = self.save(rec)
            if p:
                paths.append(p)
        return paths

    # ── Load ───────────────────────────────────────────────────────────────────

    def load_all(self) -> list[dict]:
        """Load every question record from disk."""
        records = []
        for json_file in QUESTIONS_DIR.rglob("*.json"):
            if json_file.name == "_index.json":
                continue
            try:
                with open(json_file, encoding="utf-8") as f:
                    records.append(json.load(f))
            except Exception as exc:
                logger.warning(f"Could not load {json_file}: {exc}")
        return records

    def load_by_type(self, exam_type: str) -> list[dict]:
        """Load all records for a given exam type."""
        type_dir = QUESTIONS_DIR / exam_type.replace(" ", "_")
        if not type_dir.exists():
            return []
        records = []
        for json_file in type_dir.glob("*.json"):
            try:
                with open(json_file, encoding="utf-8") as f:
                    records.append(json.load(f))
            except Exception as exc:
                logger.warning(f"Could not load {json_file}: {exc}")
        return records

    def load_index(self) -> list[dict]:
        """Return the lightweight index (no questions, just metadata)."""
        if not INDEX_FILE.exists():
            return []
        try:
            with open(INDEX_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def search(self, query: str, exam_types: list[str] | None = None) -> list[dict]:
        """
        Search all stored questions for a text match.
        Returns matching question records (full records).
        """
        query_lower = query.lower()
        results = []
        all_records = self.load_all()
        for rec in all_records:
            if exam_types and rec.get("exam_type") not in exam_types:
                continue
            for q in rec.get("questions", []):
                q_text = (q.get("question", "") + " " + str(q.get("options", ""))).lower()
                if query_lower in q_text:
                    results.append({**rec, "matched_question": q})
        return results

    def get_stats(self) -> dict:
        """Return summary statistics."""
        index = self.load_index()
        total_q  = sum(e.get("question_count", 0) for e in index)
        by_type  = {}
        by_year  = {}
        for e in index:
            t = e.get("exam_type", "Unknown")
            y = str(e.get("year") or "Unknown")
            by_type[t] = by_type.get(t, 0) + e.get("question_count", 0)
            by_year[y] = by_year.get(y, 0) + e.get("question_count", 0)
        return {
            "total_exams":     len(index),
            "total_questions": total_q,
            "by_exam_type":    by_type,
            "by_year":         dict(sorted(by_year.items(), reverse=True)),
        }

    def export_all_json(self) -> str:
        """Export all records as a single JSON string (for download)."""
        return json.dumps(self.load_all(), ensure_ascii=False, indent=2)

    def export_by_type(self, exam_type: str) -> str:
        return json.dumps(self.load_by_type(exam_type), ensure_ascii=False, indent=2)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _update_index(self, record: dict, file_path: Path):
        index = self.load_index()
        exam_id = record.get("exam_id", "")
        # Remove old entry if exists
        index = [e for e in index if e.get("exam_id") != exam_id]
        index.append({
            "exam_id":        exam_id,
            "exam_type":      record.get("exam_type", ""),
            "exam_name":      record.get("exam_name", ""),
            "year":           record.get("year"),
            "subject":        record.get("subject", ""),
            "question_count": len(record.get("questions", [])),
            "source_url":     record.get("source_url", ""),
            "crawled_at":     record.get("crawled_at", ""),
            "file_path":      str(file_path),
        })
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _generate_id(record: dict) -> str:
        parts = [
            record.get("exam_type", "unknown").replace(" ", "_"),
            re.sub(r"\W+", "_", record.get("exam_name", "unnamed"))[:20],
            str(record.get("year") or datetime.now().year),
        ]
        return "_".join(p for p in parts if p)

    @staticmethod
    def _safe_filename(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*\s]', "_", name)[:80]

    @staticmethod
    def _ensure_dirs():
        QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
