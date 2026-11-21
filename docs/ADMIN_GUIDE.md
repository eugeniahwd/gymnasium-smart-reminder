# Panduan Admin — Gymnasium Smart Reminder & Follow-up

> **PROTOTYPE · data synthetic.** Prioritas dari model dan draft dari AI hanya **bantuan**. Keputusan dan isi
> pesan tetap tanggung jawab admin. Aplikasi **tidak pernah mengirim pesan sendiri**.

## 1. Membuka aplikasi

1. Buka URL aplikasi (Streamlit). Jika muncul "API sedang bangun, bisa memakan sekitar 1 menit", tunggu sebentar —
   server gratis tidur bila 15 menit tidak dipakai.
2. Cek **sidebar kiri**: harus tertulis `Status API: ok · Database: terhubung · Model: ...`.
   Jika tidak, klik **Cek ulang koneksi API**. Bila tetap gagal, lihat bagian 7.
3. Menu: **Reminder Hari Ini** (pekerjaan harian), **Customer**, **Jadwal**, **Riwayat Reminder**.

## 2. Rutinitas harian (Reminder Hari Ini)

1. **Pilih tanggal kelas** (default hari ini). Daftar berisi reminder untuk kelas pada tanggal itu, diurutkan
   🔴 High → 🟠 Medium → 🟢 Low, lalu kelas yang paling dekat waktunya. Kelas hanya Senin–Sabtu, jadi hari Minggu
   kosong.
2. **Pilih satu reminder** di kotak "Pilih reminder untuk diproses" (bisa diketik untuk mencari nama). Mulailah dari
   paling atas.
3. (Opsional) Klik **Lihat alasan prioritas** untuk melihat faktor seperti "3 absen berturut-turut".
   **Alasan ini hanya untuk admin — jangan disalin ke pesan.** Customer baru bertanda "riwayat belum cukup".
4. Klik **Generate Draft**. Draft muncul di kotak pesan.
   - Sumber **Gemini (AI)**: draft sesuai persona dan prioritas.
   - Sumber **Template cadangan**: muncul bila AI sedang tidak tersedia (kuota habis, gangguan). Peringatan kuning
     menjelaskan sebabnya. Template tetap aman dipakai, tetapi lebih umum.
   - Kurang cocok? Klik **Generate ulang draft** (isi kotak akan diganti).
5. **Baca dan edit** pesan di kotak. Pastikan nama, kelas, tanggal, dan jam benar. Klik **Simpan pesan** bila ingin
   menyimpan editan sebelum dikirim.
6. Klik **Buka WhatsApp (teks terisi)**. WhatsApp terbuka ke nomor customer dengan teks pesan. **Tekan kirim di
   WhatsApp sendiri.**
7. Kembali ke aplikasi, centang **"Saya sudah mengirim pesan ini lewat WhatsApp"**, lalu klik **Tandai Terkirim**.
   Pesan di kotak disimpan sebagai pesan akhir dan status menjadi **Sent**. Setelah itu pesan **terkunci**.
8. Setelah ada kabar dari customer, buka lagi reminder tersebut lalu klik **Responded** (membalas) atau
   **No Response** (tidak membalas). Status ini final.

Alur status: `Scheduled` (belum dikirim) → `Sent` (terkirim) → `Responded` / `No Response`. Urutan lain ditolak
sistem dengan pesan yang menjelaskan alurnya.

## 3. Membuat reminder baru

Di bagian bawah **Reminder Hari Ini**, aktifkan **Buat reminder baru** → pilih customer, kelas pada tanggal yang
dipilih (atau "Tanpa jadwal"), dan jenis pesan:

| Jenis pesan | Kapan dipakai |
|---|---|
| Reminder kelas | Mengingatkan kelas yang akan datang |
| Follow-up setelah absen | Customer tidak hadir di kelas yang dipilih |
| Follow-up belum membalas | Pesan sebelumnya belum dibalas |

Prioritas dihitung otomatis saat reminder dibuat. Reminder yang sama (customer + kelas + jenis pesan) yang masih
aktif tidak bisa dibuat dua kali. Reminder tanpa jadwal tidak muncul di daftar per tanggal; lihat di **Riwayat
Reminder**.

## 4. Customer

- **Tambah customer**: isi nama, nomor WhatsApp (`08…` atau `628…`), persona (Ibu-ibu / Lansia / Menengah atas).
- **Tulis gelar di depan nama** — misalnya "Bapak Bambang Hartono" atau "Ibu Sari Wijaya" — agar sapaan draft tepat.
  Tanpa gelar, persona lansia dan menengah atas disapa "Bapak/Ibu", karena sistem sengaja tidak menebak jenis
  kelamin dari nama.
- **Ubah / hapus**: pilih customer, ubah data, **Simpan perubahan**. Menghapus customer juga menghapus semua
  reminder, riwayat, prediksi, dan kehadirannya (perlu centang konfirmasi).

## 5. Jadwal

Pilih rentang tanggal untuk melihat jadwal. **Tambah jadwal**: nama kelas, tipe (kelas grup / private), tanggal,
jam mulai (WIB), pelatih, kapasitas. Menghapus jadwal menghapus data kehadirannya, sedangkan reminder tetap ada
tanpa jadwal.

## 6. Riwayat Reminder

Pilih customer untuk melihat semua reminder-nya (terbaru dulu), lalu pilih satu reminder untuk melihat pesan akhir
dan riwayat perubahan statusnya.

## 7. Jika ada masalah

| Pesan / gejala | Arti dan tindakan |
|---|---|
| "API sedang bangun, bisa memakan sekitar 1 menit" | Server sedang menyala dari mode tidur. Tunggu, lalu coba lagi. |
| "Tidak dapat terhubung ke API ..." | Server API mati atau alamat salah. Hubungi pengelola aplikasi. |
| "Database tidak dapat dihubungi ..." | Database sedang tidak aktif (Supabase ter-pause). Pengelola perlu mengaktifkannya kembali. |
| Peringatan kuning "Kuota Gemini habis ..." | Draft dibuat dari template cadangan. Pakai template itu atau coba **Generate ulang** nanti. |
| "Pesan tidak dapat diubah karena reminder sudah berstatus 'Sent'" | Pesan terkunci setelah dikirim; ini disengaja. |
| "Transisi ... tidak diizinkan" | Urutan status salah (misalnya Responded sebelum Sent). Ikuti alur di bagian 2. |
| "Nomor WhatsApp sudah terdaftar pada customer lain" | Nomor sudah dipakai customer lain; cek data yang ada. |
| Daftar kosong | Tidak ada kelas pada tanggal itu (hari Minggu), atau data demo perlu diperbarui pengelola. |

## 8. Etika pesan

- Jangan menyebut prioritas, skor, "AI", atau alasan internal kepada customer.
- Jangan menjanjikan promo, harga, atau manfaat kesehatan yang tidak ada di data.
- Untuk customer yang lama tidak hadir: tanyakan kabar dengan ramah dan tawarkan bantuan jadwal, tanpa menyalahkan.
