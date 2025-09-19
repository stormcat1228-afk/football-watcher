# src/kickoff_gate.py
import requests, pytz
from datetime import datetime, timedelta

ET = pytz.timezone("America/New_York")
ESPN = "https://site.api.espn.com/apis/v2/sports/football/nfl/scoreboard?dates={yyyymmdd}"

def _now_et():
    return datetime.now(ET).replace(second=0, microsecond=0)

def _starts_today_et():
    today = _now_et().strftime("%Y%m%d")
    r = requests.get(ESPN.format(yyyymmdd=today), timeout=15)
    r.raise_for_status()
    data = r.json()
    starts = []
    for ev in data.get("events", []):
        iso = ev.get("date") or ev.get("startDate")
        if not iso: 
            continue
        dt_utc = datetime.fromisoformat(iso.replace("Z","+00:00"))
        starts.append(dt_utc.astimezone(ET).replace(second=0, microsecond=0))
    return sorted(set(starts))

def should_run_now(pad_min: int = 6):
    """
    Returns (should_run: bool, window: 'T90'|'T30'|None, next_kick: datetime|None)
    True only if now is within ±pad_min minutes of T-90 or T-30 before any kickoff today.
    """
    now = _now_et()
    for k in _starts_today_et():
        for mark, label in ((k - timedelta(minutes=90), "T90"),
                            (k - timedelta(minutes=30), "T30")):
            if abs((now - mark).total_seconds()) <= pad_min * 60:
                return True, label, k
    return False, None, None
