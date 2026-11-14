"""Tests for Manuscript Match (`/api/v2/figures/{id}/manuscript-match`) and MCP server (`danqing.mcp_server`)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from danqing.manuscript_matcher import match_manuscript_palettes
from danqing.mcp_server import handle_jsonrpc_message
from danqing.palettes import get_palette, list_palettes
from danqing.pdf_engine import parse_pdf_scene
from danqing.solver import solve_scene_colors
from web.backend.app import app

REPO = Path(__file__).resolve().parents[1]
SAMPLE_PDF = REPO / "bench" / "figures" / "01_PalmerPenguins_MultiModal_Gorman2014.pdf"
SHIELD_PDF = REPO / "bench" / "figures" / "02_Histology_WB_EvidenceShield_10xVisium.pdf"


def test_manuscript_match_api_presets_and_isolation() -> None:
    c1 = TestClient(app)
    c2 = TestClient(app)

    r_open = c1.post("/api/v2/figures?sync=true", data={"preset_id": "penguins_multimodal"})
    assert r_open.status_code == 200
    fid = r_open.json()["figure_id"]

    up = c1.post(
        "/api/v2/figures?sync=true",
        files={"file": ("penguins.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
    )
    assert up.status_code == 200
    up_id = up.json()["figure_id"]

    forbidden = c2.post(f"/api/v2/figures/{up_id}/manuscript-match", json={"preset": "cns_clean"})
    assert forbidden.status_code == 404

    for preset in ("cns_clean", "clinical", "omics", "museum"):
        res = c1.post(
            f"/api/v2/figures/{fid}/manuscript-match",
            json={"preset": preset, "brief": "Nature Medicine tumor immunology"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["engine"] in ("perceptual", "gemini")
        recs = body["recommendations"]
        assert len(recs) == 3
        for rec in recs:
            assert rec["palette_id"]
            assert rec["reason"]["en"]
            assert rec["reason"]["zh"]


def test_mcp_server_tools_end_to_end(tmp_path: Path) -> None:
    init_resp = handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
    )
    assert init_resp is not None
    assert init_resp["result"]["serverInfo"]["name"] == "danqing_mcp"

    list_resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert list_resp is not None
    tool_names = {t["name"] for t in list_resp["result"]["tools"]}
    assert {
        "danqing_inspect_figure",
        "danqing_match_manuscript_palettes",
        "danqing_recolor_figure",
        "danqing_list_palettes",
    }.issubset(tool_names)

    # 1. Inspect figure with protected raw experimental images
    insp = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "danqing_inspect_figure", "arguments": {"file_path": str(SHIELD_PDF)}},
        }
    )
    assert insp is not None and not insp["result"]["isError"]
    insp_data = json.loads(insp["result"]["content"][0]["text"])
    assert insp_data["protected_raw_image_count"] >= 1

    # 2. Match manuscript palettes
    match = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "danqing_match_manuscript_palettes",
                "arguments": {
                    "file_path": str(SAMPLE_PDF),
                    "preset": "clinical",
                    "brief": "Lancet clinical oncology cohort",
                },
            },
        }
    )
    assert match is not None and not match["result"]["isError"]
    match_data = json.loads(match["result"]["content"][0]["text"])
    assert len(match_data["recommendations"]) == 3
    picked_id = match_data["recommendations"][0]["palette_id"]

    # 3. Losslessly recolor and write R/Python snippets
    out_pdf = tmp_path / "recolored_shield.pdf"
    recol = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "danqing_recolor_figure",
                "arguments": {
                    "input_path": str(SHIELD_PDF),
                    "output_path": str(out_pdf),
                    "palette_id": picked_id,
                    "write_code_snippets": True,
                },
            },
        }
    )
    assert recol is not None and not recol["result"]["isError"]
    recol_data = json.loads(recol["result"]["content"][0]["text"])
    assert recol_data["integrity_audit"]["geometry_and_text_identical"] is True
    assert recol_data["integrity_audit"]["raw_experimental_images_identical"] is True
    assert out_pdf.is_file()
    assert out_pdf.with_suffix(".palette.R").is_file()
    assert out_pdf.with_suffix(".palette.py").is_file()


def test_expanded_3434_palettes_cns_purity_and_homologous_paired_ramps() -> None:
    all_pals = list_palettes(include_conventions=True)
    assert len(all_pals) == 3434

    # Journal collection purity: non-academic pop-culture prefixes are moved to `museum`
    non_academic_prefixes = (
        "pypal_palettetown_",
        "pypal_nbapalettes_",
        "pypal_tvthemes_",
        "pypal_beyonce_",
        "pypal_harrypotter_",
        "pypal_gameofthrones_",
        "pypal_taylorswift_",
    )
    journal_ids = [p.id for p in all_pals if p.collection == "journal"]
    assert len(journal_ids) == 728
    assert not any(jid.startswith(non_academic_prefixes) for jid in journal_ids)

    # Every palette exposes 7-stop paired_sequential_stops & paired_diverging_stops in to_api_dict()
    for pid in ("okabe_ito", "cns_nature_immunology_8", "cns_ramp_teal_navy_7", "sanzo_wada_121", "nice_cl_0002"):
        pal = get_palette(pid)
        api_d = pal.to_api_dict()
        seq_stops = api_d["partners"]["paired_sequential_stops"]
        div_stops = api_d["partners"]["paired_diverging_stops"]
        assert len(seq_stops) == 7
        assert len(div_stops) == 7

    # CNS Clean Manuscript Match returns curated CNS palettes + paired CNS continuous/diverging ramps
    cns_res = match_manuscript_palettes(preset="cns_clean", has_continuous=True, gemini_api_key="")
    cns_ids = [r["palette_id"] for r in cns_res["recommendations"]]
    assert len(cns_ids) == 3
    assert all(pid.startswith("cns_") for pid in cns_ids)
    assert all(r["paired_sequential"].startswith("cns_ramp_") for r in cns_res["recommendations"])
    assert all(r["paired_diverging"].startswith("cns_div_") for r in cns_res["recommendations"])

    cns_seq_only = match_manuscript_palettes(preset="cns_clean", required_k=1, has_continuous=True, gemini_api_key="")
    assert cns_seq_only["recommendations"][0]["palette_id"] == "cns_ramp_teal_navy_7"

    cns_div_only = match_manuscript_palettes(
        preset="cns_clean", required_k=1, has_continuous=True, has_diverging=True, gemini_api_key=""
    )
    assert cns_div_only["recommendations"][0]["palette_id"] == "cns_div_slate_terracotta_7"

    # Web API /api/v2/palettes serves all 3,434 palettes with paired stops
    c = TestClient(app)
    res = c.get("/api/v2/palettes")
    assert res.status_code == 200
    payload = res.json()
    assert len(payload["palettes"]) == 3434
    sample_api = next(x for x in payload["palettes"] if x["id"] == "cns_nature_immunology_8")
    assert len(sample_api["partners"]["paired_sequential_stops"]) == 7
    assert len(sample_api["partners"]["paired_diverging_stops"]) == 7

    # Solver uses homologous paired_sequential_stops & paired_diverging_stops on continuous scales
    sc_seq = parse_pdf_scene(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name, "seq_pair_test")
    pal_sw = get_palette("cns_nature_immunology_8")
    sr_seq = solve_scene_colors(sc_seq.entities, sc_seq.continuous_scales, sc_seq.evidence_regions, "cns_nature_immunology_8")
    sid_seq = next(iter(sc_seq.continuous_scales))
    assert sr_seq.scale_stops[sid_seq] == list(pal_sw.paired_sequential_stops)

    sc_div = parse_pdf_scene(SHIELD_PDF.read_bytes(), SHIELD_PDF.name, "div_pair_test")
    sr_div = solve_scene_colors(sc_div.entities, sc_div.continuous_scales, sc_div.evidence_regions, "cns_nature_immunology_8")
    sid_div = next(iter(sc_div.continuous_scales))
    assert sr_div.scale_stops[sid_div] == list(pal_sw.paired_diverging_stops)

    # MCP list_palettes exposes partners.paired_sequential_stops & paired_diverging_stops
    mcp_pals = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "danqing_list_palettes", "arguments": {"query": "cns_nature_immunology_8", "limit": 5}},
        }
    )
    assert mcp_pals is not None and not mcp_pals["result"]["isError"]
    mcp_list = json.loads(mcp_pals["result"]["content"][0]["text"])["palettes"]
    assert len(mcp_list) >= 1
    assert len(mcp_list[0]["partners"]["paired_sequential_stops"]) == 7
    assert len(mcp_list[0]["partners"]["paired_diverging_stops"]) == 7

