"""Step 3: understand the feedback and extract structured information.

"The farm was amazing, but the entrance was difficult to find" ->
    sentiment: mixed (positive overall), issues: [signage], highlights: [], confidence: 0.8

Two backends share one interface, `extract(text_en) -> Extraction`:

* OllamaExtractor - a small open model (e.g. Qwen2.5-3B, Gemma 3 4B, Llama 3.2 3B)
  served locally by Ollama, asked for JSON that matches a fixed schema.
* RulesExtractor  - keyword rules, no model. Used for tests, demos and as the
  fallback if the model is down or returns invalid JSON.

Both return a confidence score; the pipeline flags anything below the threshold.
"""
import json
import re
from dataclasses import dataclass, field

import requests

from .config import Settings

# Issue/highlight tags, mapped to the question-bank categories they unlock.
TAG_TO_CATEGORY = {
    "signage": "Getting there and entrance",
    "access_road": "Getting there and entrance",
    "booking": "Booking and pre-visit communication",
    "reply_time": "Booking and pre-visit communication",
    "facilities": "Facilities and comfort",
    "price": "Price and payment",
    "payment": "Price and payment",
    "language": "Language and communication",
    "safety": "Safety, accessibility and sustainability",
    "accessibility": "Safety, accessibility and sustainability",
    "tour": "Tour content and activities",
    "coffee": "Coffee, food and products",
    "coffee_sales": "Coffee, food and products",
    "food": "Coffee, food and products",
    "hospitality": "Welcome and hospitality",
    "scenery": "Tour content and activities",
}
TAGS = sorted(TAG_TO_CATEGORY)


@dataclass
class Item:
    tag: str
    detail: str


@dataclass
class Extraction:
    sentiment: str                      # positive | mixed | negative | neutral
    issues: list = field(default_factory=list)       # [Item]
    highlights: list = field(default_factory=list)   # [Item]
    confidence: float = 0.0
    backend: str = ""

    def to_dict(self):
        return {
            "sentiment": self.sentiment,
            "issues": [vars(i) for i in self.issues],
            "highlights": [vars(i) for i in self.highlights],
            "confidence": self.confidence,
            "backend": self.backend,
        }


# ---------------------------------------------------------------- rules backend

# (tag, regex) for problems and for praise. English only: text arrives translated.
ISSUE_PATTERNS = [
    ("signage", r"(hard|difficult|couldn'?t|could not|impossible) to find|got lost|no sign|lost our way|missed the turn|entrance (was )?(hidden|unclear)"),
    ("access_road", r"road was (bad|rough|muddy)|bumpy|pothole|steep road|hard to reach"),
    ("booking", r"hard to book|booking was (hard|confusing)|couldn'?t book"),
    ("reply_time", r"(slow|late|no) (reply|response)|never (replied|answered)|took (too )?long to (reply|answer)"),
    ("facilities", r"no (toilets?|shade|water|seat|place to sit)|toilet was (dirty|bad)|nowhere to (sit|rest|wash)"),
    ("price", r"too expensive|overpriced|price was (high|unclear)|not worth"),
    ("payment", r"(no|couldn'?t) (pay|use) (by )?(card|mobile money)|no change|payment was (hard|difficult)"),
    ("language", r"couldn'?t (understand|communicate)|language (barrier|was hard)|no english"),
    ("safety", r"slippery|unsafe|dangerous|fell|(got )?hurt|slipped"),
    ("tour", r"too (long|short)|boring|rushed|nothing to do"),
    ("coffee_sales", r"(no|none) (coffee )?(for sale|to buy)|couldn'?t buy|wanted to buy|would have liked to buy"),
    ("food", r"food was (bad|cold)|no food|hungry"),
]
PRAISE_PATTERNS = [
    ("coffee", r"(coffee|tasting).{0,30}(best|great|amazing|delicious|excellent|loved)|(loved|best|great|delicious).{0,20}(coffee|tasting)"),
    ("hospitality", r"(noor|host|family).{0,30}(kind|warm|friendly|welcoming|lovely)|warm welcome|felt welcome"),
    ("tour", r"(farm|tour|walk|visit|explanation).{0,30}(great|amazing|interesting|fantastic|wonderful|loved)"),
    ("scenery", r"(view|views|scenery|landscape).{0,30}(beautiful|stunning|amazing)|beautiful (view|scenery|landscape)"),
    ("food", r"(food|lunch|snack).{0,30}(delicious|great|tasty)"),
]
POSITIVE = r"\b(amazing|fantastic|great|wonderful|loved|love|beautiful|excellent|best|delicious|friendly|enjoyed|perfect|recommend)\b"
NEGATIVE = r"\b(bad|difficult|hard|dirty|lost|slippery|expensive|boring|rude|poor|disappointing|unsafe|terrible|no)\b"
VAGUE = r"\b(okay|ok|so-so|kind of|sort of|thing|stuff|whatever|meh|hmm)\b|\.\.\.|…"


class RulesExtractor:
    def extract(self, text: str) -> Extraction:
        t = (text or "").lower()
        issues = [Item(tag, m.group(0)) for tag, p in ISSUE_PATTERNS if (m := re.search(p, t))]
        highs = [Item(tag, m.group(0)) for tag, p in PRAISE_PATTERNS if (m := re.search(p, t))]
        pos = len(re.findall(POSITIVE, t))
        neg = len(re.findall(NEGATIVE, t)) + len(issues)
        if pos and neg:
            sentiment = "mixed"
        elif pos:
            sentiment = "positive"
        elif neg:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        matches = len(issues) + len(highs)
        words = len(t.split())
        confidence = 0.4 + 0.25 * min(matches, 2) + 0.05 * min(pos + neg - len(issues), 2)
        if words < 3:
            confidence -= 0.15
        if re.search(VAGUE, t):
            confidence -= 0.25
        if matches == 0:
            confidence = min(confidence, 0.4)
        return Extraction(sentiment, issues, highs, round(max(0.05, min(confidence, 0.95)), 2), "rules")


# --------------------------------------------------------------- ollama backend

SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "mixed", "negative", "neutral"]},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "tag": {"type": "string", "enum": TAGS}, "detail": {"type": "string"}},
            "required": ["tag", "detail"]}},
        "highlights": {"type": "array", "items": {"type": "object", "properties": {
            "tag": {"type": "string", "enum": TAGS}, "detail": {"type": "string"}},
            "required": ["tag", "detail"]}},
        "confidence": {"type": "number"},
    },
    "required": ["sentiment", "issues", "highlights", "confidence"],
}

SYSTEM_PROMPT = f"""You analyse visitor feedback about a small family coffee farm.
Return ONLY JSON matching the schema.
- sentiment: the visitor's overall feeling (positive, mixed, negative, neutral).
- issues: concrete problems the visitor experienced. Use only these tags: {", ".join(TAGS)}.
- highlights: things the visitor clearly enjoyed, same tags.
- detail: at most 8 words, in English, in the visitor's own meaning.
- confidence: 0-1, how sure you are of your reading. If the text is vague, ambiguous or
  you would have to guess, give a LOW confidence (below 0.5) and do not invent issues.
Never add problems or praise the visitor did not express."""


class OllamaExtractor:
    def __init__(self, url: str, model: str):
        self.url, self.model = url.rstrip("/"), model
        self._fallback = RulesExtractor()

    def extract(self, text: str) -> Extraction:
        try:
            r = requests.post(f"{self.url}/api/chat", timeout=60, json={
                "model": self.model,
                "stream": False,
                "format": SCHEMA,
                "options": {"temperature": 0},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": text}],
            })
            r.raise_for_status()
            data = json.loads(r.json()["message"]["content"])
            clean = lambda xs: [Item(x["tag"], x.get("detail", "")[:60]) for x in xs if x.get("tag") in TAG_TO_CATEGORY]
            return Extraction(
                data.get("sentiment", "neutral"), clean(data.get("issues", [])), clean(data.get("highlights", [])),
                round(float(max(0.0, min(1.0, data.get("confidence", 0.0)))), 2), f"ollama:{self.model}")
        except Exception:
            # Model unavailable or bad JSON: fall back, and never claim high confidence.
            ex = self._fallback.extract(text)
            ex.confidence = min(ex.confidence, 0.55)
            ex.backend = "rules(fallback)"
            return ex


def extractor_from(settings: Settings):
    if settings.extractor == "ollama":
        return OllamaExtractor(settings.ollama_url, settings.ollama_model)
    return RulesExtractor()
