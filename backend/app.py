"""REST API lokal Check Mail."""
from __future__ import annotations

import hashlib
import html
import http.client
import io
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import ssl
import sqlite3
import sys
import time
from email import policy
from email.parser import BytesParser
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse

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
    r"unggah|mengunggah|lampirkan|mencantumkan|cantumkan|serahkan|"
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

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024 + 64 * 1024
BATAS_BERKAS_EMAIL = 10 * 1024 * 1024
BATAS_REDIRECT = 5
BATAS_WAKTU_REDIRECT = 30

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


def validasi_url_publik(url: str) -> tuple[str, int, str, str]:
    """Validasi URL dan pin ke alamat IP publik agar pemeriksaan tak menjadi SSRF lokal."""
    parsed = urlparse(url)
    skema = parsed.scheme.lower()
    if skema not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL harus HTTP/HTTPS publik dan tidak boleh berisi kredensial.")
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    port = parsed.port or (443 if skema == "https" else 80)
    if port != (443 if skema == "https" else 80):
        raise ValueError("Pemeriksaan hanya mengizinkan port web standar 80/443.")
    try:
        alamat = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            hasil_dns = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as kesalahan:
            raise ValueError("Domain tidak dapat ditemukan melalui DNS.") from kesalahan
        alamat = list({ipaddress.ip_address(item[4][0].split("%", 1)[0]) for item in hasil_dns})
    if not alamat or any(not ip.is_global for ip in alamat):
        raise ValueError("Alamat tujuan bukan IP publik; koneksi diblokir demi keamanan lokal.")
    return skema, port, host, str(alamat[0])


def periksa_redirect_url(url: str) -> dict:
    """Ikuti hanya header redirect dengan HEAD; tidak mengunduh isi halaman."""
    if len(url) > 2048:
        raise ValueError("URL terlalu panjang untuk diperiksa.")
    alamat_sekarang = url
    kunjungan = set()
    rantai = []
    tenggat = time.monotonic() + BATAS_WAKTU_REDIRECT
    konteks_tls = ssl.create_default_context()
    for _ in range(BATAS_REDIRECT + 1):
        if alamat_sekarang in kunjungan:
            return {"rantai": rantai, "url_akhir": alamat_sekarang, "status": "Siklus redirect terdeteksi", "terblokir": True}
        kunjungan.add(alamat_sekarang)
        skema, port, host, ip_tujuan = validasi_url_publik(alamat_sekarang)
        parsed = urlparse(alamat_sekarang)
        sisa = tenggat - time.monotonic()
        if sisa <= 0:
            return {"rantai": rantai, "url_akhir": alamat_sekarang, "status": "Batas waktu pemeriksaan tercapai", "terblokir": False}
        path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
        target = f"{path}?{query}" if query else path
        host_header = f"[{host}]" if ":" in host else host
        if port != (443 if skema == "https" else 80):
            host_header = f"{host_header}:{port}"
        def kirim_permintaan(metode: str) -> tuple[int, str | None]:
            sock = socket.create_connection((ip_tujuan, port), timeout=min(5.0, sisa))
            try:
                sock.settimeout(min(5.0, sisa))
                if skema == "https":
                    sock = konteks_tls.wrap_socket(sock, server_hostname=host)
                    sock.settimeout(min(5.0, sisa))
                tambahan = "Range: bytes=0-0\r\n" if metode == "GET" else ""
                permintaan = (f"{metode} {target} HTTP/1.1\r\nHost: {host_header}\r\n"
                              "User-Agent: CheckMail-Redirect-Check/1.0\r\n"
                              f"Accept: */*\r\n{tambahan}Connection: close\r\n\r\n")
                sock.sendall(permintaan.encode("ascii"))
                respons = http.client.HTTPResponse(sock)
                respons.begin()
                return respons.status, respons.getheader("Location")
            finally:
                sock.close()

        metode = "HEAD"
        status, lokasi = kirim_permintaan(metode)
        if status in {405, 501}:
            # Beberapa situs menolak HEAD. Coba GET Range satu byte, tanpa membaca body.
            metode = "GET Range"
            status, lokasi = kirim_permintaan("GET")
        rantai.append({"url": alamat_sekarang, "kode_http": status, "metode": metode, "lokasi": lokasi or ""})
        if status in {405, 501}:
            return {"rantai": rantai, "url_akhir": alamat_sekarang,
                    "status": f"Server menolak {metode}; tujuan redirect belum dapat dipastikan (HTTP {status})", "terblokir": False}
        if status >= 400:
            return {"rantai": rantai, "url_akhir": alamat_sekarang,
                    "status": f"Server membatasi pemeriksaan; tujuan redirect belum dapat dipastikan (HTTP {status})", "terblokir": False}
        if status not in {301, 302, 303, 307, 308} or not lokasi:
            return {"rantai": rantai, "url_akhir": alamat_sekarang, "status": f"HTTP {status}; tidak ada redirect lanjutan", "terblokir": False}
        tujuan = urljoin(alamat_sekarang, lokasi)
        try:
            validasi_url_publik(tujuan)
        except ValueError as kesalahan:
            rantai.append({"url": tujuan[:2048], "kode_http": None, "lokasi": ""})
            return {"rantai": rantai, "url_akhir": tujuan[:2048], "status": f"Redirect diblokir: {kesalahan}", "terblokir": True}
        alamat_sekarang = tujuan
    return {"rantai": rantai, "url_akhir": alamat_sekarang, "status": f"Batas {BATAS_REDIRECT} redirect tercapai", "terblokir": False}


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
            tanda.append("Tautan pendek; tujuan akhir belum diperiksa")
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
    # Proses temuan tautan sebelum keputusan gabungan agar redirect yang
    # menyembunyikan domain tujuan ikut dipertimbangkan, bukan hanya ditampilkan.
    if tautan:
        for item in tautan:
            for nama in item.get("indikator", []):
                kode = "tautan_tidak_cocok" if "berbeda" in nama else "tautan_tujuan"
                if "pengalih" in nama.lower() or item.get("domain_tanam"):
                    kode = "tautan_pengalih"
                if not any(x["kode"] == kode and x.get("nama") == nama for x in indikator):
                    domain_tujuan = item.get("domain_tanam") or item.get("domain", "tidak diketahui")
                    indikator.append({"kode": kode, "nama": nama,
                        "penjelasan": f"Tautan memakai domain {item.get('domain', 'tidak diketahui')} dan menyimpan/menunjukkan tujuan {domain_tujuan}. Check Mail tidak membuka tautan atau mengikuti redirect.",
                        "tingkat": "tinggi" if kode in {"tautan_tidak_cocok", "tautan_pengalih"} else "sedang"})
    kode_indikator = {item["kode"] for item in indikator}
    ada_tautan_email = bool(tautan) or bool(
        re.search(r"(?:https?://|www\.)[^\s<>\]\[(){}\"']+", teks_email, flags=re.I)
    )
    alasan_label = "Kategori mengikuti prediksi model teks."
    # Keputusan akhir mengutamakan pola tindakan berisiko yang berpadu:
    # data sensitif, perubahan rekening, atau akun terancam + verifikasi/link.
    if "permintaan_data_pribadi" in kode_indikator or "minta_kredensial" in kode_indikator:
        label = "Phishing"
        alasan_label = "Email meminta data pribadi atau akses akun. Check Mail menaikkan hasil akhir menjadi Phishing berdasarkan aturan risiko, meskipun teks model mentah memilih Spam atau Normal. Jangan kirim data; verifikasi melalui kanal resmi."
    elif "rekening_pembayaran_berubah" in kode_indikator and kode_indikator.intersection({"mendesak", "tagihan_dan_tekanan", "ancaman_gangguan_layanan", "tautan_pengalih", "tautan_tidak_cocok"}):
        label = "Phishing"
        alasan_label = "Aturan risiko mendeteksi perubahan tujuan pembayaran yang disertai tekanan atau ancaman gangguan layanan. Prediksi model teks mentah tetap ditampilkan; verifikasi melalui kanal resmi."
    elif ("verifikasi_identitas_akun" in kode_indikator and "ancaman_gangguan_layanan" in kode_indikator and ada_tautan_email) or (
        "login_tidak_biasa" in kode_indikator and "verifikasi_identitas_akun" in kode_indikator and ada_tautan_email
    ):
        label = "Phishing"
        alasan_label = "Email menggabungkan klaim keamanan/aktivitas akun, desakan atau ancaman akses, dan tautan untuk melakukan verifikasi. Kombinasi ini berisiko phishing; buka aplikasi atau situs resmi secara mandiri, jangan lewat tautan email. Skor ML mentah tetap ditampilkan terpisah."
    elif label_model == "Spam" and not tautan and not kode_indikator.intersection({
        "mendesak", "rekening_pembayaran_berubah", "tagihan_dan_tekanan", "verifikasi_identitas_akun",
        "ancaman_gangguan_layanan", "minta_kredensial", "ancaman_akun", "tautan_ip", "tautan_pendek",
        "domain_punycode", "domain_balasan_berbeda", "tautan_tidak_cocok",
    }) and re.search(r"\b(jadwal konsultasi|jadwal kuliah|konfirmasi jadwal|pertemuan akan dilaksanakan|agenda rapat|draft proposal|meeting scheduled)\b", teks_email, flags=re.I):
        label = "Normal"
        alasan_label = "Model teks mentah memilih Spam, tetapi isi menunjukkan konteks penjadwalan/kegiatan rutin tanpa indikator risiko atau tautan. Tetap pastikan email ini memang diharapkan."
    id_riwayat = simpan_analisis(teks_email, label, probabilitas, indikator)
    return {"label": label, "label_model": label_model, "alasan_label": alasan_label,
            "probabilitas": probabilitas, "indikator": indikator,
            "tautan": tautan or [], "catatan": "Skor model adalah estimasi teks, bukan jaminan keamanan."}, id_riwayat


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


@app.post("/api/check-redirect")
def periksa_redirect():
    """Periksa redirect hanya setelah pengguna menekan tombol pada tautan tertentu."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    if not isinstance(url, str) or not url.strip():
        return jsonify(berhasil=False, kesalahan="URL tidak tersedia."), 400
    try:
        hasil = periksa_redirect_url(url.strip())
    except ValueError as kesalahan:
        return jsonify(berhasil=False, kesalahan=str(kesalahan)), 400
    except (OSError, ssl.SSLError, http.client.HTTPException) as kesalahan:
        app.logger.info("Pemeriksaan redirect gagal: %s", kesalahan)
        return jsonify(berhasil=False, kesalahan="Situs tidak merespons pemeriksaan redirect atau koneksi berakhir."), 502
    return jsonify(berhasil=True, hasil=hasil, catatan="Pemeriksaan menghubungi domain redirect dengan HEAD atau GET Range; isi halaman tidak dibaca.")


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

