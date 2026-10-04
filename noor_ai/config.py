"""Runtime settings, read from environment variables.

Backends:
  NOOR_TRANSLATOR = nllb | lite        (lite = no model download, demo phrasebook)
  NOOR_EXTRACTOR  = ollama | rules     (rules = keyword-based, no model)
  NOOR_SMS        = console | twilio | africastalking
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    translator: str = field(default_factory=lambda: os.getenv("NOOR_TRANSLATOR", "lite"))
    extractor: str = field(default_factory=lambda: os.getenv("NOOR_EXTRACTOR", "rules"))
    sms_backend: str = field(default_factory=lambda: os.getenv("NOOR_SMS", "console"))

    # Noor's reading language, as an ISO 639-1 code (used for SMS templates)
    # and an NLLB/FLORES-200 code (used for translation).
    noor_lang: str = field(default_factory=lambda: os.getenv("NOOR_LANG", "id"))
    noor_phone: str = field(default_factory=lambda: os.getenv("NOOR_PHONE", "+620000000000"))

    # Models
    nllb_model: str = field(default_factory=lambda: os.getenv("NOOR_NLLB_MODEL", "facebook/nllb-200-distilled-600M"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("NOOR_OLLAMA_MODEL", "qwen2.5:3b"))

    # Below this confidence a reply is flagged for Noor instead of being interpreted.
    confidence_threshold: float = float(os.getenv("NOOR_CONFIDENCE_THRESHOLD", "0.6"))
    max_follow_ups: int = int(os.getenv("NOOR_MAX_FOLLOW_UPS", "6"))

    question_bank: Path = field(default_factory=lambda: Path(os.getenv(
        "NOOR_QUESTION_BANK", Path(__file__).resolve().parent.parent / "data" / "noor_feedback_question_bank.jsonl")))

    # SMS gateway credentials (only the chosen backend's are needed)
    twilio_sid: str = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", ""))
    twilio_token: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    twilio_from: str = field(default_factory=lambda: os.getenv("TWILIO_FROM", ""))
    at_username: str = field(default_factory=lambda: os.getenv("AT_USERNAME", "sandbox"))
    at_api_key: str = field(default_factory=lambda: os.getenv("AT_API_KEY", ""))
    at_sender: str = field(default_factory=lambda: os.getenv("AT_SENDER_ID", ""))


# ISO 639-1 -> NLLB (FLORES-200) codes for languages the demo knows about.
# Add more from https://github.com/facebookresearch/flores/blob/main/flores200/README.md
NLLB_CODES = {
    "en": "eng_Latn", "id": "ind_Latn", "jv": "jav_Latn", "su": "sun_Latn",
    "de": "deu_Latn", "fr": "fra_Latn", "es": "spa_Latn", "nl": "nld_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "zh": "zho_Hans", "sw": "swh_Latn", "ms": "zsm_Latn",
}
