"""Watchlist matching and alert delivery (stdout, optional Telegram)."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .analyze import Analysis, Disclosure


def load_watchlist(path: Path | None) -> dict[str, set[str]]:
    """{"THYAO": ["dividend", "buyback"], "*": ["m_and_a"]}; "*" matches any ticker
    and an empty list matches any event type. No file = alert on everything."""
    if not path:
        return {"*": set()}
    return {k.upper(): set(v) for k, v in json.loads(Path(path).read_text("utf-8")).items()}


def matches(watchlist: dict[str, set[str]], ticker: str, event: str) -> bool:
    for key in (ticker.upper(), "*"):
        if key in watchlist and (not watchlist[key] or event in watchlist[key]):
            return True
    return False


def format_alert(d: Disclosure, a: Analysis) -> str:
    lines = [f"[{d.ticker}] {a.event_type.upper()} - {d.title or d.id}"]
    for k in ("amount", "date", "counterparty"):
        if getattr(a, k):
            lines.append(f"  {k}: {getattr(a, k)}")
    if a.method == "llm" and a.verified:
        lines += [f"  TR: {a.summary_tr}", f"  EN: {a.summary_en}"]
    elif a.method == "llm":
        lines.append("  (summary withheld: failed the number check - " + "; ".join(a.problems[:3]) + ")")
    lines += [f'  source: "{q}"' for q in a.quotes]
    lines.append("  Not investment advice. Check the original disclosure on kap.org.tr.")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    """Sends only when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)
    return True
