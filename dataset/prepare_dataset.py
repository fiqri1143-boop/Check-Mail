"""Siapkan dataset tiga kelas Check Mail secara deterministik dari arsip sumber."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import random
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

DIREKTORI_DATASET = Path(__file__).resolve().parent
JALUR_ARSIP_PENGGUNA = DIREKTORI_DATASET / "emails-source.zip"
JALUR_ARSIP_SINTETIS = DIREKTORI_DATASET / "dataset_email.zip"
JALUR_MEAJOR = DIREKTORI_DATASET / "meajor_cleaned_preprocessed.csv"
URL_MEAJOR = "https://zenodo.org/api/records/18471483/files/meajor_cleaned_preprocessed.csv/content"
MD5_MEAJOR = "aa8f59e96787cbd696c0b650e5400dc9"
BATAS_PER_SALURAN = 4_000
SEED = 42
SALURAN_VALID = {"trec5", "trec6", "trec7"}


def hitung_md5(jalur: Path) -> str:
    """Hitung checksum dalam potongan kecil agar RAM tetap rendah."""
    md5 = hashlib.md5(usedforsecurity=False)
    with jalur.open("rb") as berkas:
        while potongan := berkas.read(1024 * 1024):
            md5.update(potongan)
    return md5.hexdigest()


def unduh_meajor() -> None:
    """Ambil CSV sumber MeAJOR hanya saat belum tersedia secara lokal."""
    if JALUR_MEAJOR.exists():
        sidik = hitung_md5(JALUR_MEAJOR)
        if sidik == MD5_MEAJOR:
            return
        JALUR_MEAJOR.unlink()
    permintaan = urllib.request.Request(URL_MEAJOR, headers={"User-Agent": "CheckMail/1.0"})
    jalur_sementara = JALUR_MEAJOR.with_suffix(".csv.part")
    try:
        print("Mengunduh dataset MeAJOR dari Zenodo (sekitar 191 MB)...", flush=True)
        with urllib.request.urlopen(permintaan, timeout=180) as respons, jalur_sementara.open("wb") as berkas:
            while potongan := respons.read(1024 * 1024):
                berkas.write(potongan)
        sidik = hitung_md5(jalur_sementara)
        if sidik != MD5_MEAJOR:
            raise ValueError("Checksum CSV MeAJOR tidak cocok; unduhan mungkin terputus atau berubah.")
        os.replace(jalur_sementara, JALUR_MEAJOR)
        print("Unduhan tervalidasi.", flush=True)
    finally:
        jalur_sementara.unlink(missing_ok=True)


def kunci_teks(teks: str) -> str:
    """Buat sidik teks stabil untuk menghapus duplikasi persis."""
    normal = " ".join(teks.casefold().split())
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def siapkan_dataset() -> None:
    if not JALUR_ARSIP_PENGGUNA.exists():
        raise FileNotFoundError(f"Arsip awal tidak ditemukan: {JALUR_ARSIP_PENGGUNA}")
    unduh_meajor()

    terpilih: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    jumlah_ditemukan: Counter[tuple[str, str]] = Counter()
    pembangkit = random.Random(SEED)
    with JALUR_MEAJOR.open("r", encoding="utf-8-sig", newline="") as berkas:
        pembaca = csv.DictReader(berkas)
        kolom_wajib = {"subject", "body", "source", "label"}
        if not kolom_wajib.issubset(pembaca.fieldnames or []):
            raise ValueError(f"Kolom MeAJOR tidak sesuai: {pembaca.fieldnames}")
        for baris in pembaca:
            sumber = (baris.get("source") or "").strip().lower()
            nilai_label = (baris.get("label") or "").strip()
            if sumber not in SALURAN_VALID or nilai_label not in {"0.0", "1.0"}:
                continue
            label = "Normal" if nilai_label == "0.0" else "Phishing"
            teks = "\n".join(part.strip() for part in (baris.get("subject"), baris.get("body")) if part and part.strip())
            if not teks:
                continue
            kunci = (sumber, label)
            jumlah_ditemukan[kunci] += 1
            kandidat = {"teks": teks, "label": label, "sumber": f"meajor_{sumber}"}
            wadah = terpilih[kunci]
            if len(wadah) < BATAS_PER_SALURAN:
                wadah.append(kandidat)
            else:
                indeks = pembangkit.randrange(jumlah_ditemukan[kunci])
                if indeks < BATAS_PER_SALURAN:
                    wadah[indeks] = kandidat

    if {k[0] for k in jumlah_ditemukan} != SALURAN_VALID:
        raise ValueError(f"Sumber MeAJOR tidak lengkap: {sorted({k[0] for k in jumlah_ditemukan})}")

    baris_final: list[dict[str, str]] = []
    sidik_terlihat: dict[str, str] = {}
    benturan_label = 0
    duplikat = 0

    def tambah(teks: str, label: str, sumber: str) -> None:
        nonlocal benturan_label, duplikat
        teks = teks.strip()
        if not teks:
            return
        sidik = kunci_teks(teks)
        if sidik in sidik_terlihat:
            duplikat += 1
            if sidik_terlihat[sidik] != label:
                benturan_label += 1
            return
        sidik_terlihat[sidik] = label
        baris_final.append({"teks": teks, "label": label, "sumber": sumber})

    with zipfile.ZipFile(JALUR_ARSIP_PENGGUNA) as arsip:
        nama_csv = next((nama for nama in arsip.namelist() if nama.lower().endswith(".csv")), None)
        if nama_csv is None:
            raise ValueError("Arsip pengguna tidak memuat berkas CSV.")
        with arsip.open(nama_csv) as isi, __import__("io").TextIOWrapper(isi, encoding="utf-8-sig", errors="replace", newline="") as teks_csv:
            pembaca = csv.DictReader(teks_csv)
            if not {"text", "spam"}.issubset(pembaca.fieldnames or []):
                raise ValueError(f"Kolom dataset pengguna tidak sesuai: {pembaca.fieldnames}")
            for baris in pembaca:
                nilai_spam = (baris.get("spam") or "").strip()
                if nilai_spam not in {"0", "1"}:
                    continue
                label = "Normal" if nilai_spam == "0" else "Spam"
                tambah(baris.get("text") or "", label, "dataset_pengguna")

    for kandidat in sorted((baris for daftar in terpilih.values() for baris in daftar), key=lambda b: (b["sumber"], b["label"], kunci_teks(b["teks"]))):
        tambah(kandidat["teks"], kandidat["label"], kandidat["sumber"])

    if JALUR_ARSIP_SINTETIS.exists():
        with zipfile.ZipFile(JALUR_ARSIP_SINTETIS) as arsip:
            nama_csv_sintetis = next((nama for nama in arsip.namelist() if nama.lower().endswith(".csv")), None)
            if nama_csv_sintetis is None:
                raise ValueError("Arsip dataset_email.zip tidak memuat CSV.")
            with arsip.open(nama_csv_sintetis) as isi, io.TextIOWrapper(isi, encoding="utf-8-sig", errors="replace", newline="") as teks_csv:
                pembaca = csv.DictReader(teks_csv)
                if not {"teks", "label"}.issubset(pembaca.fieldnames or []):
                    raise ValueError(f"Kolom dataset sintetis tidak sesuai: {pembaca.fieldnames}")
                jumlah_sintetis = 0
                for nomor, baris in enumerate(pembaca, start=2):
                    label = (baris.get("label") or "").strip()
                    teks = (baris.get("teks") or "").strip()
                    if label not in {"Normal", "Spam", "Phishing"}:
                        raise ValueError(f"Label dataset sintetis tidak valid pada baris {nomor}: {label!r}")
                    if teks:
                        tambah(teks, label, "sintetis_gpt")
                        jumlah_sintetis += 1
                print(f"Contoh sintetis GPT dibaca: {jumlah_sintetis}.")

    jalur_hasil = DIREKTORI_DATASET / "emails.csv"
    with jalur_hasil.open("w", encoding="utf-8", newline="") as berkas:
        penulis = csv.DictWriter(berkas, fieldnames=["teks", "label", "sumber"], quoting=csv.QUOTE_MINIMAL)
        penulis.writeheader()
        penulis.writerows(baris_final)

    jumlah_label = Counter(baris["label"] for baris in baris_final)
    jumlah_sumber = Counter(baris["sumber"] for baris in baris_final)
    print("Dataset Check Mail selesai dibuat.")
    print("Jumlah label:", dict(jumlah_label))
    print("Jumlah sumber:", dict(jumlah_sumber))
    print(f"Sampel dibatasi maksimal {BATAS_PER_SALURAN} untuk tiap sumber × kelas MeAJOR (seed={SEED}).")
    print(f"Duplikat persis dilewati: {duplikat}; benturan label yang dilewati: {benturan_label}.")
    JALUR_MEAJOR.unlink(missing_ok=True)


if __name__ == "__main__":
    siapkan_dataset()


