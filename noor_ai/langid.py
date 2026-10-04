"""Step 1: detect which language the visitor wrote in.

Uses `lingua-language-detector` (open source, runs offline, no model download).
Returns an ISO 639-1 code plus a confidence score so low-confidence detections
can be flagged instead of guessed.
"""
from dataclasses import dataclass
from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

# Restricting the candidate set makes short texts far more accurate.
CANDIDATES = [
    Language.ENGLISH, Language.INDONESIAN, Language.MALAY, Language.GERMAN,
    Language.FRENCH, Language.SPANISH, Language.DUTCH, Language.ITALIAN,
    Language.PORTUGUESE, Language.JAPANESE, Language.KOREAN, Language.CHINESE,
    Language.SWAHILI,
]


@dataclass
class Detection:
    lang: str          # ISO 639-1, e.g. "de"
    confidence: float  # 0..1


@lru_cache(maxsize=1)
def _detector():
    return LanguageDetectorBuilder.from_languages(*CANDIDATES).with_preloaded_language_models().build()


def detect(text: str) -> Detection:
    text = (text or "").strip()
    if len(text) < 3:
        return Detection(lang="und", confidence=0.0)
    values = _detector().compute_language_confidence_values(text)
    if not values:
        return Detection(lang="und", confidence=0.0)
    best = values[0]
    code = best.language.iso_code_639_1.name.lower()
    return Detection(lang=code, confidence=round(float(best.value), 3))
