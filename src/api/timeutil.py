"""Utilitas waktu. Semua waktu di database = waktu lokal WIB tanpa zona (naive)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    _WIB = ZoneInfo("Asia/Jakarta")
except Exception:  # tzdata tidak tersedia -> WIB = UTC+7 tetap (Indonesia tanpa DST)
    _WIB = timezone(timedelta(hours=7))


def now_wib() -> datetime:
    """Waktu sekarang di WIB sebagai datetime naive."""
    return datetime.now(_WIB).replace(tzinfo=None, microsecond=0)


def today_wib() -> date:
    return now_wib().date()


def to_naive_wib(dt: datetime) -> datetime:
    """Datetime ber-zona -> WIB naive; datetime naive dianggap sudah WIB."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_WIB).replace(tzinfo=None)


def mask_phone(number: str | None) -> str:
    """Samarkan nomor untuk log: 628990000001 -> 6289****0001."""
    if not number or len(number) < 8:
        return "****"
    return f"{number[:4]}****{number[-4:]}"
