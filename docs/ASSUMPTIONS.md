# Asumsi & Keputusan

| # | Fase | Keputusan / asumsi | Alasan |
|---|---|---|---|
| 1 | 1 | `.gitignore` TIDAK mengabaikan `data/raw`, `data/processed`, `src/ml/artifacts` | CSV dibutuhkan untuk reproduksi; file model `.joblib` dibutuhkan Render saat deploy |
| 2 | 1 | Waktu disimpan sebagai `TIMESTAMP` tanpa zona (WIB) | Menghindari pergeseran zona waktu antara data synthetic, Postgres, dan UI |
| 3 | 1 | Hasil reminder dianggap "diketahui" jika `responded_at < ref`, atau `sent_at + 48 jam < ref` untuk No Response | Mencegah kebocoran data masa depan ke fitur |
| 4 | 1 | `consecutive_absences` hanya menghitung `tidak_hadir`; `reschedule` dilewati | Reschedule bukan absen tanpa kabar |
| 5 | 1 | Customer yang terjadwal tetapi belum pernah hadir: `days_since_last_attendance` = `tenure_days` | Agar sinyal risiko tidak hilang oleh imputasi median |
| 6 | 1 | `n_history_events` (< 3 = cold start) bukan fitur model | Hanya untuk pesan "riwayat belum cukup" |
| 7 | 1 | Nomor WhatsApp synthetic berformat `628990xxxxxx` | Menghindari nomor sungguhan |
| 8 | 1 | Reminder historis synthetic tidak punya `priority`, `draft_message`, `final_message` | Prioritas baru dihasilkan oleh model di aplikasi |
| 9 | 1 | Split Fase 2 wajib grouped per `customer_id` | Satu customer punya 3-4 snapshot |
| 10 | 2 | Split 80/20 diambil dari satu fold `StratifiedGroupKFold(5)` | Menjaga proporsi kelas dan memastikan satu customer tidak ada di train sekaligus test |
| 11 | 2 | Model dipilih dari macro-F1 cross-validation pada data train, bukan dari test set | Test set tetap menjadi estimasi yang tidak bias terhadap pemilihan model |
| 12 | 2 | Artefak model dilatih pada data train saja (tidak di-refit pada seluruh data) | Metrik yang dilaporkan berlaku persis untuk model yang disimpan |
| 13 | 2 | Cold start (< 3 kejadian riwayat) dibatasi Low/Medium, `top_factors` dikosongkan, `note` = "riwayat belum cukup" | Model tidak andal untuk customer tanpa riwayat |
| 14 | 2 | Probabilitas model tidak dikalibrasi | Dipakai sebagai skor relatif, bukan peluang sebenarnya |
| 15 | 2 | `python -m src.ml.train` memperbarui bagian hasil di `docs/MODEL_EVALUATION.md` di antara penanda `RESULTS_START/END`; test tidak menyentuh dokumen | Angka di dokumen selalu berasal dari run terakhir |
| 16 | 3 | Filter `date` pada `/reminders` memakai TANGGAL KELAS (`schedules.waktu_mulai`), bukan tanggal kirim | "Reminder Hari Ini" = reminder untuk kelas hari ini; reminder tanpa jadwal tidak ikut |
| 17 | 3 | Urutan daftar reminder: High, Medium, Low, tanpa prioritas; lalu kelas terdekat | Admin melihat customer prioritas tinggi lebih dulu |
| 18 | 3 | Reminder aktif ganda (customer + kelas + jenis pesan, status Scheduled/Sent) ditolak 409 | Mencegah pesan ganda ke customer yang sama |
| 19 | 3 | Saat menjadi `Sent`, `draft_message` disalin ke `final_message` jika admin belum mengedit | Draft yang dikirim apa adanya tetap tercatat |
| 20 | 3 | Kegagalan prediksi otomatis saat membuat reminder tidak menggagalkan pembuatan reminder | Prioritas bersifat bantuan, bukan syarat |
| 21 | 3 | `seed_demo.py` melanjutkan timeline dari pola 60 hari terakhir tiap customer dan menghapus data setelah 30 Sep 2026 setiap dijalankan | Demo selalu punya data "hari ini"; tanpa itu fitur jendela 30/90 hari kosong dan sinyal berisiko hilang |
| 22 | 3 | Pada data demo, hasil reminder yang belum jatuh tempo berstatus `Sent` (menunggu respons) | Menampilkan langkah Sent → Responded / No Response |
| 23 | 3 | Hapus customer/jadwal dilakukan eksplisit di kode (bukan mengandalkan ON DELETE CASCADE) | Perilaku sama di PostgreSQL dan SQLite (tes) |
| 24 | 3 | `seed_demo` membaca tabel bertahap (5.000 baris per fetch), mengulang otomatis jika koneksi putus (`SSL error: unexpected eof`), dan menjalankan hapus data demo lama + sisip data baru dalam SATU transaksi | Koneksi ke Supabase bisa terputus di tengah proses; transaksi tunggal membuat operasi atomik dan aman diulang |
| 25 | 3 | Engine PostgreSQL memakai TCP keepalive (idle 30 dtk) dan `pool_pre_ping` | Mencegah koneksi diam yang dipotong NAT/pooler |
| 26 | 3 | `GET /` mengalihkan ke `/docs` | Membuka alamat dasar di browser tidak lagi menampilkan 404 |
| 27 | 4 | Tes lama `test_generate_draft_placeholder_501` diganti `test_generate_draft_unknown_reminder_404` (request sama, perilaku baru) | Fase 4 memang menghapus placeholder 501; tes lain tidak diubah |
| 28 | 4 | `top_factors` TIDAK dimasukkan ke prompt Gemini; hanya dipakai post-check untuk menolak draft yang memuatnya. Label prioritas juga tidak ditulis mentah, diganti "arahan isi" | Menghilangkan kemungkinan bocor ke customer dan meminimalkan data yang dikirim ke layanan eksternal |
| 29 | 4 | Reminder tanpa prioritas memakai gaya `Low` (pengingat ringan) + `warning` | Gaya paling aman; admin tahu prioritas belum dihitung |
| 30 | 4 | Sapaan: gelar di nama dibaca (Ibu/Bu/Ny./Hj. vs Bapak/Pak/Bpk./Tn./H.); tanpa gelar → persona ibu-ibu "Bu <nama>", persona lain "Bapak/Ibu <nama>". Jenis kelamin tidak ditebak dari nama depan | Nama synthetic acak; tebakan salah lebih buruk daripada sapaan netral |
| 31 | 4 | Jika `GEMINI_MODEL` kosong dipakai `DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"` di `config.py` | Model stabil Flash-Lite (paling hemat kuota) di halaman model resmi, dicek 8 Nov 2026 |
| 32 | 4 | `max_output_tokens` tidak diisi dan `thinking_config` tidak diatur; panjang dijaga post-check | Dokumentasi resmi: batas output ikut menghitung token thinking (batas rendah bisa mengosongkan jawaban); opsi thinking berbeda per model |
| 33 | 4 | Retry ditulis sendiri di `GeminiClient`: maks 2 retry (3 percobaan), backoff 1 s/2 s + jitter, hanya 408/429/5xx/timeout/koneksi; error 400/401/403/404 langsung fallback. Retry bawaan SDK dibiarkan mati | Bisa dites tanpa jaringan dan batas waktunya jelas |
| 34 | 4 | Respons kosong diperlakukan sebagai kegagalan post-check (1x regenerasi lalu fallback); error jaringan tidak diregenerasi lagi (sudah di-retry di klien) | Sesuai AI_SPEC B3; mencegah pemanggilan berlebih saat kuota habis |
| 35 | 4 | Cache hanya berlaku jika `draft_message` ada DAN `draft_source` valid (`gemini`/`template_fallback`); draft cadangan yang tersimpan dikembalikan sebagai cache dengan warning untuk regenerate | Draft lama tanpa sumber tidak bisa dipertanggungjawabkan; fallback tetap tercatat |
| 36 | 4 | `POST /generate-draft` ditolak (409 `draft_not_allowed`) untuk status selain `Scheduled`, termasuk saat `regenerate=true` | Setelah Sent pesan terkunci (konsisten dengan `message_locked`) |
| 37 | 4 | Post-check juga menolak jam/tanggal/nama hari yang tidak ada di data (hari "Minggu" tidak dicek karena juga berarti "pekan") dan draft yang tidak menyebut nama kelas | Penjaga sederhana terhadap jadwal karangan |
| 38 | 4 | Batas panjang post-check 15-100 kata / 700 karakter (target prompt 60-80 kata) | Toleransi variasi wajar tanpa langsung fallback |
| 39 | 4 | Template cadangan tidak bergantung prioritas dan lebih ringkas (±32-53 kata) daripada target Gemini | Template harus aman untuk semua kasus; spesifikasi: per persona x message_type |
| 40 | 4 | `draft_eval.py` memetakan Low→reminder_kelas, Medium→follow_up_tidak_merespons, High→follow_up_absen; jeda 5 detik antarskenario | 9 panggilan tetap mencakup 3 jenis pesan dan aman untuk batas per menit free tier |
| 41 | 4 | Tes draft memblokir semua koneksi socket kecuali loopback (dibutuhkan event loop asyncio di Windows) dan mengosongkan `GEMINI_API_KEY` | Bukti bahwa tes tidak pernah memanggil Gemini/Supabase |
