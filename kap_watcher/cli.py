"""kap-watcher command line.

  python -m kap_watcher run inbox/ --watchlist watchlist.json [--keywords-only] [--watch 60]
  python -m kap_watcher eval [--out results/eval.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import alerts, evaluate, ingest
from .analyze import analyze, analyze_keywords


def process(paths, watchlist, keywords_only, seen: set, ticker=None) -> int:
    n = 0
    for f in ingest.files(paths):
        for d in ingest.load(f, ticker):
            key = f"{f}:{d.id}"
            if key in seen:
                continue
            seen.add(key)
            a = analyze_keywords(d) if keywords_only else analyze(d)
            if alerts.matches(watchlist, d.ticker, a.event_type):
                msg = alerts.format_alert(d, a)
                print(msg + "\n", flush=True)
                alerts.send_telegram(msg)
                n += 1
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kap-watcher", description="Summarise, classify and alert on KAP disclosures you saved.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="process saved disclosures (.txt/.html/.pdf/.jsonl files or folders)")
    r.add_argument("paths", nargs="+", type=Path)
    r.add_argument("--watchlist", type=Path)
    r.add_argument("--ticker", help="ticker for files that do not name one")
    r.add_argument("--keywords-only", action="store_true", help="no model: keyword class + source excerpt")
    r.add_argument("--watch", type=int, metavar="SECONDS", help="keep polling the paths for new files")
    r.add_argument("--state", type=Path, help="JSON file remembering processed files across runs")
    e = sub.add_parser("eval", help="score keyword baseline and LLM on the labelled set")
    e.add_argument("--data", type=Path, default=Path("data/disclosures.jsonl"))
    e.add_argument("--out", type=Path)
    e.add_argument("--workers", type=int, default=2)
    e.add_argument("--limit", type=int)
    args = p.parse_args(argv)

    if args.cmd == "eval":
        res = evaluate.run(args.data, args.out, args.workers, args.limit)
        print(evaluate.table(res))
        print(json.dumps({k: res[k] for k in ("provider", "model", "usage", "llm_errors", "fields", "summary_number_check_pass_rate",
                                              "latency_s_median")}, indent=1))
        return 0

    wl = alerts.load_watchlist(args.watchlist)
    seen = set(json.loads(args.state.read_text())) if args.state and args.state.exists() else set()
    while True:
        process(args.paths, wl, args.keywords_only, seen, args.ticker)
        if args.state:
            args.state.write_text(json.dumps(sorted(seen)))
        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main())
