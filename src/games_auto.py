import os, json, requests, datetime as dt
import pytz

ODDS_KEY = os.getenv("ODDS_API_KEY")
SPORT = "americanfootball_nfl"
BASE = "https://api.the-odds-api.com/v4"
ET = pytz.timezone("America/New_York")

def _load_team_map():
    with open("config/teams_meta.json") as f:
        raw = json.load(f)
    return {k.upper(): v for k, v in raw.items()}

def _abbr(name, mapping):
    if not name: return name
    key = name.upper().strip()
    if key in mapping:
        return mapping[key]
    # fallback: last token (e.g., "Dallas Cowboys" -> "COWBOYS" not in map)
    return mapping.get(key, key[:3])

def _iso_et(dt_obj):
    return dt_obj.astimezone(ET).isoformat()

def _is_today_et(start_iso):
    when = dt.datetime.fromisoformat(start_iso.replace("Z","+00:00")).astimezone(ET)
    now = dt.datetime.now(ET)
    return when.date() == now.date()

def refresh_today():
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    # fetch all NFL events
    url = f"{BASE}/sports/{SPORT}/events"
    r = requests.get(url, params={"apiKey": ODDS_KEY}, timeout=20)
    r.raise_for_status()
    events = r.json()

    team_map = _load_team_map()
    out = []
    for ev in events:
        commence = ev.get("commence_time")
        if not commence or not _is_today_et(commence):
            continue
        home = ev.get("home_team","").strip()
        away = ev.get("away_team","").strip()
        if not home or not away:
            continue
        home_abbr = _abbr(home, team_map)
        away_abbr = _abbr(away, team_map)
        gid = f"{away_abbr}@{home_abbr}"
        kickoff_et = _iso_et(dt.datetime.fromisoformat(commence.replace("Z","+00:00")))
        out.append({"game_id": gid, "kickoff_et": kickoff_et, "home": home_abbr, "away": away_abbr})

    out.sort(key=lambda g: g["kickoff_et"])
    os.makedirs("config", exist_ok=True)
    with open("config/games_today.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(out)} games to config/games_today.json")
