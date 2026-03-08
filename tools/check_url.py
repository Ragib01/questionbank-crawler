"""Check what URL we actually load and what's in the article."""
import asyncio, sys, io, re
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

URLS = [
    "https://www.exambd.net/2025/06/46th-bcs-preliminary-question-solution.html",
    "https://www.exambd.net/2024/04/45th-bcs-preliminary-question-solution.html",
]

async def check(url):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        resp = await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)
        final_url = page.url
        title = await page.title()
        from bs4 import BeautifulSoup
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Strip scripts/styles/nav
        for t in soup(["script", "style", "nav", "header", "footer", "aside"]):
            t.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        print(f"\n{'='*60}")
        print(f"Original URL: {url}")
        print(f"Final URL:    {final_url}")
        print(f"Title:        {title}")
        print(f"HTTP status:  {resp.status if resp else 'N/A'}")
        print(f"Text length:  {len(text)}")
        print(f"\nFirst 2000 chars of text:")
        print(text[:2000])

        # Look for PDF links
        pdf_links = [a['href'] for a in soup.find_all('a', href=True) if a['href'].lower().endswith('.pdf')]
        print(f"\nPDF links: {pdf_links[:5]}")

        # Look for download links
        dl_links = [a['href'] for a in soup.find_all('a', href=True) if 'download' in a.get_text().lower() or 'download' in a['href'].lower()]
        print(f"Download links: {dl_links[:5]}")

        await browser.close()

async def main():
    for url in URLS:
        await check(url)

if __name__ == "__main__":
    asyncio.run(main())
