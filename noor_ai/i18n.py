"""Languages on both sides of the conversation.

* Visitor side: show the questions in the visitor's language. Hand-checked
  translations ship for en/id/de/fr/es (core questions); anything else is
  machine-translated from English with NLLB at runtime, or shown in English
  if no translator is available.
* Noor's side: every question and answer option has a hand-written
  Bahasa Indonesia version (data/question_bank_id.json), so her full report
  reads naturally. Visitors' free text is machine-translated into Indonesian.
"""
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def bank_id():
    return json.loads((DATA / "question_bank_id.json").read_text())


@lru_cache(maxsize=1)
def ui_data():
    return json.loads((DATA / "ui_i18n.json").read_text())


def languages():
    return ui_data()["languages"]


def ui_strings(lang: str) -> dict:
    ui = ui_data()["ui"]
    return {**ui["en"], **ui.get(lang, {})}


# ---------------------------------------------------------- Noor (Indonesian)

def question_id_text(qid: str, english: str) -> str:
    return bank_id()["questions"].get(qid, english)


def option_id_text(option: str) -> str:
    return bank_id()["options"].get(option, option)


def answer_to_indonesian(value) -> str:
    """Translate a selected option (or list of options) into Indonesian."""
    if isinstance(value, list):
        return ", ".join(option_id_text(str(v)) for v in value)
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return option_id_text(str(value))


# ------------------------------------------------------------ visitor side

class VisitorLocalizer:
    """Puts a question bank entry into the visitor's language."""

    def __init__(self, translator=None):
        self.translator = translator
        self._cache = {}

    def _machine(self, text: str, lang: str):
        if not self.translator or not text:
            return None
        key = (text, lang)
        if key not in self._cache:
            tr = self.translator.translate(text, "en", lang)
            self._cache[key] = tr.text if tr.ok else None
        return self._cache[key]

    def question(self, q, lang: str) -> dict:
        """Return {id, question, options, type, translated} for the visitor."""
        d = ui_data()
        if lang == "en":
            text, opts, how = q.question, list(q.options), "original"
        elif lang == "id":
            text = question_id_text(q.id, q.question)
            opts = [option_id_text(o) for o in q.options]
            how = "human"
        elif q.id in d["questions"].get(lang, {}):
            text = d["questions"][lang][q.id]
            omap = d["options"].get(lang, {})
            opts = [omap.get(o) or self._machine(o, lang) or o for o in q.options]
            how = "human"
        else:
            mt = self._machine(q.question, lang)
            text = mt or q.question
            opts = [self._machine(o, lang) or o for o in q.options]
            how = "machine" if mt else "english_fallback"
        # Options are shown translated but submitted as the English originals.
        return {"id": q.id, "type": q.response_type, "question": text,
                "options": [{"value": o, "label": l} for o, l in zip(q.options, opts)],
                "translated": how}
