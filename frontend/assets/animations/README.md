# Slot ilustrasi Check Mail

Dashboard saat ini memakai SVG lokal sebagai ilustrasi sementara dan Lottie lokal kecil untuk aksen. Untuk menggantinya dengan animasi pilihanmu:

1. Unduh animasi Lottie JSON yang lisensinya mengizinkan penggunaan pada proyek ini.
2. Simpan file di folder ini, misalnya `ilustrasi-checkmail.json`.
3. Buka `frontend/script.js`, lalu isi `JALUR_ANIMASI_MASKOT` dengan `/assets/animations/ilustrasi-checkmail.json`.
4. Refresh aplikasi. Saat Lottie berhasil dimuat, SVG fallback akan disembunyikan otomatis.

Pilih animasi yang sederhana, punya latar transparan, dan tetap jelas pada tema gelap maupun terang. Jika preferensi `reduced motion` aktif, ilustrasi tetap menggunakan SVG statis.
