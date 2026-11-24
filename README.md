# Check Mail

Aplikasi lokal untuk menganalisis email dengan tiga kelas: **Normal**, **Spam**, dan **Phishing**. Email dapat ditempel sebagai teks atau diimpor dari berkas `.eml`/`.txt`. Backend memakai Flask REST API, gabungan TF-IDF kata (1–2 gram), karakter (3–5 gram), dan fitur struktural email, Multinomial Naive Bayes dengan bobot kelas seimbang, heuristik yang dapat dijelaskan, dan SQLite. Fitur karakter dan struktural memberi sinyal tambahan seperti permintaan data sensitif, perubahan pembayaran, ajakan promosi, dan konteks kegiatan rutin; semua tetap dipelajari bersama teks, bukan aturan satu kata. Aturan risiko dapat mengubah kategori model bila mendeteksi kombinasi berisiko tinggi. Respons menyertakan label mentah model untuk transparansi. Frontend memakai kertas krem bergaris grid, keycap warna-warni dengan outline tebal dan bayangan keras, serta maskot SVG/Lottie lokal.

## Antarmuka

Check Mail langsung membuka halaman Scan, tanpa halaman promosi/landing. Navigasi membawa pengguna ke halaman **Scan**, **Riwayat**, atau **Panduan**. Tampilan lebar memakai dashboard penuh, dark mode aktif sebagai tema awal, dan tombol tema menyimpan pilihan di browser. Ukuran teks input dibuat lebih besar, sementara animasi loading hanya muncul saat permintaan analisis benar-benar berjalan.

Slot ilustrasi memakai SVG sementara. Untuk menggantinya dengan Lottie pilihanmu, ikuti petunjuk di [frontend/assets/animations/README.md](frontend/assets/animations/README.md). File animasi disimpan lokal; tidak perlu CDN.

## Struktur utama

```text
backend/app.py                 REST API dan analisis
backend/train_model.py         Pelatihan + evaluasi holdout lintas sumber
backend/fitur_struktural.py    Ekstraksi sinyal gabungan untuk fitur ML
backend/model_meta.json       Fingerprint data, parameter, dan versi lingkungan (dibuat saat pelatihan)
dataset/emails-source.zip      Dataset lokal yang disediakan pemilik proyek (tidak di-commit)
dataset/dataset_email.zip      Contoh sintetis lokal (tidak di-commit)
dataset/prepare_dataset.py     Penggabungan, pemetaan label, deduplikasi, sampling
dataset/emails.csv             Dataset terkurasi lokal (tidak di-commit)
dataset/README.md              Sumber, atribusi, lisensi, metode persiapan
docs/evaluasi-model.md         Ringkasan metrik yang mudah dibaca
docs/evaluasi-model.json       Metrik terstruktur per sumber (dibuat saat pelatihan)
docs/perbandingan-fitur-model.md Perbandingan fitur dan trade-off evaluasi
docs/model-card.md             Batas penggunaan, risiko, dan ringkasan kinerja
frontend/                      HTML, CSS, JavaScript dan aset lokal
  index.html                   Halaman scan/dashboard
  riwayat.html                 Halaman riwayat terpisah
  panduan.html                 Panduan keamanan email
database/history.db            Riwayat analisis lokal (dibuat otomatis)
```

## Jalankan aplikasi

Dari PowerShell di folder proyek:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe dataset\prepare_dataset.py
.\.venv\Scripts\python.exe backend\train_model.py
.\.venv\Scripts\python.exe backend\app.py
```

Buka `http://127.0.0.1:5000`. Jika `.venv` belum ada, buat dengan `py -m venv .venv` dahulu. Pelatihan membuat artefak model, metadata reproducibility, dan laporan evaluasi di folder `backend/` serta `docs/`.

### Persiapan data untuk checkout baru

```powershell
.\.venv\Scripts\python.exe dataset\prepare_dataset.py
```

Sumber email dan hasil gabungannya tidak disertakan di Git karena berisi konten pesan. Untuk checkout baru, siapkan arsip berizin `emails-source.zip` serta `dataset_email.zip` di folder `dataset/`; skrip mengambil MeAJOR dari Zenodo bila CSV sumber belum tersedia. Jalankan `prepare_dataset.py`, lalu `train_model.py`, kemudian mulai aplikasi. Artefak model dan database dibuat lokal dan tidak di-commit.

## API lokal

- `POST /api/analyze` — JSON berisi `teks_email` dan opsional `alamat_pengirim`/`alamat_balasan`; mengembalikan prediksi, probabilitas tiga kelas, dan indikator heuristik. Alamat hanya dibandingkan selama scan dan tidak disimpan.
- `POST /api/analyze-file` — `multipart/form-data` dengan field `berkas_email` berupa `.eml`, `.txt`, atau `.pdf` (maksimal 10 MB); mengurai header, teks, dan tautan `href`/anotasi PDF lalu menjalankan model yang sama.
- `GET /api/history?limit=20` — riwayat terbaru, maksimal 100 entri.
- `GET /api/stats` — jumlah analisis per label.
- `DELETE /api/history` — hapus riwayat lokal.

Batas input 20.000 karakter. Riwayat menyimpan metadata, hash, dan cuplikan maksimal 180 karakter, bukan badan email lengkap. Cuplikan dapat memuat informasi pribadi, jadi gunakan data demonstrasi yang sesuai.

### Memindai email yang diunduh

Di Gmail, buka menu tiga titik pada pesan lalu pilih **Download message**. Di Check Mail pilih berkas `.eml` yang diunduh. Berkas `.txt` dan `.pdf` juga dapat dipilih (maksimal 10 MB). Lampiran PDF di dalam EML dan PDF langsung akan diekstrak teks/tautannya bila PDF memiliki lapisan teks. PDF hasil scan gambar serta gambar lampiran terdeteksi, tetapi OCR belum tersedia; jika badan email kosong, sistem menolak membuat prediksi dari header saja. Lampiran lain hanya dicatat tipenya dan tidak dieksekusi. URL dianalisis secara pasif dari struktur yang tersedia, seperti alamat IP, pemendek tautan, Punycode, atau parameter pengalih. Check Mail tidak membuka URL, mengirim permintaan jaringan ke domainnya, mengikuti redirect, atau menampilkan peta tujuan. Hasil tautan adalah temuan diagnostik, bukan pemeriksaan reputasi atau jaminan keamanan situs. Tidak ada layanan AI eksternal yang menerima email; kesimpulan klasifikasi berasal dari model ML lokal dan aturan heuristik.

## Dataset dan batas interpretasi

Dataset terkurasi saat ini memiliki 28.683 baris: 15.889 Normal, 1.377 Spam, dan 11.417 Phishing. Data mencakup arsip proyek, MeAJOR v2.0, dan 30 contoh sintetis GPT yang dilacak dengan sumber `sintetis_gpt`. Persiapan memakai sampling deterministik dan deduplikasi persis. Atribusi, lisensi, pemetaan label, dan batasan dijelaskan di [dataset/README.md](dataset/README.md).

Model menggabungkan TF-IDF kata dan karakter dengan fitur struktural yang dipelajari Multinomial Naive Bayes. Kata fungsi generik Indonesia/Inggris dinetralisasi hanya pada cabang TF-IDF kata agar perbedaan kosakata antarkorpus tidak mendominasi keputusan; negasi dipertahankan dan cabang karakter tetap melihat teks asli.

Lapisan aturan risiko menaikkan label akhir menjadi **Phishing** bila email secara eksplisit meminta data pribadi/kredensial (mis. NIK/KTP, tanggal lahir, alamat, OTP/PIN, kata sandi, rekening, atau nomor kartu); mengubah rekening pembayaran sambil mendesak pembayaran; atau menggabungkan ancaman akses akun dengan verifikasi melalui tautan. Deteksi kontekstual juga memeriksa klaim merek terhadap domain pengirim/tujuan tautan, permintaan pembaruan alamat paket, OTP bersama klaim aktivitas akun dan tautan asing, klaim hadiah yang meminta identitas, serta ancaman denda/akses dengan tujuan domain yang tidak selaras. Sinyal kontekstual tersebut ditampilkan sebagai indikator tersendiri dan mengalahkan prediksi Spam ketika menunjukkan pola phishing yang kuat. Pemeriksaan domain bersifat pencocokan lokal, bukan validasi reputasi atau konfirmasi status resmi; autentikasi pengirim pun perlu dinilai dari header penuh.

Hasil menampilkan **indeks keputusan gabungan** di grafik utama agar konsisten dengan label akhir. Bila aturan mengubah label dari prediksi ML, indeks ini memberi bobot terbatas pada indikator pendukung dan tidak pernah diklaim sebagai probabilitas terkalibrasi. Keluaran `predict_proba` asli tetap tersedia pada rincian skor ML mentah untuk transparansi.

Jika model mentah memilih Spam, sistem juga mengenali gabungan sinyal percakapan personal—sapaan/konteks relasi, ajakan berinteraksi, dan rencana spesifik—untuk mengurangi salah klasifikasi korespondensi biasa. Penyesuaian ini hanya berlaku tanpa tautan, promosi, dan indikator risiko tinggi; konteks percakapan bukan bukti bahwa identitas pengirim sudah terverifikasi. Promosi tanpa pola tindakan berisiko tetap dinilai sebagai Spam oleh model. Permintaan data atau peringatan akun yang sah dapat ikut ditandai, jadi periksa alasan label dan verifikasi melalui kanal resmi. Skor per kelas tetap skor ML mentah, terpisah dari perubahan label oleh aturan.
Promosi juga dianalisis dari jenis penawaran, klaim hasil luar biasa, urgensi/kelangkaan, ajakan bertindak, pola audiens umum, tautan, dan permintaan pengisian data. **Indeks sinyal promosi (maksimum 90 poin)** adalah bobot indikator heuristik, bukan probabilitas atau kepastian penipuan. Promosi dengan formulir/tautan diberi catatan kewaspadaan; label Phishing tetap memerlukan sinyal pengambilan data sensitif, ancaman akun, atau pola berisiko lain.

Evaluasi memisahkan holdout lintas sub-sumber MeAJOR dan holdout stratifikasi untuk arsip Spam yang diberikan. Ini lebih informatif daripada satu random split, tetapi tidak membuktikan performa pada email Indonesia atau kampanye baru. Tinjau `docs/evaluasi-model.json`; jangan menganggap hasil Normal sebagai jaminan aman.

Bobot kelas seimbang mengubah prior efektif model. Karena itu angka `predict_proba` adalah skor relatif model, bukan probabilitas risiko yang terkalibrasi terhadap trafik email nyata.

## Pengamanan UI

Konten pengguna ditampilkan menggunakan `textContent` dan node teks, bukan `innerHTML`. URL di-defang sebelum ditampilkan dan tidak dibuat menjadi tautan. API memvalidasi jenis/ukuran input, memakai query SQLite berparameter, dan hanya mendengarkan di `127.0.0.1`.



