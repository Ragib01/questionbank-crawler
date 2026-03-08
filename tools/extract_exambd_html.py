"""
Extract questions directly from exambd.net HTML.
The questions are embedded as static HTML with radio buttons — pagination is CSS-only.
Answers are embedded as arguments to checkAnswer(questionNumber, correctAnswer).

Run: python tools/extract_exambd_html.py
"""
import asyncio
import json
import re
import sys
import io

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET_URL = "https://www.exambd.net/2025/06/46th-bcs-preliminary-question-solution.html"


async def get_full_html(url: str) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)
        html = await page.content()
        await browser.close()
    return html


def extract_questions(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    questions = []

    # ── Strategy 1: Find checkAnswer() calls to map q_no → correct answer ──────
    # Pattern: checkAnswer(1, 'A') or checkAnswer(1, "A")
    answer_map = {}
    for match in re.finditer(r"checkAnswer\s*\(\s*(\d+)\s*,\s*['\"]([^'\"]+)['\"]", html):
        q_num = int(match.group(1))
        answer = match.group(2).strip()
        answer_map[q_num] = answer

    print(f"Found {len(answer_map)} checkAnswer() calls")
    if answer_map:
        sample = dict(list(answer_map.items())[:5])
        print(f"Sample: {sample}")

    # ── Strategy 2: Extract question containers ──────────────────────────────
    # Look for divs/forms containing radio buttons named q1, q2, q3...
    # The structure is likely: question text + radio options per question number

    # Find all radio inputs with name="qN"
    radio_inputs = soup.find_all("input", {"type": "radio"})
    print(f"\nRadio inputs found: {len(radio_inputs)}")

    if radio_inputs:
        # Group by question name (q1, q2, ...)
        q_groups: dict[int, list] = {}
        for inp in radio_inputs:
            name = inp.get("name", "")
            m = re.match(r"q(\d+)$", name)
            if m:
                qn = int(m.group(1))
                q_groups.setdefault(qn, []).append(inp)

        print(f"Question groups (by radio name): {len(q_groups)}")
        print(f"First 5 keys: {sorted(list(q_groups.keys()))[:5]}")

        for qn in sorted(q_groups.keys()):
            radios = q_groups[qn]
            options = {}
            for r in radios:
                val = r.get("value", "")
                # Get the label text
                label = r.find_next_sibling("label") or r.find_parent("label")
                if label:
                    label_text = label.get_text(strip=True)
                else:
                    # Try the parent element's text
                    parent = r.parent
                    label_text = parent.get_text(strip=True) if parent else val

                # Remove the value prefix from the label if it starts with it
                if label_text.startswith(val):
                    label_text = label_text[len(val):].strip(" .")
                options[val] = label_text

            # Find question text — look for the containing div or preceding sibling
            # The question container should be near the first radio
            first_radio = radios[0]
            container = first_radio
            # Walk up to find the question block
            for _ in range(6):
                container = container.parent
                if container is None:
                    break
                # Look for question text — usually a <p> or heading with the question
                q_text_el = container.find("p") or container.find(["h3", "h4", "h2"])
                if q_text_el:
                    q_text = q_text_el.get_text(strip=True)
                    if len(q_text) > 10 and not q_text.startswith("option") and "radio" not in q_text.lower():
                        break
            else:
                q_text = ""

            answer = answer_map.get(qn, "")
            questions.append({
                "q_no": qn,
                "question": q_text,
                "options": options,
                "answer": answer,
            })

    # ── Strategy 3: Find result elements (result1, result2, ...) ────────────
    result_els = soup.find_all(id=re.compile(r"^result(\d+)$"))
    print(f"\nResult elements (result1, result2, ...): {len(result_els)}")

    # ── Strategy 4: showAnswer() calls ─────────────────────────────────────
    show_answers = re.findall(r"showAnswer\s*\(\s*['\"]([^'\"]+)['\"]", html)
    print(f"showAnswer() calls: {len(show_answers)}, samples: {show_answers[:5]}")

    # ── Dump a sample of the raw HTML to understand structure ───────────────
    # Find the first question radio container HTML
    if radio_inputs:
        print(f"\n=== First question radio HTML context ===")
        first = radio_inputs[0]
        # Get 3 levels up
        ctx = first
        for _ in range(4):
            if ctx.parent:
                ctx = ctx.parent
        print(str(ctx)[:2000])

    return questions


async def main():
    print(f"Fetching: {TARGET_URL}")
    html = await get_full_html(TARGET_URL)
    print(f"HTML length: {len(html)}")

    questions = extract_questions(html)
    print(f"\n=== Extracted {len(questions)} questions ===")
    for q in questions[:5]:
        print(json.dumps(q, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
