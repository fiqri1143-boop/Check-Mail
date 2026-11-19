"""Ekstraksi fitur struktural teks email untuk pipeline Check Mail."""
import re


# Kata fungsi dari dua bahasa dominan korpus. Korpus Spam dan Normal berasal
# dari koleksi berbeda sehingga pronomina/kata penghubung sempat menjadi jalan
# pintas bagi model. Kata negasi (mis. "tidak", "not", "jangan") sengaja
# dipertahankan karena dapat mengubah maksud pesan.
KATA_UMUM = frozenset({
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "been", "before", "being", "but", "by", "can", "could",
    "did", "do", "does", "each", "for", "from", "had", "has", "have", "he",
    "her", "here", "him", "his", "how", "i", "if", "in", "into", "is", "it",
    "its", "just", "may", "me", "more", "most", "my", "of", "on", "or", "our",
    "ours", "she", "should", "so", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "through", "to",
    "was", "we", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "would", "you", "your", "yours",
    "akan", "anda", "antara", "atas", "atau", "bagi", "bahwa", "banyak", "beberapa",
    "bersama", "bisa", "buat", "dalam", "dan", "dari", "daripada", "dengan",
    "dia", "di", "dapat", "dua", "ia", "ini", "itu", "jadi", "juga", "kami", "kamu",
    "karena", "ke", "kepada", "kita", "kurang", "lebih", "melalui", "memang", "mereka",
    "merupakan", "oleh", "pada", "para", "saat", "saja", "sama", "sangat", "saya",
    "secara", "sebagai", "segera", "setelah", "setiap", "sudah", "tanpa", "tentang",
    "terhadap", "tersebut", "tiga", "untuk", "yang", "informasi",
})


def hapus_kata_umum(teks):
    """Netralisasi kata umum agar sumber dataset tidak menjadi jalan pintas."""
    if not isinstance(teks, str):
        teks = str(teks)
    return re.sub(
        r"(?u)\b[\w'-]+\b",
        lambda cocok: " " if cocok.group(0).casefold() in KATA_UMUM else cocok.group(0),
        teks,
    )


def ekstrak_fitur_struktural(daftar_teks):
    """Ekstrak kombinasi sinyal bentuk dan maksud, bukan keputusan berbasis kata tunggal."""
    fitur_semua = []
    pola_url = re.compile(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", re.I)
    pola_aksi = re.compile(r"\b(?:kirim|berikan|masukkan|isi|balas|klik|bayar|transfer|verifikasi|konfirmasi|send|provide|enter|submit|click|pay|transfer|verify|confirm|update)\b", re.I)
    pola_sensitif = re.compile(r"\b(?:password|kata sandi|otp|pin|cvv|kode verifikasi|kredensial|rekening|bank details|account details|card number|login credentials)\b", re.I)
    pola_urgensi = re.compile(r"\b(?:segera|hari ini|sekarang|dalam \d+ jam|urgent|immediately|within \d+ hours|act now|deadline)\b", re.I)
    pola_ancaman = re.compile(r"\b(?:diblokir|ditangguhkan|dinonaktifkan|akses dibatasi|layanan dihentikan|account locked|account suspended|service interruption|service restriction)\b", re.I)
    pola_promosi = re.compile(r"\b(?:promo|diskon|gratis|voucher|cashback|giveaway|flash sale|penawaran|bonus|hadiah|limited offer|free trial|special deal|discount code)\b", re.I)
    pola_cta_promosi = re.compile(r"\b(?:beli sekarang|daftar sekarang|jangan lewatkan|subscribe now|buy now|shop now|claim now)\b", re.I)
    # Cakup korespondensi rutin berbahasa Indonesia yang hampir tidak muncul
    # dalam korpus MeAJOR berbahasa Inggris. Ini bukan daftar pengecualian satu
    # email; pola mencakup pekerjaan, administrasi, akademik, dan konfirmasi.
    pola_konteks_rutin = re.compile(
        r"\b(?:jadwal|rapat|pertemuan|agenda|notulen|proyek|akademik|kuliah|"
        r"registrasi|lamaran|rekrutmen|seleksi|tahapan|administrasi|pemberitahuan|"
        r"berkas|dokumen|pengiriman|resi|konfirmasi|terima kasih|kami telah menerima|"
        r"telah kami terima|dapat diproses|peninjauan|undangan|jadwal konsultasi|"
        r"meeting|schedule|project update|attached document|registration confirmed|"
        r"application received|we have received|thank you for|delivery update|"
        r"order confirmation|payment received|maintenance notice)\b", re.I)
    pola_sapaan_umum = re.compile(r"\b(?:dear customer|dear user|valued customer|pelanggan yth|pelanggan yang terhormat|pengguna yang terhormat)\b", re.I)
    pola_rekening_berubah = re.compile(r"\b(?:rekening|bank details|payment destination|payment account)\b.{0,70}\b(?:berubah|baru|diganti|no longer valid|updated|changed|revised)\b|\b(?:updated|changed|revised|new)\b.{0,50}\b(?:rekening|bank details|payment destination|payment account)\b", re.I)
    pola_ip = re.compile(r"https?://(?:\d{1,3}\.){3}\d{1,3}(?=[:/\s]|$)", re.I)
    pola_pendek = re.compile(r"https?://(?:bit\.ly|tinyurl\.com|t\.co|is\.gd|cutt\.ly|rb\.gy)/", re.I)
    pola_redirect = re.compile(r"https?://[^\s<>]+(?:url\?|redirect=|[?&](?:url|target|next|continue)=)", re.I)
    for teks in daftar_teks:
        teks = str(teks)
        huruf = [karakter for karakter in teks if karakter.isalpha()]
        urls = pola_url.findall(teks)
        aksi = list(pola_aksi.finditer(teks))
        sensitif = list(pola_sensitif.finditer(teks))
        permintaan_sensitif = any(abs(a.start() - s.start()) <= 90 for a in aksi for s in sensitif)
        promosi = bool(pola_promosi.search(teks))
        mendesak = bool(pola_urgensi.search(teks))
        ancaman = bool(pola_ancaman.search(teks))
        rutin = bool(pola_konteks_rutin.search(teks))
        fitur_semua.append({
            "panjang_teks": min(len(teks) / 10000, 1.0),
            "panjang_kata": min(len(re.findall(r"\b\w+\b", teks)) / 1500, 1.0),
            "jumlah_url": min(len(urls), 10) / 10,
            "jumlah_tanda_seru": min(teks.count("!"), 10) / 10,
            "rasio_huruf_kapital": (sum(1 for c in huruf if c.isupper()) / len(huruf)) if huruf else 0.0,
            "memakai_url": float(bool(urls)),
            "tautan_ip": float(bool(pola_ip.search(teks))),
            "tautan_pendek": float(bool(pola_pendek.search(teks))),
            "tautan_redirect": float(bool(pola_redirect.search(teks))),
            "permintaan_data_sensitif": float(permintaan_sensitif),
            "urgensi": float(mendesak),
            "ancaman_akses": float(ancaman),
            "urgensi_dan_ancaman": float(mendesak and ancaman),
            "tautan_dan_permintaan_sensitif": float(bool(urls) and permintaan_sensitif),
            "promosi": float(promosi),
            "promosi_dengan_ajakan": float(promosi and bool(pola_cta_promosi.search(teks))),
            "sapaan_massal": float(bool(pola_sapaan_umum.search(teks))),
            "konteks_kegiatan_rutin": float(rutin),
            # Sinyal ini hanya aktif pada konteks rutin tanpa tanda pemaksaan,
            # permintaan data sensitif, tautan, atau ajakan promosi. Model tetap
            # menilai keseluruhan teks; fitur ini tidak menjadi whitelist.
            "konteks_rutin_tanpa_tekanan": float(
                rutin and not mendesak and not ancaman and not permintaan_sensitif
                and not urls and not bool(pola_cta_promosi.search(teks))
                and not bool(pola_rekening_berubah.search(teks))
            ),
            "perubahan_tujuan_pembayaran": float(bool(pola_rekening_berubah.search(teks))),
            "perubahan_pembayaran_dan_tekanan": float(bool(pola_rekening_berubah.search(teks)) and (mendesak or ancaman)),
        })
    return fitur_semua
