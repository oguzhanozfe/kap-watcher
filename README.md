# kap-watcher

[![CI](https://github.com/oguzhanozfe/kap-watcher/actions/workflows/ci.yml/badge.svg)](https://github.com/oguzhanozfe/kap-watcher/actions/workflows/ci.yml)

Reads KAP (Kamuyu Aydınlatma Platformu, Turkey's public disclosure platform)
disclosures that **you** saved or pasted, classifies the event, pulls out the
amount, date and counterparty, writes a short Turkish and English summary, and
alerts you when a disclosure matches your watchlist.

Every number in a summary must be backed by a verbatim quote from the source.
A checker enforces this; a summary that fails is withheld and the alert shows
the source quotes instead.

> **Not investment advice.** This is information tooling. Summaries and
> classifications come from a small local model and a keyword list and can be
> wrong. Always read the original disclosure on kap.org.tr.

## Why it matters

KAP publishes hundreds of disclosures a day. Most are routine; a few
(a dividend decision, a tender win, a regulator fine) matter to someone
holding the stock. A watcher that is fast, local and refuses to invent numbers
is more useful than one that is fluent and occasionally wrong about money.

## Data access: manual input only

I checked how KAP allows automated access before writing any fetch code
(17 Nov 2026):

- `kap.org.tr/robots.txt` returns 404 and `www.kap.org.tr` sits behind a WAF
  that rejects scripted requests. No robots.txt does not mean permission.
- KAP's own announcement *"Kamuyu Aydınlatma Platformu Veri Yayın Servisi
  Rest API Entegrasyonu"* (27 Nov 2024, under KAP Hakkında → Duyurular) says
  disclosures are delivered to **subscribers** through the Veri Yayın REST API,
  that subscription starts with a **data distribution agreement with Borsa
  İstanbul**, keys are issued per IP by MKK, and that high-volume requests must
  go through that API rather than the website.

So this tool does **not** scrape kap.org.tr. It works on files you provide:

| Input | How |
|---|---|
| Pasted text | `.txt`/`.md`, optional `Ticker:` and `Title:` lines at the top |
| Saved web page | `.html` (title and body text extracted with the stdlib parser) |
| Saved PDF | `.pdf`, needs the optional `pypdf` (`pip install '.[pdf]'`) |
| Batch | `.jsonl` with `ticker`, `title`, `text` per line |

The ticker comes from `--ticker`, a `Ticker:` header, or the file-name prefix
(`THYAO_2026-11-17.txt`). `--watch 60` polls a folder for new files, so you can
drop disclosures into an inbox as you read them. If you hold a Veri Yayın
subscription, its JSON can be converted to the `.jsonl` format; I have no
subscription, so there is no client for it here.

## Run

Python 3.10+, no required dependencies. A model is needed only for summaries:
Gemini API if `GEMINI_API_KEY` is set (default model `gemma-4-31b-it`, whose
free-tier quota is separate from the Gemini models'), else DeepSeek if
`DEEPSEEK_API_KEY` is set, else a local [Ollama](https://ollama.com) model (`qwen3.5:9b`). Disclosures are
public, but note that cloud providers receive the text you process.

```bash
git clone https://github.com/oguzhanozfe/kap-watcher && cd kap-watcher
python -m unittest discover -s tests          # offline, no model needed

# offline: keyword class + source excerpt, no model
python -m kap_watcher run examples/inbox --watchlist examples/watchlist.json --keywords-only

# with a model: class, fields, verified TR/EN summary
export GEMINI_API_KEY=...            # or DEEPSEEK_API_KEY, or neither for local Ollama
python -m kap_watcher run examples/inbox --watchlist examples/watchlist.json

# keep watching a folder, remember what was already processed
python -m kap_watcher run inbox/ --watchlist my-watchlist.json --watch 60 --state state.json
```

Watchlist format (`"*"` = any ticker, empty list = any event type):

```json
{"DMGDA": ["dividend", "buyback", "capital_increase"], "DRAYL": [], "*": ["m_and_a", "legal_case"]}
```

Event types: `dividend`, `capital_increase` (incl. bonus issue), `buyback`,
`contract_tender`, `m_and_a`, `management_change`, `financial_statements`,
`legal_case`, `other`.

Options:

- **Telegram:** set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`; alerts are also sent there.
- **Provider:** `KAP_LLM_PROVIDER=gemini|deepseek|ollama|openai` forces one;
  `KAP_LLM_MODEL` overrides the model; `OLLAMA_HOST` points at another Ollama;
  `openai` means any OpenAI-compatible endpoint via `KAP_LLM_BASE_URL` and
  `KAP_LLM_API_KEY`. Keys are read from the environment only; tests and CI need none.
- **Cache:** model responses are stored in `.kap-cache/`, keyed by a hash of the
  request. Set `KAP_CACHE_DIR` to move the cache, or set it to `off` to disable it.

## Measured results

Three hand-labelled sets of KAP-style disclosures, all about fictional
companies (see Known limits), scored on 9 classes:

- **main** ([data/disclosures.jsonl](data/disclosures.jsonl), 65 items). I wrote
  these, and I also wrote the keyword rules and the class definitions in the
  prompt. Both scores on this set are therefore optimistic.
- **held-out** ([data/heldout.jsonl](data/heldout.jsonl), 27 items, 3 per class).
  - Written afterwards by a separate agent (Claude Sonnet) that never saw the
    rules, the prompt or the main set. I then checked the labels.
  - 17 of the 27 have the generic title *Özel Durum Açıklaması (Genel)*, and 5
    are in English.
- **hard** ([data/hard.jsonl](data/hard.jsonl), 18 items). Also written
  independently by Claude Sonnet, as deliberate traps in five categories:
  - an event is mentioned but the disclosure is about something else;
  - several events in one disclosure;
  - a correction or cancellation of an earlier disclosure;
  - an `other` item that looks like a dividend or a buyback;
  - amounts written in words or in thousands.

  The label is the event the disclosure is *about*.

Neither independent set was drafted by a model that is evaluated here.

All runs were on 2026-11-17 at temperature 0, with the same prompt and the
same number check. Raw outputs, per-item predictions and summaries are in
[results/](results/).

- **Local:** `qwen3.5:9b` via Ollama (digest `56671c2a…`).
- **Cloud:** `gemma-4-31b-it` and `gemini-3.5-flash-lite`, through the Gemini
  API's free tier.

Classification accuracy (macro F1 in brackets):

| set | n | keyword baseline | qwen3.5:9b (local) | gemma-4-31b-it (cloud) | gemini-3.5-flash-lite (cloud) |
|---|---|---|---|---|---|
| main (my own) | 65 | 0.94 (0.94) | 1.00 (1.00) | not run | not run |
| held-out | 27 | 0.78 (0.77) | 1.00 (1.00) | 1.00 (1.00) | not run |
| **hard** | 18 | **0.50 (0.41)** | **0.83 (0.87)** | **0.94 (0.96)** | **0.83 (0.87)** |

Hard set, number correct by trap category:

| trap | n | keyword | qwen3.5:9b | gemma-4-31b-it | flash-lite |
|---|---|---|---|---|---|
| mentions one event, is about another | 4 | 1 | 3 | 4 | 4 |
| multi-event | 4 | 2 | 4 | 4 | 4 |
| correction or cancellation | 4 | 3 | 4 | 4 | 4 |
| `other` that looks like dividend/buyback | 4 | 2 | 2 | 3 | 1 |
| amount in words or thousands | 2 | 1 | 2 | 2 | 2 |

What the hard set shows:

- **The keyword baseline breaks** wherever the body contains another class's
  words. Its score falls from 0.94 on my own set to 0.78 on held-out and 0.50
  on hard.
- **The models' weak spot is the lookalikes**, items that read like a dividend
  or a buyback but aren't one:
  - an extraordinary general assembly agenda that lists a dividend item no one
    has decided yet;
  - a shareholder buying shares for themselves;
  - a fund, run by a subsidiary, buying the parent's shares.
- **That last case is genuinely arguable.** My prompt counts a subsidiary
  buying parent shares as a buyback; the writer labelled it `other` because the
  buyer is a fund the subsidiary manages. Every model said `buyback`. It is
  Gemma's only miss.
- **qwen3.5:9b also missed** a set of financial statements whose notes describe
  a buyback.

Fields and summaries:

| | qwen held-out | gemma held-out | qwen hard | gemma hard | flash-lite hard |
|---|---|---|---|---|---|
| amount matches gold | 0.85 | 0.96 | 0.83 | 0.89 | 0.78 |
| date matches gold | 0.96 | 1.00 | 0.83 | 1.00 | 1.00 |
| counterparty matches gold | 0.81 | 0.93 | 0.83 | 0.94 | 0.94 |
| summaries passing the number check | 1.00 | 1.00 | 0.89 | 1.00 | 1.00 |

On the main set, qwen3.5:9b matched the gold amount 0.88 of the time, the date
0.97 and the counterparty 0.95. Its summaries passed the number check on 64 of
65 items.

**The number check withheld 3 summaries**, all from the local model:

- **Main set, one summary.** It used the year "2025" from the source without
  including it in a quote.
- **Hard set, two summaries.** One quoted an amount written in words slightly
  wrongly. The other used a number with no supporting quote.

Every withheld summary is replaced by its quotes in the alert, as designed.

**Speed and sample size:**

- **Local speed:** about 21 to 25 s per disclosure when the shared Mac was
  quiet. Under load from other sessions it took much longer.
- **Cloud latency isn't reported:** reruns served from the response cache make
  it meaningless.
- **Small sets:** 18 or 27 items means one mistake moves accuracy by 4 to
  6 points.
- **Missing cloud runs:** the main set and flash-lite on held-out weren't run on
  cloud. The free tier allows about 20 requests per model per day on a key
  shared with other projects, and `gemma-4-31b-it` kept returning 503s, so
  those runs needed retries.

Reproduce. Responses are cached in `.kap-cache/`, so a rerun only calls the
model for items that are missing:

```bash
python -m kap_watcher eval --data data/hard.jsonl --out results/eval-hard-gemma-4-31b-it.json
KAP_LLM_MODEL=gemini-3.5-flash-lite python -m kap_watcher eval --data data/hard.jsonl
KAP_LLM_PROVIDER=ollama python -m kap_watcher eval --data data/heldout.jsonl
```

Example alert from the local model ([results/demo-run-qwen3.5-9b.txt](results/demo-run-qwen3.5-9b.txt)):

```text
[DMGDA] DIVIDEND - Kar Payı Dağıtım İşlemlerine İlişkin Bildirim
  amount: 312.500.000 TL
  date: 28.05.2026
  TR: Örnek Gıda Sanayi A.Ş. Yönetim Kurulu, 2025 yılı kârından pay başına brüt 1,25 TL olmak üzere toplam 312.500.000 TL nakit kâr payı dağıtılmasının Genel Kurul onayına sunulmasına karar vermiştir.
  EN: The Board of Directors of Örnek Gıda Sanayi A.Ş. has decided to submit for General Assembly approval the distribution of a total cash dividend of 312,500,000 TL based on a gross amount of 1.25 TL per share from the 2025 profit.
  source: "2025 yılı kârından"
  source: "pay başına brüt 1,25 TL"
  source: "toplam 312.500.000 TL nakit kâr payı dağıtılmasının"
  source: "Ödemenin 28.05.2026 tarihinde yapılması önerilmektedir."
  Not investment advice. Check the original disclosure on kap.org.tr.
```

## How the number check works

The model returns `summary_tr`, `summary_en` and a list of `quotes`. The
checker ([kap_watcher/analyze.py](kap_watcher/analyze.py),
[kap_watcher/numbers.py](kap_watcher/numbers.py)):

1. drops any quote that is not a character-for-character substring of the
   source (whitespace-normalised);
2. reads every number and date in both summaries, accepting Turkish
   (`312.500.000`, `1,25`) and English (`312,500,000`, `1.25`) formats,
   `28.05.2026` / `28 Mayıs 2026` / `May 28, 2026`, and `42 million`;
3. fails the summary if any number or date is not found in the surviving quotes.

On failure the model gets one repair attempt with the checker's complaints.
If it still fails, the alert withholds the summary and prints the quotes.

## Known limits

- **No live feed.** Manual input only, for the reasons above.
- **Synthetic, not real, evaluation data.** The labelled sets are realistic
  disclosures modelled on KAP templates, with fictional companies and tickers.
  They are not copies of real filings. Real filings are longer, carry tables
  and attachments, and will score differently.
- **Small sets.** 65 + 27 + 18 items. Per-class numbers rest on 1 to 10
  examples and move a lot with one mistake.
- **The number check proves presence, not meaning.** It catches invented or
  altered numbers; it does not catch a real number attached to the wrong
  thing (old capital reported as new capital) or a wrong tense. In the demo
  run the model summarised "sözleşme ... imzalanmıştır" (was signed) as
  "will be signed" and the check passed, because the numbers were right.
- **Field extraction is judged leniently** (same value, same date, or name
  containment) and "amount" is only the single headline figure.
- **PDF text** depends on `pypdf`; scanned PDFs without a text layer give nothing.

## Related

- [turkish-finance-data](https://github.com/oguzhanozfe/turkish-finance-data):
  Turkish market data imports with the same rule of using only sources that
  permit it.

## License

MIT for the code. KAP disclosures belong to their publishers; nothing from
kap.org.tr is redistributed here.
