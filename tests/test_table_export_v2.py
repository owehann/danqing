"""WP T7 Verification: Native .xlsx (CellRichText, spanners, numeric cells, `data` sheet, comments, freeze),
.docx (gridSpan, w:tblHeader, w:cantSplit, three-line borders, superscripts), and .zip (`make_table.py` great_tables execution)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import openpyxl
from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from openpyxl.cell.rich_text import CellRichText

from web.backend.app import app

client = TestClient(app)


def _sample_v2_export_payload() -> dict:
    return {
        "filename_stem": "Table_1_Cleveland_Cohort",
        "title": "Table 1. Baseline clinical characteristics by coronary artery disease status",
        "subtitle": "Univariate comparisons across Cleveland Heart Disease cohort (N = 303).",
        "preset": "cns_three_line",
        "spanners": [
            {"label": "No CAD (n=164)", "superscript": "", "start_col": 1, "end_col": 1},
            {"label": "Cohort Arms", "superscript": "a", "start_col": 1, "end_col": 2},
        ],
        "headers": [
            {"label": "Characteristic", "superscript": "", "align": "left"},
            {"label": "No CAD Mean (SD)", "superscript": "", "align": "right"},
            {"label": "CAD Mean (SD)", "superscript": "", "align": "right"},
            {"label": "Age Raw", "superscript": "", "align": "right"},
            {"label": "Trajectory", "superscript": "", "align": "right"},
            {"label": "P value", "superscript": "b", "align": "right"},
        ],
        "blocks": [
            {
                "part_name": "Continuous Hemodynamics",
                "part_accent": "#2E6F95",
                "rows": [
                    [
                        {
                            "text": "Age (years)",
                            "superscript": "c",
                            "align": "left",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "sparkline_values": None,
                            "edited_from": "age",
                            "indent": 0,
                        },
                        {
                            "text": "52.6 (9.5)",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "sparkline_values": None,
                            "no_wrap": True,
                        },
                        {
                            "text": "56.6 (7.9)",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "sparkline_values": None,
                            "no_wrap": True,
                        },
                        {
                            "text": "54.4",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#EFF6F7",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": 54.4389,
                            "number_format": "0.0",
                            "sparkline_values": None,
                            "edited_from": "54.0",
                        },
                        {
                            "text": "+4.0",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "sparkline_values": [48.1, 51.2, 54.4, 56.6],
                        },
                        {
                            "text": "<0.001***",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": True,
                            "box_border": False,
                            "raw_number": 6.35e-5,
                            "number_format": "",
                            "sparkline_values": None,
                        },
                    ],
                    [
                        {
                            "text": "Male sex, n (%)",
                            "superscript": "",
                            "align": "left",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "indent": 1,
                        },
                        {
                            "text": "92 (56.1%)",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "no_wrap": True,
                        },
                        {
                            "text": "114 (82.0%)",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                            "no_wrap": True,
                        },
                        {
                            "text": "206",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": 206,
                            "number_format": "0",
                        },
                        {
                            "text": "—",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": False,
                            "box_border": False,
                            "raw_number": None,
                            "number_format": "",
                        },
                        {
                            "text": "<0.001***",
                            "superscript": "",
                            "align": "right",
                            "bg_hex": "#FFFFFF",
                            "fg_hex": "#111827",
                            "bold": True,
                            "box_border": False,
                            "raw_number": 2.66e-6,
                            "number_format": "",
                        },
                    ],
                ],
            }
        ],
        "footnotes": [
            {"symbol": "a", "text": "Stratified by angiographic coronary artery disease."},
            {"symbol": "b", "text": "Welch two-sample t-test or Pearson chi-square test."},
            {"symbol": "c", "text": "Label edited from raw code 'age'."},
            {"symbol": "", "text": "* P < 0.05; ** P < 0.01; *** P < 0.001."},
        ],
        "raw_data_sheet": {
            "headers": [
                "Characteristic",
                "No_CAD_Mean",
                "No_CAD_SD",
                "CAD_Mean",
                "CAD_SD",
                "Age_Raw",
                "T1",
                "T2",
                "T3",
                "T4",
                "P_value",
            ],
            "rows": [
                ["Age (years)", 52.5854, 9.512, 56.6259, 7.9389, 54.4389, 48.1, 51.2, 54.4, 56.6, 6.35e-5],
                ["Male sex, n (%)", 92, "56.0976%", 114, "82.0144%", 206, "", "", "", "", 2.66e-6],
            ],
        },
    }


def test_export_xlsx_v2_rich_superscripts_spanners_data_sheet_and_comments() -> None:
    payload = _sample_v2_export_payload()
    payload["spanners"] = [
        {"label": "Cohort Arms", "superscript": "a", "start_col": 1, "end_col": 2}
    ]
    resp = client.post("/api/v2/tables/export/xlsx", json=payload)
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content), rich_text=True)
    assert wb.sheetnames == ["Table", "data"]

    ws = wb["Table"]
    # Print page setup fitToWidth = 1
    assert ws.page_setup.fitToWidth == 1
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True

    # Freeze panes below leaf header row (Row 4) and column B
    assert ws.freeze_panes == "B5"

    # Verify spanner merge B3:C3 and CellRichText superscript 'a'
    merge_strs = {str(m) for m in ws.merged_cells.ranges}
    assert "B3:C3" in merge_strs
    sp_val = ws["B3"].value
    assert isinstance(sp_val, CellRichText)
    assert any(getattr(getattr(b, "font", None), "vertAlign", None) == "superscript" for b in sp_val)

    # Verify leaf header F4 has CellRichText superscript 'b' (NOT '[b]')
    hdr_f = ws["F4"].value
    assert isinstance(hdr_f, CellRichText)
    assert "[" not in str(hdr_f)
    assert any(
        getattr(getattr(b, "font", None), "vertAlign", None) == "superscript" and str(b) == "b"
        for b in hdr_f
    )

    # Row 5 is block banner 'Continuous Hemodynamics', Row 6 is first data row, Row 7 is second data row
    age_num_cell = ws["D6"]
    assert isinstance(age_num_cell.value, float)
    assert abs(age_num_cell.value - 54.4389) < 1e-6
    assert age_num_cell.number_format == "0.0"
    assert age_num_cell.comment is not None
    assert "Original: 54.0" in age_num_cell.comment.text

    # Edited label cell A6 also carries comment + superscript 'c'
    a6_cell = ws["A6"]
    assert isinstance(a6_cell.value, CellRichText)
    assert a6_cell.comment is not None
    assert "Original: age" in a6_cell.comment.text

    # Count cell D7 stored as int
    assert ws["D7"].value == 206
    assert isinstance(ws["D7"].value, int)

    # Raw `data` sheet contains unmerged floats for downstream calculation
    ws_data = wb["data"]
    assert ws_data["A1"].value == "Characteristic"
    assert isinstance(ws_data["B2"].value, float)
    assert abs(ws_data["B2"].value - 52.5854) < 1e-6
    assert isinstance(ws_data["G2"].value, float)


def test_export_docx_v2_gridspan_tblheader_cantsplit_and_superscripts() -> None:
    payload = _sample_v2_export_payload()
    payload["spanners"] = [
        {"label": "Cohort Arms", "superscript": "a", "start_col": 1, "end_col": 2}
    ]
    resp = client.post("/api/v2/tables/export/docx", json=payload)
    assert resp.status_code == 200

    doc = Document(io.BytesIO(resp.content))
    assert len(doc.tables) == 1
    tbl = doc.tables[0]

    # Row 0 = Spanner row, Row 1 = Leaf header, Row 2 = Block banner, Row 3 & 4 = Data rows
    assert len(tbl.rows) == 5

    # Verify <w:tblHeader/> on header rows and <w:cantSplit/> on data rows
    assert tbl.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert tbl.rows[1]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert tbl.rows[3]._tr.trPr.find(qn("w:cantSplit")) is not None

    # Verify gridSpan=2 on Cohort Arms spanner cell
    sp_tc = tbl.rows[0]._tr.xpath("./w:tc")[1]
    grid_span = sp_tc.find(qn("w:tcPr")).find(qn("w:gridSpan"))
    assert grid_span is not None
    assert grid_span.get(qn("w:val")) == "2"

    # Verify superscript runs on P value^b and Age^c
    hdr_sups = [r.text for r in tbl.rows[1].cells[5].paragraphs[0].runs if r.font.superscript]
    assert "b" in hdr_sups
    body_sups = [r.text for r in tbl.rows[3].cells[0].paragraphs[0].runs if r.font.superscript]
    assert "c" in body_sups

    # Verify three-line closing bottom border 1.5pt (sz=12) and zero vertical borders
    last_borders = tbl.rows[4].cells[1]._tc.tcPr.find(qn("w:tcBorders"))
    assert last_borders.find(qn("w:bottom")).get(qn("w:sz")) == "12"
    assert last_borders.find(qn("w:left")).get(qn("w:val")) == "nil"
    assert last_borders.find(qn("w:right")).get(qn("w:val")) == "nil"


def test_export_zip_bundle_and_execute_great_tables_script(tmp_path: Path) -> None:
    zip_payload = {
        "filename_stem": "penguins_reproducible",
        "table_json": {
            "schema": "danqing.table_studio.v2",
            "structure": {"stage": "tidied", "title": "Table 1. Penguin morphometrics"},
            "style": {"preset": "cns_three_line"},
        },
        "csv_headers": [
            "Variable",
            "Adelie_mean",
            "Adelie_sd",
            "Gentoo_mean",
            "Gentoo_sd",
            "p_value",
        ],
        "csv_rows": [
            ["Bill length (mm)", 38.791, 2.663, 47.505, 3.082, "<0.001"],
            ["Flipper length (mm)", 189.954, 6.539, 217.187, 6.485, "0.0002"],
        ],
        "gt_meta": {
            "title": "Table 1. Penguin morphometrics",
            "subtitle": "Palmer Station LTER",
            "rowname_col": "Variable",
            "p_cols": ["p_value"],
            "decimals_map": {
                "Adelie_mean": 1,
                "Adelie_sd": 1,
                "Gentoo_mean": 1,
                "Gentoo_sd": 1,
            },
            "spanners": [
                {"label": "Adelie (n=151)", "columns": ["Adelie_mean", "Adelie_sd"]},
                {"label": "Gentoo (n=123)", "columns": ["Gentoo_mean", "Gentoo_sd"]},
            ],
            "merges": [
                {"columns": ["Adelie_mean", "Adelie_sd"], "pattern": "{0} ({1})"},
                {"columns": ["Gentoo_mean", "Gentoo_sd"], "pattern": "{0} ({1})"},
            ],
            "footnotes": [
                {"symbol": "*", "text": "One-way ANOVA across species."},
            ],
        },
    }

    resp = client.post("/api/v2/tables/export/zip", json=zip_payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert set(zf.namelist()) == {"table.json", "data.csv", "make_table.py"}
        zf.extractall(tmp_path)

    loaded_json = json.loads((tmp_path / "table.json").read_text("utf-8"))
    assert loaded_json["schema"] == "danqing.table_studio.v2"

    proc = subprocess.run(
        [sys.executable, str(tmp_path / "make_table.py")],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"make_table.py failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    rendered_html = (tmp_path / "table_rendered.html").read_text("utf-8")
    assert "Table 1. Penguin morphometrics" in rendered_html
    assert "Adelie (n=151)" in rendered_html


def test_end_to_end_all_3_samples_and_6_hostile_fixtures_parse_to_xlsx_and_docx() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixtures_dir = repo_root / "tests" / "fixtures" / "tables"
    fixture_files = sorted(p for p in fixtures_dir.iterdir() if p.is_file())
    assert len(fixture_files) == 6

    snapshots: list[tuple[str, dict]] = []
    for sample_id in ("penguins_long", "uci_cleveland_table1", "owid_renewables_wide"):
        s_resp = client.get(f"/api/v2/tables/samples/{sample_id}")
        assert s_resp.status_code == 200
        snapshots.append((sample_id, s_resp.json()))

    for fpath in fixture_files:
        with fpath.open("rb") as fh:
            p_resp = client.post(
                "/api/v2/tables/parse",
                files={"file": (fpath.name, fh, "application/octet-stream")},
            )
        assert p_resp.status_code == 200, f"Parse failed for {fpath.name}: {p_resp.text}"
        snapshots.append((fpath.stem, p_resp.json()))

    assert len(snapshots) == 9
    for stem, snap in snapshots:
        grid = snap["grid"]
        sug = snap["suggestions"]
        h0, h1 = sug["header_rows"]
        b0, b1 = sug["body_range"]
        resolved_headers = sug.get("resolved_headers") or grid[h0]
        spanners = [
            {
                "label": sp["label"],
                "superscript": "",
                "start_col": min(sp["source_cols"]),
                "end_col": max(sp["source_cols"]),
            }
            for sp in sug.get("spanners", [])
            if sp.get("source_cols")
        ]
        headers = [
            {
                "label": str(lbl or f"Col_{idx + 1}"),
                "superscript": "",
                "align": "left" if idx == 0 else "right",
            }
            for idx, lbl in enumerate(resolved_headers)
        ]
        body_rows_raw = grid[b0 : b1 + 1]
        rendered_rows = [
            [
                {
                    "text": str(val),
                    "superscript": "",
                    "align": "left" if c_idx == 0 else "right",
                    "bg_hex": "#FFFFFF",
                    "fg_hex": "#111827",
                    "bold": False,
                    "box_border": False,
                    "raw_number": None,
                    "number_format": "",
                }
                for c_idx, val in enumerate(r[: len(headers)])
            ]
            for r in body_rows_raw
        ]
        export_payload = {
            "filename_stem": stem,
            "title": sug.get("title_candidate") or f"Table — {stem}",
            "subtitle": "",
            "preset": "cns_three_line",
            "spanners": spanners,
            "headers": headers,
            "blocks": [{"part_name": "", "part_accent": "#2E6F95", "rows": rendered_rows}],
            "footnotes": [
                {"symbol": chr(97 + idx), "text": fn}
                for idx, fn in enumerate(sug.get("footnote_candidates", []))
            ],
            "raw_data_sheet": {"headers": [h["label"] for h in headers], "rows": body_rows_raw},
        }

        rx = client.post("/api/v2/tables/export/xlsx", json=export_payload)
        assert rx.status_code == 200, f"XLSX export failed for {stem}"
        wb = openpyxl.load_workbook(io.BytesIO(rx.content), rich_text=True)
        assert wb.sheetnames == ["Table", "data"]

        rd = client.post("/api/v2/tables/export/docx", json=export_payload)
        assert rd.status_code == 200, f"DOCX export failed for {stem}"
        doc = Document(io.BytesIO(rd.content))
        assert len(doc.tables) == 1

