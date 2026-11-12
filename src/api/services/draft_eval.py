"""Evaluasi kualitas draft: 9 skenario (3 persona x 3 prioritas) -> tabel Markdown dengan kolom rubrik kosong.

Dijalankan oleh PEMILIK dengan API key asli (data skenario 100% synthetic). Dari root repo (PowerShell):

    .\\.venv\\Scripts\\Activate.ps1
    python -m src.api.services.draft_eval              # memanggil Gemini (butuh GEMINI_API_KEY di .env)
    python -m src.api.services.draft_eval --dry-run    # tanpa Gemini (template), hanya untuk cek format

Hasil ditulis ke docs/draft_eval/draft_eval_<versi-prompt>_<tanggal-jam>.md. Nilai rubrik 1-5 diisi MANUAL di
bagian "Lembar nilai", lalu rata-ratanya dihitung dengan:

    python -m src.api.services.draft_eval --summarize docs\\draft_eval\\<nama-file>.md
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from src.api.config import ROOT, get_settings
from src.api.services.draft_service import compose_draft
from src.api.services.gemini_client import DraftGenerator, build_draft_generator
from src.api.services.prompt_builder import (MESSAGE_TYPES, PERSONAS, PRIORITIES, PROMPT_VERSION, DraftContext,
                                             build_prompt, format_tanggal, format_waktu)
from src.api.timeutil import now_wib

# Prioritas -> jenis pesan yang paling khas, agar 9 skenario juga mencakup ketiga jenis pesan.
SCENARIO_MESSAGE_TYPE = {"Low": "reminder_kelas", "Medium": "follow_up_tidak_merespons", "High": "follow_up_absen"}
SCENARIO_CUSTOMER = {"ibu-ibu": "Sari Wijaya", "lansia": "Bambang Hartono", "menengah_atas": "Ny. Linda Tanujaya"}
SCENARIO_CLASS = {  # (nama_kelas, tipe, pelatih) - dari katalog kelas synthetic
    "ibu-ibu": ("Zumba Fun", "group_class", "Coach Dina"),
    "lansia": ("Senam Sehat Lansia", "group_class", "Coach Budi"),
    "menengah_atas": ("Private Coaching", "private", "Coach Andra"),
}
SCENARIO_TOP_FACTORS = {  # konteks internal; TIDAK boleh muncul di draft
    "Low": [],
    "Medium": ["2 reminder terakhir tidak direspons", "jarang merespons reminder (40% direspons)"],
    "High": ["3 absen berturut-turut", "tingkat kehadiran 30 hari: 25%"],
}
RUBRIC = ["Nada (1-5)", "Info kelas (1-5)", "Tanpa kebocoran label (1-5)", "Tanpa fakta karangan (1-5)",
          "Siap kirim (1-5)"]


@dataclass
class Scenario:
    no: int
    persona: str
    priority: str
    ctx: DraftContext


def build_scenarios(now: datetime, message_type: str | None = None) -> list[Scenario]:
    out: list[Scenario] = []
    for persona in PERSONAS:
        for priority in PRIORITIES:
            mtype = message_type or SCENARIO_MESSAGE_TYPE[priority]
            past = mtype == "follow_up_absen"
            base = now - timedelta(days=1) if past else now + timedelta(days=1)
            kelas, tipe, pelatih = SCENARIO_CLASS[persona]
            out.append(Scenario(len(out) + 1, persona, priority, DraftContext(
                nama_customer=SCENARIO_CUSTOMER[persona], persona=persona, message_type=mtype, now=now,
                priority=priority, nama_kelas=kelas, class_type=tipe,
                waktu_kelas=base.replace(hour=9, minute=0, second=0, microsecond=0), pelatih=pelatih,
                tanggal_pesan_terakhir=(now - timedelta(days=2)) if priority != "Low" else None,
                top_factors=list(SCENARIO_TOP_FACTORS[priority]))))
    return out


def run_eval(generator: DraftGenerator | None, now: datetime | None = None, message_type: str | None = None,
             delay: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    rows = []
    scenarios = build_scenarios(now or now_wib(), message_type)
    for i, sc in enumerate(scenarios):
        if i and delay and generator is not None:
            sleep(delay)  # jaga batas request per menit free tier
        res = compose_draft(sc.ctx, generator)
        rows.append({"scenario": sc, "result": res})
        print(f"[{sc.no}/{len(scenarios)}] {sc.persona} / {sc.priority} -> {res.source} ({res.attempts} panggilan)")
    return rows


def _cell(text: str) -> str:
    return (text or "-").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _input_summary(ctx: DraftContext) -> str:
    parts = [f"Sapaan: {ctx.salutation.sapaan}", f"Jenis: {ctx.message_type}",
             f"Kelas: {ctx.nama_kelas}, {format_waktu(ctx.waktu_kelas)}", f"Pelatih: {ctx.pelatih}",
             f"Pesan terakhir: {format_tanggal(ctx.tanggal_pesan_terakhir) if ctx.tanggal_pesan_terakhir else '-'}",
             f"top_factors (internal): {', '.join(ctx.top_factors) or '-'}"]
    return "<br>".join(_cell(p) for p in parts)


SHEET_HEADING = "## Lembar nilai (ISI DI SINI)"
RUBRIC_GUIDE = [
    "Ketik satu angka 1-5 di setiap sel kosong (1 = buruk, 5 = sangat baik). Kolom Catatan boleh dikosongkan.",
    "Baca draft di tabel **Hasil** di atas (cocokkan lewat kolom No), lalu nilai dengan panduan ini:",
    "",
    "| Kolom | 5 | 3 | 1 |",
    "|---|---|---|---|",
    "| Nada | Gaya pas dengan persona dan prioritas, hangat/sopan, tidak menekan | Umumnya pas, ada bagian kaku, "
    "terlalu santai, atau berlebihan | Menyalahkan, menekan, atau tidak sopan |",
    "| Info kelas | Nama kelas, hari/tanggal, jam, dan pelatih benar dan jelas | Ada yang kurang jelas atau "
    "terlewat | Salah atau tidak ada |",
    "| Tanpa kebocoran label | Tidak menyebut prioritas/risiko/AI/skor/statistik absen/label persona | "
    "Ada sindiran samar | Jelas menyebut label atau data internal |",
    "| Tanpa fakta karangan | Semua isi berasal dari data | Ada tambahan kecil yang tidak berbahaya | "
    "Mengarang jadwal, harga, promo, atau klaim kesehatan |",
    "| Siap kirim | Bisa langsung dikirim (4 = edit 1-2 kata) | Perlu edit satu kalimat (2 = edit banyak) | "
    "Harus ditulis ulang |",
    "",
    "Setelah semua terisi, hitung rata-rata otomatis (PowerShell):",
    "`python -m src.api.services.draft_eval --summarize <path file ini>`",
]


def scoring_sheet(entries: list[tuple[int, str, str, str]]) -> list[str]:
    """Tabel nilai ringkas: satu baris per skenario (no, persona, prioritas, jenis pesan), sel nilai kosong."""
    lines = [SHEET_HEADING, "", *RUBRIC_GUIDE, "",
             "| No | Persona | Prioritas | Jenis pesan | " + " | ".join(RUBRIC) + " | Catatan |",
             "|---|---|---|---|" + "---|" * (len(RUBRIC) + 1)]
    for no, persona, priority, mtype in entries:
        lines.append(f"| {no} | {persona} | {priority} | {mtype} |" + "  |" * (len(RUBRIC) + 1))
    return lines


def to_markdown(rows: list[dict], model: str, temperature: float | None, dry_run: bool, now: datetime) -> str:
    gem = sum(r["result"].source == "gemini" for r in rows)
    lines = [
        f"# Evaluasi draft pesan - prompt {PROMPT_VERSION}",
        "",
        "> PROTOTYPE - seluruh skenario memakai data **synthetic**. Nilai rubrik diisi MANUAL oleh evaluator di "
        "bagian **Lembar nilai** di bawah. Jangan mengubah kolom Output.",
        "",
        f"- Waktu jalan: {now:%Y-%m-%d %H:%M} WIB",
        f"- Model: {'(dry-run, tanpa Gemini)' if dry_run else model}",
        f"- Temperature: {'-' if dry_run else temperature}",
        f"- Versi prompt: {PROMPT_VERSION}",
        f"- Sumber draft: {gem} gemini, {len(rows) - gem} template_fallback dari {len(rows)} skenario",
        "",
        "## Hasil",
        "",
        "| No | Persona | Prioritas | Input | Output | Sumber | Catatan sistem |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        sc, res = r["scenario"], r["result"]
        notes = [f"{res.attempts} panggilan"]
        notes += [f"ditolak post-check: {'; '.join(x)}" for x in res.rejected_reasons]
        if res.warning:
            notes.append(f"warning: {res.warning}")
        lines.append(f"| {sc.no} | {sc.persona} | {sc.priority} | {_input_summary(sc.ctx)} | {_cell(res.text)} | "
                     f"{res.source} | {_cell('<br>'.join(notes))} |")
    entries = [(r["scenario"].no, r["scenario"].persona, r["scenario"].priority, r["scenario"].ctx.message_type)
               for r in rows]
    lines += [
        "",
        *scoring_sheet(entries),
        "",
        "## Ringkasan (isi manual)",
        "",
        "- Rata-rata per kolom rubrik: (tempel hasil perintah --summarize)",
        "- Masalah yang ditemukan: ...",
        "- Perbaikan untuk versi prompt berikutnya: ...",
        "",
        "## Lampiran: prompt skenario 1 (system instruction ada di src/api/services/prompt_builder.py)",
        "",
        "```text",
        build_prompt(rows[0]["scenario"].ctx) if rows else "",
        "```",
        "",
    ]
    return "\n".join(lines)


def summarize(text: str) -> tuple[dict[str, float | None], int, int, list[str]]:
    """Baca Lembar nilai -> (rata-rata per kolom, baris terisi lengkap, total baris, daftar kesalahan isian)."""
    lines = text.splitlines()
    try:
        start = lines.index(SHEET_HEADING)
    except ValueError:
        return {}, 0, 0, [f"Bagian '{SHEET_HEADING}' tidak ditemukan di file."]
    values: dict[str, list[int]] = {col: [] for col in RUBRIC}
    errors: list[str] = []
    total = complete = 0
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("| ") or not cells[0].isdigit():
            continue
        total += 1
        filled = 0
        for col, raw in zip(RUBRIC, cells[4:4 + len(RUBRIC)]):
            if not raw:
                continue
            if raw in {"1", "2", "3", "4", "5"}:
                values[col].append(int(raw))
                filled += 1
            else:
                errors.append(f"Baris No {cells[0]}, kolom '{col}': '{raw}' bukan angka 1-5.")
        complete += filled == len(RUBRIC)
    means = {col: (round(sum(v) / len(v), 2) if v else None) for col, v in values.items()}
    return means, complete, total, errors


def _print_summary(path: Path) -> int:
    means, complete, total, errors = summarize(path.read_text(encoding="utf-8"))
    for err in errors:
        print(err, file=sys.stderr)
    if not total:
        return 1
    print(f"Baris terisi lengkap: {complete}/{total}\n")
    print("| Kolom rubrik | Rata-rata |\n|---|---|")
    for col, mean in means.items():
        print(f"| {col} | {'-' if mean is None else f'{mean:.2f}'} |")
    filled = [m for m in means.values() if m is not None]
    if filled:
        print(f"| **Rata-rata seluruh kolom** | **{sum(filled) / len(filled):.2f}** |")
    print("\nSalin tabel di atas ke bagian 'Ringkasan' di file evaluasi.")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluasi 9 skenario draft pesan (3 persona x 3 prioritas).")
    parser.add_argument("--dry-run", action="store_true", help="Tanpa memanggil Gemini (memakai template).")
    parser.add_argument("--delay", type=float, default=5.0, help="Jeda antar-skenario (detik). Default 5.")
    parser.add_argument("--message-type", choices=MESSAGE_TYPES, default=None,
                        help="Paksa satu jenis pesan untuk semua skenario (default: dipetakan dari prioritas).")
    parser.add_argument("--out", type=Path, default=None, help="Path file Markdown keluaran.")
    parser.add_argument("--summarize", type=Path, default=None, metavar="FILE",
                        help="Hitung rata-rata rubrik dari Lembar nilai di FILE (tanpa memanggil Gemini).")
    args = parser.parse_args(argv)

    if args.summarize:
        return _print_summary(args.summarize)
    settings = get_settings()
    if not args.dry_run and not settings.gemini_api_key:
        print("GEMINI_API_KEY belum diisi di .env. Isi dulu, atau jalankan dengan --dry-run.", file=sys.stderr)
        return 2
    generator = None if args.dry_run else build_draft_generator(settings)
    now = now_wib()
    rows = run_eval(generator, now, args.message_type, delay=args.delay)
    out = args.out or ROOT / "docs" / "draft_eval" / f"draft_eval_{PROMPT_VERSION}_{now:%Y%m%d_%H%M}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_markdown(rows, settings.effective_gemini_model, settings.gemini_temperature, args.dry_run, now),
                   encoding="utf-8")
    print(f"\nHasil ditulis ke: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
