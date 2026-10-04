# Noor AI: small-AI feedback pipeline

Visitors from any country give feedback in **their own language** through a short chat.
Noor receives **everything in Bahasa Indonesia**: a one-SMS summary on her basic phone, the full
translated text on request, and a complete report in her inbox. Noor AI picks the **next relevant
questions** from a 100-question bank and **flags** anything it is unsure about instead of guessing.
Every model is open and can run on your own server.

📄 **Overview deck:** [How Noor AI Works (PDF)](docs/How-Noor-AI-Works.pdf)

```
Visitor chat (any language)
  │  answers + comments
  ▼
1 Detect language (lingua) ─► 2 Translate to English pivot (NLLB-200) ─► 3 Extract (small LLM / rules)
                                                                           │
  4 Flag if unsure ◄──────────────────────────────────────────────────────┘
  5 Pick follow-up questions (question bank) ─► back to the visitor chat
  6 Translate EVERY answer and comment into Bahasa Indonesia
     • answer options: hand-written Indonesian (data/question_bank_id.json)
     • free text: NLLB-200, visitor's language → ind_Latn
  7 Summary SMS in Bahasa Indonesia (fits 1 SMS) ─► SMS gateway ─► Noor's phone
                                      Noor replies: 1 = dibaca, 2 = telepon, 3 = teks lengkap
```

## What's in the box

| Part | File | Notes |
|---|---|---|
| Visitor chat page | `noor_ai/static/index.html` | Mobile-first. English, Bahasa Indonesia, Deutsch, Français, Español built in |
| Noor's inbox page | `noor_ai/static/noor.html` | All feedback in Bahasa Indonesia, plus a simulated phone with reply keys 1/2/3 |
| Language detection | `noor_ai/langid.py` | lingua (offline) |
| Translation | `noor_ai/translate.py` | NLLB-200 distilled 600M, or the lite demo phrasebook |
| Extraction | `noor_ai/extract.py` | Small LLM via Ollama (JSON schema), or keyword rules |
| Question selection | `noor_ai/questions.py` | Core questions plus up to 6 targeted follow-ups |
| Indonesian for Noor | `noor_ai/i18n.py`, `data/question_bank_id.json` | All 100 questions and every option, hand-written |
| Visitor languages | `data/ui_i18n.json` | Chat text plus core questions in en/id/de/fr/es; others machine-translated |
| SMS | `noor_ai/sms_compose.py`, `noor_ai/sms_gateway.py` | One-segment summary; Twilio, Africa's Talking or console |
| API | `noor_ai/app.py` | FastAPI, docs at `/docs` |

## Try it (lite mode, no model downloads)

```bash
pip install lingua-language-detector requests fastapi uvicorn pydantic python-multipart pytest httpx
uvicorn noor_ai.app:app --reload
```

- Visitor chat: http://localhost:8000. Add `?demo=1` to see Noor's phone beside the chat.
- Noor's inbox (Bahasa Indonesia): http://localhost:8000/noor
- Command-line demo: `python demo.py`
- Tests: `pytest -q`

**Lite-mode limits:** the demo phrasebook only translates the sample sentences (for example
*"Die Farm war fantastisch, aber der Eingang war schwer zu finden."*). Other free text is shown
to Noor in the original with "[belum diterjemahkan]" and flagged. Follow-up questions appear in
English for de/fr/es visitors, with a note. Full mode removes both limits.

## Deploy (free, lite mode)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/SkillsHunter/noor-ai)

`render.yaml` sets up a free Render web service in lite mode. Noor's side (`/noor`, the feedback
API, the SMS webhook) is behind a login: user `noor`, with a password Render generates
(service → **Environment** → `NOOR_ADMIN_PASSWORD`). The visitor chat at `/` stays public.

Free-tier limits: the service sleeps after 15 minutes idle (first visit then takes ~1 minute), and
feedback is kept in memory, so it is lost on every restart or redeploy.

## Full small-AI mode

```bash
pip install -r requirements.txt            # adds transformers, torch (CPU), sentencepiece
# install Ollama from https://ollama.com, then:
ollama pull qwen2.5:3b                     # or gemma3:4b, llama3.2:3b

export NOOR_TRANSLATOR=nllb                # first run downloads ~2.5 GB
export NOOR_EXTRACTOR=ollama
uvicorn noor_ai.app:app
```

NLLB then translates any visitor's free text straight into Bahasa Indonesia (`ind_Latn`), and the
follow-up questions into the visitor's language. A small CPU server with about 8 GB RAM is enough
at a farm's volume. If a model is unavailable, the pipeline falls back and flags rather than guesses.

## Configure

| Variable | Default | Meaning |
|---|---|---|
| `NOOR_LANG` | `id` | Noor's language: Bahasa Indonesia |
| `NOOR_PHONE` | `+620000000000` | Noor's number. **Placeholder: set the real one** |
| `NOOR_SMS` | `console` | `console`, `twilio` or `africastalking` |
| `NOOR_CONFIDENCE_THRESHOLD` | `0.6` | Below this, a comment is flagged rather than interpreted |
| `NOOR_MAX_FOLLOW_UPS` | `6` | Most follow-up questions per visitor |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` |  | Twilio credentials |
| `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID` | `sandbox` | Africa's Talking credentials |

Set your gateway's incoming-SMS webhook to `POST /sms/inbound` so Noor's replies reach the app.

## What Noor receives

**SMS (1 segment, 143 characters):**
```
NOOR AI #1: 2 tamu (Jerman). Nilai 5/5
Masalah: petunjuk jalan/papan nama, ingin beli kopi
Disukai: tur
Balas 1=dibaca 2=telepon 3=teks lengkap
```
**She replies "3", and gets:**
```
#1 teks lengkap:
- Kebunnya luar biasa, tetapi pintu masuknya sulit ditemukan.
- Kami ingin membeli kopi, tetapi tidak ada yang dijual.
```
**Inbox report:** every question and answer in Bahasa Indonesia (for example *Seberapa mudah menemukan
kebun? 2 - Buruk*), the visitor's comments translated, and a list of anything flagged.

## Design choices

- **Hand-written Indonesian for fixed text, machine translation only for free text.** Questions and
  options are the same for every visitor, so they are translated once by a person. That makes the
  report accurate, and only the visitors' own words go through NLLB.
- **Templates, not free generation, for the SMS.** It cannot invent content and always fits one SMS.
- **Human in the loop.** Unclear or untranslatable answers are flagged and shown in the original, and Noor decides.

## Before going live

- Have someone who reads Bahasa Indonesia check NLLB's output on real visitor comments.
- Store submissions in a database; this prototype keeps them in memory.
- Set `NOOR_ADMIN_PASSWORD` so `/noor` and the feedback API need a login (on by default with `render.yaml`).
- Remove names and phone numbers from comments before logging.
- Use a local Indonesian SMS aggregator if it is cheaper than Twilio for numbers in Indonesia.
