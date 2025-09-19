import os, asyncio, json, pytz, datetime as dt, re
import requests
from typing import List, Tuple, Dict, Optional
from playwright.async_api import async_playwright

TZ = pytz.timezone("America/New_York")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

DK_NFL_LEAGUE = "https://sportsbook.draftkings.com/leagues/football/88670846?category=game-lines&subcategory=game"
# We’ll discover event links from the league page (the id can change; this URL redirects correctly).

ANYTIME_LABELS = {"any time touchdown scorer", "anytime touchdown scorer", "player to score a touchdown"}
FIRSTTD_LABELS = {"first touchdown scorer", "first td scorer", "first player to score"}

async def dk_text(el):
    try:
        return (await el.inner_text()).strip()
    except:
        return ""

def normalize_money(s: str) -> Optional[int]:
    # +150 -> 150 ; -120 -> -120 ; 3/1 -> None (not used); "" -> None
    s = s.replace(" ", "").replace("–", "-")
    m = re.match(r'^[\+\-]?\d+$', s)
    if m: return int(m.group(0))
    return None

def now_str():
    return dt.datetime.now(TZ).strftime("%Y-%m-%d %I:%M %p %Z")

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)

async def discover_game_urls(page) -> List[Tuple[str, str]]:
    """Return list of (game_title, url) for today only."""
    await page.goto(DK_NFL_LEAGUE, timeout=60000)
    await page.wait_for_load_state("networkidle")

    # DK groups events into cards; we look for anchor tags that contain event links.
    anchors = page.locator('a[href*="/event/"]')
    count = await anchors.count()
    seen = set()
    results = []
    for i in range(count):
        a = anchors.nth(i)
        href = await a.get_attribute("href") or ""
        if "/event/" not in href:
            continue
        # Build absolute URL
        if href.startswith("/"):
            href = "https://sportsbook.draftkings.com" + href
        # Deduplicate
        if href in seen:
            continue
        seen.add(href)

        # Title usually contains "Team A vs Team B"
        title = await dk_text(a)
        # Filter to today’s events if a date appears near card; DK sometimes includes date in sibling.
        # If we can't read date, include it and let per-page time filtering handle later.
        results.append((title or "NFL Game", href))

    print(f"Discovered {len(results)} DK event links")
    return results

async def scrape_market_table(page, market_labels: set) -> List[Tuple[str, Optional[int]]]:
    """
    Find a market section whose header matches one of market_labels (case-insensitive),
    then read rows as (player, price).
    """
    results = []

    # Sections often have role="region" with a heading
    sections = page.locator("section, div[role=region]")
    scount = await sections.count()
    for si in range(scount):
        sec = sections.nth(si)
        # header can be h2/h3/button/div
        header = sec.locator("h2, h3, button, div").first
        label = (await dk_text(header)).lower()
        if not label:
            continue
        if not any(lbl in label for lbl in market_labels):
            continue

        # Rows usually contain two spans: player name and price, or a button with both.
        # Try common patterns, fallback to all buttons inside.
        row_candidates = sec.locator("div, button").filter(has_text=re.compile(r"\+|\-"))
        rcount = await row_candidates.count()
        for ri in range(rcount):
            r = row_candidates.nth(ri)
            text = (await dk_text(r))
            if not text:
                continue

            # Extract player and price heuristically
            # Example: "A.J. Brown +110"
            price_match = re.search(r"([+\-]\d{2,4})", text)
            if not price_match:
                continue
            price = normalize_money(price_match.group(1))
            # Player name = text with price stripped
            player = text.replace(price_match.group(1), "").strip(" •|-")
            # Keep it tight (avoid capturing whole blocks)
            if len(player) > 40:
                # try split by newline and take the first long-ish token without odds
                player = [t for t in re.split(r"[\n\r]+", player) if not re.search(r"[+\-]\d{2,4}", t)]
                player = player[0].strip() if player else "Player"

            if price is not None:
                results.append((player, price))

        if results:
            break  # only first matching market

    return results

async def scrape_game(page, title: str, url: str) -> Optional[str]:
    try:
        await page.goto(url, timeout=60000)
        await page.wait_for_load_state("networkidle")

        # Sometimes markets are behind tabs like "Player Props"
        possible_tabs = page.locator("a,button").filter(
            has_text=re.compile(r"player props|player|props", re.I)
        )
        if await possible_tabs.count():
            # Click first tab we find
            try:
                await possible_tabs.first.click()
                await page.wait_for_timeout(1200)
            except:
                pass

        anytime = await scrape_market_table(page, ANYTIME_LABELS)
        firsttd = await scrape_market_table(page, FIRSTTD_LABELS)

        if not anytime and not firsttd:
            return None

        def fmt(rows):
            # sort best (lowest negative, highest positive) — purely presentational
            rows = list(rows)
            rows.sort(key=lambda x: (x[1] is None, x[1]))
            out = []
            for p, price in rows[:12]:  # cap to reduce spam
                price_str = f"{price:+d}" if price is not None else "N/A"
                out.append(f"{p} ({price_str})")
            return "\n".join(out) if out else "None"

        msg = [
            f"🏈 <b>{title}</b>",
            f"<i>{now_str()}</i>",
        ]
        if anytime:
            msg += ["\n<b>Anytime TD (DK):</b>", fmt(anytime)]
        if firsttd:
            msg += ["\n<b>First TD Scorer (DK):</b>", fmt(firsttd)]
        return "\n".join(msg)

    except Exception as e:
        print(f"Error scraping {title}: {e}")
        return None

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        # 1) discover today’s NFL events
        games = await discover_game_urls(page)
        if not games:
            send_telegram("⚠️ No NFL event links discovered on DraftKings.")
            await browser.close()
            return

        hits = 0
        for title, url in games:
            msg = await scrape_game(page, title, url)
            if msg:
                send_telegram(msg)
                hits += 1
                await page.wait_for_timeout(500)  # be polite to DK

        if hits == 0:
            send_telegram("⚠️ No DK Anytime/First TD markets visible yet on current events.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
