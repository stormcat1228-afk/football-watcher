# ftd_model.py
# This is a very simple placeholder model that will later be expanded
# to scrape data and calculate expected value. For now it just returns test data.

def select_ftd_candidates():
    """
    Selects first touchdown (FTD) candidates.
    For now, returns a static list we can use to verify everything is connected.
    """
    candidates = [
        {"team": "Eagles", "player": "AJ Brown", "ev": 0.22},
        {"team": "Cowboys", "player": "CeeDee Lamb", "ev": 0.19},
    ]
    return candidates


def format_ftd_message(candidates):
    """
    Formats a message to send to Telegram. Very simple for now.
    """
    lines = ["📢 **First TD Candidates (TEST DATA)**"]
    for c in candidates:
        lines.append(f"- {c['player']} ({c['team']}) — EV: {c['ev']*100:.1f}%")
    return "\n".join(lines)


if __name__ == "__main__":
    # Test run: print to console
    cands = select_ftd_candidates()
    print(format_ftd_message(cands))
