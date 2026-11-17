"""Web app: the visitor's chat form, Noor's inbox, and the SMS webhook.

Run:  NOOR_DEV=1 uvicorn noor_ai.app:app --reload
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

Security
- NOOR_ADMIN_PASSWORD protects Noor's side (/noor, reading feedback, digest, outbox, replies)
  with HTTP Basic auth, user NOOR_ADMIN_USER (default "noor"). If it is unset, Noor's side is
  closed (503) unless NOOR_DEV=1, which opens it for local development only.
- Actions that send SMS or change data (summary/digest with send=true, demo seed, replies typed
  on the demo phone) also need the X-Noor-Action: 1 header, so another website cannot trigger
  them through Noor's logged-in browser (CSRF).
- The SMS gateway authenticates with its own secret, not the admin password:
  set NOOR_WEBHOOK_TOKEN and point the gateway at https://your-host/sms/inbound?token=<token>.
  Only messages from NOOR_PHONE are accepted on that path.
- Public endpoints are size-limited and rate-limited per client IP (NOOR_RATE_FEEDBACK,
  NOOR_RATE_FOLLOW_UPS per minute), and per-visit SMS are capped (NOOR_SMS_PER_HOUR).
- /docs and /openapi.json are only served when NOOR_DEV=1 or NOOR_DOCS=1.

NOOR_SCHEDULE=1 sends the weekly summary on Sunday 18:00 and the monthly one on the 1st at 08:00
(local time, NOOR_TZ_OFFSET hours from UTC, default 7 = WIB). On hosts that sleep, call
/api/summary?period=week&send=true from a cron job instead (with Basic auth and X-Noor-Action: 1).
"""
import asyncio
import contextlib
import os
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, StringConstraints, field_validator

from .i18n import VisitorLocalizer, languages, ui_strings
from .pipeline import NoorAI, Submission
from .sms_gateway import parse_reply, reply_feedback_no

STATIC = Path(__file__).resolve().parent / "static"
AUTO_FILLED = {"Q001"}  # visit date is filled in automatically

MAX_COMMENTS = 10
MAX_COMMENT_CHARS = 2000
MAX_ANSWERS = 100
MAX_ANSWER_CHARS = 2000


def _dev_mode() -> bool:
    return os.getenv("NOOR_DEV") == "1"


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


_docs = _dev_mode() or os.getenv("NOOR_DOCS") == "1"
app = FastAPI(title="Noor AI", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url=None,
              openapi_url="/openapi.json" if _docs else None)
noor = NoorAI()
localizer = VisitorLocalizer(noor.translator)
replies: list[dict] = []
basic = HTTPBasic(auto_error=False)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


# ------------------------------------------------------------------- auth
def noor_only(creds: HTTPBasicCredentials | None = Depends(basic)):
    """Basic auth for Noor's pages. Without NOOR_ADMIN_PASSWORD they stay closed unless NOOR_DEV=1."""
    password = os.getenv("NOOR_ADMIN_PASSWORD")
    if not password:
        if _dev_mode():
            return
        raise HTTPException(503, "Noor's side is closed: set NOOR_ADMIN_PASSWORD (or NOOR_DEV=1 for local development)")
    user = os.getenv("NOOR_ADMIN_USER", "noor")
    if not (creds and secrets.compare_digest(creds.username.encode(), user.encode())
            and secrets.compare_digest(creds.password.encode(), password.encode())):
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": 'Basic realm="Noor AI"'})


def _require_action_header(request: Request):
    """Browsers re-send cached Basic auth on cross-site requests; a custom header cannot be forged that way."""
    if os.getenv("NOOR_ADMIN_PASSWORD") and request.headers.get("X-Noor-Action") != "1":
        raise HTTPException(403, "Missing X-Noor-Action header")


def noor_action(request: Request, _auth=Depends(noor_only)):
    """Noor's side, for requests that send SMS or change data."""
    _require_action_header(request)


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


# ------------------------------------------------------------ rate limits
_hits: dict[tuple, deque] = defaultdict(deque)


def rate_limited(kind: str, env: str, default: int):
    def check(request: Request):
        limit = int(os.getenv(env, str(default)))
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        if len(_hits) > 10_000:          # keep memory bounded under a flood of distinct IPs
            _hits.clear()
        q = _hits[(kind, ip)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many requests, please wait a minute")
        q.append(now)
    return check


# ------------------------------------------------------------- redaction
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def redact(text: str) -> str:
    """Remove e-mail addresses and phone numbers (9+ digits) that visitors type into comments."""
    text = _EMAIL.sub("[redacted]", text)
    return _PHONE.sub(lambda m: "[redacted]" if len(_digits(m.group())) >= 9 else m.group(), text)


Comment = Annotated[str, StringConstraints(max_length=MAX_COMMENT_CHARS)]


class SubmissionIn(BaseModel):
    answers: dict = Field(default_factory=dict, examples=[{"Q023": "2 - Poor", "Q091": "5 - Excellent"}])
    comments: list[Comment] = Field(default_factory=list, max_length=MAX_COMMENTS,
                                    examples=[["Die Farm war fantastisch, aber der Eingang war schwer zu finden."]])
    guests: int | None = Field(default=None, ge=0, le=500)
    visitor_id: str = Field(default="", max_length=64)
    lang: str = Field(default="en", max_length=12)

    @field_validator("answers")
    @classmethod
    def bounded_answers(cls, answers: dict) -> dict:
        if len(answers) > MAX_ANSWERS:
            raise ValueError(f"at most {MAX_ANSWERS} answers")
        for k, v in answers.items():
            if len(str(k)) > 20 or len(str(v)) > MAX_ANSWER_CHARS:
                raise ValueError("answer too long")
        return answers


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


@app.post("/api/follow-ups", dependencies=[Depends(rate_limited("follow-ups", "NOOR_RATE_FOLLOW_UPS", 60))])
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


@app.post("/api/feedback", dependencies=[Depends(rate_limited("feedback", "NOOR_RATE_FEEDBACK", 10))])
def api_feedback(sub: SubmissionIn):
    data = sub.model_dump()
    data["comments"] = [redact(c) for c in data["comments"]]
    for k, v in data["answers"].items():
        q = noor.bank.by_id.get(k)
        if isinstance(v, str) and q and q.response_type == "open_text":
            data["answers"][k] = redact(v)
    data["answers"].setdefault("Q001", date.today().isoformat())
    res = noor.process(Submission(**data))
    return asdict(res)


@app.get("/api/feedback", dependencies=[Depends(noor_only)])
def api_all_feedback():
    return [asdict(r) for r in reversed(noor.history)]


@app.get("/api/digest", dependencies=[Depends(noor_only)])
def api_digest(request: Request, send: bool = False):
    if send:
        _require_action_header(request)
        s = noor.send_summary("week")
        return {"text": s["sms"], "delivery": s["delivery"]}
    return {"text": noor.digest(), "delivery": None}


@app.get("/api/summary", dependencies=[Depends(noor_only)])
def api_summary(request: Request, period: str = "week", send: bool = False):
    if period not in ("week", "month"):
        raise HTTPException(400, "period must be week or month")
    if send:
        _require_action_header(request)
        return noor.send_summary(period)
    return asdict(noor.summary(period))


@app.get("/api/decisions", dependencies=[Depends(noor_only)])
def api_decisions():
    return {"pending": noor.pending, "decisions": list(reversed(noor.decisions))}


@app.post("/api/demo/seed", dependencies=[Depends(noor_action)])
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


def sms_sender_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(basic)) -> str:
    """The gateway proves itself with ?token=NOOR_WEBHOOK_TOKEN; Noor's demo phone uses her login."""
    token = os.getenv("NOOR_WEBHOOK_TOKEN")
    supplied = request.query_params.get("token")
    if token and supplied:
        if secrets.compare_digest(supplied.encode(), token.encode()):
            return "gateway"
        raise HTTPException(401, "Bad webhook token")
    noor_only(creds)
    _require_action_header(request)
    return "noor"


@app.post("/sms/inbound")
async def sms_inbound(request: Request, source: str = Depends(sms_sender_auth)):
    """Point your SMS gateway's incoming-message webhook here (with ?token=NOOR_WEBHOOK_TOKEN)."""
    form = dict(await request.form())
    sender = str(form.get("From") or form.get("from", ""))[:32]
    text = str(form.get("Body") or form.get("text", ""))[:160]
    if source == "gateway" and _digits(sender) != _digits(noor.s.noor_phone):
        raise HTTPException(403, "Only Noor's number may reply")
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
    del replies[:-500]                               # keep the reply log bounded
    return entry
