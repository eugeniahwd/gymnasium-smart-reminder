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
