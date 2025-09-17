import os
import sys
import time
import json
import datetime as dt
from urllib.parse import urlencode

import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ODDS_API_KEY       = os.getenv("ODDS_API_KEY", "").strip()

SPORT_KEY = "americanfootball_nfl"
REGIONS   = "us"                 # US books
ODDS_FMT  = "american"
DATE_FMT  = "iso"
# We’ll request both markets. If one isn’t available in your plan/region, we’ll just skip it.
MARKETS   = "player_anytime_td,first_team_to_score"

API_BASE  = "https://api.the-odds-api.com/v4"

def _get(url, params):
    params = dict(params or {})
    params["apiKey"] = ODDS_API_KEY
    full = f"{url}?{urlencode(params)}"
    r = requests.get(full, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Odds API error {r.status_code}: {r.text}")
    return r.json(), r.headers

def fetch_odds_for_upcoming():
    """
    Pull odds for all upcoming NFL events with requested markets.
    API: /sports/{sport_key}/odds
    """
    url = f"{API_BASE}/sports/{SPORT_KEY}/odds"
    params = {
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FMT,
        "dateFormat": DATE_FMT,
    }
    data, headers = _get(url, params)
    # Optional: log quota remaining
    rem = headers.get("x-requests-remaining") or headers.get("x-requests-remaining-month")
    print(f"[odds] items: {len(data)} | remaining: {rem}")
    return data

def best_price_outcome(outcomes):
    """
    Given an array of outcomes from a single bookmaker market,
    return outcome with the best (highest) American odds for us (longer +money).
    """
    best = None
    for o in outcomes or []:
        price = o.get("price")
        # Ensure price is an int (american odds)
        if price is None:
            continue
        if (best is None) or (price > best.get("price", -10**9)):
            best = o
    return best

def collect_best_anytime_td(bookmakers_market):
    """
    For 'player_anytime_td' market, aggregate best odds per player across books.
    bookmakers_market: list of bookmakers [{key, title, markets:[{key, outcomes:[]}, ...]}]
    Returns: list of dicts {name, price, bookmaker}
    """
    board = {}  # name -> (price, book)
    for bk in bookmakers_market or []:
        title = bk.get("title") or bk.get("key")
        for m in bk.get("markets", []):
            if m.get("key") != "player_anytime_td":
                continue
            best = best_price_outcome(m.get("outcomes"))
            if not best: 
                continue
            name  = best.get("name", "Unknown")
            price = best.get("price")
            prev  = board.get(name)
            if (prev is None) or (price > prev["price"]):
                board[name] = {"name": name, "price": price, "bookmaker": title}
    # Sort by price desc (longer odds first)
    return sorted(board.values(), key=lambda x: x["price"], reverse=True)

def collect_best_first_team_to_score(bookmakers_market, home_team, away_team):
    """
    For 'first_team_to_score' market, pick the best price for each team across all books.
    Returns list of dicts {team, price, bookmaker}
    """
    best_by_team = {}
    for bk in bookmakers_market or []:
        title = bk.get("title") or bk.get("key")
        for m in bk.get("markets", []):
            if m.get("key") != "first_team_to_score":
                continue
            for o in m.get("outcomes", []):
                team = o.get("name")
                price = o.get("price")
                if not team or price is None:
                    continue
                prev = best_by_team.get(team)
                if (prev is None) or (price > prev["price"]):
                    best_by_team[team] = {"team": team, "price": price, "bookmaker": title}
    # Only keep home/away if present
    res = []
    for t in (home_team, away_team):
        if t and t in best_by_team:
            res.append(best_by_team[t])
    # Sort by price desc
    return sorted(res, key=lambda x: x["price"], reverse=True)

def tg_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")
    return r.json()

def short_list(items, limit=5):
    return items[:limit] if items else []

def run_td_alerts():
    # Basic env check
    print("Has TELEGRAM_BOT_TOKEN:", bool(TELEGRAM_BOT_TOKEN))
    print("Has TELEGRAM_CHAT_ID:",  bool(TELEGRAM_CHAT_ID))
    print("Has ODDS_API_KEY:",      bool(ODDS_API_KEY))

    try:
        events = fetch_odds_for_upcoming()
    except Exception as e:
        # If API call fails, send one error to Telegram so we know
        tg_send(f"⚠️ Odds API error: {e}")
        raise

    # Send a compact message per event
    sent = 0
    for ev in events:
        home = ev.get("home_team")
        away = ev.get("away_team")
        commence = ev.get("commence_time")  # ISO string
        bookmakers = ev.get("bookmakers", [])

        # Collect markets
        top_anytime = collect_best_anytime_td(bookmakers)
        top_first   = collect_best_first_team_to_score(bookmakers, home, away)

        # Build text (simple)
        lines = []
        lines.append(f"{away} at {home}")
        if commence:
            lines.append(f"Kickoff: {commence}")
        if top_first:
            lines.append("First Team to Score (best prices):")
            for row in short_list(top_first, 2):
                lines.append(f" - {row['team']}: {row['price']} @ {row['bookmaker']}")
        else:
            lines.append("First Team to Score: (no market found)")

        if top_anytime:
            lines.append("Anytime TD (best prices):")
            for row in short_list(top_anytime, 6):
                # player name + best price + book
                lines.append(f" - {row['name']}: {row['price']} @ {row['bookmaker']}")
        else:
            lines.append("Anytime TD: (no market found)")

        text = "\n".join(lines)
        try:
            tg_send(text)
            sent += 1
        except Exception as e:
            # Don’t crash the whole run for one game
            print(f"Telegram send failed: {e}", file=sys.stderr)
            time.sleep(1)

    if sent == 0:
        tg_send("No upcoming NFL events with those markets (or plan doesn’t include them).")

