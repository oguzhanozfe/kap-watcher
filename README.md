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
Gemini if `GEMINI_API_KEY` is set, else DeepSeek if `DEEPSEEK_API_KEY` is set,
else a local [Ollama](https://ollama.com) model (`qwen3.5:9b`). Disclosures are
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

## Measured results

Two hand-labelled sets of KAP-style disclosures (fictional companies, see
Known limits), 9 classes:

- **main** ([data/disclosures.jsonl](data/disclosures.jsonl), 65 items): I wrote these,
  and I also wrote the keyword rules and the class definitions in the prompt.
  Both scores are therefore optimistic.
- **held-out** ([data/heldout.jsonl](data/heldout.jsonl), 27 items, 3 per class): written
  afterwards by a separate agent that never saw the rules, prompt or main set,
  then label-checked by me. 17 of 27 use the generic title *Özel Durum
  Açıklaması (Genel)*, 5 are in English, and several are deliberate confusables
  (bond issue vs capital increase, insider sale vs buyback, factory purchase vs
  acquisition). This is the more honest number.

Local model: `qwen3.5:9b` via Ollama (digest `56671c2a…`), temperature 0, on a
Mac, run 2026-11-17. Raw outputs, per-item predictions and summaries:
[results/](results/).

| | keyword baseline | qwen3.5:9b (local) |
|---|---|---|
| main set accuracy (n=65) | 0.94 | 1.00 |
| main set macro F1 | 0.94 | 1.00 |
| **held-out accuracy (n=27)** | **0.78** | **1.00** |
| held-out macro F1 | 0.77 | 1.00 |

Held-out set, per class:

| class | n | keyword P | keyword R | LLM P | LLM R |
|---|---|---|---|---|---|
| dividend | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| capital_increase | 3 | 1.00 | 0.67 | 1.00 | 1.00 |
| buyback | 3 | 0.75 | 1.00 | 1.00 | 1.00 |
| contract_tender | 3 | 0.67 | 0.67 | 1.00 | 1.00 |
| m_and_a | 3 | 0.50 | 0.67 | 1.00 | 1.00 |
| management_change | 3 | 0.75 | 1.00 | 1.00 | 1.00 |
| financial_statements | 3 | 1.00 | 0.67 | 1.00 | 1.00 |
| legal_case | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| other | 3 | 0.50 | 0.33 | 1.00 | 1.00 |

The keyword baseline loses where the title is generic and the body contains
another class's words: "pay geri alımı ile bir ilgisi yoktur" (an insider sale)
reads as a buyback, "satın alınmıştır" (a factory purchase) as an acquisition.

Fields and summaries (local model):

| | main (65) | held-out (27) |
|---|---|---|
| amount matches gold | 0.88 | 0.85 |
| date matches gold | 0.97 | 0.96 |
| counterparty matches gold | 0.95 | 0.81 |
| summaries passing the number check | 0.98 (64/65) | 1.00 |
| median seconds per disclosure | 24.7 | 20.9 |

The one failure on the main set used the year "2025" from the source without
including it in a quote; the alert withheld that summary as designed.

Read these numbers with the sample size in mind: 27 held-out items means one
mistake moves accuracy by almost 4 points, and 100% on 27 easy-to-medium
items does not mean 100% on real filings.

**Cloud comparison: pending.** The default provider is now Gemini (then
DeepSeek, then local Ollama). On the run date the shared Gemini free-tier key
had used up its daily per-model quota and the DeepSeek account had no
balance, so there is no cloud result yet. Reproduce with:

```bash
python -m kap_watcher eval --data data/heldout.jsonl --out results/eval-heldout-gemini.json
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
- **Small sets.** 65 + 27 items; per-class numbers rest on 3 to 10 examples
  and move a lot with one mistake.
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
