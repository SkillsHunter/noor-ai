"""Step 2: translate the visitor's words.

Two backends share one interface, `translate(text, src, tgt) -> Translation`:

* NLLBTranslator - Meta's open NLLB-200 model (default: the distilled 600M
  checkpoint, ~2.5 GB, runs on CPU). Used in production.
* LiteTranslator - no model download. Passes English through, and knows a tiny
  phrasebook of demo sentences. Lets the pipeline, tests and the class demo run
  anywhere. Anything it can't translate is marked `ok=False` so the pipeline
  flags it rather than pretending.
"""
from dataclasses import dataclass
from functools import lru_cache

from .config import NLLB_CODES, Settings


@dataclass
class Translation:
    text: str
    src: str
    tgt: str
    ok: bool = True
    backend: str = ""


class NLLBTranslator:
    def __init__(self, model_name: str):
        # Imported lazily so the lite mode never needs torch/transformers.
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self._tok = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self._tok_cls = AutoTokenizer
        self._name = model_name

    def translate(self, text: str, src: str, tgt: str) -> Translation:
        if src == tgt or not text.strip():
            return Translation(text, src, tgt, True, "nllb")
        if src not in NLLB_CODES or tgt not in NLLB_CODES:
            return Translation(text, src, tgt, False, "nllb")
        self._tok.src_lang = NLLB_CODES[src]
        inputs = self._tok(text, return_tensors="pt", truncation=True, max_length=400)
        out = self._model.generate(
            **inputs,
            forced_bos_token_id=self._tok.convert_tokens_to_ids(NLLB_CODES[tgt]),
            max_new_tokens=400,
        )
        return Translation(self._tok.batch_decode(out, skip_special_tokens=True)[0], src, tgt, True, "nllb")


class LiteTranslator:
    """Demo stand-in. NOT a real translator."""
    PHRASEBOOK = {
        ("de", "en"): {
            "die farm war fantastisch, aber der eingang war schwer zu finden.":
                "The farm was fantastic, but the entrance was difficult to find.",
            "kein schild an der straße. wir haben uns verfahren.":
                "No sign on the road. We got lost.",
            "wir hätten gern kaffee gekauft, aber es gab keinen zu kaufen.":
                "We would have liked to buy coffee, but there was none for sale.",
        },
        ("fr", "en"): {
            "la dégustation de café était le meilleur moment !":
                "The coffee tasting was the best moment!",
            "il n'y avait pas de toilettes et pas d'ombre.":
                "There were no toilets and no shade.",
        },
        ("id", "en"): {
            "jalannya licin setelah hujan.": "The path was slippery after the rain.",
        },
        ("es", "en"): {
            "el café estaba delicioso, pero el camino era resbaladizo.":
                "The coffee was delicious, but the path was slippery.",
        },
        # Into Bahasa Indonesia, for Noor's full report
        ("de", "id"): {
            "die farm war fantastisch, aber der eingang war schwer zu finden.":
                "Kebunnya luar biasa, tetapi pintu masuknya sulit ditemukan.",
            "kein schild an der straße. wir haben uns verfahren.":
                "Tidak ada papan petunjuk di jalan. Kami tersesat.",
            "wir hätten gern kaffee gekauft, aber es gab keinen zu kaufen.":
                "Kami ingin membeli kopi, tetapi tidak ada yang dijual.",
        },
        ("fr", "id"): {
            "la dégustation de café était le meilleur moment !": "Mencicipi kopi adalah momen terbaik!",
            "il n'y avait pas de toilettes et pas d'ombre.": "Tidak ada toilet dan tidak ada tempat teduh.",
        },
        ("es", "id"): {
            "el café estaba delicioso, pero el camino era resbaladizo.": "Kopinya enak, tetapi jalannya licin.",
        },
        ("en", "id"): {
            "it was okay, but that thing near the house...": "Lumayan, tapi benda di dekat rumah itu...",
            "the farm was amazing, but the entrance was difficult to find.":
                "Kebunnya luar biasa, tetapi pintu masuknya sulit ditemukan.",
            "the coffee tasting was the best part!": "Mencicipi kopi adalah bagian terbaik!",
            "there was no sign on the road.": "Tidak ada papan petunjuk di jalan.",
            "add a sign at the main road.": "Pasang papan petunjuk di jalan utama.",
        },
    }

    def translate(self, text: str, src: str, tgt: str) -> Translation:
        if src == tgt or not text.strip():
            return Translation(text, src, tgt, True, "lite")
        hit = self.PHRASEBOOK.get((src, tgt), {}).get(text.strip().lower())
        if hit:
            return Translation(hit, src, tgt, True, "lite")
        return Translation(text, src, tgt, False, "lite")


@lru_cache(maxsize=1)
def get_translator(backend: str, model_name: str):
    if backend == "nllb":
        try:
            return NLLBTranslator(model_name)
        except Exception as e:  # missing torch/transformers, or model download blocked
            import warnings
            warnings.warn(f"NLLB unavailable ({e.__class__.__name__}: {e}); using lite translator. "
                          "Untranslatable comments will be flagged for Noor.")
    return LiteTranslator()


def translator_from(settings: Settings):
    return get_translator(settings.translator, settings.nllb_model)
