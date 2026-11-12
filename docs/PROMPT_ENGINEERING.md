# Prompt Engineering — Draft Pesan WhatsApp (Gemini)

> **PROTOTYPE.** Semua data customer adalah **synthetic**. Draft dibuat oleh Generative AI (Gemini) dan **tidak
> pernah dikirim otomatis**: admin membaca, mengedit, lalu mengirim sendiri lewat WhatsApp.

Spesifikasi yang mengikat: `docs/AI_SPEC.md` bagian B. Kode: `src/api/services/`
(`prompt_builder.py`, `gemini_client.py`, `post_check.py`, `templates.py`, `draft_service.py`, `draft_eval.py`).
Versi prompt saat ini: **v2** (`PROMPT_VERSION` di `prompt_builder.py`). Perubahan dari v1 dan alasannya: bagian 10.

## 1. Alur `POST /generate-draft`

```mermaid
flowchart TD
    A[POST /generate-draft] --> B{Reminder ada?}
    B -- tidak --> E404[404 not_found]
    B -- ya --> C{Status Scheduled?}
    C -- tidak --> E409[409 draft_not_allowed]
    C -- ya --> D{Draft tersimpan dan regenerate=false?}
    D -- ya --> CACHE[Kembalikan draft tersimpan, cached=true, tanpa memanggil Gemini]
    D -- tidak --> K{GEMINI_API_KEY ada?}
    K -- tidak --> T[Template cadangan + warning]
    K -- ya --> G[Gemini: system instruction + DATA PESAN]
    G -- error 429/5xx/timeout setelah retry --> T
    G --> P{Post-check lolos?}
    P -- ya --> S[draft_source = gemini]
    P -- tidak --> R[Regenerasi 1x dengan alasan penolakan]
    R --> P2{Post-check lolos?}
    P2 -- ya --> S
    P2 -- tidak --> T
    S --> SAVE[Simpan draft_message + draft_source, final_message TIDAK disentuh]
    T --> SAVE
```

Respons selalu **HTTP 200** kecuali 404/409, sehingga admin **selalu punya draft**:

```json
{"reminder_id": 12, "draft_message": "Halo Bu Sari, ...", "draft_source": "gemini",
 "cached": false, "message_type": "reminder_kelas", "warning": null}
```

## 2. Input ke prompt builder (AI_SPEC B1)

| Field spesifikasi | Sumber data | Masuk prompt? |
|---|---|---|
| `nama_customer` | `customers.nama` → diturunkan menjadi sapaan (bagian 4) | Hanya sapaan (nama depan + gelar) |
| `persona` | `customers.persona` | Ya |
| `priority` | `reminders.priority` (kosong → gaya `Low` + warning) | Tidak mentah; diterjemahkan menjadi **arahan isi** |
| `top_factors` | prediksi terakhir di tabel `predictions` | **Tidak.** Hanya dipakai post-check untuk menolak kebocoran |
| `nama_kelas`, `tanggal_jam`, `pelatih` | `schedules` (boleh kosong) | Ya; jika kosong prompt melarang menyebut jadwal |
| `tipe_pesan` | `reminders.message_type` | Ya, beserta arahannya |
| `tanggal_pesan_terakhir` | `sent_at` terbaru dari reminder lain milik customer | Ya, **hanya sebagai konteks** (v2: dilarang ditulis di pesan; post-check menolak tanggalnya) |

Nomor WhatsApp dan catatan customer **tidak pernah** dikirim ke Gemini.

**Arahan isi per prioritas** (label `Low/Medium/High` tidak ditulis ke prompt agar tidak bocor):

| Prioritas | Arahan isi di prompt |
|---|---|
| Low | Pengingat ringan: sampaikan detail kelas dengan ramah dan singkat. Tidak perlu menanyakan kendala. |
| Medium | Pengingat yang hangat: sampaikan detail kelas, lalu tanyakan kabar atau kendala dengan ramah dalam satu kalimat. |
| High | Lebih personal dan proaktif: tanyakan kabar dengan tulus, tawarkan bantuan atau opsi ganti jadwal (tanpa menyebut jadwal pengganti tertentu), tetap tanpa menekan atau menyalahkan. |

**Arahan per jenis pesan:** `reminder_kelas` = ingatkan kelas; `follow_up_absen` = customer tidak hadir di kelas
yang tercantum, tanyakan kabar tanpa menyalahkan dan tanpa menyebut jumlah ketidakhadiran, tawarkan bantuan jadwal
pengganti; `follow_up_tidak_merespons` = ingatkan kembali dengan sopan, minta konfirmasi bila berkenan, tanpa
menyindir. Prompt juga menyebut apakah kelas **akan datang/sudah berlalu** dan label **hari ini/besok/kemarin**
yang dihitung di backend, agar model tidak menebak tanggal relatif.

## 3. Template prompt (v2)

Gemini menerima dua bagian: **system instruction** (aturan + 6 contoh few-shot) dan **prompt per permintaan**
(blok `DATA PESAN`). Parameter: `temperature` dari `GEMINI_TEMPERATURE` (default 0,7).

### 3.1 Aturan (bagian awal system instruction, disalin persis dari kode)

```text
Kamu adalah admin Gymnasium, tempat gym dan private coaching, yang menulis pesan WhatsApp untuk member.
Tugasmu: tulis SATU pesan WhatsApp berdasarkan DATA PESAN. Admin akan membaca dan mengedit pesanmu sebelum mengirimnya sendiri.

ATURAN UMUM
1. Bahasa Indonesia yang baik dan natural, siap dikirim lewat WhatsApp.
2. Panjang 60-80 kata. Teks biasa tanpa markdown: tanpa tanda bintang, tanpa judul, tanpa daftar berpoin, tanpa tanda kurung siku atau kurawal.
3. Buka dengan "Halo" diikuti sapaan pembuka persis seperti di DATA PESAN. Jangan memakai salam waktu (selamat pagi/siang/sore/malam) karena jam kirim belum pasti.
4. Sebut nama kelas, tanggal, jam, dan pelatih persis seperti di DATA PESAN. Kata "hari ini", "besok", atau "kemarin" hanya boleh dipakai jika tercantum di DATA PESAN.
5. Akhiri dengan salam penutup "Salam hangat, Admin Gymnasium" (ibu-ibu), "Salam hormat, Admin Gymnasium" (lansia), atau "Salam, Admin Gymnasium" (menengah_atas).
6. Tulis hanya isi pesan, tanpa pengantar, judul, atau penjelasan.
7. Setiap kalimat harus lengkap dan punya subjek, misalnya "Kami ingin mengingatkan ...", bukan "Mengingatkan ...".
8. Tanggal pesan terakhir hanya konteks: jangan menulis tanggalnya dan jangan mengungkit bahwa kami sudah atau pernah mengirim pesan. Untuk follow-up karena pesan belum dibalas, cukup tulis "pesan kami sebelumnya" tanpa tanggal.
9. Jangan mengulang harapan atau doa yang sama (misalnya mendoakan sehat dua kali). Kata "semoga" paling banyak 2 kali.

GAYA PER PERSONA
- ibu-ibu: hangat dan akrab, sapaan "Bu"/"Ibu", emoji maksimal 2.
- lansia: sangat sopan, kalimat pendek dan jelas, tanpa singkatan, tanpa istilah asing, dan tanpa partikel santai (ya, kok, nih, dong, sih, deh), sebaiknya tanpa emoji (maksimal 1), tidak terkesan terburu-buru.
- menengah_atas: profesional, ringkas, sopan, tanpa partikel santai (ya, kok, nih, dong, sih, deh), emoji maksimal 1.

LARANGAN KERAS
1. Jangan menyebut prioritas, kategori, risiko, skor, model, AI, analisis, prediksi, persentase, atau data internal apa pun.
2. Jangan menyebut jumlah absen atau ketidakhadiran, dan jangan bernada menyalahkan atau menghakimi.
3. Jangan mengarang fakta: jangan menyebut harga, promo, diskon, hadiah, jadwal, tanggal, jam, atau nama yang tidak ada di DATA PESAN. Jika suatu data tidak ada, jangan disebut.
4. Jangan memberi klaim kesehatan atau medis (misalnya menyembuhkan penyakit atau menurunkan tekanan darah).
5. Jangan memakai nada rasa bersalah atau urgensi palsu (misalnya "kesempatan terakhir", "jangan sampai rugi").
6. Jangan menyebut kata "lansia", "persona", atau label kelompok customer lainnya.
7. Jangan berasumsi customer sakit, sedang bermasalah, atau punya kendala serius, dan jangan menuntut balasan (misalnya "kami nantikan kabar baik dari Ibu").
```

### 3.2 Contoh few-shot (2 per persona)

Data contoh fiktif (nama, kelas, dan pelatih yang tidak ada di data synthetic) agar model tidak menyalinnya;
post-check menolak draft yang memuat istilah khusus contoh.

| # | Persona | Prioritas | Jenis pesan | Sapaan |
|---|---|---|---|---|
| 1 | ibu-ibu | Low | reminder_kelas | Bu Rina |
| 2 | ibu-ibu | High | follow_up_absen | Bu Wulan |
| 3 | lansia | Medium | reminder_kelas | Bapak/Ibu Harsono |
| 4 | lansia | High | follow_up_tidak_merespons | Ibu Endang |
| 5 | menengah_atas | Low | reminder_kelas | Ibu Vania |
| 6 | menengah_atas | Medium | follow_up_absen | Bapak/Ibu Santoso |

Contoh lengkap (Contoh 1) persis seperti di system instruction:

```text
DATA PESAN
- Sapaan pembuka: Bu Rina
- Kata ganti customer: Ibu
- Persona: ibu-ibu (hangat dan akrab)
- Jenis pesan: reminder kelas. Ingatkan kelas yang tercantum.
- Arahan isi: Pengingat ringan: sampaikan detail kelas dengan ramah dan singkat. Tidak perlu menanyakan kendala.
- Kelas: Stretching Pagi (kelas grup)
- Waktu kelas: Rabu, 4 Maret 2026 pukul 07.30 WIB (besok; akan datang)
- Pelatih: Coach Wina
- Pesan terakhir dari kami: tidak ada data (jangan disebut)
PESAN:
Halo Bu Rina, semoga sehat dan semangat selalu ya 😊 Kami mau mengingatkan jadwal kelas Stretching Pagi besok, Rabu, 4 Maret 2026 pukul 07.30 WIB bersama Coach Wina. Kalau ada perubahan rencana atau kendala, kabari kami saja lewat pesan ini ya, Bu. Kami tunggu kehadirannya, semoga latihannya menyenangkan dan seru bersama teman-teman lainnya. Sampai ketemu di kelas! Salam hangat, Admin Gymnasium
```

### 3.3 Prompt per permintaan

```text
DATA PESAN
- Sapaan pembuka: Bu Sari
- Kata ganti customer: Ibu
- Persona: ibu-ibu (hangat dan akrab)
- Jenis pesan: reminder kelas. Ingatkan kelas yang tercantum.
- Arahan isi: Pengingat ringan: sampaikan detail kelas dengan ramah dan singkat. Tidak perlu menanyakan kendala.
- Kelas: Zumba Fun (kelas grup)
- Waktu kelas: Selasa, 10 November 2026 pukul 09.00 WIB (besok; akan datang)
- Pelatih: Coach Dina
- Pesan terakhir dari kami: tidak ada data (jangan disebut)

Tulis PESAN untuk DATA PESAN di atas.
```

Jika post-check gagal, prompt regenerasi menambahkan:
`CATATAN: pesan sebelumnya ditolak pemeriksaan otomatis karena: <alasan>. Tulis ulang pesan yang memenuhi SEMUA aturan.`

## 4. Aturan sapaan

Jenis kelamin **tidak ditebak dari nama depan** (data synthetic memakai nama acak dan tebakan bisa salah).

| Kondisi | ibu-ibu | lansia / menengah_atas | Kata ganti di kalimat |
|---|---|---|---|
| Nama diawali gelar perempuan (`Ibu`, `Bu`, `Ny.`, `Nyonya`, `Hj.`) | `Bu Sari` | `Ibu Sari` | `Ibu` |
| Nama diawali gelar laki-laki (`Bapak`, `Pak`, `Bpk.`, `Tn.`, `Tuan`, `H.`) | `Pak Budi` | `Bapak Budi` | `Bapak` |
| Tanpa gelar (jenis kelamin tidak jelas) | `Bu Sari` (persona ibu-ibu) | `Bapak/Ibu Hendra` | `Ibu` / `Bapak/Ibu` |

Gelar netral (`Dr.`, `Prof.`, `Ir.`, `Drs.`, `Dra.`) dibuang tanpa menyimpulkan apa pun. Panggilan = kata pertama
setelah gelar ("Ibu Sari Wijaya" → "Sari"); nama huruf besar semua dirapikan ("RATNA" → "Ratna").

**Tips untuk admin:** evaluasi v1 menunjukkan "Bapak/Ibu Bambang" terdengar kaku untuk nama yang jelas laki-laki.
Solusinya bukan menebak dari nama, tetapi menulis gelar saat mengisi data customer, misalnya "Bapak Bambang
Hartono", sehingga sapaan otomatis menjadi "Bapak Bambang".

## 5. Post-check (`post_check.py`)

Fakta yang memang diberikan (nama kelas, pelatih, nama customer) di-*mask* dulu, sehingga kelas seperti
"Aerobic Low Impact" atau "Senam Ringan Lansia" tidak dianggap kebocoran label.

| Pemeriksaan | Contoh yang ditolak |
|---|---|
| Kosong / terlalu pendek (< 15 kata) / terlalu panjang (> 100 kata atau > 700 karakter) | respons kosong, jawaban terpotong |
| Kata terlarang: label internal & AI | prioritas, risiko, AI, model, skor, analisis, prediksi, High/Medium/Low |
| Label kelompok customer | lansia, persona, segmen, kategori |
| Kebocoran `top_factors` / statistik | teks top_factors persis, `%`, "absen berturut-turut", "3 kali absen", "selama 20 hari" |
| Harga/promo karangan | promo, diskon, gratis, harga, Rp 100.000 |
| Klaim kesehatan/medis | menyembuhkan, obat, terapi, tekanan darah, dijamin |
| Rasa bersalah / urgensi palsu | kesempatan terakhir, jangan sampai ketinggalan, rugi, kecewa |
| Jadwal karangan | jam, tanggal, atau nama hari yang tidak ada di data; nama kelas tidak disebut |
| Format | markdown/tanda bintang, placeholder `[Nama]`/`{...}`, pengantar "Berikut draft..." |
| Gaya | emoji melebihi batas persona (ibu-ibu 2, lansia 1, menengah_atas 1), singkatan (yg, dgn, utk) |
| Menyalin contoh few-shot | nama/kelas/pelatih yang hanya ada di contoh |
| v2: mengungkit pesan sebelumnya | "Kami sudah/sempat/pernah mengirim pesan…", tanggal pesan terakhir |
| v2: berasumsi atau menuntut | sakit, sembuh, cedera, "kendala serius", "kabar baik dari Ibu" |
| v2: partikel santai (lansia, menengah_atas) | ya, kok, nih, dong, sih, deh (tetap boleh untuk ibu-ibu) |
| v2: doa berulang | "sehat" lebih dari 1 kali, "semoga" lebih dari 2 kali |

Post-check bersifat **penyaring konservatif**, bukan jaminan: admin tetap wajib membaca draft sebelum mengirim.

## 6. Desain fallback (`templates.py`)

- 9 template statis (**3 persona × 3 jenis pesan**), tidak bergantung pada prioritas, hanya memakai data yang ada.
  Jika jadwal kosong, info kelas diganti frasa umum ("jadwal kelas berikutnya" / "kelas sebelumnya").
- Semua kombinasi template diuji lolos post-check (dengan/tanpa jadwal, berbagai sapaan).
- Dipakai bila: `GEMINI_API_KEY` kosong; Gemini gagal (429, 5xx, timeout, koneksi, 400/401/403/404) setelah retry;
  respons kosong/terlalu panjang/melanggar aturan setelah **1 kali regenerasi**; error tak terduga.
- Respons memuat `draft_source="template_fallback"` dan `warning` berbahasa Indonesia, misalnya
  "Kuota Gemini habis atau terlalu banyak permintaan (HTTP 429). Coba regenerate beberapa saat lagi. Draft dibuat
  dari template cadangan; periksa dan sesuaikan sebelum dikirim." Draft cadangan juga disimpan; pemanggilan
  berikutnya tanpa `regenerate` mengembalikannya dengan warning "Gunakan regenerate untuk mencoba Gemini lagi."

## 7. Ketahanan pemanggilan Gemini (`gemini_client.py`)

| Aspek | Nilai | Catatan |
|---|---|---|
| SDK | `google-genai` (`client.models.generate_content`) | Diverifikasi dari dokumentasi resmi dan source paket 2.34.0 |
| Model | env `GEMINI_MODEL`; jika kosong default `gemini-3.5-flash-lite` (di `config.py`) | Model stabil Flash-Lite menurut halaman model resmi (dicek 8 Nov 2026) |
| Temperature | env `GEMINI_TEMPERATURE`, default 0,7 | Dokumentasi Google menyebut model Gemini 3.6+ mengabaikan temperature kustom |
| Timeout | env `GEMINI_TIMEOUT_SECONDS`, default 20 detik | `HttpOptions(timeout=...)` dalam milidetik |
| Retry | env `GEMINI_MAX_RETRIES`, default 2 (total 3 percobaan) | Hanya 408/429/5xx/timeout/koneksi; backoff 1 s, 2 s (+jitter ≤10%, maks 8 s). Retry bawaan SDK tidak aktif |
| `max_output_tokens` | tidak diisi | Batas ini ikut menghitung token "thinking" sehingga batas rendah bisa memotong jawaban; panjang dijaga post-check |
| Klien | disuntik lewat `create_app(draft_generator=...)` / `deps.get_draft_generator` | Tes memakai klien palsu dan pemblokir socket |

Waktu tunggu terburuk: 3 percobaan × timeout + backoff, dikali 2 bila terjadi regenerasi. Untuk UI, tampilkan
spinner.

## 8. Privasi & free tier

- Free tier Gemini boleh memakai input untuk perbaikan produk Google → **hanya kirim data synthetic**. Jangan
  memasukkan data customer sungguhan selama memakai free tier.
- Yang dikirim: sapaan (nama depan), persona, arahan isi, jenis pesan, info kelas, tanggal pesan terakhir (konteks). Tidak
  dikirim: nomor WhatsApp, catatan customer, `top_factors`, label prioritas mentah, probabilitas.
- Kuota harian free tier kecil; 429 ditangani dengan retry terbatas lalu template cadangan.

## 9. Evaluasi kualitas (9 skenario)

Skrip `src/api/services/draft_eval.py` menjalankan **3 persona × 3 prioritas** memakai pipeline yang sama dengan
endpoint (prompt → Gemini → post-check → fallback), lalu menulis tabel Markdown ke
`docs/draft_eval/draft_eval_<versi>_<tanggal-jam>.md`. Agar 9 skenario juga mencakup ketiga jenis pesan:
Low → `reminder_kelas`, Medium → `follow_up_tidak_merespons`, High → `follow_up_absen`
(opsi `--message-type` memaksa satu jenis).

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.api.services.draft_eval --dry-run   # cek format tanpa Gemini
python -m src.api.services.draft_eval             # memanggil Gemini (butuh GEMINI_API_KEY di .env)
# isi angka 1-5 di bagian "Lembar nilai" file hasil, lalu hitung rata-ratanya:
python -m src.api.services.draft_eval --summarize docs\draft_eval\<nama-file>.md
```

Rubrik (diisi **manual**, 1 = buruk, 5 = sangat baik):

| Kolom | Pertanyaan |
|---|---|
| Kesesuaian nada | Apakah gaya cocok dengan persona dan intensitas prioritas, tanpa menekan/menyalahkan? |
| Kejelasan info kelas | Apakah nama kelas, tanggal, jam, dan pelatih jelas dan benar? |
| Tidak ada kebocoran label | Bebas dari prioritas/risiko/AI/skor/top_factors/label persona? |
| Tidak ada fakta karangan | Bebas dari harga, promo, jadwal, klaim kesehatan yang tidak ada di data? |
| Kesiapan kirim | Bisa langsung dikirim tanpa edit (5) sampai perlu ditulis ulang (1)? |

### Hasil evaluasi v1

- File hasil: [`docs/draft_eval/draft_eval_v1_20261111_2048.md`](draft_eval/draft_eval_v1_20261111_2048.md)
- Model dan waktu jalan: `gemini-3.5-flash-lite`, temperature 0,7, 11 Nov 2026 20.48 WIB
- Sumber draft: **9 gemini, 0 template_fallback**; semua lolos post-check v1 pada percobaan pertama
- Panjang draft: 49-67 kata (Low 49-60, Medium 60-65, High 63-67). AI_SPEC B2 menetapkan 60-80 kata sebagai
  **batas maksimal**, jadi draft Low yang 49 kata tetap memenuhi spesifikasi.
- Rata-rata rubrik (skala 1-5, 9/9 skenario) — **dinilai asisten AI (Claude Opus 5.5) atas permintaan pemilik,
  belum ditinjau evaluator manusia**; nilai per skenario dan alasannya ada di Lembar nilai file hasil:

  | Nada | Info kelas | Tanpa kebocoran label | Tanpa fakta karangan | Siap kirim | Rata-rata |
  |---|---|---|---|---|---|
  | 3,67 | 4,89 | 5,00 | 4,89 | 3,56 | 4,40 |

  Kolom terendah adalah **Nada** dan **Siap kirim**, sesuai masalah di bagian 10. Keamanan isi (kebocoran label,
  fakta karangan) sudah tinggi sejak v1.

Pengamatan kualitatif (analisis engineer, bukan nilai rubrik):

- Tidak ada kebocoran label atau `top_factors`, tidak ada promo/klaim kesehatan, semua fakta kelas (nama, tanggal,
  jam, pelatih, "besok"/"kemarin") benar.
- Intensitas sesuai prioritas: Low hanya pengingat (#1, #4, #7), Medium menanyakan kabar (#2, #5, #8), High
  menawarkan jadwal pengganti (#3, #6, #9). Draft terbaik: #3 ("Kami paham jika Ibu sedang ada kesibukan lain").
- Masalah ditemukan di 5 dari 9 draft (rincian di bagian 10).

### Hasil evaluasi v2

- File hasil: [`docs/draft_eval/draft_eval_v2_20261112_1610.md`](draft_eval/draft_eval_v2_20261112_1610.md)
- Model dan waktu jalan: `gemini-3.5-flash-lite`, temperature 0,7, 12 Nov 2026 16.10 WIB
- Sumber draft: **9 gemini, 0 template_fallback**; semua lolos post-check v2 pada percobaan pertama
- Rubrik (penilai dan label sama dengan v1: **asisten AI, belum ditinjau evaluator manusia**):

  | Versi | Nada | Info kelas | Tanpa kebocoran label | Tanpa fakta karangan | Siap kirim | Rata-rata |
  |---|---|---|---|---|---|---|
  | v1 | 3,67 | 4,89 | 5,00 | 4,89 | 3,56 | 4,40 |
  | v2 | 4,56 | 4,78 | 5,00 | 4,89 | 4,44 | 4,73 |
  | Selisih | +0,89 | −0,11 | 0 | 0 | +0,88 | +0,33 |

- Kelima masalah v1 tidak muncul lagi: tidak ada tanggal pesan lama atau kalimat "kami sudah mengirim pesan"
  (follow-up memakai "pesan kami sebelumnya"), tidak ada asumsi "kendala serius", tidak ada partikel santai untuk
  menengah_atas, dan tidak ada doa berulang.
- Info kelas turun sedikit karena follow-up absen lansia (#6) hanya menyebut "kemarin" tanpa jam.
- Catatan baru (kecil): #3 hampir menyalin contoh few-shot no. 2 kalimat per kalimat (variasi rendah); #1
  "membuat tubuh semakin bugar" (klaim manfaat ringan); #7 memakai "hari ini" padahal sesinya besok.
- Kehati-hatian membaca angka: hanya 9 skenario, satu kali jalan dengan temperature 0,7, dan penilainya sama
  dengan penyusun prompt. Kenaikan ini **indikatif**, bukan bukti statistik.

## 10. Iterasi prompt (v1 → v2)

| Iterasi | Masalah yang ditemukan (bukti: skenario no.) | Perubahan | Dampak |
|---|---|---|---|
| v1 | Versi awal | Aturan umum, gaya persona, larangan keras, 6 few-shot, post-check, template cadangan | 9/9 draft dari Gemini, 0 fallback; rubrik rata-rata 4,40 (Nada 3,67, Siap kirim 3,56; penilaian asisten AI); masalah di 5 draft (lihat baris v2) |
| v2 | (1) Tanggal pesan terakhir ditulis dan pesan lama diungkit ("Kami sudah/sempat/pernah mengirim pesan pada Senin, 9 November 2026"), terasa menagih balasan (#2, #5, #6, #8, #9). Penyebab: contoh few-shot no. 4 di v1 menulis kalimat serupa. (2) Asumsi dan nada menuntut: "kendala serius", "Kami nantikan kabar baik dari Ibu" (#9). (3) Kalimat tanpa subjek "Mengingatkan kembali jadwal…" dan partikel santai "ya, Bu" untuk menengah_atas (#8). (4) Doa sehat diulang dua kali (#6). | Prompt: aturan umum 7 (kalimat lengkap), 8 (tanggal pesan terakhir hanya konteks, cukup "pesan kami sebelumnya"), 9 (doa tidak diulang, "semoga" maks. 2); partikel santai dilarang untuk lansia dan menengah_atas; larangan keras 7 (tidak berasumsi sakit/bermasalah, tidak menuntut balasan). Blok DATA: tanggal pesan terakhir diberi label "konteks saja; JANGAN ditulis". Few-shot no. 4 ditulis ulang tanpa tanggal; no. 6 dibuang satu doa yang mirip. Post-check: 4 pemeriksaan baru (bagian 5) dan tanggal pesan terakhir tidak lagi termasuk tanggal yang boleh disebut. | **Terukur sebelum menjalankan v2:** post-check v2 diterapkan ke 9 output v1 → 4 lolos (#1, #3, #4, #7), 5 ditolak (#2, #5, #6, #8, #9), tepat draft yang bermasalah; jadi jika Gemini mengulang kesalahan itu, draft akan diregenerasi atau jatuh ke template, bukan sampai ke admin. Kalimat tanpa subjek (#8) hanya diatur di prompt, tidak bisa dicek otomatis. **Setelah menjalankan v2 (12 Nov):** 9/9 gemini, 0 fallback; kelima masalah v1 tidak muncul; rubrik rata-rata 4,40 → 4,73 (Nada 3,67 → 4,56, Siap kirim 3,56 → 4,44; penilaian asisten AI, 9 skenario, indikatif) |

Masalah yang **tidak** diubah di v2 beserta alasannya:

- Sapaan "Bapak/Ibu Bambang" (#4-#6): disengaja (jenis kelamin tidak ditebak dari nama); solusinya admin menulis
  gelar pada nama customer (bagian 4).
- Draft Low 49 kata (#1, #4): masih di bawah batas maksimal AI_SPEC dan wajar untuk pengingat ringan.
- Aturan doa: usulan awal "cukup satu kalimat doa" dilonggarkan menjadi "jangan diulang, maks. 2 'semoga'",
  karena draft v1 yang memakai dua harapan berbeda (#2, #3) tetap terasa natural untuk persona ibu-ibu.

Cara membuat iterasi berikutnya: ubah `_RULES`/`FEW_SHOT_EXAMPLES`, naikkan `PROMPT_VERSION`, perbarui bagian 3.1
dokumen ini (tes `test_prompt_doc_matches_code` gagal bila tidak sinkron), jalankan ulang skrip, lalu bandingkan.

## 11. Keterbatasan

- Rubrik v1 dinilai oleh asisten AI yang juga menyusun prompt (risiko bias penilai), bukan oleh admin atau
  customer sungguhan; begitu juga rubrik v2. Hanya 9 skenario dan satu kali jalan per versi.
- Variasi kalimat rendah: model cenderung meniru struktur contoh few-shot (v2 #3). Perbaikan opsional untuk v3:
  variasikan contoh dan larang menyalin kalimat contoh.
- Post-check berbasis pola kata; bisa meloloskan pelanggaran halus (mis. nada menyalahkan tanpa kata terlarang)
  atau menolak kalimat wajar (mis. menyebut hari lain). Admin tetap penanggung jawab akhir isi pesan.
- Data synthetic; nada pesan belum diuji pada customer sungguhan.
