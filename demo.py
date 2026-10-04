"""Run four sample visitors through Noor AI and print what Noor receives, in Bahasa Indonesia.

    python demo.py            # lite mode: no model downloads
    NOOR_TRANSLATOR=nllb NOOR_EXTRACTOR=ollama python demo.py   # full small-AI mode
"""
from noor_ai import NoorAI, Submission

VISITORS = [
    ("German couple, lost on the way, wanted to buy coffee",
     Submission(guests=2,
                answers={"Q023": "2 - Poor", "Q032": "5 - Excellent", "Q039": "5 - Excellent", "Q091": "5 - Excellent",
                         "Q054": "No, but I wanted to", "Q092": 9},
                comments=["Die Farm war fantastisch, aber der Eingang war schwer zu finden.",
                          "Wir hätten gern Kaffee gekauft, aber es gab keinen zu kaufen."])),
    ("French solo traveller, loved tasting, no toilet",
     Submission(guests=1,
                answers={"Q023": "4 - Good", "Q061": "2 - Poor", "Q091": "4 - Good", "Q092": 8},
                comments=["La dégustation de café était le meilleur moment !",
                          "Il n'y avait pas de toilettes et pas d'ombre."])),
    ("English visitor, vague answer",
     Submission(guests=3,
                answers={"Q091": "3 - Okay", "Q092": 6},
                comments=["It was okay, but that thing near the house..."])),
    ("Domestic visitor, slippery path",
     Submission(guests=4,
                answers={"Q083": "Not sure", "Q091": "4 - Good", "Q092": 7},
                comments=["Jalannya licin setelah hujan."])),
]


def main():
    noor = NoorAI()
    print(f"Backends: translator={noor.s.translator}, extractor={noor.s.extractor}, sms={noor.s.sms_backend}, "
          f"Noor reads: {noor.s.noor_lang}")
    for title, sub in VISITORS:
        print("\n" + "=" * 72 + f"\n{title}")
        r = noor.process(sub)
        for c in r.comments:
            flag = f"  FLAGGED ({c.flag_reason})" if c.flagged else ""
            print(f"  [{c.lang} {c.lang_confidence:.2f}] {c.original}")
            print(f"     -> EN: {c.english}")
            print(f"     -> ID: {c.indonesian}")
            print(f"     -> {c.extraction['sentiment']}, issues={[i['tag'] for i in c.extraction['issues']]}, "
                  f"highlights={[h['tag'] for h in c.extraction['highlights']]}, conf={c.extraction['confidence']}{flag}")
        print(f"  Next questions Noor AI would ask:")
        for q in r.follow_ups[:4]:
            print(f"     {q['id']}: {q['question']}")
        print(f"  SMS: {r.sms_encoding}, {len(r.sms)} chars, {r.sms_segments} segment(s)")
        print("  Noor's full report (Bahasa Indonesia):")
        print("    " + r.report_id.replace("\n", "\n    "))
    print("\n" + "=" * 72 + "\nWeekly digest SMS:\n" + noor.digest())


if __name__ == "__main__":
    main()
