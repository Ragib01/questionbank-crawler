"""
Dump relevant HTML sections to understand exambd.net question structure.
"""
import asyncio
import re
import sys
import io

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET_URL = "https://www.exambd.net/2025/06/46th-bcs-preliminary-question-solution.html"


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)
        html = await page.content()
        await browser.close()

    print(f"HTML length: {len(html)}")

    # 1. Find checkAnswer occurrences
    check_occurrences = [(m.start(), m.group()) for m in re.finditer(r"checkAnswer", html)]
    print(f"\ncheckAnswer occurrences: {len(check_occurrences)}")
    for start, _ in check_occurrences[:3]:
        print(f"  at {start}: ...{html[start:start+100]}...")

    # 2. Find input[type=radio] occurrences
    radio_occurrences = list(re.finditer(r'<input[^>]+type=["\']radio["\']', html, re.I))
    print(f"\nRadio input occurrences: {len(radio_occurrences)}")
    for m in radio_occurrences[:3]:
        print(f"  {m.group()[:100]}")

    # 3. Find the article content area
    # Look for the post-content or article div
    content_m = re.search(r'<div[^>]+class=["\'][^"\']*(?:entry-content|post-content|article-content)[^"\']*["\']', html, re.I)
    if content_m:
        start = content_m.start()
        print(f"\nContent div found at {start}:")
        print(html[start:start+2000])
    else:
        print("\nNo entry-content/post-content div found")

    # 4. Look for question-related text (any q1, q2 pattern)
    q_pattern = list(re.finditer(r'name=["\']q\d+["\']', html, re.I))
    print(f"\n'name=qN' occurrences: {len(q_pattern)}")
    for m in q_pattern[:3]:
        print(f"  at {m.start()}: {html[m.start()-50:m.start()+100]}")

    # 5. Find onclick attributes containing checkAnswer
    onclick_q = list(re.finditer(r'onclick=["\'][^"\']*checkAnswer[^"\']*["\']', html, re.I))
    print(f"\nonclick checkAnswer occurrences: {len(onclick_q)}")
    for m in onclick_q[:5]:
        print(f"  {m.group()[:200]}")

    # 6. What does the visible page text say?
    # Find the main article/post div
    # Dump around "46th" or "BCS" keyword
    bcs_positions = [m.start() for m in re.finditer(r'46th|46 তম|বিসিএস', html)]
    print(f"\n'46th/46th BCS' positions: {bcs_positions[:5]}")
    if bcs_positions:
        p0 = bcs_positions[0]
        print(f"Context around first occurrence:")
        print(html[max(0, p0-200):p0+500])

    # 7. Look for any element containing question numbers like "১." or "1."
    bn_q = list(re.finditer(r'[১২৩৪৫৬৭৮৯০]{1,3}\s*[।.]\s*', html))
    en_q = list(re.finditer(r'\b[1-9]\d?\s*[.)]\s*[A-Za-z\u0980-\u09FF]', html))
    print(f"\nBengali numbered items (১., ২., ...): {len(bn_q)}")
    print(f"English numbered items (1., 2., ...): {len(en_q)}")
    if en_q:
        for m in en_q[:5]:
            print(f"  at {m.start()}: {html[m.start():m.start()+150]}")

    # 8. Dump the post entry div HTML
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article") or soup.find("div", class_=re.compile(r"post|entry|article", re.I))
    if article:
        article_text = article.get_text(separator="\n")
        print(f"\nArticle text length: {len(article_text)}")
        print(f"Article text (first 3000 chars):")
        print(article_text[:3000])


if __name__ == "__main__":
    asyncio.run(main())
