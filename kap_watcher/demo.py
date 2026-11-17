"""`python -m kap_watcher demo`: no key needed.

Model resolution: cloud key in env -> local Ollama with the model -> replay of
recorded responses (examples/recorded.json). Prints the alerts a sample
watchlist fires and writes a static HTML page (docs/index.html)."""
from __future__ import annotations

import hashlib
import html
import json
import os
import time
import urllib.request
from pathlib import Path

from . import alerts, llm, numbers
from .analyze import Analysis, Disclosure, analyze

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
RECORDED = EXAMPLES / "recorded.json"
RESULTS = [  # (label, results file) for the comparison table
    ("keyword baseline", None), ("qwen3.5:9b (local)", "qwen3.5-9b"),
    ("gemma-4-31b-it (cloud)", "gemma-4-31b-it"), ("gemini-3.5-flash-lite (cloud)", "gemini-3.5-flash-lite"),
]


def _key(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode()).hexdigest()


def ollama_ready() -> bool:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=3) as r:
            names = {m["name"] for m in json.load(r)["models"]}
    except Exception:
        return False
    return (os.environ.get("KAP_LLM_MODEL") or llm.PROVIDERS["ollama"][2]) in names


def resolve(force_replay: bool = False) -> str:
    if force_replay:
        return "replay"
    if os.environ.get("KAP_LLM_PROVIDER") or any(os.environ.get(v) for v in
                                                   ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "KAP_LLM_BASE_URL")):
        return "live"
    if ollama_ready():
        os.environ["KAP_LLM_PROVIDER"] = "ollama"
        return "live"
    return "replay"


def replay_chat(recorded: dict):
    def chat(system, user):
        try:
            return recorded["responses"][_key(system, user)]
        except KeyError:
            raise llm.LLMError("no recorded response for this input (the prompt or disclosure changed)") from None
    return chat


def recording_chat(store: dict):
    def chat(system, user):
        out = llm.chat_json(system, user)
        store[_key(system, user)] = out
        return out
    return chat


def _highlight(summary: str, quotes: list[str]) -> str:
    """Escape the summary and mark each number green (in a quote) or red."""
    values = set().union(*(v for _, v in numbers.extract(" ".join(quotes))[0])) if quotes else set()
    out, last = [], 0
    for m in numbers.NUMBER.finditer(summary):
        ok = bool(numbers.number_values(m.group()) & values) or m.group() in " ".join(quotes)
        out.append(html.escape(summary[last:m.start()]))
        out.append(f'<mark class="{"ok" if ok else "bad"}" title="{"found in a source quote" if ok else "not in any quote"}">'
                   f"{html.escape(m.group())}</mark>")
        last = m.end()
    out.append(html.escape(summary[last:]))
    return "".join(out)


def _results_table() -> str:
    head = "".join(f"<th>{html.escape(n)}</th>" for n, _ in RESULTS)
    rows = []
    for set_name, label in (("heldout", "held-out (27)"), ("hard", "hard (18)")):
        cells = []
        for name, slug in RESULTS:
            f = ROOT / "results" / f"eval-{set_name}-{slug or 'qwen3.5-9b'}.json"
            if not f.exists():
                cells.append("<td>not run</td>")
                continue
            r = json.loads(f.read_text("utf-8"))
            acc = r["keyword_baseline" if slug is None else "llm"]["_accuracy"]
            cells.append(f"<td>{acc:.2f}</td>")
        rows.append(f"<tr><th>{label}</th>{''.join(cells)}</tr>")
    return f"<table><tr><th>set</th>{head}</tr>{''.join(rows)}</table>"


def render(items: list[tuple[Disclosure, Analysis, bool]], mode: str) -> str:
    cards = []
    for d, a, fired in items:
        fields = "".join(f"<dt>{k}</dt><dd>{html.escape(getattr(a, k) or '—')}</dd>"
                         for k in ("amount", "date", "counterparty"))
        if a.verified:
            summ = (f'<p><span class="lang">TR</span> {_highlight(a.summary_tr, a.quotes)}</p>'
                    f'<p><span class="lang">EN</span> {_highlight(a.summary_en, a.quotes)}</p>'
                    '<p class="check ok">✓ every number in both summaries appears in a verbatim source quote</p>')
        else:
            summ = ('<p class="check bad">✗ summary withheld: ' + html.escape("; ".join(a.problems[:3])) + "</p>")
        quotes = "".join(f"<li>“{html.escape(q)}”</li>" for q in a.quotes)
        badge = '<span class="alert on">alert fired</span>' if fired else '<span class="alert">no alert (not on watchlist)</span>'
        cards.append(f"""<article>
<header><span class="ticker">{html.escape(d.ticker)}</span> <span class="title">{html.escape(d.title)}</span></header>
<blockquote>{html.escape(d.text)}</blockquote>
<div class="out"><p><span class="cls">{a.event_type}</span> {badge}</p>
<dl>{fields}</dl>{summ}
<details><summary>source quotes ({len(a.quotes)})</summary><ul>{quotes}</ul></details></div>
</article>""")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>kap-watcher demo</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#5f5f5a;--line:#e3e2dd;--ok:#d9f2df;--okink:#17602b;--bad:#fbe0dc;--badink:#8a1f11;--accent:#0b5cad}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1f1f1d;--ink:#ecebe6;--muted:#a3a29b;--line:#34332f;--ok:#1d3b25;--okink:#9be3ad;--bad:#47231d;--badink:#f4b0a4;--accent:#7ab4f0}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 48px}}h1{{margin:0 0 4px;font-size:26px}}
.lede{{color:var(--muted);margin:0 0 16px}}.note{{border:1px solid var(--line);background:var(--card);padding:10px 14px;border-radius:8px;font-size:14px}}
article{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:16px 0;overflow:hidden}}
article header{{padding:10px 14px;border-bottom:1px solid var(--line);font-weight:600}}
.ticker{{font-family:ui-monospace,Menlo,monospace;color:var(--accent)}}
blockquote{{margin:0;padding:12px 14px;color:var(--muted);border-bottom:1px solid var(--line);font-size:14px}}
.out{{padding:12px 14px}}.cls{{font-family:ui-monospace,Menlo,monospace;font-weight:700}}
.alert{{font-size:12px;margin-left:8px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}}
.alert.on{{background:var(--accent);border-color:var(--accent);color:var(--card)}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:8px 0;font-size:14px}}dt{{color:var(--muted)}}dd{{margin:0}}
.lang{{font-size:11px;font-weight:700;color:var(--muted);margin-right:4px}}
mark{{border-radius:3px;padding:0 2px}}mark.ok{{background:var(--ok);color:var(--okink)}}mark.bad{{background:var(--bad);color:var(--badink)}}
.check{{font-size:13px;margin:4px 0}}.check.ok{{color:var(--okink)}}.check.bad{{color:var(--badink)}}
details{{font-size:13px;color:var(--muted)}}table{{border-collapse:collapse;width:100%;background:var(--card);font-size:14px;display:block;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:6px 10px;text-align:left}}a{{color:var(--accent)}}
</style></head><body><main>
<h1>kap-watcher</h1>
<p class="lede">Classifies Turkish public-company disclosures (KAP), extracts amount, date and counterparty, and writes Turkish and English summaries in which every number must appear in a verbatim source quote.</p>
<p class="note"><strong>Realistic examples, not real filings.</strong> The six disclosures below are written in KAP style about fictional companies. They come from the independently written evaluation sets.
Model output: <code>{html.escape(mode)}</code>. Watchlist: any ticker for dividend, M&amp;A, legal and capital events, plus HENRJ for contracts.
Not investment advice. <a href="https://github.com/oguzhanozfe/kap-watcher">Source and method on GitHub</a>.</p>
{''.join(cards)}
<h2>Classification accuracy</h2>
<p class="lede">Fictional KAP-style sets written by a separate agent. The <em>hard</em> set is all traps: a disclosure that mentions one event but is about another, multi-event disclosures, corrections, items that look like a dividend or buyback but are not, and amounts in words. With n=18–27, one mistake moves accuracy by 4–6 points.</p>
{_results_table()}
</main></body></html>
"""


def run(force_replay: bool = False, record: bool = False, out: Path | None = ROOT / "docs" / "index.html") -> int:
    mode = "live" if record else resolve(force_replay)
    recorded = json.loads(RECORDED.read_text("utf-8")) if RECORDED.exists() else {"responses": {}}
    if mode == "replay":
        chat, label = replay_chat(recorded), f"replay (recorded {recorded.get('model')}, {recorded.get('date')})"
    elif record:
        store: dict = {}
        chat, label = recording_chat(store), f"{llm.provider()} {llm.model_name()}"
    else:
        chat, label = llm.chat_json, f"live ({llm.provider()} {llm.model_name()})"
    print(f"mode: {label}\n")
    wl = alerts.load_watchlist(EXAMPLES / "demo-watchlist.json")
    items = []
    for line in (EXAMPLES / "demo.jsonl").read_text("utf-8").splitlines():
        r = json.loads(line)
        d = Disclosure(r["ticker"], r["title"], r["text"], id=r["id"])
        a = analyze(d, chat=chat)
        fired = alerts.matches(wl, d.ticker, a.event_type)
        items.append((d, a, fired))
        if fired:
            print(alerts.format_alert(d, a) + "\n")
        else:
            print(f"[{d.ticker}] {a.event_type} - no alert (not on the watchlist)\n")
    if record:
        RECORDED.write_text(json.dumps({"model": llm.model_name(), "date": time.strftime("%Y-%m-%d"),
                                        "responses": store}, ensure_ascii=False, indent=1), "utf-8")
        label = f"recorded {llm.model_name()}"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(items, label), "utf-8")
        print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    verified = sum(a.verified for _, a, _ in items)
    print(f"{len(items)} disclosures, {sum(f for *_, f in items)} alerts, {verified} summaries passed the number check")
    return 0
