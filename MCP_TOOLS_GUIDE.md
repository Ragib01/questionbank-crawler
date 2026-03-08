# Bangladesh Question Bank — MCP Server Guide

Build and run an **MCP (Model Context Protocol) server** that exposes the question bank stored in MongoDB so any MCP-compatible AI — Claude Desktop, Kimi, Cursor, Zed, etc. — can search, quiz, and browse Bangladesh govt exam questions.

---

## What is MCP?

[Model Context Protocol](https://modelcontextprotocol.io) is an open standard (created by Anthropic) that lets AI assistants call **tools** you define. Once your MCP server is running, the AI can:

- Search questions by keyword (Bengali or English)
- Get questions by exam type (BCS, Bank, …)
- Fetch a random quiz question
- Look up the answer + explanation for a specific question

No copy-paste, no file uploads — the AI calls your live MongoDB directly through your MCP server.

---

## Data Schema (what's in MongoDB)

Each **exam record** in the `exams` collection looks like:

```json
{
  "exam_id":    "BCS_44th_BCS_Preliminary_2022",
  "exam_type":  "BCS",
  "exam_name":  "44th BCS Preliminary",
  "year":       2022,
  "subject":    "General Knowledge",
  "source_url": "https://pdf.exambd.net/...",
  "crawled_at": "2024-11-06T10:23:11",
  "questions": [
    {
      "q_no":        1,
      "question":    "বাংলাদেশের মুক্তিযুদ্ধের সময় ঢাকা কোন সেক্টরে ছিল?",
      "options":     { "A": "১ নং", "B": "২ নং", "C": "৩ নং", "D": "৪ নং" },
      "answer":      "B",
      "explanation": "ঢাকা ২ নং সেক্টরে ছিল।",
      "topic":       "Bangladesh Affairs"
    }
  ]
}
```

---

## Step 1 — Install the MCP SDK

The official Python SDK is `mcp`. Install it into the project virtual environment:

```bash
# From the project directory
uv add mcp
# or with pip:
.venv/Scripts/pip install mcp
```

---

## Step 2 — Create the MCP Server File

Create `mcp_server.py` in the project root:

```python
"""
Bangladesh Question Bank — MCP Server
Exposes MongoDB question data as MCP tools for Claude, Kimi, Cursor, etc.

Run:
    python mcp_server.py
or with the MCP inspector:
    npx @modelcontextprotocol/inspector python mcp_server.py
"""

import random
import sys
import os

# Make sure project packages are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from storage.mongo_store import MongoStore

# ── MCP server instance ───────────────────────────────────────────────────────
mcp = FastMCP(
    name="bd-question-bank",
    instructions=(
        "You have access to a Bangladesh government exam question bank. "
        "Use the tools to search questions, quiz users, and retrieve answers. "
        "Questions are in Bengali and English, covering BCS, Bank, and other exams."
    ),
)

# ── Shared MongoDB connection ─────────────────────────────────────────────────
_store: MongoStore | None = None

def get_store() -> MongoStore:
    global _store
    if _store is None:
        _store = MongoStore()
    return _store


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_questions(query: str, exam_type: str = "", limit: int = 10) -> list[dict]:
    """
    Search the question bank by keyword (Bengali or English).

    Args:
        query:     Search keyword — e.g. "মুক্তিযুদ্ধ" or "liberation war"
        exam_type: Optional filter — "BCS", "Bank", "NTRCA", etc. Leave empty for all.
        limit:     Max number of results to return (default 10, max 50).

    Returns:
        List of matched questions with exam name, options, answer, and explanation.
    """
    store = get_store()
    exam_types = [exam_type] if exam_type else None
    results = store.search(query, exam_types=exam_types, limit=min(limit, 50))

    output = []
    for res in results:
        q = res["matched_question"]
        output.append({
            "exam_type":   res.get("exam_type", ""),
            "exam_name":   res.get("exam_name", ""),
            "year":        res.get("year"),
            "q_no":        q.get("q_no"),
            "question":    q.get("question", ""),
            "options":     q.get("options", {}),
            "answer":      q.get("answer", ""),
            "explanation": q.get("explanation", ""),
            "topic":       q.get("topic", ""),
        })
    return output


@mcp.tool()
def get_random_question(exam_type: str = "", topic: str = "") -> dict:
    """
    Get a random MCQ question from the question bank for quizzing.

    Args:
        exam_type: Optional — "BCS", "Bank", "NTRCA", etc.
        topic:     Optional topic filter — e.g. "Bangladesh Affairs", "General Math".

    Returns:
        A single question with options. Answer is hidden — call check_answer() to verify.
    """
    store = get_store()
    records = store.load_all(exam_type=exam_type if exam_type else None)

    # Flatten all questions
    pool = []
    for rec in records:
        for q in rec.get("questions", []):
            if topic and topic.lower() not in q.get("topic", "").lower():
                continue
            pool.append({
                "exam_id":   rec.get("exam_id", ""),
                "exam_name": rec.get("exam_name", ""),
                "exam_type": rec.get("exam_type", ""),
                "year":      rec.get("year"),
                "q_no":      q.get("q_no"),
                "question":  q.get("question", ""),
                "options":   q.get("options", {}),
                "topic":     q.get("topic", ""),
                # Answer intentionally omitted for quizzing
            })

    if not pool:
        return {"error": "No questions found for the given filters."}

    chosen = random.choice(pool)
    chosen["hint"] = "Call check_answer() with exam_id and q_no to see the answer."
    return chosen


@mcp.tool()
def check_answer(exam_id: str, q_no: int) -> dict:
    """
    Reveal the correct answer and explanation for a specific question.

    Args:
        exam_id: The exam_id returned by get_random_question() or list_exams().
        q_no:    The question number (q_no field).

    Returns:
        The correct answer letter and full explanation.
    """
    store = get_store()
    record = store.get_exam(exam_id)
    if not record:
        return {"error": f"Exam '{exam_id}' not found."}

    for q in record.get("questions", []):
        if q.get("q_no") == q_no:
            return {
                "exam_name":   record.get("exam_name", ""),
                "q_no":        q_no,
                "question":    q.get("question", ""),
                "answer":      q.get("answer", ""),
                "explanation": q.get("explanation", ""),
                "topic":       q.get("topic", ""),
            }

    return {"error": f"Question {q_no} not found in exam '{exam_id}'."}


@mcp.tool()
def list_exams(exam_type: str = "") -> list[dict]:
    """
    List all available exams in the question bank.

    Args:
        exam_type: Optional filter — "BCS", "Bank", "NTRCA", etc. Leave empty for all.

    Returns:
        List of exams with name, year, subject, and question count.
    """
    store = get_store()
    index = store.load_index()

    if exam_type:
        index = [e for e in index if e.get("exam_type", "").lower() == exam_type.lower()]

    return [
        {
            "exam_id":        e.get("exam_id", ""),
            "exam_type":      e.get("exam_type", ""),
            "exam_name":      e.get("exam_name", ""),
            "year":           e.get("year"),
            "subject":        e.get("subject", ""),
            "question_count": e.get("question_count", 0),
            "source_url":     e.get("source_url", ""),
        }
        for e in index
    ]


@mcp.tool()
def get_exam_questions(exam_id: str) -> dict:
    """
    Retrieve all questions from a specific exam.

    Args:
        exam_id: The exam_id from list_exams().

    Returns:
        Full exam record with all questions, options, answers, and explanations.
    """
    store = get_store()
    record = store.get_exam(exam_id)
    if not record:
        return {"error": f"Exam '{exam_id}' not found."}

    return {
        "exam_id":    record.get("exam_id", ""),
        "exam_name":  record.get("exam_name", ""),
        "exam_type":  record.get("exam_type", ""),
        "year":       record.get("year"),
        "subject":    record.get("subject", ""),
        "source_url": record.get("source_url", ""),
        "questions":  record.get("questions", []),
    }


@mcp.tool()
def get_stats() -> dict:
    """
    Return summary statistics for the question bank.

    Returns:
        Total exams, total questions, breakdown by exam type and year.
    """
    store = get_store()
    return store.get_stats()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
```

---

## Step 3 — Test with MCP Inspector

Before connecting to any AI, verify your tools work:

```bash
# Install the inspector (one-time)
npm install -g @modelcontextprotocol/inspector

# Run your server through the inspector
npx @modelcontextprotocol/inspector python mcp_server.py
```

Open the URL it prints (usually `http://localhost:5173`) — you'll see a UI where you can call each tool manually and see the JSON responses.

---

## Step 4 — Connect to Claude Desktop

### 1. Find your config file

| OS      | Path |
|---------|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS   | `~/Library/Application Support/Claude/claude_desktop_config.json` |

### 2. Add the MCP server entry

```json
{
  "mcpServers": {
    "bd-question-bank": {
      "command": "E:\\ragib\\projects\\questionbank scrapper\\.venv\\Scripts\\python.exe",
      "args": [
        "E:\\ragib\\projects\\questionbank scrapper\\mcp_server.py"
      ],
      "env": {
        "MONGODB_DSN": "your-mongodb-atlas-dsn-here",
        "MONGODB_DATABASE_QB": "questionbank"
      }
    }
  }
}
```

> **Tip:** Instead of hardcoding `MONGODB_DSN`, you can omit the `env` block entirely if your `.env` file is present in the project directory — python-dotenv will load it automatically.

### 3. Restart Claude Desktop

After saving the config, restart Claude Desktop. You'll see a 🔌 plug icon in the chat input — that means the MCP server is connected.

### 4. Try it in Claude

```
Show me all available exams in the question bank.
```
```
Give me a random BCS question and quiz me.
```
```
Search for questions about মুক্তিযুদ্ধ
```

---

## Step 5 — Connect to Other AI Clients

### Cursor (VS Code-based AI editor)

Add to `.cursor/mcp.json` in your home directory or workspace:

```json
{
  "mcpServers": {
    "bd-question-bank": {
      "command": "E:\\ragib\\projects\\questionbank scrapper\\.venv\\Scripts\\python.exe",
      "args": ["E:\\ragib\\projects\\questionbank scrapper\\mcp_server.py"]
    }
  }
}
```

### Zed Editor

In `~/.config/zed/settings.json`:

```json
{
  "context_servers": {
    "bd-question-bank": {
      "command": {
        "path": "E:\\ragib\\projects\\questionbank scrapper\\.venv\\Scripts\\python.exe",
        "args": ["E:\\ragib\\projects\\questionbank scrapper\\mcp_server.py"]
      }
    }
  }
}
```

### Any client that supports HTTP/SSE transport

Run the server with HTTP transport so any HTTP-capable client (Kimi, OpenAI Assistants, etc.) can reach it:

```python
# At the bottom of mcp_server.py, replace mcp.run() with:
if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8080)
```

Then point the client to `http://localhost:8080/sse`.

---

## Available Tools Reference

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `search_questions` | Full-text search (Bengali + English) | `query`, `exam_type`, `limit` |
| `get_random_question` | Random MCQ for quizzing | `exam_type`, `topic` |
| `check_answer` | Reveal answer + explanation | `exam_id`, `q_no` |
| `list_exams` | All exams with metadata | `exam_type` |
| `get_exam_questions` | All questions from one exam | `exam_id` |
| `get_stats` | Total counts by type/year | — |

---

## Example Conversations

**Quiz mode:**
> **User:** Give me a BCS question on Bangladesh Affairs.
>
> **Claude:** *(calls `get_random_question(exam_type="BCS", topic="Bangladesh Affairs")*
>
> Here's your question from the 44th BCS Preliminary:
>
> **বাংলাদেশের মুক্তিযুদ্ধের সময় ঢাকা কোন সেক্টরে ছিল?**
> - A) ১ নং   B) **২ নং**   C) ৩ নং   D) ৪ নং
>
> What's your answer?

**Search mode:**
> **User:** মুক্তিযুদ্ধ সম্পর্কে প্রশ্ন খোঁজো
>
> **Claude:** *(calls `search_questions(query="মুক্তিযুদ্ধ")`)*
>
> Found 8 questions matching "মুক্তিযুদ্ধ" across BCS and Bank exams…

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: mcp` | Run `uv add mcp` in the project directory |
| `MONGODB_DSN is not set` | Add `MONGODB_DSN` to `.env` or to the `env` block in the Claude config |
| Tool not showing in Claude | Restart Claude Desktop after editing the config |
| Server crashes on start | Run `python mcp_server.py` directly and check the error message |
| Bengali text garbled | Ensure your terminal/client uses UTF-8 encoding |

---

## Project File Layout

```
questionbank scrapper/
├── mcp_server.py          ← MCP server (create this)
├── app.py                 ← Streamlit crawler UI
├── storage/
│   └── mongo_store.py     ← MongoDB layer (used by MCP server)
├── crawler/
├── processors/
├── .env                   ← MONGODB_DSN lives here
└── MCP_TOOLS_GUIDE.md     ← This file
```

---

*Built on [Model Context Protocol](https://modelcontextprotocol.io) · Data scraped from pdf.exambd.net · Stored in MongoDB Atlas*
