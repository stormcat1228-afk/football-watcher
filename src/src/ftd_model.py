import math
from .ftd_config import *

def implied_probability_from_decimal(decimal_odds):
    return 1.0 / decimal_odds

def expected_value(mp, decimal_odds):
    # EV = (mp * (decimal - 1)) - (1 - mp)
    return (mp * (decimal_odds - 1)) - (1 - mp)

def stake_label(mp, ev):
    if ev >= EV_MIN_FULL and mp >= MP_MIN_FULL:
        return LABEL_FULL
    elif ev >= EV_MIN_HALF and mp >= MP_MIN_HALF:
        return LABEL_HALF
    return None  # below quality threshold

def select_ftd_candidates(players):
    """
    players: list of dict {name, team, mp, decimal_odds}
    Returns (primary, backup or None)
    """
    best = []
    for p in players:
        ip = implied_probability_from_decimal(p["decimal_odds"])
        edge = p["mp"] - ip
        ev = expected_value(p["mp"], p["decimal_odds"])
        label = stake_label(p["mp"], ev)
        if label and edge >= EDGE_MIN and p["decimal_odds"] >= PRICE_MIN:
            best.append({**p, "ip": ip, "edge": edge, "ev": ev, "label": label})

    if not best:
        return None, None

    best.sort(key=lambda x: x["ev"], reverse=True)
    primary = best[0]
    backup = None
    if INCLUDE_BACKUP_IF_CLOSE and len(best) > 1:
        if abs(best[1]["mp"] - primary["mp"]) <= BACKUP_MP_DIFF_MAX:
            backup = best[1]
    return primary, backup

def _to_american(decimal_odds: float) -> str:
    # Works for positive-odds cases (decimal >= 2.0). Good for our FTD use.
    return f"+{int(round((decimal_odds - 1) * 100))}"

def format_ftd_message(game_id, primary, backup=None):
    if not primary:
        return f"🎯 FIRST TD PICK — {game_id}\n🚫 No quality +EV pick — PASS"

    msg = [f"🎯 FIRST TD PICK — {game_id}"]
    msg.append(
        f"🔴 {primary['name']} ({primary['team']}) — {_to_american(primary['decimal_odds'])} — {primary['label']}"
    )
    if backup:
        msg.append(
            f"Backup: {backup['name']} ({backup['team']}) — {_to_american(backup['decimal_odds'])} — {backup['label']}"
        )
    return "\n".join(msg)
