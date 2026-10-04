"""Step 4: pick the next relevant questions instead of asking all 100.

Uses the question bank (data/noor_feedback_question_bank.jsonl):
* every visitor gets the `core` questions;
* `follow_up` questions are unlocked by (a) a low core rating in their category,
  (b) an issue the extractor found in the visitor's free text, or (c) a happy
  visitor (>= 4 overall) for the review/testimonial questions;
* at most `max_follow_ups` are asked, highest score first.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .extract import TAG_TO_CATEGORY

OVERALL_QID_HINT = "Overall, how satisfied"


@dataclass
class Question:
    id: str
    category: str
    question: str
    response_type: str
    options: list
    tier: str
    trigger: str
    improvement_purpose: str


def score_of(value):
    """'4 - Good' -> 4, 4 -> 4, 'Yes' -> None."""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"\s*(\d+(\.\d+)?)", str(value or ""))
    return float(m.group(1)) if m else None


class QuestionBank:
    def __init__(self, path: Path):
        self.questions = [Question(**json.loads(line)) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.by_id = {q.id: q for q in self.questions}
        self.core = [q for q in self.questions if q.tier == "core"]
        # The core rating question that represents each category.
        self.core_rating = {}
        for q in self.core:
            if q.response_type == "rating_1_5":
                self.core_rating.setdefault(q.category, q.id)
        self.overall_id = next((q.id for q in self.core if q.question.startswith(OVERALL_QID_HINT)), None)

    def core_questions(self):
        return list(self.core)

    def overall_score(self, answers: dict):
        return score_of(answers.get(self.overall_id)) if self.overall_id else None

    def plan_follow_ups(self, answers: dict, issue_tags=(), max_n: int = 6):
        """Return the follow-up questions worth asking, best first."""
        weak = {}  # category -> core rating
        for cat, qid in self.core_rating.items():
            s = score_of(answers.get(qid))
            if s is not None and s <= 3:
                weak[cat] = s
        issue_cats = {TAG_TO_CATEGORY[t] for t in issue_tags if t in TAG_TO_CATEGORY}
        overall = self.overall_score(answers)

        scored = []
        for q in self.questions:
            if q.tier != "follow_up" or q.id in answers:
                continue
            trig = q.trigger.lower()
            score = 0.0
            m = re.search(r"rating <= (\d)", trig)
            if q.category in weak:
                score += 2 + (3 - weak[q.category])          # lower rating, higher priority
                if m and weak[q.category] <= int(m.group(1)):
                    score += 2                                # its own trigger fires
            if q.category in issue_cats:
                score += 3
                if q.response_type in ("single_choice", "multiple_choice"):
                    score += 0.5                              # quick to answer
            if ">= 4" in trig and overall is not None and overall >= 4:
                score += 1.5
            if score > 0:
                scored.append((score, q))
        scored.sort(key=lambda x: (-x[0], x[1].id))
        return [q for _, q in scored[:max_n]]
