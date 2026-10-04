"""Step 7: weekly and monthly summaries, with suggestions Noor can accept or postpone.

The per-visit SMS tells Noor what ONE visitor said. The summaries read across ALL
visitors in a period and turn repeated feedback into one concrete suggestion:

    NOOR AI minggu ini: 4 tamu, nilai 4.3/5
    Masalah: petunjuk jalan (3/4)
    Disukai: kopi (3/4)
    Saran: Pasang papan petunjuk di jalan utama?
    Balas 1=ya 2=nanti

Guardrails
* Suggestions come from a FIXED list (below), never free generation, so they cannot
  invent anything. Every suggestion shows its evidence ("3 of 4 visitors").
* Fewer than MIN_VISITORS in the period: no suggestion, "not enough data" instead.
* Noor decides. Her 1 (yes) or 2 (later) is recorded, and the next monthly summary
  reports whether the complaint went down after she acted on it.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from .sms_compose import TEMPLATES, sms_info

PERIOD_DAYS = {"week": 7, "month": 30}
MIN_VISITORS = 3          # below this, no suggestions: too little evidence
ISSUE_SHARE = 0.25        # an issue needs >= 25% of visitors (and at least 2) to become a suggestion
HIGHLIGHT_SHARE = 0.5     # a highlight needs >= 50% of visitors (and at least 2)

# Fixed list of suggestions, hand-written in Bahasa Indonesia (English for the team).
FIX = {
    "signage": ("Pasang papan petunjuk di jalan utama?", "Put up a sign at the main road?"),
    "access_road": ("Kirim peta/petunjuk jalan ke tamu sebelum datang?", "Send visitors a map before they come?"),
    "booking": ("Buat cara pesan lewat WhatsApp?", "Offer booking by WhatsApp?"),
    "reply_time": ("Balas pesan tamu dalam 1 hari?", "Reply to visitors within a day?"),
    "facilities": ("Siapkan toilet bersih, tempat teduh dan air minum?", "Prepare a clean toilet, shade and water?"),
    "price": ("Jelaskan harga tur sebelum tamu datang?", "Explain the tour price before visitors come?"),
    "payment": ("Terima pembayaran QRIS/non-tunai?", "Accept QRIS / cashless payment?"),
    "language": ("Siapkan kartu penjelasan tur dalam bahasa Inggris?", "Prepare a tour card in English?"),
    "safety": ("Perbaiki jalan setapak yang licin?", "Fix the slippery path?"),
    "accessibility": ("Buat jalur yang mudah untuk lansia/kursi roda?", "Make an easy path for elderly/wheelchairs?"),
    "tour": ("Atur ulang lama tur dan kegiatan anak?", "Adjust tour length and add kids' activities?"),
    "coffee_sales": ("Jual kopi bubuk/biji di kebun?", "Sell ground coffee/beans at the farm?"),
    "food": ("Sediakan makanan ringan untuk tamu?", "Offer snacks to visitors?"),
    "hospitality": ("Bicarakan cara menyambut tamu dengan pemandu?", "Talk with the guide about welcoming visitors?"),
}
BUILD = {
    "coffee": ("Jadikan mencicipi kopi paket tur sendiri?", "Make coffee tasting its own tour package?"),
    "scenery": ("Buat titik foto pemandangan dan minta tamu berbagi foto?", "Add a photo spot and ask visitors to share?"),
    "hospitality": ("Minta tamu yang puas menulis ulasan online?", "Ask happy visitors for an online review?"),
    "tour": ("Minta tamu yang puas menulis ulasan online?", "Ask happy visitors for an online review?"),
    "food": ("Tawarkan makan siang sebagai tambahan berbayar?", "Offer lunch as a paid extra?"),
}


@dataclass
class Suggestion:
    kind: str            # "fix" (a repeated problem) or "build" (something most visitors loved)
    tag: str
    count: int           # visitors who mentioned it
    visitors: int        # visitors in the period
    text_id: str
    text_en: str


@dataclass
class Summary:
    period: str
    start: str
    end: str
    visitors: int
    average: float | None
    prev_visitors: int
    prev_average: float | None
    issues: dict
    prev_issues: dict
    highlights: dict
    flagged: int
    enough_data: bool
    suggestions: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)   # what happened after Noor's earlier "yes"
    sms: str = ""
    sms_segments: int = 0


def _window(results, start, end):
    return [r for r in results if start < date.fromisoformat(r.received) <= end]


def _avg(rs):
    xs = [r.overall for r in rs if r.overall is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def summarise(results, period="week", today=None, decisions=()):
    days = PERIOD_DAYS[period]
    today = today or date.today()
    start, prev_start = today - timedelta(days=days), today - timedelta(days=2 * days)
    cur, prev = _window(results, start, today), _window(results, prev_start, start)
    n = len(cur)

    issues = Counter(t for r in cur for t in set(r.issues))
    prev_issues = Counter(t for r in prev for t in set(r.issues))
    highs = Counter(t for r in cur for t in set(r.highlights))
    enough = n >= MIN_VISITORS

    suggestions = []
    if enough:
        for tag, k in issues.most_common():
            if tag in FIX and k >= 2 and k / n >= ISSUE_SHARE:
                suggestions.append(Suggestion("fix", tag, k, n, *FIX[tag]))
        for tag, k in highs.most_common():
            if tag in BUILD and k >= 2 and k / n >= HIGHLIGHT_SHARE:
                suggestions.append(Suggestion("build", tag, k, n, *BUILD[tag]))

    # Close the loop: for suggestions Noor said yes to before this period, did the complaint drop?
    outcomes = []
    for d in decisions if period == "month" else ():
        if (d["decision"] == "yes" and d["kind"] == "fix" and date.fromisoformat(d["date"]) <= start
                and prev_issues.get(d["tag"], 0) > 0):
            outcomes.append({"tag": d["tag"], "decided": d["date"],
                             "before": prev_issues.get(d["tag"], 0), "after": issues.get(d["tag"], 0)})

    s = Summary(period, start.isoformat(), today.isoformat(), n, _avg(cur), len(prev), _avg(prev),
                dict(issues), dict(prev_issues), dict(highs), sum(c.flagged for r in cur for c in r.comments),
                enough, suggestions, outcomes)
    s.sms = compose_summary(s)
    s.sms_segments = sms_info(s.sms)[2]
    return s


def compose_summary(s: Summary) -> str:
    """SMS in Bahasa Indonesia. Weekly fits 2 SMS, monthly 3 (6-7 visitors a month, so this is cheap)."""
    label = lambda t: TEMPLATES["id"]["tags"].get(t, t)
    avg = "?" if s.average is None else f"{s.average:g}"
    if s.period == "week":
        lines = [f"NOOR AI minggu ini: {s.visitors} tamu, nilai {avg}/5"]
    else:
        pavg = "?" if s.prev_average is None else f"{s.prev_average:g}"
        lines = [f"NOOR AI bulan ini: {s.visitors} tamu (lalu {s.prev_visitors}), nilai {avg}/5 (lalu {pavg})"]
    if s.issues:
        top = sorted(s.issues.items(), key=lambda x: -x[1])[:2]
        if s.period == "week":
            lines.append("Masalah: " + ", ".join(f"{label(t)} ({k}/{s.visitors})" for t, k in top))
        else:
            lines.append("Masalah: " + ", ".join(f"{label(t)} {k} (lalu {s.prev_issues.get(t, 0)})" for t, k in top))
    if s.highlights:
        t, k = max(s.highlights.items(), key=lambda x: x[1])
        lines.append(f"Disukai: {label(t)} ({k}/{s.visitors})")
    for o in s.outcomes[:1]:
        trend = "membaik" if o["after"] < o["before"] else "belum membaik"
        lines.append(f"Hasil: {label(o['tag'])} {o['before']}->{o['after']} keluhan, {trend}")
    if s.flagged:
        lines.append(f"{s.flagged} jawaban perlu dicek")
    if not s.enough_data:
        lines.append(f"Saran: belum ada, data kurang (<{MIN_VISITORS} tamu)")
        lines.append("Balas 1=dibaca")
    elif s.suggestions:
        lines.append("Saran: " + s.suggestions[0].text_id)
        lines.append("Balas 1=ya 2=nanti")
    else:
        lines.append("Balas 1=dibaca")
    return "\n".join(lines)
