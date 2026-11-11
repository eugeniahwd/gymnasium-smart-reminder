"""Penyusun prompt draft pesan WhatsApp (docs/AI_SPEC.md bagian B).

Input berupa struktur data (`DraftContext`), bukan teks mentah. Prinsip penting:
- `top_factors` hanya konteks INTERNAL: diterima di konteks tetapi TIDAK dimasukkan ke prompt (tidak mungkin bocor)
  dan dipakai post-check untuk menolak draft yang memuatnya.
- Label prioritas tidak ditulis mentah ke prompt; diterjemahkan menjadi arahan isi (intensitas pesan).
- Contoh few-shot dirender dengan fungsi yang SAMA dengan data asli agar formatnya konsisten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

PROMPT_VERSION = "v1"

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember"]

PERSONAS = ("ibu-ibu", "lansia", "menengah_atas")
MESSAGE_TYPES = ("reminder_kelas", "follow_up_absen", "follow_up_tidak_merespons")
PRIORITIES = ("Low", "Medium", "High")
DEFAULT_PRIORITY = "Low"  # dipakai bila reminder belum punya prioritas (gaya paling ringan)

# ------------------------------------------------------------------ sapaan
_FEMALE = {"ibu", "bu", "ny", "nyonya", "hj", "hjh", "hajah", "hajjah"}
_MALE = {"bapak", "pak", "bpk", "tn", "tuan", "h", "haji"}
_NEUTRAL_TITLES = {"dr", "prof", "ir", "drs", "dra", "sdr", "sdri"}


@dataclass(frozen=True)
class Salutation:
    sapaan: str  # pembuka pesan, mis. "Bu Sari", "Bapak/Ibu Hendra"
    kata_ganti: str  # rujukan di kalimat, mis. "Ibu", "Bapak", "Bapak/Ibu"
    first_name: str


def derive_salutation(nama: str, persona: str) -> Salutation:
    """Turunkan sapaan dari nama (tanpa menebak jenis kelamin dari nama depan).

    Aturan:
    1. Gelar di depan nama dibuang dan dibaca: Ibu/Bu/Ny./Hj. -> perempuan, Bapak/Pak/Bpk./Tn./H. -> laki-laki.
       Gelar netral (Dr., Prof., Ir., ...) dibuang tanpa menyimpulkan apa pun.
    2. Panggilan = kata pertama sisa nama (mis. "Sari Wijaya" -> "Sari").
    3. Persona ibu-ibu -> "Bu <nama>" (kecuali nama jelas bergelar laki-laki -> "Pak <nama>").
    4. Persona lain: gelar perempuan -> "Ibu <nama>", gelar laki-laki -> "Bapak <nama>",
       jenis kelamin tidak jelas -> "Bapak/Ibu <nama>".
    """
    tokens = (nama or "").split()
    gender: str | None = None
    while tokens:
        key = tokens[0].rstrip(".,").lower()
        if key in _FEMALE:
            gender = gender or "f"
        elif key in _MALE:
            gender = gender or "m"
        elif key not in _NEUTRAL_TITLES:
            break
        tokens.pop(0)
    first = tokens[0].strip(".,") if tokens else ""
    if first.isupper() or first.islower():
        first = first.capitalize()

    if persona == "ibu-ibu":
        honor, ganti = ("Pak", "Bapak") if gender == "m" else ("Bu", "Ibu")
    elif gender == "f":
        honor, ganti = "Ibu", "Ibu"
    elif gender == "m":
        honor, ganti = "Bapak", "Bapak"
    else:
        honor, ganti = "Bapak/Ibu", "Bapak/Ibu"
    return Salutation(sapaan=f"{honor} {first}".strip(), kata_ganti=ganti, first_name=first)


# ------------------------------------------------------------------ format tanggal (tanpa bergantung locale OS)
def format_tanggal(d: date | datetime) -> str:
    """'Jumat, 13 November 2026'."""
    return f"{HARI[d.weekday()]}, {d.day} {BULAN[d.month - 1]} {d.year}"


def format_jam(dt: datetime) -> str:
    """'08.30' (format jam Indonesia)."""
    return f"{dt.hour:02d}.{dt.minute:02d}"


def format_waktu(dt: datetime) -> str:
    """'Jumat, 13 November 2026 pukul 08.30 WIB'."""
    return f"{format_tanggal(dt)} pukul {format_jam(dt)} WIB"


def relative_day(target: date, today: date) -> str | None:
    delta = (target - today).days
    return {0: "hari ini", 1: "besok", -1: "kemarin"}.get(delta)


# ------------------------------------------------------------------ konteks
@dataclass
class DraftContext:
    """Data terstruktur untuk satu draft (AI_SPEC B1)."""

    nama_customer: str
    persona: str
    message_type: str
    now: datetime
    priority: str | None = None
    nama_kelas: str | None = None
    class_type: str | None = None  # group_class | private
    waktu_kelas: datetime | None = None
    pelatih: str | None = None
    tanggal_pesan_terakhir: datetime | None = None
    top_factors: list[str] = field(default_factory=list)  # INTERNAL, tidak masuk prompt

    @property
    def salutation(self) -> Salutation:
        return derive_salutation(self.nama_customer, self.persona)

    @property
    def effective_priority(self) -> str:
        return self.priority if self.priority in PRIORITIES else DEFAULT_PRIORITY

    @property
    def has_class(self) -> bool:
        return bool(self.nama_kelas and self.waktu_kelas)

    @property
    def class_noun(self) -> str:
        return "sesi" if self.class_type == "private" else "kelas"

    @property
    def class_is_past(self) -> bool:
        return bool(self.waktu_kelas and self.waktu_kelas < self.now)


PRIORITY_GUIDANCE = {
    "Low": "Pengingat ringan: sampaikan detail kelas dengan ramah dan singkat. Tidak perlu menanyakan kendala.",
    "Medium": "Pengingat yang hangat: sampaikan detail kelas, lalu tanyakan kabar atau kendala dengan ramah "
              "dalam satu kalimat.",
    "High": "Lebih personal dan proaktif: tanyakan kabar dengan tulus, tawarkan bantuan atau opsi ganti jadwal "
            "(tanpa menyebut jadwal pengganti tertentu), tetap tanpa menekan atau menyalahkan.",
}

MESSAGE_TYPE_GUIDANCE = {
    "reminder_kelas": ("reminder kelas", "Ingatkan kelas yang tercantum."),
    "follow_up_absen": ("follow-up setelah tidak hadir",
                        "Customer tidak hadir di kelas yang tercantum. Sapa dan tanyakan kabar tanpa menyalahkan "
                        "dan tanpa menyebut jumlah ketidakhadiran; tawarkan bantuan bila ingin mengatur jadwal "
                        "pengganti."),
    "follow_up_tidak_merespons": ("follow-up karena pesan sebelumnya belum dibalas",
                                  "Ingatkan kembali dengan sopan dan minta konfirmasi bila berkenan, tanpa menyindir "
                                  "dan tanpa membuat customer merasa bersalah."),
}

PERSONA_LABEL = {
    "ibu-ibu": "ibu-ibu (hangat dan akrab)",
    "lansia": "lansia (sangat sopan, kalimat pendek)",
    "menengah_atas": "menengah_atas (profesional dan ringkas)",
}


def format_data_block(ctx: DraftContext) -> str:
    """Blok DATA PESAN. Tidak memuat top_factors maupun label prioritas mentah."""
    sal = ctx.salutation
    jenis, arahan_jenis = MESSAGE_TYPE_GUIDANCE[ctx.message_type]
    lines = [
        "DATA PESAN",
        f"- Sapaan pembuka: {sal.sapaan}",
        f"- Kata ganti customer: {sal.kata_ganti}",
        f"- Persona: {PERSONA_LABEL.get(ctx.persona, ctx.persona)}",
        f"- Jenis pesan: {jenis}. {arahan_jenis}",
        f"- Arahan isi: {PRIORITY_GUIDANCE[ctx.effective_priority]}",
    ]
    if ctx.has_class:
        tipe = "sesi private" if ctx.class_type == "private" else "kelas grup"
        rel = relative_day(ctx.waktu_kelas.date(), ctx.now.date())
        status = "sudah berlalu" if ctx.class_is_past else "akan datang"
        keterangan = f"{rel}; {status}" if rel else status
        lines += [
            f"- Kelas: {ctx.nama_kelas} ({tipe})",
            f"- Waktu kelas: {format_waktu(ctx.waktu_kelas)} ({keterangan})",
            f"- Pelatih: {ctx.pelatih}" if ctx.pelatih else "- Pelatih: tidak ada data (jangan disebut)",
        ]
    else:
        lines.append("- Kelas: tidak ada data (jangan menyebut nama kelas, tanggal, jam, atau pelatih tertentu)")
    if ctx.tanggal_pesan_terakhir:
        lines.append(f"- Pesan terakhir dari kami: {format_tanggal(ctx.tanggal_pesan_terakhir)}")
    else:
        lines.append("- Pesan terakhir dari kami: tidak ada data (jangan disebut)")
    return "\n".join(lines)


# ------------------------------------------------------------------ few-shot (data contoh fiktif, 2 per persona)
_EX_NOW = datetime(2026, 3, 3, 10, 0)
FEW_SHOT_EXAMPLES: list[tuple[DraftContext, str]] = [
    (DraftContext("Rina Kusnadi", "ibu-ibu", "reminder_kelas", _EX_NOW, "Low", "Stretching Pagi", "group_class",
                  datetime(2026, 3, 4, 7, 30), "Coach Wina"),
     "Halo Bu Rina, semoga sehat dan semangat selalu ya 😊 Kami mau mengingatkan jadwal kelas Stretching Pagi "
     "besok, Rabu, 4 Maret 2026 pukul 07.30 WIB bersama Coach Wina. Kalau ada perubahan rencana atau kendala, "
     "kabari kami saja lewat pesan ini ya, Bu. Kami tunggu kehadirannya, semoga latihannya menyenangkan dan "
     "seru bersama teman-teman lainnya. Sampai ketemu di kelas! Salam hangat, Admin Gymnasium"),
    (DraftContext("Ibu Wulan Sari", "ibu-ibu", "follow_up_absen", _EX_NOW, "High", "Senam Bugar", "group_class",
                  datetime(2026, 3, 2, 9, 0), "Coach Tama", datetime(2026, 2, 27, 15, 0)),
     "Halo Bu Wulan, apa kabar? Kemarin kami tidak bertemu Ibu di kelas Senam Bugar bersama Coach Tama, semoga "
     "Ibu dan keluarga baik-baik saja ya. Kalau sedang sibuk atau ada kendala, tidak apa-apa kok, Bu. Kalau Ibu "
     "mau, kami bisa bantu carikan jadwal pengganti yang lebih pas. Cukup balas pesan ini kapan saja ya, Bu. "
     "Semoga harinya menyenangkan 🙏 Salam hangat, Admin Gymnasium"),
    (DraftContext("Harsono Budiman", "lansia", "reminder_kelas", _EX_NOW, "Medium", "Senam Bugar", "group_class",
                  datetime(2026, 3, 5, 8, 0), "Coach Tama"),
     "Halo Bapak/Ibu Harsono, semoga dalam keadaan baik. Kami ingin mengingatkan kelas Senam Bugar pada hari "
     "Kamis, 5 Maret 2026, pukul 08.00 WIB. Kelas dipandu oleh Coach Tama. Bagaimana kabar Bapak/Ibu belakangan "
     "ini? Bila ada kendala untuk hadir, silakan sampaikan kepada kami. Kami siap membantu dengan senang hati. "
     "Kami senang bisa bertemu Bapak/Ibu lagi di kelas. Terima kasih. Salam hormat, Admin Gymnasium"),
    (DraftContext("Ibu Endang Lestiani", "lansia", "follow_up_tidak_merespons", _EX_NOW, "High", "Yoga Kursi",
                  "group_class", datetime(2026, 3, 4, 8, 30), "Coach Wina", datetime(2026, 3, 2, 9, 0)),
     "Halo Ibu Endang, semoga Ibu sehat selalu. Kami mengirim pesan pada hari Senin, 2 Maret 2026, tentang kelas "
     "Yoga Kursi. Kelas tersebut akan berlangsung besok, Rabu, 4 Maret 2026, pukul 08.30 WIB bersama Coach Wina. "
     "Bila Ibu berkenan hadir, mohon balas pesan ini. Bila waktunya kurang cocok, kami bisa membantu mencari "
     "jadwal lain. Semoga hari Ibu menyenangkan. Terima kasih, Ibu. Salam hormat, Admin Gymnasium"),
    (DraftContext("Ny. Vania Hadiwijaya", "menengah_atas", "reminder_kelas", _EX_NOW, "Low", "Private Coaching",
                  "private", datetime(2026, 3, 3, 18, 30), "Coach Tama"),
     "Halo Ibu Vania, kami ingin mengingatkan sesi Private Coaching hari ini, Selasa, 3 Maret 2026 pukul 18.30 "
     "WIB bersama Coach Tama. Apabila ada perubahan rencana atau Ibu perlu menyesuaikan waktu, silakan balas "
     "pesan ini dan kami akan membantu mengaturnya. Kami harap waktu tersebut masih sesuai dengan agenda Ibu. "
     "Semoga sesi latihannya berjalan lancar. Terima kasih dan sampai bertemu. Salam, Admin Gymnasium"),
    (DraftContext("Santoso Wirawan", "menengah_atas", "follow_up_absen", _EX_NOW, "Medium", "Body Conditioning",
                  "group_class", datetime(2026, 3, 2, 19, 0), "Coach Wina"),
     "Halo Bapak/Ibu Santoso, semoga aktivitasnya lancar. Kami tidak melihat Bapak/Ibu di kelas Body "
     "Conditioning kemarin, Senin, 2 Maret 2026 pukul 19.00 WIB. Semoga semuanya baik. Apakah ada kendala yang "
     "bisa kami bantu? Bila jadwal tersebut kurang sesuai, silakan balas pesan ini dan kami akan membantu "
     "mencari waktu yang lebih cocok. Kami senang bisa kembali menyambut Bapak/Ibu di kelas berikutnya. "
     "Terima kasih. Salam, Admin Gymnasium"),
]

# Nama/kelas/pelatih yang HANYA ada di contoh: jika muncul di draft sungguhan berarti model menyalin contoh.
# "Private Coaching" dikecualikan karena juga nama layanan sungguhan.
EXAMPLE_ONLY_TERMS = sorted({t for ctx, _ in FEW_SHOT_EXAMPLES
                             for t in (ctx.salutation.first_name, ctx.nama_kelas, ctx.pelatih)
                             if t and t != "Private Coaching"})

_RULES = """Kamu adalah admin Gymnasium, tempat gym dan private coaching, yang menulis pesan WhatsApp untuk member.
Tugasmu: tulis SATU pesan WhatsApp berdasarkan DATA PESAN. Admin akan membaca dan mengedit pesanmu sebelum mengirimnya sendiri.

ATURAN UMUM
1. Bahasa Indonesia yang baik dan natural, siap dikirim lewat WhatsApp.
2. Panjang 60-80 kata. Teks biasa tanpa markdown: tanpa tanda bintang, tanpa judul, tanpa daftar berpoin, tanpa tanda kurung siku atau kurawal.
3. Buka dengan "Halo" diikuti sapaan pembuka persis seperti di DATA PESAN. Jangan memakai salam waktu (selamat pagi/siang/sore/malam) karena jam kirim belum pasti.
4. Sebut nama kelas, tanggal, jam, dan pelatih persis seperti di DATA PESAN. Kata "hari ini", "besok", atau "kemarin" hanya boleh dipakai jika tercantum di DATA PESAN.
5. Akhiri dengan salam penutup "Salam hangat, Admin Gymnasium" (ibu-ibu), "Salam hormat, Admin Gymnasium" (lansia), atau "Salam, Admin Gymnasium" (menengah_atas).
6. Tulis hanya isi pesan, tanpa pengantar, judul, atau penjelasan.

GAYA PER PERSONA
- ibu-ibu: hangat dan akrab, sapaan "Bu"/"Ibu", emoji maksimal 2.
- lansia: sangat sopan, kalimat pendek dan jelas, tanpa singkatan dan tanpa istilah asing, sebaiknya tanpa emoji (maksimal 1), tidak terkesan terburu-buru.
- menengah_atas: profesional, ringkas, sopan, emoji maksimal 1.

LARANGAN KERAS
1. Jangan menyebut prioritas, kategori, risiko, skor, model, AI, analisis, prediksi, persentase, atau data internal apa pun.
2. Jangan menyebut jumlah absen atau ketidakhadiran, dan jangan bernada menyalahkan atau menghakimi.
3. Jangan mengarang fakta: jangan menyebut harga, promo, diskon, hadiah, jadwal, tanggal, jam, atau nama yang tidak ada di DATA PESAN. Jika suatu data tidak ada, jangan disebut.
4. Jangan memberi klaim kesehatan atau medis (misalnya menyembuhkan penyakit atau menurunkan tekanan darah).
5. Jangan memakai nada rasa bersalah atau urgensi palsu (misalnya "kesempatan terakhir", "jangan sampai rugi").
6. Jangan menyebut kata "lansia", "persona", atau label kelompok customer lainnya."""


def build_system_instruction() -> str:
    """System instruction lengkap: aturan + contoh few-shot (2 per persona)."""
    parts = [_RULES, "", "CONTOH (data contoh fiktif; JANGAN menyalin nama, kelas, pelatih, atau waktunya)"]
    for i, (ctx, message) in enumerate(FEW_SHOT_EXAMPLES, start=1):
        parts += ["", f"Contoh {i}", format_data_block(ctx), "PESAN:", message]
    return "\n".join(parts)


SYSTEM_INSTRUCTION = build_system_instruction()


def build_prompt(ctx: DraftContext, rejected_reasons: list[str] | None = None) -> str:
    """Prompt per permintaan. `rejected_reasons` diisi saat regenerasi setelah post-check gagal."""
    prompt = f"{format_data_block(ctx)}\n\nTulis PESAN untuk DATA PESAN di atas."
    if rejected_reasons:
        prompt += ("\n\nCATATAN: pesan sebelumnya ditolak pemeriksaan otomatis karena: "
                   + "; ".join(rejected_reasons) + ". Tulis ulang pesan yang memenuhi SEMUA aturan.")
    return prompt
