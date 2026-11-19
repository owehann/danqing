"""2D Modular Bento Spine Grid, Vertical Sub-Stacks, Multi-Tier Journal Adaptation & Row-Band Solver."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math

from .ir import BentoBlock, BentoRow, CompiledPanelSlot, LegendPosMode, PanelIR, PanelStyleOverride
from .specs import JournalSpec, measure_text_mm, pt_to_mm

LAYOUT_MODES: list[dict[str, str]] = [
    {
        "id": "auto_bento",
        "name": "Optimal Modular Bento",
        "name_zh": "智能最优模块网格",
        "desc": "Allocates spans and row heights by information density and locked ratios.",
    },
    {
        "id": "hero_bento",
        "name": "Two-Row Hero Anchor",
        "name_zh": "左上主视觉跨双行",
        "desc": "Leads with a focal anchor paired with vertical sub-stacks on the right.",
    },
    {
        "id": "uniform_3col",
        "name": "Three-Column Spine Matrix",
        "name_zh": "三栏严谨内轴矩阵",
        "desc": "Canonical 3-column grid maximizing vertical Y-axis spine continuity.",
    },
    {
        "id": "compact_4col",
        "name": "Multi-Column Dense Atlas",
        "name_zh": "高密度多栏紧凑图谱",
        "desc": "Packs 9–24+ panels cleanly onto one page (4–6 cols) while preserving >=5.5 pt type.",
    },
    {
        "id": "asymmetric_bands",
        "name": "Asymmetric Narrative Bands",
        "name_zh": "非对称叙事行带",
        "desc": "Alternates wide trajectory slots with compact comparison slots.",
    },
]


@dataclass
class PanelMarginsMM:
    left_mm: float
    right_mm: float
    top_mm: float
    bottom_mm: float
    bottom_horiz_mm: float = 2.0
    min_horiz_spine_w_mm: float = 0.0
    min_spine_w_mm: float = 16.0
    min_spine_h_mm: float = 18.0
    effective_legend_pos: LegendPosMode = "right"


def resolve_effective_legend_pos(
    panel: PanelIR,
    ov: PanelStyleOverride,
    suppress_legend: bool,
) -> tuple[LegendPosMode, tuple[float, float]]:
    """Determine effective legend/colorbar placement & default normalized (x,y) inside SpineBox if inset."""
    has_any_leg = bool(panel.legend_entries) or (panel.colorbar is not None)
    if not has_any_leg or panel.locked_special:
        return ("hidden", ov.legend_xy_norm)
    if ov.legend_pos != "auto":
        if ov.legend_pos == "inside_tr":
            return ("inside_tr", (0.60, 0.05))
        if ov.legend_pos == "inside_tl":
            return ("inside_tl", (0.04, 0.05))
        if ov.legend_pos == "inside_br":
            return ("inside_br", (0.60, 0.68))
        if ov.legend_pos == "inside_bl":
            return ("inside_bl", (0.04, 0.68))
        return (ov.legend_pos, ov.legend_xy_norm)

    if suppress_legend and panel.colorbar is None:
        return ("hidden", ov.legend_xy_norm)

    # Smart auto-inset for isotropic scatter plots (e.g. Panel E PCA!) when a corner of SpineBox is empty!
    if panel.colorbar is None and panel.elasticity == "L1_ISOTROPIC_VECTOR" and len(panel.legend_entries) <= 4 and panel.markers:
        rx0, ry0, rx1, ry1 = panel.spine_box
        rw, rh = max(1e-6, rx1 - rx0), max(1e-6, ry1 - ry0)
        corners = [
            ("inside_tr", 0.58, 1.0, 0.0, 0.30, (0.60, 0.05)),
            ("inside_br", 0.58, 1.0, 0.70, 1.0, (0.60, 0.72)),
            ("inside_tl", 0.0, 0.42, 0.0, 0.30, (0.04, 0.05)),
        ]
        for cname, xlo, xhi, ylo, yhi, xy_def in corners:
            hits = sum(
                1
                for m in panel.markers
                if xlo <= (m.cx - rx0) / rw <= xhi and ylo <= (m.cy - ry0) / rh <= yhi
            )
            if hits <= max(1, int(0.008 * len(panel.markers))):
                return (cname, xy_def)  # type: ignore[return-value]

    return ("right", ov.legend_xy_norm)


def estimate_panel_margins_mm(
    panel: PanelIR,
    spec: JournalSpec,
    font_family: str,
    title_pt: float,
    axis_title_pt: float,
    tick_pt: float,
    show_panel_titles: bool = True,
    suppress_legend: bool = False,
    ov: PanelStyleOverride | None = None,
) -> PanelMarginsMM:
    """Compute baseline physical millimeter margins around `SpineBox` (per-panel pad trims apply at slot materialization)."""
    ov = ov or PanelStyleOverride()
    f_sc = ov.font_scale
    lg_sc = ov.legend_scale
    eff_title_pt = title_pt * f_sc
    eff_axis_pt = axis_title_pt * f_sc
    eff_tick_pt = tick_pt * f_sc
    eff_show_title = ov.show_title if ov.show_title is not None else show_panel_titles
    p_font = ov.panel_font_family or font_family
    lg_font = ov.legend_font_family or p_font

    eff_leg_pos, _ = resolve_effective_legend_pos(panel, ov, suppress_legend)
    if eff_leg_pos == "top":
        if panel.colorbar is not None:
            top_leg_extra = 2.0 * lg_sc + pt_to_mm(eff_tick_pt * lg_sc * 1.15) + 1.9
        else:
            top_leg_extra = pt_to_mm(eff_tick_pt * lg_sc * 1.45) + 1.4
    else:
        top_leg_extra = 0.0
    top_mm = ((pt_to_mm(eff_title_pt) + 2.6) if eff_show_title else 1.6) + top_leg_extra

    if panel.locked_special:
        return PanelMarginsMM(
            left_mm=1.4,
            right_mm=1.4,
            top_mm=max(1.0, top_mm),
            bottom_mm=1.8,
            bottom_horiz_mm=1.8,
            min_horiz_spine_w_mm=0.0,
            min_spine_w_mm=18.0,
            min_spine_h_mm=16.0,
            effective_legend_pos="hidden",
        )

    y_ticks_sorted = sorted([t for t in panel.texts if t.role == "Y_TICK"], key=lambda t: t.y_raw)
    x_ticks_sorted = sorted([t for t in panel.texts if t.role == "X_TICK"], key=lambda t: t.x_raw)
    has_y_title = any(t.role == "Y_TITLE" for t in panel.texts)
    has_x_title = any(t.role == "X_TITLE" for t in panel.texts)

    def _yt_w(idx_y: int, s: str) -> float:
        tov = ov.text_overrides.get(f"YT:{idx_y}")
        use_s = tov.text.strip() if (tov and tov.text and tov.text.strip()) else s
        use_pt = eff_tick_pt * (tov.font_scale if tov else 1.0)
        use_f = (tov.font_family if tov and tov.font_family else p_font)
        use_b = bool(tov.bold) if (tov and tov.bold is not None) else False
        return measure_text_mm(use_s, use_pt, bold=use_b, font_family=use_f)[0]

    def _xt_w(idx_x: int, s: str) -> float:
        tov = ov.text_overrides.get(f"XT:{idx_x}")
        use_s = tov.text.strip() if (tov and tov.text and tov.text.strip()) else s
        use_pt = eff_tick_pt * (tov.font_scale if tov else 1.0)
        use_f = (tov.font_family if tov and tov.font_family else p_font)
        use_b = bool(tov.bold) if (tov and tov.bold is not None) else False
        return measure_text_mm(use_s, use_pt, bold=use_b, font_family=use_f)[0]

    max_yt_w = max((_yt_w(i, t.text) for i, t in enumerate(y_ticks_sorted)), default=4.0)
    y_title_h = (measure_text_mm("Ag", eff_axis_pt, bold=True, font_family=p_font)[1] + 2.1) if has_y_title else 0.0
    left_mm = max(2.0, 1.7 + max_yt_w + y_title_h + 1.1)

    xt_widths = [_xt_w(i, t.text) for i, t in enumerate(x_ticks_sorted)]
    max_xt_w = max(xt_widths, default=4.0)
    xt_cap_h = measure_text_mm("Ag", eff_tick_pt, font_family=p_font)[1]
    x_title_h = (measure_text_mm("Ag", eff_axis_pt, bold=True, font_family=p_font)[1] + 2.1) if has_x_title else 0.0
    if eff_leg_pos == "bottom":
        if panel.colorbar is not None:
            bot_leg_extra = 2.0 * lg_sc + pt_to_mm(eff_tick_pt * lg_sc * 1.15) + 2.1
        else:
            bot_leg_extra = pt_to_mm(eff_tick_pt * lg_sc * 1.45) + 1.8
    else:
        bot_leg_extra = 0.0

    bottom_horiz_mm = max(2.0, 1.3 + xt_cap_h + 1.9 + x_title_h) + bot_leg_extra
    if panel.is_categorical_x and max_xt_w > 7.2:
        xt_block_h = max_xt_w * math.sin(math.radians(38.0)) + xt_cap_h * math.cos(math.radians(38.0)) + 1.7
        bottom_mm = max(2.0, 1.3 + xt_block_h + x_title_h) + bot_leg_extra
        min_horiz_w = (sum(xt_widths) + 1.6 * max(1, len(xt_widths))) * 1.12
    else:
        bottom_mm = bottom_horiz_mm
        min_horiz_w = 0.0

    if panel.colorbar is not None and eff_leg_pos == "right":
        if ov.legend_orient == "horizontal":
            right_mm = max(14.5 * lg_sc, 15.5) + 1.8
        else:
            max_cb_t = max(
                (measure_text_mm(txt, eff_tick_pt * 0.94 * lg_sc, font_family=lg_font)[0] for _, txt in panel.colorbar.ticks),
                default=5.0,
            )
            right_mm = 7.2 * lg_sc + max_cb_t + 1.8
    elif eff_leg_pos == "right" and panel.legend_entries:
        def _lg_w(idx_l: int, s: str) -> float:
            tov = ov.text_overrides.get(f"LEG:{idx_l}")
            use_s = tov.text.strip() if (tov and tov.text and tov.text.strip()) else s
            use_pt = eff_tick_pt * 0.94 * lg_sc * (tov.font_scale if tov else 1.0)
            use_f = (tov.font_family if tov and tov.font_family else lg_font)
            use_b = bool(tov.bold) if (tov and tov.bold is not None) else ov.legend_bold
            return measure_text_mm(use_s, use_pt, bold=use_b, font_family=use_f)[0]

        max_lg_w = max(
            (_lg_w(i, le.label) for i, le in enumerate(panel.legend_entries)),
            default=8.0,
        )
        eff_cols = len(panel.legend_entries) if ov.legend_orient == "horizontal" else max(1, min(len(panel.legend_entries), ov.legend_cols))
        right_mm = eff_cols * (3.6 * lg_sc + max_lg_w) + 2.0
    else:
        # Legend / Colorbar is inset (`inside_*` / `custom`) or horizontal (`top` / `bottom`) or `hidden` -> release right margin!
        right_mm = 1.6

    min_spine_h = max(18.0, panel.n_y_categories * (xt_cap_h + 1.1))
    min_spine_w = max(16.0, panel.n_x_categories * 3.8 * min(1.0, ov.category_spacing))

    return PanelMarginsMM(
        left_mm=left_mm,
        right_mm=right_mm,
        top_mm=max(1.2, top_mm),
        bottom_mm=bottom_mm,
        bottom_horiz_mm=bottom_horiz_mm,
        min_horiz_spine_w_mm=min_horiz_w,
        min_spine_w_mm=min_spine_w,
        min_spine_h_mm=min_spine_h,
        effective_legend_pos=eff_leg_pos,
    )


def _tag_for_index(idx: int, tag_case: str) -> str:
    ch = chr(ord("a") + (idx % 26))
    suffix = "" if idx < 26 else str(idx // 26 + 1)
    lbl = ch + suffix
    return lbl.upper() if tag_case == "upper" else lbl


def _max_cols_for_width(width_mm: float, n_panels: int = 10) -> int:
    if width_mm < 72.0:
        return 1
    if width_mm <= 102.0:
        return 2
    if width_mm <= 148.0:
        return 3
    if n_panels >= 21 and width_mm >= 170.0:
        return 6
    if n_panels >= 13 and width_mm >= 162.0:
        return 5
    return 4


def _valid_12col_splits(k: int, overrides: list[int | None]) -> list[tuple[int, ...]]:
    if k == 1:
        return [(12,)]
    domain = range(2, 9) if k >= 3 else range(3, 10)
    out: list[tuple[int, ...]] = []
    for comb in itertools.product(domain, repeat=k):
        if sum(comb) != 12:
            continue
        if all(ov is None or ov == c for ov, c in zip(overrides, comb)):
            out.append(comb)
    if not out:
        raw = [ov if ov is not None else max(2, 12 // k) for ov in overrides]
        sc = 12.0 / sum(raw)
        norm = [max(2, int(round(v * sc))) for v in raw]
        norm[-1] += 12 - sum(norm)
        if norm[-1] < 2:
            norm[0] -= 2 - norm[-1]
            norm[-1] = 2
        out.append(tuple(norm))
    return out


def _score_row_allocation(
    panels: list[PanelIR],
    margins: list[PanelMarginsMM],
    spans: tuple[int, ...],
    usable_w_mm: float,
    col_gutter_mm: float,
) -> tuple[float, float]:
    k = len(panels)
    avail_total = usable_w_mm - col_gutter_mm * (k - 1)
    outer_ws = [avail_total * (sp / 12.0) for sp in spans]
    spine_ws = [max(9.0, ow - m.left_mm - m.right_mm) for ow, m in zip(outer_ws, margins)]

    h_floor = max(m.min_spine_h_mm for m in margins)
    h_lo = max(20.0, h_floor)
    h_hi = max(h_lo + 4.0, 54.0)

    best_cost = 1e18
    best_h = 30.0
    for step in range(25):
        h = h_lo + (h_hi - h_lo) * (step / 24.0)
        c_sum = 0.0
        for p, m, sw in zip(panels, margins, spine_ws):
            if sw < m.min_spine_w_mm:
                c_sum += 18.0 * ((m.min_spine_w_mm - sw) / m.min_spine_w_mm) ** 2
            asp = sw / h
            weight = 4.2 if (p.locked_special or p.elasticity == "L1_ISOTROPIC_VECTOR") else 1.15
            c_sum += weight * ((asp - p.ideal_aspect) / max(0.25, p.ideal_aspect)) ** 2
            if not p.locked_special:
                if asp < p.min_aspect:
                    c_sum += 6.0 * ((p.min_aspect - asp) / p.min_aspect) ** 2
                elif asp > p.max_aspect:
                    c_sum += 6.0 * ((asp - p.max_aspect) / p.max_aspect) ** 2
        c_sum += 0.14 * ((h - 30.0) / 30.0) ** 2
        if c_sum < best_cost:
            best_cost = c_sum
            best_h = h

    acc = 0
    for sp in spans[:-1]:
        acc += sp
        if acc not in (3, 4, 6, 8, 9):
            best_cost += 0.08
    return best_cost, best_h


def build_preset_bento_rows(
    panels: list[PanelIR],
    margins: list[PanelMarginsMM],
    spec: JournalSpec,
    layout_mode: str = "auto_bento",
    gutter_mm: float = 3.2,
    span_overrides: dict[str, int] | None = None,
) -> list[BentoRow]:
    """Generate clean 2D `BentoRow` topology from a preset strategy, respecting single/mid/double column widths."""
    n = len(panels)
    if n == 0:
        return []
    span_overrides = span_overrides or {}
    usable_w = spec.width_mm - 7.0
    max_cols = _max_cols_for_width(spec.width_mm, n)

    # Single-column narrow journals (e.g. Science 55mm): 1 panel per row
    if max_cols == 1:
        return [BentoRow(blocks=[BentoBlock(panel_ids=[p.panel_id], weight=12.0)]) for p in panels]

    # Hero 2-Row Anchor (using native Vertical Sub-Stacks on the right!)
    if layout_mode == "hero_bento" and n >= 5 and max_cols >= 3:
        hero_w = float(span_overrides.get(panels[0].panel_id) or 5)
        hero_w = max(4.0, min(6.0, hero_w))
        rem_w = 12.0 - hero_w
        b_hero = BentoBlock(panel_ids=[panels[0].panel_id], weight=hero_w)
        b_col1 = BentoBlock(panel_ids=[panels[1].panel_id, panels[3].panel_id], weight=rem_w * 0.5)
        b_col2 = BentoBlock(panel_ids=[panels[2].panel_id, panels[4].panel_id], weight=rem_w * 0.5)
        top_row = BentoRow(blocks=[b_hero, b_col1, b_col2], height_scale=1.0)
        if n == 5:
            return [top_row]
        tail_rows = build_preset_bento_rows(
            panels[5:], margins[5:], spec, layout_mode="auto_bento", gutter_mm=gutter_mm, span_overrides=span_overrides
        )
        return [top_row] + tail_rows

    if layout_mode in ("uniform_3col", "compact_4col", "asymmetric_bands"):
        desired = 3 if layout_mode in ("uniform_3col", "asymmetric_bands") else max(4, max_cols)
        per_row = min(max_cols, desired)
        counts: list[int] = []
        if per_row == 2:
            counts = [2] * (n // 2) + ([1] if n % 2 else [])
        elif per_row == 3:
            if n <= 3:
                counts = [n]
            elif n % 3 == 0:
                counts = [3] * (n // 3)
            elif n % 3 == 1:
                counts = [3] * (n // 3 - 1) + [min(max_cols, 4)] if max_cols >= 4 else [3] * (n // 3 - 1) + [2, 2]
            else:
                counts = [3] * (n // 3) + [2]
        else:
            if n <= per_row:
                counts = [n]
            elif n % per_row == 0:
                counts = [per_row] * (n // per_row)
            elif n % per_row == 1:
                a = (per_row + 1) // 2 + (1 if (per_row + 1) % 2 else 0)
                b = (per_row + 1) - a
                counts = [per_row] * (n // per_row - 1) + [a, b]
            else:
                counts = [per_row] * (n // per_row) + [n % per_row]

        out_rows: list[BentoRow] = []
        cur = 0
        for r_i, cnt in enumerate(counts):
            idxs = list(range(cur, cur + cnt))
            cur += cnt
            if layout_mode == "asymmetric_bands" and cnt == 3:
                ws = (5.0, 4.0, 3.0) if r_i % 2 == 0 else (3.0, 5.0, 4.0)
            elif layout_mode == "compact_4col" and cnt >= 4:
                reqs = [
                    margins[idx].left_mm + margins[idx].right_mm + max(11.0, 0.72 * margins[idx].min_spine_w_mm)
                    for idx in idxs
                ]
                r_sum = sum(reqs) or float(cnt)
                ws = tuple(0.45 * (12.0 / cnt) + 0.55 * (12.0 * rq / r_sum) for rq in reqs)
            else:
                ws = tuple(12.0 / cnt for _ in range(cnt))
            blocks = [
                BentoBlock(
                    panel_ids=[panels[idx].panel_id],
                    weight=float(span_overrides.get(panels[idx].panel_id) or w),
                )
                for idx, w in zip(idxs, ws)
            ]
            out_rows.append(BentoRow(blocks=blocks, height_scale=1.0))
        return out_rows

    # `auto_bento`: DP optimal row breaks respecting `max_cols`
    dp_cost = [1e18] * (n + 1)
    dp_prev: list[tuple[int, tuple[int, ...]] | None] = [None] * (n + 1)
    dp_cost[0] = 0.0

    min_k = 1 if (n <= 3 or max_cols <= 2) else 2
    allowed_k = tuple(range(min_k, max_cols + 1))

    for i in range(n):
        if dp_cost[i] >= 1e17:
            continue
        for k in allowed_k:
            j = i + k
            if j > n:
                continue
            idxs = list(range(i, j))
            ovs = [span_overrides.get(panels[idx].panel_id) for idx in idxs]
            splits = _valid_12col_splits(k, ovs)
            best_rc = 1e18
            best_sp = splits[0]
            for sp in splits:
                rc, _ = _score_row_allocation(
                    [panels[idx] for idx in idxs], [margins[idx] for idx in idxs], sp, usable_w, gutter_mm
                )
                if rc < best_rc:
                    best_rc = rc
                    best_sp = sp
            cand = dp_cost[i] + best_rc + 0.52
            if cand < dp_cost[j]:
                dp_cost[j] = cand
                dp_prev[j] = (i, best_sp)

    cur = n
    rev: list[BentoRow] = []
    while cur > 0 and dp_prev[cur] is not None:
        prev_i, sp = dp_prev[cur]  # type: ignore[misc]
        blocks = [
            BentoBlock(panel_ids=[panels[idx].panel_id], weight=float(w))
            for idx, w in zip(range(prev_i, cur), sp)
        ]
        rev.append(BentoRow(blocks=blocks, height_scale=1.0))
        cur = prev_i
    return list(reversed(rev))


def solve_bento_layout(
    panels: list[PanelIR],
    margins: list[PanelMarginsMM],
    spec: JournalSpec,
    layout_mode: str = "auto_bento",
    gutter_mm: float = 3.2,
    span_overrides: dict[str, int] | None = None,
    shared_legend_height_mm: float = 0.0,
    bento_rows: list[BentoRow] | None = None,
    panel_overrides: dict[str, PanelStyleOverride] | None = None,
    tag_flow: str = "row_major",
) -> tuple[list[CompiledPanelSlot], list[BentoRow], list[tuple[float, float]], float, str | None]:
    """Materialize exact millimeter coordinates for any 2D `BentoRow` topology (including vertical sub-stacks & custom weights)."""
    if not panels:
        return [], [], [], 40.0, None
    panel_overrides = panel_overrides or {}
    span_overrides = span_overrides or {}
    p_map = {p.panel_id: p for p in panels}
    m_map = {p.panel_id: m for p, m in zip(panels, margins)}

    # Sanitize or build `bento_rows` so its panel set matches `panels`
    active_set = {p.panel_id for p in panels}
    clean_rows: list[BentoRow] = []
    seen_pids: set[str] = set()
    if bento_rows:
        for r in bento_rows:
            c_blocks: list[BentoBlock] = []
            for b in r.blocks:
                valid_ids = [pid for pid in b.panel_ids if pid in active_set and pid not in seen_pids]
                if valid_ids:
                    seen_pids.update(valid_ids)
                    ov_w = span_overrides.get(valid_ids[0]) if len(valid_ids) == 1 else None
                    c_blocks.append(BentoBlock(panel_ids=valid_ids, weight=float(ov_w or max(1.2, b.weight))))
            if c_blocks:
                clean_rows.append(BentoRow(blocks=c_blocks, height_scale=max(0.55, min(1.85, r.height_scale))))
        missing = [p.panel_id for p in panels if p.panel_id not in seen_pids]
        if missing:
            max_c = _max_cols_for_width(spec.width_mm, len(panels))
            for idx in range(0, len(missing), max_c):
                chunk = missing[idx : idx + max_c]
                clean_rows.append(
                    BentoRow(blocks=[BentoBlock(panel_ids=[pid], weight=12.0 / len(chunk)) for pid in chunk])
                )

    if not clean_rows:
        clean_rows = build_preset_bento_rows(
            panels, margins, spec, layout_mode=layout_mode, gutter_mm=gutter_mm, span_overrides=span_overrides
        )

    pad_x = 3.5
    pad_top = 3.5 + shared_legend_height_mm
    pad_bot = 3.2
    usable_w = max(36.0, spec.width_mm - 2.0 * pad_x)

    # First compute natural base height of every row
    row_base_spine_hs: list[float] = []
    row_natural_totals: list[float] = []
    for r in clean_rows:
        nb = len(r.blocks)
        w_sum = sum(max(0.5, b.weight) for b in r.blocks)
        avail_rw = usable_w - gutter_mm * max(0, nb - 1)

        # Single-panel blocks drive the row's base spine height; stacked blocks require sum of sub-panel heights
        single_ps: list[PanelIR] = []
        single_ms: list[PanelMarginsMM] = []
        single_sp: list[int] = []
        min_block_total_h = 22.0
        for b in r.blocks:
            bw_mm = avail_rw * (max(0.5, b.weight) / w_sum)
            if len(b.panel_ids) == 1:
                pid = b.panel_ids[0]
                single_ps.append(p_map[pid])
                single_ms.append(m_map[pid])
                single_sp.append(max(2, int(round(12.0 * b.weight / w_sum))))
            else:
                stack_req = gutter_mm * (len(b.panel_ids) - 1)
                for pid in b.panel_ids:
                    mp = m_map[pid]
                    pp = p_map[pid]
                    sw_est = max(10.0, bw_mm - mp.left_mm - mp.right_mm)
                    sh_est = max(18.5, mp.min_spine_h_mm, min(32.0, sw_est / max(0.5, pp.ideal_aspect)))
                    stack_req += mp.top_mm + sh_est + mp.bottom_mm
                min_block_total_h = max(min_block_total_h, stack_req)

        if single_ps:
            _, opt_sh = _score_row_allocation(single_ps, single_ms, tuple(single_sp), usable_w, gutter_mm)
            r_top = max(
                max(0.8, m.top_mm + panel_overrides.get(p_it.panel_id, PanelStyleOverride()).pad_top_mm)
                for p_it, m in zip(single_ps, single_ms)
            )
            r_bot = 2.0
            for b_it in r.blocks:
                if len(b_it.panel_ids) != 1:
                    continue
                pid_it = b_it.panel_ids[0]
                m_it = m_map[pid_it]
                bw_it = avail_rw * (max(0.5, b_it.weight) / w_sum)
                sw_it = bw_it - m_it.left_mm - m_it.right_mm
                use_bm = m_it.bottom_horiz_mm if sw_it >= m_it.min_horiz_spine_w_mm else m_it.bottom_mm
                r_bot = max(r_bot, max(0.8, use_bm + panel_overrides.get(pid_it, PanelStyleOverride()).pad_bottom_mm))
            sh_use = max(opt_sh, min_block_total_h - r_top - r_bot)
            tot_h = (r_top + sh_use + r_bot) * r.height_scale
            sh_scaled = max(16.0, tot_h - r_top - r_bot)
            row_base_spine_hs.append(sh_scaled)
            row_natural_totals.append(r_top + sh_scaled + r_bot)
        else:
            tot_h = min_block_total_h * r.height_scale
            row_base_spine_hs.append(tot_h)
            row_natural_totals.append(tot_h)

    # Gentle proportional height compression if all height_scales == 1.0 and page slightly exceeds max_height_mm
    all_default_h = all(abs(r.height_scale - 1.0) < 1e-3 for r in clean_rows)
    est_page_h = pad_top + pad_bot + sum(row_natural_totals) + gutter_mm * max(0, len(clean_rows) - 1)
    if all_default_h and est_page_h > spec.max_height_mm - 1.5 and spec.width_mm >= 140.0:
        excess = est_page_h - (spec.max_height_mm - 1.5)
        n_total_p = len(panels)
        base_floor = 13.8 if n_total_p >= 17 else (15.5 if n_total_p >= 13 else 18.5)
        cat_scale = 0.72 if n_total_p >= 13 else 0.88
        floors: list[float] = []
        for r in clean_rows:
            fl_r = base_floor
            for b in r.blocks:
                if len(b.panel_ids) == 1:
                    fl_r = max(fl_r, m_map[b.panel_ids[0]].min_spine_h_mm * cat_scale)
                else:
                    fl_r = max(fl_r, 20.0 * len(b.panel_ids))
            floors.append(fl_r)
        slack = sum(max(0.0, sh - fl) for sh, fl in zip(row_base_spine_hs, floors))
        if slack > 0.5:
            ratio = min(1.0, excess / slack)
            for idx_r in range(len(clean_rows)):
                sh_new = row_base_spine_hs[idx_r] - ratio * max(0.0, row_base_spine_hs[idx_r] - floors[idx_r])
                diff = row_base_spine_hs[idx_r] - sh_new
                row_base_spine_hs[idx_r] = sh_new
                row_natural_totals[idx_r] -= diff

    # Vertical Column-Rail Left-Margin Synchronization (when blocks start at identical quantized 12-col coordinate)
    rail_lefts: dict[int, list[float]] = {}
    for r in clean_rows:
        w_sum = sum(max(0.5, b.weight) for b in r.blocks)
        c_acc = 0.0
        for b in r.blocks:
            q_col = int(round(c_acc * 12.0 / w_sum))
            for pid in b.panel_ids:
                if not p_map[pid].locked_special:
                    rail_lefts.setdefault(q_col, []).append(m_map[pid].left_mm)
            c_acc += max(0.5, b.weight)

    synced_lm: dict[int, float] = {
        q_c: max(vals) for q_c, vals in rail_lefts.items() if len(vals) >= 2 and (max(vals) - min(vals)) <= 10.5
    }

    # Materialize slots
    raw_slots: list[CompiledPanelSlot] = []
    row_bounds_mm: list[tuple[float, float]] = []
    cur_y = pad_top

    for r_idx, (r, base_sh, row_tot_h) in enumerate(zip(clean_rows, row_base_spine_hs, row_natural_totals)):
        nb = len(r.blocks)
        w_sum = sum(max(0.5, b.weight) for b in r.blocks)
        avail_rw = usable_w - gutter_mm * max(0, nb - 1)

        single_pids = [b.panel_ids[0] for b in r.blocks if len(b.panel_ids) == 1]
        r_top = max(
            (max(0.8, m_map[pid].top_mm + panel_overrides.get(pid, PanelStyleOverride()).pad_top_mm) for pid in single_pids),
            default=2.0,
        )
        r_bot = 2.0
        for b_it in r.blocks:
            if len(b_it.panel_ids) != 1:
                continue
            pid_it = b_it.panel_ids[0]
            m_it = m_map[pid_it]
            bw_it = avail_rw * (max(0.5, b_it.weight) / w_sum)
            sw_it = bw_it - m_it.left_mm - m_it.right_mm
            use_bm = m_it.bottom_horiz_mm if sw_it >= m_it.min_horiz_spine_w_mm else m_it.bottom_mm
            r_bot = max(r_bot, max(0.8, use_bm + panel_overrides.get(pid_it, PanelStyleOverride()).pad_bottom_mm))
        eff_sh = max(14.0, row_tot_h - r_top - r_bot)

        row_bounds_mm.append((cur_y, cur_y + row_tot_h))
        cur_x = pad_x
        c_acc = 0.0

        for b_idx, b in enumerate(r.blocks):
            w_norm12 = 12.0 * (max(0.5, b.weight) / w_sum)
            bw_mm = avail_rw * (w_norm12 / 12.0)
            q_col = int(round(c_acc))
            q_span = max(1, int(round(w_norm12)))
            b.weight = round(w_norm12, 3)

            if len(b.panel_ids) == 1:
                pid = b.panel_ids[0]
                pp = p_map[pid]
                mp = m_map[pid]
                ov_p = panel_overrides.get(pid, PanelStyleOverride())
                ox0, oy0, ox1, oy1 = cur_x, cur_y, cur_x + bw_mm, cur_y + row_tot_h

                base_lm = synced_lm.get(q_col, mp.left_mm) if not pp.locked_special else mp.left_mm
                if base_lm + mp.right_mm > 0.52 * bw_mm and not pp.locked_special:
                    base_lm = mp.left_mm
                eff_lm = max(0.8, base_lm + ov_p.pad_left_mm)
                eff_rm = max(0.6, mp.right_mm + ov_p.pad_right_mm)
                if not pp.locked_special and eff_lm + eff_rm + 8.5 > bw_mm:
                    avail_lr = max(4.0, bw_mm - 8.5)
                    eff_lm = max(2.2, avail_lr * (eff_lm / max(1e-6, eff_lm + eff_rm)))
                    eff_rm = max(1.4, avail_lr - eff_lm)
                sx0 = ox0 + eff_lm
                sx1 = max(sx0 + 8.0, ox1 - eff_rm)

                base_sy0 = oy0 + r_top
                base_sy1 = base_sy0 + eff_sh
                # Per-panel top/bottom margin trim directly moves THIS panel's sy0 / sy1!
                self_bm = mp.bottom_horiz_mm if (sx1 - sx0) >= mp.min_horiz_spine_w_mm else mp.bottom_mm
                min_self_top = max(0.8, mp.top_mm - 2.2)
                min_self_bot = max(0.8, self_bm - 1.8)
                sy0 = base_sy0 if abs(ov_p.pad_top_mm) < 1e-3 else max(oy0 + min_self_top, min(base_sy1 - 10.0, base_sy0 + ov_p.pad_top_mm))
                sy1 = base_sy1 if abs(ov_p.pad_bottom_mm) < 1e-3 else max(sy0 + 10.0, min(oy1 - min_self_bot, base_sy1 - ov_p.pad_bottom_mm))

                # For unlocked isotropic scatter plots, never shrink vertical height (zero top/bottom dead space!); only cap extreme ultra-wide aspect
                if pp.elasticity == "L1_ISOTROPIC_VECTOR" and not pp.locked_special:
                    max_iso_w = 1.45 * (sy1 - sy0)
                    if (sx1 - sx0) > max_iso_w:
                        mid_x = 0.5 * (sx0 + sx1)
                        sx0, sx1 = (sx0, sx0 + max_iso_w) if q_col == 0 else (mid_x - 0.5 * max_iso_w, mid_x + 0.5 * max_iso_w)

                raw_slots.append(
                    CompiledPanelSlot(
                        panel_id=pid,
                        tag_label="",
                        row_idx=r_idx,
                        block_idx=b_idx,
                        stack_idx=0,
                        col_start=q_col,
                        col_span=q_span,
                        weight=b.weight,
                        row_span=2 if any(len(ob.panel_ids) >= 2 for ob in r.blocks) else 1,
                        outer_box_mm=(ox0, oy0, ox1, oy1),
                        spine_box_mm=(sx0, sy0, sx1, sy1),
                        has_legend=(bool(pp.legend_entries) or pp.colorbar is not None) and not pp.locked_special,
                        is_colorbar=(pp.colorbar is not None) and not pp.locked_special,
                        is_categorical_x=pp.is_categorical_x,
                        elasticity=pp.elasticity,
                        locked_special=pp.locked_special,
                    )
                )
            else:
                # Vertical Sub-Stack inside block `b` (`len(b.panel_ids) >= 2`)!
                k_st = len(b.panel_ids)
                avail_sub_h = row_tot_h - gutter_mm * (k_st - 1)
                reqs = [
                    max(0.8, m_map[pid].top_mm + panel_overrides.get(pid, PanelStyleOverride()).pad_top_mm)
                    + max(18.0, m_map[pid].min_spine_h_mm)
                    + max(0.8, m_map[pid].bottom_mm + panel_overrides.get(pid, PanelStyleOverride()).pad_bottom_mm)
                    for pid in b.panel_ids
                ]
                req_sum = sum(reqs)
                sub_y = cur_y
                for s_idx, (pid, rq) in enumerate(zip(b.panel_ids, reqs)):
                    pp = p_map[pid]
                    mp = m_map[pid]
                    ov_p = panel_overrides.get(pid, PanelStyleOverride())
                    sh_tot = avail_sub_h * (rq / req_sum)
                    ox0, oy0, ox1, oy1 = cur_x, sub_y, cur_x + bw_mm, sub_y + sh_tot
                    base_lm = synced_lm.get(q_col, mp.left_mm) if not pp.locked_special else mp.left_mm
                    if base_lm + mp.right_mm > 0.52 * bw_mm and not pp.locked_special:
                        base_lm = mp.left_mm
                    sx0 = ox0 + max(0.8, base_lm + ov_p.pad_left_mm)
                    sx1 = max(sx0 + 8.0, ox1 - max(0.6, mp.right_mm + ov_p.pad_right_mm))
                    sy0 = oy0 + max(0.8, mp.top_mm + ov_p.pad_top_mm)
                    sy1 = max(sy0 + 10.0, oy1 - max(0.8, mp.bottom_mm + ov_p.pad_bottom_mm))

                    raw_slots.append(
                        CompiledPanelSlot(
                            panel_id=pid,
                            tag_label="",
                            row_idx=r_idx,
                            block_idx=b_idx,
                            stack_idx=s_idx,
                            col_start=q_col,
                            col_span=q_span,
                            weight=b.weight,
                            row_span=1,
                            outer_box_mm=(ox0, oy0, ox1, oy1),
                            spine_box_mm=(sx0, sy0, sx1, sy1),
                            has_legend=(bool(pp.legend_entries) or pp.colorbar is not None) and not pp.locked_special,
                            is_colorbar=(pp.colorbar is not None) and not pp.locked_special,
                            is_categorical_x=pp.is_categorical_x,
                            elasticity=pp.elasticity,
                            locked_special=pp.locked_special,
                        )
                    )
                    sub_y += sh_tot + gutter_mm

            cur_x += bw_mm + gutter_mm
            c_acc += w_norm12

        cur_y += row_tot_h + gutter_mm

    # Author Tag Assignment (`row_major` vs `col_major` + Per-Panel `custom_tag` Sovereignty!)
    if tag_flow == "col_major":
        ordered_for_tags = sorted(raw_slots, key=lambda s: (s.block_idx, s.row_idx, s.stack_idx))
    else:
        # Row-major visual reading order: sorted by outer top y (bucketed by 6 mm tolerance) then outer left x!
        ordered_for_tags = sorted(raw_slots, key=lambda s: (round(s.outer_box_mm[1] / 6.0), s.outer_box_mm[0], s.stack_idx))

    auto_counter = 0
    for sl in ordered_for_tags:
        ov = panel_overrides.get(sl.panel_id)
        if ov is not None and ov.custom_tag is not None:
            sl.tag_label = ov.custom_tag.strip()
        else:
            sl.tag_label = _tag_for_index(auto_counter, spec.tag_case)
            auto_counter += 1

    total_h = cur_y - gutter_mm + pad_bot
    warn = None
    if total_h > spec.max_height_mm + 0.5:
        warn = f"{total_h:.1f} mm > {spec.max_height_mm:.0f} mm"
    return raw_slots, clean_rows, row_bounds_mm, total_h, warn
