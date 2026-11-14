"""Unit and golden benchmark tests for Danqing's Style Engine (`core/danqing/style_engine.py`)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from danqing.color_science import (
    ciede2000_matrix,
    hex_to_oklch,
    hex_to_srgb01,
    interpolate_oklch_lut,
    oklab_to_oklch,
    srgb01_to_hex,
    srgb_to_oklab,
)
from danqing.mcp_server import execute_tool
from danqing.pdf_engine import parse_pdf_scene, render_pdf_page_to_pil
from danqing.solver import solve_scene_colors
from danqing.style_engine import (
    STYLE_PROFILES,
    _angle_in_sector,
    apply_style_to_solve_result,
    export_styled_figure,
    extract_style_profile,
    list_styles,
    sculpt_continuous_stops,
    sculpt_scene_style,
)
from danqing.svg_engine import parse_svg_scene

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = REPO_ROOT / "bench" / "figures"

REQUIRED_STYLES = (
    "aegean_blue_white",
    "qingbai_porcelain",
    "warm_terracotta",
    "bauhaus_airy",
    "ink_vermilion",
    "vermeer_jewel",
    "twilight_indigo",
    "kyoto_moss",
)


def _in_sector_with_tol(h_deg: float, sector: tuple[float, float], tol_deg: float = 3.0) -> bool:
    if _angle_in_sector(h_deg, sector):
        return True
    for ep in sector:
        diff = abs(((h_deg - ep + 180.0) % 360.0) - 180.0)
        if diff <= tol_deg:
            return True
    return False


def test_eight_builtin_styles_present_and_quadrant_distinct() -> None:
    ids = [s.id for s in list_styles()]
    for req_id in REQUIRED_STYLES:
        assert req_id in STYLE_PROFILES
        assert req_id in ids

    scene = parse_pdf_scene(
        (BENCH_DIR / "01_PalmerPenguins_MultiModal_Gorman2014.pdf").read_bytes(),
        "01_PalmerPenguins_MultiModal_Gorman2014.pdf",
        "penguins",
    )
    base_solved = solve_scene_colors(
        scene.entities,
        scene.continuous_scales,
        scene.evidence_regions,
        style_id="okabe_ito",
    )
    eids = sorted(scene.entities.keys())
    style_rgb_ById: dict[str, np.ndarray] = {}
    for sid in REQUIRED_STYLES:
        sc_res = apply_style_to_solve_result(scene, base_solved, sid)
        style_rgb_ById[sid] = np.stack([hex_to_srgb01(sc_res.entity_hex[e]) for e in eids], axis=0)

    # Every pair of built-in styles applied to the same palette must be clearly distinct
    for i, sa in enumerate(REQUIRED_STYLES):
        for sb in REQUIRED_STYLES[i + 1 :]:
            mean_de = float(np.mean(np.diag(ciede2000_matrix(style_rgb_ById[sa], style_rgb_ById[sb]))))
            assert mean_de >= 15.0, f"Styles {sa} and {sb} are too similar (mean ΔE2000={mean_de:.2f})"


@pytest.mark.parametrize("style_id", REQUIRED_STYLES)
def test_penguins_and_visium_brain_golden_invariants(style_id: str) -> None:
    prof = STYLE_PROFILES[style_id]
    s_peng = parse_pdf_scene(
        (BENCH_DIR / "01_PalmerPenguins_MultiModal_Gorman2014.pdf").read_bytes(),
        "01_PalmerPenguins_MultiModal_Gorman2014.pdf",
        "peng",
    )
    s_brain = parse_pdf_scene(
        (BENCH_DIR / "04_MouseBrain_Visium_Complex_10xGenomics.pdf").read_bytes(),
        "04_MouseBrain_Visium_Complex_10xGenomics.pdf",
        "brain",
    )

    # 1. Export & verify Gate G6 geometry/text & Gate G0 raw images bit-identity
    pdf_peng_a, aud_peng_a, res_peng_a = export_styled_figure(s_peng, style_id, palette_id="okabe_ito")
    pdf_peng_b, aud_peng_b, res_peng_b = export_styled_figure(s_peng, style_id, palette_id="npg")
    pdf_brain, aud_brain, res_brain = export_styled_figure(s_brain, style_id, palette_id="cns_cell_atlas_10")

    assert aud_peng_a["g6_geometry_identical"] is True
    assert aud_peng_a["g0_evidence_bit_identical"] is True
    assert aud_peng_b["g6_geometry_identical"] is True
    assert aud_brain["g6_geometry_identical"] is True
    assert aud_brain["g0_evidence_bit_identical"] is True
    assert len(pdf_peng_a) > 1000 and len(pdf_brain) > 1000

    # 2. Canvas paper background (#FFFFFF) at page corners remains untouched pure white
    pil_peng = render_pdf_page_to_pil(pdf_peng_a, page_index=0, scale=1.0)
    assert pil_peng.getpixel((2, 2))[:3] == (255, 255, 255)

    # 3. Palette Personality Preservation: okabe_ito vs npg under identical style remain distinct
    eids = sorted(s_peng.entities.keys())
    arr_a = np.stack([hex_to_srgb01(res_peng_a.entity_hex[e]) for e in eids], axis=0)
    arr_b = np.stack([hex_to_srgb01(res_peng_b.entity_hex[e]) for e in eids], axis=0)
    mean_pair_de = float(np.mean(np.diag(ciede2000_matrix(arr_a, arr_b))))
    assert mean_pair_de >= 15.0, f"{style_id} collapsed palette individuality (mean ΔE={mean_pair_de:.2f})"
    assert res_peng_a.entity_hex != res_peng_b.entity_hex

    # 4. Panel-scoped anti-collision guardrail (min ΔE2000 >= 9.0)
    assert float(res_peng_a.diagnostics["min_de2000_normal"]) >= 9.0
    assert float(res_brain.diagnostics["min_de2000_normal"]) >= 9.0

    # 5. Control layer protection (`Out of Tissue` e_09 in MouseBrain stays recessive neutral)
    L_oot, C_oot, _ = hex_to_oklch(res_brain.entity_hex["e_09"])
    assert L_oot >= 0.70 and C_oot <= 0.032

    # 6. Zero "muddy gray mixing" & strict OKLCH lightness/hue envelope adherence on data entities
    brain_data_eids = [e for e in s_brain.entities if e not in ("e_09", "e_10")]
    for eid in brain_data_eids:
        L_val, C_val, h_val = hex_to_oklch(res_brain.entity_hex[eid])
        assert prof.l_band[0] - 0.02 <= L_val <= prof.l_band[1] + 0.02
        c_floor = prof.c_band[0] if not prof.accent_c_band else min(prof.c_band[0], prof.accent_c_band[0])
        assert C_val >= c_floor - 0.008
        if prof.hue_sector is not None:
            in_main = _in_sector_with_tol(h_val, prof.hue_sector)
            in_acc = prof.accent_hue_sector is not None and _in_sector_with_tol(h_val, prof.accent_hue_sector)
            assert in_main or in_acc, f"{style_id}: hue {h_val:.1f} outside {prof.hue_sector} / {prof.accent_hue_sector}"

    # 7. Continuous scales: colorbar `scale_stops` AND `member_group_ids` in `group_hex` sync + strict L(t) monotonicity
    for scene_cur, res_cur in ((s_peng, res_peng_a), (s_brain, res_brain)):
        for sid, cs in scene_cur.continuous_scales.items():
            stops = res_cur.scale_stops[sid]
            assert stops != list(cs.original_stops_hex)
            l_stops = [hex_to_oklch(hx)[0] for hx in stops]
            diffs = np.diff(l_stops)
            assert bool(np.all(diffs <= -1e-3) or np.all(diffs >= 1e-3)), f"Non-monotonic L(t) in {style_id}: {l_stops}"

            lut256 = interpolate_oklch_lut(stops, n=256)
            assert len(cs.member_group_ids) > 0
            for gid in cs.member_group_ids:
                cg = scene_cur.color_groups[gid]
                expected_hex = srgb01_to_hex(lut256[max(0, min(255, int(round(cg.continuous_t * 255.0))))])
                assert res_cur.group_hex[gid] == expected_hex


def test_diverging_scale_symmetry_control_tier_lock_and_evidence_shield() -> None:
    s02 = parse_pdf_scene(
        (BENCH_DIR / "02_Histology_WB_EvidenceShield_10xVisium.pdf").read_bytes(),
        "02_Histology_WB_EvidenceShield_10xVisium.pdf",
        "ev_shield",
    )
    eids = list(s02.entities.keys())
    locked_eid = eids[0]
    control_eid = eids[1]
    s02.entities[locked_eid].locked = True
    s02.entities[locked_eid].current_hex = "#123456"
    s02.entities[control_eid].tier = "control"
    s02.entities[control_eid].current_hex = "#FF00AA"  # Vivid input -> should be pushed back to recessive neutral

    out_pdf, audit, res = export_styled_figure(s02, "warm_terracotta")
    assert audit["g0_evidence_bit_identical"] is True
    assert audit["g6_geometry_identical"] is True
    assert len(out_pdf) > 1000
    assert res.entity_hex[locked_eid] == "#123456"
    assert res.entity_hex[control_eid] == STYLE_PROFILES["warm_terracotta"].recessive_control_hex

    # Diverging ramp symmetry check
    div_stops = sculpt_continuous_stops(
        ["#2166AC", "#F7F7F7", "#B2182B"],
        STYLE_PROFILES["aegean_blue_white"],
        kind="continuous_diverging",
        midpoint_t=0.5,
    )
    assert len(div_stops) == 7
    lch_div = oklab_to_oklch(srgb_to_oklab(np.stack([hex_to_srgb01(h) for h in div_stops], axis=0)))
    assert float(lch_div[3, 0]) >= 0.93 and float(lch_div[3, 1]) <= 0.015
    assert float(lch_div[0, 0]) < float(lch_div[1, 0]) < float(lch_div[2, 0]) < float(lch_div[3, 0])
    assert float(lch_div[6, 0]) < float(lch_div[5, 0]) < float(lch_div[4, 0]) < float(lch_div[3, 0])
    assert abs(float(lch_div[0, 0]) - float(lch_div[6, 0])) <= 0.03


def test_svg_scene_and_automatic_reference_style_extraction() -> None:
    s_svg = parse_svg_scene(
        (BENCH_DIR / "03_EGFR_MAPK_Pathway_Lemmon2010.svg").read_bytes(),
        "03_EGFR_MAPK_Pathway_Lemmon2010.svg",
        "svg_egfr",
    )
    extracted_from_pal = extract_style_profile("cns_nature_immunology_8")
    extracted_from_hex = extract_style_profile(["#264653", "#2A9D8F", "#E9C46A", "#E76F51"], style_id="custom_ coastal")

    svg_bytes_1, aud_1, res_1 = export_styled_figure(s_svg, extracted_from_pal, palette_id="okabe_ito")
    svg_bytes_2, aud_2, res_2 = export_styled_figure(s_svg, extracted_from_hex)
    assert aud_1["g6_geometry_identical"] is True
    assert aud_2["g6_geometry_identical"] is True
    assert b"<svg" in svg_bytes_1 and b"<svg" in svg_bytes_2
    assert len(res_1.entity_hex) == len(s_svg.entities)
    assert len(res_2.scale_stops) == len(s_svg.continuous_scales)

    # Also test direct `sculpt_scene_style` without a prior palette
    direct_sc = sculpt_scene_style(s_svg, "kyoto_moss")
    assert direct_sc.style_id == "kyoto_moss"


def test_web_studio_api_and_mcp_style_integration(tmp_path: Path) -> None:
    from web.backend.app import app

    with TestClient(app) as client:
        cat = client.get("/api/v2/palettes").json()
        assert len(cat.get("styles", [])) >= 8
        st_resp = client.get("/api/v2/styles").json()
        assert len(st_resp["styles"]) >= 8

        # Open Penguins preset
        create_res = client.post("/api/v2/figures", data={"preset_id": "penguins_multimodal"})
        assert create_res.status_code == 200
        fig_id = "penguins_multimodal"

        # Apply palette `okabe_ito`
        r_pal = client.patch(f"/api/v2/figures/{fig_id}/state", json={"action": "set_palette", "palette_id": "okabe_ito"}).json()
        assert r_pal["aesthetic_style"] is None
        colors_pal_only = r_pal["entity_colors"]

        # Hover preview a style without mutating state
        hov_png = client.get(f"/api/v2/figures/{fig_id}/render?rev={r_pal['revision']}&style=qingbai_porcelain")
        assert hov_png.status_code == 200 and hov_png.headers["content-type"] == "image/png"

        # Commit `qingbai_porcelain` aesthetic style
        r_st = client.patch(
            f"/api/v2/figures/{fig_id}/state",
            json={"action": "set_aesthetic_style", "aesthetic_style": "qingbai_porcelain"},
        ).json()
        assert r_st["aesthetic_style"] == "qingbai_porcelain"
        assert r_st["entity_colors"] != colors_pal_only

        # Preview PNG must match exported PDF rendered at preview_scale
        fig_info = client.get(f"/api/v2/figures/{fig_id}").json()
        prev_bytes = client.get(fig_info["render_url"]).content
        exp_res = client.post(
            f"/api/v2/figures/{fig_id}/export",
            json={"format": "pdf", "include_r": False, "include_python": False, "force": True},
        )
        assert exp_res.status_code == 200
        assert "qingbai_porcelain" in exp_res.headers.get("content-disposition", "")
        pil_prev = Image.open(io.BytesIO(prev_bytes)).convert("RGB")
        pil_exp = render_pdf_page_to_pil(exp_res.content, page_index=0, scale=float(fig_info["preview_scale"]))
        diff_arr = np.abs(np.asarray(pil_prev, dtype=np.int16) - np.asarray(pil_exp, dtype=np.int16))
        assert float(diff_arr.mean()) < 0.5

        # Undo restores palette-only state; Redo restores `qingbai_porcelain`
        r_undo = client.patch(f"/api/v2/figures/{fig_id}/state", json={"action": "undo"}).json()
        assert r_undo["aesthetic_style"] is None
        assert r_undo["entity_colors"] == colors_pal_only
        r_redo = client.patch(f"/api/v2/figures/{fig_id}/state", json={"action": "redo"}).json()
        assert r_redo["aesthetic_style"] == "qingbai_porcelain"

    # MCP `danqing_list_styles` & `danqing_recolor_figure` with `aesthetic_style`
    mcp_styles = execute_tool("danqing_list_styles", {})
    assert mcp_styles["count"] >= 8
    out_pdf_path = tmp_path / "penguins_qingbai.pdf"
    mcp_recolor = execute_tool(
        "danqing_recolor_figure",
        {
            "input_path": str(BENCH_DIR / "01_PalmerPenguins_MultiModal_Gorman2014.pdf"),
            "output_path": str(out_pdf_path),
            "palette_id": "okabe_ito",
            "aesthetic_style": "qingbai_porcelain",
            "write_code_snippets": True,
        },
    )
    assert mcp_recolor["aesthetic_style"] == "qingbai_porcelain"
    assert mcp_recolor["integrity_audit"]["geometry_and_text_identical"] is True
    assert mcp_recolor["integrity_audit"]["raw_experimental_images_identical"] is True
    assert out_pdf_path.is_file()
    assert out_pdf_path.with_suffix(".palette.R").is_file()
