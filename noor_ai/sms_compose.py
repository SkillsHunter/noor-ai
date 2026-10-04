"""Step 5: turn structured feedback into one short SMS in Noor's language.

The summary is built from templates, not free generation, so it is short,
predictable and never invents content. It is kept to ONE SMS segment where
possible (160 GSM-7 characters, or 70 if any character needs Unicode), dropping
the least important lines first.
"""
import math

GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = set("^{}\\[~]|€")  # count as two characters


def sms_info(text: str):
    """Return (encoding, length_in_units, segments)."""
    if all(c in GSM7 or c in GSM7_EXT for c in text):
        units = sum(2 if c in GSM7_EXT else 1 for c in text)
        single, multi = 160, 153
        enc = "GSM-7"
    else:
        units = len(text)
        single, multi = 70, 67
        enc = "UCS-2"
    segments = 1 if units <= single else math.ceil(units / multi)
    return enc, units, segments


# Templates per reading language. Add a language by adding a block here.
TEMPLATES = {
    "id": {
        "head": "NOOR AI #{n}: {guests} tamu ({lang}). Nilai {overall}/5",
        "issue": "Masalah: {x}",
        "high": "Disukai: {x}",
        "flag": "{k} jawaban tidak jelas, cek aslinya",
        "foot": "Balas 1=dibaca 2=telepon 3=teks lengkap",
        "unknown_rating": "?",
        "tags": {
            "signage": "petunjuk jalan/papan nama", "access_road": "jalan ke kebun", "booking": "cara pesan",
            "reply_time": "balasan lambat", "facilities": "toilet/teduh/air", "price": "harga",
            "payment": "cara bayar", "language": "bahasa", "safety": "keamanan jalan setapak",
            "accessibility": "akses", "tour": "tur", "coffee": "kopi", "coffee_sales": "ingin beli kopi",
            "food": "makanan", "hospitality": "keramahan", "scenery": "pemandangan",
        },
        "langs": {"en": "Inggris", "de": "Jerman", "fr": "Prancis", "es": "Spanyol", "nl": "Belanda",
                  "it": "Italia", "pt": "Portugis", "ja": "Jepang", "ko": "Korea", "zh": "Tiongkok",
                  "id": "Indonesia", "ms": "Melayu", "sw": "Swahili", "und": "?"},
    },
    "en": {
        "head": "NOOR AI #{n}: {guests} guest(s) ({lang}). Rated {overall}/5",
        "issue": "Problem: {x}",
        "high": "Liked: {x}",
        "flag": "{k} unclear answer(s), check original",
        "foot": "Reply 1=seen 2=call 3=full text",
        "unknown_rating": "?",
        "tags": {
            "signage": "road sign/directions", "access_road": "road to farm", "booking": "booking",
            "reply_time": "slow replies", "facilities": "toilet/shade/water", "price": "price",
            "payment": "payment", "language": "language", "safety": "path safety",
            "accessibility": "access", "tour": "tour", "coffee": "coffee", "coffee_sales": "wanted to buy coffee",
            "food": "food", "hospitality": "hospitality", "scenery": "scenery",
        },
        "langs": {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "nl": "Dutch",
                  "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
                  "id": "Indonesian", "ms": "Malay", "sw": "Swahili", "und": "?"},
    },
}


def compose(n, guests, visitor_lang, overall, issue_tags, highlight_tags, flagged, noor_lang="id", max_segments=1):
    t = TEMPLATES.get(noor_lang, TEMPLATES["en"])
    tag = lambda x: t["tags"].get(x, x)
    rating = t["unknown_rating"] if overall is None else f"{overall:g}"
    lines = [t["head"].format(n=n, guests=guests or "?", lang=t["langs"].get(visitor_lang, visitor_lang), overall=rating)]
    optional = []  # (priority, line): lower priority is dropped first
    if issue_tags:
        lines.append(t["issue"].format(x=", ".join(tag(x) for x in issue_tags[:2])))
    if flagged:
        optional.append((2, t["flag"].format(k=flagged)))
    if highlight_tags:
        optional.append((1, t["high"].format(x=", ".join(tag(x) for x in highlight_tags[:2]))))
    foot = t["foot"]

    def build(opts):
        return "\n".join(lines + [l for _, l in sorted(opts, key=lambda x: -x[0])] + [foot])

    text = build(optional)
    while sms_info(text)[2] > max_segments and optional:
        optional.sort(key=lambda x: x[0])
        optional.pop(0)
        text = build(optional)
    if sms_info(text)[2] > max_segments and len(issue_tags) > 1:
        lines[1] = t["issue"].format(x=tag(issue_tags[0]))
        text = build(optional)
    return text
