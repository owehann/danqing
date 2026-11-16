#!/usr/bin/env python3
"""Build real, reproducible public sample tables for Danqing Table Studio (WP T1 / v3).

Downloads raw open-license datasets (if not already cached in bench/tables/raw/),
verifies non-empty payloads, computes deterministic unstyled exports into bench/tables/out/,
and writes bench/tables/raw/SOURCES.md + bench/tables/MANIFEST.json.

Includes both:
- "Auto-Compute" raw-column datasets (individual clinical patient records & biological replicate matrices)
- "Smart-Tidy" structural/relational datasets (multi-cohort flat contrasts, long groupby, 2-row merged Excel, 24-yr wide series)

Zero hand-typed numbers; zero random/synthetic fallbacks. Network errors abort nonzero.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import openpyxl
from scipy import stats

SCRIPT_VERSION = "3.0.0"
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "bench" / "tables" / "raw"
OUT_DIR = REPO_ROOT / "bench" / "tables" / "out"
MANIFEST_PATH = REPO_ROOT / "bench" / "tables" / "MANIFEST.json"
SOURCES_MD_PATH = RAW_DIR / "SOURCES.md"

SOURCES: dict[str, dict[str, str]] = {
    "cleveland_patients_raw": {
        "raw_filename": "processed.cleveland.data",
        "out_filename": "cleveland_patients_raw.csv",
        "url": "https://archive.ics.uci.edu/ml/machine-learning-databases/heart-disease/processed.cleveland.data",
        "source_page": "https://archive.ics.uci.edu/dataset/45/heart+disease",
        "provider_en": "UCI Machine Learning Repository (Cleveland Heart Disease, n=303)",
        "provider_zh": "UCI 机器学习仓库（Cleveland 心脏病原始个案，n=303）",
        "license": "CC BY 4.0",
        "workflow_mode": "auto_compute",
    },
    "wdbc_biopsy_replicates": {
        "raw_filename": "wdbc.data",
        "out_filename": "wdbc_biopsy_replicates.csv",
        "url": "https://archive.ics.uci.edu/ml/machine-learning-databases/breast-cancer-wisconsin/wdbc.data",
        "source_page": "https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic",
        "provider_en": "UCI Machine Learning Repository (Wisconsin FNA Biopsy Morphometry)",
        "provider_zh": "UCI 机器学习仓库（Wisconsin 乳腺穿刺细胞核形态学）",
        "license": "CC BY 4.0",
        "workflow_mode": "auto_compute",
    },
    "hcv_multicohort_contrasts": {
        "raw_filename": "hcvdat0.csv",
        "out_filename": "hcv_multicohort_contrasts.csv",
        "url": "https://archive.ics.uci.edu/ml/machine-learning-databases/00571/hcvdat0.csv",
        "source_page": "https://archive.ics.uci.edu/dataset/571/hcv+data",
        "provider_en": "UCI Machine Learning Repository (Hoffmann et al., Serum Liver Biomarkers)",
        "provider_zh": "UCI 机器学习仓库（Hoffmann 等，肝病血清生物标志物队列）",
        "license": "CC BY 4.0",
        "workflow_mode": "smart_tidy",
    },
    "penguins_long": {
        "raw_filename": "penguins.csv",
        "out_filename": "penguins_long.csv",
        "url": "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv",
        "source_page": "https://allisonhorst.github.io/palmerpenguins/",
        "provider_en": "Palmer Station LTER (Horst, Hill & Gorman, 2020)",
        "provider_zh": "Palmer Station LTER（Horst, Hill & Gorman, 2020）",
        "license": "CC0-1.0",
        "workflow_mode": "smart_tidy",
    },
    "uci_cleveland_table1": {
        "raw_filename": "processed.cleveland.data",
        "out_filename": "uci_cleveland_table1.xlsx",
        "url": "https://archive.ics.uci.edu/ml/machine-learning-databases/heart-disease/processed.cleveland.data",
        "source_page": "https://archive.ics.uci.edu/dataset/45/heart+disease",
        "provider_en": "UCI Machine Learning Repository (Cleveland Heart Disease)",
        "provider_zh": "UCI 机器学习仓库（Cleveland 心脏病队列）",
        "license": "CC BY 4.0",
        "workflow_mode": "smart_tidy",
    },
    "owid_renewables_wide": {
        "raw_filename": "share-electricity-renewables.csv",
        "out_filename": "owid_renewables_wide.csv",
        "url": "https://ourworldindata.org/grapher/share-electricity-renewables.csv?v=1&csvType=full&useColumnShortNames=true",
        "source_page": "https://ourworldindata.org/renewable-energy",
        "provider_en": "Our World in Data (Ember & Energy Institute)",
        "provider_zh": "Our World in Data（Ember 与 Energy Institute）",
        "license": "CC BY 4.0",
        "workflow_mode": "smart_tidy",
    },
}

PENGUIN_NUM_COLS = [
    "bill_length_mm",
    "bill_depth_mm",
    "flipper_length_mm",
    "body_mass_g",
]

UCI_COLUMNS = [
    "age",
    "sex",
    "cp",
    "trestbps",
    "chol",
    "fbs",
    "restecg",
    "thalach",
    "exang",
    "oldpeak",
    "slope",
    "ca",
    "thal",
    "num",
]
UCI_CONTINUOUS = ["age", "trestbps", "chol", "thalach", "oldpeak"]
UCI_BINARY = [("sex=1", "sex"), ("fbs=1", "fbs"), ("exang=1", "exang")]

UCI_CP_LABELS = {
    1: "Typical angina",
    2: "Atypical angina",
    3: "Non-anginal pain",
    4: "Asymptomatic",
}

WDBC_MEAN_FEATURES = [
    ("Radius (um)", 2),
    ("Texture (gray)", 3),
    ("Perimeter (um)", 4),
    ("Area (um2)", 5),
    ("Smoothness", 6),
    ("Compactness", 7),
    ("Concavity", 8),
    ("Concave points", 9),
    ("Symmetry", 10),
    ("Fractal dimension", 11),
]
WDBC_REPLICATES_PER_GROUP = 6

HCV_BIOMARKERS = [
    ("ALB", "Albumin (g/L)"),
    ("ALP", "Alkaline phosphatase (U/L)"),
    ("ALT", "ALT (U/L)"),
    ("AST", "AST (U/L)"),
    ("BIL", "Bilirubin (umol/L)"),
    ("CHE", "Cholinesterase (kU/L)"),
    ("CHOL", "Cholesterol (mmol/L)"),
    ("CREA", "Creatinine (umol/L)"),
    ("GGT", "GGT (U/L)"),
    ("PROT", "Total protein (g/L)"),
]

OWID_ENTITIES = [
    "Denmark",
    "Germany",
    "United Kingdom",
    "China",
    "United States",
    "Japan",
    "Norway",
    "World",
]
OWID_YEARS = [str(y) for y in range(2000, 2024)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_raw_file(url: str, dest: Path, force: bool = False) -> None:
    if dest.exists() and dest.stat().st_size > 128 and not force:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DanqingTableSampleBuilder/3.0 (+https://github.com/owehann/danqing)"
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} downloading {url}")
        data = resp.read()
    if len(data) < 128:
        raise RuntimeError(f"Downloaded payload too small ({len(data)} bytes) for {url}")
    dest.write_bytes(data)


def compute_cleveland_patients_raw(raw_data: Path) -> list[list[str]]:
    """Convert raw Cleveland Heart Disease records into clean human-readable raw patient columns."""
    header = [
        "Patient_ID",
        "Diagnosis",
        "Age_yr",
        "Sex",
        "Chest_Pain",
        "Resting_BP_mmHg",
        "Cholesterol_mg_dL",
        "Fasting_BS",
        "Max_HR_bpm",
        "ST_Depression_mV",
        "Major_Vessels",
    ]
    out_rows: list[list[str]] = [header]
    pid = 1
    with raw_data.open("r", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 14 or parts[13] in ("?", ""):
                continue
            diag = "No CAD" if float(parts[13]) == 0.0 else "CAD"
            age_str = str(int(round(float(parts[0])))) if parts[0] not in ("?", "") else ""
            sex_str = (
                ("Male" if int(round(float(parts[1]))) == 1 else "Female")
                if parts[1] not in ("?", "")
                else ""
            )
            cp_str = (
                UCI_CP_LABELS.get(int(round(float(parts[2]))), "")
                if parts[2] not in ("?", "")
                else ""
            )
            bp_str = str(int(round(float(parts[3])))) if parts[3] not in ("?", "") else ""
            chol_str = str(int(round(float(parts[4])))) if parts[4] not in ("?", "") else ""
            fbs_str = (
                (">120 mg/dL" if int(round(float(parts[5]))) == 1 else "<=120 mg/dL")
                if parts[5] not in ("?", "")
                else ""
            )
            hr_str = str(int(round(float(parts[7])))) if parts[7] not in ("?", "") else ""
            oldpeak_str = f"{float(parts[9]):.1f}" if parts[9] not in ("?", "") else ""
            ca_str = str(int(round(float(parts[11])))) if parts[11] not in ("?", "") else ""
            out_rows.append(
                [
                    f"PT-{pid:03d}",
                    diag,
                    age_str,
                    sex_str,
                    cp_str,
                    bp_str,
                    chol_str,
                    fbs_str,
                    hr_str,
                    oldpeak_str,
                    ca_str,
                ]
            )
            pid += 1
    return out_rows


def write_cleveland_patients_raw(raw_data: Path, out_csv: Path) -> dict[str, int]:
    grid = compute_cleveland_patients_raw(raw_data)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows(grid)
    return {"rows": len(grid) - 1, "cols": len(grid[0])}


def compute_wdbc_biopsy_replicates(raw_data: Path) -> list[list[str]]:
    """Extract first 6 Benign and first 6 Malignant biopsies in file order across 10 nuclear assays."""
    benign_recs: list[list[str]] = []
    malig_recs: list[list[str]] = []
    with raw_data.open("r", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 12:
                continue
            diag = parts[1].upper()
            if diag == "B" and len(benign_recs) < WDBC_REPLICATES_PER_GROUP:
                benign_recs.append(parts)
            elif diag == "M" and len(malig_recs) < WDBC_REPLICATES_PER_GROUP:
                malig_recs.append(parts)
            if (
                len(benign_recs) >= WDBC_REPLICATES_PER_GROUP
                and len(malig_recs) >= WDBC_REPLICATES_PER_GROUP
            ):
                break

    if (
        len(benign_recs) < WDBC_REPLICATES_PER_GROUP
        or len(malig_recs) < WDBC_REPLICATES_PER_GROUP
    ):
        raise RuntimeError("Insufficient Benign/Malignant records in wdbc.data")

    header = [
        "Nuclear_Feature",
        *[f"Benign_{i + 1}" for i in range(WDBC_REPLICATES_PER_GROUP)],
        *[f"Malignant_{i + 1}" for i in range(WDBC_REPLICATES_PER_GROUP)],
    ]
    out_rows: list[list[str]] = [header]
    for feat_label, col_idx in WDBC_MEAN_FEATURES:
        b_vals = [f"{float(r[col_idx]):.4f}" for r in benign_recs]
        m_vals = [f"{float(r[col_idx]):.4f}" for r in malig_recs]
        out_rows.append([feat_label, *b_vals, *m_vals])
    return out_rows


def write_wdbc_biopsy_replicates(raw_data: Path, out_csv: Path) -> dict[str, int]:
    grid = compute_wdbc_biopsy_replicates(raw_data)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows(grid)
    return {"rows": len(grid) - 1, "cols": len(grid[0])}


def compute_hcv_multicohort_contrasts(raw_csv: Path) -> list[list[str]]:
    """Compute flat multi-cohort serum biomarker summary (Median/Q1/Q3 + 2 log2FC/padj contrasts)."""
    by_cat: dict[str, list[dict[str, float]]] = {
        "donor": [],
        "fibrosis": [],
        "cirrhosis": [],
    }
    with raw_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cat = (row.get("Category") or "").strip().lower()
            bucket: str | None = None
            if cat.startswith("0="):
                bucket = "donor"
            elif cat.startswith("2="):
                bucket = "fibrosis"
            elif cat.startswith("3="):
                bucket = "cirrhosis"
            if bucket is None:
                continue
            parsed_vals: dict[str, float] = {}
            for code, _ in HCV_BIOMARKERS:
                raw_v = (row.get(code) or "").strip()
                if raw_v in ("", "NA", "N/A", "nan"):
                    parsed_vals[code] = math.nan
                else:
                    parsed_vals[code] = float(raw_v)
            by_cat[bucket].append(parsed_vals)

    raw_p_fib: list[float] = []
    raw_p_cir: list[float] = []
    stats_cache: list[tuple[str, float, float, float, float, float, float, float, float]] = []

    for code, label in HCV_BIOMARKERS:
        d_arr = np.array([r[code] for r in by_cat["donor"] if not math.isnan(r[code])], dtype=float)
        f_arr = np.array([r[code] for r in by_cat["fibrosis"] if not math.isnan(r[code])], dtype=float)
        c_arr = np.array([r[code] for r in by_cat["cirrhosis"] if not math.isnan(r[code])], dtype=float)

        d_q25, d_med, d_q75 = [float(x) for x in np.percentile(d_arr, [25, 50, 75])]
        f_med = float(np.median(f_arr))
        c_q25, c_med, c_q75 = [float(x) for x in np.percentile(c_arr, [25, 50, 75])]

        fc_fib = math.log2(f_med / d_med)
        fc_cir = math.log2(c_med / d_med)

        _, p_fib = stats.mannwhitneyu(f_arr, d_arr, alternative="two-sided")
        _, p_cir = stats.mannwhitneyu(c_arr, d_arr, alternative="two-sided")
        raw_p_fib.append(float(p_fib))
        raw_p_cir.append(float(p_cir))
        stats_cache.append((label, d_med, d_q25, d_q75, fc_fib, c_med, c_q25, c_q75, fc_cir))

    padj_fib = stats.false_discovery_control(np.array(raw_p_fib, dtype=float), method="bh")
    padj_cir = stats.false_discovery_control(np.array(raw_p_cir, dtype=float), method="bh")

    header = [
        "Biomarker",
        "Donor_Median",
        "Donor_Q1",
        "Donor_Q3",
        "Fibrosis_vs_Donor_log2FC",
        "Fibrosis_vs_Donor_padj",
        "Cirrhosis_Median",
        "Cirrhosis_Q1",
        "Cirrhosis_Q3",
        "Cirrhosis_vs_Donor_log2FC",
        "Cirrhosis_vs_Donor_padj",
    ]
    out_rows: list[list[str]] = [header]
    for idx, (label, d_med, d_q25, d_q75, fc_fib, c_med, c_q25, c_q75, fc_cir) in enumerate(
        stats_cache
    ):
        out_rows.append(
            [
                label,
                f"{d_med:.2f}",
                f"{d_q25:.2f}",
                f"{d_q75:.2f}",
                f"{fc_fib:.3f}",
                f"{float(padj_fib[idx]):.4e}",
                f"{c_med:.2f}",
                f"{c_q25:.2f}",
                f"{c_q75:.2f}",
                f"{fc_cir:.3f}",
                f"{float(padj_cir[idx]):.4e}",
            ]
        )
    return out_rows


def write_hcv_multicohort_contrasts(raw_csv: Path, out_csv: Path) -> dict[str, int]:
    grid = compute_hcv_multicohort_contrasts(raw_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows(grid)
    return {"rows": len(grid) - 1, "cols": len(grid[0])}


def compute_penguins_long(raw_csv: Path) -> list[list[str]]:
    with raw_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        clean_rows: list[dict[str, Any]] = []
        for row in reader:
            sp = (row.get("species") or "").strip()
            if not sp or sp.upper() == "NA":
                continue
            vals: dict[str, float] = {}
            missing = False
            for col in PENGUIN_NUM_COLS:
                raw_v = (row.get(col) or "").strip()
                if not raw_v or raw_v.upper() == "NA":
                    missing = True
                    break
                vals[col] = float(raw_v)
            if not missing:
                clean_rows.append({"species": sp, **vals})

    species_order = sorted({r["species"] for r in clean_rows})
    p_by_var: dict[str, float] = {}
    for col in PENGUIN_NUM_COLS:
        groups = [
            np.array([r[col] for r in clean_rows if r["species"] == sp], dtype=float)
            for sp in species_order
        ]
        _, p_val = stats.f_oneway(*groups)
        p_by_var[col] = float(p_val)

    out_rows: list[list[str]] = [
        ["species", "variable", "mean", "std", "count", "p_value"]
    ]
    for sp in species_order:
        sp_rows = [r for r in clean_rows if r["species"] == sp]
        for col in PENGUIN_NUM_COLS:
            arr = np.array([r[col] for r in sp_rows], dtype=float)
            mean_v = float(np.mean(arr))
            std_v = float(np.std(arr, ddof=1))
            cnt_v = int(arr.size)
            out_rows.append(
                [
                    sp,
                    col,
                    f"{mean_v:.6f}",
                    f"{std_v:.6f}",
                    str(cnt_v),
                    f"{p_by_var[col]:.6e}",
                ]
            )
    return out_rows


def write_penguins_long(raw_csv: Path, out_csv: Path) -> dict[str, int]:
    grid = compute_penguins_long(raw_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows(grid)
    return {"rows": len(grid) - 1, "cols": len(grid[0])}


def compute_uci_cleveland(raw_data: Path) -> tuple[int, int, list[list[Any]]]:
    records: list[dict[str, float]] = []
    with raw_data.open("r", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 14:
                continue
            rec: dict[str, float] = {}
            for col_name, raw_tok in zip(UCI_COLUMNS, parts):
                if raw_tok == "?" or raw_tok == "":
                    rec[col_name] = math.nan
                else:
                    rec[col_name] = float(raw_tok)
            if not math.isnan(rec["num"]):
                records.append(rec)

    no_cad = [r for r in records if r["num"] == 0.0]
    cad = [r for r in records if r["num"] > 0.0]
    n0 = len(no_cad)
    n1 = len(cad)

    body_rows: list[list[Any]] = []
    for col in UCI_CONTINUOUS:
        g0 = np.array([r[col] for r in no_cad if not math.isnan(r[col])], dtype=float)
        g1 = np.array([r[col] for r in cad if not math.isnan(r[col])], dtype=float)
        m0, s0 = float(np.mean(g0)), float(np.std(g0, ddof=1))
        m1, s1 = float(np.mean(g1)), float(np.std(g1, ddof=1))
        _, p_val = stats.ttest_ind(g0, g1, equal_var=False)
        body_rows.append([col, m0, s0, m1, s1, float(p_val)])

    for label, col in UCI_BINARY:
        g0 = [r[col] for r in no_cad if not math.isnan(r[col])]
        g1 = [r[col] for r in cad if not math.isnan(r[col])]
        k0 = sum(1 for v in g0 if v == 1.0)
        k1 = sum(1 for v in g1 if v == 1.0)
        pct0 = 100.0 * k0 / len(g0)
        pct1 = 100.0 * k1 / len(g1)
        table_2x2 = np.array([[k0, len(g0) - k0], [k1, len(g1) - k1]], dtype=float)
        _, p_val, _, _ = stats.chi2_contingency(table_2x2, correction=False)
        body_rows.append([label, int(k0), f"{pct0:.6f}%", int(k1), f"{pct1:.6f}%", float(p_val)])

    return n0, n1, body_rows


def write_uci_cleveland_xlsx(raw_data: Path, out_xlsx: Path) -> dict[str, int]:
    n0, n1, body_rows = compute_uci_cleveland(raw_data)
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Table1_Raw"

    # Row 1: Title row; Row 2: Blank row
    ws.cell(row=1, column=1, value="Table 1 raw export")

    # Rows 3-4: 2-level merged header
    ws.cell(row=3, column=2, value=f"No CAD (n={n0})")
    ws.merge_cells(start_row=3, start_column=2, end_row=3, end_column=3)
    ws.cell(row=3, column=4, value=f"CAD (n={n1})")
    ws.merge_cells(start_row=3, start_column=4, end_row=3, end_column=5)

    subheaders = ["variable", "mean", "sd", "mean", "sd", "p_value"]
    for c_idx, h_text in enumerate(subheaders, start=1):
        ws.cell(row=4, column=c_idx, value=h_text)

    row_cursor = 5
    for brow in body_rows:
        for c_idx, cell_val in enumerate(brow, start=1):
            ws.cell(row=row_cursor, column=c_idx, value=cell_val)
        row_cursor += 1

    # Footer row
    ws.cell(row=row_cursor, column=1, value="Welch t-test for continuous; chi-square for binary.")

    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_xlsx)
    return {"rows": len(body_rows), "cols": len(subheaders)}


def compute_owid_renewables_wide(raw_csv: Path) -> list[list[str]]:
    with raw_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        entity_col = "Entity" if "Entity" in fieldnames else fieldnames[0]
        code_col = "Code" if "Code" in fieldnames else fieldnames[1]
        year_col = "Year" if "Year" in fieldnames else fieldnames[2]
        val_cols = [c for c in fieldnames if c not in (entity_col, code_col, year_col)]
        if not val_cols:
            raise RuntimeError(f"Could not locate value column in OWID CSV headers: {fieldnames}")
        val_col = val_cols[0]

        by_entity_year: dict[str, dict[str, str]] = {e: {} for e in OWID_ENTITIES}
        codes: dict[str, str] = {}
        for row in reader:
            ent = (row.get(entity_col) or "").strip()
            yr = (row.get(year_col) or "").strip()
            if ent in by_entity_year and yr in OWID_YEARS:
                raw_val = (row.get(val_col) or "").strip()
                by_entity_year[ent][yr] = raw_val
                code_val = (row.get(code_col) or "").strip()
                if code_val:
                    codes[ent] = code_val

    header = ["Entity", "Code", *OWID_YEARS]
    out_rows: list[list[str]] = [header]
    for ent in OWID_ENTITIES:
        code_str = codes.get(ent, "")
        yr_vals = [by_entity_year[ent].get(yr, "") for yr in OWID_YEARS]
        out_rows.append([ent, code_str, *yr_vals])
    return out_rows


def write_owid_renewables_wide(raw_csv: Path, out_csv: Path) -> dict[str, int]:
    grid = compute_owid_renewables_wide(raw_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows(grid)
    return {"rows": len(grid) - 1, "cols": len(grid[0])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build real public sample tables for Table Studio.")
    parser.add_argument("--refresh", action="store_true", help="Force re-download of raw files.")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for sample_id, meta in SOURCES.items():
        raw_path = RAW_DIR / meta["raw_filename"]
        print(f"[T1] Fetching/verifying {sample_id} -> {raw_path.relative_to(REPO_ROOT)}")
        ensure_raw_file(meta["url"], raw_path, force=args.refresh)

    dims_map = {
        "cleveland_patients_raw": write_cleveland_patients_raw(
            RAW_DIR / SOURCES["cleveland_patients_raw"]["raw_filename"],
            OUT_DIR / SOURCES["cleveland_patients_raw"]["out_filename"],
        ),
        "wdbc_biopsy_replicates": write_wdbc_biopsy_replicates(
            RAW_DIR / SOURCES["wdbc_biopsy_replicates"]["raw_filename"],
            OUT_DIR / SOURCES["wdbc_biopsy_replicates"]["out_filename"],
        ),
        "hcv_multicohort_contrasts": write_hcv_multicohort_contrasts(
            RAW_DIR / SOURCES["hcv_multicohort_contrasts"]["raw_filename"],
            OUT_DIR / SOURCES["hcv_multicohort_contrasts"]["out_filename"],
        ),
        "penguins_long": write_penguins_long(
            RAW_DIR / SOURCES["penguins_long"]["raw_filename"],
            OUT_DIR / SOURCES["penguins_long"]["out_filename"],
        ),
        "uci_cleveland_table1": write_uci_cleveland_xlsx(
            RAW_DIR / SOURCES["uci_cleveland_table1"]["raw_filename"],
            OUT_DIR / SOURCES["uci_cleveland_table1"]["out_filename"],
        ),
        "owid_renewables_wide": write_owid_renewables_wide(
            RAW_DIR / SOURCES["owid_renewables_wide"]["raw_filename"],
            OUT_DIR / SOURCES["owid_renewables_wide"]["out_filename"],
        ),
    }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_samples: list[dict[str, Any]] = []
    sources_md_lines = [
        "# Raw Public Datasets for Danqing Table Studio (`bench/tables/raw/`)",
        "",
        f"- Generated at (UTC): `{now_iso}`",
        f"- Builder script: `scripts/build_table_samples.py` (`v{SCRIPT_VERSION}`)",
        "- Policy: Every sample in `bench/tables/out/` is deterministically computed from the raw files below.",
        "",
        "| Sample ID | Raw File | License | Raw SHA-256 | Source URL |",
        "|---|---|---|---|---|",
    ]

    sample_ui_meta = {
        "cleveland_patients_raw": {
            "title_en": "Clinical Cohort Raw Records → Auto Table 1",
            "title_zh": "心脏病临床个案原始记录 → 一键计算 Table 1",
            "needs_en": "303 raw patients · normal & skewed traits · multi-level categories · missingness",
            "needs_zh": "303 例未汇总原始列 · 自动正态/偏态检验 · 多分类缩进 · 缺失分母校准",
        },
        "wdbc_biopsy_replicates": {
            "title_en": "Biopsy Replicate Columns → Auto Fold-Change & FDR",
            "title_zh": "穿刺活检重复样本列 → 一键汇总均值、log2FC 与 FDR",
            "needs_en": "12 raw replicate cols (Benign_1..6 vs Malignant_1..6) · collapse & BH-FDR",
            "needs_zh": "12 列原始重复观测（Benign_1..6 对 Malignant_1..6）· 自动算差异与 BH-FDR",
        },
        "hcv_multicohort_contrasts": {
            "title_en": "Liver Biomarkers — Flat Multi-Cohort Contrasts",
            "title_zh": "肝纤维化血清标志物 — 扁平单行多队列对比表",
            "needs_en": "Flat prefixes · Median+Q1+Q3 · dual (log2FC, padj) pairs · inline effect bars",
            "needs_zh": "单行前缀拆解建组 · Median[IQR] 合并 · 双队列独立显著性绑定 · 效应微条形",
        },
        "penguins_long": {
            "title_en": "Palmer Penguins — Long Groupby Export",
            "title_zh": "企鹅形态学 — Pandas 长格式汇总导出",
            "needs_en": "Long format · scientific-notation P · 6 decimals · snake_case labels",
            "needs_zh": "长格式透视展开 · 科学计数法 P 值 · 6 位小数 · 分组样本量提炼",
        },
        "uci_cleveland_table1": {
            "title_en": "Cleveland Heart Disease — Merged Excel Export",
            "title_zh": "Cleveland 心脏病 — 带废标题与合并格 Excel 导出",
            "needs_en": "Title row · 2-row merged header · mixed Mean/SD & n(%) · footer note",
            "needs_zh": "首行废标题剥离 · 两层合并表头 · 均值/SD 与 n(%) 混排 · 表底脚注提取",
        },
        "owid_renewables_wide": {
            "title_en": "Our World in Data — Renewable Electricity (2000–2023)",
            "title_zh": "OWID 可再生电力占比超宽表（2000–2023，24 年）",
            "needs_en": "24 wide year columns · uneven decimals · FT sparkline compression",
            "needs_zh": "24 个连续年份宽列 · 小数位不齐 · 折叠为首末对比与行内迷你趋势线",
        },
    }

    for sample_id, meta in SOURCES.items():
        raw_path = RAW_DIR / meta["raw_filename"]
        out_path = OUT_DIR / meta["out_filename"]
        raw_sha = sha256_file(raw_path)
        out_sha = sha256_file(out_path)
        ui = sample_ui_meta[sample_id]

        manifest_samples.append(
            {
                "id": sample_id,
                "filename": meta["out_filename"],
                "raw_filename": meta["raw_filename"],
                "url": meta["url"],
                "source_page": meta["source_page"],
                "provider_en": meta["provider_en"],
                "provider_zh": meta["provider_zh"],
                "license": meta["license"],
                "workflow_mode": meta["workflow_mode"],
                "title_en": ui["title_en"],
                "title_zh": ui["title_zh"],
                "needs_en": ui["needs_en"],
                "needs_zh": ui["needs_zh"],
                "raw_sha256": raw_sha,
                "out_sha256": out_sha,
                "rows": dims_map[sample_id]["rows"],
                "cols": dims_map[sample_id]["cols"],
            }
        )
        sources_md_lines.append(
            f"| `{sample_id}` | `{meta['raw_filename']}` | {meta['license']} | `{raw_sha}` | {meta['url']} |"
        )

    SOURCES_MD_PATH.write_text("\n".join(sources_md_lines) + "\n", encoding="utf-8")
    manifest_payload = {
        "script_version": SCRIPT_VERSION,
        "generated_at_utc": now_iso,
        "samples": manifest_samples,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[T1] Successfully built {len(manifest_samples)} samples -> {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
