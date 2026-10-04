"""The Noor AI pipeline: visitor feedback in any language, Bahasa Indonesia out.

For every submission:
    detect language -> translate to English (pivot for analysis) -> extract
    -> flag if unsure -> choose follow-up questions
    -> translate EVERY answer and comment into Bahasa Indonesia (Noor's full report)
    -> compose a one-segment summary SMS in Bahasa Indonesia -> send
Noor can reply "3" to receive the full Indonesian text by SMS.

Noor stays the decision-maker: the SMS only reports; unclear answers are
flagged and still shown to her in translation, never interpreted.
"""
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from itertools import count

from .config import Settings
from .extract import Extraction, extractor_from
from .i18n import answer_to_indonesian, question_id_text
from .langid import detect
from .questions import QuestionBank, score_of
from .sms_compose import TEMPLATES, compose, sms_info
from .sms_gateway import gateway_from
from .summary import summarise
from .translate import translator_from

# Core rating category -> issue tag, so a low score counts even without a comment.
LOW_RATING_TAG = {
    "Getting there and entrance": "signage", "Facilities and comfort": "facilities",
    "Welcome and hospitality": "hospitality", "Language and communication": "language",
    "Tour content and activities": "tour",
}
LANG_NAMES_ID = TEMPLATES["id"]["langs"]


@dataclass
class Submission:
    answers: dict                 # question id -> answer (English option values, numbers, or free text)
    comments: list = field(default_factory=list)   # extra free-text comments, any language
    guests: int | None = None
    visitor_id: str = ""
    lang: str = ""                # language the visitor chose on the form (optional)


@dataclass
class CommentResult:
    original: str
    lang: str
    lang_confidence: float
    english: str
    indonesian: str | None        # what Noor reads
    translated_ok: bool
    extraction: dict
    flagged: bool
    flag_reason: str = ""
    qid: str = ""                 # the question it answered, if any


@dataclass
class Result:
    feedback_no: int
    visitor_lang: str
    overall: float | None
    sentiment: str
    issues: list
    highlights: list
    comments: list = field(default_factory=list)
    answers_id: list = field(default_factory=list)   # [{qid, pertanyaan, jawaban}] in Indonesian
    report_id: str = ""                              # full report in Bahasa Indonesia
    follow_ups: list = field(default_factory=list)
    sms: str = ""
    sms_encoding: str = ""
    sms_segments: int = 0
    delivery: dict = field(default_factory=dict)
    received: str = ""                               # ISO date, for weekly/monthly summaries


class NoorAI:
    def __init__(self, settings: Settings | None = None, gateway=None):
        self.s = settings or Settings()
        self.bank = QuestionBank(self.s.question_bank)
        self.translator = translator_from(self.s)
        self.extractor = extractor_from(self.s)
        self.gateway = gateway or gateway_from(self.s)
        self._counter = count(1)
        self.history: list[Result] = []
        self.decisions: list[dict] = []   # Noor's answers to summary suggestions
        self.pending = None               # suggestion awaiting her 1=ya / 2=nanti

    # -- translation into Noor's language ------------------------------------
    def to_noor(self, text: str, src: str, english: str | None = None) -> str | None:
        target = self.s.noor_lang
        if src == target:
            return text
        tr = self.translator.translate(text, src, target)
        if tr.ok:
            return tr.text
        if english and src != "en":          # second try via the English pivot
            tr = self.translator.translate(english, "en", target)
            if tr.ok:
                return tr.text
        return None

    # -- per comment ---------------------------------------------------------
    def analyse_comment(self, text: str, qid: str = "", hint: str = "") -> CommentResult:
        """`hint` is the language the visitor picked in the chat. If detection agrees with it,
        a lower detection confidence is accepted (short sentences score low on their own)."""
        d = detect(text)
        lang_sure = d.confidence >= 0.5 or (bool(hint) and d.lang == hint)
        tr = self.translator.translate(text, d.lang, "en") if d.lang not in ("en", "und") else None
        english = tr.text if tr else text
        ok = tr.ok if tr else d.lang != "und"
        ex: Extraction = self.extractor.extract(english) if ok else Extraction("neutral", confidence=0.0, backend="skipped")
        indonesian = self.to_noor(text, d.lang, english if ok else None) if d.lang != "und" else None

        reason = ""
        if not lang_sure:
            reason = "language unclear"
        elif not ok or indonesian is None:
            reason = "could not translate"
        elif ex.confidence < self.s.confidence_threshold:
            reason = "meaning unclear"
        return CommentResult(text, d.lang, d.confidence, english, indonesian, ok, ex.to_dict(),
                             bool(reason), reason, qid)

    # -- per submission ------------------------------------------------------
    def _free_text(self, sub: Submission):
        """Open-text answers in the form plus extra comments, with their question ids."""
        items = []
        for qid, val in sub.answers.items():
            q = self.bank.by_id.get(qid)
            if q and q.response_type == "open_text" and isinstance(val, str) and val.strip():
                items.append((qid, val))
        items += [("", c) for c in sub.comments if c and c.strip()]
        return items

    def _answers_in_indonesian(self, sub: Submission, comments: list[CommentResult]):
        by_q = {c.qid: c for c in comments if c.qid}
        rows = []
        for qid in sorted(sub.answers, key=lambda x: (len(x), x)):
            q = self.bank.by_id.get(qid)
            if not q:
                continue
            if q.response_type == "open_text":
                c = by_q.get(qid)
                ans = (c.indonesian or f"[belum diterjemahkan] {c.original}") if c else str(sub.answers[qid])
            else:
                ans = answer_to_indonesian(sub.answers[qid])
            rows.append({"qid": qid, "pertanyaan": question_id_text(qid, q.question), "jawaban": ans})
        return rows

    def _report(self, n, sub, visitor_lang, rows, comments):
        lines = [f"MASUKAN PENGUNJUNG #{n}",
                 f"Tanggal: {date.today().isoformat()} | Tamu: {sub.guests or '?'} | "
                 f"Bahasa pengunjung: {LANG_NAMES_ID.get(visitor_lang, visitor_lang)}", ""]
        for r in rows:
            lines.append(f"- {r['pertanyaan']}\n  {r['jawaban']}")
        extra = [c for c in comments if not c.qid]
        if extra:
            lines += ["", "Komentar pengunjung:"]
            for c in extra:
                lines.append(f"- {c.indonesian or '[belum diterjemahkan] ' + c.original}")
        flagged = [c for c in comments if c.flagged]
        if flagged:
            lines += ["", "Perlu dicek (AI tidak yakin):"]
            for c in flagged:
                lines.append(f"- \"{c.original}\" ({LANG_NAMES_ID.get(c.lang, c.lang)})")
        return "\n".join(lines)

    def process(self, sub: Submission, send: bool = True, today: date | None = None) -> Result:
        comments = [self.analyse_comment(t, qid, sub.lang) for qid, t in self._free_text(sub)]
        usable = [c for c in comments if not c.flagged]

        issues = Counter(i["tag"] for c in usable for i in c.extraction["issues"])
        highs = Counter(h["tag"] for c in usable for h in c.extraction["highlights"])
        for cat, qid in self.bank.core_rating.items():
            s = score_of(sub.answers.get(qid))
            tag = LOW_RATING_TAG.get(cat)
            if s is not None and s <= 2 and tag and tag not in issues:
                issues[tag] += 1

        sentiments = Counter(c.extraction["sentiment"] for c in usable)
        sentiment = sentiments.most_common(1)[0][0] if sentiments else "unknown"
        detected = Counter(c.lang for c in comments if c.lang != "und").most_common(1)
        visitor_lang = detected[0][0] if detected else (sub.lang or "und")
        overall = self.bank.overall_score(sub.answers)

        follow_ups = self.bank.plan_follow_ups(sub.answers, list(issues), self.s.max_follow_ups)
        n = next(self._counter)
        rows = self._answers_in_indonesian(sub, comments)
        report = self._report(n, sub, visitor_lang, rows, comments)
        text = compose(n, sub.guests, visitor_lang, overall,
                       [t for t, _ in issues.most_common()], [t for t, _ in highs.most_common()],
                       sum(c.flagged for c in comments), self.s.noor_lang)
        enc, _, segs = sms_info(text)
        res = Result(n, visitor_lang, overall, sentiment, [t for t, _ in issues.most_common()],
                     [t for t, _ in highs.most_common()], comments, rows, report,
                     [{"id": q.id, "question": q.question, "options": q.options} for q in follow_ups],
                     text, enc, segs, received=(today or date.today()).isoformat())
        self.history.append(res)          # keep the feedback even if the SMS fails
        if send:
            self.pending = None           # her next 1/2 answers this SMS, not an older suggestion
            try:
                res.delivery = self.gateway.send(self.s.noor_phone, text)
            except Exception as e:        # store-and-forward: Noor still sees it in the inbox
                res.delivery = {"status": "failed", "error": e.__class__.__name__}
        return res

    # -- Noor asks for the full text by replying "3" ---------------------------
    def full_text_sms(self, feedback_no: int | None = None) -> str:
        if not self.history:
            return "Belum ada masukan."
        if feedback_no is None:
            r = self.history[-1]
        else:
            r = next((h for h in self.history if h.feedback_no == feedback_no), None)
            if r is None:
                return f"Masukan #{feedback_no} tidak ditemukan."
        parts = [f"#{r.feedback_no} teks lengkap:"]
        for c in r.comments:
            parts.append("- " + (c.indonesian or f"(asli) {c.original}"))
        if len(parts) == 1:
            parts.append("Tidak ada komentar tertulis.")
        return "\n".join(parts)

    # -- weekly / monthly summaries ----------------------------------------------
    def summary(self, period: str = "week", today: date | None = None):
        return summarise(self.history, period, today, self.decisions)

    def send_summary(self, period: str = "week", today: date | None = None) -> dict:
        s = self.summary(period, today)
        self.pending = {"period": period, **asdict(s.suggestions[0])} if s.suggestions else None
        try:
            delivery = self.gateway.send(self.s.noor_phone, s.sms)
        except Exception as e:
            delivery = {"status": "failed", "error": e.__class__.__name__}
        return {**asdict(s), "delivery": delivery}

    def decide(self, choice: str, today: date | None = None) -> dict | None:
        """Noor replied 1 (yes) or 2 (later) to the pending suggestion."""
        if not self.pending:
            return None
        d = {**self.pending, "decision": choice, "date": (today or date.today()).isoformat()}
        self.decisions.append(d)
        self.pending = None
        return d

    def digest(self) -> str:
        """Kept for older callers: the weekly summary SMS."""
        return self.summary("week").sms

    # -- demo data -------------------------------------------------------------
    def seed_demo(self, today: date | None = None) -> int:
        """SYNTHETIC visits over the last 60 days, so the summaries have something to show.
        Uses only phrasebook sentences, so it also works in lite mode.

        Last month: signage complaints; Noor said yes to a sign 30 days ago.
        This month: fewer signage complaints, many visitors want to buy coffee.
        """
        today = today or date.today()
        visits = [  # (days ago, overall rating, comments)
            (55, "3 - Okay", ["There was no sign on the road."]),
            (50, "3 - Okay", ["Kein Schild an der Straße. Wir haben uns verfahren."]),
            (44, "4 - Good", ["Die Farm war fantastisch, aber der Eingang war schwer zu finden."]),
            (38, "4 - Good", ["The farm was amazing, but the entrance was difficult to find."]),
            (34, "5 - Excellent", ["The coffee tasting was the best part!"]),
            (26, "5 - Excellent", ["La dégustation de café était le meilleur moment !"]),
            (20, "4 - Good", ["Wir hätten gern Kaffee gekauft, aber es gab keinen zu kaufen."]),
            (12, "5 - Excellent", ["The coffee tasting was the best part!",
                                   "Wir hätten gern Kaffee gekauft, aber es gab keinen zu kaufen."]),
            (6, "4 - Good", ["Il n'y avait pas de toilettes et pas d'ombre."]),
            (5, "4 - Good", ["Wir hätten gern Kaffee gekauft, aber es gab keinen zu kaufen."]),
            (4, "5 - Excellent", ["El café estaba delicioso, pero el camino era resbaladizo."]),
            (2, "4 - Good", ["Wir hätten gern Kaffee gekauft, aber es gab keinen zu kaufen."]),
        ]
        with_overall = self.bank.overall_id
        for ago, rating, comments in visits:
            answers = {with_overall: rating} if with_overall else {}
            lang = detect(comments[0]).lang
            self.process(Submission(answers=answers, comments=comments, guests=2, visitor_id="demo", lang=lang),
                         send=False, today=today - timedelta(days=ago))
        if not any(d["tag"] == "signage" for d in self.decisions):
            self.decisions.append({"period": "month", "kind": "fix", "tag": "signage", "count": 4, "visitors": 5,
                                   "text_id": "Pasang papan petunjuk di jalan utama?",
                                   "text_en": "Put up a sign at the main road?", "decision": "yes",
                                   "date": (today - timedelta(days=30)).isoformat()})
        return len(visits)
