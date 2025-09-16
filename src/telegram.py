import os, requests

def post(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"  # lets us bold names later
    }, timeout=20)
    r.raise_for_status()
    return r.json()
