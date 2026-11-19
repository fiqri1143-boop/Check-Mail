"""Latih dan evaluasi Check Mail dengan holdout lintas sumber."""
from __future__ import annotations

import json
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

DIREKTORI_PROYEK = Path(__file__).resolve().parent.parent
if str(DIREKTORI_PROYEK) not in sys.path:
    sys.path.insert(0, str(DIREKTORI_PROYEK))

from backend.fitur_struktural import ekstrak_fitur_struktural, hapus_kata_umum

import joblib
import pandas as pd
import sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.utils.class_weight import compute_sample_weight

JALUR_DATASET = DIREKTORI_PROYEK / "dataset" / "emails.csv"
LABEL_VALID = ["Normal", "Spam", "Phishing"]
SEED = 42


def latih_pipa(data_latih: pd.DataFrame) -> tuple[FeatureUnion, MultinomialNB]:
    """Latih TF-IDF kata+karakter dan sinyal struktural bersama Naive Bayes."""
    vectorizer = FeatureUnion([
        ("kata", TfidfVectorizer(preprocessor=hapus_kata_umum, ngram_range=(1, 2), strip_accents="unicode", min_df=2, max_features=180_000, sublinear_tf=True)),
        # Cabang karakter tetap melihat ejaan asli agar pola obfuscation,
        # URL, serta bentuk kata tetap tersedia bagi model.
        ("karakter", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=80_000, sublinear_tf=True)),
        ("struktur", Pipeline([
            ("ekstraksi", FunctionTransformer(ekstrak_fitur_struktural, validate=False)),
            ("vektor", DictVectorizer()),
        ])),
    ])
    matriks = vectorizer.fit_transform(data_latih["teks"])
    bobot = compute_sample_weight(class_weight="balanced", y=data_latih["label"])
    model = MultinomialNB(alpha=0.5).fit(matriks, data_latih["label"], sample_weight=bobot)
    return vectorizer, model


def evaluasi_pipa(data_latih: pd.DataFrame, data_uji: pd.DataFrame) -> tuple[dict, list[str]]:
    """Latih tanpa data uji dan kembalikan metrik per kelas."""
    vectorizer, model = latih_pipa(data_latih)
    prediksi = model.predict(vectorizer.transform(data_uji["teks"]))
    label_diuji = [label for label in LABEL_VALID if label in set(data_uji["label"])]
    metrik = classification_report(data_uji["label"], prediksi, labels=label_diuji, output_dict=True, zero_division=0)
    matriks = confusion_matrix(data_uji["label"], prediksi, labels=label_diuji)
    return ({"label_diuji": label_diuji, "metrik": metrik, "confusion_matrix": matriks.tolist(), "jumlah_uji": len(data_uji)}, prediksi.tolist())


def latih_dan_evaluasi() -> None:
    data = pd.read_csv(JALUR_DATASET, keep_default_na=False)
    kolom_wajib = {"teks", "label", "sumber"}
    if not kolom_wajib.issubset(data.columns):
        raise ValueError(f"Dataset harus memiliki kolom {sorted(kolom_wajib)}.")
    data["teks"] = data["teks"].astype(str).str.strip()
    data["label"] = data["label"].astype(str).str.strip()
    data["sumber"] = data["sumber"].astype(str).str.strip()
    data = data[(data["teks"] != "") & (data["sumber"] != "")].copy()
    label_tak_valid = set(data["label"]) - set(LABEL_VALID)
    if label_tak_valid or set(data["label"]) != set(LABEL_VALID):
        raise ValueError(f"Label tidak valid/tidak lengkap: {sorted(label_tak_valid)}; ditemukan {sorted(set(data['label']))}")
    jumlah_label = data["label"].value_counts()
    if jumlah_label.min() < 10:
        raise ValueError("Setiap kelas perlu sedikitnya 10 baris untuk evaluasi.")

    ringkasan = {
        "waktu_utc": datetime.now(timezone.utc).isoformat(),
        "jumlah_data": int(len(data)),
        "jumlah_per_kelas": {str(k): int(v) for k, v in jumlah_label.items()},
        "seed": SEED,
        "metode": "Holdout berdasarkan sumber untuk MeAJOR; holdout stratifikasi untuk dataset spam pengguna.",
        "catatan": "Skor pada sumber yang dikenal tidak menjamin generalisasi ke email Indonesia atau kampanye baru. Bobot kelas seimbang mengubah prior efektif; predict_proba bukan probabilitas risiko yang terkalibrasi. Fitur kata, karakter, dan struktur email menambah cakupan pola; evaluasi pada data lokal baru tetap diperlukan.",
        "evaluasi_lintas_sumber": {},
    }

    sumber_meajor = sorted(s for s in data["sumber"].unique() if s.startswith("meajor_"))
    if len(sumber_meajor) < 2:
        raise ValueError("Diperlukan sedikitnya dua kelompok sumber MeAJOR untuk evaluasi lintas sumber.")
    for sumber_uji in sumber_meajor:
        data_uji = data[data["sumber"] == sumber_uji]
        data_latih = data[data["sumber"] != sumber_uji]
        hasil, prediksi = evaluasi_pipa(data_latih, data_uji)
        ringkasan["evaluasi_lintas_sumber"][sumber_uji] = hasil
        print(f"\nHoldout lintas sumber: {sumber_uji} (data uji={len(data_uji):,})")
        print(classification_report(data_uji["label"], prediksi, labels=hasil["label_diuji"], zero_division=0))

    data_pengguna = data[data["sumber"] == "dataset_pengguna"]
    latih_pengguna, uji_pengguna = train_test_split(
        data_pengguna, test_size=0.2, random_state=SEED, stratify=data_pengguna["label"]
    )
    data_latih_pengguna = pd.concat([data[data["sumber"] != "dataset_pengguna"], latih_pengguna], ignore_index=True)
    hasil_pengguna, prediksi_pengguna = evaluasi_pipa(data_latih_pengguna, uji_pengguna)
    ringkasan["holdout_dataset_pengguna"] = hasil_pengguna
    print("\nHoldout dataset spam yang diberikan pengguna:")
    print(classification_report(uji_pengguna["label"], prediksi_pengguna, labels=hasil_pengguna["label_diuji"], zero_division=0))

    vectorizer, model = latih_pipa(data)
    joblib.dump(model, DIREKTORI_PROYEK / "backend" / "model.pkl")
    joblib.dump(vectorizer, DIREKTORI_PROYEK / "backend" / "vectorizer.pkl")
    sha256_dataset = hashlib.sha256()
    with JALUR_DATASET.open("rb") as berkas_dataset:
        while potongan := berkas_dataset.read(1024 * 1024):
            sha256_dataset.update(potongan)
    metadata_model = {
        "dibuat_pada_utc": ringkasan["waktu_utc"],
        "nama_dataset": "dataset/emails.csv",
        "sha256_dataset": sha256_dataset.hexdigest(),
        "jumlah_data": int(len(data)),
        "jumlah_per_kelas": {str(k): int(v) for k, v in jumlah_label.items()},
        "jumlah_per_sumber": {str(k): int(v) for k, v in data["sumber"].value_counts().items()},
        "kelas_model": [str(k) for k in model.classes_],
        "vectorizer": vectorizer.get_params(),
        "fitur_teks": "FeatureUnion: TF-IDF kata (1-2 gram; kata umum Indonesia/Inggris dinetralisasi) + karakter char_wb (3-5 gram; teks asli) + fitur struktural email",
        "classifier": model.get_params(),
        "pembobotan_kelas": "balanced sample_weight",
        "seed_evaluasi": SEED,
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
    }
    (DIREKTORI_PROYEK / "backend" / "model_meta.json").write_text(
        json.dumps(metadata_model, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    jalur_laporan = DIREKTORI_PROYEK / "docs" / "evaluasi-model.json"
    jalur_laporan.write_text(json.dumps(ringkasan, ensure_ascii=False, indent=2), encoding="utf-8")
    baris_laporan = [
        "# Evaluasi Model Check Mail",
        "",
        f"Dibuat: {ringkasan['waktu_utc']} (UTC)",
        f"Total data: {ringkasan['jumlah_data']:,} — " + ", ".join(f"{label}: {jumlah:,}" for label, jumlah in ringkasan["jumlah_per_kelas"].items()),
        "",
        "## Holdout lintas sumber MeAJOR",
        "",
        "Setiap sub-sumber ditahan seluruhnya saat fold terkait diuji. Fold ini mengukur perubahan sumber untuk Normal/Phishing; kelas Spam tidak ada di korpus uji tersebut.",
        "",
        "| Sumber uji | Kelas | Precision | Recall | F1 | Jumlah uji |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for sumber_uji, hasil in ringkasan["evaluasi_lintas_sumber"].items():
        for label in hasil["label_diuji"]:
            skor = hasil["metrik"][label]
            baris_laporan.append(f"| {sumber_uji} | {label} | {skor['precision']:.3f} | {skor['recall']:.3f} | {skor['f1-score']:.3f} | {int(skor['support']):,} |")
    hasil = ringkasan["holdout_dataset_pengguna"]
    baris_laporan.extend(["", "## Holdout dataset yang diberikan pengguna", "", "Data uji dipisah secara stratifikasi; fold ini mengukur Normal/Spam pada korpus tersebut.", "", "| Kelas | Precision | Recall | F1 | Jumlah uji |", "|---|---:|---:|---:|---:|"])
    for label in hasil["label_diuji"]:
        skor = hasil["metrik"][label]
        baris_laporan.append(f"| {label} | {skor['precision']:.3f} | {skor['recall']:.3f} | {skor['f1-score']:.3f} | {int(skor['support']):,} |")
    baris_laporan.extend(["", "## Confusion matrix", "", "Baris adalah label aktual; kolom adalah hasil prediksi. Urutan label tercantum pada kolom kedua.", "", "| Holdout | Urutan label | Matriks |", "|---|---|---|"])
    for sumber_uji, hasil_uji in ringkasan["evaluasi_lintas_sumber"].items():
        baris_laporan.append(f"| {sumber_uji} | {', '.join(hasil_uji['label_diuji'])} | `{hasil_uji['confusion_matrix']}` |")
    baris_laporan.append(f"| Arsip pengguna | {', '.join(hasil['label_diuji'])} | `{hasil['confusion_matrix']}` |")
    baris_laporan.extend(["", "## Batas interpretasi", "", ringkasan["catatan"], "", "Metrik dipisah berdasarkan tugas dan sumber; jangan gabungkan menjadi satu akurasi tiga-kelas yang seolah-olah mewakili seluruh kondisi dunia nyata."])
    (DIREKTORI_PROYEK / "docs" / "evaluasi-model.md").write_text("\n".join(baris_laporan) + "\n", encoding="utf-8")
    print("\nJumlah data:", ringkasan["jumlah_per_kelas"])
    print("Model final: TF-IDF kata+karakter, fitur struktural, dan Multinomial Naive Bayes.")
    print("Model dan vectorizer disimpan di backend/.")
    print("Ringkasan evaluasi disimpan di docs/evaluasi-model.md dan .json")


if __name__ == "__main__":
    latih_dan_evaluasi()


