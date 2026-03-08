"""
AI Extractor — uses Anthropic Claude to extract structured Q&A
from raw scraped text or PDF text.
"""

from __future__ import annotations
import json
import re
import time
from datetime import datetime
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, AI_MODEL_FAST, AI_MODEL_SMART
from utils import get_logger, ProgressQueue

logger = get_logger("ai_extractor")


class AIExtractor:
    """
    Uses Claude to turn messy scraped text into structured question JSON.
    Falls back gracefully if no questions are found.
    """

    def __init__(self, progress_queue: ProgressQueue | None = None, model: str = AI_MODEL_FAST):
        self.pq = progress_queue
        self.model = model
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._call_count = 0
        self._token_count = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    # Characters per chunk when text is very long
    _CHUNK_SIZE    = 15_000
    _CHUNK_OVERLAP = 500

    def extract_questions(self, raw_text: str, exam_type: str, source_url: str, year: Optional[int] = None) -> dict:
        """
        Extract structured questions from raw text.
        Automatically chunks very long text and merges results.
        Returns a question-bank record dict (matches QUESTION_SCHEMA in config.py).
        """
        if not raw_text or len(raw_text.strip()) < 50:
            logger.warning("Text too short to extract questions.")
            return self._empty_record(exam_type, source_url, year)

        # Split into chunks if text is very long
        chunks = self._split_text(raw_text)

        if len(chunks) == 1:
            return self._extract_single(chunks[0], exam_type, source_url, year)

        # Multi-chunk: extract from each, merge questions
        logger.info(f"Long text ({len(raw_text)} chars) split into {len(chunks)} chunks")
        if self.pq:
            self.pq.put("log", "AI", f"Long page — processing in {len(chunks)} chunks")

        merged_questions: list[dict] = []
        base_record: dict | None = None

        for i, chunk in enumerate(chunks, 1):
            try:
                rec = self._extract_single(chunk, exam_type, source_url, year)
                if base_record is None and rec.get("exam_name"):
                    base_record = rec
                merged_questions.extend(rec.get("questions", []))
                time.sleep(0.3)   # brief pause between chunk calls
            except Exception as exc:
                logger.warning(f"Chunk {i}/{len(chunks)} failed: {exc}")

        if base_record is None:
            base_record = self._empty_record(exam_type, source_url, year)

        # Re-number questions sequentially and deduplicate by text
        seen: set[str] = set()
        unique: list[dict] = []
        for q in merged_questions:
            key = q.get("question", "")[:80]
            if key and key not in seen:
                seen.add(key)
                unique.append(q)
        for idx, q in enumerate(unique, 1):
            q["q_no"] = idx

        base_record["questions"]  = unique
        base_record["ai_processed"] = True
        base_record["crawled_at"]   = datetime.now().isoformat()
        return base_record

    def _extract_single(self, text: str, exam_type: str, source_url: str, year: Optional[int]) -> dict:
        """Extract from a single text chunk with retry."""
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0, 5, 15], start=1):
            if delay:
                logger.info(f"AI retry {attempt} after {delay}s")
                time.sleep(delay)
            try:
                result = self._call_claude(text, exam_type, source_url, year)
                result["ai_processed"] = True
                result["crawled_at"]   = datetime.now().isoformat()
                return result
            except Exception as exc:
                last_exc = exc
                logger.warning(f"AI attempt {attempt} failed: {exc}")
                if self.pq:
                    self.pq.put("log", "AI", f"Attempt {attempt} failed: {exc}")

        logger.error(f"AI extraction failed after all retries: {last_exc}")
        if self.pq:
            self.pq.put("error", "AI", f"Extraction error: {last_exc}")
        return self._empty_record(exam_type, source_url, year)

    def _split_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks if it exceeds _CHUNK_SIZE."""
        if len(text) <= self._CHUNK_SIZE:
            return [text]
        chunks = []
        start  = 0
        while start < len(text):
            end = start + self._CHUNK_SIZE
            chunks.append(text[start:end])
            start = end - self._CHUNK_OVERLAP   # overlap between chunks
            if start >= len(text):
                break
        return chunks

    def extract_batch(self, records: list[dict]) -> list[dict]:
        """Process a list of raw crawler records; return structured question records."""
        results = []
        total = len(records)
        for i, rec in enumerate(records, 1):
            if self.pq:
                self.pq.put("progress", "AI",
                            f"AI processing {i}/{total}: {rec.get('source_name', '?')}",
                            percent=(i / total) * 100)
            structured = self.extract_questions(
                raw_text   = rec.get("raw_text", ""),
                exam_type  = rec.get("exam_type", "Unknown"),
                source_url = rec.get("page_url", rec.get("source_url", "")),
                year       = rec.get("year"),
            )
            # Carry over PDF links
            structured["pdf_links_found"] = rec.get("pdf_links", [])
            if structured.get("questions"):
                results.append(structured)
            # Polite delay between API calls
            time.sleep(0.5)
        return results

    @property
    def usage_stats(self) -> dict:
        return {"api_calls": self._call_count, "approx_tokens": self._token_count}

    # ── Claude call ────────────────────────────────────────────────────────────

    def _call_claude(self, text: str, exam_type: str, source_url: str, year: Optional[int]) -> dict:
        system_prompt = self._system_prompt()
        user_prompt   = self._user_prompt(text, exam_type, source_url, year)

        response = self.client.messages.create(
            model      = self.model,
            max_tokens = 8192,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_prompt}],
        )

        self._call_count += 1
        self._token_count += response.usage.input_tokens + response.usage.output_tokens

        raw_output = response.content[0].text
        return self._parse_response(raw_output, exam_type, source_url, year)

    # ── Prompts ────────────────────────────────────────────────────────────────

    @staticmethod
    def _system_prompt() -> str:
        return """You are an expert at extracting Bangladesh government exam questions from raw text.
Your task is to parse exam questions from Bengali and English text scraped from websites or PDFs.

RULES:
1. Extract every MCQ (multiple choice) question you find.
2. Return ONLY a valid JSON object — no markdown fences, no extra text.
3. If you cannot find any questions, return: {"exam_name":"","year":null,"subject":"","questions":[]}
4. Preserve original Bengali text exactly — do not translate.
5. For answer, use the letter (A/B/C/D) if available, or the full answer text.
6. Guess the topic from context (e.g., "Bangladesh Affairs", "General Math", "English", "Science").
7. exam_name should be descriptive, e.g. "44th BCS Preliminary", "Sonali Bank Officer 2022".

JSON SCHEMA (return exactly this structure):
{
  "exam_name": "string",
  "year": integer or null,
  "subject": "string",
  "questions": [
    {
      "q_no": integer,
      "question": "string",
      "options": {"A": "string", "B": "string", "C": "string", "D": "string"},
      "answer": "A" or "B" or "C" or "D" or "string",
      "explanation": "string or empty",
      "topic": "string"
    }
  ]
}"""

    @staticmethod
    def _user_prompt(text: str, exam_type: str, source_url: str, year: Optional[int]) -> str:
        year_hint = f" (likely year: {year})" if year else ""
        return f"""Exam type: {exam_type}{year_hint}
Source: {source_url}

Extract all exam questions from the following text. Return valid JSON only.

--- TEXT START ---
{text}
--- TEXT END ---"""

    # ── Response parser ────────────────────────────────────────────────────────

    def _parse_response(self, raw: str, exam_type: str, source_url: str, year: Optional[int]) -> dict:
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()
        # Find the outermost JSON object
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            logger.warning("No JSON object found in AI response.")
            return self._empty_record(exam_type, source_url, year)

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as exc:
            logger.warning(f"JSON parse error: {exc}. Attempting repair.")
            data = self._repair_json(match.group())
            if not data:
                return self._empty_record(exam_type, source_url, year)

        return {
            "exam_id":    self._make_exam_id(exam_type, data.get("exam_name", ""), data.get("year") or year),
            "exam_type":  exam_type,
            "exam_name":  data.get("exam_name", ""),
            "year":       data.get("year") or year,
            "subject":    data.get("subject", ""),
            "source_url": source_url,
            "pdf_path":   None,
            "crawled_at": datetime.now().isoformat(),
            "ai_processed": True,
            "questions":  self._validate_questions(data.get("questions", [])),
        }

    @staticmethod
    def _validate_questions(questions: list) -> list:
        """Ensure each question has the required fields."""
        valid = []
        for i, q in enumerate(questions, 1):
            if not isinstance(q, dict):
                continue
            if not q.get("question"):
                continue
            valid.append({
                "q_no":        q.get("q_no", i),
                "question":    str(q.get("question", "")),
                "options":     q.get("options") or {},
                "answer":      q.get("answer", ""),
                "explanation": q.get("explanation", ""),
                "topic":       q.get("topic", ""),
            })
        return valid

    @staticmethod
    def _empty_record(exam_type: str, source_url: str, year: Optional[int]) -> dict:
        return {
            "exam_id":      "",
            "exam_type":    exam_type,
            "exam_name":    "",
            "year":         year,
            "subject":      "",
            "source_url":   source_url,
            "pdf_path":     None,
            "crawled_at":   datetime.now().isoformat(),
            "ai_processed": False,
            "questions":    [],
        }

    @staticmethod
    def _make_exam_id(exam_type: str, exam_name: str, year) -> str:
        parts = [exam_type.replace(" ", "_")]
        if exam_name:
            safe = re.sub(r"[^\w]", "_", exam_name)[:30]
            parts.append(safe)
        if year:
            parts.append(str(year))
        return "_".join(parts)

    @staticmethod
    def _repair_json(raw: str) -> dict | None:
        """
        Multi-strategy repair for truncated/malformed JSON from the AI.
        Most common cause: max_tokens cut the response mid-array.
        """
        strategies = []

        # 1. Remove trailing comma before ] or }
        strategies.append(re.sub(r",\s*([}\]])", r"\1", raw))

        # 2. Truncated inside questions array — find last complete question object
        #    and close the array + object properly.
        last_complete = raw.rfind("},")
        if last_complete == -1:
            last_complete = raw.rfind("}")
        if last_complete > 0:
            truncated = raw[: last_complete + 1]
            # Close questions array and outer object
            strategies.append(truncated + "\n]}")
            strategies.append(truncated + "\n]}\n")
            # Also try with trailing comma removal first
            cleaned = re.sub(r",\s*([}\]])", r"\1", truncated)
            strategies.append(cleaned + "\n]}")

        # 3. Add missing closing brace/bracket combos
        strategies.append(raw + "]}")
        strategies.append(raw + "\n]}")
        strategies.append(raw + "}")

        for attempt in strategies:
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue

        return None
