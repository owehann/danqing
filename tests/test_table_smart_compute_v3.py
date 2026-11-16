"""WP T5 / v3 Verification: Deep Relational Column Graph & Statistical Auto-Compute Engine."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import openpyxl
import pytest
from fastapi.testclient import TestClient
from scipy import stats

from danqing.table_studio import parse_tabular_bytes, parse_tabular_paste
from web.backend.app import app

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "bench" / "tables" / "out"
client = TestClient(app)


def test_hcv_multicohort_relational_graph() -> None:
    raw = (OUT_DIR / "hcv_multicohort_contrasts.csv").read_bytes()
    snap = parse_tabular_bytes(raw, filename="hcv_multicohort_contrasts.csv")
    sug = snap.suggestions

    assert sug["smart_compute"] is None  # Already summarized statistical table
    assert sug["spanners"] == [
        {"label": "Donor", "source_cols": [1, 2, 3]},
        {"label": "Fibrosis vs Donor", "source_cols": [4, 5]},
        {"label": "Cirrhosis", "source_cols": [6, 7, 8]},
        {"label": "Cirrhosis vs Donor", "source_cols": [9, 10]},
    ]
    assert sug["leaf_headers"] == [
        "Biomarker",
        "Median",
        "Q1",
        "Q3",
        "log2FC",
        "FDR",
        "Median",
        "Q1",
        "Q3",
        "log2FC",
        "FDR",
    ]
    assert sug["merges"] == [
        {"source_cols": [1, 2, 3], "pattern": "iqr"},
        {"source_cols": [6, 7, 8], "pattern": "iqr"},
    ]
    # Protagonist log2FC columns get `bar` role while baseline IQR columns stay `normal`
    assert sug["roles"]["1"] == "normal"
    assert sug["roles"]["4"] == "bar"
    assert sug["roles"]["5"] == "sig"
    assert sug["roles"]["6"] == "normal"
    assert sug["roles"]["9"] == "bar"
    assert sug["roles"]["10"] == "sig"

    assert sug["sig_bindings"] == [
        {"source_col": 5, "target_cols": [4], "label": "Fibrosis vs Donor"},
        {"source_col": 10, "target_cols": [9], "label": "Cirrhosis vs Donor"},
    ]


def test_mathematical_invariants_and_spearman_binding() -> None:
    # 1. Ratio conservation n + pct without '%' symbol in cells + 3-col cryptic order invariant
    tsv = (
        "Subgroup\tArmA_n\tArmA_pct\tArmB_Med\tArmB_P25\tArmB_P75\t"
        "Model_Base_log2FC\tModel_True_log2FC\tModel_padj\n"
        "G1\t50\t25.0\t12.0\t8.0\t18.0\t0.10\t2.40\t0.0001\n"
        "G2\t80\t40.0\t15.0\t10.0\t22.0\t1.90\t0.05\t0.8500\n"
        "G3\t40\t20.0\t9.5\t6.0\t14.0\t0.20\t1.85\t0.0020\n"
        "G4\t30\t15.0\t11.0\t7.5\t16.0\t1.50\t0.12\t0.7200\n"
    )
    snap = parse_tabular_paste(pasted_text=tsv)
    sug = snap.suggestions
    assert {"source_cols": [1, 2], "pattern": "paren"} in sug["merges"]
    assert {"source_cols": [3, 4, 5], "pattern": "iqr"} in sug["merges"]
    assert snap.column_stats[2]["detected_unit"] == "%"

    # Spearman tie-breaker must bind `Model_padj` (col 8) to `Model_True_log2FC` (col 7), NOT `Model_Base_log2FC` (col 6)
    assert sug["sig_bindings"] == [
        {"source_col": 8, "target_cols": [7], "label": "Model"}
    ]


def test_auto_compute_table1_cleveland_and_modes() -> None:
    raw_bytes = (OUT_DIR / "cleveland_patients_raw.csv").read_bytes()
    snap = parse_tabular_bytes(raw_bytes, filename="cleveland_patients_raw.csv")
    sc = snap.suggestions["smart_compute"]
    assert sc is not None
    assert sc["kind"] == "subject_table1"
    assert sc["n_subjects"] == 303
    assert sc["default_group_col"] == 1

    # 1. Default 2-group auto normality compute via API
    r1 = client.post(
        "/api/v2/tables/compute",
        json={
            "grid": snap.grid,
            "header_rows": [0, 0],
            "body_range": [1, len(snap.grid) - 1],
            "decimal_comma": False,
            "source": snap.source,
            "mode": "subject_table1",
            "options": {"group_col": 1, "continuous_mode": "auto", "include_overall": True, "adjust_p": True},
            "lang": "en",
        },
    )
    assert r1.status_code == 200
    body1 = r1.json()
    grid1 = body1["snapshot"]["grid"]
    by_label = {row[0].split("^")[0]: row for row in grid1[1:]}

    # Age is normal -> Mean ± SD + Welch's t-test
    assert by_label["Age (yr)"][1:7] == ["54.4", "9.0", "52.6", "9.5", "56.6", "7.9"]
    assert float(by_label["Age (yr)"][7]) == pytest.approx(7.061439e-05, rel=1e-4)

    # ST Depression is skewed -> Median [Q1–Q3] + Mann–Whitney U
    assert by_label["ST Depression (mV)"][1:7] == [
        "0.8",
        "[0.0–1.6]",
        "0.2",
        "[0.0–1.0]",
        "1.4",
        "[0.6–2.5]",
    ]
    assert float(by_label["ST Depression (mV)"][7]) == pytest.approx(6.813094e-13, rel=1e-4)

    # Missing denominator audit on Major Vessels (n=299 out of 303)
    assert "Major Vessels (n=299), n (%)" in by_label
    # FDR column populated
    assert float(by_label["Age (yr)"][8]) >= float(by_label["Age (yr)"][7])

    # 2. Multi-group (>=3 arms) stratify by Chest_Pain (col 4 -> 4 arms: ANOVA + Kruskal-Wallis)
    r_multi = client.post(
        "/api/v2/tables/compute",
        json={
            "grid": snap.grid,
            "header_rows": [0, 0],
            "body_range": [1, len(snap.grid) - 1],
            "decimal_comma": False,
            "source": snap.source,
            "mode": "subject_table1",
            "options": {"group_col": 4, "continuous_mode": "auto", "include_overall": False},
            "lang": "en",
        },
    )
    assert r_multi.status_code == 200
    fn_texts = " | ".join(f["text"] for f in r_multi.json()["structure"]["footnotes"])
    assert "ANOVA" in fn_texts
    assert "Kruskal–Wallis" in fn_texts

    # 3. Single-cohort Overall-only mode -> zero hypothesis-test claims in footnotes!
    r_ov = client.post(
        "/api/v2/tables/compute",
        json={
            "grid": snap.grid,
            "header_rows": [0, 0],
            "body_range": [1, len(snap.grid) - 1],
            "decimal_comma": False,
            "source": snap.source,
            "mode": "subject_table1",
            "options": {"group_col": "none"},
            "lang": "en",
        },
    )
    assert r_ov.status_code == 200
    ov_fns = " | ".join(f["text"] for f in r_ov.json()["structure"]["footnotes"])
    assert "Welch" not in ov_fns
    assert "Mann–Whitney" not in ov_fns
    assert "chi-square" not in ov_fns


def test_fisher_exact_small_expected_counts() -> None:
    # 16 subjects where binary outcome has expected cell count < 5 -> must use Fisher's exact test
    grid = [["ID", "Arm", "Response", "Score"]]
    # Control: 8 subjects (1 responder, 7 non-responders); Treated: 8 subjects (6 responders, 2 non-responders)
    for i in range(8):
        grid.append([f"S{i+1}", "Control", "Yes" if i == 0 else "No", f"{10.0 + i}"])
    for i in range(8):
        grid.append([f"S{i+9}", "Treated", "Yes" if i < 6 else "No", f"{20.0 + i}"])

    res = client.post(
        "/api/v2/tables/compute",
        json={
            "grid": grid,
            "header_rows": [0, 0],
            "body_range": [1, len(grid) - 1],
            "source": {"filename": "small_trial.csv"},
            "mode": "subject_table1",
            "options": {"group_col": 1, "include_overall": False},
            "lang": "en",
        },
    )
    assert res.status_code == 200
    data = res.json()
    _, exp_fisher_p = stats.fisher_exact([[6, 1], [2, 7]], alternative="two-sided")
    resp_row = next(r for r in data["snapshot"]["grid"][1:] if r[0].startswith("Response"))
    assert float(resp_row[-1]) == pytest.approx(float(exp_fisher_p), rel=1e-6)
    assert any("Fisher's exact" in f["text"] for f in data["structure"]["footnotes"])


def test_replicate_collapse_and_source_data_export_sheets() -> None:
    raw_bytes = (OUT_DIR / "wdbc_biopsy_replicates.csv").read_bytes()
    snap = parse_tabular_bytes(raw_bytes, filename="wdbc_biopsy_replicates.csv")
    sc = snap.suggestions["smart_compute"]
    assert sc is not None
    assert sc["kind"] == "replicate_collapse"
    assert len(sc["groups"]) == 2

    res = client.post(
        "/api/v2/tables/compute",
        json={
            "grid": snap.grid,
            "header_rows": [0, 0],
            "body_range": [1, len(snap.grid) - 1],
            "source": snap.source,
            "mode": "replicate_collapse",
            "options": {"summary_mode": "parametric", "effect_metric": "log2fc", "paired": False},
            "lang": "en",
        },
    )
    assert res.status_code == 200
    comp = res.json()
    c_grid = comp["snapshot"]["grid"]
    assert c_grid[0] == [
        "Nuclear Feature",
        "Benign (n=6) · Mean",
        "Benign (n=6) · SD",
        "Malignant (n=6) · Mean",
        "Malignant (n=6) · SD",
        "log2FC",
        "P value",
        "FDR",
    ]

    # Verify Radius (um) exact calculation against numpy/scipy
    b_rad = np.array([float(x) for x in snap.grid[1][1:7]])
    m_rad = np.array([float(x) for x in snap.grid[1][7:13]])
    exp_fc = np.log2(np.mean(m_rad) / np.mean(b_rad))
    _, exp_p = stats.ttest_ind(m_rad, b_rad, equal_var=False)
    assert float(c_grid[1][5]) == pytest.approx(float(exp_fc), abs=1e-3)
    assert float(c_grid[1][6]) == pytest.approx(float(exp_p), rel=1e-5)

    # Verify 3-sheet XLSX export (`Table`, `data`, `source_data`) & ZIP `source_data.csv`
    xlsx_res = client.post(
        "/api/v2/tables/export/xlsx",
        json={
            "filename_stem": "wdbc_computed",
            "title": "Table 1. Differential nuclear morphometry",
            "preset": "cns_three_line",
            "headers": [{"label": "Feature", "align": "left"}, {"label": "log2FC", "align": "right"}],
            "blocks": [{"part_name": "", "part_accent": "#2E6F95", "rows": [[{"text": "Radius", "align": "left"}, {"text": "0.561*", "align": "right"}]]}],
            "raw_data_sheet": {"headers": c_grid[0], "rows": c_grid[1:]},
            "source_data_sheet": {"headers": snap.grid[0], "rows": snap.grid[1:]},
        },
    )
    assert xlsx_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_res.content), data_only=True)
    assert wb.sheetnames == ["Table", "data", "source_data"]
    ws_src = wb["source_data"]
    assert ws_src.max_row == 11
    assert ws_src.max_column == 13
    assert ws_src.cell(row=1, column=2).value == "Benign_1"

    zip_res = client.post(
        "/api/v2/tables/export/zip",
        json={
            "filename_stem": "wdbc_bundle",
            "table_json": {"schema": "danqing.table_studio.v2"},
            "csv_headers": c_grid[0],
            "csv_rows": c_grid[1:],
            "source_data_sheet": {"headers": snap.grid[0], "rows": snap.grid[1:]},
            "gt_meta": {"title": "Table 1"},
        },
    )
    assert zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as zf:
        assert set(zf.namelist()) == {"table.json", "data.csv", "make_table.py", "source_data.csv"}
