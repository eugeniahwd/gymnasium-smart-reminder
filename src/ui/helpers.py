"""Fungsi pembantu UI tanpa dependensi Streamlit (bisa dites langsung).

UI hanya berbicara dengan FastAPI; modul ini tidak boleh mengimpor apa pun dari `src.api` atau database.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping
from urllib.parse import quote

try:
    from zoneinfo import ZoneInfo

    WIB = ZoneInfo("Asia/Jakarta")
except Exception:  # tzdata tidak ada -> UTC+7 tetap (Indonesia tanpa DST)
    WIB = timezone(timedelta(hours=7))

DEFAULT_API_BASE_URL = "http://localhost:8000"
DISCLAIMER = ("PROTOTYPE - seluruh data adalah data synthetic. Prioritas dari model ML dan draft dari AI hanya "
              "bantuan, bukan klaim akurasi di kondisi nyata. Pesan tidak dikirim otomatis.")

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

PRIORITY_STYLE: dict[str | None, tuple[str, str]] = {  # (warna st.badge, emoji untuk tabel)
    "High": ("red", "🔴"), "Medium": ("orange", "🟠"), "Low": ("green", "🟢"), None: ("gray", "⚪"),
}
STATUS_STYLE = {"Scheduled": "blue", "Sent": "violet", "Responded": "green", "No Response": "gray"}
STATUS_HINT = {"Scheduled": "belum dikirim", "Sent": "terkirim, menunggu balasan", "Responded": "sudah dibalas",
               "No Response": "tidak ada balasan"}
MESSAGE_TYPE_LABEL = {"reminder_kelas": "Reminder kelas", "follow_up_absen": "Follow-up setelah absen",
                      "follow_up_tidak_merespons": "Follow-up belum membalas"}
PERSONA_LABEL = {"ibu-ibu": "Ibu-ibu", "lansia": "Lansia", "menengah_atas": "Menengah atas"}
CLASS_TYPE_LABEL = {"group_class": "Kelas grup", "private": "Private"}
DRAFT_SOURCE_LABEL = {"gemini": "Gemini (AI)", "template_fallback": "Template cadangan"}
# Cermin alur backend (validasi tetap di backend): Scheduled -> Sent -> Responded | No Response
NEXT_STATUSES = {"Scheduled": ["Sent"], "Sent": ["Responded", "No Response"], "Responded": [], "No Response": []}


def today_wib() -> date:
    """Tanggal hari ini di WIB (server Streamlit Cloud memakai UTC)."""
    return datetime.now(WIB).date()


def resolve_api_base_url(secrets_get: Callable[[str], str | None] | None = None,
                         environ: Mapping[str, str] | None = None) -> str:
    """Urutan: st.secrets["API_BASE_URL"] -> env API_BASE_URL -> http://localhost:8000. Garis miring akhir dibuang."""
    environ = os.environ if environ is None else environ
    value = None
    if secrets_get is not None:
        try:
            value = secrets_get("API_BASE_URL")
        except Exception:  # noqa: BLE001 - secrets tidak tersedia
            value = None
    value = (value or environ.get("API_BASE_URL") or DEFAULT_API_BASE_URL).strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"API_BASE_URL harus diawali http:// atau https:// (sekarang: {value!r})")
    return value.rstrip("/")


def wa_url(number: str, text: str | None = None) -> str:
    """Link wa.me yang membuka WhatsApp dengan teks terisi. Admin tetap menekan kirim sendiri."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    if not digits:
        raise ValueError("Nomor WhatsApp kosong")
    url = f"https://wa.me/{digits}"
    text = (text or "").strip()
    return f"{url}?text={quote(text, safe='')}" if text else url


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def format_dt(value: str | datetime | None, with_day: bool = True) -> str:
    """'Jumat, 13 Nov 2026 09.00' (WIB, tanpa bergantung locale)."""
    dt = parse_dt(value)
    if dt is None:
        return "-"
    base = f"{dt.day} {BULAN[dt.month - 1]} {dt.year} {dt.hour:02d}.{dt.minute:02d}"
    return f"{HARI[dt.weekday()]}, {base}" if with_day else base


def format_date(value: date | str | None) -> str:
    if value is None:
        return "-"
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{HARI[d.weekday()]}, {d.day} {BULAN[d.month - 1]} {d.year}"


def format_time(value: str | datetime | None) -> str:
    dt = parse_dt(value)
    return "-" if dt is None else f"{dt.hour:02d}.{dt.minute:02d}"


def format_probabilities(probs: Mapping[str, float] | None) -> str:
    """'High 65% · Medium 25% · Low 10%' (urut High -> Low)."""
    if not probs:
        return "belum ada"
    return " · ".join(f"{k} {probs[k]:.0%}" for k in ("High", "Medium", "Low") if k in probs)


def priority_label(priority: str | None) -> str:
    return f"{PRIORITY_STYLE.get(priority, PRIORITY_STYLE[None])[1]} {priority or 'Belum ada'}"


def empty_day_message(d: date) -> str:
    """Penjelasan saat tidak ada reminder untuk tanggal kelas `d`."""
    if d.weekday() == 6:
        return (f"Tidak ada reminder untuk {format_date(d)}. Kelas hanya berlangsung Senin-Sabtu, jadi hari Minggu "
                "memang kosong.")
    return (f"Tidak ada reminder untuk kelas pada {format_date(d)}. Jika ini data demo, jalankan "
            "`python -m src.data_generation.seed_demo` agar data synthetic diperpanjang sampai hari ini.")


def reminder_option_label(rem: Mapping) -> str:
    """Label pilihan reminder: '🔴 High · Sari Wijaya · Zumba Fun 09.00 · Scheduled'."""
    customer = (rem.get("customer") or {}).get("nama", f"customer #{rem.get('customer_id')}")
    schedule = rem.get("schedule") or {}
    kelas = f"{schedule.get('nama_kelas', 'tanpa jadwal')} {format_time(schedule.get('waktu_mulai'))}".strip()
    return f"{priority_label(rem.get('priority'))} · {customer} · {kelas} · {rem.get('status')} (#{rem.get('id')})"


def reminder_rows(reminders: list[Mapping]) -> list[dict]:
    """Baris tabel ringkas untuk daftar reminder (urutan dipertahankan dari API)."""
    rows = []
    for rem in reminders:
        schedule = rem.get("schedule") or {}
        probs = rem.get("priority_probabilities") or {}
        rows.append({
            "No": rem.get("id"),
            "Prioritas": priority_label(rem.get("priority")),
            "Peluang High": f"{probs['High']:.0%}" if "High" in probs else "-",
            "Customer": (rem.get("customer") or {}).get("nama", "-"),
            "Kelas": schedule.get("nama_kelas", "-"),
            "Jam": format_time(schedule.get("waktu_mulai")),
            "Jenis pesan": MESSAGE_TYPE_LABEL.get(rem.get("message_type"), rem.get("message_type")),
            "Status": rem.get("status"),
            "Draft": "✓" if rem.get("draft_message") else "",
        })
    return rows


def message_for_editor(rem: Mapping) -> str:
    """Isi awal kotak edit: pesan akhir yang tersimpan, jika belum ada pakai draft."""
    return rem.get("final_message") or rem.get("draft_message") or ""


def combine_wib(d: date, hour: int, minute: int) -> str:
    """ISO waktu naive WIB untuk dikirim ke API (API menganggap waktu tanpa zona = WIB)."""
    return datetime(d.year, d.month, d.day, hour, minute).isoformat()
