"""Web app: the visitor's chat form, Noor's inbox, and the SMS webhook.

Run:  uvicorn noor_ai.app:app --reload
      open http://localhost:8000          (visitor chat, add ?demo=1 to see Noor's phone beside it)
      open http://localhost:8000/noor     (all feedback in Bahasa Indonesia)

API
GET  /api/languages               languages the form offers
GET  /api/core?lang=de            UI text + core questions in the visitor's language
POST /api/follow-ups              answers + comments so far -> next questions, in the visitor's language
POST /api/feedback                finished form -> translated to Indonesian, summary SMS sent to Noor
GET  /api/feedback                every processed submission (Noor's inbox)
GET  /api/summary?period=week|month&send=true   weekly / monthly summary with a suggestion
GET  /api/decisions               Noor's 1=ya / 2=nanti answers to suggestions
POST /api/demo/seed               synthetic visits for the demo (only when NOOR_DEMO=1)
GET  /api/digest?send=true        weekly summary SMS (older name)
POST /sms/inbound                 SMS gateway webhook: Noor replies 1 (seen), 2 (call me), 3 (full text)

Set NOOR_ADMIN_PASSWORD to protect Noor's side (/noor, reading feedback, digest, outbox,
replies, SMS webhook) with HTTP Basic auth, user NOOR_ADMIN_USER (default "noor").
For a gateway webhook use https://noor:<password>@your-host/sms/inbound.

NOOR_SCHEDULE=1 sends the weekly summary on Sunday 18:00 and the monthly one on the 1st at 08:00
(local time, NOOR_TZ_OFFSET hours from UTC, default 7 = WIB). On hosts that sleep, call
/api/summary?period=week&send=true from a cron job instead.
"""
import asyncio
import contextlib
import os
import secrets
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from .i18n import VisitorLocalizer, languages, ui_strings
from .pipeline import NoorAI, Submission
from .sms_gateway import parse_reply, reply_feedback_no

STATIC = Path(__file__).resolve().parent / "static"
AUTO_FILLED = {"Q001"}  # visit date is filled in automatically

async def _scheduler():
    sent = set()
    offset = timedelta(hours=float(os.getenv("NOOR_TZ_OFFSET", "7")))
    while True:
        now = datetime.now(timezone.utc) + offset
        week, month = ("week", *now.isocalendar()[:2]), ("month", now.year, now.month)
        if now.weekday() == 6 and now.hour >= 18 and week not in sent:
            noor.send_summary("week"); sent.add(week)
        if now.day == 1 and now.hour >= 8 and month not in sent:
            noor.send_summary("month"); sent.add(month)
        await asyncio.sleep(600)


@contextlib.asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_scheduler()) if os.getenv("NOOR_SCHEDULE") == "1" else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Noor AI", lifespan=lifespan)
noor = NoorAI()
localizer = VisitorLocalizer(noor.translator)
replies: list[dict] = []
basic = HTTPBasic(auto_error=False)


def noor_only(creds: HTTPBasicCredentials | None = Depends(basic)):
    """Basic auth for Noor's pages; open when NOOR_ADMIN_PASSWORD is unset (local dev)."""
    password = os.getenv("NOOR_ADMIN_PASSWORD")
    if not password:
        return
    user = os.getenv("NOOR_ADMIN_USER", "noor")
    if not (creds and secrets.compare_digest(creds.username.encode(), user.encode())
            and secrets.compare_digest(creds.password.encode(), password.encode())):
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": 'Basic realm="Noor AI"'})


class SubmissionIn(BaseModel):
    answers: dict = Field(default_factory=dict, examples=[{"Q023": "2 - Poor", "Q091": "5 - Excellent"}])
    comments: list[str] = Field(default_factory=list,
                                examples=[["Die Farm war fantastisch, aber der Eingang war schwer zu finden."]])
    guests: int | None = None
    visitor_id: str = ""
    lang: str = "en"


# ------------------------------------------------------------------ pages
@app.get("/", include_in_schema=False)
def visitor_page():
    return FileResponse(STATIC / "index.html")


@app.get("/noor", include_in_schema=False, dependencies=[Depends(noor_only)])
def noor_page():
    return FileResponse(STATIC / "noor.html")


# -------------------------------------------------------------------- api
@app.get("/api/languages")
def api_languages():
    return languages()


@app.get("/api/core")
def api_core(lang: str = "en"):
    qs = [localizer.question(q, lang) for q in noor.bank.core_questions() if q.id not in AUTO_FILLED]
    return {"lang": lang, "ui": ui_strings(lang), "questions": qs}


@app.post("/api/follow-ups")
def api_follow_ups(sub: SubmissionIn):
    tags = []
    for c in sub.comments + [v for k, v in sub.answers.items()
                             if noor.bank.by_id.get(k) and noor.bank.by_id[k].response_type == "open_text"]:
        if isinstance(c, str) and c.strip():
            r = noor.analyse_comment(c, hint=sub.lang)
            if not r.flagged:
                tags += [i["tag"] for i in r.extraction["issues"]]
    qs = noor.bank.plan_follow_ups(sub.answers, tags, noor.s.max_follow_ups)
    return [localizer.question(q, sub.lang) for q in qs]


@app.post("/api/feedback")
def api_feedback(sub: SubmissionIn):
    data = sub.model_dump()
    data["answers"].setdefault("Q001", date.today().isoformat())
    res = noor.process(Submission(**data))
    return asdict(res)


@app.get("/api/feedback", dependencies=[Depends(noor_only)])
def api_all_feedback():
    return [asdict(r) for r in reversed(noor.history)]


@app.get("/api/digest", dependencies=[Depends(noor_only)])
def api_digest(send: bool = False):
    if send:
        s = noor.send_summary("week")
        return {"text": s["sms"], "delivery": s["delivery"]}
    return {"text": noor.digest(), "delivery": None}


@app.get("/api/summary", dependencies=[Depends(noor_only)])
def api_summary(period: str = "week", send: bool = False):
    if period not in ("week", "month"):
        raise HTTPException(400, "period must be week or month")
    return noor.send_summary(period) if send else asdict(noor.summary(period))


@app.get("/api/decisions", dependencies=[Depends(noor_only)])
def api_decisions():
    return {"pending": noor.pending, "decisions": list(reversed(noor.decisions))}


@app.post("/api/demo/seed", dependencies=[Depends(noor_only)])
def api_demo_seed():
    if os.getenv("NOOR_DEMO") != "1":
        raise HTTPException(404, "Demo data is off (set NOOR_DEMO=1)")
    return {"added": noor.seed_demo()}


@app.get("/api/replies", dependencies=[Depends(noor_only)])
def api_replies():
    return replies


@app.get("/api/outbox", dependencies=[Depends(noor_only)])
def api_outbox():
    """SMS sent to Noor (console gateway only; real gateways keep their own logs)."""
    return list(reversed(getattr(noor.gateway, "outbox", [])))


@app.post("/sms/inbound", dependencies=[Depends(noor_only)])
async def sms_inbound(request: Request):
    """Point your SMS gateway's incoming-message webhook here."""
    form = dict(await request.form())
    sender = form.get("From") or form.get("from", "")
    text = form.get("Body") or form.get("text", "")
    action = parse_reply(text)
    entry = {"from": sender, "text": text, "action": action}
    if hasattr(noor.gateway, "outbox"):           # demo: show Noor's reply in the phone view
        noor.gateway.outbox.append({"from": "noor", "text": text})
    if noor.pending and action in ("seen", "call_requested"):   # answering a summary suggestion
        entry["action"] = "decision"
        entry["decision"] = noor.decide("yes" if action == "seen" else "later")
    elif action == "full_text":
        full = noor.full_text_sms(reply_feedback_no(text))
        entry["sent"] = full
        noor.gateway.send(noor.s.noor_phone, full)
    replies.append(entry)
    return entry
