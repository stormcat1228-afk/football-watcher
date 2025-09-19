import os
import re
import json
import asyncio
from typing import List, Dict, Any, Optional
import requests

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

# --------- Config / Constants ---------

# Markets we care about (case-insensitive contains match on the page)
MARKET_ALIASES = {
    "ANYTIME_TD": [
        "anytime touchdown scorer",
        "player to score a touchdown",
        "player any time touchdown",
        "anytime td scorer",
    ],
    "FIRST_TD": [
        "first touchdown scorer",
        "first td scorer",
        "player to score first touchdown",
    ],
}

# Very permissive player/odds patterns to rescue data when site structure changes.
RE_PLAYER = re.compile(r"\b([A-Z][a-z]+(?:\s[JRMDKXVI]+\.?)?(?:\s[A-Z][a-z]+){0,2})\b")
RE_ODDS   = re.compile(r"([+\-]\d{2,4})")

# Optional: cap per-game rows to avoid spam
MAX_ROWS_PER_MARKET = 12

# --------- Telegram helper (self-contained) ---------

def send_telegram(text: str) -> None:
    """Post a message to Telegram (group or channel)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("WARN: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID; skipping Telegram send.")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print(f"Telegram send failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Telegram error: {e}")

# --------- File helpers ---------

def load_game_urls() -> List[Dict[str, Any]]:
    """
    Reads config/game_urls.json

    Expected format:
    [
      {"book":"fanduel","home":"BUF","away":"NYJ","url":"https://www.fanduel.com/some-game-url"},
      {"book":"draftkings","home":"DAL","away":"PHI","url":"https://sportsbook.draftkings.com/event/foo"}
    ]
    """
    path = "config/game_urls.json"
    if not os.path.exists(path):
        # Create a stub so user can fill quickly
        stub = [
            {
                "book": "fanduel",
                "home": "BUF",
                "away": "NYJ",
                "url": "https://www.fanduel.com/"
            }
        ]
        os.makedirs("config", exist_ok=True)
        with open(path, "w") as f:
            json.dump(stub, f, indent=2)
        print(f"Created stub {path}. Please edit with real event URLs.")
        return []
    with open(path, "r") as f:
        data = json.load(f)
    # sanitize
    out = []
    for row in data:
        if isinstance(row, dict) and row.get("url"):
            out.append(row)
    return out

# --------- Scraping core ---------

async def goto_safely(page, url: str, wait: float = 40000):
    """Navigate and wait for network to be reasonably idle."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=wait)
        # sites often lazy-load; give a short settle window
        await page.wait_for_timeout(1500)
    except PWTimeoutError:
        print(f"Timeout reaching {url}")
    except Exception as e:
        print(f"goto error {url}: {e}")

async def find_market_container(page, aliases: List[str]) -> Optional[str]:
    """
    Try to locate a market section by alias text. If found, return its inner HTML.
    We try accessible roles/headings first; then a broad text search; finally return None.
    """
    # 1) headings / labels
    for a in aliases:
        try:
            # headings/sections
            loc = page.get_by_role("heading", name=re.compile(a, re.I))
            if await loc.count() > 0:
                el = loc.first
                # bubble to a likely container
                section = await el.locator("xpath=ancestor::*[self::section or self::div][1]").first.inner_html()
                return section
        except Exception:
            pass

    # 2) broad contains text
    try:
        for a in aliases:
            loc = page.get_by_text(a, exact=False)
            if await loc.count() > 0:
                el = loc.first
                container = await el.locator("xpath=ancestor::*[self::section or self::div][1]").first.inner_html()
                return container
    except Exception:
        pass

    # 3) fallback: full page HTML and let regex do work later
    try:
        return await page.content()
    except Exception:
        return None

def parse_pairs_from_html(html: str) -> List[Dict[str, str]]:
    """
    Generic HTML parser that tries to pair player names with nearest American odds.
    Very forgiving; you’ll still want to sanity-check downstream.
    """
    # Split into candidate lines/rows
    # keep only short-ish chunks to reduce noise
    chunks = [c.strip() for c in re.split(r"<[/]?[^>]+>", html)]
    rows = []
    for c in chunks:
        if not c or len(c) > 80:
            continue
        # must contain odds
        mo = RE_ODDS.search(c)
        if not mo:
            continue
        odds = mo.group(1)
        # look for a player nearby (same chunk or neighbors handled by caller)
        name_match = RE_PLAYER.search(c)
        name = name_match.group(1) if name_match else None
        if name:
            rows.append({"player": name, "odds": odds})
    return rows

async def scrape_market(page, aliases: List[str]) -> List[Dict[str, str]]:
    """
    Get rows for a market by alias list: [{'player':..., 'odds':...}, ...]
    """
    container_html = await find_market_container(page, aliases)
    if not container_html:
        return []

    rows = parse_pairs_from_html(container_html)

    # If we didn’t catch names within the same chunk, try a second pass:
    if not rows:
        # fallback: scan whole page
        try:
            all_html = await page.content()
            rows = parse_pairs_from_html(all_html)
        except Exception:
            rows = []

    # Dedup on (player, odds) while keeping order
    seen = set()
    cleaned = []
    for r in rows:
        key = (r["player"], r["odds"])
        if r["player"] and r["odds"] and key not in seen:
            seen.add(key)
            cleaned.append(r)
        if len(cleaned) >= MAX_ROWS_PER_MARKET:
            break
    return cleaned

async def scrape_game(pw_ctx, entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scrape a single event page (book-specific URL).
    Returns dict with 'book','home','away','anytime','firsttd'
    """
    url = entry["url"]
    browser = await pw_ctx.chromium.launch(headless=True, args=["--no-sandbox"])
    page = await browser.new_page(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ))
    await goto_safely(page, url)
    anytime = await scrape_market(page, MARKET_ALIASES["ANYTIME_TD"])
    firsttd = await scrape_market(page, MARKET_ALIASES["FIRST_TD"])
    await browser.close()
    return {
        "book": entry.get("book", "?"),
        "home": entry.get("home", "?"),
        "away": entry.get("away", "?"),
        "url": url,
        "anytime": anytime,
        "firsttd": firsttd,
    }

def format_telegram_block(g: Dict[str, Any]) -> str:
    """Pretty, compact Telegram message for one game."""
    head = f"<b>{g['away']} @ {g['home']}</b> — <i>{g['book']}</i>"
    ft_rows = "\n".join([f"• {r['player']}  <b>{r['odds']}</b>" for r in g.get("firsttd", [])]) or "• (none found)"
    at_rows = "\n".join([f"• {r['player']}  <b>{r['odds']}</b>" for r in g.get("anytime", [])]) or "• (none found)"
    tail = f"\n<code>{g['url']}</code>"
    return f"{head}\n\n<b>First TD (top {MAX_ROWS_PER_MARKET}):</b>\n{ft_rows}\n\n<b>Anytime TD (top {MAX_ROWS_PER_MARKET}):</b>\n{at_rows}{tail}"

async def main():
    entries = load_game_urls()
    if not entries:
        send_telegram("⚠️ No game URLs found in config/game_urls.json. Add event pages to scrape.")
        print("No game URLs to scrape. Exiting.")
        return

    async with async_playwright() as pw:
        results = []
        for e in entries:
            try:
                print(f"Scraping {e.get('book','?')} {e.get('away','?')}@{e.get('home','?')} …")
                g = await scrape_game(pw, e)
                results.append(g)
            except Exception as ex:
                print(f"Error scraping {e.get('url')}: {ex}")

    # Send one message per game (cleaner for Telegram)
    for g in results:
        msg = format_telegram_block(g)
        send_telegram(msg)
        print(msg)  # also log to Actions

if __name__ == "__main__":
    asyncio.run(main())
