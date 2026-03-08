"""
Inspect exambd.net network traffic to find the question API.
Run: python tools/inspect_exambd.py
"""
import asyncio
import json
import sys
import io

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TARGET_URL = "https://www.exambd.net/2025/06/46th-bcs-preliminary-question-solution.html"


async def inspect():
    from playwright.async_api import async_playwright

    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Capture all XHR / fetch requests + responses
        async def on_response(response):
            req = response.request
            if req.resource_type in ("xhr", "fetch", "document"):
                url = response.url
                status = response.status
                try:
                    body = await response.text()
                    body_preview = body[:500]
                except Exception:
                    body_preview = "<unreadable>"
                entry = {
                    "type": req.resource_type,
                    "method": req.method,
                    "url": url,
                    "status": status,
                    "body_len": len(body_preview),
                    "body_preview": body_preview,
                }
                captured.append(entry)
                if req.resource_type in ("xhr", "fetch"):
                    print(f"[{req.resource_type.upper()}] {req.method} {url} → {status}")
                    print(f"  body: {body_preview[:200]}")

        page.on("response", on_response)

        print(f"Loading: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)

        # --- Inspect the page ---
        html = await page.content()
        print(f"\nPage HTML length: {len(html)}")

        # Look for clickable question elements
        q_buttons = await page.query_selector_all(
            "button, a[onclick], span[onclick], div[onclick], "
            "[class*='question'], [class*='quiz'], [class*='mcq'], "
            "[id*='question'], [id*='quiz']"
        )
        print(f"Clickable question elements found: {len(q_buttons)}")

        # Try clicking the first few
        for i, btn in enumerate(q_buttons[:5]):
            tag = await btn.evaluate("el => el.tagName + ':' + (el.className || el.id || el.textContent?.slice(0,30))")
            print(f"  btn[{i}]: {tag}")

        # Actually click a few to trigger AJAX
        print("\nClicking first 3 clickable elements to trigger AJAX...")
        for i, btn in enumerate(q_buttons[:3]):
            try:
                await btn.click(timeout=3000)
                await asyncio.sleep(1.5)
                print(f"  Clicked btn[{i}]")
            except Exception as ex:
                print(f"  btn[{i}] click failed: {ex}")

        await asyncio.sleep(2)

        # Dump all AJAX calls
        ajax_calls = [c for c in captured if c["type"] in ("xhr", "fetch")]
        print(f"\n=== Total AJAX calls: {len(ajax_calls)} ===")
        for c in ajax_calls:
            print(json.dumps({k: v for k, v in c.items() if k != "body_preview"}, indent=2))
            print(f"  body preview: {c['body_preview'][:300]}")
            print()

        # Dump page text to see what content is actually visible
        visible_text = await page.evaluate("document.body.innerText")
        print(f"\n=== Visible page text (first 2000 chars) ===")
        print(visible_text[:2000])

        # Check if any JSON is embedded in the page
        scripts = await page.query_selector_all("script")
        for i, script in enumerate(scripts[:20]):
            try:
                content = await script.evaluate("el => el.textContent")
                if content and ("question" in content.lower() or "answer" in content.lower() or "mcq" in content.lower()):
                    print(f"\n[Script {i}] Contains question/answer keywords:")
                    print(content[:500])
            except Exception:
                pass

        await browser.close()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(inspect())
