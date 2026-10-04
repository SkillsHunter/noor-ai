from fastapi.testclient import TestClient

from noor_ai import NoorAI, Settings, Submission
from noor_ai.extract import RulesExtractor
from noor_ai.langid import detect
from noor_ai.sms_compose import compose, sms_info
from noor_ai.sms_gateway import ConsoleGateway, parse_reply


def make():
    return NoorAI(Settings(translator="lite", extractor="rules", sms_backend="console"), gateway=ConsoleGateway())


def test_language_detection():
    assert detect("Die Farm war fantastisch, aber der Eingang war schwer zu finden.").lang == "de"
    assert detect("La dégustation de café était le meilleur moment !").lang == "fr"
    assert detect("").lang == "und"


def test_script_example_is_structured():
    ex = RulesExtractor().extract("The farm was amazing, but the entrance was difficult to find")
    assert [i.tag for i in ex.issues] == ["signage"]
    assert ex.sentiment in ("mixed", "positive")
    assert ex.confidence >= 0.6


def test_vague_reply_is_flagged_not_guessed():
    r = make().process(Submission(answers={}, comments=["It was okay, but that thing near the house..."]))
    assert r.comments[0].flagged
    assert r.issues == []


def test_untranslatable_text_is_flagged():
    r = make().process(Submission(answers={}, comments=["Das Wetter war heute sehr wechselhaft und kalt."]))
    assert r.comments[0].flagged and r.comments[0].flag_reason == "could not translate"


def test_follow_ups_target_the_problem():
    noor = make()
    r = noor.process(Submission(answers={"Q023": "2 - Poor", "Q091": "5"},
                                comments=["Die Farm war fantastisch, aber der Eingang war schwer zu finden."]))
    cats = {noor.bank.by_id[q["id"]].category for q in r.follow_ups[:3]}
    assert cats == {"Getting there and entrance"}
    assert len(r.follow_ups) <= noor.s.max_follow_ups


def test_sms_fits_one_segment_and_is_in_noors_language():
    r = make().process(Submission(guests=2, answers={"Q091": "5"},
                                  comments=["Die Farm war fantastisch, aber der Eingang war schwer zu finden."]))
    assert r.sms_segments == 1
    assert "Masalah" in r.sms and "Balas 1=dibaca" in r.sms


def test_long_summary_is_trimmed_to_one_segment():
    text = compose(123, 12, "de", 3, ["signage", "facilities", "payment"], ["coffee", "hospitality"], 4, "id")
    assert sms_info(text)[2] == 1


def test_unicode_counts_as_70_chars():
    assert sms_info("a" * 160)[2] == 1
    assert sms_info("ü" * 160)[2] == 1          # ü is GSM-7
    assert sms_info("ş" * 71)[2] == 2           # ş is not


def test_reply_codes():
    assert parse_reply("1") == "seen"
    assert parse_reply("2 tolong") == "call_requested"
    assert parse_reply("terima kasih") == "note"


def test_every_comment_reaches_noor_in_indonesian():
    r = make().process(Submission(guests=2, answers={"Q023": "2 - Poor", "Q040": ["Tasting", "Scenery"], "Q091": "5 - Excellent"},
                                  comments=["Die Farm war fantastisch, aber der Eingang war schwer zu finden.",
                                            "La dégustation de café était le meilleur moment !"]))
    assert [c.indonesian for c in r.comments] == [
        "Kebunnya luar biasa, tetapi pintu masuknya sulit ditemukan.", "Mencicipi kopi adalah momen terbaik!"]
    rows = {a["qid"]: a for a in r.answers_id}
    assert rows["Q023"]["pertanyaan"] == "Seberapa mudah menemukan kebun?"
    assert rows["Q023"]["jawaban"] == "2 - Buruk"
    assert rows["Q040"]["jawaban"] == "Mencicipi kopi, Pemandangan"
    assert "Komentar pengunjung" in r.report_id and "Jerman" in r.report_id


def test_open_text_answers_are_translated_too():
    r = make().process(Submission(answers={"Q095": "Add a sign at the main road."}))
    assert r.comments[0].qid == "Q095"
    assert {a["qid"]: a["jawaban"] for a in r.answers_id}["Q095"] == "Pasang papan petunjuk di jalan utama."


def test_reply_3_sends_full_text():
    noor = make()
    noor.process(Submission(answers={}, comments=["Il n'y avait pas de toilettes et pas d'ombre."]))
    assert "Tidak ada toilet dan tidak ada tempat teduh." in noor.full_text_sms()


def test_api_roundtrip():
    from noor_ai import app as app_module
    from noor_ai.i18n import VisitorLocalizer
    app_module.noor = make()
    app_module.localizer = VisitorLocalizer(app_module.noor.translator)
    client = TestClient(app_module.app)
    assert client.get("/").status_code == 200 and client.get("/noor").status_code == 200
    core = client.get("/api/core?lang=de").json()
    q23 = next(q for q in core["questions"] if q["id"] == "Q023")
    assert q23["question"] == "Wie leicht war die Farm zu finden?"
    assert q23["options"][1] == {"value": "2 - Poor", "label": "2 - Schlecht"}
    fu = client.post("/api/follow-ups", json={"answers": {"Q061": "2 - Poor"}, "comments": [], "lang": "id"}).json()
    assert fu and fu[0]["translated"] == "human"
    res = client.post("/api/feedback", json={"answers": {"Q091": "4 - Good"}, "guests": 1, "lang": "fr",
                                             "comments": ["La dégustation de café était le meilleur moment !"]}).json()
    assert res["highlights"] == ["coffee"] and res["comments"][0]["indonesian"]
    r3 = client.post("/sms/inbound", data={"from": "+620000000000", "text": "3"}).json()
    assert r3["action"] == "full_text" and "Mencicipi kopi" in r3["sent"]
    assert "NOOR AI" in client.get("/api/digest").json()["text"]
    assert client.get("/api/outbox").json()


def test_noor_pages_need_login_when_password_set(monkeypatch):
    import noor_ai.app as app_module
    client = TestClient(app_module.app)
    monkeypatch.setenv("NOOR_ADMIN_PASSWORD", "s3cret")
    assert client.get("/").status_code == 200
    assert client.get("/api/languages").status_code == 200
    for path in ("/noor", "/api/feedback", "/api/outbox", "/api/digest"):
        assert client.get(path).status_code == 401
        assert client.get(path, auth=("noor", "wrong")).status_code == 401
        assert client.get(path, auth=("noor", "s3cret")).status_code == 200
    assert client.post("/sms/inbound", data={"text": "1"}).status_code == 401


def test_feedback_kept_when_sms_fails():
    class Broken:
        def send(self, to, text):
            raise RuntimeError("gateway down")
    noor = NoorAI(Settings(translator="lite", extractor="rules", sms_backend="console"), gateway=Broken())
    r = noor.process(Submission(answers={}, comments=["The toilets were dirty."]))
    assert r.delivery["status"] == "failed" and noor.history == [r]
    assert "tidak ditemukan" in noor.full_text_sms(99)


# ---------------------------------------------------------------- summaries
from datetime import date, timedelta

from noor_ai.summary import MIN_VISITORS


def test_summaries_suggest_from_repeated_feedback_and_close_the_loop():
    noor, today = make(), date(2026, 10, 4)
    noor.seed_demo(today)
    week, month = noor.summary("week", today), noor.summary("month", today)
    assert week.visitors == 4 and month.visitors == 7 and month.prev_visitors == 5
    assert week.suggestions[0].tag == "coffee_sales" and week.suggestions[0].count == 2
    assert "Saran: Jual kopi" in week.sms and "1=ya 2=nanti" in week.sms
    assert month.outcomes == [{"tag": "signage", "decided": "2026-09-04", "before": 4, "after": 0}]
    assert "4->0" in month.sms and not week.outcomes
    assert week.sms_segments <= 2 and month.sms_segments <= 3


def test_no_suggestion_without_enough_visitors():
    noor, today = make(), date(2026, 10, 4)
    for _ in range(MIN_VISITORS - 1):
        noor.process(Submission(answers={}, comments=["Kein Schild an der Straße. Wir haben uns verfahren."], lang="de"),
                     send=False, today=today)
    s = noor.summary("week", today)
    assert not s.enough_data and not s.suggestions and "data kurang" in s.sms


def test_short_comment_in_chosen_language_is_not_flagged_as_unclear():
    assert make().analyse_comment("The coffee tasting was the best part!", hint="en").flag_reason != "language unclear"


def test_noor_answers_a_suggestion_by_sms(monkeypatch):
    import noor_ai.app as app_module
    monkeypatch.delenv("NOOR_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("NOOR_DEMO", "1")
    monkeypatch.setattr(app_module, "noor", make())
    client = TestClient(app_module.app)
    assert client.post("/api/demo/seed").json()["added"] > 0
    s = client.get("/api/summary?period=week&send=true").json()
    assert s["suggestions"] and client.get("/api/decisions").json()["pending"]["tag"] == s["suggestions"][0]["tag"]
    r = client.post("/sms/inbound", data={"from": "noor", "text": "1"}).json()
    assert r["action"] == "decision" and r["decision"]["decision"] == "yes"
    assert client.get("/api/decisions").json()["pending"] is None
    # after a per-visit SMS, "1" means "seen" again, not a decision
    client.post("/api/feedback", json={"answers": {}, "comments": ["The toilets were dirty."], "lang": "en"})
    assert client.post("/sms/inbound", data={"from": "noor", "text": "1"}).json()["action"] == "seen"
    assert client.get("/api/summary?period=year").status_code == 400


def test_demo_seed_is_off_by_default(monkeypatch):
    import noor_ai.app as app_module
    monkeypatch.delenv("NOOR_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("NOOR_DEMO", raising=False)
    assert TestClient(app_module.app).post("/api/demo/seed").status_code == 404
