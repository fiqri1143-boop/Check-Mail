# Evaluasi Model Check Mail

Dibuat: 2026-11-19T13:22:10.823597+00:00 (UTC)
Total data: 28,683 — Normal: 15,889, Phishing: 11,417, Spam: 1,377

## Holdout lintas sumber MeAJOR

Setiap sub-sumber ditahan seluruhnya saat fold terkait diuji. Fold ini mengukur perubahan sumber untuk Normal/Phishing; kelas Spam tidak ada di korpus uji tersebut.

| Sumber uji | Kelas | Precision | Recall | F1 | Jumlah uji |
|---|---|---:|---:|---:|---:|
| meajor_trec5 | Normal | 0.943 | 0.886 | 0.913 | 3,736 |
| meajor_trec5 | Phishing | 0.897 | 0.937 | 0.917 | 3,969 |
| meajor_trec6 | Normal | 0.938 | 0.937 | 0.937 | 3,992 |
| meajor_trec6 | Phishing | 0.929 | 0.922 | 0.925 | 3,504 |
| meajor_trec7 | Normal | 0.844 | 0.878 | 0.861 | 3,986 |
| meajor_trec7 | Phishing | 0.871 | 0.831 | 0.850 | 3,934 |

## Holdout dataset yang diberikan pengguna

Data uji dipisah secara stratifikasi; fold ini mengukur Normal/Spam pada korpus tersebut.

| Kelas | Precision | Recall | F1 | Jumlah uji |
|---|---:|---:|---:|---:|
| Normal | 1.000 | 0.957 | 0.978 | 833 |
| Spam | 0.883 | 0.993 | 0.935 | 274 |

## Confusion matrix

Baris adalah label aktual; kolom adalah hasil prediksi. Urutan label tercantum pada kolom kedua.

| Holdout | Urutan label | Matriks |
|---|---|---|
| meajor_trec5 | Normal, Phishing | `[[3309, 425], [201, 3718]]` |
| meajor_trec6 | Normal, Phishing | `[[3740, 248], [247, 3229]]` |
| meajor_trec7 | Normal, Phishing | `[[3501, 484], [649, 3268]]` |
| Arsip pengguna | Normal, Spam | `[[797, 36], [0, 272]]` |

## Batas interpretasi

Skor pada sumber yang dikenal tidak menjamin generalisasi ke email Indonesia atau kampanye baru. Bobot kelas seimbang mengubah prior efektif; predict_proba bukan probabilitas risiko yang terkalibrasi. Fitur kata, karakter, dan struktur email menambah cakupan pola; evaluasi pada data lokal baru tetap diperlukan.

Metrik dipisah berdasarkan tugas dan sumber; jangan gabungkan menjadi satu akurasi tiga-kelas yang seolah-olah mewakili seluruh kondisi dunia nyata.
