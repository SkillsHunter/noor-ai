"""Measure how well Noor AI reads visitor comments, on a labelled test set.

    python eval.py                          # lite mode: keyword rules, demo phrasebook
    python eval.py --translator nllb --extractor ollama   # full small-AI mode
    python eval.py --out docs/eval-results.md

Test set: data/eval/comments.jsonl. SYNTHETIC: written by the team, labelled by hand,
before the rules were scored against it (the rules were not tuned on it afterwards).

What we measure
* Issue detection: precision / recall of issue tags, over comments the AI did NOT flag.
* Highlight detection: the same, for things visitors liked.
* Flag rate: share of comments handed to Noor as "not sure".
* Confident-wrong rate: NOT flagged, yet the issue tags are wrong (missed or invented).
  This is the number that matters for "flag, don't guess": it should be as low as possible.
* Vague caught: share of deliberately vague comments that were flagged.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path

from noor_ai import NoorAI, Settings, Submission
from noor_ai.sms_gateway import ConsoleGateway

TESTSET = Path(__file__).resolve().parent / "data" / "eval" / "comments.jsonl"


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r


def score(items, results):
    t = {"tp": 0, "fp": 0, "fn": 0, "htp": 0, "hfp": 0, "hfn": 0}
    flagged = confident_wrong = vague = vague_flagged = 0
    rows = []
    for it, c in zip(items, results):
        gold, pred = set(it["issues"]), {i["tag"] for i in c.extraction["issues"]}
        hgold, hpred = set(it["highlights"]), {h["tag"] for h in c.extraction["highlights"]}
        if it["vague"]:
            vague += 1
            vague_flagged += c.flagged
        if c.flagged:
            flagged += 1
            verdict = "flagged"
        else:
            t["tp"] += len(gold & pred); t["fp"] += len(pred - gold); t["fn"] += len(gold - pred)
            t["htp"] += len(hgold & hpred); t["hfp"] += len(hpred - hgold); t["hfn"] += len(hgold - hpred)
            ok = gold == pred
            confident_wrong += not ok
            verdict = "correct" if ok else "CONFIDENT-WRONG"
        rows.append((it["id"], it["lang"], verdict, c.flag_reason, sorted(gold), sorted(pred)))
    n = len(items)
    ip, ir = prf(t["tp"], t["fp"], t["fn"])
    hp, hr = prf(t["htp"], t["hfp"], t["hfn"])
    return {
        "n": n, "flagged": flagged, "confident_wrong": confident_wrong,
        "issue_precision": ip, "issue_recall": ir, "highlight_precision": hp, "highlight_recall": hr,
        "vague": vague, "vague_flagged": vague_flagged, "rows": rows,
    }


class _Analysed:
    """Extractor output alone, flagged by the same confidence threshold the pipeline uses."""
    def __init__(self, ex, threshold):
        self.extraction = ex.to_dict()
        self.flagged = ex.confidence < threshold
        self.flag_reason = "meaning unclear" if self.flagged else ""


def run_analysis_only(noor, items):
    return [_Analysed(noor.extractor.extract(it["text"]), noor.s.confidence_threshold) for it in items]


def run(translator, extractor):
    items = [json.loads(l) for l in TESTSET.read_text(encoding="utf-8").splitlines() if l.strip()]
    noor = NoorAI(Settings(translator=translator, extractor=extractor, sms_backend="console"), gateway=ConsoleGateway())
    with contextlib.redirect_stdout(io.StringIO()):
        results = [noor.analyse_comment(it["text"]) for it in items]
    return items, results, noor


def report(name, s):
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"
    return "\n".join([
        f"### {name} ({s['n']} comments)",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Issue precision (unflagged) | {s['issue_precision']:.2f} |",
        f"| Issue recall (unflagged) | {s['issue_recall']:.2f} |",
        f"| Highlight precision (unflagged) | {s['highlight_precision']:.2f} |",
        f"| Highlight recall (unflagged) | {s['highlight_recall']:.2f} |",
        f"| Flagged for Noor | {s['flagged']}/{s['n']} ({pct(s['flagged'], s['n'])}) |",
        f"| **Confident-wrong** | **{s['confident_wrong']}/{s['n']} ({pct(s['confident_wrong'], s['n'])})** |",
        f"| Vague comments caught | {s['vague_flagged']}/{s['vague']} |",
        "",
    ])


def detail(s):
    lines = ["| ID | Lang | Outcome | Flag reason | Gold issues | Predicted |", "|---|---|---|---|---|---|"]
    for i, lang, v, why, g, p in s["rows"]:
        lines.append(f"| {i} | {lang} | {v} | {why} | {', '.join(g) or '-'} | {', '.join(p) or '-'} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--translator", default="lite")
    ap.add_argument("--extractor", default="rules")
    ap.add_argument("--out")
    a = ap.parse_args()
    items, results, noor = run(a.translator, a.extractor)
    english = [it for it in items if it["lang"] == "en"]
    other = [(it, c) for it, c in zip(items, results) if it["lang"] != "en"]
    analysis = score(english, run_analysis_only(noor, english))
    mode = f"translator={a.translator}, extractor={a.extractor}"
    text = "\n".join([
        f"# Noor AI evaluation ({mode})",
        "",
        "Test set: `data/eval/comments.jsonl`, 42 **synthetic** comments written and labelled by the team.",
        "",
        "## 1. Analysis step only (30 English comments, no translation)",
        "",
        "How well the extractor reads a comment once it is in English.",
        "",
        report("Analysis", analysis),
        "## 2. End to end: what reaches Noor (all 42 comments)",
        "",
        "Detect language, translate, analyse, translate into Bahasa Indonesia, flag.",
        "",
        report("All comments", score(items, results)),
        report("Non-English comments", score(*zip(*other))),
        "## Per comment: analysis step",
        "",
        detail(analysis),
        "",
        "## Per comment: end to end",
        "",
        detail(score(items, results)),
        "",
    ])
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
