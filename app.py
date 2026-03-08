"""
Bangladesh Govt Jobs Question Bank Crawler
Streamlit UI — Windows-compatible, no Docker required.

Run:  streamlit run app.py
"""

import sys
import os
import json
import time
import threading
from pathlib import Path
from datetime import datetime

# ── Windows asyncio fix (must be before any asyncio import) ──────────────────
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import streamlit as st
import pandas as pd

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BD Govt Question Bank",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Lazy imports (so Streamlit can start even if deps missing) ────────────────
try:
    from config import (ANTHROPIC_API_KEY, EXAM_TYPES, CRAWL_TARGETS,
                        AI_MODEL_FAST, AI_MODEL_SMART, PDF_DIR, QUESTIONS_DIR)
    from crawler import CrawlerManager
    from processors import AIExtractor, PDFHandler
    from storage import QuestionStore
    from utils import ProgressQueue, get_logger
    IMPORTS_OK = True
except ImportError as _e:
    IMPORTS_OK = False
    _IMPORT_ERR = str(_e)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; color: #006A4E; margin-bottom: 0.2rem; }
    .sub-header  { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
    .stat-box    { background: #f0f8f4; border-left: 4px solid #006A4E;
                   padding: 1rem; border-radius: 6px; margin: 0.5rem 0; }
    .q-card      { background: #fafafa; border: 1px solid #e0e0e0;
                   border-radius: 8px; padding: 1rem; margin: 0.8rem 0; }
    .answer-badge { background: #006A4E; color: white; padding: 2px 8px;
                    border-radius: 4px; font-size: 0.85rem; font-weight: 600; }
    .exam-badge  { background: #F42A41; color: white; padding: 2px 8px;
                   border-radius: 4px; font-size: 0.8rem; }
    .log-box     { background: #1e1e1e; color: #d4d4d4; font-family: monospace;
                   font-size: 0.8rem; padding: 1rem; border-radius: 6px;
                   max-height: 300px; overflow-y: auto; }
</style>
""", unsafe_allow_html=True)


# ── Session state init ────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "api_key":          ANTHROPIC_API_KEY if IMPORTS_OK else "",
        "crawl_running":    False,
        "crawl_done":       False,
        "progress_pct":     0.0,
        "progress_msg":     "",
        "log_lines":        [],
        "raw_records":      [],
        "structured_records": [],
        "pdf_paths":        [],
        "last_crawl_time":  None,
        "pq":               None,
        "manager":          None,
        "ai_extractor":     None,
        "ai_model":         AI_MODEL_FAST if IMPORTS_OK else "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    # API Key
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

    # Exam type selection
    st.markdown("### Exam Types")
    selected_types = []
    for etype in (EXAM_TYPES if IMPORTS_OK else []):
        if st.checkbox(etype, value=True, key=f"chk_{etype}"):
            selected_types.append(etype)

    st.divider()

    # Options
    st.markdown("### Options")
    use_playwright = st.toggle("Use Playwright (JS pages)", value=True,
                               help="Disable if Playwright/Chromium is not installed")
    download_pdfs  = st.toggle("Download PDFs", value=True,
                               help="Download PDF question papers found on pages")
    ai_model_choice = st.selectbox(
        "AI Model",
        options=[AI_MODEL_FAST, AI_MODEL_SMART] if IMPORTS_OK else ["—"],
        index=0,
        help="Fast (Haiku) = cheaper, Smart (Sonnet) = better extraction",
    )
    if IMPORTS_OK:
        st.session_state.ai_model = ai_model_choice

    max_pages = st.slider("Max pages per site", 5, 50, 20, step=5)

    st.divider()

    # Crawl button
    crawl_btn = st.button(
        "🚀 Start Crawling",
        disabled=st.session_state.crawl_running or not IMPORTS_OK or not selected_types,
        use_container_width=True,
        type="primary",
    )

    if not IMPORTS_OK:
        st.error(f"Import error: {_IMPORT_ERR}\nRun setup.bat first.")


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-header">📚 Bangladesh Govt Question Bank</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Crawl BCS • Bank • Ministry • Primary Teacher • NTRCA exam questions</div>',
            unsafe_allow_html=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_crawl, tab_browse, tab_search, tab_pdfs, tab_export = st.tabs(
    ["🕷️ Crawl", "📖 Browse Questions", "🔍 Search", "📄 PDFs", "💾 Export"]
)


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — CRAWL
# ════════════════════════════════════════════════════════════════════════════
with tab_crawl:
    col1, col2, col3, col4 = st.columns(4)

    store = QuestionStore() if IMPORTS_OK else None
    stats = store.get_stats() if store else {}

    with col1:
        st.markdown(f'<div class="stat-box"><b>{stats.get("total_exams", 0)}</b><br>Exams Saved</div>',
                    unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-box"><b>{stats.get("total_questions", 0)}</b><br>Questions Saved</div>',
                    unsafe_allow_html=True)
    with col3:
        pdf_count = len(list(PDF_DIR.rglob("*.pdf"))) if IMPORTS_OK else 0
        st.markdown(f'<div class="stat-box"><b>{pdf_count}</b><br>PDFs Downloaded</div>',
                    unsafe_allow_html=True)
    with col4:
        last = st.session_state.last_crawl_time or "Never"
        st.markdown(f'<div class="stat-box"><b>{last}</b><br>Last Crawl</div>',
                    unsafe_allow_html=True)

    st.divider()

    # Progress section
    progress_placeholder = st.empty()
    progress_bar         = st.empty()
    log_placeholder      = st.empty()

    # ── Start crawl when button pressed ──────────────────────────────────────
    if crawl_btn and IMPORTS_OK and selected_types:
        if not st.session_state.api_key:
            st.error("Please enter your Anthropic API Key in the sidebar.")
        else:
            # Update config with current API key
            import config as _cfg
            _cfg.ANTHROPIC_API_KEY = st.session_state.api_key
            _cfg.MAX_PAGES_PER_SITE = max_pages
            os.environ["ANTHROPIC_API_KEY"] = st.session_state.api_key

            pq = ProgressQueue()
            manager = CrawlerManager(
                progress_queue=pq,
                exam_types=selected_types,
                use_playwright=use_playwright,
                download_pdfs=download_pdfs,
            )
            st.session_state.pq             = pq
            st.session_state.manager        = manager
            st.session_state.crawl_running  = True
            st.session_state.crawl_done     = False
            st.session_state.progress_pct   = 0.0
            st.session_state.progress_msg   = "Starting..."
            st.session_state.log_lines      = []
            st.session_state.raw_records    = []
            st.session_state.structured_records = []
            st.session_state.pdf_paths      = []

            manager.start()
            st.rerun()

    # ── Poll loop while crawl is running ─────────────────────────────────────
    if st.session_state.crawl_running:
        pq      = st.session_state.pq
        manager = st.session_state.manager

        # Drain messages
        if pq:
            for msg in pq.get_all():
                mtype = msg["type"]
                line  = f"[{msg['ts']}] [{msg['source']}] {msg['message']}"
                st.session_state.log_lines.append(line)

                if mtype == "progress":
                    st.session_state.progress_pct = msg["percent"]
                    st.session_state.progress_msg = msg["message"]
                elif mtype == "error":
                    st.session_state.log_lines.append(f"  *** ERROR: {msg['message']}")
                elif mtype == "done":
                    st.session_state.crawl_running = False
                    st.session_state.crawl_done    = True
                    st.session_state.raw_records   = manager.get_results()
                    st.session_state.last_crawl_time = datetime.now().strftime("%H:%M")

        # Check if manager finished
        if manager and manager.is_done() and st.session_state.crawl_running:
            st.session_state.crawl_running = False
            st.session_state.crawl_done    = True
            st.session_state.raw_records   = manager.get_results()
            st.session_state.last_crawl_time = datetime.now().strftime("%H:%M")

        # Render progress
        pct = st.session_state.progress_pct / 100
        progress_placeholder.markdown(f"**{st.session_state.progress_msg}**")
        progress_bar.progress(min(pct, 1.0))

        log_html = "<br>".join(st.session_state.log_lines[-40:])
        log_placeholder.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

        if st.session_state.crawl_running:
            time.sleep(1.5)
            st.rerun()

    # ── Post-crawl: AI processing ─────────────────────────────────────────────
    if st.session_state.crawl_done and st.session_state.raw_records:
        raw = st.session_state.raw_records
        progress_placeholder.success(f"Crawl complete! {len(raw)} raw pages collected.")
        progress_bar.progress(1.0)

        # AI extraction step
        with st.spinner(f"AI extracting questions from {len(raw)} pages..."):
            extractor = AIExtractor(
                progress_queue=st.session_state.pq,
                model=st.session_state.ai_model,
            )
            structured = extractor.extract_batch(raw)
            st.session_state.structured_records = structured

            # Save to disk
            if store and structured:
                saved_paths = store.save_batch(structured)
                st.success(f"Saved {len(saved_paths)} exam records to disk.")

        # PDF download step
        if download_pdfs:
            all_pdf_urls = []
            for rec in raw:
                for pdf_url in rec.get("pdf_links", []):
                    all_pdf_urls.append((pdf_url, rec.get("exam_type", "misc")))

            if all_pdf_urls:
                with st.spinner(f"Downloading {len(all_pdf_urls)} PDFs..."):
                    pdf_handler = PDFHandler(progress_queue=st.session_state.pq)
                    downloaded = []
                    for url, etype in all_pdf_urls[:50]:  # cap at 50
                        p = pdf_handler.download(url, etype)
                        if p:
                            downloaded.append(p)
                    st.session_state.pdf_paths = downloaded
                    if downloaded:
                        st.info(f"Downloaded {len(downloaded)} PDFs.")
                        # Extract text from PDFs and AI-process them too
                        with st.spinner("Extracting text from PDFs..."):
                            for pdf_path in downloaded:
                                pdf_text = pdf_handler.extract_text(pdf_path)
                                if pdf_text and len(pdf_text) > 100:
                                    etype = PDFHandler.get_exam_type_from_path(pdf_path)
                                    pdf_rec = extractor.extract_questions(
                                        raw_text=pdf_text,
                                        exam_type=etype,
                                        source_url=str(pdf_path),
                                    )
                                    pdf_rec["pdf_path"] = str(pdf_path)
                                    if pdf_rec.get("questions"):
                                        store.save(pdf_rec)

        st.session_state.crawl_done = False
        st.rerun()

    # ── Show log if available ─────────────────────────────────────────────────
    if st.session_state.log_lines and not st.session_state.crawl_running:
        with st.expander("View Crawl Log", expanded=False):
            log_html = "<br>".join(st.session_state.log_lines)
            st.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — BROWSE QUESTIONS
# ════════════════════════════════════════════════════════════════════════════
with tab_browse:
    if not IMPORTS_OK:
        st.warning("Dependencies not loaded.")
    else:
        store = QuestionStore()
        index = store.load_index()

        if not index:
            st.info("No questions saved yet. Run a crawl first.")
        else:
            # Filter controls
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                type_filter = st.selectbox("Exam Type", ["All"] + EXAM_TYPES, key="browse_type")
            with col_f2:
                years = sorted({str(e.get("year") or "") for e in index if e.get("year")}, reverse=True)
                year_filter = st.selectbox("Year", ["All"] + years, key="browse_year")
            with col_f3:
                exam_names = sorted({e.get("exam_name", "") for e in index if e.get("exam_name")})
                name_filter = st.selectbox("Exam Name", ["All"] + exam_names, key="browse_name")

            # Apply filters
            filtered = index
            if type_filter != "All":
                filtered = [e for e in filtered if e.get("exam_type") == type_filter]
            if year_filter != "All":
                filtered = [e for e in filtered if str(e.get("year") or "") == year_filter]
            if name_filter != "All":
                filtered = [e for e in filtered if e.get("exam_name") == name_filter]

            st.markdown(f"**{len(filtered)} exam paper(s) found**")

            if filtered:
                # Summary table
                df = pd.DataFrame([{
                    "Exam Type":   e.get("exam_type", ""),
                    "Exam Name":   e.get("exam_name", ""),
                    "Year":        e.get("year", ""),
                    "Subject":     e.get("subject", ""),
                    "Questions":   e.get("question_count", 0),
                    "Crawled At":  e.get("crawled_at", "")[:16],
                } for e in filtered])
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Drill into individual exam
                st.divider()
                selected_exam = st.selectbox(
                    "View questions from:",
                    options=[e.get("exam_name") or e.get("exam_id", f"Exam #{i}") for i, e in enumerate(filtered)],
                    key="browse_exam_select",
                )
                sel_idx = next((i for i, e in enumerate(filtered)
                                if (e.get("exam_name") or e.get("exam_id", f"Exam #{i}")) == selected_exam), None)

                if sel_idx is not None:
                    sel_entry = filtered[sel_idx]
                    fp = sel_entry.get("file_path", "")
                    if fp and Path(fp).exists():
                        with open(fp, encoding="utf-8") as f:
                            record = json.load(f)
                        questions = record.get("questions", [])
                        st.markdown(f"### {record.get('exam_name', 'Questions')} — {len(questions)} questions")

                        for q in questions:
                            opts = q.get("options", {})
                            opts_str = "  ".join(f"**{k}.** {v}" for k, v in opts.items()) if opts else ""
                            topic = q.get("topic", "")
                            ans   = q.get("answer", "")
                            st.markdown(f"""
<div class="q-card">
<b>Q{q.get('q_no', '')}.</b> {q.get('question', '')}
<br><br>{opts_str}
<br><br>
<span class="answer-badge">Ans: {ans}</span>
{"&nbsp;&nbsp;<small>" + topic + "</small>" if topic else ""}
</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — SEARCH
# ════════════════════════════════════════════════════════════════════════════
with tab_search:
    if not IMPORTS_OK:
        st.warning("Dependencies not loaded.")
    else:
        st.markdown("### Search Questions")
        search_col1, search_col2 = st.columns([3, 1])
        with search_col1:
            search_query = st.text_input("Search keyword (English or Bengali)", key="search_q",
                                         placeholder="e.g.  মুক্তিযুদ্ধ  or  liberation war")
        with search_col2:
            search_types = st.multiselect("Exam Types", EXAM_TYPES, default=EXAM_TYPES, key="search_types")

        if search_query:
            store = QuestionStore()
            with st.spinner("Searching..."):
                results = store.search(search_query, exam_types=search_types if search_types else None)

            if not results:
                st.warning("No matching questions found.")
            else:
                st.success(f"Found {len(results)} matching questions.")
                for res in results[:50]:
                    q   = res.get("matched_question", {})
                    opts = q.get("options", {})
                    opts_str = "  ".join(f"**{k}.** {v}" for k, v in opts.items()) if opts else ""
                    st.markdown(f"""
<div class="q-card">
<span class="exam-badge">{res.get("exam_type", "")}</span>
<small> {res.get("exam_name", "")} {res.get("year", "")}</small>
<br><br>
<b>Q{q.get('q_no', '')}.</b> {q.get('question', '')}
<br><br>{opts_str}
<br><br>
<span class="answer-badge">Ans: {q.get('answer', '')}</span>
</div>
""", unsafe_allow_html=True)

                if len(results) > 50:
                    st.info(f"Showing 50 of {len(results)} results. Refine your search.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — PDFs
# ════════════════════════════════════════════════════════════════════════════
with tab_pdfs:
    if not IMPORTS_OK:
        st.warning("Dependencies not loaded.")
    else:
        st.markdown("### Downloaded PDF Question Papers")

        all_pdfs = list(PDF_DIR.rglob("*.pdf"))
        if not all_pdfs:
            st.info("No PDFs downloaded yet. Enable 'Download PDFs' and run a crawl.")
        else:
            st.success(f"{len(all_pdfs)} PDF(s) available")

            # Group by exam type
            by_type: dict[str, list[Path]] = {}
            for p in all_pdfs:
                etype = p.parent.name.replace("_", " ")
                by_type.setdefault(etype, []).append(p)

            for etype, pdfs in sorted(by_type.items()):
                with st.expander(f"**{etype}** — {len(pdfs)} file(s)"):
                    for pdf in sorted(pdfs, key=lambda x: x.name):
                        col_a, col_b, col_c = st.columns([4, 1, 1])
                        size_kb = pdf.stat().st_size // 1024
                        with col_a:
                            st.markdown(f"📄 **{pdf.name}** `{size_kb} KB`")
                        with col_b:
                            with open(pdf, "rb") as fh:
                                st.download_button(
                                    "Download",
                                    data=fh,
                                    file_name=pdf.name,
                                    mime="application/pdf",
                                    key=f"dl_{pdf.stem}",
                                )
                        with col_c:
                            if st.button("Preview Text", key=f"prev_{pdf.stem}"):
                                handler = PDFHandler()
                                text = handler.extract_text(pdf)
                                st.text_area("PDF Text", text[:3000], height=300, key=f"ta_{pdf.stem}")


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — EXPORT
# ════════════════════════════════════════════════════════════════════════════
with tab_export:
    if not IMPORTS_OK:
        st.warning("Dependencies not loaded.")
    else:
        st.markdown("### Export Question Bank as JSON")
        store = QuestionStore()
        stats = store.get_stats()

        # Stats display
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            st.markdown("**Questions by Exam Type**")
            if stats.get("by_exam_type"):
                df_type = pd.DataFrame(
                    stats["by_exam_type"].items(),
                    columns=["Exam Type", "Questions"]
                ).sort_values("Questions", ascending=False)
                st.dataframe(df_type, use_container_width=True, hide_index=True)
            else:
                st.info("No data yet.")

        with col_e2:
            st.markdown("**Questions by Year**")
            if stats.get("by_year"):
                df_year = pd.DataFrame(
                    stats["by_year"].items(),
                    columns=["Year", "Questions"]
                ).head(15)
                st.dataframe(df_year, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Download JSON")

        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            st.markdown("**Export all exam types**")
            if st.button("Prepare Full Export", key="export_all"):
                with st.spinner("Preparing..."):
                    data = store.export_all_json()
                st.download_button(
                    "Download all_questions.json",
                    data=data.encode("utf-8"),
                    file_name=f"all_questions_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                    mime="application/json",
                    key="dl_all",
                )

        with exp_col2:
            st.markdown("**Export by exam type**")
            etype_exp = st.selectbox("Select type", EXAM_TYPES, key="exp_type")
            if st.button(f"Prepare {etype_exp} Export", key="export_type"):
                with st.spinner("Preparing..."):
                    data = store.export_by_type(etype_exp)
                st.download_button(
                    f"Download {etype_exp.replace(' ', '_')}_questions.json",
                    data=data.encode("utf-8"),
                    file_name=f"{etype_exp.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json",
                    key="dl_type",
                )
