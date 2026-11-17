"""Score the keyword baseline and the LLM against the hand-labelled set."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import keywords, llm, numbers
from .analyze import Disclosure, analyze


def per_class(gold: list[str], pred: list[str]) -> dict:
    out = {}
    for c in keywords.LABELS:
        tp = sum(g == p == c for g, p in zip(gold, pred))
        fp = sum(p == c != g for g, p in zip(gold, pred))
        fn = sum(g == c != p for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[c] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "support": tp + fn}
    out["_accuracy"] = round(sum(g == p for g, p in zip(gold, pred)) / len(gold), 3)
    out["_macro_f1"] = round(sum(out[c]["f1"] for c in keywords.LABELS) / len(keywords.LABELS), 3)
    return out


def field_match(kind: str, gold: str | None, pred: str | None) -> bool:
    if not gold or not pred:
        return not gold and not pred
    if kind == "amount":
        g, p = numbers.extract(gold)[0], numbers.extract(pred)[0]
        return bool(g and p and g[0][1] & p[0][1])
    if kind == "date":
        return bool(numbers.extract(gold)[1] & numbers.extract(pred)[1])
    g, p = gold.casefold(), pred.casefold()
    return g in p or p in g


TRAPS = {"1": "mentions one event, is about another", "2": "multi-event", "3": "correction or cancellation",
         "4": "'other' that looks like dividend/buyback", "5": "amount in words or thousands"}


def by_trap(rows, kw_preds, llm_preds) -> dict:
    """Correct counts per trap category; 'trap' starts with the category digit."""
    out = {}
    for r, k, p in zip(rows, kw_preds, llm_preds):
        t = TRAPS.get(str(r.get("trap", "")).strip()[:1])
        if t:
            c = out.setdefault(t, {"n": 0, "keyword": 0, "llm": 0})
            c["n"] += 1
            c["keyword"] += k == r["label"]
            c["llm"] += p == r["label"]
    return out


def run(data: Path, out: Path | None = None, workers: int = 2, limit: int | None = None) -> dict:
    rows = [json.loads(l) for l in Path(data).read_text("utf-8").splitlines() if l.strip()][:limit]
    gold = [r["label"] for r in rows]
    result = {"dataset": Path(data).name, "n": len(rows),
              "keyword_baseline": per_class(gold, [keywords.classify(r["title"], r["text"]) for r in rows])}

    def one(r):
        t = time.time()
        try:
            a = analyze(Disclosure(r["ticker"], r["title"], r["text"], id=r["id"]))
        except llm.LLMError as e:
            return r, None, str(e), time.time() - t
        return r, a, None, time.time() - t

    with ThreadPoolExecutor(workers) as ex:  # small batches: Ollama is shared
        done = list(ex.map(one, rows))
    preds = [a.event_type if a else "error" for _, a, _, _ in done]
    ok = [(r, a) for r, a, _, _ in done if a]
    result["provider"] = llm.provider()
    result["model"] = llm.model_name()
    result["model_digest"] = llm.model_digest()
    result["run_date"] = time.strftime("%Y-%m-%d")
    result["llm"] = per_class(gold, preds)
    result["llm_errors"] = sum(a is None for _, a, _, _ in done)
    result["fields"] = {k: round(sum(field_match(k, r[k], getattr(a, k)) for r, a in ok) / max(len(ok), 1), 3)
                        for k in ("amount", "date", "counterparty")}
    result["summary_number_check_pass_rate"] = round(sum(a.verified for _, a in ok) / max(len(ok), 1), 3)
    result["usage"] = dict(llm.USAGE)
    if any(r.get("trap") for r in rows):  # hard set: accuracy per trap category
        result["by_trap"] = by_trap(rows, [keywords.classify(r["title"], r["text"]) for r in rows], preds)
    result["latency_s_median"] = round(sorted(t for *_, t in done)[len(done) // 2], 1)
    result["items"] = [{"id": r["id"], "gold": r["label"], "keyword": keywords.classify(r["title"], r["text"]),
                        "llm": a.event_type if a else None, "error": err,
                        "amount": a and a.amount, "date": a and a.date, "counterparty": a and a.counterparty,
                        "summary_tr": a and a.summary_tr, "summary_en": a and a.summary_en,
                        "quotes": a and a.quotes, "problems": a and a.problems, "seconds": round(t, 1)}
                       for r, a, err, t in done]
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    return result


def table(result: dict) -> str:
    kb, lm = result["keyword_baseline"], result["llm"]
    rows = ["| class | n | keyword P | keyword R | LLM P | LLM R |", "|---|---|---|---|---|---|"]
    for c in keywords.LABELS:
        rows.append(f"| {c} | {kb[c]['support']} | {kb[c]['precision']:.2f} | {kb[c]['recall']:.2f} "
                    f"| {lm[c]['precision']:.2f} | {lm[c]['recall']:.2f} |")
    rows.append(f"| **accuracy** | {result['n']} | {kb['_accuracy']:.2f} | | {lm['_accuracy']:.2f} | |")
    rows.append(f"| **macro F1** | | {kb['_macro_f1']:.2f} | | {lm['_macro_f1']:.2f} | |")
    return "\n".join(rows)
