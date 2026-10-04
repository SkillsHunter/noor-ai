# Data, Small AI fit and Responsible AI

## The problem is real (cited evidence)

The brief's Ondera highlands are fictional. We use **Indonesia** as the stand-in country, because
Noor's national language in our build is Bahasa Indonesia.

| Evidence | Figure | Source (year) |
|---|---|---|
| Foreign visitors Noor's farm could serve | **13.9 million** international arrivals to Indonesia in 2024, up about 19% on 2023 | BPS Statistics Indonesia, reported by Jakarta Globe (2025) |
| Tourism is a jobs engine | **25.01 million** tourism workers in Indonesia in 2024, up 2.5% from 24.41 million in 2023 | Cabinet Secretariat of the Republic of Indonesia, setkab.go.id (2025) |
| Each visitor dollar matters | Every US$1 million of travel and tourism spending in Indonesia supports **about 200 jobs** (67 direct); **58%** of almost 7 million hotel and restaurant workers are women | World Bank Results brief "Visitors Welcome", citing WTTC (April 2025) |
| Design for a basic phone, not a smartphone | In low- and middle-income countries women are **8%** less likely than men to own a mobile phone and **14%** less likely to own a smartphone; in East Asia and Pacific 92% of women own a mobile but only 80% use mobile internet | GSMA Mobile Gender Gap Report 2025 (2024 data) |
| Small operators run on instinct | Informal operators lack the digital listing and skills to learn from customers; Noor gets 6-7 visitors a month by word of mouth | Challenge brief, Annex C (Jordan evidence) (2026) |

**What we do not have:** no figures for the specific highland district, and no survey of how many farm-tour
operators collect feedback today. These would be the first things to measure in a pilot.

## Evaluation: does it work?

`python eval.py` scores the pipeline on `data/eval/comments.jsonl`: 42 **synthetic** visitor comments
(30 English, 12 in German, French, Spanish, Indonesian, Dutch and Japanese), written and labelled by the team
before scoring. The rules were **not** tuned on this set afterwards. Full results:
[docs/eval-results-lite.md](docs/eval-results-lite.md).

Lite mode (keyword rules, demo phrasebook, no model downloads):

| Measure | Analysis step (30 English) | End to end (all 42) |
|---|---|---|
| Issue precision / recall on comments it did not flag | 1.00 / 1.00 | 1.00 / 1.00 |
| Flagged "not sure" for Noor | 13 / 30 (43%) | 35 / 42 (83%) |
| **Confident-wrong** (not flagged, but wrong) | **0** | **0** |
| Deliberately vague comments caught | 4 / 4 | 4 / 4 |

Full translation mode (real NLLB-200 600M on a laptop CPU, keyword rules for analysis), results in
[docs/eval-results-nllb.md](docs/eval-results-nllb.md):

| Measure | End to end (all 42) | Non-English (12) |
|---|---|---|
| Issue precision / recall on comments it did not flag | 1.00 / 0.95 | 1.00 / 0.86 |
| Flagged "not sure" for Noor | 15 / 42 (36%) | 2 / 12 (17%) |
| **Confident-wrong** | **1 (2%)** | **1 (8%)** |

Real translation cuts the flags from 83% to 36%. The **one confident-wrong case** (Dutch, M11): "the coffee
tasting was great, but the road was **really** bad". The rule expects "road was bad", so the complaint was
missed, and the praise in the same comment made the analysis confident. Lesson: confidence should be judged
per claim, not per comment. We did **not** patch the rule on the test set, to avoid gaming the score.

**Translation errors NLLB does not flag** (read by the team, not yet by a native speaker):
"farm" became *peternakan* (a livestock farm; should be *kebun*), "guide" became *panduan* (a guidebook;
should be *pemandu*), "coffee tasting" became *percobaan kopi* ("coffee experiment"; should be
*mencicipi kopi*). NLLB reports every translation as a success, so these reach Noor unflagged. This is why
fixed text is hand-written, why the original is always shown next to the translation, and why a native-speaker
check and a small farm-vocabulary glossary are the next steps.

**Reading the lite results honestly:** it never told Noor something wrong with confidence, but in lite mode it flags far
too much. End to end, most flags are "could not translate", because the lite phrasebook knows only the demo
sentences. Full mode (NLLB translation) is what removes those flags. The set is small and synthetic: real
visitor comments, checked by a native Indonesian reader, are the next step.

## Data we build with

| Dataset / model | Source | Licence | Size | Used for |
|---|---|---|---|---|
| NLLB-200 distilled 600M | Meta AI (Hugging Face `facebook/nllb-200-distilled-600M`) | CC-BY-NC 4.0 | ~2.5 GB (fp32); ~0.6 GB int8-quantized | Free-text translation, visitor language → Bahasa Indonesia |
| FLORES-200 | Meta AI | CC-BY-SA 4.0 | 1,012 sentences × 200 languages | Published benchmark for NLLB's `ind_Latn` quality (we cite, not re-measure) |
| lingua language detector | pemistahl/lingua-py | Apache 2.0 | ~100 MB of n-gram models, offline | Language identification, restricted to 13 candidates |
| Qwen2.5-3B (optional) via Ollama | Alibaba | Apache 2.0 | ~1.9 GB (Q4) | Structured extraction into a fixed tag list (JSON schema) |
| Question bank, 100 questions | **Synthetic**: written by Team Ezploria | Ours | 100 rows (`data/`) | Core + follow-up questions |
| Indonesian question/option text | **Hand-written** by the team | Ours | 157 lines | Noor's report; no machine translation for fixed text |
| Demo phrasebook + test comments | **Synthetic**, written by the team | Ours | ~12 sentences | Lite-mode demo and unit tests |

## What the data does NOT cover (known gaps)

- **Noor's local language.** We target Bahasa Indonesia (the national language). NLLB covers Javanese and
  Sundanese, but lingua cannot detect them, so such comments are **flagged for Noor, not guessed**.
- **Voice.** Text only; visitors with low literacy are not served yet (MMS speech models would be the next step).
- **Slang, mixed languages, very short replies.** Detection under ~3 words is unreliable; these are flagged.
- **Languages outside the 13 candidates** (e.g. Russian, Thai, Vietnamese) are detected with low confidence
  and flagged. Verified by probe: Russian/Thai → confidence 0.0, flagged.
- **No real visitor data yet.** The question bank and test comments are synthetic. NLLB output on real
  comments has not been checked by a native Indonesian reader.
- **Keyword rules (lite mode)** only recognise listed phrasings; anything else gets low confidence and is flagged.

## Small AI fit

- **Noor's device:** her existing basic phone. She receives one SMS (≤160 chars) and replies 1/2/3.
- **Visitor's device:** their own smartphone (a web chat, no app install).
- **Where the AI runs:** a small box at the farm (e.g. Raspberry Pi 5, 8 GB) serving the chat over local
  Wi-Fi. No internet is needed for translation or analysis. A GSM modem sends the SMS when there is signal
  (store-and-forward); if sending fails, the feedback is kept and shown in the inbox.
- **Model size:** NLLB int8 ~0.6 GB plus an optional ~1–2 GB extractor. Small enough to side-load on an SD card.
- **Trade-off:** the box is a new device for Noor. The hosted Render demo is for judging only.

## Responsible AI

- **Human in the loop:** the AI only reports and suggests. Noor decides (reply 1 = yes, 2 = later), and her
  decisions are logged. Nothing is ever sent to a visitor automatically.
- **Summaries cannot invent advice:** weekly and monthly suggestions come from a fixed, hand-written list, show
  their evidence ("4 of 7 visitors"), and need at least 3 visitors in the period. Otherwise the summary says
  "not enough data" instead of guessing.
- **Fail-safe ("not sure, ask a person"):** comments are flagged and shown word for word whenever the
  language is unclear (<0.5), translation fails, or extraction confidence is <0.6.
- **No hallucination in the SMS:** built from fixed templates and a fixed tag list; it cannot invent content.
- **Consent:** the chat tells visitors, before the first question, that answers go to Noor, translated and
  by SMS, and asks them not to write names or phone numbers.
- **Where data sits / who reads it:** on the farm box (in memory in this prototype). Only Noor's inbox,
  behind a password (`NOOR_ADMIN_PASSWORD`), and her phone show it. The SMS passes through the mobile operator.
- **Lost or shared phone:** the SMS has a summary only, with no visitor names or contact details.
- **Bias:** languages with less training data translate worse. That is why fixed text is hand-written and
  uncertain free text is flagged rather than trusted.

## Scaling: one model, many farms

Noor gets 6–7 visitors a month, so a model dedicated to one farm would sit idle almost all the time.
The plan is **one small box at the Ondera Coffee Cooperative** running the AI for every member farm:

- Each farm gets its own QR code, its own inbox and SMS to its own phone. The model is loaded once and shared.
- The cooperative is the trusted local institution that hosts and maintains it, so costs are shared.
- With the farms' consent, the cooperative can see anonymised patterns across farms
  (e.g. "visitors keep asking to buy coffee") for shared products or marketing.
- Any other cooperative or tourism association can reuse the same setup.

**Trade-offs:** each farm must see only its own feedback. Farms need a signal to reach the cooperative box
(Noor's SMS still works on a basic phone). If the box is down, every farm is affected, so feedback is
saved before any SMS is sent.

**Status:** the translation and analysis models are already shared across all requests. The app itself is
still single-farm (one phone, one inbox). Next step: add a `farm_id` to submissions, plus a QR link,
phone number, password and inbox per farm.
