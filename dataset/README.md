# Sumber dan persiapan dataset

## Dataset email pengguna

Arsip `emails-source.zip` diberikan untuk proyek ini. Isinya 5.728 contoh dengan kolom `text` dan `spam`; nilai `0` dipetakan menjadi `Normal`, nilai `1` menjadi `Spam`. Identitas bibliografis/lisensi arsip tidak disertakan di dalam nama file yang diterima, sehingga atribusi sumber asal perlu ditambahkan pemilik arsip bila tersedia.

Arsip ini, `dataset_email.zip`, dan hasil `emails.csv` dikecualikan dari Git karena berisi konten email. Untuk mereproduksi dataset dari checkout baru, pemilik proyek perlu menempatkan arsip yang boleh digunakan di folder `dataset/` secara lokal.

## Dataset phishing MeAJOR

Untuk melengkapi kelas phishing, proyek mengambil label dan konten dari rilis MeAJOR v2.0. CSV sumber menyatakan label `0 = benign` dan `1 = phishing`, dengan sub-sumber TREC-05, TREC-06, dan TREC-07. Data telah dianonimkan oleh pembuat dataset. Rilis juga menyebut sumber publik lain, tetapi file CSV yang dianalisis di proyek ini menampilkan tiga nilai sumber TREC tersebut.

- Pencipta: Francisco Cardoso, João Vitorino, Paulo Mendes, Eva Maia, Isabel Praça.
- Judul: *MeAJOR: Merged email Assets from Joint Open-source Repositories*.
- Rilis: v2.0, 2026.
- DOI: [10.5281/zenodo.18471483](https://doi.org/10.5281/zenodo.18471483).
- Lisensi: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

Sitasi yang disarankan:

> Cardoso, F., Vitorino, J., Mendes, P., Maia, E., & Praça, I. (2026). *MeAJOR: Merged email Assets from Joint Open-source Repositories* (v2.0) [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.18471483

## Contoh sintetis GPT

Arsip `dataset_email.zip` berisi 30 contoh sintetis berbahasa Indonesia/Inggris: 10 Normal, 10 Spam, dan 10 Phishing. Data ini ditambahkan sebagai sumber `sintetis_gpt` untuk memberi variasi pola bahasa dan skenario. Contoh sintetis bukan pengganti email nyata dan tidak dipakai sebagai evaluasi mandiri setelah model dilatih dengannya. Label dan isi tetap perlu ditinjau manusia; angka pada domain `example.*` dan nomor bertanda `X` adalah placeholder aman.

## Cara membangun ulang `emails.csv`

`prepare_dataset.py` membaca `emails-source.zip` dan `dataset_email.zip`, lalu mengunduh CSV MeAJOR (sekitar 191 MB) dari Zenodo jika file sumber belum tersedia. Unduhan sementara dihapus setelah CSV terkurasi berhasil dibuat. Jalankan dari root proyek:

```powershell
.\.venv\Scripts\python.exe dataset/prepare_dataset.py
```

Langkah persiapan:

1. Gabungkan subjek dan badan email menjadi teks.
2. Petakan MeAJOR `0` ke `Normal`, `1` ke `Phishing`; arsip pengguna dipetakan `0` ke `Normal`, `1` ke `Spam`.
3. Ambil maksimal 4.000 contoh per kombinasi sub-sumber MeAJOR dan kelas menggunakan reservoir sampling dengan seed 42.
4. Hapus duplikat teks persis setelah normalisasi spasi dan huruf. Jika ada label konflik, baris yang lebih dulu masuk dipertahankan dan benturan dicatat.
5. Tambahkan contoh sintetis dengan label tervalidasi dan sumber `sintetis_gpt`.
6. Simpan `teks,label,sumber` ke `emails.csv`.

Hasil saat ini berisi 28.683 baris: 15.889 Normal, 1.377 Spam, dan 11.417 Phishing. Karena data Spam tetap didominasi arsip pengguna, evaluasinya dipisahkan dari holdout MeAJOR. Lihat `../docs/evaluasi-model.json` setelah pelatihan.

## Batas interpretasi

MeAJOR menyatakan label biner aman/phishing. Proyek memetakan label tersebut menjadi kelas Phishing dan mempertahankan Spam dari arsip pengguna; definisi kampanye dari sumber asli dapat berbeda. Dataset berbahasa Inggris dan sumbernya berasal dari korpus historis, sehingga angka evaluasi tidak membuktikan generalisasi ke email Indonesia atau kampanye baru. Jangan menafsirkan skor holdout sebagai jaminan keamanan.
