"""Debug script to capture real Kwork HTML structure."""
import asyncio
import json
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

DEBUG_DIR = Path(__file__).parent.parent / "debug"
DEBUG_DIR.mkdir(exist_ok=True)


async def save_html(page, filename):
    """Save page HTML for debugging."""
    content = await page.content()
    path = DEBUG_DIR / filename
    path.write_text(content, encoding="utf-8")
    print(f"Saved HTML: {path}")
    return path


async def analyze_kwork():
    """Analyze Kwork projects page structure."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        page = await context.new_page()

        print("Loading kwork.ru/projects...")
        await page.goto("https://kwork.ru/projects", wait_until="networkidle")
        await asyncio.sleep(5)  # Wait for JS to render

        # Save full HTML
        await save_html(page, "kwork_projects_full.html")

        # Analyze page structure
        print("\n=== PAGE STRUCTURE ANALYSIS ===")

        # Count all links
        links = await page.eval_on_selector_all("a[href]", "els => els.map(e => ({href: e.href, text: e.innerText.trim().slice(0,100), class: e.className}))")
        project_links = [l for l in links if "/projects/" in l["href"] and "/view" in l["href"]]
        print(f"Total links: {len(links)}")
        print(f"Project links: {len(project_links)}")
        print(f"\nFirst 5 project links:")
        for l in project_links[:5]:
            print(f"  URL: {l['href']}")
            print(f"  Text: {l['text'][:80]}")
            print(f"  Class: {l['class'][:100]}")
            print()

        # Find card-like containers
        cards = await page.eval_on_selector_all("*", """
            els => els.filter(e => {
                const cls = e.className || '';
                return (cls.includes('card') || cls.includes('item') || cls.includes('project') || cls.includes('want')) 
                    && e.children.length > 2;
            }).map(e => ({
                tag: e.tagName,
                class: e.className,
                childCount: e.children.length,
                textPreview: e.innerText.trim().slice(0, 150)
            })).slice(0, 20)
        """)
        print(f"\nPotential card containers (first 20):")
        for i, c in enumerate(cards[:10]):
            print(f"  {i+1}. <{c['tag']}> class='{c['class'][:80]}' children={c['childCount']}")
            print(f"     Text: {c['textPreview'][:100]}")

        # Find elements with price/budget
        price_elems = await page.eval_on_selector_all("*", """
            els => els.filter(e => {
                const text = e.innerText || '';
                return (text.includes('₽') || text.includes('руб')) && text.length < 200;
            }).map(e => ({
                tag: e.tagName,
                class: e.className,
                text: e.innerText.trim().slice(0, 100)
            })).slice(0, 15)
        """)
        print(f"\nElements with currency (first 15):")
        for i, p in enumerate(price_elems[:10]):
            print(f"  {i+1}. <{p['tag']}> class='{p['class'][:60]}' → {p['text']}")

        # Try to find specific data structures
        print("\n=== LOOKING FOR DATA ATTRIBUTES ===")
        data_attrs = await page.eval_on_selector_all("[data-project-id], [data-id], [data-vacancy-id]", """
            els => els.map(e => ({
                tag: e.tagName,
                dataset: JSON.stringify(e.dataset),
                class: e.className
            })).slice(0, 10)
        """)
        print(f"Elements with data-* IDs: {len(data_attrs)}")
        for d in data_attrs[:5]:
            print(f"  {d}")

        # Look for JSON data in page
        page_text = await page.content()
        import re
        json_matches = re.findall(r'window\.__[A-Z_]+__\s*=\s*({.+?});', page_text)
        print(f"\nJSON data blocks found: {len(json_matches)}")
        for i, m in enumerate(json_matches[:2]):
            try:
                data = json.loads(m)
                print(f"  Block {i+1} keys: {list(data.keys())[:10]}")
            except (json.JSONDecodeError, ValueError):
                print(f"  Block {i+1}: not valid JSON (length {len(m)})")

        # Now try to open first project page
        if project_links:
            first_url = project_links[0]["href"]
            print(f"\n\n=== OPENING PROJECT PAGE ===")
            print(f"URL: {first_url}")

            await page.goto(first_url, wait_until="networkidle")
            await asyncio.sleep(3)
            await save_html(page, "kwork_project_detail.html")

            # Extract project page structure
            h1 = await page.query_selector("h1")
            if h1:
                h1_text = await h1.inner_text()
                print(f"H1: {h1_text[:100]}")

            # Look for description
            desc_selectors = [".description", ".project-description", "[itemprop='description']", ".wants-card__description", ".task-description"]
            for sel in desc_selectors:
                el = await page.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    print(f"Description found via '{sel}': {text[:200]}...")
                    break

        await browser.close()
        print(f"\n=== DEBUG FILES SAVED TO {DEBUG_DIR} ===")


if __name__ == "__main__":
    asyncio.run(analyze_kwork())
