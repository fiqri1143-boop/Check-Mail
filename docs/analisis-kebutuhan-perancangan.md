# Check Mail — Tahap 1: Analisis Kebutuhan dan Perancangan Sistem

**Nama proyek:** Check Mail – Intelligent Email Threat Detection  
**Topik:** Defensive AI  
**Status:** Rancangan awal untuk proyek akademik lokal  
**Versi:** 1.0

## 1. Ringkasan

Check Mail adalah aplikasi lokal untuk menganalisis teks email yang ditempel secara manual oleh pengguna. Sistem menggabungkan model klasifikasi teks tiga kelas (Normal/Ham, Spam, Phishing) dengan pemeriksaan heuristik. Hasil menyajikan label, probabilitas kelas, indikator yang ditemukan, dan ringkasan riwayat lokal. Aplikasi tidak terhubung ke Gmail atau layanan email eksternal.

Klasifikasi ML adalah estimasi berdasarkan data latih, bukan jaminan bahwa email aman atau berbahaya. Heuristik memberi konteks yang dapat dijelaskan, tetapi tidak menggantikan penilaian manusia.

## 2. Tujuan dan batasan

### Tujuan
- Mengklasifikasikan teks email ke salah satu dari tiga kategori.
- Menampilkan keyakinan model dan alasan heuristik yang mudah dipahami.
- Menyimpan riwayat analisis dan menyediakan statistik sederhana melalui SQLite.
- Menyajikan antarmuka gelap dengan aksen hijau neon, karakter visual yang konsisten, dan interaksi yang jelas.
- Menjaga konten email sebagai data tidak tepercaya di frontend dan backend.

### Dalam cakupan
- Input teks melalui copy-paste, validasi panjang, analisis, tampilan hasil, riwayat, statistik lokal, serta penghapusan riwayat.
- Pelatihan model dari `dataset/emails.csv` dan penyimpanan artefak lokal dengan joblib.
- Aturan heuristik untuk bahasa mendesak, permintaan kredensial, tautan IP/Punycode/pemendek, serta perbedaan domain alamat pengirim dan balasan jika pengguna mengisinya.
- Aset ilustrasi/animasi lokal pada `frontend/assets/animations/`.

### Di luar cakupan
- Integrasi Gmail/IMAP, pengiriman email, pemindaian lampiran, reputasi URL melalui layanan eksternal, pemblokiran otomatis, autentikasi multi-pengguna, dan klaim deteksi sempurna.

## 3. Aktor dan alur utama

**Aktor:** Pengguna lokal (mahasiswa/penguji).

1. Pengguna membuka halaman Check Mail.
2. Pengguna menempelkan teks email dan meminta analisis.
3. Frontend memvalidasi ukuran, mengirim JSON ke API, dan menampilkan status proses.
4. Backend menjalankan model dan heuristik, menyimpan ringkasan analisis ke SQLite, lalu mengembalikan hasil.
5. Frontend menampilkan label, skor tiga kelas, indikator, serta teks email yang telah di-defang bila perlu.
6. Pengguna dapat membuka riwayat/statistik atau menghapus riwayat.

## 4. Kebutuhan fungsional

| ID | Kebutuhan | Prioritas |
|---|---|---|
| KF-01 | Pengguna dapat memasukkan teks email secara manual. | Must |
| KF-02 | Sistem menolak input kosong dan input di atas batas ukuran yang ditetapkan. | Must |
| KF-03 | API mengembalikan tepat satu label: `Normal`, `Spam`, atau `Phishing`. | Must |
| KF-04 | Hasil menyertakan probabilitas masing-masing kelas dan label prediksi. | Must |
| KF-05 | Mesin heuristik menyertakan daftar indikator, penjelasan, dan tingkat sinyal. | Must |
| KF-06 | Sistem menyimpan waktu, label, skor, indikator, dan ringkasan teks analisis. | Must |
| KF-07 | Pengguna dapat melihat riwayat terbaru dan statistik jumlah tiap label. | Should |
| KF-08 | Pengguna dapat menghapus seluruh riwayat lokal melalui tindakan yang jelas. | Should |
| KF-09 | UI menampilkan keadaan kosong, memuat, sukses, dan gagal secara eksplisit. | Must |
| KF-10 | Semua konten email ditampilkan sebagai teks; URL di-defang agar tidak dapat diklik. | Must |

## 5. Kebutuhan nonfungsional dan keamanan

- **Lokal dan privat:** tidak ada pengiriman email ke layanan pihak ketiga; database dan artefak model berada di proyek lokal.
- **XSS:** gunakan `textContent`/pembuatan node teks, bukan `innerHTML` untuk konten pengguna. Sanitasi tampilan adalah pertahanan tambahan; backend tetap memperlakukan masukan sebagai data tidak tepercaya.
- **URL aman:** defang skema dan pemisah domain pada tampilan (misalnya `https://` menjadi `hxxps://`, titik domain menjadi `[.]`). Jangan membuat elemen tautan dari teks email.
- **API:** validasi tipe/ukuran masukan, keluaran JSON konsisten, tangani kesalahan tanpa traceback atau isi email dalam pesan error, serta batasi CORS ke origin frontend lokal yang digunakan.
- **Penyimpanan:** gunakan parameter SQL, bukan penggabungan string; siapkan skema saat aplikasi dimulai; simpan waktu dalam format ISO 8601.
- **Model:** muat artefak lokal yang dihasilkan oleh proses pelatihan proyek sendiri. Jangan menerima unggahan model dari pengguna.
- **Ketersediaan:** aplikasi harus tetap memberi pesan yang berguna bila artefak model belum tersedia atau database gagal diinisialisasi.
- **Keterjelasan:** hasil membedakan probabilitas model dari sinyal heuristik dan menampilkan catatan bahwa skor bukan jaminan.

## 6. Rancangan arsitektur

```text
Browser (HTML/CSS/JS)
  ├─ validasi input + tampilan teks aman/defanged
  └─ REST/JSON
       ↓
Flask API (backend/app.py)
  ├─ validasi dan normalisasi permintaan
  ├─ layanan prediksi: TF-IDF kata+karakter → Multinomial Naive Bayes
  ├─ mesin heuristik yang dapat dijelaskan
  └─ repositori SQLite
       ↓
SQLite (database/history.db)

Pelatihan offline: dataset/emails.csv → train_model.py → model.pkl + vectorizer.pkl
```

Backend menjadi sumber hasil analisis dan validasi utama. Frontend menangani pengalaman pengguna dan presentasi aman; frontend tidak menjadi otoritas klasifikasi. Jalur pelatihan dipisahkan dari jalur inferensi agar model tidak dilatih ulang setiap permintaan.

## 7. Rancangan klasifikasi dan heuristik

### Pipeline ML
1. Baca CSV dengan kolom teks dan label yang disepakati (`teks`, `label`).
2. Validasi data kosong, label yang tidak dikenal, dan duplikasi yang relevan.
3. Bagi data secara stratifikasi menjadi data latih dan uji, dengan seed tetap untuk reproduksibilitas.
4. Fit TF-IDF hanya pada data latih; latih Multinomial Naive Bayes.
5. Evaluasi precision, recall, F1 per kelas, confusion matrix, dan macro-F1. Simpan artefak vectorizer/model lokal.
6. Saat inferensi, gunakan `predict_proba`; petakan urutan probabilitas berdasarkan `classes_`, jangan mengasumsikan urutan kelas.

Dataset perlu memiliki contoh memadai dan relatif seimbang untuk setiap label. Evaluasi akademik harus mencatat keterbatasan dataset dan kemungkinan false positive/false negative. Probabilitas Naive Bayes tidak selalu terkalibrasi sebagai probabilitas risiko nyata.

### Heuristik awal
- Bahasa urgensi/ancaman konsekuensi (misalnya akun akan ditutup).
- Permintaan kata sandi, OTP, PIN, atau data sensitif.
- URL dengan host berbentuk alamat IP.
- URL yang memakai pemendek tautan atau pola domain menyerupai merek (indikator saja, bukan bukti).
- Ajakan membuka tautan atau mengunduh lampiran.

Setiap indikator memiliki `kode`, `nama`, `penjelasan`, dan `tingkat` (`rendah`/`sedang`/`tinggi`). Heuristik tidak diam-diam mengganti prediksi model. Bila sistem kelak membuat keputusan gabungan, aturan penggabungan harus eksplisit, diuji, dan dijelaskan di UI.

## 8. Rancangan API

Prefix lokal: `/api`.

### `POST /api/analyze`
Permintaan:
```json
{"teks_email":"Isi email yang ditempel pengguna","alamat_pengirim":"opsional@contoh.id","alamat_balasan":"opsional@contoh.id"}
```
`alamat_pengirim` dan `alamat_balasan` opsional, hanya dipakai untuk pemeriksaan perbedaan domain, dan tidak disimpan ke riwayat.
Respons sukses (bentuk rancangan):
```json
{
  "berhasil": true,
  "hasil": {
    "label": "Phishing",
    "probabilitas": {"Normal": 0.08, "Spam": 0.12, "Phishing": 0.80},
    "indikator": [{"kode": "minta_kredensial", "nama": "Permintaan data sensitif", "tingkat": "tinggi", "penjelasan": "..."}],
    "catatan": "Skor adalah estimasi model, bukan jaminan keamanan."
  },
  "id_riwayat": 42
}
```
Kesalahan validasi menggunakan status HTTP 400; kegagalan internal menggunakan 500 dengan pesan umum. Jangan mengembalikan traceback atau teks mentah email pada respons kesalahan.

### `GET /api/history?limit=20`
Mengembalikan entri terbaru dengan batas maksimum limit yang ditentukan server. Hindari mengirim kembali isi email penuh kecuali memang diperlukan oleh kebutuhan UI.

### `GET /api/stats`
Mengembalikan total analisis dan jumlah per label, termasuk nol untuk label yang belum pernah muncul.

### `DELETE /api/history`
Menghapus seluruh riwayat lokal dan mengembalikan status keberhasilan. UI meminta konfirmasi sebelum menjalankan tindakan ini.

Semua endpoint mengembalikan JSON dengan bentuk konsisten dan header `Content-Type: application/json`.

## 9. Rancangan data SQLite

Tabel `riwayat_analisis`:

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | ID otomatis |
| `dibuat_pada` | TEXT NOT NULL | Waktu ISO 8601 |
| `label` | TEXT NOT NULL | Normal/Spam/Phishing |
| `probabilitas_json` | TEXT NOT NULL | Skor tiap label sebagai JSON |
| `indikator_json` | TEXT NOT NULL | Daftar indikator sebagai JSON |
| `sidik_teks` | TEXT NOT NULL | Hash teks untuk jejak minimal/deduplikasi opsional |
| `cuplikan_teks` | TEXT | Cuplikan pendek opsional, dengan batas panjang |

**Privasi penyimpanan:** rancangan default menyimpan skor, indikator, hash, dan cuplikan terbatas; tidak menyimpan badan email lengkap. Jika implementasi membutuhkan badan penuh untuk fitur riwayat, keputusan itu harus terlihat jelas pada UI dan README. Gunakan query berparameter.

## 10. Rancangan UI/UX

- Dashboard langsung membuka halaman Scan; navigasi menuju halaman Riwayat dan Panduan yang terpisah, bukan landing page atau satu halaman panjang.
- Dark mode aktif sebagai tema awal dan dapat diganti ke tema terang. Pilihan disimpan di browser; perpindahan warna dan komponen memakai transisi singkat.
- Area kerja memanfaatkan hampir seluruh lebar layar, dengan ukuran teks input dan hasil yang nyaman dibaca. Pada layar kecil, kolom disusun ulang.
- Grid lembut, keycap warna cerah, outline tebal dan bayangan keras meneruskan karakter playful/neo-brutalist; warna tetap dibantu label dan ikon agar makna tidak bergantung pada warna saja.
- Ilustrasi lokal memakai SVG fallback dan slot untuk Lottie JSON pilihan pengguna. Aset disimpan lokal tanpa CDN; petunjuk penggantian ada di `frontend/assets/animations/README.md`.
- Animasi loading muncul hanya selama permintaan analisis berlangsung. Semua gerak mengikuti preferensi `prefers-reduced-motion` dan tidak menghalangi interaksi.
- Hasil memakai warna dan ikon serta label teks; jangan mengandalkan warna saja. Phishing menggunakan status peringatan yang mudah dikenali, Spam status berbeda, Normal status aman tanpa menyatakan jaminan mutlak.
- Tampilkan URL yang di-defang sebagai teks biasa. Hasil dan riwayat harus responsif dan bisa digunakan dengan keyboard.
- Nuansa Gen Z/milenial hadir melalui microcopy santai yang jelas, bukan slang berlebihan; informasi keamanan tetap presisi.

## 11. Struktur proyek yang disepakati

```text
Check-Mail/
├── backend/
│   ├── app.py
│   ├── train_model.py
│   ├── model.pkl
│   └── vectorizer.pkl
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── script.js
│   └── assets/animations/
├── dataset/
│   └── emails.csv
├── database/
│   └── history.db
├── docs/
│   └── analisis-kebutuhan-perancangan.md
├── requirements.txt
└── README.md
```

Folder `docs/` menampung rancangan ini. Artefak model dan database dapat dibuat saat pelatihan/aplikasi berjalan sehingga tidak harus tersedia sebagai file biner awal.

## 12. Konvensi penamaan

Nama variabel dan fungsi baru menggunakan bahasa Indonesia yang jelas, misalnya `teks_email`, `probabilitas_kelas`, `deteksi_indikator`, `simpan_riwayat`, `ambil_statistik`, dan `validasi_permintaan`. Nama paket, kelas dari pustaka, format API/JSON, serta nama berkas yang telah ditetapkan boleh mengikuti konvensi teknis yang diwajibkan agar integrasi tetap konsisten. Label kelas untuk API disepakati: `Normal`, `Spam`, `Phishing`.

## 13. Kriteria penerimaan rancangan

- Tiga kelas dan alur hybrid ML + heuristik terdefinisi.
- Ada pemisahan yang jelas antara inferensi, heuristik, penyimpanan, dan UI.
- Kontrak endpoint dan bentuk data historis ditetapkan.
- Risiko XSS, URL aktif, input berlebih, SQL injection, kebocoran data, dan keterbatasan model sudah dipertimbangkan.
- Gaya visual, animasi lokal, fallback, aksesibilitas, dan microcopy telah menjadi kebutuhan desain.
- Tahapan berikutnya dapat dikerjakan tanpa mengubah lingkup dasar: penyiapan dataset dan evaluasi model, backend/API, lalu frontend dan integrasi.

## 14. Keputusan yang perlu dikunci sebelum implementasi

Badan email lengkap tidak disimpan dalam riwayat; sistem menyimpan cuplikan maksimal 180 karakter. Dataset sekarang memakai kolom `teks`, `label`, dan `sumber`. Batas input adalah 20.000 karakter dan batas riwayat API 100 entri per permintaan.

## 15. Dataset yang dipakai

Dataset sumber awal mempunyai label Normal dan Spam. Pipeline menambahkan data MeAJOR untuk kelas Phishing, mencatat asal setiap baris, membatasi jumlah per sumber, dan mengevaluasi dengan holdout berbasis sumber. Atribusi, langkah persiapan, hitungan kelas, dan keterbatasan dijelaskan dalam dataset/README.md dan docs/evaluasi-model.json setelah pelatihan.




