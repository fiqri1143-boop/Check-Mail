# Perbandingan Fitur Model Check Mail

Eksperimen memakai dataset kurasi dan pembagian holdout yang sama. Multinomial Naive Bayes dan bobot kelas seimbang dipertahankan.

## Perubahan TF-IDF kata → kata + karakter

| Holdout | Recall kelas target, baseline kata | Kata + karakter | Perubahan |
|---|---:|---:|---:|
| MeAJOR TREC-05 · Phishing | 0.777 | 0.928 | +0.151 |
| MeAJOR TREC-06 · Phishing | 0.855 | 0.926 | +0.071 |
| MeAJOR TREC-07 · Phishing | 0.736 | 0.825 | +0.089 |
| Arsip pengguna · Spam | 0.894 | 0.985 | +0.091 |

## Perubahan kata + karakter → kata + karakter + fitur struktural

Fitur tambahan memberi sinyal numerik yang dipelajari model bersama teks: jumlah URL/tanda seru, rasio kapital, pola URL IP/pemendek/pengalih, kombinasi permintaan tindakan dengan data sensitif, ancaman dan urgensi, promosi dengan ajakan, sapaan massal, konteks kegiatan rutin, serta perubahan tujuan pembayaran. Tidak ada fitur tunggal yang menetapkan label.

| Holdout | Recall fokus sebelumnya | Dengan fitur struktural | Perubahan | F1 sebelumnya → baru |
|---|---:|---:|---:|---:|
| MeAJOR TREC-05 · Phishing | 0.928 | 0.930 | +0.002 | 0.920 → 0.919 |
| MeAJOR TREC-06 · Phishing | 0.926 | 0.928 | +0.002 | 0.936 → 0.936 |
| MeAJOR TREC-07 · Phishing | 0.825 | 0.829 | +0.004 | 0.855 → 0.857 |
| Arsip pengguna · Spam | 0.985 | 0.985 | 0.000 | 0.954 → 0.954 |

Perubahan struktural ini **sedikit menaikkan recall Phishing di tiga holdout**, sementara precision/F1 berubah tipis dan akurasi keseluruhan hampir sama. Itu hasil moderat, bukan peningkatan besar atau bukti generalisasi untuk semua email.

## Netralisasi kata umum lintas bahasa

Audit sebuah email normal berbahasa Indonesia menunjukkan kata umum seperti “kami”, “untuk”, “informasi”, “anda”, dan “dan” mendapat kontribusi kuat ke kelas Spam akibat perbedaan sumber korpus. Kata fungsi generik Indonesia/Inggris kini dinetralisasi pada cabang TF-IDF kata saja. Kata negasi seperti “tidak”, “not”, dan “jangan” dipertahankan; cabang karakter tetap memakai teks asli. Fitur konteks rutin juga diperluas untuk administrasi, rekrutmen, akademik, jadwal, pengiriman, dan konfirmasi.

| Holdout | F1 sebelum netralisasi | F1 setelah netralisasi |
|---|---:|---:|
| MeAJOR TREC-05 · Normal | 0.922 | 0.913 |
| MeAJOR TREC-05 · Phishing | 0.920 | 0.917 |
| MeAJOR TREC-06 · Normal | 0.944 | 0.937 |
| MeAJOR TREC-06 · Phishing | 0.930 | 0.925 |
| MeAJOR TREC-07 · Normal | 0.870 | 0.861 |
| MeAJOR TREC-07 · Phishing | 0.857 | 0.850 |
| Arsip pengguna · Normal | 0.985 | 0.978 |
| Arsip pengguna · Spam | 0.954 | 0.935 |

Ada trade-off kecil pada holdout berbahasa Inggris/arsip pengguna, bukan kenaikan semua metrik. Namun email pemberitahuan seleksi yang dilaporkan (dan tidak dimasukkan ke data latih) berubah dari Spam 99.8% menjadi Normal 89.3%. Ini hanya pemeriksaan regresi pada satu email; belum membuktikan akurasi umum bahasa Indonesia. Model dipertahankan karena menghilangkan false positive yang jelas dengan penurunan metrik holdout sekitar 0.3–1.9 poin F1. Prioritas berikutnya adalah menambah dan menguji korpus Indonesia berlabel dari beragam sumber, bukan menambah whitelist kata.

## Batas evaluasi dan data berikutnya

- Holdout MeAJOR menguji Normal/Phishing; arsip pengguna menguji Normal/Spam. Keduanya tidak membentuk satu pengujian tiga kelas yang seimbang.
- Dataset Spam (1.377) jauh lebih kecil daripada Normal (15.889) dan Phishing (11.417), serta berasal dari satu arsip yang sumber lisensinya belum tersedia. Pembobotan kelas membantu pelatihan, tetapi tidak menggantikan variasi sumber.
- Isi email pengguna/simulasi yang baru dilaporkan tidak otomatis dimasukkan ke data latih. Labelnya harus ditinjau dan sampel uji dipisahkan agar evaluasi tidak bocor.
- Untuk peningkatan lebih nyata, tambahkan contoh berlabel manusia dari beberapa sumber dan bahasa, terutama Normal berbahasa Indonesia, Spam beragam, serta Phishing yang menyerupai email administrasi sah. Sisihkan set uji baru berbasis waktu/sumber.
- Hasil Normal bukan jaminan aman. Periksa [evaluasi-model.md](evaluasi-model.md) untuk metrik dan matriks kebingungan; baseline TF-IDF kata+karakter tersimpan di [evaluasi-model-kata-karakter.json](evaluasi-model-kata-karakter.json).
