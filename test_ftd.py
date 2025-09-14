from src.ftd_model import select_ftd_candidates, format_ftd_message

# Dummy test data (change numbers later to play)
players = [
    {"name": "Dallas Goedert", "team": "PHI", "mp": 0.068, "decimal_odds": 15.0},  # +1400
    {"name": "CeeDee Lamb",    "team": "DAL", "mp": 0.090, "decimal_odds": 13.0},  # +1200
    {"name": "Rico Dowdle",    "team": "DAL", "mp": 0.030, "decimal_odds": 17.0},  # too low -> ignored
]

primary, backup = select_ftd_candidates(players)
msg = format_ftd_message("DAL @ PHI", primary, backup)
print(msg)
