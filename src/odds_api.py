import os, requests, time

ODDS_KEY = os.getenv("ODDS_API_KEY")

BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# We ask for just the two markets we care about.
# NOTE: Market names vary by provider. We match by substrings later for safety.
MARKETS = "h2h,specials,player_props"

def fetch_odds_for_games(game_ids):
    """
    Pulls odds once for all games, then we'll filter for:
      - 'First Team to Score'
      - 'Anytime Touchdown Scorer' (or similar text)
    We keep it API-agnostic by scanning market/description strings.
    """
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")

    url = f"{BASE}/sports/{SPORT}/odds"
    params = {
        "apiKey": ODDS_KEY,
        "regions": "us",
        "markets": MARKETS,
        "oddsFormat": "american"
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    # Filter to only the games we care about today (by home/away names in config mapping).
    # We'll pass in game_ids like 'DAL@PHI' and match by team names below.
    # The Odds API returns 'home_team' and 'away_team' strings.
    wanted = set(game_ids)
    keep = []
    for g in data:
        home = g.get("home_team","").upper()
        away = g.get("away_team","").upper()
        gid = f"{away.split()[-1][:3].upper()}@{home.split()[-1][:3].upper()}"  # crude fallback
        # We'll attach actual names; td_alerts will map to our config to verify.
        g["_gid_guess"] = gid
        keep.append(g)
    return keep
