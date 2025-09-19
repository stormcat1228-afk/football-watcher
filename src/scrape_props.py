# src/scrape_props.py
# DraftKings scraper for NFL "Anytime TD Scorer" and "First TD Scorer"
# No Odds API usage. Robust selector-based waits (no networkidle).
# Sends summaries to Telegram.

import os
import re
import asyncio
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# -----------------------------
# Configuration
# -----------------------------
DK_BASE = "https://sportsbook.draftkings.com"
DK_NFL_LEAGUE = f"{DK_BASE}/leagues/football/nfl"  # lists all NFL events

MAX_GAMES = 12          # safety cap per run
NAV_TIMEOUT = 90_000    # ms
WAIT_TIMEOUT = 60_000   # ms

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOTFOOTBALL_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# -----------------------------
# Telegram helpers
# -----------------------------
import requests

def tg_send(text: str) -> None:
    """Fire-and-forget Telegram message (best-effort)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID – cannot send Telegram message.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

# -----------------------------
# Utilities
# -----------------------------
def american_to_implied(odds_text: str) -> Optional[float]:
    """Convert American odds like '+160' / '-120' to implied probability (0-1)."""
    m = re.search(r'([+\-]?\d+)', odds_text.replace(" ", ""))
    if not m:
        return None
    n = int(m.group(1))
    if n == 0:
        return None
    if n > 0:
        return 100 / (n + 100)
    return (-n) / ((-n) + 100)

async def safe_text(el) -> str:
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ""

def looks_like_event_href(href: Optional[str]) -> bool:
    if not href:
        return False
    # Common DK event pattern
    return "/event/" in href

@dataclass
class Outcome:
    player: str
    odds: str
    implied: Optional[float]

# -----------------------------
# Scraper core
# -----------------------------
async def discover_game_urls(page) -> List[Tuple[str, str]]:
    """Find NFL event URLs from the league page."""
    print("→ Navigating to DK NFL league page…")
    await page.goto(DK_NFL_LEAGUE, timeout=NAV_TIMEOUT)

    # Wait until event links render (no networkidle!)
    try:
        await page.wait_for_selector('a[href*="/event/"]', timeout=WAIT_TIMEOUT, state="attached")
    except PWTimeout:
        print("⚠️ Timeout waiting for event links.")
        return []

    anchors = page.locator('a[href*="/event/"]')
    count = await anchors.count()
    print(f"• Found {count} anchors (raw)")

    seen, results = set(), []
    for i in range(count):
        a = anchors.nth(i)
        href = await a.get_attribute("href")
        if not looks_like_event_href(href):
            continue
        if href.startswith("/"):
            href = DK_BASE + href
        if href in seen:
            continue
        title = await safe_text(a)
        seen.add(href)
        results.append((title or "NFL Game", href))

    print(f"• Discovered {len(results)} event links")
    return results[:MAX_GAMES]

async def open_market(page, market_name: str) -> bool:
    """Try to reveal a specific market panel by clicking its tab/card."""
    # Look for buttons/cards/headers that contain the market name
    patterns = [
        re.compile(market_name, re.I),
        re.compile(market_name.replace(" ", ""), re.I),
    ]

    # Try role=button first
    for pat in patterns:
        els = page.get_by_role("button", name=pat)
        if await els.count():
            try:
                await els.first.click(timeout=10_000)
                await asyncio.sleep(0.2)
                return True
            except Exception:
                pass

    # Try clickable elements by text
    for pat in patterns:
        el = page.locator("text=" + market_name).first
        try:
            if await el.count() > 0:
                await el.click(timeout=10_000)
                await asyncio.sleep(0.2)
                return True
        except Exception:
            pass

    # Some pages load markets collapsed; try scrolling to load more
    try:
        await page.mouse.wheel(0, 4000)
        await asyncio.sleep(0.4)
    except Exception:
        pass

    # Second attempt after scroll
    for pat in patterns:
        els = page.get_by_role("button", name=pat)
        if await els.count():
            try:
                await els.first.click(timeout=10_000)
                await asyncio.sleep(0.2)
                return True
            except Exception:
                pass

    print(f"⚠️ Could not locate market tab for: {market_name}")
    return False

async def parse_market_outcomes(page) -> List[Outcome]:
    """
    Extract player/odds from a visible market panel.
    DK often uses outcome cells with various classnames; we match broadly.
    """
    # Wait for any outcome-like cell to be present
    selectors = [
        '[data-test*="outcome"], [data-test*="Outcome"]',
        '.sportsbook-outcome-cell, [class*="outcome"]',
        '[data-entity-id]'
    ]
    panel = None
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=10_000)
            panel = page.locator(sel)
            if await panel.count() > 0:
                break
        except PWTimeout:
            continue

    if not panel or await panel.count() == 0:
        print("⚠️ No outcome rows found.")
        return []

    results: List[Outcome] = []
    # Grab a limited number to avoid spam
    row_count = min(await panel.count(), 60)

    for i in range(row_count):
        cell = panel.nth(i)

        # Player/selection name (best-effort)
        name_loc = cell.locator('[data-test*="outcome-name"], .outcome-name, [class*="name"]')
        odds_loc = cell.locator('[data-test*="odds"], .sportsbook-odds, [class*="odds"]')

        player = (await safe_text(name_loc)) or (await safe_text(cell))
        odds = await safe_text(odds_loc)

        # Filter obviously wrong rows
        if not player or not re.search(r'[+\-]\d+', odds):
            continue

        results.append(Outcome(player=player, odds=odds, implied=american_to_implied(odds)))

    return results

async def scrape_event(page, title: str, url: str) -> Dict[str, List[Outcome]]:
    """Open an event page and collect the two target markets."""
    print(f"→ Event: {title} | {url}")
    await page.goto(url, timeout=NAV_TIMEOUT)

    # Make sure core content is present before we hunt markets
    try:
        await page.wait_for_selector('main, [id*="root"], [data-test*="market"]', timeout=WAIT_TIMEOUT)
    except PWTimeout:
        print("⚠️ Event page content not found in time.")
        return {}

    markets: Dict[str, List[Outcome]] = {}

    # 1) Anytime TD Scorer
    if await open_market(page, "Anytime Touchdown Scorer"):
        outcomes = await parse_market_outcomes(page)
        markets["Anytime TD Scorer"] = outcomes

    # 2) First TD Scorer
    if await open_market(page, "First Touchdown Scorer"):
        outcomes = await parse_market_outcomes(page)
        markets["First TD Scorer"] = outcomes

    return markets

def format_outcomes(outcomes: List[Outcome], top_n: int = 8) -> str:
    if not outcomes:
        return "— none —"
    # Sort by best implied probability (desc); if unknown, push to bottom
    def key(o: Outcome):
        return o.implied if o.implied is not None else -1.0
    items = sorted(outcomes, key=key, reverse=True)[:top_n]

    lines = []
    for o in items:
        prob = f"{round(o.implied*100,1)}%" if o.implied is not None else "?"
        # Escape < & >
        name = o.player.replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"• <b>{name}</b>  {o.odds}  (≈ {prob})")
    return "\n".join(lines)

async def run() -> None:
    tg_send("🏈 Starting DraftKings scrape for Anytime / First TD…")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            viewport={"width": 1400, "height": 900},
        )
        page = await context.new_page()

        games = await discover_game_urls(page)
        if not games:
            tg_send("⚠️ No NFL event links found on DraftKings. The page may have changed.")
            await context.close()
            await browser.close()
            return

        # Loop through events and scrape
        scraped_any = False
        for idx, (title, url) in enumerate(games, start=1):
            try:
                markets = await scrape_event(page, title, url)
            except Exception as e:
                print(f"Error on event scrape: {e}")
                continue

            if not markets:
                continue

            scraped_any = True
            msg = [f"<b>{title}</b>"]
            if "Anytime TD Scorer" in markets:
                msg.append("\n<b>Anytime TD Scorer</b>")
                msg.append(format_outcomes(markets["Anytime TD Scorer"]))
            if "First TD Scorer" in markets:
                msg.append("\n<b>First TD Scorer</b>")
                msg.append(format_outcomes(markets["First TD Scorer"]))

            tg_send("\n".join(msg))

        if not scraped_any:
            tg_send("⚠️ No target markets visible on event pages. They may be hidden/closed right now.")

        await context.close()
        await browser.close()
    tg_send("✅ DraftKings scrape finished.")

if __name__ == "__main__":
    asyncio.run(run())

