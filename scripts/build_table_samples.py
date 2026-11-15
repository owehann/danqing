#!/usr/bin/env python3
"""Build real, reproducible public sample tables for Danqing Table Studio (WP T1).

Downloads raw open-license datasets (if not already cached in bench/tables/raw/),
verifies non-empty payloads, computes unstyled messy exports into bench/tables/out/,
and writes bench/tables/raw/SOURCES.md + bench/tables/MANIFEST.json.

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

SCRIPT_VERSION = "2.0.0"
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "bench" / "tables" / "raw"
OUT_DIR = REPO_ROOT / "bench" / "tables" / "out"
MANIFEST_PATH = REPO_ROOT / "bench" / "tables" / "MANIFEST.json"
SOURCES_MD_PATH = RAW_DIR / "SOURCES.md"

SOURCES: dict[str, dict[str, str]] = {
    "penguins_long": {
        "raw_filename": "penguins.csv",
        "out_filename": "penguins_long.csv",
        "url": "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv",
        "source_page": "https://allisonhorst.github.io/palmerpenguins/",
        "provider_en": "Palmer Station LTER (Horst, Hill & Gorman, 2020)",
        "provider_zh": "Palmer Station LTER（Horst, Hill & Gorman, 2020）",
        "license": "CC0-1.0",
    },
    "uci_cleveland_table1": {
        "raw_filename": "processed.cleveland.data",
        "out_filename": "uci_cleveland_table1.xlsx",
        "url": "https://archive.ics.uci.edu/ml/machine-learning-databases/heart-disease/processed.cleveland.data",
        "source_page": "https://archive.ics.uci.edu/dataset/45/heart+disease",
        "provider_en": "UCI Machine Learning Repository (Cleveland Heart Disease)",
        "provider_zh": "UCI 机器学习仓库（Cleveland 心脏病队列）",
        "license": "CC BY 4.0",
    },
    "owid_renewables_wide": {
        "raw_filename": "share-electricity-renewables.csv",
        "out_filename": "owid_renewables_wide.csv",
        "url": "https://ourworldindata.org/grapher/share-electricity-renewables.csv?v=1&csvType=full&useColumnShortNames=true",
        "source_page": "https://ourworldindata.org/renewable-energy",
        "provider_en": "Our World in Data (Ember & Energy Institute)",
        "provider_zh": "Our World in Data（Ember 与 Energy Institute）",
        "license": "CC BY 4.0",
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
            "User-Agent": "DanqingTableSampleBuilder/2.0 (+https://github.com/owehann/danqing)"
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} downloading {url}")
        data = resp.read()
    if len(data) < 128:
        raise RuntimeError(f"Downloaded payload too small ({len(data)} bytes) for {url}")
    dest.write_bytes(data)


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

    dims_penguins = write_penguins_long(
        RAW_DIR / SOURCES["penguins_long"]["raw_filename"],
        OUT_DIR / SOURCES["penguins_long"]["out_filename"],
    )
    dims_uci = write_uci_cleveland_xlsx(
        RAW_DIR / SOURCES["uci_cleveland_table1"]["raw_filename"],
        OUT_DIR / SOURCES["uci_cleveland_table1"]["out_filename"],
    )
    dims_owid = write_owid_renewables_wide(
        RAW_DIR / SOURCES["owid_renewables_wide"]["raw_filename"],
        OUT_DIR / SOURCES["owid_renewables_wide"]["out_filename"],
    )
    dims_map = {
        "penguins_long": dims_penguins,
        "uci_cleveland_table1": dims_uci,
        "owid_renewables_wide": dims_owid,
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
        "penguins_long": {
            "title_en": "Palmer Penguins — Long Groupby Export",
            "title_zh": "企鹅形态学 — Pandas 长格式汇总导出",
            "needs_en": "Long format · scientific-notation P · 6 decimals · snake_case labels",
            "needs_zh": "需整理：长格式透视 · 科学计数法 P 值 · 6 位小数 · 原始变量名",
        },
        "uci_cleveland_table1": {
            "title_en": "UCI Cleveland Heart Disease — Raw Excel Export",
            "title_zh": "UCI 心脏病队列 — 带合并表头的原始 Excel 导出",
            "needs_en": "Title row · 2-row merged header · mixed Mean/SD & n(%) · footer note",
            "needs_zh": "需整理：首行废标题 · 两层合并表头 · 均值/SD 与 n(%) 混排 · 表底脚注行",
        },
        "owid_renewables_wide": {
            "title_en": "Our World in Data — Renewable Electricity (2000–2023)",
            "title_zh": "OWID 可再生电力占比宽表（2000–2023，24 年）",
            "needs_en": "24 wide year columns · uneven decimals · sparkline compression",
            "needs_zh": "需整理：24 个年份宽列 · 小数位不齐 · 适合压缩为行内趋势线",
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
