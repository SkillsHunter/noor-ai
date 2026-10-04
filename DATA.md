# Data, Small AI fit and Responsible AI

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

- **Human in the loop:** the AI only reports. Noor decides. Nothing is ever sent to a visitor automatically.
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
