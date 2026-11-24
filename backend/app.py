"""REST API lokal Check Mail."""
from __future__ import annotations

import hashlib
import html
import io
from difflib import SequenceMatcher
from html.parser import HTMLParser
import ipaddress
import json
import re
import sqlite3
import sys
from email import policy
from email.parser import BytesParser
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import joblib
from pypdf import PdfReader
from flask import Flask, jsonify, request, send_from_directory

DIREKTORI_PROYEK = Path(__file__).resolve().parent.parent
if str(DIREKTORI_PROYEK) not in sys.path:
    sys.path.insert(0, str(DIREKTORI_PROYEK))
JALUR_DATABASE = DIREKTORI_PROYEK / "database" / "history.db"
JALUR_MODEL = Path(__file__).resolve().parent / "model.pkl"
JALUR_VECTORIZER = Path(__file__).resolve().parent / "vectorizer.pkl"
BATAS_PANJANG_EMAIL = 20_000
BATAS_RIWAYAT = 100
LABEL_VALID = ("Normal", "Spam", "Phishing")

POLA_DATA_PRIBADI_SENSITIF = re.compile(
    r"\b(?:nik|nomor induk kependudukan|ktp|kartu tanda penduduk|"
    r"kartu keluarga|nomor kk|npwp|nomor paspor|passport number|"
    r"tanggal lahir|tempat dan tanggal lahir|birth date|date of birth|"
    r"nama lengkap|full name|alamat rumah|alamat lengkap|home address|"
    r"alamat email|email address|nomor telepon|phone number|nama pengguna|username|"
    r"informasi pemulihan|recovery information|recovery email|"
    r"nomor rekening|rekening bank|nomor kartu(?: kredit| debit)?|"
    r"cvv|cvc|kata sandi|password|otp|one[- ]time password|pin|kode verifikasi|"
    r"data pribadi|data diri|informasi pribadi|informasi identitas|"
    r"identitas pribadi|nomor identitas|kartu identitas|personal identity|"
    r"personal information|personal data|"
    r"kredensial|data login|social security number|ssn|bank account number)\b",
    re.IGNORECASE,
)
POLA_TINDAKAN_DATA_PRIBADI = re.compile(
    r"\b(?:minta|meminta|diminta|isi|mengisi|isikan|lengkapi|melengkapi|"
    r"masukkan|memasukkan|kirim|mengirim|kirimkan|berikan|memberikan|"
    r"unggah|mengunggah|lampirkan|mencantumkan|cantumkan|sertakan|menyertakan|serahkan|"
    r"sampaikan|bagikan|konfirmasi|konfirmasikan|verifikasi|verifikasikan|perbarui|memperbarui|"
    r"submit|provide|send|share|upload|enter|fill(?: out)?|confirm|verify|"
    r"update|reply with|attach|request(?:ing)?|ask(?:ing)? for|"
    r"need|require|wajib|diperlukan)\b",
    re.IGNORECASE,
)
POLA_PENOLAKAN_PERMINTAAN = re.compile(
    r"\b(?:jangan|tidak|bukan|tak|never|don't|do not|does not|will not|"
    r"won't|never ask(?:s|ed)? for)\b[^.!?\n]{0,70}$",
    re.IGNORECASE,
)


def deteksi_permintaan_data_pribadi(teks: str) -> bool:
    """Kenali permintaan eksplisit atas data sensitif, bukan sekadar penyebutannya."""
    for kalimat in re.split(r"(?<=[.!?])\s+|\n+", teks):
        for data in POLA_DATA_PRIBADI_SENSITIF.finditer(kalimat):
            awal = max(0, data.start() - 120)
            akhir = min(len(kalimat), data.end() + 120)
            konteks = kalimat[awal:akhir]
            for tindakan in POLA_TINDAKAN_DATA_PRIBADI.finditer(konteks):
                if abs((awal + tindakan.start()) - data.start()) > 120:
                    continue
                sebelum_tindakan = konteks[:tindakan.start()]
                if POLA_PENOLAKAN_PERMINTAAN.search(sebelum_tindakan):
                    continue
                return True
    return False


def deteksi_percakapan_personal(teks: str) -> bool:
    """Kenali percakapan antarindividu dari gabungan relasi, interaksi, dan rencana."""
    teks_normal = re.sub(r"\s+", " ", teks.casefold())
    pola_relasi = re.compile(
        r"\b(?:halo|hai|hi|hey)\s+[\w'-]+\b|\bapa kabar\b|"
        r"\blama (?:tidak|tak|nggak|gak) (?:bertemu|ketemu|berkabar)\b|"
        r"\bsudah lama (?:tidak|tak|nggak|gak)\b|\bkangen\b|"
        r"\bsince we last (?:met|talked)\b|\blong time no see\b|"
        r"\bhow have you been\b",
        re.IGNORECASE,
    )
    pola_interaksi = re.compile(
        r"\b(?:kalau kamu|jika kamu|kalau tidak sibuk|kabari ya|beri tahu ya|"
        r"siapa tahu kita|mampir|ngopi|ngobrol|berbincang|ketemu|bertemu|"
        r"makan bersama|jalan bersama|main bersama|hang out|catch up|"
        r"grab (?:a )?(?:coffee|lunch|dinner)|meet up|let me know|are you free)\b",
        re.IGNORECASE,
    )
    pola_rencana = re.compile(
        r"\b(?:minggu depan|akhir pekan|weekend|besok|lusa|hari (?:senin|selasa|rabu|kamis|jumat|sabtu|minggu)|"
        r"(?:senin|selasa|rabu|kamis|jumat|sabtu|minggu) sore|pukul \d{1,2}|jam \d{1,2}|"
        r"next week|this weekend|tomorrow|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
        re.IGNORECASE,
    )
    ada_relasi = bool(pola_relasi.search(teks_normal))
    ada_interaksi = bool(pola_interaksi.search(teks_normal))
    ada_rencana = bool(pola_rencana.search(teks_normal))
    return ada_interaksi and (ada_relasi or (ada_rencana and re.search(r"\b(?:saya|aku|kamu|kita|we|i|you)\b", teks_normal)))


def analisis_pola_promosi(teks: str, ada_tautan: bool = False) -> dict:
    """Uraikan pola promosi dan tekanan persuasi; skor ini bukan probabilitas ML."""
    isi = teks.casefold()
    kategori = "Promosi komersial umum"
    pola_sektor = [
        ("Perjudian dan bonus permainan", r"\b(?:free spin|putaran gratis|bonus deposit|deposit \d+%|slot online|slot gacor|mesin slot|permainan slot|pemain baru|taruhan|betting|casino|kasino)\b"),
        ("Produk kesehatan dan penurunan berat badan", r"\b(?:turun \d+\s*kg|berat badan|diet ketat|kapsul|suplemen|ekstrak herbal|obat pelangsing|lunturkan lemak)\b"),
        ("Pinjaman atau kredit cepat", r"\b(?:pinjaman|kredit cepat|dana tunai|langsung cair|tanpa agunan|bi checking|bunga super ringan)\b"),
        ("Investasi atau penghasilan instan", r"\b(?:robot trading|investasi|kebebasan finansial|penghasilan pasif|hasilkan rp|keuntungan hingga|profit harian)\b"),
        ("Jasa pemasaran digital atau SEO", r"\b(?:backlink|ranking 1 google|optimasi website|pengunjung website|blast promosi|database email aktif|jasa seo)\b"),
    ]
    for nama, pola in pola_sektor:
        if re.search(pola, isi, re.I):
            kategori = nama
            break

    indikator = []
    pola_promosi = r"\b(?:promo(?:si)?|diskon|voucher|cashback|bonus|penawaran|paket|kami menawarkan|kami menyediakan|dapatkan|bergabunglah|kampanye promosi|khusus pemesanan|free trial|special offer)\b"
    pola_klaim = (
        r"\b(?:dijamin|terbukti secara klinis|tanpa efek samping|tanpa modal|tanpa agunan|tanpa survei|"
        r"langsung cair|langsung meroket|ranking 1|1000%|300% per minggu|200%|turun \d+\s*kg dalam \d+ hari|"
        r"\d+\s*(?:juta|kg)\b.{0,60}\b(?:setiap hari|per minggu|dalam \d+ (?:hari|menit|jam))|"
        r"\b(?:hasilkan|hasil|keuntungan|pengunjung|omzet|berat badan)\b.{0,70}\b(?:\d+%|\d+\s*(?:juta|kg)|dalam \d+ (?:hari|minggu|menit)|dijamin|terbukti)\b)"
    )
    pola_urgensi = r"\b(?:hari ini|sekarang juga|sekarang|segera|kuota.{0,30}(?:tersisa|terbatas)|\d+ pendaftar tercepat|sebelum kehabisan|khusus.{0,25}hari ini|dalam \d+ (?:menit|jam|hari)|limited time|act now)\b"
    pola_ajakan = r"\b(?:klik(?: di sini| tautan)?|daftar(?: sekarang)?|pesan(?: sekarang)?|ajukan(?: sekarang)?|klaim(?: bonus)?|amankan slot|lihat daftar paket|beli sekarang|bergabunglah|register now|claim now|apply now)\b"
    pola_massal = r"\b(?:yth\.? pelanggan|calon jutawan|pemilik website ?/ ?bisnis|ribuan member|member baru|database email aktif|kampanye promosi|dikirim secara otomatis|unsubscribe|berhenti menerima penawaran)\b"
    pola_data = r"\b(?:isi|mengisi|lengkapi|masukkan|ajukan).{0,45}\b(?:data(?: diri| pribadi| singkat)?|formulir|informasi pribadi|identitas)\b|\b(?:data pribadi|identitas|informasi pribadi)\b.{0,45}\b(?:isi|kirim|masukkan|lengkapi)\b"

    if re.search(pola_promosi, isi, re.I):
        indikator.append({"kode": "spam_bahasa_promosi", "nama": "Bahasa penawaran komersial", "penjelasan": "Email menawarkan produk, layanan, keuntungan, bonus, atau diskon secara langsung.", "tingkat": "sedang"})
    klaim_tidak_realistis = bool(re.search(pola_klaim, isi, re.I))
    if klaim_tidak_realistis:
        indikator.append({"kode": "spam_klaim_luar_biasa", "nama": "Klaim hasil sangat besar atau sangat cepat", "penjelasan": "Pesan menjanjikan hasil finansial, kesehatan, atau performa yang luar biasa dalam waktu singkat atau memakai kata jaminan. Kebenaran klaim tidak dapat dibuktikan dari isi email.", "tingkat": "sedang"})
    urgensi = bool(re.search(pola_urgensi, isi, re.I))
    if urgensi:
        indikator.append({"kode": "spam_urgensi_kelangkaan", "nama": "Urgensi atau kelangkaan penawaran", "penjelasan": "Batas waktu, kuota, atau ajakan bertindak segera dipakai untuk mendorong keputusan cepat.", "tingkat": "sedang"})
    ajakan = bool(re.search(pola_ajakan, isi, re.I))
    if ajakan:
        indikator.append({"kode": "spam_ajakan_tindakan", "nama": "Ajakan mendaftar, membeli, atau mengklaim", "penjelasan": "Email mengarahkan penerima ke langkah promosi seperti mendaftar, mengajukan, membeli, atau mengklaim bonus.", "tingkat": "rendah"})
    massal = bool(re.search(pola_massal, isi, re.I))
    if massal:
        indikator.append({"kode": "spam_audiens_umum", "nama": "Sapaan atau distribusi massal", "penjelasan": "Bahasa menyasar pelanggan/member secara umum atau menyebut kampanye dan distribusi ke banyak penerima.", "tingkat": "rendah"})
    if ada_tautan:
        indikator.append({"kode": "spam_tautan_penawaran", "nama": "Tautan untuk melanjutkan penawaran", "penjelasan": "Pesan menyertakan tautan promosi. Tautan tidak dibuka dan reputasi domain tidak diperiksa.", "tingkat": "sedang"})
    data_diminta = bool(re.search(pola_data, isi, re.I))
    if data_diminta:
        indikator.append({"kode": "spam_pengisian_data", "nama": "Ajakan mengisi data untuk penawaran", "penjelasan": "Promosi meminta pengisian data/formulir. Periksa legalitas penyedia sebelum memberikan informasi; pola ini sendiri belum membuktikan phishing.", "tingkat": "sedang"})

    promosi_eksplisit = bool(re.search(pola_promosi, isi, re.I)) or (ajakan and kategori != "Promosi komersial umum")
    bobot = (
        (15, bool(re.search(pola_promosi, isi, re.I))),
        (20, klaim_tidak_realistis),
        (10, urgensi),
        (10, ajakan),
        (10, massal),
        (10, ada_tautan),
        (10, kategori != "Promosi komersial umum"),
        (5, data_diminta),
    )
    skor = sum(nilai for nilai, terdeteksi in bobot if terdeteksi)
    return {
        "kategori": kategori,
        "skor_sinyal": skor,
        "skor_maksimum": 90,
        "kekuatan": "kuat" if skor >= 60 else "sedang" if skor >= 40 else "terbatas",
        "promosi_eksplisit": promosi_eksplisit,
        "permintaan_data": data_diminta,
        "temuan": indikator,
        "arah_lanjutan": (
            "Perlu kewaspadaan pengumpulan data karena penawaran meminta formulir dan menyertakan tautan. Ini belum cukup untuk memastikan phishing; verifikasi penyedia secara mandiri."
            if data_diminta and ada_tautan else
            "Pola yang terlihat adalah promosi agresif. Klaim/penyedia perlu diverifikasi; belum cukup bukti dari isi ini saja untuk memastikan phishing."
            if kategori != "Promosi komersial umum" and klaim_tidak_realistis else
            "Ini tampak sebagai promosi komersial. Status tidak diinginkan bergantung pada apakah penerima pernah menyetujuinya; periksa tautan secara independen."
        ),
    }


def deteksi_konteks_phishing(teks: str, alamat_pengirim: str = "", tautan: list | None = None) -> list[dict[str, str]]:
    """Cari gabungan sinyal impersonasi, umpan data, OTP, dan tekanan pembayaran."""
    isi = teks.casefold()
    daftar_tautan = tautan or []
    ada_tautan = bool(daftar_tautan) or bool(re.search(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", isi, re.I))
    temuan: list[dict[str, str]] = []

    merek_dikenal = [
        ("J&T Express", r"\bj\s*&\s*t(?:\s+express)?\b|\bjnt\s+express\b", ("jtexpress.com", "jtexpress.co.id", "jtexpress.id", "jet.co.id", "jnt.co.id")),
        ("DANA", r"\b(?:akun|layanan|tim keamanan|aplikasi)\s+dana\b|\btim.{0,30}\bdana\b", ("dana.id", "dana.co.id", "danaindonesia.id")),
        ("Microsoft", r"\bmicrosoft\b", ("microsoft.com", "microsoftonline.com", "microsoft365.com", "office.com", "live.com", "outlook.com")),
    ]
    tujuan_tidak_selaras = []
    domain_pengirim = parseaddr(alamat_pengirim)[1].rsplit("@", 1)[-1].casefold().rstrip(".") if alamat_pengirim else ""
    if not domain_pengirim:
        cocok_pengirim = re.search(r"(?:from|dari)\s*:\s*[^\n<]{0,100}<([^>\s]+@[^>\s]+)>", teks, re.I)
        if cocok_pengirim:
            domain_pengirim = cocok_pengirim.group(1).rsplit("@", 1)[-1].casefold().rstrip(".")

    for nama_merek, pola_merek, domain_resmi in merek_dikenal:
        if not re.search(pola_merek, isi, re.I):
            continue
        pengirim_selaras = any(domain_pengirim == domain or domain_pengirim.endswith("." + domain) for domain in domain_resmi)
        domain_tujuan_ditemukan = False
        mirip_tujuan = False
        for item in daftar_tautan:
            host = (item.get("domain_tanam") or item.get("domain") or "").casefold().rstrip(".")
            if not host:
                continue
            if any(host == domain or host.endswith("." + domain) for domain in domain_resmi):
                domain_tujuan_ditemukan = True
                break
            label_host = re.split(r"[.-]", host)
            for label in label_host:
                if len(label) >= 5 and any(SequenceMatcher(None, label, domain.split(".")[0]).ratio() >= 0.78 for domain in domain_resmi):
                    mirip_tujuan = True
        if daftar_tautan and not domain_tujuan_ditemukan and (domain_pengirim and not pengirim_selaras or mirip_tujuan):
            tujuan_tidak_selaras.append(nama_merek)
            temuan.append({
                "kode": "tautan_merek_tidak_selaras",
                "nama": f"Tautan tidak selaras dengan merek {nama_merek}",
                "penjelasan": f"Isi mengatasnamakan {nama_merek}, tetapi domain pengirim atau tujuan tautan tidak cocok dengan domain layanan tersebut. Ini merupakan sinyal impersonasi; jangan masuk atau memberikan data lewat tautan itu.",
                "tingkat": "tinggi",
            })
            if mirip_tujuan:
                temuan.append({
                    "kode": "domain_mirip_merek",
                    "nama": "Domain tujuan menyerupai nama merek",
                    "penjelasan": "Nama host memiliki kemiripan ejaan dengan merek yang disebut, tetapi bukan domain resminya yang dikenali.",
                    "tingkat": "tinggi",
                })
            break

    konteks_paket = bool(re.search(r"\b(?:paket|kiriman|pengiriman|ekspedisi)\b", isi))
    alamat_diperbarui = bool(re.search(r"\b(?:alamat|alamat pengiriman)\b.{0,90}\b(?:kurang lengkap|tidak lengkap|perbarui|memperbarui|lengkapi|diperbarui)\b|\b(?:perbarui|memperbarui|lengkapi)\b.{0,80}\b(?:alamat|alamat pengiriman)\b", isi))
    if konteks_paket and alamat_diperbarui and ada_tautan:
        temuan.append({
            "kode": "paket_minta_pembaruan_alamat",
            "nama": "Klaim paket tertahan meminta pembaruan alamat lewat tautan",
            "penjelasan": "Pesan menyatakan kiriman bermasalah lalu meminta perubahan alamat melalui tautan. Periksa status hanya lewat aplikasi atau situs kurir yang dibuka sendiri.",
            "tingkat": "tinggi",
        })

    ada_otp = bool(re.search(r"\b(?:otp|kode verifikasi sekali pakai|kode sekali pakai|one[- ]time password)\b", isi))
    konteks_akun_mencurigakan = bool(re.search(r"\b(?:aktivitas mencurigakan|aktivitas masuk|akses akun|perangkat baru|masuk tidak biasa|login tidak biasa)\b", isi))
    if ada_otp:
        temuan.append({
            "kode": "kode_otp_tercantum",
            "nama": "Pesan memuat kode OTP",
            "penjelasan": "OTP adalah rahasia autentikasi. Jangan membagikan atau memasukkannya melalui tautan dari email; kode yang muncul sendiri tidak membuktikan email ini sah.",
            "tingkat": "tinggi",
        })
    if ada_otp and konteks_akun_mencurigakan and ada_tautan and tujuan_tidak_selaras:
        temuan.append({
            "kode": "otp_aktivitas_akun_tautan_asing",
            "nama": "OTP digabung dengan klaim aktivitas akun dan tautan asing",
            "penjelasan": "Kombinasi kode akses, klaim aktivitas akun mencurigakan, dan tautan yang tidak selaras berisiko mengarahkan korban untuk menyetujui akses atau menyerahkan kode.",
            "tingkat": "tinggi",
        })

    konteks_undian = bool(re.search(r"\b(?:pemenang|undian|hadiah utama|terpilih sebagai pemenang|klaim hadiah)\b", isi))
    if konteks_undian and deteksi_permintaan_data_pribadi(teks):
        temuan.append({
            "kode": "undian_meminta_identitas",
            "nama": "Klaim hadiah meminta identitas resmi",
            "penjelasan": "Pesan menyatakan penerima menang tanpa konteks partisipasi yang jelas lalu meminta NIK/identitas untuk pencairan. Jangan kirim identitas untuk klaim tak terduga.",
            "tingkat": "tinggi",
        })

    konteks_tilang = bool(re.search(r"\b(?:e-?tilang|tilang|pelanggaran lalu lintas|pelanggaran berkendara)\b", isi))
    konteks_denda = bool(re.search(r"\b(?:denda|faktur pembayaran|tagihan|menyelesaikan pembayaran)\b", isi))
    ancaman_kendaraan = bool(re.search(r"\b(?:pemblokiran|diblokir|blokir).{0,45}\b(?:stnk|kendaraan|registrasi)\b|\b(?:stnk|kendaraan|registrasi)\b.{0,45}\b(?:pemblokiran|diblokir|blokir)\b", isi))
    if konteks_tilang and konteks_denda and ancaman_kendaraan and ada_tautan:
        tujuan = next(((x.get("domain_tanam") or x.get("domain") or "").casefold() for x in daftar_tautan if x.get("domain_tanam") or x.get("domain")), "")
        domain_pemerintah = tujuan.endswith((".go.id", ".gov.id"))
        if tujuan and not domain_pemerintah:
            temuan.append({
                "kode": "denda_resmi_domain_nonpemerintah",
                "nama": "Ancaman blokir STNK diarahkan ke domain nonpemerintah",
                "penjelasan": "Pesan mengaitkan denda lalu lintas dengan ancaman pemblokiran STNK, tetapi tujuan tautan tidak berada pada domain pemerintah yang dikenali. Verifikasi melalui kanal resmi kepolisian/instansi terkait.",
                "tingkat": "tinggi",
            })

    konteks_masuk_asing = bool(re.search(r"\b(?:aktivitas masuk.{0,60}tidak biasa|masuk.{0,60}lokasi.{0,45}perangkat|perangkat.{0,45}belum pernah digunakan|login.{0,50}mencurigakan)\b", isi))
    ajakan_reset_sandi = bool(re.search(r"\b(?:ubah|mengubah|atur ulang|reset|ganti).{0,55}\b(?:kata sandi|password)\b", isi))
    if konteks_masuk_asing and ajakan_reset_sandi and ada_tautan and "tautan_merek_tidak_selaras" in {x["kode"] for x in temuan}:
        temuan.append({
            "kode": "login_asing_reset_melalui_tautan",
            "nama": "Peringatan login mendorong reset sandi melalui tautan tidak selaras",
            "penjelasan": "Klaim login tak biasa diikuti instruksi mengubah kata sandi lewat tautan yang tidak cocok dengan domain penyedia. Buka pengaturan akun secara mandiri.",
            "tingkat": "tinggi",
        })

    # Hilangkan temuan duplikat jika beberapa pola mendeteksi sinyal yang sama.
    unik = {}
    for item in temuan:
        unik[item["kode"]] = item
    return list(unik.values())


def hitung_skor_keputusan(probabilitas: dict, label_model: str, label_akhir: str, indikator: list) -> dict[str, float]:
    """Buat indeks skor yang mengikuti label hibrida; bukan probabilitas terkalibrasi."""
    if label_model == label_akhir:
        return dict(probabilitas)

    kode_pendukung = {
        "Phishing": {
            "permintaan_data_pribadi", "minta_kredensial", "rekening_pembayaran_berubah",
            "tagihan_dan_tekanan", "verifikasi_identitas_akun", "login_tidak_biasa",
            "ancaman_gangguan_layanan", "tautan_merek_tidak_selaras", "domain_mirip_merek",
            "paket_minta_pembaruan_alamat", "otp_aktivitas_akun_tautan_asing",
            "undian_meminta_identitas", "denda_resmi_domain_nonpemerintah",
            "login_asing_reset_melalui_tautan", "tautan_pengalih", "tautan_tidak_cocok",
        },
        "Normal": {"percakapan_personal"},
    }
    relevan = [
        item for item in indikator
        if item.get("kode") in kode_pendukung.get(label_akhir, set())
        or (label_akhir == "Spam" and str(item.get("kode", "")).startswith("spam_"))
    ]
    bobot_tingkat = {"tinggi": 0.10, "sedang": 0.06, "rendah": 0.03}
    dukungan = min(0.30, sum(bobot_tingkat.get(item.get("tingkat"), 0.03) for item in relevan))
    # Label aturan tetap yang diputuskan sistem; besaran skor naik secara
    # terbatas sesuai bukti pendukung, tidak pernah dipaksakan menjadi 100%.
    skor_label_akhir = min(0.88, 0.56 + dukungan)
    skor_sisa = 1.0 - skor_label_akhir
    label_lain = [kelas for kelas in probabilitas if kelas != label_akhir]
    bobot_lain = sum(float(probabilitas.get(kelas, 0.0)) for kelas in label_lain)
    hasil = {label_akhir: skor_label_akhir}
    for kelas in label_lain:
        proporsi = float(probabilitas.get(kelas, 0.0)) / bobot_lain if bobot_lain else 1 / max(1, len(label_lain))
        hasil[kelas] = skor_sisa * proporsi
    return {kelas: round(skor, 4) for kelas, skor in hasil.items()}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024 + 64 * 1024
BATAS_BERKAS_EMAIL = 10 * 1024 * 1024

model = None
vectorizer = None
if JALUR_MODEL.exists() and JALUR_VECTORIZER.exists():
    try:
        model = joblib.load(JALUR_MODEL)
        vectorizer = joblib.load(JALUR_VECTORIZER)
    except (OSError, ValueError, EOFError) as kesalahan:
        print(f"Artefak model tidak dapat dimuat: {kesalahan}")


def koneksi_database() -> sqlite3.Connection:
    """Buka koneksi SQLite dengan row factory dan foreign keys aktif."""
    koneksi = sqlite3.connect(JALUR_DATABASE, timeout=10)
    koneksi.row_factory = sqlite3.Row
    koneksi.execute("PRAGMA foreign_keys = ON")
    return koneksi


def siapkan_database() -> None:
    JALUR_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with koneksi_database() as koneksi:
        koneksi.execute("""
            CREATE TABLE IF NOT EXISTS riwayat_analisis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dibuat_pada TEXT NOT NULL,
                label TEXT NOT NULL CHECK(label IN ('Normal', 'Spam', 'Phishing')),
                probabilitas_json TEXT NOT NULL,
                indikator_json TEXT NOT NULL,
                sidik_teks TEXT NOT NULL,
                cuplikan_teks TEXT
            )
        """)


def cari_indikator(teks_email: str, alamat_pengirim: str = "", alamat_balasan: str = "") -> list[dict[str, str]]:
    """Cari sinyal ancaman yang menjelaskan analisis gabungan model dan aturan."""
    indikator = []
    aturan = [
        ("mendesak", r"\b(segera|sekarang juga|hari ini|dalam \d+ jam|urgent|immediately|act now|within \d+ hours|deadline|batas waktu|sebelum pukul|by \d{1,2}(?::\d{2})?\s*(?:am|pm|wib)?)\b",
         "Bahasa mendesak", "Pesan mendorong tindakan cepat, pola yang sering dipakai untuk menekan penerima.", "sedang"),
        ("rekening_pembayaran_berubah", r"\b(?:perubahan|mengubah|ganti|berubah|baru|terbaru|updated|changed|revised|dialihkan|pindahkan)\b.{0,85}\b(?:rekening|akun bank|rekening pembayaran|detail pembayaran|payment destination|bank details|payment details|bank account|payment account)\b|\b(?:rekening|akun bank|rekening pembayaran|detail pembayaran|payment destination|bank details|payment details|bank account|payment account)\b.{0,90}\b(?:berubah|baru|diganti|terbaru|perubahan|no longer valid|updated|changed|revised|dialihkan|pindahkan)\b|\babaikan\b.{0,50}\brekening\b",
         "Perubahan rekening pembayaran", "Perubahan rekening pada tagihan perlu diverifikasi melalui nomor atau situs resmi yang sudah diketahui, terutama bila disertai desakan membayar.", "tinggi"),
        ("tagihan_dan_tekanan", r"\b(invoice|tagihan|faktur|pembayaran)\b.{0,100}\b(terlambat|jatuh tempo|batas waktu|segera|denda|biaya keterlambatan|pembatasan layanan|overdue|past due|immediately)\b|\b(terlambat|jatuh tempo|overdue|past due)\b.{0,100}\b(invoice|tagihan|faktur|pembayaran)\b",
         "Tagihan disertai tekanan tindakan", "Tagihan yang menggabungkan tenggat, denda, atau ancaman layanan dapat dipakai untuk mendorong pembayaran tanpa verifikasi.", "tinggi"),
        ("verifikasi_identitas_akun", r"\b(?:verifik\w*|konfirm\w*|confirm\w*|valid\w*|periksa\w*|pemeriksaan|check|perbarui\w*|memperbarui|sinkron\w*|sync\w*)\b.{0,120}\b(?:identitas|informasi|data|profil|akun|account|akses|keamanan|security|kotak surat|mailbox|email|nama pengguna|username|pemulihan|recovery)\b|\b(?:identitas|informasi akun|data akun|profil|akun|account|akses|keamanan|security|kotak surat|mailbox|email|nama pengguna|username|pemulihan|recovery)\b.{0,120}\b(?:verifik\w*|konfirm\w*|confirm\w*|valid\w*|periksa\w*|pemeriksaan|check|perbarui\w*|memperbarui|sinkron\w*|sync\w*)\b",
         "Verifikasi identitas akun", "Permintaan konfirmasi identitas akun perlu dicurigai bila berasal dari pesan tak terduga atau disertai desakan.", "tinggi"),
        ("login_tidak_biasa", r"\b(?:aktivitas|upaya|percobaan|login|sign[ -]?in|masuk)\b.{0,100}\b(?:tidak biasa|mencurigakan|asing|perangkat baru|perangkat yang belum pernah digunakan|belum pernah digunakan sebelumnya|lokasi baru|unusual|suspicious|unknown|new device|new location|not recognized)\b|\b(?:tidak biasa|mencurigakan|unusual|suspicious)\b.{0,55}\b(?:login|sign[ -]?in|aktivitas akun|account activity)\b",
         "Aktivitas login tidak biasa", "Email mengklaim ada aktivitas akun atau login yang tidak biasa; verifikasi melalui aplikasi atau situs resmi yang dibuka sendiri.", "tinggi"),
        ("ancaman_gangguan_layanan", r"\b(gangguan layanan|pembatasan layanan|akses.{0,55}(?:dinonaktifkan|dihentikan|dibatasi|ditutup|dikunci|terkunci)|(?:akun|akses|kotak surat|mailbox|email).{0,65}(?:dinonaktifkan|dihentikan|dibatasi|ditutup|dikunci|terkunci|penonaktifan|locked|suspended|disabled|deactivated)|penonaktifan.{0,35}(?:akun|akses|kotak surat)|(?:lock|suspend|disable|deactivat)[a-z ]{0,45}(?:account|mailbox|email)|service disruption|service interruption|service restriction)\b",
         "Ancaman gangguan layanan", "Pesan mengaitkan tindakan penerima dengan ancaman gangguan atau pembatasan layanan.", "sedang"),
        ("minta_kredensial", r"\b(?:kirim(?:kan)?|mengirim(?:kan)?|berikan|memberikan|masukkan|isi|balas dengan|send|provide|enter|submit|reply with)\b.{0,45}\b(kata sandi|password|otp|pin|kode verifikasi|nomor kartu|data login|credentials)\b|\b(kata sandi|password|otp|pin|kode verifikasi|nomor kartu|data login|credentials)\b.{0,45}\b(?:dikirim|diberikan|dimasukkan|diisi|send|provide|enter|submit)\b",
         "Permintaan data sensitif", "Teks menyebut kredensial atau data finansial yang seharusnya tidak dibagikan lewat email.", "tinggi"),
        ("ancaman_akun", r"\b(ditangguhkan|diblokir|akun.*(ditutup|dinonaktifkan)|suspended|locked account|account.*(closed|disabled))\b",
         "Ancaman terhadap akun", "Ancaman kehilangan akses dapat digunakan untuk memancing respons impulsif.", "sedang"),
        ("lampiran", r"\b(buka|unduh|download).{0,35}\b(lampiran|attachment|file)\b",
         "Ajakan membuka lampiran", "Pesan mengarahkan penerima untuk membuka atau mengunduh lampiran.", "rendah"),
    ]
    for kode, pola, nama, penjelasan, tingkat in aturan:
        cocok = re.search(pola, teks_email, flags=re.IGNORECASE)
        if cocok and kode == "minta_kredensial":
            konteks_sebelum = teks_email[max(0, cocok.start() - 55):cocok.start()]
            if re.search(r"\b(jangan|tidak|bukan|never|don't|do not|mustn't)\b[^.!?\n]{0,50}$", konteks_sebelum, flags=re.I):
                cocok = None
        if cocok:
            indikator.append({"kode": kode, "nama": nama, "penjelasan": penjelasan, "tingkat": tingkat})

    if deteksi_permintaan_data_pribadi(teks_email) and not any(
        item["kode"] == "permintaan_data_pribadi" for item in indikator
    ):
        indikator.append({
            "kode": "permintaan_data_pribadi",
            "nama": "Permintaan data pribadi atau kredensial",
            "penjelasan": "Email meminta penerima mengirimkan atau memasukkan data identitas, kontak, keuangan, atau akses akun. Jangan berikan lewat email atau tautan dari pesan; verifikasi permintaan lewat kanal resmi yang kamu buka sendiri.",
            "tingkat": "tinggi",
        })

    for url in re.findall(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", teks_email, flags=re.IGNORECASE):
        bersih = url.rstrip(".,!?;:")
        parsed = urlparse(bersih if "://" in bersih else f"http://{bersih}")
        host = (parsed.hostname or "").lower()
        if not host:
            continue
        try:
            ipaddress.ip_address(host)
            indikator.append({"kode": "tautan_ip", "nama": "Tautan memakai alamat IP", "penjelasan": "Host URL berupa alamat IP, pola yang patut diperiksa sebelum dibuka.", "tingkat": "tinggi"})
            break
        except ValueError:
            pass
        if host in {"bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "rb.gy"}:
            indikator.append({"kode": "tautan_pendek", "nama": "Tautan dipendekkan", "penjelasan": "Tujuan akhir tautan pendek tidak terlihat dari teks email.", "tingkat": "sedang"})
            break
        if "xn--" in host:
            indikator.append({"kode": "domain_punycode", "nama": "Domain memakai Punycode", "penjelasan": "Domain berisi karakter internasional yang dikodekan; periksa ejaan dan nama domain aslinya dengan cermat.", "tingkat": "sedang"})
            break

    if alamat_pengirim and alamat_balasan:
        domain_pengirim = parseaddr(alamat_pengirim)[1].rsplit("@", 1)[-1].lower()
        domain_balasan = parseaddr(alamat_balasan)[1].rsplit("@", 1)[-1].lower()
        if domain_pengirim and domain_balasan and domain_pengirim != domain_balasan:
            indikator.append({"kode": "domain_balasan_berbeda", "nama": "Domain alamat balasan berbeda", "penjelasan": f"Alamat balasan memakai domain {domain_balasan}, berbeda dari domain pengirim {domain_pengirim}. Pastikan perbedaan ini memang wajar.", "tingkat": "sedang"})
    return indikator


class PengambilTautanHTML(HTMLParser):
    """Ambil URL dari atribut href tanpa pernah memuat atau membuka URL itu."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tautan = []
        self._href = None
        self._teks = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._teks = []

    def handle_data(self, data):
        if self._href is not None:
            self._teks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.tautan.append((self._href.strip(), " ".join(self._teks).strip()))
            self._href = None


def domain_url(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def parse_berkas_email(isi: bytes) -> dict:
    """Parse EML/HTML secara lokal; hanya pilih HTTP(S), abaikan cid/mailto/script."""
    pesan = BytesParser(policy=policy.default).parsebytes(isi)
    bagian_teks, bagian_html, tautan_html, daftar_lampiran = [], [], [], []
    for bagian in pesan.walk():
        if bagian.is_multipart():
            continue
        tipe = bagian.get_content_type().lower()
        nama_lampiran = bagian.get_filename()
        if bagian.get_content_disposition() == "attachment" or nama_lampiran:
            nama_lampiran = Path(str(nama_lampiran or "lampiran")).name[:200]
            payload = bagian.get_payload(decode=True) or b""
            catatan = {"nama": nama_lampiran, "tipe": tipe, "ukuran": len(payload), "status": "Belum diekstrak"}
            if tipe == "application/pdf" or nama_lampiran.lower().endswith(".pdf"):
                try:
                    hasil_pdf = parse_pdf_email(payload)
                    teks_pdf = hasil_pdf.get("teks_isi", "").strip()
                    if teks_pdf:
                        bagian_teks.append(f"[Isi lampiran PDF: {nama_lampiran}]\n{teks_pdf}")
                        tautan_html.extend((item["url"], item.get("teks_tampil", "")) for item in hasil_pdf["tautan"])
                        catatan["status"] = "Teks dan tautan diekstrak"
                    else:
                        catatan["status"] = "PDF gambar/scan; perlu OCR"
                except Exception:
                    catatan["status"] = "PDF tidak dapat dibaca"
            elif tipe.startswith("image/"):
                catatan["status"] = "Gambar terdeteksi; perlu OCR"
            daftar_lampiran.append(catatan)
            continue
        try:
            konten = bagian.get_content()
        except (LookupError, UnicodeDecodeError, AttributeError):
            continue
        if not isinstance(konten, str):
            continue
        if tipe == "text/plain":
            bagian_teks.append(konten)
        elif tipe == "text/html":
            parser = PengambilTautanHTML()
            parser.feed(konten)
            tautan_html.extend(parser.tautan)
            # Jadikan HTML sebagai teks sederhana agar model juga membaca kontennya.
            bagian_html.append(html.unescape(re.sub(r"(?is)<(script|style).*?>.*?</\1>|<[^>]+>", " ", konten)))
    subjek = str(pesan.get("subject", ""))[:500]
    pengirim = str(pesan.get("from", ""))[:320]
    balasan = str(pesan.get("reply-to", ""))[:320]
    # multipart/alternative biasanya mengulang isi yang sama sebagai plain + HTML.
    # Pilih plain text jika berisi; HTML hanya menjadi fallback, sambil tetap mengambil href.
    isi_teks = "\n".join(teks for teks in bagian_teks if teks.strip()).strip()
    if not isi_teks:
        isi_teks = "\n".join(teks for teks in bagian_html if teks.strip()).strip()
    # Ambil URL plain-text, lalu gabungkan dengan href tombol/link pada HTML.
    tautan = list(tautan_html)
    for url in re.findall(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", isi_teks, flags=re.I):
        tautan.append((url.rstrip(".,!?;:"), ""))
    unik, tautan_rapi = set(), []
    for url, label in tautan:
        url = html.unescape(url).strip().rstrip(".,!?;:")
        parsed = urlparse(url if "://" in url else f"https://{url}")
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        kunci = url.lower()
        if kunci in unik:
            continue
        unik.add(kunci)
        host_asli = (parsed.hostname or "").lower()
        # Teks tombol seperti "Resubscribe now" bukan domain. Bandingkan
        # hanya bila teks anchor memang tampak seperti URL/nama host.
        label_tampak_domain = bool(re.match(r"^(?:https?://|www\.)|^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/:?#]|$)", label.strip(), flags=re.I)) if label else False
        host_tampil = domain_url(label) if label_tampak_domain else ""
        tanda = []
        try:
            ipaddress.ip_address(host_asli)
            tanda.append("Tautan memakai alamat IP")
        except ValueError:
            pass
        if host_asli.startswith("xn--") or ".xn--" in host_asli:
            tanda.append("Domain memakai Punycode")
        if host_asli in {"bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "rb.gy"}:
            tanda.append("Tautan dipersingkat; alamat akhir tidak terlihat pada pesan")
        if host_tampil and host_tampil != host_asli and not host_tampil.endswith("." + host_asli):
            tanda.append("Teks tautan berbeda dari domain tujuan")
        domain_tanam = ""
        parameter = parse_qs(parsed.query)
        for nama_parameter in ("q", "url", "u", "target", "redirect", "continue", "next"):
            for nilai_parameter in parameter.get(nama_parameter, []):
                tujuan = urlparse(html.unescape(nilai_parameter))
                if tujuan.scheme.lower() in {"http", "https"} and tujuan.hostname and tujuan.hostname.lower() != host_asli:
                    domain_tanam = tujuan.hostname.lower()
                    tanda.append("Tautan pengalih menyimpan domain tujuan di dalam URL")
                    break
            if domain_tanam:
                break
        tautan_rapi.append({"url": url[:2048], "domain": host_asli[:253], "domain_tanam": domain_tanam[:253], "teks_tampil": label[:300], "indikator": tanda})
    teks_model = f"Subjek: {subjek}\nDari: {pengirim}\nReply-To: {balasan}\n\n{isi_teks}"[:BATAS_PANJANG_EMAIL]
    return {"teks_email": teks_model.strip(), "alamat_pengirim": pengirim, "alamat_balasan": balasan,
            "subjek": subjek, "tautan": tautan_rapi, "teks_konten": isi_teks,
            "lampiran": daftar_lampiran}


def parse_pdf_email(isi: bytes) -> dict:
    """Ekstrak teks dan tautan PDF tanpa menjalankan konten aktif atau membuka URL."""
    pembaca = PdfReader(io.BytesIO(isi), strict=False)
    if pembaca.is_encrypted:
        try:
            if not pembaca.decrypt(""):
                raise ValueError("PDF dilindungi kata sandi dan tidak dapat dibaca.")
        except Exception as kesalahan:
            raise ValueError("PDF dilindungi kata sandi dan tidak dapat dibaca.") from kesalahan
    if len(pembaca.pages) > 100:
        raise ValueError("PDF maksimal 100 halaman untuk menjaga pemindaian tetap ringan.")
    bagian_teks, tautan = [], []
    for halaman in pembaca.pages:
        bagian_teks.append(halaman.extract_text() or "")
        for anotasi in halaman.get("/Annots", []):
            aksi = anotasi.get_object().get("/A")
            if aksi and aksi.get("/URI"):
                url = str(aksi.get("/URI")).strip()
                parsed = urlparse(url)
                if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
                    tautan.append({"url": url[:2048], "domain": parsed.hostname.lower()[:253],
                                   "teks_tampil": "Tautan PDF", "indikator": []})
    teks = "\n".join(bagian_teks).strip()
    for url in re.findall(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", teks, flags=re.I):
        url = url.rstrip(".,!?;:")
        domain = domain_url(url)
        if domain and not any(item["url"] == url for item in tautan):
            tautan.append({"url": url[:2048], "domain": domain, "teks_tampil": "", "indikator": []})
    metadata_pdf = pembaca.metadata or {}
    subjek = str(metadata_pdf.get("/Subject") or "")[:500]
    judul = str(metadata_pdf.get("/Title") or "")[:500]
    teks_model = f"Subjek dokumen: {subjek}\nJudul dokumen: {judul}\n\n{teks}"[:BATAS_PANJANG_EMAIL].strip()
    return {"teks_email": teks_model, "teks_isi": teks, "alamat_pengirim": "", "alamat_balasan": "",
            "subjek": subjek or judul, "tautan": tautan}


def jalankan_analisis(teks_email: str, alamat_pengirim: str = "", alamat_balasan: str = "", tautan: list | None = None):
    nilai = model.predict_proba(vectorizer.transform([teks_email]))[0]
    probabilitas = {str(label): round(float(skor), 4) for label, skor in zip(model.classes_, nilai)}
    label_model = max(probabilitas, key=probabilitas.get)
    label = label_model
    indikator = cari_indikator(teks_email, alamat_pengirim, alamat_balasan)
    # Proses temuan tautan sebelum keputusan gabungan agar URL pengalih yang
    # menyembunyikan domain tujuan ikut dipertimbangkan, bukan hanya ditampilkan.
    if tautan:
        for item in tautan:
            for nama in item.get("indikator", []):
                kode = "tautan_tidak_cocok" if "berbeda" in nama else "tautan_tujuan"
                if "pengalih" in nama.lower() or item.get("domain_tanam"):
                    kode = "tautan_pengalih"
                if not any(x["kode"] == kode and x.get("nama") == nama for x in indikator):
                    indikator.append({"kode": kode, "nama": nama,
                        "penjelasan": f"Tautan memakai domain pengalih {item.get('domain', 'tidak diketahui')} dan menyimpan alamat tujuan di dalam parameternya. Check Mail tidak membuka tautan atau memverifikasi situs tujuan.",
                        "tingkat": "tinggi" if kode in {"tautan_tidak_cocok", "tautan_pengalih"} else "sedang"})
    kode_indikator = {item["kode"] for item in indikator}
    ada_tautan_email = bool(tautan) or bool(
        re.search(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", teks_email, flags=re.I)
    )
    profil_spam = analisis_pola_promosi(teks_email, ada_tautan_email)
    # Analisis kontekstual memakai relasi klaim merek, pengirim, tujuan tautan,
    # serta maksud pesan. Sinyalnya ditambahkan sebelum keputusan akhir agar
    # penjelasan dan klasifikasi memakai sumber temuan yang sama.
    temuan_kontekstual = deteksi_konteks_phishing(teks_email, alamat_pengirim, tautan)
    for temuan in temuan_kontekstual:
        if not any(item["kode"] == temuan["kode"] for item in indikator):
            indikator.append(temuan)
    kode_indikator = {item["kode"] for item in indikator}
    kode_temuan = {item["kode"] for item in indikator}
    for temuan in profil_spam["temuan"]:
        if temuan["kode"] not in kode_temuan:
            indikator.append(temuan)
            kode_temuan.add(temuan["kode"])
    kode_indikator = {item["kode"] for item in indikator}
    alasan_label = "Kategori mengikuti prediksi model teks."
    jenis_penyesuaian = None
    # Keputusan akhir mengutamakan pola tindakan berisiko yang berpadu:
    # data sensitif, perubahan rekening, atau akun terancam + verifikasi/link.
    pemicu_phishing_kontekstual = {
        "tautan_merek_tidak_selaras", "domain_mirip_merek", "paket_minta_pembaruan_alamat",
        "otp_aktivitas_akun_tautan_asing", "undian_meminta_identitas",
        "denda_resmi_domain_nonpemerintah", "login_asing_reset_melalui_tautan",
    }
    if "permintaan_data_pribadi" in kode_indikator or "minta_kredensial" in kode_indikator:
        label = "Phishing"
        jenis_penyesuaian = "aturan_risiko"
        alasan_label = "Email meminta data pribadi atau akses akun. Check Mail menaikkan hasil akhir menjadi Phishing berdasarkan aturan risiko, meskipun teks model mentah memilih Spam atau Normal. Jangan kirim data; verifikasi melalui kanal resmi."
    elif kode_indikator.intersection(pemicu_phishing_kontekstual):
        label = "Phishing"
        jenis_penyesuaian = "aturan_risiko"
        dasar_phishing = [item["nama"] for item in indikator if item["kode"] in pemicu_phishing_kontekstual]
        rincian_phishing = "; ".join(dasar_phishing[:3])
        alasan_label = (
            f"Sinyal utama: {rincian_phishing}. Email menggabungkan konteks penyamaran/umpan tindakan "
            "dengan tujuan tautan yang tidak selaras atau ancaman yang meminta tindakan sensitif. "
            "Sinyal ini lebih kuat daripada gaya bahasa promosi. "
            "Jangan ikuti tautan; verifikasi melalui aplikasi atau kanal resmi yang dibuka sendiri. "
            "Skor ML mentah tetap ditampilkan terpisah."
        )
    elif "rekening_pembayaran_berubah" in kode_indikator and kode_indikator.intersection({"mendesak", "tagihan_dan_tekanan", "ancaman_gangguan_layanan", "tautan_pengalih", "tautan_tidak_cocok"}):
        label = "Phishing"
        jenis_penyesuaian = "aturan_risiko"
        alasan_label = "Aturan risiko mendeteksi perubahan tujuan pembayaran yang disertai tekanan atau ancaman gangguan layanan. Prediksi model teks mentah tetap ditampilkan; verifikasi melalui kanal resmi."
    elif ("verifikasi_identitas_akun" in kode_indikator and "ancaman_gangguan_layanan" in kode_indikator and ada_tautan_email) or (
        "login_tidak_biasa" in kode_indikator and "verifikasi_identitas_akun" in kode_indikator and ada_tautan_email
    ):
        label = "Phishing"
        jenis_penyesuaian = "aturan_risiko"
        alasan_label = "Email menggabungkan klaim keamanan/aktivitas akun, desakan atau ancaman akses, dan tautan untuk melakukan verifikasi. Kombinasi ini berisiko phishing; buka aplikasi atau situs resmi secara mandiri, jangan lewat tautan email. Skor ML mentah tetap ditampilkan terpisah."
    elif label_model != "Phishing" and profil_spam["promosi_eksplisit"] and profil_spam["skor_sinyal"] >= 40:
        label = "Spam"
        jenis_penyesuaian = "promosi_komersial"
        alasan_label = (
            f"Isi sesuai pola promosi komersial ({profil_spam['kategori'].lower()}) dengan "
            f"{len(profil_spam['temuan'])} sinyal persuasi/distribusi. Indeks sinyal promosi "
            f"{profil_spam['skor_sinyal']}/{profil_spam['skor_maksimum']} bukan probabilitas atau bukti phishing."
        )
    elif label_model == "Spam" and not tautan and not kode_indikator.intersection({
        "mendesak", "rekening_pembayaran_berubah", "tagihan_dan_tekanan", "verifikasi_identitas_akun",
        "ancaman_gangguan_layanan", "minta_kredensial", "permintaan_data_pribadi", "ancaman_akun",
        "tautan_ip", "tautan_pendek", "domain_punycode", "domain_balasan_berbeda", "tautan_tidak_cocok",
    }) and not re.search(
        r"\b(?:promo|promosi|diskon|voucher|cashback|giveaway|flash sale|penawaran khusus|"
        r"beli sekarang|daftar sekarang|subscribe now|buy now|shop now|limited offer|discount code)\b",
        teks_email,
        flags=re.I,
    ) and deteksi_percakapan_personal(teks_email):
        label = "Normal"
        jenis_penyesuaian = "konteks_percakapan"
        alasan_label = (
            "Model teks mentah memilih Spam, tetapi pesan menunjukkan percakapan personal "
            "dengan interaksi dan rencana yang spesifik. Tidak ditemukan tautan, ajakan promosi, "
            "atau indikator risiko tinggi. Hasil akhir disesuaikan menjadi Normal; tetap pastikan "
            "alamat pengirim memang dikenal."
        )
        indikator.append({
            "kode": "percakapan_personal",
            "nama": "Konteks percakapan personal",
            "penjelasan": (
                "Terdapat sapaan atau konteks relasi personal, ajakan berinteraksi, dan rencana "
                "yang spesifik. Ini mendukung konteks korespondensi biasa, tetapi bukan verifikasi identitas pengirim."
            ),
            "tingkat": "rendah",
        })
    skor_keputusan = hitung_skor_keputusan(probabilitas, label_model, label, indikator)
    id_riwayat = simpan_analisis(teks_email, label, probabilitas, indikator)
    ringkasan_tautan = [
        {"domain": item.get("domain", ""), "teks_tampil": item.get("teks_tampil", ""),
         "indikator": list(item.get("indikator", []))}
        for item in (tautan or [])
    ]
    return {"label": label, "label_model": label_model, "alasan_label": alasan_label,
            "jenis_penyesuaian": jenis_penyesuaian,
            "probabilitas": probabilitas, "skor_keputusan": skor_keputusan,
            "indikator": indikator, "profil_spam": profil_spam,
            "tautan": ringkasan_tautan, "catatan": "Skor model adalah estimasi teks, bukan jaminan keamanan."}, id_riwayat


def simpan_analisis(teks_email: str, label: str, probabilitas: dict, indikator: list) -> int:
    """Simpan metadata analisis tanpa menyimpan badan email utuh."""
    sidik = hashlib.sha256(teks_email.encode("utf-8")).hexdigest()
    cuplikan = re.sub(r"\s+", " ", teks_email).strip()[:180]
    with koneksi_database() as koneksi:
        cursor = koneksi.execute(
            "INSERT INTO riwayat_analisis (dibuat_pada,label,probabilitas_json,indikator_json,sidik_teks,cuplikan_teks) VALUES (?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), label, json.dumps(probabilitas, ensure_ascii=False),
             json.dumps(indikator, ensure_ascii=False), sidik, cuplikan),
        )
        return int(cursor.lastrowid)


@app.get("/")
def halaman_utama():
    return send_from_directory(DIREKTORI_PROYEK / "frontend", "index.html")


@app.get("/<path:nama_berkas>")
def berkas_frontend(nama_berkas: str):
    return send_from_directory(DIREKTORI_PROYEK / "frontend", nama_berkas)


@app.post("/api/analyze")
def analisis_email():
    if model is None or vectorizer is None:
        return jsonify(berhasil=False, kesalahan="Model belum tersedia. Jalankan: python backend/train_model.py"), 503
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("teks_email"), str):
        return jsonify(berhasil=False, kesalahan="Kirim JSON dengan properti teks_email berupa teks."), 400
    teks_email = data["teks_email"].strip()
    if not teks_email:
        return jsonify(berhasil=False, kesalahan="Teks email tidak boleh kosong."), 400
    if len(teks_email) > BATAS_PANJANG_EMAIL:
        return jsonify(berhasil=False, kesalahan=f"Teks email melebihi batas {BATAS_PANJANG_EMAIL:,} karakter."), 413
    alamat_pengirim = data.get("alamat_pengirim", "")
    alamat_balasan = data.get("alamat_balasan", "")
    if not isinstance(alamat_pengirim, str) or not isinstance(alamat_balasan, str):
        return jsonify(berhasil=False, kesalahan="Alamat pengirim dan balasan harus berupa teks."), 400
    alamat_pengirim = alamat_pengirim.strip()
    alamat_balasan = alamat_balasan.strip()
    for nama, alamat in (("pengirim", alamat_pengirim), ("balasan", alamat_balasan)):
        if len(alamat) > 320:
            return jsonify(berhasil=False, kesalahan=f"Alamat {nama} terlalu panjang."), 400
        if alamat and not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+|[^<>]+<[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+>", alamat):
            return jsonify(berhasil=False, kesalahan=f"Format alamat {nama} tidak dikenali. Masukkan nama@domain.com."), 400
    try:
        hasil, id_riwayat = jalankan_analisis(teks_email, alamat_pengirim, alamat_balasan)
    except sqlite3.Error:
        app.logger.exception("Gagal menyimpan riwayat analisis")
        return jsonify(berhasil=False, kesalahan="Analisis gagal disimpan ke riwayat lokal."), 500
    return jsonify(berhasil=True, hasil=hasil, id_riwayat=id_riwayat)


@app.post("/api/analyze-file")
def analisis_berkas_email():
    if model is None or vectorizer is None:
        return jsonify(berhasil=False, kesalahan="Model belum tersedia. Jalankan backend/train_model.py."), 503
    berkas = request.files.get("berkas_email")
    if not berkas or not berkas.filename:
        return jsonify(berhasil=False, kesalahan="Pilih berkas .eml atau .txt terlebih dahulu."), 400
    nama = berkas.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    ekstensi = Path(nama).suffix.lower()
    if ekstensi not in {".eml", ".txt", ".pdf"}:
        return jsonify(berhasil=False, kesalahan="Format yang didukung: .eml, .txt, atau .pdf."), 415
    isi = berkas.stream.read(BATAS_BERKAS_EMAIL + 1)
    if len(isi) > BATAS_BERKAS_EMAIL:
        return jsonify(berhasil=False, kesalahan="Berkas email terlalu besar (maksimal 1 MB)."), 413
    try:
        if ekstensi == ".eml":
            data = parse_berkas_email(isi)
        elif ekstensi == ".pdf":
            data = parse_pdf_email(isi)
            data["teks_konten"] = data.get("teks_isi", "")
            data["lampiran"] = [{"nama": Path(nama).name, "tipe": "application/pdf", "ukuran": len(isi),
                                  "status": "Teks dan tautan diekstrak" if data["teks_konten"].strip() else "PDF gambar/scan; perlu OCR"}]
        else:
            teks = isi.decode("utf-8-sig", errors="replace").strip()
            data = {"teks_email": teks, "teks_konten": teks, "alamat_pengirim": "", "alamat_balasan": "", "subjek": "", "tautan": [], "lampiran": []}
            for url in re.findall(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", teks, flags=re.I):
                url = url.rstrip(".,!?;:")
                host = domain_url(url)
                if host and not any(x["url"] == url for x in data["tautan"]):
                    data["tautan"].append({"url": url, "domain": host, "teks_tampil": "", "indikator": []})
        teks = data["teks_email"].strip()
        if not data.get("teks_konten", "").strip():
            lampiran = data.get("lampiran", [])
            perlu_ocr = any("perlu OCR" in item.get("status", "") for item in lampiran)
            if perlu_ocr:
                pesan = "Isi pesan tidak memiliki teks yang dapat dianalisis; lampiran berupa PDF/gambar hasil scan. OCR belum tersedia, jadi Check Mail tidak membuat prediksi dari header kosong."
            elif ekstensi == ".pdf":
                pesan = "Teks tidak dapat diekstrak dari PDF. Jika ini hasil scan/foto, OCR belum tersedia; coba PDF dengan teks yang dapat dipilih."
            else:
                pesan = "Isi teks tidak ditemukan di berkas email. Check Mail tidak membuat prediksi dari header saja."
            return jsonify(berhasil=False, kesalahan=pesan, lampiran=lampiran), 422
        hasil, id_riwayat = jalankan_analisis(teks, data["alamat_pengirim"], data["alamat_balasan"], data["tautan"])
    except Exception as kesalahan:
        app.logger.exception("Gagal membaca atau menganalisis berkas email")
        if isinstance(kesalahan, sqlite3.Error):
            return jsonify(berhasil=False, kesalahan="Analisis gagal disimpan ke riwayat lokal."), 500
        return jsonify(berhasil=False, kesalahan=str(kesalahan) or "Berkas tidak dapat dibaca."), 400
    return jsonify(berhasil=True, hasil=hasil, metadata={"nama_berkas": Path(nama).name,
                   "subjek": data["subjek"], "alamat_pengirim": data["alamat_pengirim"],
                   "alamat_balasan": data["alamat_balasan"], "lampiran": data.get("lampiran", [])},
                   teks_diperiksa=teks, id_riwayat=id_riwayat)


@app.get("/api/history")
def ambil_riwayat():
    try:
        limit = min(max(int(request.args.get("limit", "20")), 1), BATAS_RIWAYAT)
    except ValueError:
        return jsonify(berhasil=False, kesalahan="Parameter limit harus berupa angka."), 400
    with koneksi_database() as koneksi:
        baris = koneksi.execute("SELECT id,dibuat_pada,label,probabilitas_json,indikator_json,cuplikan_teks FROM riwayat_analisis ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    hasil = [{"id": r["id"], "dibuat_pada": r["dibuat_pada"], "label": r["label"],
              "probabilitas": json.loads(r["probabilitas_json"]), "indikator": json.loads(r["indikator_json"]),
              "cuplikan_teks": r["cuplikan_teks"]} for r in baris]
    return jsonify(berhasil=True, riwayat=hasil)


@app.get("/api/stats")
def ambil_statistik():
    with koneksi_database() as koneksi:
        total = koneksi.execute("SELECT COUNT(*) FROM riwayat_analisis").fetchone()[0]
        baris = koneksi.execute("SELECT label,COUNT(*) AS jumlah FROM riwayat_analisis GROUP BY label").fetchall()
    per_label = {label: 0 for label in LABEL_VALID}
    per_label.update({r["label"]: r["jumlah"] for r in baris})
    return jsonify(berhasil=True, total=total, per_label=per_label)


@app.delete("/api/history")
def hapus_riwayat():
    with koneksi_database() as koneksi:
        koneksi.execute("DELETE FROM riwayat_analisis")
    return jsonify(berhasil=True, pesan="Riwayat lokal telah dihapus.")


@app.errorhandler(413)
def permintaan_terlalu_besar(_kesalahan):
    return jsonify(berhasil=False, kesalahan="Ukuran berkas melebihi batas 10 MB."), 413


siapkan_database()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

