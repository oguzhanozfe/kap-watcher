"""Keyword baseline classifier: the floor the model has to beat."""
from __future__ import annotations

LABELS = [
    "dividend", "capital_increase", "buyback", "contract_tender", "m_and_a",
    "management_change", "financial_statements", "legal_case", "other",
]

# Checked in order; first label with a hit wins. Title is checked before body
# because KAP titles are templated and more reliable than free text.
RULES = [
    ("buyback", ["geri alım", "geri alın", "geri al", "buyback", "repurchase"]),
    ("dividend", ["kar payı", "kâr payı", "kar dağıtım", "kâr dağıtım", "temettü", "dividend"]),
    ("capital_increase", ["sermaye artırım", "bedelsiz", "bedelli", "rüçhan", "yeni pay alma",
                          "capital increase", "bonus issue", "rights issue"]),
    ("m_and_a", ["birleşme", "devralma", "bölünme", "pay alımı", "pay devir", "satın alın",
                 "ortak girişim", "iştirak", "acquisition", "merger", "joint venture"]),
    ("legal_case", ["dava", "tahkim", "soruşturma", "idari para cezası", "tarh", "lawsuit",
                    "legal proceedings", "arbitration"]),
    ("management_change", ["genel müdür", "yönetim kurulu üye", "istifa", "atan", "görev dağılımı",
                           "yönetim kurulu başkan", "resignation", "appointed", "ceo", "change in management"]),
    ("financial_statements", ["finansal rapor", "finansal tablo", "bağımsız denetim", "faaliyet raporu",
                              "financial report", "financial statements"]),
    ("contract_tender", ["ihale", "sözleşme", "sipariş", "yeni iş ilişkisi", "distribütörlük",
                         "contract", "agreement", "new business relationship", "order"]),
]


def _lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def classify(title: str, text: str) -> str:
    for field in (_lower(title), _lower(text)):
        for label, words in RULES:
            if any(w in field for w in words):
                return label
    return "other"
