"""Test Fase 4: draft pesan (Gemini palsu yang disuntik + SQLite in-memory; TANPA jaringan)."""
import socket
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from src.api.config import DEFAULT_GEMINI_MODEL, Settings, get_settings
from src.api.db.models import Base, Prediction, Reminder
from src.api.db.session import make_engine
from src.api.main import create_app
from src.api.services import draft_eval
from src.api.services.draft_service import compose_draft
from src.api.services.gemini_client import GeminiClient, GeminiError, build_draft_generator, classify_error
from src.api.services.post_check import MAX_WORDS, check_draft, clean_output, count_words
from src.api.services.prompt_builder import (FEW_SHOT_EXAMPLES, MESSAGE_TYPES, PERSONAS, SYSTEM_INSTRUCTION,
                                             DraftContext, build_prompt, derive_salutation)
from src.api.services.templates import TEMPLATES, render_template
from src.api.timeutil import now_wib

TOMORROW_0830 = datetime.combine(now_wib().date() + timedelta(days=1), time(8, 30))
GOOD_DRAFT = ("Halo Bu Sari, semoga sehat dan semangat selalu ya 😊 Kami mau mengingatkan kelas Yoga Lembut besok "
              "pukul 08.30 WIB bersama Coach Sari. Kalau ada kendala atau ingin ganti jadwal, kabari kami saja lewat "
              "pesan ini ya, Bu. Kami tunggu kehadirannya dan semoga latihannya menyenangkan. Sampai ketemu di "
              "kelas! Salam hangat, Admin Gymnasium")
TOP_FACTORS = ["3 absen berturut-turut", "tingkat kehadiran 30 hari: 25%"]


# ------------------------------------------------------------------ pengaman: tidak ada jaringan & key asli
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Blokir semua koneksi keluar. Loopback diizinkan: di Windows event loop asyncio (TestClient) memakai
    socketpair lewat 127.0.0.1."""
    real_connect, real_create = socket.socket.connect, socket.create_connection

    def _host(address):
        return address[0] if isinstance(address, tuple) else str(address)

    def _connect(sock, address):
        if _host(address) not in _LOOPBACK:
            raise AssertionError(f"Tes mencoba mengakses jaringan: {address}")
        return real_connect(sock, address)

    def _create(address, *args, **kwargs):
        if _host(address) not in _LOOPBACK:
            raise AssertionError(f"Tes mencoba mengakses jaringan: {address}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket, "create_connection", _create)
    monkeypatch.setenv("GEMINI_API_KEY", "")  # .env tidak akan menimpa nilai yang sudah ada


def test_network_guard_blocks_external_hosts():
    with pytest.raises(AssertionError, match="jaringan"):
        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=1)


class FakeGenerator:
    """Klien Gemini palsu: mengembalikan/melempar `outcomes` berurutan (item terakhir dipakai berulang)."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_instruction: str, prompt: str) -> str:
        self.calls.append((system_instruction, prompt))
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, BaseException):
            raise out
        return out


def _client(generator="none", settings=None):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    kwargs = {} if generator == "auto" else {"draft_generator": None if generator == "none" else generator}
    app = create_app(settings=settings or Settings(database_url=None), engine=engine, model=None, **kwargs)
    return TestClient(app)


def _setup(client, persona="ibu-ibu", nama="Ibu Sari", priority="Low", mtype="reminder_kelas", with_schedule=True,
           when=TOMORROW_0830):
    c = client.post("/customers", json={"nama": nama, "no_whatsapp": "081234567890", "persona": persona}).json()
    sid = None
    if with_schedule:
        sid = client.post("/schedules", json={"nama_kelas": "Yoga Lembut", "tipe": "group_class",
                                              "waktu_mulai": when.isoformat(), "pelatih": "Coach Sari",
                                              "kapasitas": 15}).json()["id"]
    rem = client.post("/reminders", json={"customer_id": c["id"], "schedule_id": sid, "message_type": mtype}).json()
    with client.app.state.session_factory() as db:
        db.get(Reminder, rem["id"]).priority = priority
        db.commit()
    return rem["id"], c["id"]


def _db_reminder(client, rid):
    with client.app.state.session_factory() as db:
        return db.get(Reminder, rid)


def _draft(client, rid, regenerate=False):
    return client.post("/generate-draft", json={"reminder_id": rid, "regenerate": regenerate})


# ------------------------------------------------------------------ endpoint
def test_gemini_draft_saved_and_returned():
    gen = FakeGenerator(GOOD_DRAFT)
    with _client(gen) as client:
        rid, _ = _setup(client)
        r = _draft(client, rid)
        assert r.status_code == 200, r.text
        assert r.json() == {"reminder_id": rid, "draft_message": GOOD_DRAFT, "draft_source": "gemini",
                            "cached": False, "message_type": "reminder_kelas", "warning": None}
        rem = _db_reminder(client, rid)
        assert rem.draft_message == GOOD_DRAFT and rem.draft_source == "gemini" and rem.final_message is None
        system, prompt = gen.calls[0]
        assert system == SYSTEM_INSTRUCTION
        for fact in ("Bu Sari", "Yoga Lembut", "Coach Sari", "08.30", "besok", "Ingatkan kelas"):
            assert fact in prompt


def test_cached_draft_does_not_call_client_again():
    gen = FakeGenerator(GOOD_DRAFT)
    with _client(gen) as client:
        rid, _ = _setup(client)
        _draft(client, rid)
        r = _draft(client, rid)
        assert r.json()["cached"] is True and r.json()["draft_message"] == GOOD_DRAFT
        assert len(gen.calls) == 1


def test_regenerate_calls_client_and_overwrites_draft():
    second = GOOD_DRAFT.replace("semoga latihannya menyenangkan", "semoga latihannya seru")
    gen = FakeGenerator(GOOD_DRAFT, second)
    with _client(gen) as client:
        rid, _ = _setup(client)
        _draft(client, rid)
        r = _draft(client, rid, regenerate=True)
        assert r.json()["cached"] is False and r.json()["draft_message"] == second
        assert len(gen.calls) == 2 and _db_reminder(client, rid).draft_message == second


def test_unknown_reminder_404():
    with _client(FakeGenerator(GOOD_DRAFT)) as client:
        r = _draft(client, 999)
        assert r.status_code == 404 and r.json()["code"] == "not_found"


@pytest.mark.parametrize("path", [["Sent"], ["Sent", "Responded"], ["Sent", "No Response"]])
def test_draft_not_allowed_when_not_scheduled_409(path):
    gen = FakeGenerator(GOOD_DRAFT)
    with _client(gen) as client:
        rid, _ = _setup(client)
        for status in path:
            assert client.patch(f"/reminders/{rid}/status", json={"status": status}).status_code == 200
        for regenerate in (False, True):
            r = _draft(client, rid, regenerate)
            assert r.status_code == 409 and r.json()["code"] == "draft_not_allowed"
            assert path[-1] in r.json()["detail"]
        assert gen.calls == []


@pytest.mark.parametrize("exc,expected", [
    (GeminiError("rate_limit", "HTTP 429", True, 429), "429"),
    (GeminiError("timeout", "ReadTimeout", True), "timeout"),
    (GeminiError("server", "HTTP 503", True, 503), "5xx"),
    (RuntimeError("bug tak terduga"), "tak terduga"),
])
def test_fallback_when_client_fails(exc, expected):
    gen = FakeGenerator(exc)
    with _client(gen) as client:
        rid, _ = _setup(client, persona="lansia", nama="Bambang Hartono")
        r = _draft(client, rid)
        body = r.json()
        assert r.status_code == 200 and body["draft_source"] == "template_fallback" and body["cached"] is False
        assert expected in body["warning"] and "template cadangan" in body["warning"]
        assert body["draft_message"].startswith("Halo Bapak/Ibu Bambang") and "Yoga Lembut" in body["draft_message"]
        rem = _db_reminder(client, rid)
        assert rem.draft_source == "template_fallback" and rem.draft_message == body["draft_message"]
        assert len(gen.calls) == 1  # error jaringan tidak diregenerasi (retry ada di dalam GeminiClient)


def test_fallback_when_response_empty_after_one_regeneration():
    gen = FakeGenerator("", "   ")
    with _client(gen) as client:
        rid, _ = _setup(client)
        body = _draft(client, rid).json()
        assert body["draft_source"] == "template_fallback" and "respons kosong" in body["warning"]
        assert len(gen.calls) == 2


def test_post_check_forbidden_word_triggers_one_regeneration_then_succeeds():
    bad = GOOD_DRAFT.replace("Kami mau mengingatkan", "Karena prioritas Ibu tinggi, kami mengingatkan")
    gen = FakeGenerator(bad, GOOD_DRAFT)
    with _client(gen) as client:
        rid, _ = _setup(client)
        body = _draft(client, rid).json()
        assert body["draft_source"] == "gemini" and body["draft_message"] == GOOD_DRAFT
        assert len(gen.calls) == 2 and "menyebut prioritas" in gen.calls[1][1]  # alasan dikirim saat regenerasi


def test_post_check_failing_twice_falls_back():
    bad = GOOD_DRAFT.replace("Kami mau mengingatkan", "Menurut model AI kami, risiko Ibu absen tinggi, jadi kami ingatkan")
    gen = FakeGenerator(bad)
    with _client(gen) as client:
        rid, _ = _setup(client)
        body = _draft(client, rid).json()
        assert body["draft_source"] == "template_fallback" and "pemeriksaan otomatis" in body["warning"]
        for word in ("model", "AI", "risiko"):
            assert word not in body["draft_message"]
        assert len(gen.calls) == 2


def test_empty_api_key_uses_template_without_client():
    with _client("auto", Settings(database_url=None, gemini_api_key=None)) as client:
        assert client.app.state.draft_generator is None
        rid, _ = _setup(client)
        body = _draft(client, rid).json()
        assert body["draft_source"] == "template_fallback" and "GEMINI_API_KEY" in body["warning"]


def test_final_message_never_touched():
    gen = FakeGenerator(GOOD_DRAFT)
    with _client(gen) as client:
        rid, _ = _setup(client)
        client.patch(f"/reminders/{rid}/message", json={"final_message": "Pesan editan admin"})
        _draft(client, rid)
        _draft(client, rid, regenerate=True)
        rem = _db_reminder(client, rid)
        assert rem.final_message == "Pesan editan admin" and rem.draft_message == GOOD_DRAFT


def test_too_long_draft_is_rejected():
    long_text = GOOD_DRAFT + " Semoga harinya menyenangkan ya." * 20
    gen = FakeGenerator(long_text)
    with _client(gen) as client:
        rid, _ = _setup(client)
        body = _draft(client, rid).json()
        assert body["draft_source"] == "template_fallback" and "terlalu panjang" in body["warning"]
        assert count_words(body["draft_message"]) <= MAX_WORDS


def test_top_factors_not_in_prompt_and_not_in_draft():
    leaky = GOOD_DRAFT.replace("Kalau ada kendala", "Kami lihat ada 3 absen berturut-turut. Kalau ada kendala")
    gen = FakeGenerator(leaky, GOOD_DRAFT)
    with _client(gen) as client:
        rid, cid = _setup(client, priority="High")
        with client.app.state.session_factory() as db:
            db.add(Prediction(customer_id=cid, priority="High", probabilities={"Low": 0.1, "Medium": 0.2, "High": 0.7},
                              top_factors=TOP_FACTORS, model_version="test", created_at=now_wib()))
            db.commit()
        body = _draft(client, rid).json()
        assert body["draft_source"] == "gemini"
        for factor in TOP_FACTORS:
            assert factor not in body["draft_message"]
            assert all(factor not in system and factor not in prompt for system, prompt in gen.calls)
        assert "High" not in gen.calls[0][1]  # label prioritas mentah juga tidak dikirim


def test_missing_priority_adds_warning_and_uses_light_style():
    gen = FakeGenerator(GOOD_DRAFT)
    with _client(gen) as client:
        rid, _ = _setup(client, priority=None)
        body = _draft(client, rid).json()
        assert body["draft_source"] == "gemini" and "Prioritas reminder belum tersedia" in body["warning"]
        assert "Pengingat ringan" in gen.calls[0][1]


def test_reminder_without_schedule_prompt_and_template():
    gen = FakeGenerator(RuntimeError("x"))
    with _client(gen) as client:
        rid, _ = _setup(client, with_schedule=False)
        body = _draft(client, rid).json()
        assert "Kelas: tidak ada data" in gen.calls[0][1]
        assert body["draft_source"] == "template_fallback" and "jadwal kelas berikutnya" in body["draft_message"]


def test_last_message_date_included_in_prompt():
    gen = FakeGenerator(GOOD_DRAFT)
    with _client(gen) as client:
        rid, cid = _setup(client)
        sent_at = datetime(2026, 11, 2, 10, 0)
        with client.app.state.session_factory() as db:
            db.add(Reminder(customer_id=cid, status="Sent", message_type="reminder_kelas", sent_at=sent_at,
                            created_at=sent_at, updated_at=sent_at))
            db.commit()
        _draft(client, rid)
        assert "Pesan terakhir dari kami: Senin, 2 November 2026" in gen.calls[0][1]


# ------------------------------------------------------------------ template & post-check
def _ctx(persona="ibu-ibu", mtype="reminder_kelas", nama="Sari Wijaya", with_class=True, **kw):
    now = datetime(2026, 11, 9, 10, 0)
    when = now - timedelta(days=1) if mtype == "follow_up_absen" else now + timedelta(days=1)
    base = dict(nama_customer=nama, persona=persona, message_type=mtype, now=now, priority="Medium")
    if with_class:
        base.update(nama_kelas="Aerobic Low Impact", class_type="group_class",
                    waktu_kelas=when.replace(hour=9, minute=0), pelatih="Coach Dina")
    base.update(kw)
    return DraftContext(**base)


def test_every_persona_message_type_combination_has_a_valid_template():
    assert set(TEMPLATES) == {(p, m) for p in PERSONAS for m in MESSAGE_TYPES}
    for persona in PERSONAS:
        for mtype in MESSAGE_TYPES:
            for with_class in (True, False):
                for nama in ("Sari Wijaya", "Ibu Sari", "Bapak Budi Santoso"):
                    ctx = _ctx(persona, mtype, nama, with_class, top_factors=TOP_FACTORS)
                    text = render_template(ctx)
                    assert check_draft(text, ctx) == [], (persona, mtype, with_class, nama, text)
                    assert "{" not in text and ctx.salutation.sapaan in text


def test_private_session_template_uses_sesi():
    ctx = _ctx("menengah_atas", nama_kelas="Private Coaching", class_type="private", pelatih="Coach Andra")
    assert "sesi Private Coaching bersama Coach Andra" in render_template(ctx)


def test_few_shot_examples_follow_rules():
    assert len(FEW_SHOT_EXAMPLES) == 6
    for persona in PERSONAS:
        assert sum(ctx.persona == persona for ctx, _ in FEW_SHOT_EXAMPLES) == 2
    for ctx, message in FEW_SHOT_EXAMPLES:
        assert check_draft(message, ctx) == [] and 60 <= count_words(message) <= 80
        assert message in SYSTEM_INSTRUCTION


@pytest.mark.parametrize("phrase", [
    "prioritas", "Prioritas", "risiko", "beresiko", "AI", "model", "skor", "analisis", "prediksi",
    "kategori High", "lansia", "promo", "diskon 50", "gratis", "Rp 100.000", "menyembuhkan", "tekanan darah",
    "kesempatan terakhir", "jangan sampai ketinggalan", "kecewa", "25%", "3 kali absen", "absen berturut-turut",
    "selama 20 hari", "yg", "Berikut draft pesannya:",
])
def test_post_check_rejects_forbidden_phrases(phrase):
    ctx = _ctx()
    text = render_template(ctx).replace("Kami mau mengingatkan", f"{phrase}. Kami mau mengingatkan")
    assert check_draft(text, ctx), phrase


def test_post_check_masks_given_facts():
    ctx = _ctx("lansia", nama_kelas="Senam Ringan Lansia", pelatih="Coach Budi")
    assert check_draft(render_template(ctx), ctx) == []  # "Lansia" & "Low" dari data, bukan kebocoran label
    assert check_draft(render_template(_ctx()), _ctx()) == []  # "Aerobic Low Impact"


@pytest.mark.parametrize("mutate,reason", [
    (lambda t: t.replace("09.00", "10.00"), "jam yang tidak ada"),
    (lambda t: t.replace("10 November", "12 November"), "tanggal yang tidak ada"),
    (lambda t: t.replace("Selasa", "Kamis"), "hari yang tidak ada"),
    (lambda t: t.replace("Aerobic Low Impact", "Zumba"), "nama kelas"),
    (lambda t: "**" + t + "**", "markdown"),
    (lambda t: t.replace("Halo", "Halo [Nama]"), "placeholder"),
    (lambda t: t + " 😊😊😊", "emoji"),
    (lambda t: t.replace("Coach Dina", "Coach Wina"), "menyalin data contoh"),
    (lambda t: "", "kosong"),
    (lambda t: "Halo Bu Sari.", "terlalu pendek"),
])
def test_post_check_detects_rule_violations(mutate, reason):
    ctx = _ctx()
    text = render_template(ctx)
    assert "Selasa, 10 November 2026 pukul 09.00 WIB" in text
    assert any(reason in r for r in check_draft(mutate(text), ctx))


# Output ASLI Gemini dari evaluasi prompt v1 (docs/draft_eval/draft_eval_v1_20261111_2048.md, data synthetic).
V1_OUTPUTS = {
    1: ("Halo Bu Sari, semoga sehat dan semangat selalu ya 😊 Kami ingin mengingatkan jadwal kelas Zumba Fun besok, "
        "Kamis, 12 November 2026 pukul 09.00 WIB bersama Coach Dina. Kami tunggu kehadirannya di gym ya, Bu, semoga "
        "latihannya nanti seru dan menyenangkan. Sampai ketemu di kelas! Salam hangat, Admin Gymnasium"),
    6: ("Halo Bapak/Ibu Bambang, semoga sehat selalu. Kami mengirim pesan pada hari Senin, 9 November 2026. Kemarin, "
        "pada Selasa, 10 November 2026 pukul 09.00 WIB, kami tidak melihat Bapak/Ibu di kelas Senam Sehat Lansia "
        "bersama Coach Budi. Semoga Bapak/Ibu sekeluarga dalam keadaan sehat. Jika berkenan, kami siap membantu "
        "mengatur jadwal pengganti yang lebih leluasa. Silakan membalas pesan ini kapan saja. Salam hormat, Admin "
        "Gymnasium"),
    8: ("Halo Ibu Linda, semoga Ibu sehat dan aktivitasnya menyenangkan. Kami ingin menindaklanjuti pesan kami "
        "sebelumnya pada hari Senin, 9 November 2026. Mengingatkan kembali jadwal sesi Private Coaching besok, Kamis, "
        "12 November 2026 pukul 09.00 WIB bersama Coach Andra. Bagaimana kabar Ibu, dan apakah ada kendala atau "
        "perubahan jadwal yang perlu kami bantu sesuaikan? Mohon konfirmasinya ya, Bu. Salam, Admin Gymnasium"),
    9: ("Halo Ibu Linda, semoga Ibu dan keluarga selalu sehat. Kami sempat mengirim pesan pada Senin, 9 November "
        "2026. Kemarin kami tidak berjumpa dengan Ibu pada sesi Private Coaching pukul 09.00 WIB bersama Coach Andra. "
        "Semoga tidak ada kendala serius yang Ibu hadapi. Jika Ibu ingin mengatur kembali jadwal latihan tersebut, "
        "silakan beri tahu kami agar bisa kami bantu. Kami nantikan kabar baik dari Ibu. Salam, Admin Gymnasium"),
}


@pytest.mark.parametrize("no,expected", [
    (1, []),
    (6, ["mengungkit pesan", "'sehat' lebih dari 1x", "tanggal yang tidak ada"]),
    (8, ["partikel santai", "tanggal yang tidak ada"]),
    (9, ["mengungkit pesan", "berasumsi customer sakit", "tanggal yang tidak ada"]),
])
def test_v2_post_check_catches_problems_found_in_v1_evaluation(no, expected):
    ctx = {sc.no: sc.ctx for sc in draft_eval.build_scenarios(datetime(2026, 11, 11, 20, 48))}[no]
    reasons = check_draft(V1_OUTPUTS[no], ctx)
    assert (reasons == []) if not expected else all(any(e in r for r in reasons) for e in expected), reasons


@pytest.mark.parametrize("persona,phrase,reason", [
    ("lansia", "Sampai jumpa ya.", "partikel santai"),
    ("menengah_atas", "Tidak apa-apa kok.", "partikel santai"),
    ("ibu-ibu", "Kami sudah mengirimkan pesan kemarin.", "mengungkit pesan"),
    ("lansia", "Semoga lekas sembuh.", "berasumsi"),
    ("menengah_atas", "Kami nantikan kabar baik dari Ibu.", "menuntut balasan"),
    ("ibu-ibu", "Semoga sehat. Semoga senang. Semoga lancar.", "'semoga' 4x"),
])
def test_v2_post_check_rules(persona, phrase, reason):
    ctx = _ctx(persona)
    text = render_template(ctx).replace("Halo", f"{phrase} Halo", 1)
    assert any(reason in r for r in check_draft(text, ctx)), check_draft(text, ctx)


def test_v2_casual_particles_still_allowed_for_ibu_ibu():
    ctx = _ctx("ibu-ibu")
    text = render_template(ctx).replace("Halo", "Sampai ketemu ya. Halo", 1)
    assert check_draft(text, ctx) == []


def test_v2_last_message_date_is_context_only():
    last = datetime(2026, 11, 6, 9, 0)
    ctx = _ctx("ibu-ibu", "follow_up_tidak_merespons", tanggal_pesan_terakhir=last)
    prompt = build_prompt(ctx)
    assert "Pesan terakhir dari kami: Jumat, 6 November 2026 (konteks saja; JANGAN" in prompt
    text = render_template(ctx).replace("Halo", "Pesan kami pada Jumat, 6 November 2026 belum dibalas. Halo", 1)
    reasons = check_draft(text, ctx)
    assert any("tanggal yang tidak ada" in r for r in reasons) and any("hari yang tidak ada" in r for r in reasons)


def test_clean_output_strips_quotes_and_blank_lines():
    assert clean_output('  "Halo Bu Sari,\n\n\n\nsampai jumpa."  ') == "Halo Bu Sari,\n\nsampai jumpa."
    assert clean_output(None) == ""


@pytest.mark.parametrize("nama,persona,sapaan,ganti", [
    ("Sari Wijaya", "ibu-ibu", "Bu Sari", "Ibu"),
    ("Ibu Sari Wijaya", "ibu-ibu", "Bu Sari", "Ibu"),
    ("Bapak Budi", "ibu-ibu", "Pak Budi", "Bapak"),
    ("Hendra Gunawan", "lansia", "Bapak/Ibu Hendra", "Bapak/Ibu"),
    ("Hj. Aminah Salim", "lansia", "Ibu Aminah", "Ibu"),
    ("Pak Joko", "lansia", "Bapak Joko", "Bapak"),
    ("Ny. Linda Tanujaya", "menengah_atas", "Ibu Linda", "Ibu"),
    ("Dr. Agus Halim", "menengah_atas", "Bapak/Ibu Agus", "Bapak/Ibu"),
    ("RATNA PUTRI", "menengah_atas", "Bapak/Ibu Ratna", "Bapak/Ibu"),
    ("Ibu", "lansia", "Ibu", "Ibu"),
])
def test_derive_salutation(nama, persona, sapaan, ganti):
    sal = derive_salutation(nama, persona)
    assert (sal.sapaan, sal.kata_ganti) == (sapaan, ganti)


def test_prompt_regeneration_note_and_no_raw_priority():
    ctx = _ctx(priority="High", top_factors=TOP_FACTORS)
    prompt = build_prompt(ctx, ["menyebut prioritas ('prioritas')"])
    assert "ditolak pemeriksaan otomatis" in prompt and "tawarkan bantuan" in prompt
    assert "High" not in prompt and all(f not in prompt for f in TOP_FACTORS)


def test_prompt_doc_matches_code():
    from pathlib import Path

    from src.api.services import prompt_builder

    doc = (Path(__file__).resolve().parents[1] / "docs" / "PROMPT_ENGINEERING.md").read_text(encoding="utf-8")
    assert prompt_builder._RULES in doc, "Perbarui bagian 3.1 docs/PROMPT_ENGINEERING.md sesuai _RULES"
    assert f"Versi prompt saat ini: **{prompt_builder.PROMPT_VERSION}**" in doc


def test_compose_without_generator_is_template():
    res = compose_draft(_ctx(), None)
    assert res.source == "template_fallback" and res.attempts == 0 and "GEMINI_API_KEY" in res.warning


# ------------------------------------------------------------------ GeminiClient (SDK palsu, tanpa jaringan)
class FakeSDK:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return SimpleNamespace(text=out)


def _api_error(code, status):
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": {"code": code, "message": "pesan uji", "status": status}})


def _gemini(sdk, **kw):
    sleeps = []
    client = GeminiClient(api_key="kunci-uji", model="gemini-uji", sdk_client=sdk, sleep=sleeps.append, **kw)
    return client, sleeps


def test_gemini_client_passes_model_temperature_and_system_instruction():
    sdk = FakeSDK("  Halo Bu Sari  ")
    client, _ = _gemini(sdk, temperature=0.7)
    assert client.generate("ATURAN", "DATA") == "Halo Bu Sari"
    call = sdk.calls[0]
    assert call["model"] == "gemini-uji" and call["contents"] == "DATA"
    assert isinstance(call["config"], genai_types.GenerateContentConfig)
    assert call["config"].temperature == 0.7 and call["config"].system_instruction == "ATURAN"
    assert call["config"].max_output_tokens is None


def test_gemini_client_retries_429_and_5xx_with_backoff_then_succeeds():
    sdk = FakeSDK(_api_error(429, "RESOURCE_EXHAUSTED"), _api_error(503, "UNAVAILABLE"), "ok")
    client, sleeps = _gemini(sdk, max_retries=2, base_delay=1.0)
    assert client.generate("s", "p") == "ok" and len(sdk.calls) == 3
    assert len(sleeps) == 2 and 1.0 <= sleeps[0] <= 1.1 and 2.0 <= sleeps[1] <= 2.2


def test_gemini_client_gives_up_after_bounded_retries():
    sdk = FakeSDK(*[_api_error(429, "RESOURCE_EXHAUSTED")] * 3)
    client, sleeps = _gemini(sdk, max_retries=2)
    with pytest.raises(GeminiError) as exc:
        client.generate("s", "p")
    assert exc.value.kind == "rate_limit" and exc.value.http_code == 429 and len(sdk.calls) == 3 and len(sleeps) == 2


def test_gemini_client_retries_timeout():
    sdk = FakeSDK(httpx.ReadTimeout("lambat"), "ok")
    client, sleeps = _gemini(sdk)
    assert client.generate("s", "p") == "ok" and len(sleeps) == 1


@pytest.mark.parametrize("code,status,kind", [(400, "INVALID_ARGUMENT", "bad_request"),
                                               (403, "PERMISSION_DENIED", "auth"), (404, "NOT_FOUND", "not_found")])
def test_gemini_client_does_not_retry_permanent_errors(code, status, kind):
    sdk = FakeSDK(_api_error(code, status))
    client, sleeps = _gemini(sdk)
    with pytest.raises(GeminiError) as exc:
        client.generate("s", "p")
    assert exc.value.kind == kind and len(sdk.calls) == 1 and sleeps == []


def test_gemini_client_empty_text_returns_empty_string():
    client, _ = _gemini(FakeSDK(None))
    assert client.generate("s", "p") == ""


def test_classify_error_generic_exceptions():
    assert classify_error(TimeoutError()).kind == "timeout"
    assert classify_error(ConnectionError()).kind == "connection"
    assert classify_error(ValueError()).kind == "unknown" and not classify_error(ValueError()).retryable


def test_build_draft_generator_from_settings():
    assert build_draft_generator(Settings(gemini_api_key=None)) is None
    gen = build_draft_generator(Settings(gemini_api_key="rahasia", gemini_model=None, gemini_temperature=0.5))
    assert gen.model == DEFAULT_GEMINI_MODEL and gen.temperature == 0.5 and "rahasia" not in repr(gen)
    assert build_draft_generator(Settings(gemini_api_key="k", gemini_model="gemini-lain")).model == "gemini-lain"
    with pytest.raises(ValueError):
        GeminiClient(api_key="", model="m")


def test_settings_parse_gemini_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "   ")
    monkeypatch.setenv("GEMINI_TEMPERATURE", "abc")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "3")
    s = get_settings()
    assert s.gemini_api_key is None and s.gemini_model is None and s.effective_gemini_model == DEFAULT_GEMINI_MODEL
    assert s.gemini_temperature == 0.7 and s.gemini_timeout_seconds == 20.0 and s.gemini_max_retries == 3


# ------------------------------------------------------------------ skrip evaluasi (tanpa Gemini)
def test_draft_eval_writes_nine_scenarios_with_rubric(tmp_path):
    rows = draft_eval.run_eval(FakeGenerator(RuntimeError("tanpa jaringan")), now=datetime(2026, 11, 9, 10, 0))
    assert len(rows) == 9
    assert {(r["scenario"].persona, r["scenario"].priority) for r in rows} == {
        (p, pr) for p in PERSONAS for pr in ("Low", "Medium", "High")}
    md = draft_eval.to_markdown(rows, "gemini-uji", 0.7, False, datetime(2026, 11, 9, 10, 0))
    lines = md.splitlines()
    sheet_at = lines.index(draft_eval.SHEET_HEADING)
    results = [ln for ln in lines[:sheet_at] if ln.startswith("| ") and ln[2].isdigit()]
    sheet = [ln for ln in lines[sheet_at:] if ln.startswith("| ") and ln[2].isdigit()]
    assert len(results) == 9 and len(sheet) == 9
    header = next(ln for ln in lines[sheet_at:] if ln.startswith("| No |"))
    assert all(ln.count("|") == header.count("|") for ln in sheet)
    for col in draft_eval.RUBRIC:
        assert col in header
    assert "synthetic" in md and "--summarize" in md
    means, complete, total, errors = draft_eval.summarize(md)
    assert (complete, total, errors) == (0, 9, []) and all(m is None for m in means.values())


def _fill_sheet(md, scores):
    """Isi Lembar nilai baris demi baris dengan `scores` (list nilai per baris)."""
    out, i = [], 0
    in_sheet = False
    for ln in md.splitlines():
        in_sheet = in_sheet or ln == draft_eval.SHEET_HEADING
        if in_sheet and ln.startswith("| ") and ln[2].isdigit() and i < len(scores):
            cells = ln.split("|")
            cells[5:5 + len(draft_eval.RUBRIC)] = [f" {v} " for v in scores[i]]
            ln, i = "|".join(cells), i + 1
        out.append(ln)
    return "\n".join(out)


def test_draft_eval_summarize_averages_and_validation():
    rows = draft_eval.run_eval(None, now=datetime(2026, 11, 9, 10, 0))
    md = draft_eval.to_markdown(rows, "m", 0.7, True, datetime(2026, 11, 9, 10, 0))
    filled = _fill_sheet(md, [[5, 4, 5, 5, 4], [3, 4, 5, 5, 2], [4, 4, 5, "", 3]])
    means, complete, total, errors = draft_eval.summarize(filled)
    assert (complete, total, errors) == (2, 9, [])
    assert means["Nada (1-5)"] == 4.0 and means["Siap kirim (1-5)"] == 3.0
    assert means["Tanpa fakta karangan (1-5)"] == 5.0  # sel kosong tidak ikut dihitung
    _, _, _, errors = draft_eval.summarize(_fill_sheet(md, [[5, 4, 7, 5, "x"]]))
    assert len(errors) == 2 and "bukan angka 1-5" in errors[0]
    assert draft_eval.summarize("# tanpa lembar nilai")[3]


def test_draft_eval_main_requires_key_unless_dry_run(tmp_path, capsys):
    assert draft_eval.main(["--out", str(tmp_path / "x.md")]) == 2
    out = tmp_path / "dry.md"
    assert draft_eval.main(["--dry-run", "--out", str(out)]) == 0
    assert out.exists() and "dry-run" in out.read_text(encoding="utf-8")
