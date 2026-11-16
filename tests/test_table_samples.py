"""WP T1 Verification: Real public sample provenance, SHA-256 manifest, and cell-level recomputation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import openpyxl
import pytest

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_table_samples as builder  # noqa: E402


def test_manifest_and_hashes_match() -> None:
    assert builder.MANIFEST_PATH.exists(), "bench/tables/MANIFEST.json missing"
    assert builder.SOURCES_MD_PATH.exists(), "bench/tables/raw/SOURCES.md missing"

    manifest = json.loads(builder.MANIFEST_PATH.read_text("utf-8"))
    assert manifest["script_version"] == builder.SCRIPT_VERSION
    samples = {s["id"]: s for s in manifest["samples"]}
    assert set(samples.keys()) == {
        "cleveland_patients_raw",
        "wdbc_biopsy_replicates",
        "hcv_multicohort_contrasts",
        "penguins_long",
        "uci_cleveland_table1",
        "owid_renewables_wide",
    }

    for sample_id, item in samples.items():
        raw_file = builder.RAW_DIR / item["raw_filename"]
        out_file = builder.OUT_DIR / item["filename"]
        assert raw_file.exists() and raw_file.stat().st_size > 128
        assert out_file.exists() and out_file.stat().st_size > 128
        assert builder.sha256_file(raw_file) == item["raw_sha256"], f"Raw hash mismatch for {sample_id}"
        assert builder.sha256_file(out_file) == item["out_sha256"], f"Out hash mismatch for {sample_id}"


def test_penguins_long_recomputation_cell_by_cell() -> None:
    raw_csv = builder.RAW_DIR / "penguins.csv"
    out_csv = builder.OUT_DIR / "penguins_long.csv"
    expected_grid = builder.compute_penguins_long(raw_csv)
    with out_csv.open("r", encoding="utf-8", newline="") as fh:
        actual_grid = list(csv.reader(fh))

    assert len(actual_grid) == len(expected_grid) == 13  # header + 3 species * 4 vars
    assert actual_grid[0] == ["species", "variable", "mean", "std", "count", "p_value"]

    for r_idx in range(1, len(expected_grid)):
        exp_row = expected_grid[r_idx]
        act_row = actual_grid[r_idx]
        assert act_row[0] == exp_row[0]
        assert act_row[1] == exp_row[1]
        assert int(act_row[4]) == int(exp_row[4])
        for c_idx in (2, 3, 5):
            assert float(act_row[c_idx]) == pytest.approx(float(exp_row[c_idx]), rel=1e-9, abs=1e-12)


def test_uci_cleveland_recomputation_and_no_or_column() -> None:
    raw_data = builder.RAW_DIR / "processed.cleveland.data"
    out_xlsx = builder.OUT_DIR / "uci_cleveland_table1.xlsx"
    n0, n1, exp_body = builder.compute_uci_cleveland(raw_data)

    wb = openpyxl.load_workbook(out_xlsx, data_only=True)
    ws = wb.active
    assert ws is not None
    assert ws.cell(row=1, column=1).value == "Table 1 raw export"
    assert ws.cell(row=2, column=1).value is None
    assert ws.cell(row=3, column=2).value == f"No CAD (n={n0})"
    assert ws.cell(row=3, column=4).value == f"CAD (n={n1})"

    subheaders = [ws.cell(row=4, column=c).value for c in range(1, 7)]
    assert subheaders == ["variable", "mean", "sd", "mean", "sd", "p_value"]
    assert all("or" not in str(h).lower() for h in subheaders)

    for idx, exp_row in enumerate(exp_body):
        excel_r = 5 + idx
        assert ws.cell(row=excel_r, column=1).value == exp_row[0]
        for c_idx in range(1, 6):
            act_v = ws.cell(row=excel_r, column=c_idx + 1).value
            exp_v = exp_row[c_idx]
            if isinstance(exp_v, str) and exp_v.endswith("%"):
                assert isinstance(act_v, str) and act_v.endswith("%")
                assert float(act_v[:-1]) == pytest.approx(float(exp_v[:-1]), rel=1e-9, abs=1e-9)
            else:
                assert float(act_v) == pytest.approx(float(exp_v), rel=1e-9, abs=1e-12)

    footer_val = ws.cell(row=5 + len(exp_body), column=1).value
    assert footer_val == "Welch t-test for continuous; chi-square for binary."


def test_owid_renewables_recomputation_and_no_trend_p() -> None:
    raw_csv = builder.RAW_DIR / "share-electricity-renewables.csv"
    out_csv = builder.OUT_DIR / "owid_renewables_wide.csv"
    expected_grid = builder.compute_owid_renewables_wide(raw_csv)
    with out_csv.open("r", encoding="utf-8", newline="") as fh:
        actual_grid = list(csv.reader(fh))

    assert actual_grid[0] == ["Entity", "Code", *[str(y) for y in range(2000, 2024)]]
    assert all("p" not in h.lower() for h in actual_grid[0])
    assert len(actual_grid) == len(expected_grid) == 9  # header + 8 entities

    for exp_row, act_row in zip(expected_grid[1:], actual_grid[1:]):
        assert act_row[0] == exp_row[0]
        assert act_row[1] == exp_row[1]
        for exp_cell, act_cell in zip(exp_row[2:], act_row[2:]):
            if exp_cell == "":
                assert act_cell == ""
            else:
                assert float(act_cell) == pytest.approx(float(exp_cell), rel=1e-9, abs=1e-12)


def test_v3_new_samples_recomputation_cell_by_cell() -> None:
    # 1. cleveland_patients_raw.csv (303 raw patients x 11 cols)
    exp_clev = builder.compute_cleveland_patients_raw(builder.RAW_DIR / "processed.cleveland.data")
    with (builder.OUT_DIR / "cleveland_patients_raw.csv").open("r", encoding="utf-8", newline="") as fh:
        act_clev = list(csv.reader(fh))
    assert act_clev == exp_clev
    assert len(act_clev) == 304  # header + 303 patients

    # 2. wdbc_biopsy_replicates.csv (10 features x 13 cols)
    exp_wdbc = builder.compute_wdbc_biopsy_replicates(builder.RAW_DIR / "wdbc.data")
    with (builder.OUT_DIR / "wdbc_biopsy_replicates.csv").open("r", encoding="utf-8", newline="") as fh:
        act_wdbc = list(csv.reader(fh))
    assert act_wdbc == exp_wdbc
    assert len(act_wdbc) == 11

    # 3. hcv_multicohort_contrasts.csv (10 biomarkers x 11 cols)
    exp_hcv = builder.compute_hcv_multicohort_contrasts(builder.RAW_DIR / "hcvdat0.csv")
    with (builder.OUT_DIR / "hcv_multicohort_contrasts.csv").open("r", encoding="utf-8", newline="") as fh:
        act_hcv = list(csv.reader(fh))
    assert act_hcv == exp_hcv
    assert len(act_hcv) == 11
