"""Find numbers and dates in Turkish or English text and check that a summary
only uses numbers that appear in its source.

A token like "1.250" is ambiguous (Turkish 1250, English 1.25), so every token
maps to the *set* of values it could mean; two tokens match when the sets meet.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_M = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DATE_DMY_WORD = re.compile(rf"\b(\d{{1,2}})\s+({_M})\s+(\d{{4}})\b", re.I)
DATE_MDY_WORD = re.compile(rf"\b({_M})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
SCALE = re.compile(r"\s*(milyon|million|mn|milyar|billion|bn)\b", re.I)
SCALES = {"milyon": 10**6, "million": 10**6, "mn": 10**6, "milyar": 10**9, "billion": 10**9, "bn": 10**9}


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s).normalize()
    except InvalidOperation:
        return None


def _grouped(int_part: str, sep: str) -> bool:
    groups = int_part.split(sep)
    return 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])


def number_values(token: str) -> set[Decimal]:
    """All values a numeric token could mean under Turkish or English formatting."""
    out = set()
    for thousands, decimal in ((".", ","), (",", ".")):
        int_part, _, frac = token.partition(decimal)
        if decimal in frac:
            continue
        if thousands in int_part and not _grouped(int_part, thousands):
            continue
        v = _dec(int_part.replace(thousands, "") + ("." + frac if frac else ""))
        if v is not None:
            out.add(v)
    return out


def extract(text: str) -> tuple[list[tuple[str, set]], set[tuple[int, int, int]]]:
    """Return ([(token, values)], {(year, month, day)}) found in text."""
    dates: set[tuple[int, int, int]] = set()

    def take(pattern, order):
        nonlocal text

        def repl(m):
            g = m.groups()
            vals = [g[i] for i in order]
            y, mo, d = int(vals[0]), vals[1], int(vals[2])
            mo = MONTHS[mo.lower()] if not mo.isdigit() else int(mo)
            dates.add((y, mo, d))
            return f" {y} "  # keep the year visible as a plain number
        text = pattern.sub(repl, text)

    take(DATE_NUMERIC, (2, 1, 0))
    take(DATE_ISO, (0, 1, 2))
    take(DATE_DMY_WORD, (2, 1, 0))
    take(DATE_MDY_WORD, (2, 0, 1))

    nums = []
    for m in NUMBER.finditer(text):
        values = number_values(m.group())
        scale = SCALE.match(text, m.end())
        if scale:
            values |= {(v * SCALES[scale.group(1).lower()]).normalize() for v in values}
        nums.append((m.group(), values))
    return nums, dates


def unsupported(summary: str, source: str) -> list[str]:
    """Numbers/dates in summary that do not appear in source. Empty list = pass."""
    s_nums, s_dates = extract(summary)
    src_nums, src_dates = extract(source)
    src_values = set().union(*(v for _, v in src_nums)) if src_nums else set()
    bad = [tok for tok, vals in s_nums if not vals & src_values]
    bad += ["%02d.%02d.%d" % (d, m, y) for (y, m, d) in sorted(s_dates - src_dates)]
    return bad
