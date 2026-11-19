"""End-to-end tests for Danqing Layout Studio v2 & seamless handoff to Figure Recoloring."""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pikepdf
import pytest

from danqing.layout.compiler import TypographyConfig, compile_modular_scene
from danqing.layout.exporter import render_scene_pdf, render_scene_svg
from danqing.layout.gates import run_layout_gates
from danqing.layout.ir import BentoBlock, BentoRow, PanelStyleOverride, ROIOverlaySpec
from danqing.layout.parser import parse_svg_panel, parse_uploaded_file
from danqing.layout.specs import JOURNAL_SPECS
from danqing.svg_engine import parse_svg_scene
from web.backend.app import app

REPO_ROOT = Path(__file__).resolve().parents[1]
PANELS_DIR = REPO_ROOT / "bench" / "layout_panels"
CORPUS_DIR = REPO_ROOT / "bench" / "corpus"


def _load_panels():
    manifest = json.loads((PANELS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    out = []
    for m in manifest:
        roi = ROIOverlaySpec(**m["default_roi"]) if m.get("default_roi") else None
        out.append(
            parse_svg_panel(
                (PANELS_DIR / m["filename"]).read_bytes(),
                panel_id=m["panel_id"],
                title_hint=m["title"],
                category_badge=m["category"],
                source_citation=m["source"],
                force_locked_special=m["locked_special"],
                default_roi=roi,
            )
        )
    return out


@pytest.mark.parametrize("count", [9, 10, 11, 12])
@pytest.mark.parametrize(
    "mode",
    ["auto_bento", "hero_bento", "uniform_3col", "compact_4col", "asymmetric_bands"],
)
def test_layout_9_to_12_panels_all_gates(count: int, mode: str) -> None:
    panels = _load_panels()[:count]
    scene = compile_modular_scene(panels, TypographyConfig(journal_id="nature_double", layout_mode=mode))
    audit = run_layout_gates(scene, panels)
    assert audit["all_passed"], f"Failed gates for count={count}, mode={mode}: {audit['gates']}"


@pytest.mark.parametrize(
    "journal_id,panel_count",
    [
        ("science_1col", 3),
        ("nature_1col", 4),
        ("cell_1col", 4),
        ("cell_mid", 6),
        ("nature_mid", 6),
        ("science_2col", 6),
        ("nejm_mid", 6),
        ("lancet_full", 9),
        ("hep_full", 9),
        ("onco_full", 9),
        ("pnas_full", 9),
    ],
)
def test_v2_expanded_journal_column_tiers(journal_id: str, panel_count: int) -> None:
    assert len(JOURNAL_SPECS) >= 25
    panels = _load_panels()[:panel_count]
    cfg = TypographyConfig(journal_id=journal_id, layout_mode="auto_bento")
    scene = compile_modular_scene(panels, cfg)
    assert abs(scene.width_mm - JOURNAL_SPECS[journal_id].width_mm) < 1e-3
    audit = run_layout_gates(scene, panels)
    assert audit["all_passed"], f"Failed gates for {journal_id}: {audit['gates']}"


def test_v2_panel_e_inset_draggable_legend_and_negative_margin_trim() -> None:
    all_panels = _load_panels()
    panels = {p.panel_id: p for p in all_panels}
    sub = [panels["P04"], panels["P05"], panels["P06"]]
    fixed_spans = {"P04": 4, "P05": 4, "P06": 4}

    # Docked right legend consumes outer right margin -> narrower PCA plot
    sc_right = compile_modular_scene(
        sub,
        TypographyConfig(journal_id="nature_double", hoist_shared_legends=False),
        span_overrides=fixed_spans,
        panel_overrides={"P05": PanelStyleOverride(legend_pos="right")},
    )
    # Custom dragged / inset legend releases outer right margin -> expands PCA SpineBox width!
    sc_inset = compile_modular_scene(
        sub,
        TypographyConfig(journal_id="nature_double", hoist_shared_legends=False),
        span_overrides=fixed_spans,
        panel_overrides={"P05": PanelStyleOverride(legend_pos="custom", legend_xy_norm=(0.56, 0.08), legend_scale=0.9)},
    )
    sl_r = next(s for s in sc_right.slots if s.panel_id == "P05")
    sl_i = next(s for s in sc_inset.slots if s.panel_id == "P05")
    w_r = sl_r.spine_box_mm[2] - sl_r.spine_box_mm[0]
    w_i = sl_i.spine_box_mm[2] - sl_i.spine_box_mm[0]
    assert w_i > w_r + 8.0
    assert sl_i.legend_box_mm is not None

    # Default 10-panel composition exposes selectable legend_box_mm on ALL 4 legend/colorbar panels (P05, P07, P09, P10)
    sc10 = compile_modular_scene(all_panels[:10], TypographyConfig(journal_id="nature_double"))
    leg_ids = {s.panel_id for s in sc10.slots if s.legend_box_mm is not None}
    assert {"P05", "P07", "P09", "P10"}.issubset(leg_ids)

    # Negative pad_top_mm and pad_bottom_mm on P05 inside a multi-panel row genuinely expand P05's SpineBox height!
    sc10_trim = compile_modular_scene(
        all_panels[:10],
        TypographyConfig(journal_id="nature_double"),
        panel_overrides={"P05": PanelStyleOverride(pad_top_mm=-2.0, pad_bottom_mm=-4.5)},
    )
    sl_def = next(s for s in sc10.slots if s.panel_id == "P05")
    sl_trm = next(s for s in sc10_trim.slots if s.panel_id == "P05")
    assert sl_trm.spine_box_mm[1] < sl_def.spine_box_mm[1] - 1.5
    assert sl_trm.spine_box_mm[3] > sl_def.spine_box_mm[3] + 3.5


def test_v2_panel_g_lossless_categorical_gap_compression() -> None:
    panels = {p.panel_id: p for p in _load_panels()}
    p07 = panels["P07"]
    assert p07.is_categorical_x is True

    sc_orig = compile_modular_scene([p07], TypographyConfig(journal_id="nature_1col"))
    sc_tight = compile_modular_scene(
        [p07],
        TypographyConfig(journal_id="nature_1col"),
        panel_overrides={"P07": PanelStyleOverride(category_spacing=0.50, frame_width_ratio=0.78)},
    )

    sl_o = sc_orig.slots[0].spine_box_mm
    sl_t = sc_tight.slots[0].spine_box_mm
    mk_o = [c for c in sc_orig.circles if c.clip_id is not None]
    mk_t = [c for c in sc_tight.circles if c.clip_id is not None]
    assert len(mk_o) == len(mk_t) == 303

    # Every single scatter point's normalized Y coordinate is bit-exact (< 1e-6)
    for m_o, m_t in zip(mk_o, mk_t):
        yn_o = (m_o.cy_mm - sl_o[1]) / (sl_o[3] - sl_o[1])
        yn_t = (m_t.cy_mm - sl_t[1]) / (sl_t[3] - sl_t[1])
        assert abs(yn_o - yn_t) < 1e-6

    # Horizontal span between outer category ticks narrows by > 30%
    xs_o = sorted(t.x_mm for t in sc_orig.texts if t.role == "X_TICK")
    xs_t = sorted(t.x_mm for t in sc_tight.texts if t.role == "X_TICK")
    assert (xs_t[-1] - xs_t[0]) < 0.68 * (xs_o[-1] - xs_o[0])


def test_v2_vertical_substacks_col_major_and_author_custom_tags() -> None:
    panels = {p.panel_id: p for p in _load_panels()}
    sub = [panels[k] for k in ["P01", "P02", "P08", "P05", "P06", "P07"]]
    rows = [
        BentoRow(
            blocks=[
                BentoBlock(panel_ids=["P01"], weight=5.0),
                BentoBlock(panel_ids=["P02", "P08"], weight=3.5),
                BentoBlock(panel_ids=["P05"], weight=3.5),
            ],
            height_scale=1.15,
        ),
        BentoRow(
            blocks=[
                BentoBlock(panel_ids=["P06"], weight=6.0),
                BentoBlock(panel_ids=["P07"], weight=6.0),
            ],
            height_scale=1.0,
        ),
    ]
    povs = {
        "P02": PanelStyleOverride(custom_tag=""),  # Hidden tag on inset zoom panel!
        "P05": PanelStyleOverride(custom_tag="S1"),
    }
    scene = compile_modular_scene(
        sub,
        TypographyConfig(journal_id="cell_double", tag_flow="col_major"),
        panel_overrides=povs,
        bento_rows=rows,
    )
    tag_by_id = {s.panel_id: s.tag_label for s in scene.slots}
    assert tag_by_id["P01"] == "A"
    assert tag_by_id["P06"] == "B"
    assert tag_by_id["P02"] == ""
    assert tag_by_id["P08"] == "C"
    assert tag_by_id["P07"] == "D"
    assert tag_by_id["P05"] == "S1"
    audit = run_layout_gates(scene, sub)
    assert audit["all_passed"], f"Gates failed on vertical stack: {audit['gates']}"


def test_v2_user_uploaded_vector_pdfs_and_css_svgs_decompile_and_pass_gates() -> None:
    files_to_test = [
        ("c02_mouse_brain_visium.pdf", True),
        ("c05_mpl_grouped_bar.pdf", False),
        ("c07_mpl_boxplot_arms.pdf", False),
        ("c12_mpl_volcano_deg.pdf", False),
        ("c17_mpl_kaplan_meier.pdf", False),
        ("c21_svglite_css_dodged_bar.svg", False),
    ]
    uploaded_irs = []
    for idx, (fname, expected_locked) in enumerate(files_to_test, 1):
        raw = (CORPUS_DIR / fname).read_bytes()
        ir = parse_uploaded_file(fname, raw, panel_id=f"UP{idx:02d}")
        assert ir.locked_special is expected_locked, f"Unexpected lock state for {fname}"
        if not expected_locked:
            assert (len(ir.shapes) + len(ir.markers)) >= 6
        uploaded_irs.append(ir)

    scene = compile_modular_scene(
        uploaded_irs[:5],
        TypographyConfig(journal_id="nature_double", show_panel_titles=False),
    )
    assert scene.shared_legend_hoisted is False
    audit = run_layout_gates(scene, uploaded_irs[:5])
    assert audit["all_passed"], f"Uploaded PDF composition failed gates: {audit['gates']}"


def test_layout_to_danqing_figure_handoff_preserves_panels_and_evidence() -> None:
    from danqing.layout.ir import TextItemOverride

    panels = _load_panels()[:10]
    scene = compile_modular_scene(
        panels,
        TypographyConfig(journal_id="nature_double", layout_mode="auto_bento"),
        panel_overrides={
            "P06": PanelStyleOverride(text_overrides={"XT:3": TextItemOverride(color="#B91C1C", bold=True)}),
            "P09": PanelStyleOverride(legend_pos="bottom", legend_orient="horizontal"),
        },
    )
    svg_str = render_scene_svg(scene, show_guides=False)
    dq = parse_svg_scene(svg_str.encode("utf-8"), "danqing_layout_nature_double_10panels.svg", "handoff_fig")
    assert [p.panel_id for p in dq.panels] == [f"Panel {chr(ord('a') + k)}" for k in range(10)]
    assert len(dq.evidence_regions) == 4
    # Horizontal Z-score colorbar AND its DotPlot bubbles are linked as a single continuous scale in Figure Recoloring!
    assert len(dq.continuous_scales) == 1
    cs = next(iter(dq.continuous_scales.values()))
    assert cs.title == "Z-score"
    assert len(cs.member_group_ids) >= 4

    pdf_bytes = render_scene_pdf(scene)
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    assert len(pdf.pages) == 1


def test_layout_fastapi_v2_routes() -> None:
    client = TestClient(app)
    r_init = client.get("/api/v2/layout/init")
    assert r_init.status_code == 200
    data = r_init.json()
    assert len(data["panels"]) == 12
    assert len(data["journals"]) >= 25
    assert len(data["journal_families"]) == 9

    # Upload a real vector PDF via multipart /api/v2/layout/upload
    pdf_bytes = (CORPUS_DIR / "c07_mpl_boxplot_arms.pdf").read_bytes()
    r_up = client.post(
        "/api/v2/layout/upload",
        files=[("files", ("c07_mpl_boxplot_arms.pdf", pdf_bytes, "application/pdf"))],
    )
    assert r_up.status_code == 200
    up_item = r_up.json()["uploaded"][0]
    assert up_item["locked_special"] is False
    assert up_item["is_categorical_x"] is True

    pids = data["packs"][0]["panel_ids"][:5] + [up_item["panel_id"]]
    r_comp = client.post(
        "/api/v2/layout/compose",
        json={
            "panel_ids": pids,
            "journal_id": "custom_canvas",
            "custom_width_mm": 168.0,
            "custom_max_height_mm": 230.0,
            "tag_flow": "row_major",
            "panel_overrides": {
                up_item["panel_id"]: {"category_spacing": 0.60, "font_scale": 1.05},
            },
        },
    )
    assert r_comp.status_code == 200
    comp = r_comp.json()
    assert comp["page_width_mm"] == 168.0
    assert comp["audit"]["all_passed"] is True
    assert comp["naive_svg"] == ""
    assert len(comp["bento_rows"]) >= 2

    r_naive = client.post(
        "/api/v2/layout/compose",
        json={"panel_ids": pids, "include_naive": True},
    )
    assert r_naive.status_code == 200
    assert "<svg" in r_naive.json()["naive_svg"]


def test_v2_legend_svg_sublayer_and_outer_escape_roundtrip() -> None:
    all_panels = _load_panels()[:10]
    sc_default = compile_modular_scene(all_panels, TypographyConfig(journal_id="nature_double"))
    svg_str = render_scene_svg(sc_default, show_guides=False)
    for pid in ("P05", "P07", "P09", "P10"):
        assert f'id="legend-layer-{pid}"' in svg_str

    # Round-trip: move P07 legend inside -> then escape back outside to `right` and `top`!
    sc_in = compile_modular_scene(
        all_panels,
        TypographyConfig(journal_id="nature_double"),
        panel_overrides={"P07": PanelStyleOverride(legend_pos="inside_tr")},
    )
    sl_in = next(s for s in sc_in.slots if s.panel_id == "P07")
    assert sl_in.effective_legend_pos == "inside_tr"
    assert sl_in.legend_box_mm is not None and sl_in.legend_box_mm[2] <= sl_in.spine_box_mm[2]

    sc_out_right = compile_modular_scene(
        all_panels,
        TypographyConfig(journal_id="nature_double"),
        panel_overrides={"P07": PanelStyleOverride(legend_pos="right")},
    )
    sl_out = next(s for s in sc_out_right.slots if s.panel_id == "P07")
    assert sl_out.effective_legend_pos == "right"
    assert sl_out.legend_box_mm is not None and sl_out.legend_box_mm[0] > sl_out.spine_box_mm[2]

    sc_out_top = compile_modular_scene(
        all_panels,
        TypographyConfig(journal_id="nature_double"),
        panel_overrides={"P07": PanelStyleOverride(legend_pos="top")},
    )
    sl_top = next(s for s in sc_out_top.slots if s.panel_id == "P07")
    assert sl_top.effective_legend_pos == "top"
    assert sl_top.legend_box_mm is not None and sl_top.legend_box_mm[3] <= sl_top.spine_box_mm[1]


def test_v2_inset_legend_zorder_font_color_and_match_swatch() -> None:
    panels = {p.panel_id: p for p in _load_panels()}
    sub = [panels["P05"], panels["P07"]]

    # 1. Verify inset legend text is inside <g id="legend-layer-..."> AFTER LEGEND_BG (never washed out white!)
    sc_inset = compile_modular_scene(
        sub,
        TypographyConfig(journal_id="nature_double"),
        panel_overrides={
            "P05": PanelStyleOverride(
                legend_pos="inside_tr",
                panel_font_family="Times New Roman",
                legend_font_family="Calibri",
                legend_bold=True,
                legend_text_color="#B91C1C",
            ),
            "P07": PanelStyleOverride(
                legend_pos="inside_tr",
                legend_bg=False,
                legend_match_swatch=True,
            ),
        },
    )
    svg_str = render_scene_svg(sc_inset, show_guides=False)

    g_p05_start = svg_str.index('id="legend-layer-P05"')
    g_p05_end = svg_str.index("</g>", g_p05_start)
    g_p05_xml = svg_str[g_p05_start:g_p05_end]
    bg_pos = g_p05_xml.index('fill="#FFFFFF"')
    txt_pos = g_p05_xml.index(">Benign</text>")
    assert bg_pos < txt_pos, "LEGEND_BG must render behind inset legend text!"
    assert 'fill="#B91C1C"' in g_p05_xml
    assert 'font-weight="bold"' in g_p05_xml
    assert "Calibri" in g_p05_xml
    assert "Times New Roman" in svg_str

    # 2. Verify P07 transparent background (`legend_bg=False`) & swatch-matched distinct label colors
    g_p07_start = svg_str.index('id="legend-layer-P07"')
    g_p07_end = svg_str.index("</g>", g_p07_start)
    g_p07_xml = svg_str[g_p07_start:g_p07_end]
    assert 'fill="#FFFFFF"' not in g_p07_xml
    p07_leg_txts = [t for t in sc_inset.texts if t.panel_id == "P07" and t.role == "INSET_LEGEND"]
    assert len({t.fill for t in p07_leg_txts}) >= 3


def test_v2_horizontal_colorbar_top_bottom_inside_and_pdf_export() -> None:
    all_panels = _load_panels()[:10]

    for pos in ("bottom", "top", "inside_tr", "right"):
        ov = PanelStyleOverride(
            legend_pos=pos,  # type: ignore[arg-type]
            legend_orient="horizontal",
            legend_bold=True,
            legend_text_color="#1D4ED8",
        )
        sc = compile_modular_scene(
            all_panels,
            TypographyConfig(journal_id="nature_double"),
            panel_overrides={"P09": ov},
        )
        sl_p09 = next(s for s in sc.slots if s.panel_id == "P09")
        assert sl_p09.is_colorbar is True
        assert sl_p09.effective_legend_orient == "horizontal"
        assert sl_p09.legend_box_mm is not None
        # Horizontal colorbar bounding box is wider than it is tall!
        lb = sl_p09.legend_box_mm
        assert (lb[2] - lb[0]) > (lb[3] - lb[1]) * 1.4

        svg_str = render_scene_svg(sc, show_guides=False)
        assert 'id="grad-h-P09" x1="0%" y1="0%" x2="100%" y2="0%"' in svg_str

        if pos in ("bottom", "top", "right"):
            audit = run_layout_gates(sc, all_panels)
            assert audit["all_passed"], f"Horizontal colorbar at pos={pos} failed gates: {audit['gates']}"

        pdf_bytes = render_scene_pdf(sc)
        pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        assert len(pdf.pages) == 1


@pytest.mark.parametrize("n_panels", [16, 20])
def test_v2_beyond_12_panels_dense_atlas_support(n_panels: int) -> None:
    from dataclasses import replace

    base = _load_panels()
    expanded = []
    for idx in range(n_panels):
        src = base[idx % len(base)]
        roi = replace(src.default_roi, linked_source_id=None)
        expanded.append(replace(src, panel_id=f"M{idx + 1:02d}", default_roi=roi))

    for mode in ("auto_bento", "compact_4col"):
        sc = compile_modular_scene(
            expanded,
            TypographyConfig(journal_id="nature_double", layout_mode=mode, tick_pt=5.6, title_pt=6.4, axis_title_pt=6.0),
        )
        assert len(sc.slots) == n_panels
        assert any(len(r.blocks) >= 5 for r in sc.bento_rows)
        audit = run_layout_gates(sc, expanded)
        assert audit["all_passed"], f"{n_panels}-panel {mode} failed gates: {audit['gates']}"


def test_v2_individual_single_legend_item_and_single_axis_tick_overrides() -> None:
    from danqing.layout.ir import TextItemOverride

    panels = {p.panel_id: p for p in _load_panels()}
    sub = [panels["P06"], panels["P07"], panels["P08"], panels["P09"]]

    sc = compile_modular_scene(
        sub,
        TypographyConfig(journal_id="nature_double"),
        panel_overrides={
            # Turn ONLY X-tick #3 ('Cirrhosis') red + bold; keep Donor/Hepatitis/Fibrosis black normal!
            "P06": PanelStyleOverride(
                text_overrides={
                    "XT:3": TextItemOverride(color="#B91C1C", bold=True, font_scale=1.10),
                    "XT:0": TextItemOverride(color="#64748B"),
                }
            ),
            # Turn ONLY Legend item #2 ('Severe CAD') crimson + Times New Roman + bold; keep No CAD / Mild-Mod CAD black Arial!
            "P07": PanelStyleOverride(
                legend_pos="inside_tr",
                text_overrides={
                    "LEG:2": TextItemOverride(
                        color="#B91C1C",
                        font_family="Times New Roman",
                        bold=True,
                        font_scale=1.12,
                    ),
                },
            ),
            # Italicize + highlight a single Volcano gene callout!
            "P08": PanelStyleOverride(
                text_overrides={
                    "ANN:0": TextItemOverride(
                        color="#B91C1C",
                        font_family="Times New Roman",
                        bold=True,
                        italic=True,
                    ),
                }
            ),
            # Highlight a single Y-axis biomarker on DotPlot!
            "P09": PanelStyleOverride(
                legend_pos="bottom",
                text_overrides={
                    "YT:5": TextItemOverride(color="#1D4ED8", bold=True),
                },
            ),
        },
    )

    p06_xts = {t.item_key: t for t in sc.texts if t.panel_id == "P06" and t.role == "X_TICK"}
    assert p06_xts["XT:3"].text == "Cirrhosis"
    assert p06_xts["XT:3"].fill == "#B91C1C" and p06_xts["XT:3"].bold is True
    assert p06_xts["XT:0"].fill == "#64748B" and p06_xts["XT:0"].bold is False
    assert p06_xts["XT:1"].fill == "#000000" and p06_xts["XT:1"].bold is False

    p07_legs = {t.item_key: t for t in sc.texts if t.panel_id == "P07" and t.item_key.startswith("LEG:")}
    assert p07_legs["LEG:0"].fill == "#000000" and p07_legs["LEG:0"].font_family == "Arial"
    assert p07_legs["LEG:1"].fill == "#000000" and p07_legs["LEG:1"].bold is False
    assert p07_legs["LEG:2"].fill == "#B91C1C"
    assert p07_legs["LEG:2"].font_family == "Times New Roman"
    assert p07_legs["LEG:2"].bold is True

    svg_str = render_scene_svg(sc, show_guides=False)
    assert 'font-style="italic"' in svg_str
    assert 'data-item-key="XT:3"' in svg_str
    assert 'data-item-key="LEG:2"' in svg_str

    pdf_bytes = render_scene_pdf(sc)
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    assert len(pdf.pages) == 1

    audit = run_layout_gates(sc, sub)
    assert audit["all_passed"], f"Single-item override failed gates: {audit['gates']}"

    # Verify FastAPI /api/v2/layout/compose round-trips text_overrides & returns slot.text_items
    client = TestClient(app)
    r = client.post(
        "/api/v2/layout/compose",
        json={
            "panel_ids": ["P06", "P07"],
            "panel_overrides": {
                "P06": {"text_overrides": {"XT:3": {"color": "#B91C1C", "bold": True}}},
                "P07": {"text_overrides": {"LEG:2": {"color": "SWATCH", "bold": True}}},
            },
        },
    )
    assert r.status_code == 200
    slots_out = {s["panel_id"]: s for s in r.json()["slots"]}
    xt3_meta = next(ti for ti in slots_out["P06"]["text_items"] if ti["item_key"] == "XT:3")
    assert xt3_meta["fill"] == "#B91C1C" and xt3_meta["bold"] is True
    leg2_meta = next(ti for ti in slots_out["P07"]["text_items"] if ti["item_key"] == "LEG:2")
    assert leg2_meta["fill"] != "#000000" and leg2_meta["bold"] is True


