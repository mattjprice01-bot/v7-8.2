from __future__ import annotations
import os
import httpx

def status() -> dict:
    ntfy = bool(os.getenv("NTFY_TOPIC", "").strip())
    telegram = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())
    return {
        "configured": ntfy or telegram,
        "ntfy": ntfy,
        "telegram": telegram,
        "channels": [x for x, ok in (("ntfy", ntfy), ("telegram", telegram)) if ok],
    }

def send(title: str, message: str, priority: int = 3) -> dict:
    """Deliver a notification. Deduplication/state logic lives persistently in server.py."""
    delivered = []
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if topic:
        base = os.getenv("NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")
        try:
            r = httpx.post(
                f"{base}/{topic}",
                content=message.encode(),
                headers={"Title": title, "Priority": str(priority), "Tags": "chart_with_upwards_trend"},
                timeout=8,
            )
            r.raise_for_status()
            delivered.append("ntfy")
        except Exception:
            pass

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": f"{title}\n\n{message}"},
                timeout=8,
            )
            r.raise_for_status()
            delivered.append("telegram")
        except Exception:
            pass
    return {"ok": bool(delivered), "delivered": delivered}
