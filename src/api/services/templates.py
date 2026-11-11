"""Template statis cadangan (fallback) per persona x message_type.

Dipakai jika Gemini gagal / key kosong / output tidak lolos post-check, sehingga admin SELALU punya draft.
Template tidak bergantung pada prioritas dan hanya memakai data yang tersedia (tanpa fakta tambahan).
Placeholder: {sapaan}, {kata_ganti}, {info_kelas}.
"""
from __future__ import annotations

from src.api.services.prompt_builder import DraftContext, format_waktu

TEMPLATES: dict[tuple[str, str], str] = {
    # ---------------------------------------------------------------- ibu-ibu: hangat, akrab, emoji <= 2
    ("ibu-ibu", "reminder_kelas"):
        "Halo {sapaan}, semoga sehat dan semangat selalu ya 😊 Kami mau mengingatkan {info_kelas}. "
        "Kalau ada kendala atau ingin ganti jadwal, kabari kami saja lewat pesan ini ya. "
        "Sampai ketemu di kelas! Salam hangat, Admin Gymnasium",
    ("ibu-ibu", "follow_up_absen"):
        "Halo {sapaan}, apa kabar? Kami tidak bertemu {kata_ganti} di {info_kelas}, semoga {kata_ganti} dan "
        "keluarga baik-baik saja ya 😊 Kalau {kata_ganti} mau, kami bisa bantu atur jadwal pengganti. "
        "Cukup balas pesan ini kapan saja ya. Salam hangat, Admin Gymnasium",
    ("ibu-ibu", "follow_up_tidak_merespons"):
        "Halo {sapaan}, semoga harinya menyenangkan ya 😊 Kami ingin memastikan info {info_kelas} sudah "
        "{kata_ganti} terima. Kalau berkenan, balas pesan ini untuk konfirmasi, atau kabari kami bila ingin "
        "ganti jadwal. Terima kasih banyak ya. Salam hangat, Admin Gymnasium",
    # ---------------------------------------------------------------- lansia: sangat sopan, kalimat pendek, tanpa emoji
    ("lansia", "reminder_kelas"):
        "Halo {sapaan}, semoga dalam keadaan baik. Kami ingin mengingatkan {info_kelas}. "
        "Silakan datang dengan santai, tidak perlu terburu-buru. Bila ada kendala atau ingin mengganti "
        "jadwal, {kata_ganti} cukup membalas pesan ini. Terima kasih. Salam hormat, Admin Gymnasium",
    ("lansia", "follow_up_absen"):
        "Halo {sapaan}, semoga dalam keadaan baik. Kami tidak bertemu {kata_ganti} di {info_kelas}. "
        "Kami hanya ingin menanyakan kabar. Bila {kata_ganti} ingin mengatur jadwal pengganti, kami siap "
        "membantu. Cukup balas pesan ini kapan saja. Terima kasih. Salam hormat, Admin Gymnasium",
    ("lansia", "follow_up_tidak_merespons"):
        "Halo {sapaan}, semoga dalam keadaan baik. Kami ingin memastikan {kata_ganti} sudah menerima "
        "informasi {info_kelas}. Bila berkenan, mohon balas pesan ini untuk konfirmasi. Bila ingin mengganti "
        "jadwal, kami siap membantu. Terima kasih. Salam hormat, Admin Gymnasium",
    # ---------------------------------------------------------------- menengah_atas: profesional, ringkas
    ("menengah_atas", "reminder_kelas"):
        "Halo {sapaan}, kami ingin mengingatkan {info_kelas}. Apabila ada perubahan rencana atau perlu "
        "penyesuaian jadwal, silakan balas pesan ini dan kami akan membantu. Terima kasih dan sampai "
        "bertemu. Salam, Admin Gymnasium",
    ("menengah_atas", "follow_up_absen"):
        "Halo {sapaan}, semoga semuanya lancar. Kami tidak melihat {kata_ganti} di {info_kelas}. "
        "Apabila {kata_ganti} ingin menjadwalkan sesi pengganti, silakan balas pesan ini dan kami akan "
        "membantu mengaturnya. Terima kasih. Salam, Admin Gymnasium",
    ("menengah_atas", "follow_up_tidak_merespons"):
        "Halo {sapaan}, kami ingin memastikan informasi {info_kelas} sudah diterima. Mohon konfirmasi "
        "kehadiran dengan membalas pesan ini, atau beri tahu kami bila perlu penyesuaian jadwal. "
        "Terima kasih. Salam, Admin Gymnasium",
}

# Frasa info kelas per message_type: (dengan data jadwal, tanpa data jadwal)
_INFO_KELAS: dict[str, tuple[str, str]] = {
    "reminder_kelas": ("jadwal {noun} {nama_kelas} bersama {pelatih} pada {waktu}", "jadwal kelas berikutnya"),
    "follow_up_absen": ("{noun} {nama_kelas} bersama {pelatih} pada {waktu}", "kelas sebelumnya"),
    "follow_up_tidak_merespons": ("jadwal {noun} {nama_kelas} bersama {pelatih} pada {waktu}",
                                  "jadwal kelas berikutnya"),
}


def info_kelas(ctx: DraftContext) -> str:
    with_class, without_class = _INFO_KELAS[ctx.message_type]
    if not ctx.has_class:
        return without_class
    text = with_class.format(noun=ctx.class_noun, nama_kelas=ctx.nama_kelas, pelatih=ctx.pelatih or "",
                             waktu=format_waktu(ctx.waktu_kelas))
    return text if ctx.pelatih else text.replace(" bersama  pada", " pada")


def render_template(ctx: DraftContext) -> str:
    """Draft cadangan untuk konteks ini (KeyError jika kombinasi persona x message_type tidak dikenal)."""
    template = TEMPLATES[(ctx.persona, ctx.message_type)]
    sal = ctx.salutation
    return template.format(sapaan=sal.sapaan, kata_ganti=sal.kata_ganti, info_kelas=info_kelas(ctx))
