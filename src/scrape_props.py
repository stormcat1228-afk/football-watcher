# src/scrape_props.py
import os, time, json, pytz, datetime as dt
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

ET = pytz.timezone("America/New_York")

# ---- Telegram helper ---------------------------------------------------------
def tg_send(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code != 200:
        print("Telegram error:", r.text)

# ---- Bovada helpers ----------------------------------------------------------
# Base endpoints: Bovada exposes JSON for events by league/sport.
NFL_SPORT_ID = "football"   # high-level sport for menu
BOVADA_BASE  = "https://www.bovada.lv"
# A practical feed that lists upcoming events across Football
EVENT_FEED   = "https://www.bovada.lv/services/sports/event/coupon/events/A/description/football?marketFilterId=def&preMatchOnly=true"

def fetch_bovada():
    """Return raw JSON of football events (includes NFL)"""
    r = requests.get(EVENT_FEED, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()

def unix_to_et(ts_ms: int) -> str:
    t = dt.datetime.fromtimestamp(ts_ms/1000, tz=pytz.utc).astimezone(ET)
    return t.strftime("%a %I:%M %p ET")

def is_today_et(ts_ms: int) -> bool:
    t = dt.datetime.fromtimestamp(ts_ms/1000, tz=pytz.utc).astimezone(ET).date()
    return t == dt.datetime.now(ET).date()

def collect_markets():
    data = fetch_bovada()
    # data is a list of groups; each group has "events" with displayGroups/markets
    events = []
    for group in data:
        for ev in group.get("events", []):
            # filter to today’s games only
            if not is_today_et(ev.get("startTime", 0)):
                continue
            events.append(ev)
    return events

def pick_player_prop_markets(display_groups):
    """Return dict with any/first TD markets if present."""
    out = {"anytime": None, "first": None}
    for dg in display_groups or []:
        if "Player Props" not in (dg.get("description") or ""):
            continue
        for m in dg.get("markets", []):
            name = (m.get("description") or "").lower()
            if "anytime touchdown scorer" in name and out["anytime"] is None:
                out["anytime"] = m
            if "first touchdown scorer" in name and out["first"] is None:
                out["first"] = m
    return out

def parse_outcomes(market):
    picks = []
    if not market:
        return picks
    for o in market.get("outcomes", []):
        player = o.get("description") or o.get("name") or ""
        price  = o.get("price", {})
        # American odds (may be in price['american'] or computed from 'decimal'])
        american = price.get("american")
        if american is None and "decimal" in price:
            dec = float(price["decimal"])
            # naive conversion
            if dec >= 2.0:
                american = int((dec - 1.0) * 100)
            else:
                american = int(-100 / (dec - 1.0))
        if not player or american is None:
            continue
        picks.append((player.strip(), str(american)))
    # keep top N shortest odds so the message is readable
    return picks[:15]

def build_message(ev, any_markets, first_markets):
    home = ev.get("competitors", [{}])[0].get("name", "Home")
    away = ev.get("competitors", [{}])[-1].get("name", "Away")
    when = unix_to_et(ev.get("startTime", 0))

    any_list  = parse_outcomes(any_markets)
    first_list= parse_outcomes(first_markets)

    lines = [f"🏈 <b>{away} at {home}</b> — {when}"]
    if any_list:
        lines.append("<b>Anytime TD (top lines)</b>")
        for p, odds in any_list:
            lines.append(f"• {p}: {odds}")
    else:
        lines.append("Anytime TD: (no market found)")

    if first_list:
        lines.append("<b>First TD Scorer (top lines)</b>")
        for p, odds in first_list:
            lines.append(f"• {p}: {odds}")
    else:
        lines.append("First TD Scorer: (no market found)")
    return "\n".join(lines)

def main():
    try:
        events = collect_markets()
        if not events:
            tg_send("⚠️ No NFL events for today were found in Bovada feed.")
            return

        sent = 0
        for ev in events:
            dgs = ev.get("displayGroups", [])
            picked = pick_player_prop_markets(dgs)
            # Skip games that don’t have either market
            if not picked["anytime"] and not picked["first"]:
                continue
            msg = build_message(ev, picked["anytime"], picked["first"])
            tg_send(msg)
            time.sleep(0.75)  # be polite to Telegram
            sent += 1

        if sent == 0:
            tg_send("⚠️ NFL found, but no Anytime/First TD markets were present yet.")
    except Exception as e:
        tg_send(f"⚠️ Scraper error: {e}")

if __name__ == "__main__":
    main()
