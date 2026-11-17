"""Classify a disclosure, extract key fields and write a bilingual summary
whose every number is backed by a verbatim quote from the source."""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

from . import keywords, llm, numbers

SYSTEM = """You read Turkish public-company disclosures (KAP) and return JSON only.
Event types:
- dividend: cash dividend, dividend advance, dividend policy, decision not to pay, payment date
- capital_increase: rights issue, bonus issue (bedelsiz), dedicated/private placement, capital reduction+increase
- buyback: share buyback programme or transactions, sale of repurchased shares, subsidiary buying parent shares
- contract_tender: new contract, order, tender result (won or lost), distribution agreement
- m_and_a: acquisition, merger, spin-off, stake sale, joint venture, letter of intent, controlling stake transfer
- management_change: CEO/GM/CFO/board/IR appointments, resignations, board role allocation
- financial_statements: financial report, audit report, annual/activity report, restatement, delayed statements
- legal_case: lawsuit, arbitration, regulator fine, tax assessment, investigation
- other: anything else (rating, general assembly notice, insider trade, asset purchase, bond issue, price/volume statement, investment incentive)
Return exactly:
{"event_type": "<one type>",
 "amount": "<headline money figure copied from the source with currency, or null>",
 "date": "<key event date copied from the source, or null>",
 "counterparty": "<main named other party or person, copied from the source, or null>",
 "summary_tr": "<1-2 sentence plain Turkish summary>",
 "summary_en": "<1-2 sentence plain English summary>",
 "quotes": ["<verbatim source excerpt that contains each number used in the summaries>"]}
Rules: copy every number and date exactly as written in the source. Do not compute, round or
convert numbers. Do not mention numbers that are not in the source. Every number in either
summary must appear inside one of the quotes, and each quote must be copied character for character."""


@dataclass
class Disclosure:
    ticker: str
    title: str
    text: str
    source: str = ""
    id: str = ""


@dataclass
class Analysis:
    event_type: str
    amount: str | None = None
    date: str | None = None
    counterparty: str | None = None
    summary_tr: str = ""
    summary_en: str = ""
    quotes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # empty = summary verified
    method: str = "llm"

    @property
    def verified(self) -> bool:
        return not self.problems


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def check(result: dict, source: str) -> list[str]:
    """Problems with an LLM result: quotes not in the source, or summary numbers
    that no valid quote supports. Empty list means it passed."""
    src = _norm(source)
    problems, good = [], []
    for q in result.get("quotes") or []:
        if isinstance(q, str) and q.strip() and _norm(q) in src:
            good.append(q)
        else:
            problems.append(f"quote not found in source: {str(q)[:80]!r}")
    for key in ("summary_tr", "summary_en"):
        for tok in numbers.unsupported(str(result.get(key) or ""), " ".join(good)):
            problems.append(f"{key}: {tok} not backed by a source quote")
    return problems


def _clean(v):
    return v if isinstance(v, str) and v.strip() and v.strip().lower() != "null" else None


def analyze(d: Disclosure, chat=llm.chat_json) -> Analysis:
    user = f"Title: {d.title}\n\n{d.text}"
    raw = chat(SYSTEM, user)
    problems = check(raw, d.text)
    if problems:  # one repair round with the checker's feedback
        raw2 = chat(SYSTEM, user + "\n\nYour previous answer failed verification:\n- "
                    + "\n- ".join(problems) + "\nFix it. Copy numbers and quotes verbatim.")
        p2 = check(raw2, d.text)
        if len(p2) <= len(problems):
            raw, problems = raw2, p2
    et = raw.get("event_type")
    return Analysis(
        event_type=et if et in keywords.LABELS else "other",
        amount=_clean(raw.get("amount")), date=_clean(raw.get("date")),
        counterparty=_clean(raw.get("counterparty")),
        summary_tr=str(raw.get("summary_tr") or ""), summary_en=str(raw.get("summary_en") or ""),
        quotes=[q for q in raw.get("quotes") or [] if isinstance(q, str)], problems=problems,
    )


def analyze_keywords(d: Disclosure) -> Analysis:
    """Offline path: keyword class, no summary (shows a source excerpt instead)."""
    excerpt = textwrap.shorten(d.text, 240, placeholder=" ...")
    return Analysis(event_type=keywords.classify(d.title, d.text), quotes=[excerpt], method="keywords")
