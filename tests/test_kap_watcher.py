import contextlib
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import os
from unittest import mock

from kap_watcher import alerts, cli, demo, evaluate, ingest, keywords, llm, numbers
from kap_watcher.analyze import Disclosure, analyze, check

ROOT = Path(__file__).resolve().parent.parent
SRC = "Pay başına brüt 1,25 TL, toplam 312.500.000 TL kâr payı 28.05.2026 tarihinde ödenecektir."


class Numbers(unittest.TestCase):
    def test_turkish_and_english_formats(self):
        self.assertEqual(numbers.number_values("312.500.000"), {Decimal("312500000")})
        self.assertEqual(numbers.number_values("1,25"), {Decimal("1.25")})
        self.assertEqual(numbers.number_values("85,000,000"), {Decimal("85000000")})
        self.assertEqual(numbers.number_values("1.250"), {Decimal("1250"), Decimal("1.25")})

    def test_summary_numbers_must_be_in_source(self):
        self.assertEqual(numbers.unsupported("Total TRY 312,500,000 paid on 28 May 2026, 1.25 per share", SRC), [])
        self.assertEqual(numbers.unsupported("toplam 312.500.000 TL, 28 Mayıs 2026", SRC), [])
        self.assertEqual(numbers.unsupported("toplam 300.000.000 TL", SRC), ["300.000.000"])
        self.assertEqual(numbers.unsupported("ödeme 29.05.2026", SRC), ["29.05.2026"])

    def test_scale_words(self):
        self.assertEqual(numbers.unsupported("USD 42,000,000", "contract value is USD 42 million"), [])


class Check(unittest.TestCase):
    def good(self):
        return {"summary_tr": "Toplam 312.500.000 TL kâr payı ödenecek.", "summary_en": "TRY 312,500,000 dividend.",
                "quotes": ["toplam 312.500.000 TL kâr payı"]}

    def test_passes_with_backing_quote(self):
        self.assertEqual(check(self.good(), SRC), [])

    def test_fails_on_invented_quote_or_unquoted_number(self):
        bad = self.good() | {"quotes": ["toplam 999 TL"]}
        self.assertTrue(any("quote not found" in p for p in check(bad, SRC)))
        unquoted = self.good() | {"summary_en": "Paid on 28.05.2026."}
        self.assertTrue(any("28.05.2026" in p for p in check(unquoted, SRC)))

    def test_analyze_repairs_once_then_reports(self):
        calls = []

        def fake(system, user):
            calls.append(user)
            return {"event_type": "dividend", "amount": "312.500.000 TL", "summary_tr": "1 milyar TL",
                    "summary_en": "x", "quotes": []}
        a = analyze(Disclosure("DMGDA", "Kar Payı", SRC), chat=fake)
        self.assertEqual(len(calls), 2)
        self.assertIn("failed verification", calls[1])
        self.assertFalse(a.verified)
        self.assertEqual(a.event_type, "dividend")

    def test_list_wrapped_answer(self):
        a = analyze(Disclosure("X", "", SRC), chat=lambda s, u: [{"event_type": "dividend", "quotes": []}])
        self.assertEqual(a.event_type, "dividend")
        self.assertEqual(analyze(Disclosure("X", "", SRC), chat=lambda s, u: ["junk"]).event_type, "other")

    def test_unknown_label_becomes_other(self):
        a = analyze(Disclosure("X", "", SRC), chat=lambda s, u: {"event_type": "weird", "quotes": []})
        self.assertEqual(a.event_type, "other")


class Keywords(unittest.TestCase):
    def test_title_beats_body(self):
        self.assertEqual(keywords.classify("Pay Geri Alım Programı", "kar payı politikası"), "buyback")
        self.assertEqual(keywords.classify("Özel Durum Açıklaması (Genel)", "İhaleyi kazandık."), "contract_tender")
        self.assertEqual(keywords.classify("Kredi Derecelendirmesi", "Not yükseltildi."), "other")


class Ingest(unittest.TestCase):
    def test_text_headers_html_and_filename_ticker(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "a.txt").write_text("Ticker: dmgda\nTitle: Kar Payı\n\n" + SRC, "utf-8")
            (t / "THYAO_1.html").write_text("<html><title>Özel Durum</title><script>x=1</script>"
                                            "<body><p>Metin 5 TL</p></body></html>", "utf-8")
            a, h = ingest.load(t / "a.txt")[0], ingest.load(t / "THYAO_1.html")[0]
            self.assertEqual((a.ticker, a.title, a.text), ("DMGDA", "Kar Payı", SRC))
            self.assertEqual((h.ticker, h.title, h.text), ("THYAO", "Özel Durum", "Metin 5 TL"))
            self.assertEqual(len(ingest.files([t])), 2)


class Alerts(unittest.TestCase):
    def test_watchlist(self):
        wl = {"DMGDA": {"dividend"}, "*": {"m_and_a"}, "THYAO": set()}
        self.assertTrue(alerts.matches(wl, "dmgda", "dividend"))
        self.assertFalse(alerts.matches(wl, "DMGDA", "buyback"))
        self.assertTrue(alerts.matches(wl, "ANY", "m_and_a"))
        self.assertTrue(alerts.matches(wl, "THYAO", "other"))

    def test_cli_keywords_only_offline(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["run", str(ROOT / "examples" / "inbox"), "--keywords-only",
                      "--watchlist", str(ROOT / "examples" / "watchlist.json")])
        self.assertIn("[DMGDA] DIVIDEND", out.getvalue())
        self.assertIn("Not investment advice", out.getvalue())


class Provider(unittest.TestCase):
    def test_cloud_first_then_ollama(self):
        keys = ("KAP_LLM_PROVIDER", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "KAP_LLM_BASE_URL", "KAP_LLM_MODEL")
        clean = {k: v for k, v in os.environ.items() if k not in keys}
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertEqual((llm.provider(), llm.model_name()), ("ollama", "qwen3.5:9b"))
            os.environ["DEEPSEEK_API_KEY"] = "x"
            self.assertEqual(llm.provider(), "deepseek")
            os.environ["GEMINI_API_KEY"] = "x"
            self.assertEqual(llm.provider(), "gemini")
            os.environ["KAP_LLM_PROVIDER"] = "ollama"
            self.assertEqual(llm.provider(), "ollama")


    def test_gemma_thoughts_stripped_and_cached(self):
        reply = {"choices": [{"message": {"content": '<thought>hmm {"x": 1}</thought>{"event_type": "other"}'}}],
                 "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"KAP_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "x", "KAP_CACHE_DIR": tmp}), \
                mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: Resp(json.dumps(reply).encode())) as op:
            self.assertEqual(llm.chat_json("s", "u"), {"event_type": "other"})
            self.assertEqual(llm.chat_json("s", "u"), {"event_type": "other"})
            self.assertEqual(op.call_count, 1)


class Demo(unittest.TestCase):
    def test_replay_runs_offline_and_writes_page(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
            page = Path(tmp) / "index.html"
            demo.run(force_replay=True, out=page)
            html = page.read_text("utf-8")
        self.assertIn("mode: replay (recorded", out.getvalue())
        self.assertIn("6 summaries passed the number check", out.getvalue())
        self.assertIn("Realistic examples, not real filings", html)
        self.assertNotIn('class="bad"', html)

    def test_highlight_marks_unquoted_numbers(self):
        h = demo._highlight("toplam 312.500.000 TL ve 99 TL", ["toplam 312.500.000 TL"])
        self.assertIn('<mark class="ok"', h)
        self.assertIn('class="bad" title="not in any quote">99<', h)


class Eval(unittest.TestCase):
    def test_metrics(self):
        m = evaluate.per_class(["dividend", "dividend", "other"], ["dividend", "other", "other"])
        self.assertEqual(m["dividend"], {"precision": 1.0, "recall": 0.5, "f1": 0.667, "support": 2})
        self.assertEqual(m["other"]["precision"], 0.5)

    def test_field_match(self):
        self.assertTrue(evaluate.field_match("amount", "312.500.000 TL", "TRY 312,500,000"))
        self.assertTrue(evaluate.field_match("date", "28.05.2026", "2026-05-28"))
        self.assertTrue(evaluate.field_match("counterparty", "Ege Tarım Ürünleri A.Ş.", "Ege Tarım Ürünleri"))
        self.assertFalse(evaluate.field_match("amount", None, "5 TL"))

    def test_dataset_is_well_formed(self):
        for name in ("disclosures.jsonl", "heldout.jsonl"):
            path = ROOT / "data" / name
            if not path.exists():
                continue
            for line in path.read_text("utf-8").splitlines():
                r = json.loads(line)
                self.assertIn(r["label"], keywords.LABELS, r["id"])
                for k in ("amount", "date", "counterparty"):
                    if r[k]:
                        self.assertIn(r[k], r["text"], (r["id"], k))


if __name__ == "__main__":
    unittest.main()
