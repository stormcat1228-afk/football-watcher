# src/fav_edges.py
# DraftKings-only Favorites + Coin-Flip bot.
# Per game: 2 favorites + 1 coin-flip with True vs Book vs Edge.

import os, re, math, asyncio, requests, pytz
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from kickoff_gate import should_run_now

# --- Telegram ---
BOT = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOTFOOTBALL_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")
def tg_send(text: str, silent: bool = False):
    if not (BOT and CHAT): 
        print("Telegram not configured"); 
        return None
    url = f"https://api.telegram.org/bot{BOT}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT, "text": text, "parse_mode":"HTML", "disable_notification": bool(silent)}, timeout=15)
    try:
        return r.json().get("result", {}).get("message_id")
    except Exception:
        return None
def tg_pin(message_id: int):
    if not (BOT and CHAT and message_id): return
    url = f"https://api.telegram.org/bot{BOT}/pinChatMessage"
    requests.post(url, json={"chat_id": CHAT, "message_id": message_id}, timeout=15)
def banner(label: str) -> str:
    return "<b><u>=== FINAL 30-MINUTE BOARD ===</u></b>\n" if label=="T30" else "<b>— 90-MINUTE PREVIEW —</b>\n"

# --- DK targets ---
DK = "https://sportsbook.draftkings.com"
NFL_HUB = f"{DK}/leagues/football/nfl"
ET = pytz.timezone("America/New_York")

# --- math helpers ---
def prob_from_american(a: int) -> float:
    return 100/(a+100) if a>0 else (-a)/((-a)+100)
def american_from_prob(p: float) -> int:
    p = max(1e-6, min(0.999999, p))
    return int(round(100*(p/(1-p)))) if p>=0.5 else int(round(-100*((1-p)/p)))
def parse_first_int(s:str):
    m = re.search(r'([+\-]?\d{2,4})', s.replace("–","-"))
    return int(m.group(1)) if m else None

# --- simple "true" models ---
def fair_win_prob_from_spread(spread_points: float) -> float:
    try:
        z = spread_points/13.86
        return 0.5*(1+math.erf(z/math.sqrt(2)))
    except Exception:
        return 0.0

def fair_qb_1plus_from_team_total(team_total_pts: float, pass_td_share: float=0.65) -> float:
    lam_td = max(0.0, team_total_pts/7.0)
    lam_pass = lam_td * pass_td_share
    return 1 - math.exp(-lam_pass)

def est_team_totals(total_pts: float, spread_pts: float) -> tuple:
    fav = total_pts/2 + spread_pts/2
    dog = total_pts - fav
    return fav, dog

def fair_rec_over_prob(total_pts: float, spread_pts: float, line: float=3.5) -> float:
    plays = 60
    pass_rate = 0.55 + (0.06 if spread_pts < -6 else 0.0) + (0.06 if spread_pts > 6 else 0.0)
    dropbacks = plays * pass_rate
    targets = dropbacks * 0.9 * 0.20
    recs_mean = targets * 0.66
    mu, sigma = recs_mean, 1.2
    z = (line + 0.5 - mu) / (sigma + 1e-6)
    return 1 - 0.5*(1+math.erf(z/math.sqrt(2)))

# --- DK scraping utilities ---
async def discover_event_urls(page):
    await page.goto(NFL_HUB, timeout=90_000)
    try:
        await page.wait_for_selector('a[href*="/event/"]', timeout=60_000)
    except PWTimeout:
        return []
    urls, seen = [], set()
    anchors = page.locator('a[href*="/event/"]')
    for i in range(await anchors.count()):
        href = await anchors.nth(i).get_attribute("href")
        if href and "/event/" in href:
            if href.startswith("/"): href = DK + href
            if href not in seen:
                seen.add(href)
                urls.append(href.split("?")[0])
    return urls[:15]

async def read_game_lines(page):
    txt = (await page.content()).lower()
    m_total = re.search(r'(total|o/u)\s*([0-9]{2}\.5|[0-9]{2})', txt)
    total = float(m_total.group(2)) if m_total else 44.0
    m_spread = re.search(r'[-+](\d+\.\d|\d+)\s*(spread)?', txt)
    spread = float(m_spread.group(0)) if m_spread else -3.0
    return spread, total

async def pick_favorites(page):
    picked = []
    try:
        buttons = page.locator("button:has-text('-')")
        best_ml = None
        for i in range(min(await buttons.count(), 40)):
            t = (await buttons.nth(i).inner_text()).strip()
            a = parse_first_int(t)
            if a is None or a >= 0: continue
            p_book = prob_from_american(a)
            spread, total = await read_game_lines(page)
            p_true = fair_win_prob_from_spread(abs(spread))
            edge = (p_true - p_book) * 100
            cand = ("Moneyline Favorite", a, p_true, edge)
            if (best_ml is None) or edge > best_ml[3]:
                best_ml = cand
        if best_ml and prob_from_american(best_ml[1]) >= 0.75 and best_ml[3] >= 2.5:
            picked.append(best_ml)
    except Exception:
        pass
    # QB 1+ Passing TD (simplified)
    try:
        rows = page.locator("button").filter(has_text=re.compile(r"1\+\s*(pass(ing)?\s*)?td", re.I))
        best_qb = None
        for i in range(min(await rows.count(), 60)):
            t = (await rows.nth(i).inner_text()).strip()
            a = parse_first_int(t)
            if a is None: continue
            p_book = prob_from_american(a)
            spread, total = await read_game_lines(page)
            fav_tt, dog_tt = est_team_totals(total, abs(spread))
            team_total = max(fav_tt, dog_tt)
            p_true = fair_qb_1plus_from_team_total(team_total, pass_td_share=0.64)
            edge = (p_true - p_book) * 100
            player = re.split(r"[+\-]\d+", t)[0].strip()
            cand = (f"{player} 1+ Pass TD", a, p_true, edge)
            if (best_qb is None) or edge > best_qb[3]:
                best_qb = cand
        if best_qb and prob_from_american(best_qb[1]) >= 0.75 and best_qb[3] >= 2.5:
            picked.append(best_qb)
    except Exception:
        pass
    return picked[:2]

async def pick_coinflip(page):
    try:
        rows = page.locator("button").filter(has_text=re.compile(r"over\s*(3\.5|4\.5)", re.I))
        best = None
        for i in range(min(await rows.count(), 80)):
            t = (await rows.nth(i).inner_text()).strip()
            a = parse_first_int(t)
            if a is None: continue
            p_book = prob_from_american(a)
            spread, total = await read_game_lines(page)
            ln = 3.5 if "3.5" in t else 4.5
            p_true = fair_rec_over_prob(total_pts=total, spread_pts=spread, line=ln)
            edge = (p_true - p_book) * 100
            player = re.split(r"(over|under)\s*(3\.5|4\.5)", t, flags=re.I)[0].strip()
            cand = (f"{player} Over {ln} Rec", a, p_true, edge)
            if 0.45 <= p_book <= 0.60 and edge >= 3.0:
                if (best is None) or edge > best[3]:
                    best = cand
        return best
    except Exception:
        return None

def line_str(true_p: float, book_a: int):
    true_a = american_from_prob(true_p)
    book_p = prob_from_american(book_a)
    edge = (true_p - book_p) * 100
    return f"{true_a:+d}", f"{book_a:+d}", f"{edge:+.1f}%"

async def process_event(context, url: str):
    page = await context.new_page()
    try:
        await page.goto(url, timeout=90_000)
        try:
            await page.wait_for_selector("main", timeout=60_000)
        except PWTimeout:
            pass
        title = await page.title()
        header = re.sub(r"\s+\|.*$", "", title).strip()
        favs = await pick_favorites(page)
        coin = await pick_coinflip(page)
        if len(favs) < 2 or coin is None: return
        lines = [f"🏈 <b>{header}</b>"]
        for idx, (label, book_a, p_true, edge) in enumerate(favs[:2], start=1):
            ta, ba, e = line_str(p_true, book_a)
            lines.append(f"\n✅ Favorite {idx}: {label}\nTrue: {ta} | Book: {ba} | Edge: {e}")
        ta, ba, e = line_str(coin[2], coin[1])
        lines.append(f"\n⚖️ Coin-Flip: {coin[0]}\nTrue: {ta} | Book: {ba} | Edge: {e}")
        tg_send("\n".join(lines), silent=False)
    finally:
        await page.close()

async def main():
    should, window, _kick = should_run_now(pad_min=6)
    if not should:
        print("Outside T-90/T-30 window; exiting.")
        return
    mid = tg_send(banner(window), silent=False)
    if window == "T30" and mid: 
        tg_pin(mid)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()
        urls = await discover_event_urls(page)
        if not urls:
            tg_send("⚠️ No NFL event links found on DraftKings.")
            await browser.close(); return
        for url in urls[:12]:
            await process_event(context, url)
            await asyncio.sleep(0.6)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
