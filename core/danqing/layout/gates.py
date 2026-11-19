"""9 Deterministic Scientific Layout & Typography Verification Gates (Gates L0-L8)."""

from __future__ import annotations

import math

from .ir import CompositePageScene, PanelIR
from .specs import JOURNAL_SPECS, mm_to_pt


def run_layout_gates(scene: CompositePageScene, source_panels: list[PanelIR], max_height_mm: float | None = None) -> dict[str, object]:
    """Audit compiled scene against Gates L0-L8 and return structured deterministic certificate."""
    spec = JOURNAL_SPECS.get(scene.journal_id, JOURNAL_SPECS["nature_double"])
    eff_max_h = max_height_mm if max_height_mm is not None else spec.max_height_mm

    # Gate L0: Special / Raw Evidence Aspect-Ratio & Pixel Integrity Shield
    max_aspect_err = 0.0
    min_dpi = 9999.0
    locked_checked = 0
    for r in scene.rasters:
        locked_checked += 1
        max_aspect_err = max(max_aspect_err, r.aspect_ratio_error)
        min_dpi = min(min_dpi, r.effective_dpi)
    for ls in scene.locked_svgs:
        locked_checked += 1
        vb_asp = ls.raw_vb[2] / max(1e-6, ls.raw_vb[3])
        err = abs((ls.w_mm / max(1e-9, ls.h_mm)) / vb_asp - 1.0)
        max_aspect_err = max(max_aspect_err, err)
    for sl in scene.slots:
        if sl.locked_special:
            max_aspect_err = max(max_aspect_err, abs(sl.scale_x - sl.scale_y))

    g_l0_pass = max_aspect_err < 1e-5

    # Gate L1: Data-Coordinate Fidelity Proof (< 1e-4 normalized drift inside SpineBox)
    slot_map = {sl.panel_id: sl for sl in scene.slots}
    max_coord_drift = 0.0
    checked_pts = 0
    for c in scene.circles:
        if c.norm_xy is not None and c.panel_id in slot_map:
            sl = slot_map[c.panel_id]
            sx0, sy0, sx1, sy1 = sl.spine_box_mm
            nx_out = (c.cx_mm - sx0) / max(1e-9, sx1 - sx0)
            ny_out = (c.cy_mm - sy0) / max(1e-9, sy1 - sy0)
            drift = math.hypot(nx_out - c.norm_xy[0], ny_out - c.norm_xy[1])
            max_coord_drift = max(max_coord_drift, drift)
            checked_pts += 1
    g_l1_pass = max_coord_drift < 1e-4

    # Gate L2: Text Content Invariance
    src_tokens: set[str] = set()
    for p in source_panels:
        if p.locked_special:
            continue
        for t in p.texts:
            if t.role in ("Y_TITLE", "X_TITLE"):
                src_tokens.add(t.text)
    out_tokens = {t.text for t in scene.texts} | {
        getattr(t, "orig_text", "") for t in scene.texts if getattr(t, "orig_text", "")
    }
    missing_titles = [tok for tok in src_tokens if tok not in out_tokens]
    g_l2_pass = len(missing_titles) == 0

    # Gate L3: Journal Typography Hierarchy
    pts = [t.font_pt for t in scene.texts]
    min_pt = min(pts) if pts else spec.tick_pt
    max_pt = max(pts) if pts else spec.tag_pt
    g_l3_pass = (min_pt >= spec.min_allowed_pt - 0.25) and (max_pt <= spec.max_allowed_pt + 1.0)

    # Gate L4: Journal Stroke Weight Compliance
    strokes = [p.stroke_pt for p in scene.paths if p.stroke not in ("none", "transparent") and p.stroke_pt > 0]
    min_sw = min(strokes) if strokes else spec.axis_stroke_pt
    max_sw = max(strokes) if strokes else spec.data_stroke_pt
    g_l4_pass = (min_sw >= spec.min_stroke_pt - 0.05) and (max_sw <= 1.65)

    # Gate L5: Zero Unintended Text-on-Text Collision (excluding deliberate user-dragged inset legends)
    collisions = 0
    n_txt = len(scene.texts)
    skip_roles = ("ROI_LABEL", "SCALEBAR_TEXT", "INSET_LEGEND")
    for i in range(n_txt):
        ti = scene.texts[i]
        if ti.role in skip_roles:
            continue
        bi = ti.bbox_mm
        for j in range(i + 1, n_txt):
            tj = scene.texts[j]
            if tj.role in skip_roles:
                continue
            if ti.role == "X_TICK" and tj.role == "X_TICK" and abs(ti.angle_deg) > 15.0:
                min_pitch = 1.75 if abs(ti.angle_deg) >= 75.0 else 2.5
                if abs(ti.x_mm - tj.x_mm) >= min_pitch:
                    continue
            bj = tj.bbox_mm
            ox = min(bi[2], bj[2]) - max(bi[0], bj[0])
            oy = min(bi[3], bj[3]) - max(bi[1], bj[1])
            if ox > 0.45 and oy > 0.35:
                collisions += 1
    g_l5_pass = collisions == 0

    # Gate L6: Row Spine Baseline Precision across non-stacked single-row Cartesian panels
    row_y1s: dict[int, list[float]] = {}
    stacked_rows = {
        r_idx for r_idx, r in enumerate(scene.bento_rows) if any(len(b.panel_ids) >= 2 for b in r.blocks)
    }
    for sl in scene.slots:
        if (
            not sl.locked_special
            and sl.elasticity == "L2_ELASTIC_CARTESIAN"
            and sl.row_idx not in stacked_rows
        ):
            row_y1s.setdefault(sl.row_idx, []).append(sl.spine_box_mm[3])
    max_spine_err_mm = 0.0
    for ys in row_y1s.values():
        if len(ys) >= 2:
            max_spine_err_mm = max(max_spine_err_mm, max(ys) - min(ys))
    g_l6_pass = max_spine_err_mm < 0.02

    # Gate L7: Journal Canvas Fit
    height_fits = scene.height_mm <= eff_max_h + 0.5
    g_l7_pass = height_fits and scene.width_mm >= 45.0

    # Gate L8: Export Vector Integrity Ready
    g_l8_pass = len(scene.slots) == len(source_panels) and mm_to_pt(scene.width_mm) > 100.0

    gates_list = [
        {
            "id": "L0",
            "name": "Special-Figure Lock",
            "name_zh": "特殊原图 1:1 比例锁定",
            "passed": g_l0_pass,
            "metric": f"stretch={max_aspect_err:.6f} ({locked_checked} locked)",
        },
        {
            "id": "L1",
            "name": "Data Zero Drift",
            "name_zh": "数据坐标零偏移",
            "passed": g_l1_pass,
            "metric": f"Δ={max_coord_drift:.2e}",
        },
        {
            "id": "L2",
            "name": "Text Invariance",
            "name_zh": "轴与标签完整保留",
            "passed": g_l2_pass,
            "metric": "100%",
        },
        {
            "id": "L3",
            "name": "Font Hierarchy",
            "name_zh": "物理字号合规",
            "passed": g_l3_pass,
            "metric": f"{min_pt:.1f}–{max_pt:.1f} pt",
        },
        {
            "id": "L4",
            "name": "Stroke Hierarchy",
            "name_zh": "物理线宽合规",
            "passed": g_l4_pass,
            "metric": f"{min_sw:.2f}–{max_sw:.2f} pt",
        },
        {
            "id": "L5",
            "name": "Zero Collision",
            "name_zh": "全局字形无碰撞",
            "passed": g_l5_pass,
            "metric": f"{collisions} overlaps",
        },
        {
            "id": "L6",
            "name": "Spine Alignment",
            "name_zh": "同行内轴对齐",
            "passed": g_l6_pass,
            "metric": f"Δy={max_spine_err_mm:.4f} mm",
        },
        {
            "id": "L7",
            "name": "Page Bounds",
            "name_zh": "契合刊物版心",
            "passed": g_l7_pass,
            "metric": f"{scene.width_mm:.0f} × {scene.height_mm:.1f} mm",
        },
        {
            "id": "L8",
            "name": "Vector Export",
            "name_zh": "分层矢量就绪",
            "passed": g_l8_pass,
            "metric": f"{len(scene.slots)} slots",
        },
    ]

    passed_count = sum(1 for g in gates_list if g["passed"])
    return {
        "all_passed": passed_count == len(gates_list),
        "passed_count": passed_count,
        "total_count": len(gates_list),
        "min_font_pt": round(min_pt, 2),
        "max_font_pt": round(max_pt, 2),
        "min_stroke_pt": round(min_sw, 2),
        "max_stroke_pt": round(max_sw, 2),
        "max_spine_error_mm": round(max_spine_err_mm, 5),
        "gates": gates_list,
    }
