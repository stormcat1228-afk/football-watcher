import json, os
from .telegram import post
from .odds_api import fetch_odds_for_games
from .td_rules import (
    is_first_team_to_score_market, is_anytime_td_market,
    normalize_anytime_row, normalize_first_team_row, keep_playable_anytime
)

def load_games():
    with open("config/games_today.json") as f: return json.load(f)

def map_gid(away_name, home_name, games):
    # Map API names to our config games by fuzzy contain
    a = away_name.lower(); h = home_name.lower()
    for g in games:
        # naive contains check; in practice keep a team-nickname map in config/teams_meta.json
        if g["home"].lower() in h and g["away"].lower() in a:
            return g["game_id"]
    return f"{away_name} @ {home_name}"

def run_td_alerts():
    games = load_games()
    game_ids = [g["game_id"] for g in games]

    odds = fetch_odds_for_games(game_ids)

    # For each game, collect interesting markets
    per_game_anytime = {}
    per_game_firstteam = {}

    for g in odds:
        home = g.get("home_team","").upper()
        away = g.get("away_team","").upper()
        gid = map_gid(away, home, games)

        for bk in g.get("bookmakers", []):
            book = bk.get("title") or bk.get("key") or "book"
            for mk in bk.get("markets", []):
                mname = mk.get("key") or mk.get("market") or mk.get("outcome_type") or mk.get("title") or ""
                # The Odds API uses structured keys; other providers may vary.
                # We detect by human-readable text to be robust.
                if is_anytime_td_market(mname):
                    for oc in mk.get("outcomes", []):
                        row = normalize_anytime_row(book, oc)
                        if keep_playable_anytime(row, min_plus=200):
                            per_game_anytime.setdefault(gid, []).append(row)
                elif is_first_team_to_score_market(mname):
                    for oc in mk.get("outcomes", []):
                        row = normalize_first_team_row(book, oc)
                        per_game_firstteam.setdefault(gid, []).append(row)

    # Build simple advice text (no stats, just “what to do” in plain English)
    for gid, picks in per_game_anytime.items():
        # Show top 3 longest prices across books (dedupe by player name)
        seen = set(); top = []
        for row in sorted(picks, key=lambda r: int(str(r["odds"]).replace("+","").replace("-","0")), reverse=True):
            key = (row["name"], row.get("team",""))
            if key in seen: continue
            seen.add(key); top.append(row)
            if len(top) >= 3: break

        if top:
            lines = [f"🏈 *Anytime TD — {gid}*"]
            for r in top:
                nm = r["name"]; od = r["odds"]; bk = r["book"]
                # red marker + bold player
                lines.append(f"- 🔴 **{nm}** ({od}) — Small sprinkle only. Shop best price ({bk}).")
            lines.append("What to do: treat these as upside sprinkles, not core legs.")
            post("\n".join(lines))

    for gid, options in per_game_firstteam.items():
        # If a team is best-priced across books, mention as a small play
        by_team = {}
        for r in options:
            team = r["team"]; odds = r["odds"]; book = r["book"]
            try:
                val = int(str(odds).replace("+",""))
            except:
                continue
            if team not in by_team or val > by_team[team]["val"]:
                by_team[team] = {"val": val, "odds": odds, "book": book}
        if by_team:
            ranked = sorted(by_team.items(), key=lambda kv: kv[1]["val"], reverse=True)[:2]
            lines = [f"🏈 *First Team to Score — {gid}*"]
            for team, d in ranked:
                lines.append(f"- **{team}** ({d['odds']}) — Small play only. Shop best price ({d['book']}).")
            lines.append("What to do: keep stakes tiny; this is high variance.")
            post("\n".join(lines))
