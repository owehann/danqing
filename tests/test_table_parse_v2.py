"""WP T2 Verification: Deterministic numeric vectors, 6 hostile fixtures, paste & error keys (>=30 cases)."""

from __future__ import annotations

import html
import io
import json
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from danqing.table_studio import parse_number, parse_tabular_bytes, parse_tabular_paste
from web.backend.app import app

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "core" / "danqing" / "table_numeric_spec.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "tables"

client = TestClient(app)

NUMERIC_VECTORS = json.loads(SPEC_PATH.read_text("utf-8"))["vectors"]


@pytest.mark.parametrize("vec", NUMERIC_VECTORS, ids=[v["id"] for v in NUMERIC_VECTORS])
def test_numeric_spec_vectors(vec: dict) -> None:
    res = parse_number(vec["input"], decimal_comma=bool(vec["decimal_comma"]))
    if vec["value"] is None:
        assert res.value is None
    else:
        assert res.value is not None
        assert res.value == pytest.approx(float(vec["value"]), rel=1e-9, abs=1e-95)
    assert res.prefix == vec["prefix"]
    assert res.unit == vec["unit"]
    assert res.p_text == vec["p_text"]
    assert res.is_sequence is bool(vec["is_sequence"])


def test_fixture_euro_semicolon_zh() -> None:
    raw = (FIXTURES_DIR / "euro_semicolon_zh.csv").read_bytes()
    snap = parse_tabular_bytes(raw, filename="euro_semicolon_zh.csv")
    warn_codes = {w["code"] for w in snap.warnings}
    assert "LOCALE_DECIMAL_COMMA" in warn_codes
    assert snap.suggestions["decimal_comma"] is True

    by_name = {c["name"]: c for c in snap.column_stats}
    for num_col in ("对照组 均值", "对照组 标准差", "治疗组 均值", "治疗组 标准差", "P值"):
        assert by_name[num_col]["numeric_ratio"] == 1.0
    assert by_name["P值"]["role"] == "sig"
    assert snap.suggestions["part_by"] == 0
    assert snap.suggestions["pivot"] is None  # grouped wide table, NOT long format


def test_fixture_xlsx_spanning_header_titlerows() -> None:
    raw = (FIXTURES_DIR / "xlsx_spanning_header_titlerows.xlsx").read_bytes()
    snap = parse_tabular_bytes(raw, filename="xlsx_spanning_header_titlerows.xlsx")
    assert snap.suggestions["header_rows"] == [2, 3]
    assert snap.suggestions["body_range"] == [4, 7]
    assert snap.suggestions["title_candidate"] == "Table 1. Baseline characteristics"

    spanners = snap.suggestions["spanners"]
    assert len(spanners) == 2
    assert spanners[0] == {"label": "No CAD", "source_cols": [1, 2]}
    assert spanners[1] == {"label": "CAD", "source_cols": [3, 4]}

    assert snap.suggestions["footnote_candidates"] == ["a Welch t-test."]
    warn_codes = [w["code"] for w in snap.warnings]
    assert "TITLE_ROWS_SKIPPED" in warn_codes
    assert "FOOTER_ROWS_DETECTED" in warn_codes
    assert "FORMULA_NO_CACHE" in warn_codes

    # Verify Notes sheet is flagged as lacking tabular data in sheets_meta or error on direct selection
    notes_meta = next(s for s in snap.sheets_meta if s["name"] == "Notes")
    assert notes_meta["empty"] is True


def test_fixture_messy_long_groupby() -> None:
    raw = (FIXTURES_DIR / "messy_long_groupby.csv").read_bytes()
    snap = parse_tabular_bytes(raw, filename="messy_long_groupby.csv")
    assert snap.suggestions["part_by"] == 0
    piv = snap.suggestions["pivot"]
    assert piv is not None
    assert piv["col_key"] == 0  # species
    assert piv["row_key"] == 1  # variable
    assert piv["value_cols"] == [2, 3]  # mean, std
    assert piv["retain_row_cols"] == [5]  # p_value kept once on right
    assert piv["col_counts"] == {"Adelie": "151", "Chinstrap": "68", "Gentoo": "123"}


def test_fixture_wide_years_dirty() -> None:
    raw = (FIXTURES_DIR / "wide_years_dirty.csv").read_bytes()
    snap = parse_tabular_bytes(raw, filename="wide_years_dirty.csv")
    runs = snap.suggestions["sparkline_runs"]
    assert len(runs) == 1
    assert runs[0]["source_cols"] == [1, 2, 3, 4, 5, 6]
    assert runs[0]["label"] == "2000–2023"
    # Verify quoted thousands "1,234.5" and "+1276.8" parsed cleanly
    assert snap.column_stats[1]["min_val"] == pytest.approx(-3.2)
    assert snap.column_stats[1]["max_val"] == pytest.approx(1234.5)
    assert snap.column_stats[7]["max_val"] == pytest.approx(1276.8)


def test_fixture_wide_tall_dupheaders() -> None:
    raw = (FIXTURES_DIR / "wide_tall_dupheaders.csv").read_bytes()
    snap = parse_tabular_bytes(raw, filename="wide_tall_dupheaders.csv")
    warn_codes = {w["code"] for w in snap.warnings}
    assert "DUPLICATE_HEADERS" in warn_codes
    resolved = snap.suggestions["resolved_headers"]
    assert len(resolved) == len(set(resolved))
    assert "S0 (2)" in resolved


def test_fixture_text_only_blank_rows() -> None:
    raw = (FIXTURES_DIR / "text_only_blank_rows.csv").read_bytes()
    snap = parse_tabular_bytes(raw, filename="text_only_blank_rows.csv")
    roles = list(snap.suggestions["roles"].values())
    assert "heat" not in roles
    assert snap.suggestions["header_rows"] == [0, 0]


def test_ragged_rows_padded_and_warned() -> None:
    csv_txt = "Metric,ArmA,ArmB,P\nAlpha,12.1,15.4\nBeta,9.2,11.8,0.03,EXTRA\n"
    snap = parse_tabular_bytes(csv_txt.encode("utf-8"), filename="ragged.csv")
    assert all(len(r) == 5 for r in snap.grid)
    assert any(w["code"] == "RAGGED_ROWS" for w in snap.warnings)


def test_three_column_ci_merge_detection() -> None:
    tsv = "Outcome\tAdjusted OR\tCI_Lower\tCI_Upper\tP_value\nMACE\t1.84\t1.21\t2.79\t0.004\nStroke\t1.12\t0.74\t1.69\t0.58\n"
    snap = parse_tabular_paste(pasted_text=tsv)
    merges = snap.suggestions["merges"]
    assert merges == [{"source_cols": [1, 2, 3], "pattern": "ci"}]


def test_paste_html_table_colspan_and_danqing_rules_roundtrip() -> None:
    rules_obj = {
        "schema": "danqing.table_studio.v2",
        "rawGrid": [["Var", "Val"], ["A", "1.5"], ["B", "2.5"]],
        "structure": {"title": "Restored Title"},
    }
    escaped = html.escape(json.dumps(rules_obj), quote=True)
    pasted_html = f'<table data-danqing-rules="{escaped}"><tr><th>Var</th><th>Val</th></tr><tr><td>A</td><td>1.5*</td></tr></table>'
    snap = parse_tabular_paste(pasted_html=pasted_html)
    assert snap.restored_rules is not None
    assert snap.restored_rules["structure"]["title"] == "Restored Title"
    assert snap.grid == [["Var", "Val"], ["A", "1.5"], ["B", "2.5"]]

    # Plain HTML table with colspan header
    plain_html = (
        "<table>"
        "<tr><th>Variable</th><th colspan='2'>Control</th><th>P</th></tr>"
        "<tr><th></th><th>Mean</th><th>SD</th><th></th></tr>"
        "<tr><td>BMI</td><td>24.1</td><td>3.2</td><td>0.02*</td></tr>"
        "<tr><td>SBP</td><td>122.0</td><td>14.5</td><td>0.41</td></tr>"
        "</table>"
    )
    snap2 = parse_tabular_paste(pasted_html=plain_html)
    assert snap2.suggestions["header_rows"] == [0, 1]
    assert snap2.suggestions["spanners"] == [{"label": "Control", "source_cols": [1, 2]}]
    assert snap2.grid[2][3] == "0.02"  # star stripped cleanly


def test_paste_hash_block_headers_and_star_stripping() -> None:
    txt = "Marker\tControl\tTreated\tFDR\n# Cytokines\nCXCL9\t12.4\t48.2\t0.002**\nIFNG\t8.1\t29.5\t0.014*\n# Myeloid\nSPP1\t44.0\t19.2\t0.0004***\nTREM2\t31.2\t15.8\t0.041*\n"
    snap = parse_tabular_paste(pasted_text=txt)
    assert snap.suggestions["part_by"] == 0
    assert snap.grid[1][0] == "Cytokines"
    assert snap.grid[1][4] == "0.002"
    assert snap.grid[3][0] == "Myeloid"
    assert snap.grid[3][4] == "0.0004"


def test_friendly_i18n_error_keys_via_api() -> None:
    # 1. Header-only CSV -> noDataRows
    r1 = client.post(
        "/api/v2/tables/parse",
        files={"file": ("header_only.csv", b"ColA,ColB,ColC\n", "text/csv")},
    )
    assert r1.status_code == 422
    assert r1.json()["error_key"] == "tableStudio.errors.noDataRows"

    # 2. Empty file -> emptyFile
    r2 = client.post(
        "/api/v2/tables/parse",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert r2.status_code == 422
    assert r2.json()["error_key"] == "tableStudio.errors.emptyFile"

    # 3. Binary PNG masquerading as CSV -> decodeFailed
    r3 = client.post(
        "/api/v2/tables/parse",
        files={"file": ("fake.csv", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "text/csv")},
    )
    assert r3.status_code == 422
    assert r3.json()["error_key"] == "tableStudio.errors.decodeFailed"

    # 4. Unsupported extension -> unsupported
    r4 = client.post(
        "/api/v2/tables/parse",
        files={"file": ("archive.parquet", b"PAR1data", "application/octet-stream")},
    )
    assert r4.status_code == 422
    assert r4.json()["error_key"] == "tableStudio.errors.unsupported"

    # 5. Empty XLSX sheet selection -> noDataRows
    wb = openpyxl.Workbook()
    ws1 = wb.active
    assert ws1 is not None
    ws1.title = "Data"
    ws1.append(["X", "Y"])
    ws1.append([1, 2])
    wb.create_sheet("BlankSheet")
    buf = io.BytesIO()
    wb.save(buf)
    r5 = client.post(
        "/api/v2/tables/parse",
        files={"file": ("two.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"sheet_name": "BlankSheet"},
    )
    assert r5.status_code == 422
    assert r5.json()["error_key"] == "tableStudio.errors.noDataRows"


def test_samples_api_endpoints() -> None:
    resp = client.get("/api/v2/tables/samples")
    assert resp.status_code == 200
    samples = resp.json()["samples"]
    assert len(samples) == 3
    for s in samples:
        assert 1 <= len(s["preview_grid"]) <= 6
        r_item = client.get(f"/api/v2/tables/samples/{s['id']}")
        assert r_item.status_code == 200
        payload = r_item.json()
        assert payload["source"]["kind"] == "sample"
        assert len(payload["grid"]) >= 6
