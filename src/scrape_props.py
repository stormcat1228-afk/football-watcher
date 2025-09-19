# src/scrape_props.py
import os
import re
import asyncio
from typing import List, Tuple, Dict, Optional

import requests
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# === Telegram ===
BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

def tg_send(text: str) -> None:
    if not (BOT and CHAT_ID):
        print("⚠️ Telegram not configured; skipping message.")
        return
    url = f"https://api.telegram.org/bot{BOT}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
        if r.status_code != 200:
            print(f"⚠️ Telegram send failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"⚠️ Telegram exception: {e}")

# === DraftKings targets ===
DK_BASE = "https://sportsbook.draftkings.com"
DK_NFL_LEAGUE = f"{DK_BASE}/leagues/football/nfl"

ANYTIME_LABELS = (
    "anytime touchdown scorer",
    "any time touchdown scorer",
    "touchdown scorer (anytime)",
)
FIRST_TD_LABELS = (
    "first touchdown scorer",
    "first team td scorer",  # some regional phrasings
)

# ---------- helpers ----------
async def safe_text(locator) -> str:
    try:
        t = await locator.inner_text()
        return (t or "").strip()
    except Exception:
        return ""

async def wait_for_any(page, selector: str, timeout: int = 45000) -> None:
    try:
        await page.wait_for_selector(selector, timeout=timeout, state="attached")
    except PWTimeout:
        print(f"⚠️ Timeout waiting for {selector}")

def looks_like_event_href(href: Optional[str]) -> bool:
    return bool(href and "/event/" in href)

def normalize_market_name(name: str) -> str:
    n = name.lower().strip()
    return re.sub(r"\s+", " ", n)

def is_anytime_market(name: str) -> bool:
    n = normalize_market_name(name)
    return any(lbl in n for lbl in ANYTIME_LABELS)

def is_first_td_market(name: str) -> bool:
    n = normalize_market_name(name)
    return any(lbl in n for lbl in FIRST_TD_LABELS)

def parse_price(text: str) -> Optional[int]:
    # Accept DK American odds like +135, -110
    m = re.search(r"([+\-]\d{2,4})", text.replace(" ", ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None

# ---------- discovery ----------
async def discover_game_urls(page) -> List[Tuple[str, str]]:
    """Return list of (title, url) event pages from NFL league view."""
    print("→ Navigating to DK NFL league page…")
    await page.goto(DK_NFL_LEAGUE, timeout=90000)
    await wait_for_any(page, 'a[href*="/event/"]', 60000)

    anchors = page.locator('a[href*="/event/"]')
    count = await anchors.count()
    print(f"• Found {count} raw event anchors")

    seen = set()
    results: List[Tuple[str, str]] = []
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

    # De-dupe to probable NFL games only (heuristic)
    filtered = []
    for title, url in results:
        if re.search(r"/event/\d+", url):
            filtered.append((title, url))

    print(f"• Discovered {len(filtered)} unique NFL event links")
    return filtered[:20]  # safety cap

# ---------- market scraping ----------
async def extract_player_prices_from_market(market_block) -> List[Tuple[str, int]]:
    """Given a rendered market block, return list of (player, odds)."""
    rows = market_block.locator('[data-test*="offerItem"], [role="row"]')
    n = await rows.count()
    out: List[Tuple[str, int]] = []
    for i in range(n):
        row = rows.nth(i)
        raw = await safe_text(row)
        if not raw:
            continue

        # Try to split player and price by line breaks
        parts = [p.strip() for p in re.split(r"[\n\r]+", raw) if p.strip()]
        candidate_price = parse_price(raw)
        if not candidate_price:
            continue

        # Heuristic for player name: pick the longest alpha chunk that is not the odds
        name_candidates = [p for p in parts if not re.search(r"[+\-]\d", p)]
        if not name_candidates:
            continue
        player = max(name_candidates, key=len)
        out.append((player, candidate_price))

    return out

async def find_market_blocks(page) -> Dict[str, object]:
    """Return locators for relevant markets keyed by type."""
    # Market section containers vary; look for headings/cards by text
    containers = page.locator('section, div[role="region"], div[aria-label], div.sportsbook-market-group')
    count = await containers.count()
    any_block = None
    first_block = None

    for i in range(count):
        block = containers.nth(i)
        header_txt = (await safe_text(block)).lower()
        if not header_txt:
            continue
        if not any_block and any(is_anytime_market(header_txt) for _ in [header_txt]):
            any_block = block
        if not first_block and any(is_first_td_market(header_txt) for _ in [header_txt]):
            first_block = block
        if any_block and first_block:
            break

    return {"anytime": any_block, "first": first_block}

async def scrape_game(page, title: str, url: str) -> Optional[str]:
    print(f"→ Opening event: {title} | {url}")
    await page.goto(url, timeout=90000)
    # Wait until some content is there; avoid networkidle
    await wait_for_any(page, '[data-test*="market"], [role="region"], section', 60000)

    blocks = await find_market_blocks(page)
    msgs = [f"<b>{title}</b>"]

    for label, key in (("Anytime TD", "anytime"), ("First TD", "first")):
        block = blocks.get(key)
        if not block:
            msgs.append(f"• {label}: <i>market not found</i>")
            continue
        prices = await extract_player_prices_from_market(block)
        if not prices:
            msgs.append(f"• {label}: <i>no prices visible</i>")
            continue

        # Sort best (shortest) odds first for usability
        prices.sort(key=lambda x: abs(x[1]))
        top = prices[:6]  # keep it concise
        pretty = ", ".join([f"{p} ({o:+d})" for p, o in top])
        msgs.append(f"• {label}: {pretty}")

    return "\n".join(msgs)

# ---------- runner ----------
async def run() -> None:
    if not (BOT and CHAT_ID):
        print("⚠️ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))
        page = await ctx.new_page()

        # Discover games
        try:
            games = await discover_game_urls(page)
        except Exception as e:
            tg_send(f"⚠️ DK discover error: {e}")
            await browser.close()
            return

        if not games:
            tg_send("⚠️ No game URLs found from DraftKings NFL page.")
            await browser.close()
            return

        # Scrape each event
        messages: List[str] = []
        for title, url in games:
            try:
                txt = await scrape_game(page, title, url)
                if txt:
                    messages.append(txt)
            except Exception as e:
                messages.append(f"<b>{title}</b>\n• Error: {e}")

        await browser.close()

    # Chunk messages to stay under Telegram limits
    if not messages:
        tg_send("⚠️ No props scraped from DK.")
        return

    chunk: str = ""
    for m in messages:
        if len(chunk) + len(m) + 2 > 3800:
            tg_send(chunk)
            chunk = ""
        chunk += (m + "\n\n")
    if chunk:
        tg_send(chunk)

def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
