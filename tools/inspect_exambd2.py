"""
Deep inspect exambd.net - look at the ebpg pagination elements and HTML structure.
"""
import asyncio
import json
import sys
import io
import re

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TARGET_URL = "https://www.exambd.net/2025/06/46th-bcs-preliminary-question-solution.html"


async def inspect():
    from playwright.async_api import async_playwright

    captured_ajax = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        async def on_response(response):
            req = response.request
            if req.resource_type in ("xhr", "fetch"):
                url = response.url
                # Only interested in exambd.net calls
                if "exambd" in url or "wordpress" in url or "wp-json" in url or "wp-admin" in url:
                    try:
                        body = await response.text()
                        captured_ajax.append({"url": url, "method": req.method, "body": body[:1000]})
                        print(f"[EXAMBD AJAX] {req.method} {url}")
                        print(f"  {body[:300]}")
                    except Exception:
                        pass

        page.on("response", on_response)

        print(f"Loading: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)

        html = await page.content()
        print(f"\nPage HTML length: {len(html)}")

        # --- Look at ebpg elements ---
        ebpg_items = await page.query_selector_all(".ebpg-pagination-item")
        print(f"\nebpg-pagination-item count: {len(ebpg_items)}")

        if ebpg_items:
            # Get the first few items' text
            for i, item in enumerate(ebpg_items[:5]):
                txt = await item.inner_text()
                print(f"  item[{i}]: '{txt}'")

        # Look for question content in HTML
        # Search for known Bengali/English exam keywords
        q_matches = re.findall(r'(?:question|mcq|quiz|answer|option)[^"]{0,200}', html[:50000], re.I)
        print(f"\nQuestion-related HTML snippets (first 5):")
        for m in q_matches[:5]:
            print(f"  {m[:150]}")

        # Look at ebpg wrapper divs
        ebpg_wrappers = await page.query_selector_all("[class*='ebpg']")
        print(f"\nElements with 'ebpg' class: {len(ebpg_wrappers)}")
        for i, el in enumerate(ebpg_wrappers[:3]):
            cls = await el.get_attribute("class")
            txt = await el.inner_text()
            print(f"  [{i}] class={cls[:60]} text={txt[:100]}")

        # Get the actual visible quiz content on the page
        # Look for quiz blocks
        quiz_blocks = await page.query_selector_all("[class*='quiz'], [class*='Quiz'], [id*='quiz']")
        print(f"\nQuiz elements: {len(quiz_blocks)}")
        for i, el in enumerate(quiz_blocks[:3]):
            cls = await el.get_attribute("class") or ""
            txt = await el.inner_text()
            print(f"  [{i}] {cls[:50]}: {txt[:200]}")

        # ---- Look at the raw HTML for question data ----
        # Extract the first 'ebpg' section from HTML
        ebpg_idx = html.find("ebpg")
        if ebpg_idx != -1:
            print(f"\nHTML around first 'ebpg' occurrence:")
            print(html[max(0, ebpg_idx-200):ebpg_idx+500])

        # Look for JSON data in scripts with quiz content
        # WordPress Gutenberg blocks often embed data as JSON in script tags
        script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        print(f"\nTotal script tags: {len(script_matches)}")
        for i, s in enumerate(script_matches):
            if any(kw in s.lower() for kw in ["question", "answer", "quiz", "ebpg", "mcq"]):
                print(f"\n[Script {i}] Has quiz keywords:")
                print(s[:800])

        # Try clicking the active ebpg pagination item to see if AJAX fires
        active_items = await page.query_selector_all(".ebpg-pagination-item.active")
        print(f"\nActive pagination items: {len(active_items)}")

        # Try clicking a non-active item
        show_items = await page.query_selector_all(".ebpg-pagination-item.show")
        print(f"'show' pagination items: {len(show_items)}")
        if show_items:
            for i, item in enumerate(show_items[:3]):
                txt = await item.inner_text()
                print(f"  show_item[{i}] text: '{txt}'")

        # Click the second show item
        if len(show_items) >= 2:
            print("\nClicking second page button...")
            await show_items[1].click()
            await asyncio.sleep(3)

            # Get visible page content after click
            visible = await page.evaluate("document.body.innerText")
            print(f"\nVisible text after click (first 1000 chars):")
            print(visible[:1000])

        print(f"\n=== exambd.net AJAX calls: {len(captured_ajax)} ===")
        for c in captured_ajax:
            print(json.dumps(c, ensure_ascii=False, indent=2))

        await browser.close()


if __name__ == "__main__":
    asyncio.run(inspect())
