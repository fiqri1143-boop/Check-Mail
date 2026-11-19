# Model Card — Check Mail

## Ringkasan

- **Tugas:** klasifikasi isi email menjadi Normal, Spam, atau Phishing.
- **Model:** TF-IDF kata (1–2 gram) dengan kata umum Indonesia/Inggris dinetralisasi, TF-IDF karakter dalam batas kata (3–5 gram), dan fitur struktural, digabung dengan Multinomial Naive Bayes.
- **Pendekatan:** probabilitas mentah model ditampilkan terpisah dari indikator. Aturan risiko dapat mengubah label akhir menjadi Phishing untuk permintaan data pribadi/kredensial, perubahan rekening pembayaran yang ditekan, atau kombinasi ancaman/verifikasi akun dengan tautan; skor kelas yang terlihat tetap keluaran model mentah, bukan skor setelah aturan.
- **Penggunaan yang dimaksud:** demonstrasi akademik dan triase awal oleh manusia.
- **Bukan untuk:** pemblokiran otomatis, keputusan finansial, produksi, atau menyatakan suatu email pasti aman.

## Data pelatihan

Dataset kurasi memiliki 28.683 email: 15.889 Normal, 1.377 Spam, dan 11.417 Phishing. Sumber, pemetaan, lisensi, sampling, dan proses deduplikasi dijelaskan pada [`dataset/README.md`](../dataset/README.md). Data MeAJOR berbahasa Inggris dan dianonimkan. Data Spam berasal dari arsip yang diberikan untuk proyek; metadata lisensi/sumber asalnya belum menyertai arsip.

Model memakai sample weight seimbang untuk mengurangi dominasi Normal/Phishing atas Spam. Ini mengubah prior efektif prediksi, sehingga `predict_proba` tidak boleh dianggap probabilitas risiko yang telah terkalibrasi.

## Evaluasi

Evaluasi menahan satu sumber MeAJOR penuh per fold (TREC-05, TREC-06, TREC-07) untuk menilai perubahan sumber pada Normal/Phishing. Arsip Spam pengguna diuji dengan holdout stratifikasi tersendiri untuk Normal/Spam. Ringkasan precision, recall, F1, confusion matrix, versi perangkat lunak, dan fingerprint dataset tersedia di [`evaluasi-model.md`](evaluasi-model.md), [`evaluasi-model.json`](evaluasi-model.json), dan [`backend/model_meta.json`](../backend/model_meta.json) setelah pelatihan.

## Kinerja ringkas saat ini

| Holdout | Label | Precision | Recall | F1 |
|---|---|---:|---:|---:|
| MeAJOR TREC-05 | Normal | 0.943 | 0.886 | 0.913 |
| MeAJOR TREC-05 | Phishing | 0.897 | 0.937 | 0.917 |
| MeAJOR TREC-06 | Normal | 0.938 | 0.937 | 0.937 |
| MeAJOR TREC-06 | Phishing | 0.929 | 0.922 | 0.925 |
| MeAJOR TREC-07 | Normal | 0.844 | 0.878 | 0.861 |
| MeAJOR TREC-07 | Phishing | 0.871 | 0.831 | 0.850 |
| Arsip pengguna | Normal | 1.000 | 0.957 | 0.978 |
| Arsip pengguna | Spam | 0.883 | 0.993 | 0.935 |

Email pemberitahuan seleksi administrasi yang dilaporkan pengguna tidak dimasukkan ke data latih. Setelah kata-kata fungsi generik di cabang kata dinetralisasi, prediksi model untuk email tersebut berubah dari Spam 99,8% menjadi Normal 89,3%. Ini adalah satu pemeriksaan regresi, bukan ukuran akurasi pada email Indonesia secara umum.

## Risiko dan keterbatasan

- Recall phishing lintas sumber saat ini berkisar 0.829–0.930; beberapa phishing masih terlewat.
- Data utama berbahasa Inggris dan korpus historis; performa pada Bahasa Indonesia dan taktik baru belum diukur. Perbaikan kosakata generik membantu satu email Indonesia, tetapi belum menggantikan dataset Indonesia berlabel yang beragam.
- Sumber asal Spam berbeda dari sumber phishing, jadi tidak tersedia satu holdout tiga kelas yang representatif lintas semua kelas.
- Duplikasi dekat, perbedaan era/sumber, dan bias dataset dapat memengaruhi hasil meskipun duplikasi persis telah dihapus.
- Tautan tidak dibuka, reputasi domain tidak dicek, dan lampiran tidak dianalisis.
- Heuristik berbasis kata/pola dapat salah menandai email sah atau gagal menangkap variasi bahasa.
- Kelas hasil Normal bukan jaminan bahwa pengirim, tautan, atau lampiran aman.
- Aturan permintaan data pribadi sengaja konservatif. Permintaan alamat email/telepon atau identitas melalui email sah dapat ikut berlabel Phishing; verifikasi lewat kanal resmi, dan tinjau perbedaan label model mentah dengan label akhir.
- Peringatan login, sinkronisasi, atau pemeliharaan yang sah dapat memuat urgensi dan tautan; kombinasi ancaman akses dengan verifikasi/link dapat memicu Phishing dan perlu pemeriksaan manusia.

## Pengawasan manusia

Gunakan indikator dan isi email untuk pemeriksaan lanjutan. Jangan memasukkan email rahasia ke demo publik. Jika hasil dipakai untuk keputusan nyata, validasi dengan data lokal yang berizin, berbahasa sesuai, lebih baru, dan diuji secara terpisah.

