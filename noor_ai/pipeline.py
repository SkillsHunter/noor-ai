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
from dataclasses import dataclass, field
from datetime import date
from itertools import count

from .config import Settings
from .extract import Extraction, extractor_from
from .i18n import answer_to_indonesian, question_id_text
from .langid import detect
from .questions import QuestionBank, score_of
from .sms_compose import TEMPLATES, compose, sms_info
from .sms_gateway import gateway_from
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


class NoorAI:
    def __init__(self, settings: Settings | None = None, gateway=None):
        self.s = settings or Settings()
        self.bank = QuestionBank(self.s.question_bank)
        self.translator = translator_from(self.s)
        self.extractor = extractor_from(self.s)
        self.gateway = gateway or gateway_from(self.s)
        self._counter = count(1)
        self.history: list[Result] = []

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
    def analyse_comment(self, text: str, qid: str = "") -> CommentResult:
        d = detect(text)
        tr = self.translator.translate(text, d.lang, "en") if d.lang not in ("en", "und") else None
        english = tr.text if tr else text
        ok = tr.ok if tr else d.lang != "und"
        ex: Extraction = self.extractor.extract(english) if ok else Extraction("neutral", confidence=0.0, backend="skipped")
        indonesian = self.to_noor(text, d.lang, english if ok else None) if d.lang != "und" else None

        reason = ""
        if d.confidence < 0.5:
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

    def process(self, sub: Submission, send: bool = True) -> Result:
        comments = [self.analyse_comment(t, qid) for qid, t in self._free_text(sub)]
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
                     text, enc, segs)
        self.history.append(res)          # keep the feedback even if the SMS fails
        if send:
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

    # -- weekly digest -------------------------------------------------------
    def digest(self, results: list[Result] | None = None) -> str:
        results = results if results is not None else self.history
        issues = Counter(t for r in results for t in r.issues)
        highs = Counter(t for r in results for t in r.highlights)
        flagged = sum(c.flagged for r in results for c in r.comments)
        scores = [r.overall for r in results if r.overall is not None]
        t = TEMPLATES.get(self.s.noor_lang, TEMPLATES["en"])
        label = lambda x: t["tags"].get(x, x)
        avg = f"{sum(scores)/len(scores):.1f}" if scores else "?"
        lines = [f"NOOR AI ringkasan: {len(results)} tamu, rata-rata {avg}/5"]
        if issues:
            lines.append("Masalah utama: " + ", ".join(f"{label(k)} ({v})" for k, v in issues.most_common(2)))
        if highs:
            lines.append("Paling disukai: " + label(highs.most_common(1)[0][0]))
        if flagged:
            lines.append(f"{flagged} jawaban perlu dicek")
        lines.append("Balas 1=dibaca")
        return "\n".join(lines)
