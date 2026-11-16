"""Comprehensive unit and integration test suite for Danqing core engine (WP1–WP4: Palettes, Solver, PDF & SVG Engines)."""

from __future__ import annotations

import io
import time
import zlib
from pathlib import Path

import numpy as np
import pikepdf

from danqing.color_science import (
    apca_contrast,
    ciede2000_matrix,
    describe_color_group,
    hex_to_oklch,
    hex_to_srgb01,
    interpolate_oklch_lut,
    oklch_to_hex,
    optimal_cell_text_hex,
    simulate_cvd,
    test_2d_image_1d_manifold,
)
from danqing.exporter import (
    build_verification_certificate,
    generate_change_report_csv,
    generate_python_mpl_snippet,
    generate_r_ggplot_snippet,
)
from danqing.ir import SemanticEntity
from danqing.palettes import get_palette, list_palettes
from danqing.pdf_engine import export_recolored_pdf, inspect_pdf_document, parse_pdf_scene
from danqing.solver import solve_scene_colors
from danqing.svg_engine import export_recolored_svg, parse_svg_scene

BENCH_DIR = Path(__file__).resolve().parents[1] / "bench" / "figures"


def test_color_science_and_palettes_invariants() -> None:
    pals = list_palettes(include_conventions=True)
    assert len(pals) >= 55
    collections = {p.collection for p in pals}
    assert {"accessible", "journal", "museum", "eastern", "many", "continuous", "convention"}.issubset(collections)

    L, C, h = hex_to_oklch("#C85A53")
    rt = oklch_to_hex(L, C, h)
    de = float(ciede2000_matrix(hex_to_srgb01("#C85A53")[None, :], hex_to_srgb01(rt)[None, :])[0, 0])
    assert de < 0.8

    # Diverging Zero-Anchor preservation
    lut_div = interpolate_oklch_lut(["#23577E", "#F5F2EB", "#B0352B"], n=256, diverging_midpoint=0.5)
    mid_rgb = lut_div[128]
    assert float(np.linalg.norm(mid_rgb - hex_to_srgb01("#F5F2EB"))) < 0.03

    # Dark tile auto-flips text from #000000 to #FFFFFF under G3b APCA < 55
    assert optimal_cell_text_hex(hex_to_srgb01("#173753"), 55.0) == "#FFFFFF"
    assert optimal_cell_text_hex(hex_to_srgb01("#F4F1EA"), 55.0) == "#000000"
    assert abs(apca_contrast(hex_to_srgb01("#000000"), hex_to_srgb01("#FFFFFF"))) > 100.0

    # Machado CVD severity 0 == identity
    c_arr = np.stack([hex_to_srgb01("#C85A53"), hex_to_srgb01("#3E8E7E")], axis=0)
    assert np.allclose(simulate_cvd(c_arr, "deutan", 0.0), c_arr, atol=1e-4)

    # Human-readable fallback naming
    desc = describe_color_group("#2B6CB0", 1234)
    assert "group" in desc and "1,234 marks" in desc


def test_1d_manifold_vs_histology_separation() -> None:
    lut = interpolate_oklch_lut(["#F4EFE6", "#E29D52", "#781E20"], n=256)
    yy, xx = np.mgrid[0:64, 0:64]
    idx = ((np.sin(xx * 0.15) * 0.5 + 0.5) * 255).astype(int)
    hm_rgb = lut[idx]
    assert test_2d_image_1d_manifold(hm_rgb).is_1d_manifold is True

    he_rgb = np.zeros((64, 64, 3), dtype=np.float64)
    he_rgb[:20, :] = [0.95, 0.94, 0.96]
    he_rgb[20:42, :32] = [0.85, 0.42, 0.68]
    he_rgb[20:42, 32:] = [0.32, 0.22, 0.58]
    he_rgb[42:, :] = [0.62, 0.48, 0.25]
    assert test_2d_image_1d_manifold(he_rgb).is_1d_manifold is False


def test_wp3_solver_invariants_lock_samename_hierarchy_and_gradient_subset() -> None:
    # 1. Cross-panel same_name rule MUST NOT reuse colors across panels when K_total <= N
    ents_4 = {
        "e1": SemanticEntity("e1", "Cluster_A", "Panel A", ["Panel A"], ["g1"], "#FF0000", "#FF0000"),
        "e2": SemanticEntity("e2", "Cluster_B", "Panel A", ["Panel A"], ["g2"], "#00FF00", "#00FF00"),
        "e3": SemanticEntity("e3", "Treatment_X", "Panel B", ["Panel B"], ["g3"], "#0000FF", "#0000FF"),
        "e4": SemanticEntity("e4", "Treatment_Y", "Panel B", ["Panel B"], ["g4"], "#FF00FF", "#FF00FF", locked=True),
    }
    ents_4["e4"].current_hex = "#123456"
    sr = solve_scene_colors(ents_4, {}, [], "okabe_ito", collision_scope="same_name")
    assert sr.entity_hex["e4"] == "#123456"  # Locked stays locked!
    assert len(set(sr.entity_hex.values())) == 4  # Zero cross-panel reuse when K_total (4) <= N (8)
    assert sr.diagnostics["cross_panel_reused_count"] == 0

    # Inspector swatches contain ALL palette colors sorted by min ΔE
    okabe = get_palette("okabe_ito")
    swatches_e1 = sr.inspector_swatches["e1"]
    assert len(swatches_e1) >= len(okabe.colors)
    assert set(okabe.colors).issubset({s["hex"] for s in swatches_e1})
    min_des = [s["min_de"] for s in swatches_e1]
    assert min_des == sorted(min_des, reverse=True)

    # 2. Gradient-ordered museum palette (Hiroshige, 10 colors red->yellow->blue) must pick spread-out subset for K=3
    ents_3 = {
        f"e{i}": SemanticEntity(f"e{i}", f"Group_{i}", "Panel A", ["Panel A"], [f"g{i}"], "#888888", "#888888")
        for i in range(3)
    }
    sr_grad = solve_scene_colors(ents_3, {}, [], "met_hiroshige", collision_scope="same_name")
    arr3 = np.stack([hex_to_srgb01(h) for h in sr_grad.entity_hex.values()], axis=0)
    de3 = ciede2000_matrix(arr3)
    np.fill_diagonal(de3, 999.0)
    assert float(de3.min()) >= 18.0  # Spread across warm & cool ends, not 3 adjacent corals

    # 3. K > N with hierarchical prefix families (`CD4_*`, `CD8_*`, `Mac_*`, `Fib_*`, `B_*`)
    prefixes = ["CD4", "CD8", "Mac", "Fib", "Endo"]
    ents_15: dict[str, SemanticEntity] = {}
    for pi, pref in enumerate(prefixes):
        for sub_i in range(3):
            eid = f"h_{pi}_{sub_i}"
            ents_15[eid] = SemanticEntity(
                eid, f"{pref}_State{sub_i}", "Panel A", ["Panel A"], [f"g_{eid}"], "#555555", "#555555"
            )
    sr_hier = solve_scene_colors(ents_15, {}, [], "tol_bright", collision_scope="unique")
    assert sr_hier.diagnostics["generated_count"] == 15 - len(get_palette("tol_bright").colors)
    assert len(set(sr_hier.entity_hex.values())) == 15

    # 4. K > N flat names -> Glasbey hull expansion
    ents_14_flat = {
        f"u_{i}": SemanticEntity(f"u_{i}", f"Item{i}", "Panel A", ["Panel A"], [f"gu_{i}"], "#555555", "#555555")
        for i in range(14)
    }
    sr_glas = solve_scene_colors(ents_14_flat, {}, [], "okabe_ito", collision_scope="unique")
    assert sr_glas.diagnostics["generated_count"] == 6
    assert sr_glas.diagnostics["min_de2000_normal"] >= 8.0


def test_penguins_coupled_gradient_g3b_and_scopes() -> None:
    p = BENCH_DIR / "01_PalmerPenguins_MultiModal_Gorman2014.pdf"
    sc = parse_pdf_scene(p.read_bytes(), p.name, "penguins_mm")
    assert len(sc.panels) == 4
    assert len(sc.continuous_scales) == 1
    assert len(sc.cell_text_labels) >= 18
    labels = {e.label for e in sc.entities.values()}
    assert {"Adelie", "Chinstrap", "Gentoo", "Biscoe", "Dream", "Torgersen", "S1: Biscoe-F", "S6: Torg-M"}.issubset(labels)

    # Zero-change roundtrip is bit-identical
    raw_rt, aud0 = export_recolored_pdf(
        sc,
        {gid: cg.original_hex for gid, cg in sc.color_groups.items()},
        {sid: cs.original_stops_hex for sid, cs in sc.continuous_scales.items()},
    )
    assert raw_rt == sc.raw_pdf_bytes
    assert aud0["g6_geometry_identical"] is True

    t0 = time.perf_counter()
    sr_scoped = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "east_qinghua_porcelain", "same_name")
    dt_ms = (time.perf_counter() - t0) * 1000.0
    assert dt_ms < 25.0
    assert sr_scoped.gates_summary["g4_intra_panel_collisions"] == 0

    sr_unique = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "east_qinghua_porcelain", "unique")
    assert sr_unique.gates_summary["unique_hues_used"] >= sr_scoped.gates_summary["unique_hues_used"]

    out_pdf, aud1 = export_recolored_pdf(sc, sr_scoped.group_hex, sr_scoped.scale_stops)
    assert aud1["g6_geometry_identical"] is True
    assert aud1["g3b_inverted_cell_labels"] >= 4
    assert aud1["modified_colorbar_rasters"] == 1

    r_code = generate_r_ggplot_snippet("east_qinghua_porcelain", sc.entities, sr_scoped.entity_hex, sc.continuous_scales, sr_scoped.scale_stops)
    py_code = generate_python_mpl_snippet("east_qinghua_porcelain", sc.entities, sr_scoped.entity_hex, sc.continuous_scales, sr_scoped.scale_stops)
    csv_rep = generate_change_report_csv(sc.entities, sr_scoped.entity_hex)
    cert = build_verification_certificate(
        sc.filename, "east_qinghua_porcelain", "same_name", sc.entities, sr_scoped.entity_hex, sc.continuous_scales, sr_scoped.scale_stops, sc.evidence_regions, sr_scoped.gates_summary, aud1
    )
    assert "scale_fill_danqing" in r_code
    assert "LinearSegmentedColormap" in py_code
    assert "element,panels,original_hex,new_hex,role" in csv_rep
    assert cert["integrity_gates"]["G6_canonical_geometry_invariance"]["status"] == "PASS"


def test_visium_mist_slate_compound_path_mutability() -> None:
    p = BENCH_DIR / "04_MouseBrain_Visium_Complex_10xGenomics.pdf"
    sc = parse_pdf_scene(p.read_bytes(), p.name, "visium_qc")
    hexes = {cg.original_hex.upper() for cg in sc.color_groups.values()}
    assert "#C9D6DF" in hexes, "Visium Panel D In Tissue (#C9D6DF) compound path must be mutable!"


def test_g0_wetlab_evidence_shield_and_diverging_scale() -> None:
    p = BENCH_DIR / "02_Histology_WB_EvidenceShield_10xVisium.pdf"
    sc = parse_pdf_scene(p.read_bytes(), p.name, "g0_demo")
    subtypes = {ev.subtype_label for ev in sc.evidence_regions}
    assert "western_blot_or_gel" in subtypes
    assert "histology_or_specimen_photo" in subtypes
    assert "fluorescence_microscopy" in subtypes
    assert "colorbar_strip" in subtypes

    cs = next(iter(sc.continuous_scales.values()))
    assert cs.kind == "continuous_diverging"

    sr = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "east_blue_green_landscape")
    out_pdf, aud = export_recolored_pdf(sc, sr.group_hex, sr.scale_stops)
    assert aud["g0_evidence_bit_identical"] is True
    assert len(aud["g0_locked_objects"]) == 3
    assert aud["g6_geometry_identical"] is True


def test_pdf_cs_scn_form_xobject_and_multipage_isolation() -> None:
    pdf = pikepdf.Pdf.new()
    # Page 0: untouched reference page
    p0 = pdf.add_blank_page(page_size=(300, 200))
    p0.Contents = pdf.make_stream(b"0.8 0.1 0.1 rg 20 20 60 60 re f")

    # Page 1: uses ICCBased `/CS1 cs ... scn`, Indexed `/CS2 cs ... scn`, and nested `/Form` XObject!
    p1 = pdf.add_blank_page(page_size=(400, 300))
    icc_stream = pdf.make_stream(zlib.compress(b"\x00" * 128))
    icc_stream["/N"] = 3
    icc_stream["/Alternate"] = pikepdf.Name("/DeviceRGB")
    lut_bytes = bytes([220, 60, 50, 40, 140, 200])
    cs_dict = pikepdf.Dictionary(
        {
            "/CS1": pikepdf.Array([pikepdf.Name("/ICCBased"), icc_stream]),
            "/CS2": pikepdf.Array([pikepdf.Name("/Indexed"), pikepdf.Name("/DeviceRGB"), 1, pikepdf.String(lut_bytes)]),
        }
    )
    nested_form = pdf.make_stream(b"q /CS1 cs 0.15 0.65 0.35 scn 40 80 50 90 re f Q")
    nested_form["/Type"] = pikepdf.Name("/XObject")
    nested_form["/Subtype"] = pikepdf.Name("/Form")
    nested_form["/BBox"] = pikepdf.Array([0, 0, 400, 300])
    nested_form["/Resources"] = pikepdf.Dictionary({"/ColorSpace": cs_dict})

    p1.Resources = pikepdf.Dictionary(
        {
            "/ColorSpace": cs_dict,
            "/XObject": pikepdf.Dictionary({"/Fm1": nested_form}),
        }
    )
    p1.Contents = pdf.make_stream(
        b"q /CS1 cs 0.85 0.25 0.20 scn 120 80 50 90 re f "
        b"/CS2 cs 1 scn 200 80 50 90 re f "
        b"/Fm1 Do Q"
    )
    buf = io.BytesIO()
    pdf.save(buf)
    raw_pdf = buf.getvalue()

    info = inspect_pdf_document(raw_pdf, render_thumbnails=True)
    assert info["page_count"] == 2
    assert info["pages"][1]["thumbnail"].startswith("data:image/jpeg;base64,")

    sc = parse_pdf_scene(raw_pdf, "multipage_cs_form.pdf", "mp1", page_index=1)
    assert len(sc.entities) == 3
    sr = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "okabe_ito")
    out_pdf, aud = export_recolored_pdf(sc, sr.group_hex, sr.scale_stops)
    assert aud["g6_geometry_identical"] is True
    assert aud["modified_vector_ops"] == 3

    with pikepdf.open(io.BytesIO(out_pdf)) as check_pdf:
        assert check_pdf.pages[0].Contents.read_bytes() == b"0.8 0.1 0.1 rg 20 20 60 60 re f"


def test_svg_css_classes_use_inheritance_currentcolor_and_legend() -> None:
    svg_markup = """<?xml version="1.0" encoding="UTF-8"?>
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 500 320">
      <defs>
        <style>
          .bar-wt { fill: #E64B35; }
          .bar-ko { fill: rgb(77, 187, 213); }
        </style>
        <circle id="pt" cx="0" cy="0" r="5"/>
      </defs>
      <rect x="0" y="0" width="500" height="320" fill="#FFFFFF"/>
      <rect class="bar-wt" x="60" y="100" width="50" height="140"/>
      <rect class="bar-ko" x="140" y="70" width="50" height="170"/>
      <g fill="#00A087">
        <use xlink:href="#pt" x="240" y="120"/>
        <use xlink:href="#pt" x="255" y="150"/>
        <use xlink:href="#pt" x="378" y="114"/>
      </g>
      <g color="#3C5488" stroke="currentColor" fill="none">
        <path d="M 60 60 L 260 50" stroke-width="3"/>
        <line x1="372" y1="140" x2="386" y2="140" stroke-width="3"/>
      </g>
      <!-- Legend -->
      <rect class="bar-wt" x="372" y="58" width="12" height="12"/>
      <text x="392" y="68" font-size="12">WT</text>
      <rect class="bar-ko" x="372" y="82" width="12" height="12"/>
      <text x="392" y="92" font-size="12">KO</text>
      <text x="392" y="118" font-size="12">Rescue</text>
      <text x="392" y="144" font-size="12">Trend</text>
    </svg>""".encode("utf-8")

    sc = parse_svg_scene(svg_markup, "css_use_legend.svg", "svg_p0")
    labels = {e.label for e in sc.entities.values()}
    assert {"WT", "KO", "Rescue", "Trend"}.issubset(labels)
    assert len(sc.id_map_png) > 300

    sr = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "east_ru_celadon")
    out_svg, aud = export_recolored_svg(sc, sr.group_hex, sr.scale_stops)
    assert aud["g6_geometry_identical"] is True
    assert aud["modified_vector_ops"] >= 7


def test_svg_gradient_enrichment_and_g6() -> None:
    p = BENCH_DIR / "03_EGFR_MAPK_Pathway_Lemmon2010.svg"
    sc = parse_svg_scene(p.read_bytes(), p.name, "svg_demo")
    assert len(sc.continuous_scales) == 2
    assert len(sc.evidence_regions) == 1
    assert len(sc.id_map_png) > 300

    sr = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "east_cloisonne_enamel")
    out_svg, aud = export_recolored_svg(sc, sr.group_hex, sr.scale_stops)
    assert aud["g6_geometry_identical"] is True
    assert aud["modified_colorbar_rasters"] == 2
    assert b'data-danqing-interp="1"' in out_svg


def test_overlaying_boxplot_scatter_pdf_and_svg_parity_and_pick_holes() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from PIL import Image

    x_left_a = [((i % 7) - 3) * 0.025 for i in range(40)]
    y_left_a = [21.0 + (i % 10) * 0.85 for i in range(40)]
    x_left_b = [1.0 + ((i % 5) - 2) * 0.03 for i in range(12)]
    y_left_b = [25.5 + (i % 6) * 0.9 for i in range(12)]

    y_box_orange = [30.8 + (i % 6) * 0.55 for i in range(12)]
    y_box_blue = [28.4 + (i % 10) * 0.48 for i in range(40)]
    x_ov_orange = [1.0 + ((i % 5) - 2) * 0.035 for i in range(12)]
    x_ov_blue = [2.0 + ((i % 7) - 3) * 0.03 for i in range(40)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 4.4))
    fig.suptitle("Cohort Marker Classification and Abundance", color="#555555")
    ax1.set_title("Marker classification", color="#666666")
    ax2.set_title("Protein abundance", color="#666666")

    ax1.scatter(x_left_a, y_left_a, s=28, c="#1f77b4", alpha=0.45, edgecolors="#333333", linewidths=0.6)
    ax1.scatter(x_left_b, y_left_b, s=28, c="#e69f00", alpha=0.55, edgecolors="#333333", linewidths=0.6)
    ax1.axhline(24.0, linestyle="--", color="#666666", linewidth=0.9)

    bp = ax2.boxplot([y_box_orange, y_box_blue], patch_artist=True, widths=0.46)
    for med in bp["medians"]:
        med.set_color("#444444")
    for w_ln in bp["whiskers"] + bp["caps"]:
        w_ln.set_color("#555555")
    bp["boxes"][0].set(facecolor="#e69f00", alpha=0.32, edgecolor="#666666")
    bp["boxes"][1].set(facecolor="#1f77b4", alpha=0.52, edgecolor="#444444")
    ax2.scatter(x_ov_orange, y_box_orange, s=26, c="#e69f00", alpha=0.55, edgecolors="#333333", linewidths=0.5, zorder=3)
    ax2.scatter(x_ov_blue, y_box_blue, s=26, c="#1f77b4", alpha=0.45, edgecolors="#333333", linewidths=0.5, zorder=3)

    handles = [
        Line2D([0], [0], marker="o", linestyle="None", markersize=6, markerfacecolor="#e69f00", markeredgecolor="#333333", label="Hypoxic rule (12)"),
        Line2D([0], [0], marker="o", linestyle="None", markersize=6, markerfacecolor="#1f77b4", markeredgecolor="#333333", label="Remaining cohort (40)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False)

    pdf_buf = io.BytesIO()
    svg_buf = io.BytesIO()
    fig.savefig(pdf_buf, format="pdf")
    fig.savefig(svg_buf, format="svg")
    plt.close(fig)

    sc_pdf = parse_pdf_scene(pdf_buf.getvalue(), "overlay_test.pdf")
    sc_svg = parse_svg_scene(svg_buf.getvalue(), "overlay_test.svg")

    for sc in (sc_pdf, sc_svg):
        assert len(sc.panels) == 2
        assert {e.label for e in sc.entities.values()} == {"Hypoxic rule", "Remaining cohort"}
        by_lbl = {e.label: e for e in sc.entities.values()}
        rem_gids = by_lbl["Remaining cohort"].member_group_ids
        hyp_gids = by_lbl["Hypoxic rule"].member_group_ids
        assert sum(sc.color_groups[g].primitive_count for g in rem_gids) == 40 + 1 + 40 + 1
        assert sum(sc.color_groups[g].primitive_count for g in hyp_gids) == 12 + 1 + 12 + 1
        # Panel B must separate the underlying boxplot (`area`) and overlaid scatter points (`point`)
        pb_rem_kinds = {sc.color_groups[g].mark_kind for g in rem_gids if sc.color_groups[g].panel_id == "Panel B"}
        assert pb_rem_kinds == {"area", "point"}

    # Verify pick map has BOTH area and point cat_indices and zero black outline holes inside the boxplot
    idm = np.asarray(Image.open(io.BytesIO(sc_pdf.id_map_png)).convert("RGB"), dtype=np.int32)
    cat_order = [gid for gid, cg in sc_pdf.color_groups.items() if not cg.is_continuous_member]
    gid_to_cat = {gid: idx for idx, gid in enumerate(cat_order)}
    rem_ent = next(e for e in sc_pdf.entities.values() if e.label == "Remaining cohort")
    pb_area_gid = next(g for g in rem_ent.member_group_ids if sc_pdf.color_groups[g].panel_id == "Panel B" and sc_pdf.color_groups[g].mark_kind == "area")
    pb_pt_gid = next(g for g in rem_ent.member_group_ids if sc_pdf.color_groups[g].panel_id == "Panel B" and sc_pdf.color_groups[g].mark_kind == "point")
    cat_grid = np.where((idm[..., 0] >= 1) & (idm[..., 0] <= 240), (idm[..., 0] - 1) + idm[..., 1] * 240, -1)
    assert int((cat_grid == gid_to_cat[pb_area_gid]).sum()) > 400
    assert int((cat_grid == gid_to_cat[pb_pt_gid]).sum()) > 120

    # Verify lossless recoloring of ALL individual points + boxplots
    sr_pdf = solve_scene_colors(sc_pdf.entities, sc_pdf.continuous_scales, sc_pdf.evidence_regions, "east_ru_celadon")
    out_pdf, aud_pdf = export_recolored_pdf(sc_pdf, sr_pdf.group_hex, sr_pdf.scale_stops)
    assert aud_pdf["g6_geometry_identical"] is True
    assert aud_pdf["modified_vector_ops"] >= 6

    sr_svg = solve_scene_colors(sc_svg.entities, sc_svg.continuous_scales, sc_svg.evidence_regions, "east_ru_celadon")
    out_svg, aud_svg = export_recolored_svg(sc_svg, sr_svg.group_hex, sr_svg.scale_stops)
    assert aud_svg["g6_geometry_identical"] is True
    assert aud_svg["modified_vector_ops"] >= 100


def test_r_pdf_zapfdingbats_scatter_points() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(320, 240))
    dingbats_font = pikepdf.Dictionary(
        {
            "/Type": pikepdf.Name("/Font"),
            "/Subtype": pikepdf.Name("/Type1"),
            "/BaseFont": pikepdf.Name("/ZapfDingbats"),
        }
    )
    helv_font = pikepdf.Dictionary(
        {
            "/Type": pikepdf.Name("/Font"),
            "/Subtype": pikepdf.Name("/Type1"),
            "/BaseFont": pikepdf.Name("/Helvetica"),
        }
    )
    page.Resources = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary({"/F1": dingbats_font, "/F2": helv_font}),
        }
    )
    # Bar + 4 overlaid ZapfDingbats `(l)` scatter circles + legend circle & Helvetica label
    stream = (
        b"q 0.20 0.50 0.80 rg 60 40 50 110 re f Q "
        b"q BT /F1 7.5 Tf 0.20 0.50 0.80 rg "
        b"1 0 0 1 75 90 Tm (l) Tj "
        b"1 0 0 1 85 115 Tm (l) Tj "
        b"1 0 0 1 95 140 Tm (l) Tj "
        b"1 0 0 1 80 165 Tm (l) Tj "
        b"1 0 0 1 220 190 Tm (l) Tj ET Q "
        b"q BT /F2 10 Tf 0 0 0 rg 1 0 0 1 232 187 Tm (Treated) Tj ET Q"
    )
    page.Contents = pdf.make_stream(stream)
    buf = io.BytesIO()
    pdf.save(buf)

    sc = parse_pdf_scene(buf.getvalue(), "r_dingbats.pdf")
    assert len(sc.entities) == 1
    ent = next(iter(sc.entities.values()))
    assert ent.label == "Treated"
    assert len(ent.member_group_ids) == 2
    assert {sc.color_groups[g].mark_kind for g in ent.member_group_ids} == {"area", "point"}
    assert sum(sc.color_groups[g].primitive_count for g in ent.member_group_ids) == 6

    sr = solve_scene_colors(sc.entities, sc.continuous_scales, sc.evidence_regions, "okabe_ito")
    _, aud = export_recolored_pdf(sc, sr.group_hex, sr.scale_stops)
    assert aud["g6_geometry_identical"] is True
    assert aud["modified_vector_ops"] == 2
