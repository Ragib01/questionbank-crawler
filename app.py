"""
Bangladesh Govt Jobs Question Bank Crawler
Streamlit UI — URL-based scraping with MongoDB storage.

Run:  streamlit run app.py
"""

import sys
import os
import json
import time
import threading
import warnings
from datetime import datetime

warnings.filterwarnings("ignore", category=Warning, message=".*urllib3.*")

# ── Windows asyncio fix ───────────────────────────────────────────────────────
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import streamlit as st
import pandas as pd

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BD Question Bank Crawler",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Lazy imports ──────────────────────────────────────────────────────────────
try:
    from config import (ANTHROPIC_API_KEY, EXAM_TYPES,
                        AI_MODEL_FAST, AI_MODEL_SMART, PDF_DIR, OUTPUT_DIR)
    from crawler.url_crawler import URLCrawler
    from processors.ai_extractor import AIExtractor
    from processors.pdf_handler import PDFHandler
    from storage.mongo_store import MongoStore
    from utils import ProgressQueue
    IMPORTS_OK = True
    _IMPORT_ERR = ""
except ImportError as _e:
    IMPORTS_OK = False
    _IMPORT_ERR = str(_e)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main-header { font-size:2rem; font-weight:700; color:#006A4E; margin-bottom:.2rem; }
  .sub-header  { color:#888; font-size:.9rem; margin-bottom:1.5rem; }
  .stat-box    { background:#f0f8f4; border-left:4px solid #006A4E;
                 padding:1rem; border-radius:6px; margin:.5rem 0; text-align:center; }
  .stat-num    { font-size:1.8rem; font-weight:700; color:#006A4E; }
  .q-card      { background:#fafafa; border:1px solid #e0e0e0;
                 border-radius:8px; padding:1rem; margin:.8rem 0; }
  .answer-badge{ background:#006A4E; color:white; padding:2px 10px;
                 border-radius:4px; font-size:.85rem; font-weight:600; }
  .exam-badge  { background:#F42A41; color:white; padding:2px 8px;
                 border-radius:4px; font-size:.8rem; }
  .log-box     { background:#1e1e1e; color:#d4d4d4; font-family:monospace;
                 font-size:.78rem; padding:1rem; border-radius:6px;
                 max-height:320px; overflow-y:auto; white-space:pre-wrap; }
  .url-input input { font-size:1rem !important; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
def _init():
    defaults = {
        "api_key":           ANTHROPIC_API_KEY if IMPORTS_OK else "",
        "crawl_running":     False,
        "crawl_done":        False,
        "progress_pct":      0.0,
        "progress_msg":      "",
        "log_lines":         [],
        "raw_records":       [],
        "pdf_paths":         [],
        "image_paths":       [],
        "last_crawl_url":    "",
        "last_crawl_time":   "",
        "pq":                None,
        "crawl_thread":      None,
        "crawl_result":      None,   # shared dict filled by background thread
        "ai_model":          AI_MODEL_FAST if IMPORTS_OK else "",
        "mongo_ok":          None,   # None = unchecked, True/False after ping
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── MongoDB connection check ───────────────────────────────────────────────────
@st.cache_resource
def _get_store():
    if not IMPORTS_OK:
        return None
    try:
        s = MongoStore()
        ok = s.ping()
        if not ok:
            return None
        # Bust cache if the store is missing new methods (stale cached instance)
        if not hasattr(s, "watchlist_get"):
            _get_store.clear()
            s = MongoStore()
        return s
    except Exception:
        return None


def get_store() -> "MongoStore | None":
    return _get_store()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    api_key_input = st.text_input(
        "Anthropic API Key",
        value=st.session_state.api_key,
        type="password",
        help="Get your key at console.anthropic.com",
    )
    if api_key_input:
        st.session_state.api_key = api_key_input
        os.environ["ANTHROPIC_API_KEY"] = api_key_input

    st.divider()

    # MongoDB status
    store = get_store()
    if store is not None:
        st.success("✅ MongoDB Connected")
    else:
        st.error("❌ MongoDB not connected\nCheck MONGODB_DSN in .env")

    st.divider()

    st.markdown("### AI Model")
    ai_model = st.selectbox(
        "Model",
        options=[AI_MODEL_FAST, AI_MODEL_SMART] if IMPORTS_OK else ["—"],
        index=0,
        help="Haiku = fast & cheap · Sonnet = smarter extraction",
        label_visibility="collapsed",
    )
    if IMPORTS_OK:
        st.session_state.ai_model = ai_model

    if st.button("🔄 Reconnect DB", help="Clear cached connection and reconnect"):
        _get_store.clear()
        st.rerun()

    st.divider()

    # Quick stats
    if store:
        stats = store.get_stats()
        st.markdown("### 📊 Database Stats")
        st.markdown(f"**{stats.get('total_questions', 0):,}** questions stored")
        st.markdown(f"**{stats.get('total_exams', 0)}** exam records")


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-header">📚 BD Govt Question Bank Crawler</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Enter any exam question website URL — the crawler extracts MCQs and stores them in MongoDB</div>',
    unsafe_allow_html=True,
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_crawl, tab_watchlist, tab_browse, tab_search, tab_pdfs, tab_export = st.tabs(
    ["🕷️ Crawl", "🗂️ Watchlist", "📖 Browse", "🔍 Search", "📄 PDFs & Images", "💾 Export"]
)


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — CRAWL
# ════════════════════════════════════════════════════════════════════════════
with tab_crawl:
    if not IMPORTS_OK:
        st.error(f"Dependency import error: {_IMPORT_ERR}\n\nRun `setup.bat` first.")
        st.stop()

    # ── Stats row ─────────────────────────────────────────────────────────────
    stats = store.get_stats() if store else {}
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="stat-box"><div class="stat-num">{stats.get("total_exams", 0)}</div>Exams Saved</div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="stat-box"><div class="stat-num">{stats.get("total_questions", 0):,}</div>Questions</div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="stat-box"><div class="stat-num">{len(list(PDF_DIR.rglob("*.pdf")))}</div>PDFs Downloaded</div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="stat-box"><div class="stat-num">{st.session_state.last_crawl_time or "—"}</div>Last Crawl</div>', unsafe_allow_html=True)

    st.divider()

    # ── URL input ─────────────────────────────────────────────────────────────
    st.markdown("### 🌐 Enter Website URL")
    url_input = st.text_input(
        "URL",
        placeholder="https://www.exambd.net/2024/04/45th-bcs-preliminary-question-solution.html",
        label_visibility="collapsed",
        key="url_input",
    )

    # ── Options ───────────────────────────────────────────────────────────────
    st.markdown("### ⚙️ Crawl Options")
    opt_col1, opt_col2, opt_col3 = st.columns([2, 1, 1])

    with opt_col1:
        exam_type = st.selectbox(
            "Exam Type",
            options=EXAM_TYPES + ["General / Other"],
            index=0,
            help="Tag the crawled questions with this exam type",
        )
        max_pages = st.slider(
            "Max pages to crawl",
            min_value=1, max_value=50, value=10, step=1,
            help="Number of pages to visit (1 = just the entered URL, more = follow sub-links)",
        )

    with opt_col2:
        st.markdown("**Content to scrape**")
        download_pdfs   = st.checkbox("📄 Download PDFs",   value=True,
                                       help="Download PDF files found on the page(s)")
        download_images = st.checkbox("🖼️ Download Images", value=False,
                                       help="Download images found on the page(s)")
        use_playwright  = st.checkbox("🎭 Use Playwright",  value=True,
                                       help="Use browser automation for JS-heavy pages")

    with opt_col3:
        st.markdown("**AI Processing**")
        ai_process = st.checkbox("🤖 AI Extract Questions", value=True,
                                  help="Use Claude to extract structured MCQs from scraped text")
        st.markdown(f"<small>Model: `{st.session_state.ai_model}`</small>", unsafe_allow_html=True)

    st.divider()

    # ── Start button ──────────────────────────────────────────────────────────
    can_crawl = bool(url_input and url_input.startswith("http") and
                     not st.session_state.crawl_running and
                     store is not None)

    if not store:
        st.warning("MongoDB is not connected. Cannot start crawl.")

    start_btn = st.button(
        "🚀 Start Crawling",
        disabled=not can_crawl,
        use_container_width=True,
        type="primary",
    )

    # ── Progress area ─────────────────────────────────────────────────────────
    prog_msg   = st.empty()
    prog_bar   = st.empty()
    log_area   = st.empty()

    # ── Launch crawl in background thread ─────────────────────────────────────
    if start_btn and can_crawl:
        if not st.session_state.api_key:
            st.error("Enter your Anthropic API Key in the sidebar first.")
        else:
            import config as _cfg
            _cfg.ANTHROPIC_API_KEY = st.session_state.api_key
            os.environ["ANTHROPIC_API_KEY"] = st.session_state.api_key

            # Add URL to watchlist (so it gets marked when done)
            try:
                _wl_store = MongoStore()
                _wl_store.watchlist_add(url_input, exam_type)
            except Exception:
                pass

            pq = ProgressQueue()
            result_holder = {"done": False, "raw_records": [], "pdf_paths": [], "image_paths": [], "structured": []}

            # Capture all session-state values NOW (before the thread starts).
            # st.session_state is NOT thread-safe — accessing it inside the
            # background thread raises errors and silently kills AI + MongoDB save.
            _ai_model   = st.session_state.ai_model
            _api_key    = st.session_state.api_key

            # Snapshot all widget values too (closures capture mutable references)
            _url         = url_input
            _exam_type   = exam_type
            _max_pages   = max_pages
            _dl_pdfs     = download_pdfs
            _dl_images   = download_images
            _use_pw      = use_playwright
            _ai_process  = ai_process

            def _crawl_job():
                import traceback as _tb
                try:
                    # Set API key in environment for this thread
                    os.environ["ANTHROPIC_API_KEY"] = _api_key

                    crawler = URLCrawler(pq, use_playwright=_use_pw)
                    crawl_out = crawler.crawl(
                        start_url=_url,
                        exam_type=_exam_type,
                        max_pages=_max_pages,
                        download_pdfs=_dl_pdfs,
                        download_images=_dl_images,
                    )
                    result_holder["raw_records"]  = crawl_out["raw_records"]
                    result_holder["pdf_paths"]    = crawl_out["pdf_paths"]
                    result_holder["image_paths"]  = crawl_out["image_paths"]

                    # AI extraction
                    if _ai_process and crawl_out["raw_records"]:
                        pq.put("log", "AI",
                               f"Extracting questions from {len(crawl_out['raw_records'])} pages...")
                        extractor = AIExtractor(pq, model=_ai_model)
                        structured = extractor.extract_batch(crawl_out["raw_records"])
                        result_holder["structured"] = structured
                        total_q = sum(len(s.get("questions", [])) for s in structured)
                        pq.put("log", "AI",
                               f"Extracted {len(structured)} records, {total_q} questions total")

                        # Save to MongoDB
                        if structured:
                            pq.put("log", "MongoDB", "Saving to MongoDB...")
                            _store = MongoStore()
                            saved_ids = _store.save_batch(structured)
                            _store.save_session({
                                "url":             _url,
                                "exam_type":       _exam_type,
                                "max_pages":       _max_pages,
                                "pages_crawled":   len(crawl_out["raw_records"]),
                                "exams_saved":     len(saved_ids),
                                "questions_saved": total_q,
                                "pdf_paths":       crawl_out["pdf_paths"],
                                "image_paths":     crawl_out["image_paths"],
                            })
                            _store.watchlist_mark_crawled(_url, questions_saved=total_q)
                            pq.put("log", "MongoDB",
                                   f"✅ Saved {len(saved_ids)} exam records ({total_q} questions)")
                        else:
                            pq.put("log", "AI", "⚠️ No structured records to save — no questions extracted")
                    else:
                        if not _ai_process:
                            pq.put("log", "AI", "AI processing skipped (checkbox unchecked)")
                        else:
                            pq.put("log", "AI", "⚠️ No raw records to process")

                except Exception as exc:
                    pq.put("error", "Crawler", f"Fatal error: {exc}")
                    pq.put("log", "Crawler", _tb.format_exc())
                finally:
                    result_holder["done"] = True
                    pq.put("done", "Manager", "Crawl job finished")

            t = threading.Thread(target=_crawl_job, daemon=True)
            t.start()

            st.session_state.pq            = pq
            st.session_state.crawl_thread  = t
            st.session_state.crawl_result  = result_holder
            st.session_state.crawl_running = True
            st.session_state.crawl_done    = False
            st.session_state.progress_pct  = 0.0
            st.session_state.progress_msg  = "Starting..."
            st.session_state.log_lines     = []
            st.session_state.last_crawl_url = url_input
            st.rerun()

    # ── Poll progress while running ───────────────────────────────────────────
    if st.session_state.crawl_running:
        pq     = st.session_state.pq
        result = st.session_state.crawl_result

        if pq:
            for msg in pq.get_all():
                mtype = msg["type"]
                line  = f"[{msg['ts']}] [{msg['source']}] {msg['message']}"
                st.session_state.log_lines.append(line)

                if mtype == "progress":
                    st.session_state.progress_pct = msg.get("percent", 0)
                    st.session_state.progress_msg = msg["message"]
                elif mtype == "done":
                    st.session_state.crawl_running = False
                    st.session_state.crawl_done    = True
                    st.session_state.last_crawl_time = datetime.now().strftime("%H:%M")

        if result and result.get("done") and st.session_state.crawl_running:
            st.session_state.crawl_running = False
            st.session_state.crawl_done    = True
            st.session_state.last_crawl_time = datetime.now().strftime("%H:%M")

        pct = min(st.session_state.progress_pct / 100, 1.0)
        prog_msg.markdown(f"⏳ **{st.session_state.progress_msg}**")
        prog_bar.progress(pct)
        log_html = "\n".join(st.session_state.log_lines[-50:])
        log_area.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

        if st.session_state.crawl_running:
            time.sleep(1.5)
            st.rerun()

    # ── Show results after crawl ──────────────────────────────────────────────
    if st.session_state.crawl_done:
        result = st.session_state.crawl_result or {}
        structured = result.get("structured", [])
        raw = result.get("raw_records", [])
        pdf_paths = result.get("pdf_paths", [])
        img_paths = result.get("image_paths", [])

        total_q = sum(len(s.get("questions", [])) for s in structured)
        prog_msg.success(
            f"✅ Crawl complete! Pages: {len(raw)} · Exam records: {len(structured)} · "
            f"Questions: {total_q} · PDFs: {len(pdf_paths)} · Images: {len(img_paths)}"
        )
        prog_bar.progress(1.0)
        log_html = "\n".join(st.session_state.log_lines[-50:])
        log_area.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)
        st.session_state.crawl_done = False

    # ── Previous log ─────────────────────────────────────────────────────────
    if st.session_state.log_lines and not st.session_state.crawl_running:
        with st.expander("📋 Last Crawl Log", expanded=False):
            log_html = "\n".join(st.session_state.log_lines)
            st.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

    # ── Recent crawl sessions ─────────────────────────────────────────────────
    if store:
        sessions = store.get_recent_sessions(5)
        if sessions:
            st.divider()
            st.markdown("### 🕐 Recent Crawl Sessions")
            df_s = pd.DataFrame([{
                "URL":        s.get("url", "")[:60],
                "Exam Type":  s.get("exam_type", ""),
                "Pages":      s.get("pages_crawled", 0),
                "Questions":  s.get("questions_saved", 0),
                "PDFs":       len(s.get("pdf_paths", [])),
                "Images":     len(s.get("image_paths", [])),
                "Time":       str(s.get("created_at", ""))[:16],
            } for s in sessions])
            st.dataframe(df_s, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — URL WATCHLIST
# ════════════════════════════════════════════════════════════════════════════
with tab_watchlist:
    store = get_store()
    if not store:
        st.warning("MongoDB not connected.")
    else:
        st.markdown("### 🗂️ URL Watchlist")
        st.markdown(
            "Track which URLs have been scraped and which are still pending. "
            "Add any URL here — it will be marked ✅ Done automatically when crawled."
        )

        # ── Add URL form ──────────────────────────────────────────────────
        with st.form("wl_add_form", clear_on_submit=True):
            wl_col1, wl_col2, wl_col3 = st.columns([4, 2, 1])
            with wl_col1:
                wl_url = st.text_input(
                    "URL",
                    placeholder="https://pdf.exambd.net/...",
                    label_visibility="collapsed",
                )
            with wl_col2:
                wl_type = st.selectbox(
                    "Exam Type",
                    options=EXAM_TYPES + ["General / Other"] if IMPORTS_OK else ["General / Other"],
                    label_visibility="collapsed",
                )
            with wl_col3:
                wl_submit = st.form_submit_button("➕ Add", use_container_width=True)

        if wl_submit and wl_url and wl_url.startswith("http"):
            store.watchlist_add(wl_url.strip(), wl_type)
            st.success(f"Added to watchlist: {wl_url[:70]}")
            st.rerun()
        elif wl_submit:
            st.warning("Enter a valid URL starting with http.")

        st.divider()

        # ── Load and display watchlist ────────────────────────────────────
        wl_entries = store.watchlist_get()

        if not wl_entries:
            st.info("Watchlist is empty. Add URLs above or start a crawl — URLs are added automatically.")
        else:
            pending = [e for e in wl_entries if not e.get("last_crawled_at")]
            done    = [e for e in wl_entries if e.get("last_crawled_at")]

            st.markdown(
                f"**{len(wl_entries)} URL(s) total · "
                f"⏳ {len(pending)} pending · "
                f"✅ {len(done)} done**"
            )

            # ── Summary table ─────────────────────────────────────────────
            rows = []
            for e in wl_entries:
                crawled = e.get("last_crawled_at")
                rows.append({
                    "Status":        "✅ Done" if crawled else "⏳ Pending",
                    "URL":           e.get("url", ""),
                    "Exam Type":     e.get("exam_type", ""),
                    "Questions":     e.get("questions_saved", 0),
                    "Crawl Count":   e.get("crawl_count", 0),
                    "Last Crawled":  str(crawled)[:16] if crawled else "—",
                    "Added":         str(e.get("added_at", ""))[:16],
                })
            df_wl = pd.DataFrame(rows)
            st.dataframe(df_wl, use_container_width=True, hide_index=True)

            # ── Pending section ───────────────────────────────────────────
            if pending:
                st.divider()
                st.markdown("#### ⏳ Pending URLs")
                st.caption("These URLs have never been crawled. Click 'Crawl Now' to go to the Crawl tab with the URL pre-filled.")
                for e in pending:
                    pc1, pc2, pc3 = st.columns([5, 2, 1])
                    pc1.markdown(f"🔗 `{e.get('url','')[:80]}`")
                    pc2.markdown(f"<small>{e.get('exam_type','')}</small>", unsafe_allow_html=True)
                    btn_key = f"wl_crawl_{hash(e.get('url',''))}"
                    if pc3.button("Crawl Now", key=btn_key):
                        st.session_state["url_input"] = e.get("url", "")
                        st.info(f"URL pre-filled in Crawl tab: {e.get('url','')[:60]}\n\nGo to the **🕷️ Crawl** tab and click **Start Crawling**.")

            # ── Done section ──────────────────────────────────────────────
            if done:
                st.divider()
                st.markdown("#### ✅ Done URLs")
                for e in done:
                    dc1, dc2, dc3, dc4 = st.columns([5, 2, 1, 1])
                    dc1.markdown(f"🔗 `{e.get('url','')[:75]}`")
                    dc2.markdown(
                        f"<small>{str(e.get('last_crawled_at',''))[:16]}</small>",
                        unsafe_allow_html=True,
                    )
                    dc3.markdown(
                        f"<small>**{e.get('questions_saved', 0)}** Q</small>",
                        unsafe_allow_html=True,
                    )
                    rm_key = f"wl_rm_{hash(e.get('url',''))}"
                    if dc4.button("🗑️", key=rm_key, help="Remove from watchlist"):
                        store.watchlist_remove(e.get("url", ""))
                        st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — BROWSE QUESTIONS
# ════════════════════════════════════════════════════════════════════════════
with tab_browse:
    store = get_store()
    if not store:
        st.warning("MongoDB not connected.")
    else:
        index = store.load_index()

        if not index:
            st.info("No questions saved yet. Run a crawl first.")
        else:
            # Filter row
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                all_types = sorted({e.get("exam_type", "") for e in index if e.get("exam_type")})
                type_filter = st.selectbox("Exam Type", ["All"] + all_types, key="br_type")
            with fc2:
                years = sorted({str(e.get("year") or "") for e in index if e.get("year")}, reverse=True)
                year_filter = st.selectbox("Year", ["All"] + years, key="br_year")
            with fc3:
                names = sorted({e.get("exam_name", "") for e in index if e.get("exam_name")})
                name_filter = st.selectbox("Exam Name", ["All"] + names, key="br_name")

            filtered = index
            if type_filter != "All":
                filtered = [e for e in filtered if e.get("exam_type") == type_filter]
            if year_filter != "All":
                filtered = [e for e in filtered if str(e.get("year") or "") == year_filter]
            if name_filter != "All":
                filtered = [e for e in filtered if e.get("exam_name") == name_filter]

            st.markdown(f"**{len(filtered)} exam record(s) found · "
                        f"{sum(e.get('question_count', 0) for e in filtered)} questions**")

            if filtered:
                df = pd.DataFrame([{
                    "Exam Type": e.get("exam_type", ""),
                    "Exam Name": e.get("exam_name", ""),
                    "Year":      e.get("year", ""),
                    "Subject":   e.get("subject", ""),
                    "Questions": e.get("question_count", 0),
                    "Source":    e.get("source_url", "")[:50],
                    "Crawled":   str(e.get("crawled_at", ""))[:16],
                } for e in filtered])
                st.dataframe(df, use_container_width=True, hide_index=True)

                st.divider()
                sel_name = st.selectbox(
                    "View questions from exam:",
                    options=[e.get("exam_name") or e.get("exam_id", f"#{i}") for i, e in enumerate(filtered)],
                    key="br_sel",
                )
                sel_idx = next(
                    (i for i, e in enumerate(filtered)
                     if (e.get("exam_name") or e.get("exam_id", f"#{i}")) == sel_name), None
                )
                if sel_idx is not None:
                    exam_id = filtered[sel_idx].get("exam_id", "")
                    record = store.get_exam(exam_id) if exam_id else None
                    if record:
                        questions = record.get("questions", [])
                        st.markdown(f"### {record.get('exam_name', '?')} — {len(questions)} questions")
                        for q in questions:
                            opts = q.get("options", {})
                            opts_str = "&nbsp;&nbsp;".join(
                                f"<b>{k}.</b> {v}" for k, v in opts.items()
                            ) if opts else ""
                            topic = q.get("topic", "")
                            expl  = q.get("explanation", "")
                            st.markdown(f"""
<div class="q-card">
<b>Q{q.get('q_no', '')}.</b> {q.get('question', '')}
<br><br>{opts_str}
<br><br>
<span class="answer-badge">Answer: {q.get('answer', '')}</span>
{"&nbsp;&nbsp;<small><i>" + topic + "</i></small>" if topic else ""}
{"<br><small>📝 " + expl + "</small>" if expl else ""}
</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — SEARCH
# ════════════════════════════════════════════════════════════════════════════
with tab_search:
    store = get_store()
    if not store:
        st.warning("MongoDB not connected.")
    else:
        st.markdown("### 🔍 Search Questions")
        sc1, sc2 = st.columns([3, 1])
        with sc1:
            q_text = st.text_input(
                "Search",
                placeholder="Type in English or Bengali — e.g.  মুক্তিযুদ্ধ  or  liberation war",
                label_visibility="collapsed",
                key="srch_q",
            )
        with sc2:
            all_types2 = [e.get("exam_type", "") for e in store.load_index()]
            all_types2 = sorted(set(t for t in all_types2 if t))
            srch_types = st.multiselect("Exam Types", all_types2,
                                         default=all_types2, key="srch_types")

        if q_text:
            with st.spinner("Searching MongoDB..."):
                results = store.search(q_text, exam_types=srch_types or None)

            if not results:
                st.warning("No matching questions found.")
            else:
                st.success(f"Found {len(results)} matching question(s).")
                for res in results[:60]:
                    q   = res.get("matched_question", {})
                    opts = q.get("options", {})
                    opts_str = "&nbsp;&nbsp;".join(
                        f"<b>{k}.</b> {v}" for k, v in opts.items()
                    ) if opts else ""
                    st.markdown(f"""
<div class="q-card">
<span class="exam-badge">{res.get('exam_type','')}</span>
<small> {res.get('exam_name','')} {res.get('year','') or ''}</small>
<br><br>
<b>Q{q.get('q_no','')}.</b> {q.get('question','')}
<br><br>{opts_str}
<br><br>
<span class="answer-badge">Answer: {q.get('answer','')}</span>
</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — PDFs & IMAGES
# ════════════════════════════════════════════════════════════════════════════
with tab_pdfs:
    st.markdown("### 📄 Downloaded PDFs")
    all_pdfs = list(PDF_DIR.rglob("*.pdf")) if IMPORTS_OK else []
    if not all_pdfs:
        st.info("No PDFs downloaded yet. Enable 'Download PDFs' when crawling.")
    else:
        st.success(f"{len(all_pdfs)} PDF file(s)")
        by_type: dict = {}
        for p in all_pdfs:
            etype = p.parent.name.replace("_", " ")
            by_type.setdefault(etype, []).append(p)
        for etype, pdfs in sorted(by_type.items()):
            with st.expander(f"**{etype}** — {len(pdfs)} file(s)"):
                for pdf in sorted(pdfs, key=lambda x: x.name):
                    ca, cb, cc = st.columns([4, 1, 1])
                    size_kb = pdf.stat().st_size // 1024
                    ca.markdown(f"📄 **{pdf.name}** `{size_kb} KB`")
                    with open(pdf, "rb") as fh:
                        cb.download_button("⬇ Download", data=fh, file_name=pdf.name,
                                           mime="application/pdf", key=f"dl_{pdf.stem}")
                    if cc.button("Preview", key=f"pv_{pdf.stem}"):
                        handler = PDFHandler()
                        txt = handler.extract_text(pdf)
                        st.text_area("Text", txt[:3000], height=250, key=f"ta_{pdf.stem}")

    st.divider()
    st.markdown("### 🖼️ Downloaded Images")
    img_root = OUTPUT_DIR / "images" if IMPORTS_OK else None
    all_imgs = list(img_root.rglob("*.*")) if (img_root and img_root.exists()) else []
    img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    all_imgs = [p for p in all_imgs if p.suffix.lower() in img_exts]
    if not all_imgs:
        st.info("No images downloaded yet. Enable 'Download Images' when crawling.")
    else:
        st.success(f"{len(all_imgs)} image(s) downloaded")
        cols = st.columns(5)
        for i, img in enumerate(all_imgs[:50]):
            with cols[i % 5]:
                try:
                    st.image(str(img), caption=img.name[:20], use_container_width=True)
                except Exception:
                    st.markdown(f"📎 {img.name}")


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — EXPORT
# ════════════════════════════════════════════════════════════════════════════
with tab_export:
    store = get_store()
    if not store:
        st.warning("MongoDB not connected.")
    else:
        stats = store.get_stats()

        ec1, ec2 = st.columns(2)
        with ec1:
            st.markdown("**Questions by Exam Type**")
            if stats.get("by_exam_type"):
                df_t = pd.DataFrame(
                    stats["by_exam_type"].items(), columns=["Exam Type", "Questions"]
                ).sort_values("Questions", ascending=False)
                st.dataframe(df_t, use_container_width=True, hide_index=True)
            else:
                st.info("No data yet.")
        with ec2:
            st.markdown("**Questions by Year**")
            if stats.get("by_year"):
                df_y = pd.DataFrame(
                    stats["by_year"].items(), columns=["Year", "Questions"]
                ).head(15)
                st.dataframe(df_y, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Download JSON")

        ex1, ex2 = st.columns(2)
        with ex1:
            st.markdown("**Export all**")
            if st.button("Prepare Full Export", key="exp_all"):
                with st.spinner("Loading from MongoDB..."):
                    data = store.export_all_json()
                st.download_button(
                    "⬇ all_questions.json",
                    data=data.encode("utf-8"),
                    file_name=f"all_questions_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                    mime="application/json",
                    key="dl_all",
                )
        with ex2:
            st.markdown("**Export by exam type**")
            all_types3 = sorted({e.get("exam_type", "") for e in store.load_index() if e.get("exam_type")})
            if all_types3:
                etype_exp = st.selectbox("Type", all_types3, key="exp_type")
                if st.button(f"Prepare {etype_exp}", key="exp_type_btn"):
                    with st.spinner("Loading..."):
                        data = store.export_by_type(etype_exp)
                    st.download_button(
                        f"⬇ {etype_exp.replace(' ','_')}.json",
                        data=data.encode("utf-8"),
                        file_name=f"{etype_exp.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.json",
                        mime="application/json",
                        key="dl_type",
                    )
