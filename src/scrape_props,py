import asyncio
from playwright.async_api import async_playwright
from typing import Dict, List, Tuple

# Market names we care about
MARKET_NAMES = {
    "anytime": ["Anytime Touchdown Scorer", "Anytime TD Scorer"],
    "first_td": ["First Touchdown Scorer", "First TD Scorer"],
}

def parse_rows(block_text: str) -> List[Tuple[str, int, float]]:
    rows = []
    for line in block_text.split("\n"):
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            name = " ".join(parts[:-1])
            odds_str = parts[-1]
            if odds_str.startswith("+"):
                odds = int(odds_str)
                prob = 100 / (odds + 100)
            elif odds_str.startswith("-"):
                odds = int(odds_str)
                prob = abs(odds) / (abs(odds) + 100)
            else:
                continue
            rows.append((name, odds, prob))
        except:
            continue
    return sorted(rows, key=lambda x: x[2], reverse=True)

async def scrape_event_markets(page, game_url: str) -> Dict[str, List[Tuple[str, int, float]]]:
    await page.goto(game_url, timeout=60000)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)

    results = {"anytime": [], "first_td": []}

    for key, labels in MARKET_NAMES.items():
        for label in labels:
            el = await page.get_by_text(label, exact=False).first
            try:
                if await el.count() == 0:
                    continue
                try:
                    await el.click(timeout=2000)
                except:
                    pass
                block = await page.locator("section,div").filter(has_text=label).first.inner_text()
                results[key] = parse_rows(block)[:20]
                break
            except:
                continue

    return results

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # TODO: Replace this with a real game URL list
        game_urls = ["https://www.draftkings.com/leagues/football/nfl"]

        for game in game_urls:
            markets = await scrape_event_markets(page, game)
            print("\n=== GAME ===")
            print(f"URL: {game}")
            if markets["anytime"]:
                print("Anytime TD:")
                for n, o, p in markets["anytime"]:
                    print(f"  {n}: {o} (p={p:.1%})")
            if markets["first_td"]:
                print("First TD:")
                for n, o, p in markets["first_td"]:
                    print(f"  {n}: {o} (p={p:.1%})")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
