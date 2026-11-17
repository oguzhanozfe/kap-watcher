"""Load disclosures the user saved or pasted: .txt/.md, .html, .pdf (needs the
optional pypdf), or .jsonl records. No network access."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from .analyze import Disclosure

SUFFIXES = {".txt", ".md", ".html", ".htm", ".pdf", ".jsonl"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.title = [], 0, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        self._in_title = tag == "title"
        if tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _Text()
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    return p.title.strip(), re.sub(r"\n\s*\n+", "\n", text).strip()


def _headers(text: str) -> tuple[dict, str]:
    """Optional 'Ticker: X' / 'Title: Y' lines at the top of a pasted file."""
    meta, lines = {}, text.splitlines()
    while lines and (m := re.match(r"(?i)^\s*(ticker|title|hisse|başlık)\s*:\s*(.+)$", lines[0])):
        key = {"hisse": "ticker", "başlık": "title"}.get(m.group(1).lower(), m.group(1).lower())
        meta[key] = m.group(2).strip()
        lines.pop(0)
    return meta, "\n".join(lines).strip()


def load(path: Path, ticker: str | None = None) -> list[Disclosure]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]
        return [Disclosure(r.get("ticker", ""), r.get("title", ""), r["text"], str(path), r.get("id", ""))
                for r in rows]
    if suffix in (".html", ".htm"):
        title, text = html_to_text(path.read_text("utf-8", errors="replace"))
        meta = {"title": title}
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise SystemExit("PDF input needs: pip install pypdf  (or paste the text into a .txt file)") from e
        text = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
        meta = {}
    else:
        meta, text = _headers(path.read_text("utf-8"))
    # Ticker: flag > header > filename prefix like THYAO_2026-11-17.txt
    tick = ticker or meta.get("ticker") or path.stem.split("_")[0].upper()
    return [Disclosure(tick.upper(), meta.get("title", ""), text, str(path), path.name)]


def files(paths: list[Path]) -> list[Path]:
    out = []
    for p in map(Path, paths):
        out += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUFFIXES) if p.is_dir() else [p]
    return out
