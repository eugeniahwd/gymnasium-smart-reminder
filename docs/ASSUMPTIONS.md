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
