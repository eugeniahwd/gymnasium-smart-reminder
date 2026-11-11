"""Post-check draft pesan (AI_SPEC B3): tolak output yang melanggar aturan sebelum disimpan/ditampilkan.

`check_draft` mengembalikan daftar alasan pelanggaran (bahasa Indonesia); daftar kosong = lolos.
Fakta yang memang diberikan (nama kelas, pelatih, nama customer) di-"mask" lebih dulu agar, misalnya, kelas
"Aerobic Low Impact" atau "Senam Ringan Lansia" tidak dianggap kebocoran label.
"""
from __future__ import annotations

import re

from src.api.services.prompt_builder import BULAN, EXAMPLE_ONLY_TERMS, HARI, DraftContext

MIN_WORDS = 15
MAX_WORDS = 100  # target 60-80 kata; toleransi agar variasi wajar tidak langsung ditolak
MAX_CHARS = 700
MAX_EMOJI = {"ibu-ibu": 2, "lansia": 1, "menengah_atas": 1}

_I = re.IGNORECASE
# (pola, alasan). Dicek pada teks yang fakta-fakta datanya sudah di-mask.
FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 1. label internal / AI
    (re.compile(r"\bprioritas\w*|\bpriorit(y|ies)\b", _I), "menyebut prioritas"),
    (re.compile(r"\b(be)?r[ie]siko\w*|\brisk\w*", _I), "menyebut risiko"),
    (re.compile(r"\bA\.?I\b"), "menyebut AI"),
    (re.compile(r"\b(kecerdasan buatan|artificial intelligence|machine learning|algoritm\w*|chatbot|gemini)\b", _I),
     "menyebut AI/teknologi"),
    (re.compile(r"\bmodel\b", _I), "menyebut model"),
    (re.compile(r"\b(skor|score|probabilitas|probability|prediksi\w*|analisis|analisa\w*|klasifikasi)\b", _I),
     "menyebut skor/analisis internal"),
    (re.compile(r"\b(high|medium|low)\b", _I), "menyebut label prioritas"),
    (re.compile(r"\b(lansia|lanjut usia|menengah[ _]atas|persona|segmen|kategori)\b", _I),
     "menyebut label kelompok customer"),
    (re.compile(r"\bdraf(t)?\b|\bberikut (adalah )?(pesan|contoh)", _I), "memuat pengantar/penjelasan, bukan isi pesan"),
    # 2. kebocoran top_factors / jumlah absen
    (re.compile(r"%|\bpersen\b", _I), "menyebut persentase"),
    (re.compile(r"\babsen\w*\s+berturut|\bberturut-turut\b|\btingkat kehadiran\b|\bdirespons\b", _I),
     "menyebut statistik kehadiran/respons"),
    (re.compile(r"\b(\d+|dua|tiga|empat|lima|enam|tujuh|beberapa)\s*(kali|x)\s*(absen|tidak hadir|tidak datang|"
                r"melewatkan|reschedule|tidak (mem)?balas)", _I), "menyebut jumlah absen/kejadian"),
    (re.compile(r"\bselama\s+\d+\s+hari\b", _I), "menyebut lama tidak hadir"),
    # 3. fakta karangan: harga/promo
    (re.compile(r"\b(promo\w*|diskon\w*|gratis|harga|potongan|cashback|voucher|hadiah|biaya)\b|\bRp\.?\s?\d", _I),
     "menyebut harga/promo"),
    # 4. klaim kesehatan/medis
    (re.compile(r"\b(menyembuhkan|obat|terapi|diabetes|kolesterol|hipertensi|tekanan darah|gula darah|asam urat|"
                r"osteoporosis|dijamin|menjamin)\b", _I), "memuat klaim kesehatan/medis"),
    # 5. rasa bersalah / urgensi palsu
    (re.compile(r"\b(kesempatan terakhir|jangan sampai (rugi|ketinggalan|terlewat)|rugi|kecewa\w*|menyesal|"
                r"wajib hadir|harus hadir|sekarang juga|batas waktu|mengecewakan)\b", _I),
     "bernada menekan/rasa bersalah"),
    # singkatan informal (terutama tidak cocok untuk lansia)
    (re.compile(r"\b(yg|dgn|utk|tdk|krn|sdh|blm|tsb|dll|dsb|mksh|trims|thx|bpk)\b", _I), "memakai singkatan"),
]

_MARKDOWN = re.compile(r"\*|__|```|\]\(|^\s*#|^\s*[-•]\s", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[^>]+>")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")
_TIME = re.compile(r"(?<![\d.,:])([01]?\d|2[0-3])[.:]([0-5]\d)(?![\d.,:]?\d)")
_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(BULAN) + r")\b", _I)
_WEEKDAY = re.compile(r"\b(" + "|".join(h for h in HARI if h != "Minggu") + r")\b", _I)  # "minggu" = pekan juga


def count_words(text: str) -> int:
    return len(text.split())


def count_emoji(text: str) -> int:
    return len(_EMOJI.findall(text))


def clean_output(text: str | None) -> str:
    """Rapikan output model: buang spasi berlebih dan tanda kutip pembungkus. Tidak mengubah isi."""
    out = (text or "").replace("\r\n", "\n").strip()
    if len(out) >= 2 and out[0] in "\"'“" and out[-1] in "\"'”":
        out = out[1:-1].strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return "\n".join(line.rstrip() for line in out.split("\n"))


def _mask_known_facts(text: str, ctx: DraftContext) -> str:
    facts = [ctx.nama_kelas, ctx.pelatih, ctx.salutation.first_name, ctx.nama_customer]
    for fact in sorted((f for f in facts if f), key=len, reverse=True):
        text = re.sub(re.escape(fact), " ", text, flags=_I)
    return text


def _allowed_dates(ctx: DraftContext) -> tuple[set[tuple[int, int]], set[str]]:
    days = [d for d in (ctx.waktu_kelas, ctx.tanggal_pesan_terakhir, ctx.now) if d]
    return {(d.day, d.month) for d in days}, {HARI[d.weekday()].lower() for d in days}


def check_draft(text: str, ctx: DraftContext) -> list[str]:
    """Kembalikan alasan pelanggaran (kosong = lolos)."""
    if not text or not text.strip():
        return ["respons kosong"]
    reasons: list[str] = []
    words = count_words(text)
    if words > MAX_WORDS or len(text) > MAX_CHARS:
        reasons.append(f"terlalu panjang ({words} kata; maksimal {MAX_WORDS})")
    elif words < MIN_WORDS:
        reasons.append(f"terlalu pendek ({words} kata; minimal {MIN_WORDS})")
    if _MARKDOWN.search(text):
        reasons.append("memakai format markdown")
    if _PLACEHOLDER.search(text):
        reasons.append("memuat placeholder/kurung siku atau kurawal")
    emoji = count_emoji(text)
    if emoji > MAX_EMOJI.get(ctx.persona, 1):
        reasons.append(f"emoji terlalu banyak ({emoji}; maksimal {MAX_EMOJI.get(ctx.persona, 1)})")

    masked = _mask_known_facts(text, ctx)
    for pattern, reason in FORBIDDEN_PATTERNS:
        match = pattern.search(masked)
        if match:
            reasons.append(f"{reason} ('{match.group(0).strip()}')")
    lowered = text.lower()
    for factor in ctx.top_factors:
        if factor and factor.lower() in lowered:
            reasons.append("memuat alasan prioritas internal")
            break
    copied = [t for t in EXAMPLE_ONLY_TERMS if t and re.search(rf"\b{re.escape(t)}\b", masked, _I)]
    if copied:
        reasons.append(f"menyalin data contoh ({', '.join(copied)})")

    # Jadwal karangan: jam/tanggal/hari yang disebut harus berasal dari data.
    allowed_days, allowed_weekdays = _allowed_dates(ctx)
    allowed_time = (ctx.waktu_kelas.hour, ctx.waktu_kelas.minute) if ctx.waktu_kelas else None
    for h, m in _TIME.findall(text):
        if (int(h), int(m)) != allowed_time:
            reasons.append(f"menyebut jam yang tidak ada di data ({h}.{m})")
            break
    for day, month in _DATE.findall(text):
        if (int(day), BULAN.index(month.capitalize()) + 1) not in allowed_days:
            reasons.append(f"menyebut tanggal yang tidak ada di data ({day} {month})")
            break
    for weekday in _WEEKDAY.findall(text):
        if weekday.lower() not in allowed_weekdays:
            reasons.append(f"menyebut hari yang tidak ada di data ({weekday})")
            break
    if ctx.has_class and ctx.nama_kelas.lower() not in lowered:
        reasons.append(f"tidak menyebut nama kelas '{ctx.nama_kelas}'")
    return reasons
