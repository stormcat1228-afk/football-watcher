def is_first_team_to_score_market(market_name):
    s = (market_name or "").lower()
    return ("first team to score" in s) or ("first scoring team" in s)

def is_anytime_td_market(market_name):
    s = (market_name or "").lower()
    return ("anytime touchdown" in s) or ("anytime td" in s) or ("to score a touchdown" in s)

def normalize_anytime_row(book, outcome):
    """
    outcome expected fields (provider-dependent):
      - name (player)
      - price / odds (American)
      - team (sometimes present)
    """
    name = outcome.get("name") or outcome.get("description") or "Player"
    odds = outcome.get("price") or outcome.get("odds_american") or outcome.get("odds") or None
    team = outcome.get("team") or outcome.get("metadata",{}).get("team") or ""
    return {"book": book, "name": name, "odds": odds, "team": team}

def normalize_first_team_row(book, outcome):
    team = outcome.get("name") or outcome.get("team") or outcome.get("description") or "TEAM"
    odds = outcome.get("price") or outcome.get("odds_american") or outcome.get("odds") or None
    return {"book": book, "team": team, "odds": odds}

def american_to_prob(odds_str):
    if not odds_str: return None
    s = str(odds_str).strip()
    if not s or s == "EVEN": return 0.5
    try:
        o = int(s)
    except:
        if s.startswith("+") or s.startswith("-"):
            try: o = int(s.replace("+",""))
            except: return None
        else:
            return None
    if o < 0: return abs(o) / (abs(o) + 100)
    return 100 / (o + 100)

def keep_playable_anytime(row, min_plus=200):
    """
    Basic filter: only alert when odds are juicy enough (+200 or better),
    tune later if you want.
    """
    if row["odds"] is None: return False
    s = str(row["odds"])
    try:
        val = int(s.replace("+",""))
    except:
        return False
    return val >= min_plus
