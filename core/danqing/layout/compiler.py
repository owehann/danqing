"""5-Pass Scale-Invariant Semantic Vector Compiler v2 (Per-Panel Controls, Draggable Legends & Categorical Gap Compression)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import hashlib
import io
import math
import re

from PIL import Image

from .ir import (
    BentoRow,
    CompiledCircle,
    CompiledPath,
    CompiledRaster,
    CompiledRawLockedSVG,
    CompiledText,
    CompositePageScene,
    LegendEntry,
    PanelIR,
    PanelStyleOverride,
    PathSegment,
    ROIOverlaySpec,
)
from .solver import estimate_panel_margins_mm, resolve_effective_legend_pos, solve_bento_layout
from .specs import JOURNAL_SPECS, JournalSpec, measure_text_mm, pt_to_mm


@dataclass
class TypographyConfig:
    journal_id: str = "nature_double"
    custom_width_mm: float | None = None
    custom_max_height_mm: float | None = None
    tag_case_override: str | None = None  # "lower" | "upper" | None
    tag_flow: str = "row_major"           # "row_major" | "col_major"
    layout_mode: str = "auto_bento"
    font_family: str = "Arial"
    tag_pt: float = 8.0
    title_pt: float = 6.8
    axis_title_pt: float = 6.5
    tick_pt: float = 6.0
    annotation_pt: float = 5.6
    axis_stroke_pt: float = 0.50
    data_stroke_pt: float = 0.65
    grid_stroke_pt: float = 0.30
    gutter_mm: float = 3.2
    marker_pt: float = 1.35
    show_panel_titles: bool = True
    hoist_shared_legends: bool = False


def _compute_text_bbox_mm(
    text: str,
    x_mm: float,
    y_mm: float,
    font_pt: float,
    bold: bool,
    font_family: str,
    anchor: str,
    angle_deg: float,
) -> tuple[float, float, float, float]:
    w, cap_h = measure_text_mm(text, font_pt, bold=bold, font_family=font_family)
    desc_h = cap_h * 0.28
    if anchor == "middle":
        lx0, lx1 = -0.5 * w, 0.5 * w
    elif anchor == "end":
        lx0, lx1 = -w, 0.0
    else:
        lx0, lx1 = 0.0, w
    ly0, ly1 = -cap_h, desc_h

    rad = math.radians(angle_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    corners = [
        (x_mm + lx0 * ca - ly0 * sa, y_mm + lx0 * sa + ly0 * ca),
        (x_mm + lx1 * ca - ly0 * sa, y_mm + lx1 * sa + ly0 * ca),
        (x_mm + lx1 * ca - ly1 * sa, y_mm + lx1 * sa + ly1 * ca),
        (x_mm + lx0 * ca - ly1 * sa, y_mm + lx0 * sa + ly1 * ca),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _make_text(
    text: str,
    x_mm: float,
    y_mm: float,
    font_pt: float,
    font_family: str,
    bold: bool = False,
    fill: str = "#000000",
    anchor: str = "start",
    angle_deg: float = 0.0,
    role: str = "TEXT",
    panel_id: str = "",
    italic: bool = False,
    item_key: str = "",
    orig_text: str = "",
    swatch_color: str | None = None,
) -> CompiledText:
    bb = _compute_text_bbox_mm(text, x_mm, y_mm, font_pt, bold, font_family, anchor, angle_deg)
    return CompiledText(
        text=text,
        x_mm=x_mm,
        y_mm=y_mm,
        font_pt=font_pt,
        font_family=font_family,
        bold=bold,
        italic=italic,
        fill=fill,
        anchor=anchor,  # type: ignore[arg-type]
        angle_deg=angle_deg,
        role=role,
        panel_id=panel_id,
        item_key=item_key,
        orig_text=orig_text or text,
        swatch_color=swatch_color,
        bbox_mm=bb,
    )


def _resolve_item_style(
    ov: PanelStyleOverride,
    item_key: str,
    base_text: str,
    base_pt: float,
    base_font: str,
    base_bold: bool,
    base_fill: str,
    swatch_hex: str | None = None,
) -> tuple[str, float, str, bool, bool, str]:
    tov = ov.text_overrides.get(item_key) if ov.text_overrides else None
    if tov is None:
        return (base_text, base_pt, base_font, base_bold, False, base_fill)
    eff_txt = tov.text.strip() if (tov.text is not None and tov.text.strip()) else base_text
    eff_pt = max(4.2, base_pt * max(0.70, min(1.50, tov.font_scale)))
    eff_font = tov.font_family or base_font
    eff_bold = tov.bold if tov.bold is not None else base_bold
    eff_italic = bool(tov.italic)
    if tov.color == "SWATCH" and swatch_hex:
        eff_fill = _readable_swatch_text_color(swatch_hex)
    elif tov.color:
        eff_fill = _normalize_hex_color(tov.color, base_fill)
    else:
        eff_fill = base_fill
    return (eff_txt, eff_pt, eff_font, eff_bold, eff_italic, eff_fill)


def _make_styled_text(
    ov: PanelStyleOverride,
    item_key: str,
    text: str,
    x_mm: float,
    y_mm: float,
    font_pt: float,
    font_family: str,
    bold: bool = False,
    fill: str = "#000000",
    anchor: str = "start",
    angle_deg: float = 0.0,
    role: str = "TEXT",
    panel_id: str = "",
    swatch_color: str | None = None,
) -> CompiledText:
    eff_txt, eff_pt, eff_font, eff_bold, eff_italic, eff_fill = _resolve_item_style(
        ov, item_key, text, font_pt, font_family, bold, fill, swatch_hex=swatch_color
    )
    return _make_text(
        eff_txt,
        x_mm,
        y_mm,
        eff_pt,
        eff_font,
        bold=eff_bold,
        fill=eff_fill,
        anchor=anchor,
        angle_deg=angle_deg,
        role=role,
        panel_id=panel_id,
        italic=eff_italic,
        item_key=item_key,
        orig_text=text,
        swatch_color=swatch_color,
    )


def _normalize_hex_color(col: str | None, default: str = "#000000") -> str:
    if not col:
        return default
    s = col.strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", s):
        return s.upper()
    if re.fullmatch(r"#[0-9A-Fa-f]{3}", s):
        return ("#" + "".join(ch * 2 for ch in s[1:])).upper()
    return default


def _readable_swatch_text_color(col: str | None) -> str:
    """Keep swatch hue for direct legend emphasis while darkening pale tints so contrast on white stays crisp."""
    hx = _normalize_hex_color(col, "#111827")
    r = int(hx[1:3], 16)
    g = int(hx[3:5], 16)
    b = int(hx[5:7], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum > 152.0:
        fac = 142.0 / lum
        r = max(0, min(255, int(round(r * fac))))
        g = max(0, min(255, int(round(g * fac))))
        b = max(0, min(255, int(round(b * fac))))
        return f"#{r:02X}{g:02X}{b:02X}"
    return hx


def _rect_segs_mm(x0: float, y0: float, x1: float, y1: float) -> list[PathSegment]:
    return [
        PathSegment("M", (x0, y0)),
        PathSegment("L", (x1, y0)),
        PathSegment("L", (x1, y1)),
        PathSegment("L", (x0, y1)),
        PathSegment("Z", ()),
    ]


def _line_segs_mm(x0: float, y0: float, x1: float, y1: float) -> list[PathSegment]:
    return [PathSegment("M", (x0, y0)), PathSegment("L", (x1, y1))]


def _strip_outer_svg(svg_bytes: bytes) -> str:
    txt = svg_bytes.decode("utf-8", errors="replace")
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt).strip()
    m_open = re.search(r"<svg[^>]*>", txt, flags=re.DOTALL)
    m_close = re.search(r"</svg\s*>\s*$", txt, flags=re.DOTALL)
    if m_open and m_close:
        return txt[m_open.end() : m_close.start()]
    return txt


def _crop_png_bytes(png_bytes: bytes, x_norm: float, y_norm: float, w_norm: float, h_norm: float) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(png_bytes)) as im:
        rgb = im.convert("RGB")
        W, H = rgb.size
        x0 = max(0, min(W - 8, int(round(x_norm * W))))
        y0 = max(0, min(H - 8, int(round(y_norm * H))))
        cw = max(8, min(W - x0, int(round(w_norm * W))))
        ch = max(8, min(H - y0, int(round(h_norm * H))))
        sub = rgb.crop((x0, y0, x0 + cw, y0 + ch))
        buf = io.BytesIO()
        sub.save(buf, format="PNG", compress_level=9)
        return buf.getvalue(), cw, ch


def _detect_shared_legend(
    panels: list[PanelIR],
    locked_map: dict[str, bool],
    panel_overrides: dict[str, PanelStyleOverride],
) -> tuple[set[str], list[LegendEntry]]:
    """Find legend groups shared identically across >=2 active panels that haven't overridden legend_pos."""
    sig_to_pids: dict[tuple[tuple[str, str], ...], list[str]] = {}
    sig_to_entries: dict[tuple[tuple[str, str], ...], list[LegendEntry]] = {}
    for p in panels:
        ov = panel_overrides.get(p.panel_id)
        if locked_map.get(p.panel_id, p.locked_special) or not p.legend_entries:
            continue
        if ov is not None and ov.legend_pos != "auto":
            continue
        sig = tuple((le.label, le.color.upper()) for le in p.legend_entries)
        sig_to_pids.setdefault(sig, []).append(p.panel_id)
        sig_to_entries[sig] = p.legend_entries

    hoisted_pids: set[str] = set()
    merged_entries: list[LegendEntry] = []
    for sig, pids in sig_to_pids.items():
        if len(pids) >= 2:
            hoisted_pids.update(pids)
            merged_entries.extend(sig_to_entries[sig])
    return hoisted_pids, merged_entries


def _build_categorical_x_map(
    rx0: float,
    rx1: float,
    cat_centers_raw: list[float],
    gamma: float,
) -> tuple[Callable[[float], float], float]:
    """Build exact piecewise-linear monotonic map u_norm(x_raw) -> [0, 1] that compresses inter-category gaps by `gamma`
    while keeping intra-category box/bar/jitter widths at slope 1.0!
    """
    rw = max(1e-6, rx1 - rx0)
    cs = sorted(c for c in cat_centers_raw if rx0 + 1e-3 < c < rx1 - 1e-3)
    if len(cs) < 2 or abs(gamma - 1.0) < 1e-3:
        return (lambda xr: (xr - rx0) / rw, 1.0)

    min_pitch = min(cs[k + 1] - cs[k] for k in range(len(cs) - 1))
    half_band = min(0.26 * min_pitch, 0.45 * min(cs[0] - rx0, rx1 - cs[-1], min_pitch))
    half_band = max(1.0, half_band)

    knots_old: list[float] = [rx0]
    knots_new: list[float] = [0.0]
    cur_x = rx0
    cur_out = 0.0

    for c in cs:
        b_lo = max(cur_x, c - half_band)
        b_hi = min(rx1, c + half_band)
        # Gap [cur_x, b_lo] scales by gamma
        gap_len = max(0.0, b_lo - cur_x)
        cur_out += gamma * gap_len
        knots_old.append(b_lo)
        knots_new.append(cur_out)
        # Data band [b_lo, b_hi] keeps slope 1.0!
        band_len = max(0.0, b_hi - b_lo)
        cur_out += 1.0 * band_len
        knots_old.append(b_hi)
        knots_new.append(cur_out)
        cur_x = b_hi

    tail_gap = max(0.0, rx1 - cur_x)
    cur_out += gamma * tail_gap
    knots_old.append(rx1)
    knots_new.append(cur_out)

    tot_new = max(1e-6, cur_out)
    length_ratio = max(0.42, min(1.25, tot_new / rw))

    def _u_map(xr: float) -> float:
        if xr <= rx0:
            return (xr - rx0) * gamma / tot_new
        if xr >= rx1:
            return 1.0 + (xr - rx1) * gamma / tot_new
        for idx in range(len(knots_old) - 1):
            x_a, x_b = knots_old[idx], knots_old[idx + 1]
            if x_a <= xr <= x_b:
                if x_b - x_a < 1e-9:
                    return knots_new[idx] / tot_new
                t = (xr - x_a) / (x_b - x_a)
                return (knots_new[idx] + t * (knots_new[idx + 1] - knots_new[idx])) / tot_new
        return (xr - rx0) / rw

    return (_u_map, length_ratio)


def _resolve_spec(cfg: TypographyConfig) -> JournalSpec:
    base = JOURNAL_SPECS.get(cfg.journal_id, JOURNAL_SPECS["nature_double"])
    w = cfg.custom_width_mm if (cfg.custom_width_mm and cfg.custom_width_mm >= 45.0) else base.width_mm
    h = cfg.custom_max_height_mm if (cfg.custom_max_height_mm and cfg.custom_max_height_mm >= 50.0) else base.max_height_mm
    tc = cfg.tag_case_override if cfg.tag_case_override in ("lower", "upper") else base.tag_case
    return replace(base, width_mm=w, max_height_mm=h, tag_case=tc)


def compile_modular_scene(
    panels: list[PanelIR],
    cfg: TypographyConfig,
    span_overrides: dict[str, int] | None = None,
    locked_overrides: dict[str, bool] | None = None,
    roi_overrides: dict[str, ROIOverlaySpec] | None = None,
    panel_overrides: dict[str, PanelStyleOverride] | None = None,
    bento_rows: list[BentoRow] | None = None,
) -> CompositePageScene:
    """Compile selected panels through the 5-Pass Scale-Invariant Semantic Vector Compiler v2."""
    spec = _resolve_spec(cfg)
    span_overrides = span_overrides or {}
    locked_overrides = locked_overrides or {}
    roi_overrides = roi_overrides or {}
    panel_overrides = panel_overrides or {}

    eff_panels: list[PanelIR] = []
    locked_map: dict[str, bool] = {}
    for p in panels:
        is_lk = locked_overrides.get(p.panel_id, p.locked_special)
        locked_map[p.panel_id] = is_lk
        if is_lk != p.locked_special:
            eff_panels.append(
                replace(
                    p,
                    locked_special=is_lk,
                    elasticity=("L0_LOCKED_SPECIAL" if (p.rasters and len(p.shapes) <= 4) else "T2_COUPLED_LOCKED")
                    if is_lk
                    else "L2_ELASTIC_CARTESIAN",
                )
            )
        else:
            eff_panels.append(p)

    panel_by_id = {p.panel_id: p for p in eff_panels}

    # Pass 1: Shared Legend Detection (excluding panels where user manually positioned legend)
    hoisted_pids: set[str] = set()
    shared_entries: list[LegendEntry] = []
    if cfg.hoist_shared_legends:
        hoisted_pids, shared_entries = _detect_shared_legend(eff_panels, locked_map, panel_overrides)
    shared_bar_h = 6.2 if shared_entries else 0.0

    margins = [
        estimate_panel_margins_mm(
            p,
            spec=spec,
            font_family=cfg.font_family,
            title_pt=cfg.title_pt,
            axis_title_pt=cfg.axis_title_pt,
            tick_pt=cfg.tick_pt,
            show_panel_titles=cfg.show_panel_titles,
            suppress_legend=(p.panel_id in hoisted_pids),
            ov=panel_overrides.get(p.panel_id),
        )
        for p in eff_panels
    ]

    slots, clean_rows, row_bounds_mm, page_h_mm, overflow_warn = solve_bento_layout(
        eff_panels,
        margins,
        spec=spec,
        layout_mode=cfg.layout_mode,
        gutter_mm=cfg.gutter_mm,
        span_overrides=span_overrides,
        shared_legend_height_mm=shared_bar_h,
        bento_rows=bento_rows,
        panel_overrides=panel_overrides,
        tag_flow=cfg.tag_flow,
    )

    scene = CompositePageScene(
        width_mm=spec.width_mm,
        height_mm=page_h_mm,
        journal_id=spec.id,
        font_family=cfg.font_family,
        slots=slots,
        bento_rows=clean_rows,
        row_bounds_mm=row_bounds_mm,
        shared_legend_hoisted=bool(shared_entries),
        overflow_warning=overflow_warn,
    )

    # Render Shared Legend Bar if hoisted
    if shared_entries:
        bar_y = 5.6
        item_widths = [4.2 + measure_text_mm(le.label, cfg.tick_pt, font_family=cfg.font_family)[0] + 4.2 for le in shared_entries]
        tot_lw = sum(item_widths) - 4.2
        if tot_lw <= spec.width_mm - 10.0:
            start_x = max(5.0, 0.5 * (spec.width_mm - tot_lw))
            scene.paths.append(
                CompiledPath(
                    segments_mm=_rect_segs_mm(start_x - 2.4, bar_y - 3.2, start_x + tot_lw + 2.4, bar_y + 1.8),
                    fill="#F8FAFC",
                    stroke="#CBD5E1",
                    stroke_pt=0.35,
                    role="SHARED_LEGEND_BG",
                )
            )
            cx_lg = start_x
            for le, iw in zip(shared_entries, item_widths):
                if le.kind == "circle":
                    scene.circles.append(
                        CompiledCircle(cx_mm=cx_lg + 1.3, cy_mm=bar_y - 0.85, r_mm=1.1, fill=le.color, fill_opacity=0.92, panel_id="SHARED")
                    )
                else:
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_rect_segs_mm(cx_lg, bar_y - 2.0, cx_lg + 2.5, bar_y + 0.3),
                            fill=le.color,
                            stroke="none",
                            role="LEGEND_SWATCH",
                        )
                    )
                scene.texts.append(
                    _make_text(le.label, cx_lg + 3.5, bar_y, cfg.tick_pt, cfg.font_family, role="SHARED_LEGEND")
                )
                cx_lg += iw

    margin_by_id = {p.panel_id: m for p, m in zip(eff_panels, margins)}

    # Compile each panel slot (Note: `slots` order follows 2D Bento Grid blocks)
    for sl in slots:
        p = panel_by_id[sl.panel_id]
        ov = panel_overrides.get(p.panel_id, PanelStyleOverride())
        mp = margin_by_id[p.panel_id]
        ox0, oy0, ox1, oy1 = sl.outer_box_mm
        sx0, sy0, sx1, sy1 = sl.spine_box_mm
        roi_cfg = roi_overrides.get(p.panel_id, p.default_roi)

        eff_title_pt = cfg.title_pt * ov.font_scale
        eff_axis_pt = cfg.axis_title_pt * ov.font_scale
        eff_tick_pt = cfg.tick_pt * ov.font_scale
        eff_ann_pt = cfg.annotation_pt * ov.font_scale
        eff_axis_sw = cfg.axis_stroke_pt * ov.stroke_scale
        eff_data_sw = cfg.data_stroke_pt * ov.stroke_scale
        eff_grid_sw = cfg.grid_stroke_pt * ov.stroke_scale
        eff_marker_pt = cfg.marker_pt * ov.marker_scale
        eff_show_title = ov.show_title if ov.show_title is not None else cfg.show_panel_titles
        p_font = ov.panel_font_family or cfg.font_family
        lg_font = ov.legend_font_family or p_font
        leg_txt_col = _normalize_hex_color(ov.legend_text_color, "#000000")

        # Panel Tag (`sl.tag_label` may be empty "" if author intentionally hid it!)
        if sl.tag_label:
            tag_y = oy0 + pt_to_mm(cfg.tag_pt * 0.78) + 0.4
            tag_x = ox0 + 0.4
            scene.texts.append(
                _make_styled_text(
                    ov,
                    "TAG",
                    sl.tag_label,
                    tag_x,
                    tag_y,
                    cfg.tag_pt,
                    cfg.font_family,
                    bold=True,
                    fill="#000000",
                    anchor="start",
                    role="PANEL_TAG",
                    panel_id=p.panel_id,
                )
            )

        # ---------------- Pass 2: Locked Special Panels ----------------
        if p.locked_special:
            avail_w = max(8.0, sx1 - sx0)
            avail_h = max(8.0, sy1 - sy0)

            if p.rasters and p.elasticity == "L0_LOCKED_SPECIAL" and len(p.shapes) <= 4:
                r0 = p.rasters[0]
                png_bytes = r0.png_bytes
                w_px, h_px = r0.width_px, r0.height_px
                sha = r0.sha256
                eff_fov_um = roi_cfg.fov_width_um

                if roi_cfg.linked_source_id and roi_cfg.linked_source_id in panel_by_id:
                    src_p = panel_by_id[roi_cfg.linked_source_id]
                    src_roi = roi_overrides.get(src_p.panel_id, src_p.default_roi)
                    if src_p.rasters and src_roi.enabled and src_roi.w_norm > 0.03 and src_roi.h_norm > 0.03:
                        png_bytes, w_px, h_px = _crop_png_bytes(
                            src_p.rasters[0].png_bytes,
                            src_roi.x_norm,
                            src_roi.y_norm,
                            src_roi.w_norm,
                            src_roi.h_norm,
                        )
                        sha = hashlib.sha256(png_bytes).hexdigest()
                        if src_roi.fov_width_um:
                            eff_fov_um = src_roi.fov_width_um * src_roi.w_norm

                img_aspect = w_px / max(1e-6, float(h_px))
                if avail_w / avail_h > img_aspect:
                    draw_h = avail_h
                    draw_w = draw_h * img_aspect
                else:
                    draw_w = avail_w
                    draw_h = draw_w / img_aspect

                ix0 = 0.5 * (sx0 + sx1) - 0.5 * draw_w
                iy0 = sy0 + 0.5 * (avail_h - draw_h)
                sl.spine_box_mm = (ix0, iy0, ix0 + draw_w, iy0 + draw_h)
                sl.scale_x = draw_w / max(1e-6, r0.w_raw)
                sl.scale_y = sl.scale_x

                eff_dpi = w_px / max(1e-6, draw_w / 25.4)
                asp_err = abs((draw_w / max(1e-9, draw_h)) / img_aspect - 1.0)
                scene.rasters.append(
                    CompiledRaster(
                        png_bytes=png_bytes,
                        sha256=sha,
                        width_px=w_px,
                        height_px=h_px,
                        x_mm=ix0,
                        y_mm=iy0,
                        w_mm=draw_w,
                        h_mm=draw_h,
                        panel_id=p.panel_id,
                        effective_dpi=eff_dpi,
                        aspect_ratio_error=asp_err,
                    )
                )
                border_col = "#F59E0B" if roi_cfg.linked_source_id else "#1E293B"
                scene.paths.append(
                    CompiledPath(
                        segments_mm=_rect_segs_mm(ix0, iy0, ix0 + draw_w, iy0 + draw_h),
                        fill="none",
                        stroke=border_col,
                        stroke_pt=eff_axis_sw,
                        panel_id=p.panel_id,
                        role="LOCKED_FRAME",
                    )
                )

                if roi_cfg.enabled and not roi_cfg.linked_source_id and roi_cfg.w_norm > 0.03 and roi_cfg.h_norm > 0.03:
                    rx = ix0 + max(0.0, min(0.95, roi_cfg.x_norm)) * draw_w
                    ry = iy0 + max(0.0, min(0.95, roi_cfg.y_norm)) * draw_h
                    rw = min(draw_w - (rx - ix0), roi_cfg.w_norm * draw_w)
                    rh = min(draw_h - (ry - iy0), roi_cfg.h_norm * draw_h)
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_rect_segs_mm(rx, ry, rx + rw, ry + rh),
                            fill="none",
                            stroke=roi_cfg.color,
                            stroke_pt=max(0.65, eff_data_sw),
                            dasharray_mm="1.1,0.75" if roi_cfg.dashed else None,
                            panel_id=p.panel_id,
                            role="ROI_OVERLAY",
                        )
                    )
                    if roi_cfg.label:
                        lw, lh = measure_text_mm(roi_cfg.label, eff_ann_pt, bold=True, font_family=cfg.font_family)
                        lbl_y = ry - 0.8 if (ry - iy0) > (lh + 1.6) else (ry + lh + 0.9)
                        lbl_x = min(ix0 + draw_w - lw - 0.8, max(ix0 + 0.8, rx))
                        scene.paths.append(
                            CompiledPath(
                                segments_mm=_rect_segs_mm(lbl_x - 0.6, lbl_y - lh - 0.35, lbl_x + lw + 0.6, lbl_y + 0.45),
                                fill="#0F172A",
                                fill_opacity=0.80,
                                stroke="none",
                                panel_id=p.panel_id,
                                role="ROI_BADGE",
                            )
                        )
                        scene.texts.append(
                            _make_text(
                                roi_cfg.label,
                                lbl_x,
                                lbl_y,
                                eff_ann_pt,
                                cfg.font_family,
                                bold=True,
                                fill=roi_cfg.color,
                                anchor="start",
                                role="ROI_LABEL",
                                panel_id=p.panel_id,
                            )
                        )

                if roi_cfg.scale_bar_um and eff_fov_um and eff_fov_um > 0:
                    target_um = roi_cfg.scale_bar_um
                    bar_mm = (target_um / eff_fov_um) * draw_w
                    while bar_mm > 0.36 * draw_w and target_um > 10.0:
                        target_um *= 0.5
                        bar_mm = (target_um / eff_fov_um) * draw_w
                    sb_txt = f"{int(round(target_um))} µm" if target_um < 1000 else f"{target_um/1000.0:.1f} mm"
                    tw_sb, th_sb = measure_text_mm(sb_txt, eff_ann_pt * 0.92, bold=True, font_family=cfg.font_family)
                    content_w = max(bar_mm, tw_sb)
                    pill_x1 = ix0 + draw_w - 1.2
                    pill_x0 = max(ix0 + 1.0, pill_x1 - content_w - 2.0)
                    sb_cx = 0.5 * (pill_x0 + pill_x1)
                    bx0_sb = sb_cx - 0.5 * bar_mm
                    bx1_sb = sb_cx + 0.5 * bar_mm
                    by_sb = iy0 + draw_h - 1.7
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_rect_segs_mm(pill_x0, by_sb - th_sb - 1.45, pill_x1, by_sb + 0.85),
                            fill="#0F172A",
                            fill_opacity=0.76,
                            stroke="none",
                            panel_id=p.panel_id,
                            role="SCALEBAR_BG",
                        )
                    )
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_line_segs_mm(bx0_sb, by_sb, bx1_sb, by_sb),
                            stroke="#FFFFFF",
                            stroke_pt=1.0,
                            panel_id=p.panel_id,
                            role="SCALEBAR",
                        )
                    )
                    scene.texts.append(
                        _make_text(
                            sb_txt,
                            sb_cx,
                            by_sb - 0.65,
                            max(5.0, eff_ann_pt * 0.92),
                            cfg.font_family,
                            bold=True,
                            fill="#FFFFFF",
                            anchor="middle",
                            role="SCALEBAR_TEXT",
                            panel_id=p.panel_id,
                        )
                    )

                if eff_show_title and p.title_hint:
                    max_tw_s = max(12.0, (ox1 - ox0) - 6.0)
                    t_s = p.title_hint
                    tw_s, _ = measure_text_mm(t_s, eff_title_pt, bold=True, font_family=p_font)
                    while tw_s > max_tw_s and " " in t_s:
                        t_s = t_s.rsplit(" ", 1)[0]
                        tw_s, _ = measure_text_mm(t_s, eff_title_pt, bold=True, font_family=p_font)
                    lo_s = ox0 + (4.6 if sl.tag_label else 1.0) + 0.5 * tw_s
                    hi_s = max(lo_s, ox1 - 0.8 - 0.5 * tw_s)
                    scene.texts.append(
                        _make_styled_text(
                            ov,
                            "TITLE",
                            t_s,
                            max(lo_s, min(hi_s, ix0 + 0.5 * draw_w)),
                            iy0 - 1.15,
                            eff_title_pt,
                            p_font,
                            bold=True,
                            anchor="middle",
                            role="PANEL_TITLE",
                            panel_id=p.panel_id,
                        )
                    )
            else:
                vx, vy, vw, vh = p.viewbox
                diag_aspect = vw / max(1e-6, vh)
                if avail_w / avail_h > diag_aspect:
                    draw_h = avail_h
                    draw_w = draw_h * diag_aspect
                else:
                    draw_w = avail_w
                    draw_h = draw_w / diag_aspect
                ix0 = 0.5 * (sx0 + sx1) - 0.5 * draw_w
                iy0 = sy0 + 0.5 * (avail_h - draw_h)
                s_iso = draw_w / max(1e-6, vw)
                sl.spine_box_mm = (ix0, iy0, ix0 + draw_w, iy0 + draw_h)
                sl.scale_x = s_iso
                sl.scale_y = s_iso
                scene.locked_svgs.append(
                    CompiledRawLockedSVG(
                        svg_inner_xml=_strip_outer_svg(p.raw_svg_bytes),
                        raw_vb=(vx, vy, vw, vh),
                        x_mm=ix0,
                        y_mm=iy0,
                        w_mm=draw_w,
                        h_mm=draw_h,
                        scale_isotropic=s_iso,
                        panel_id=p.panel_id,
                    )
                )
                if eff_show_title and p.title_hint:
                    max_tw_s = max(12.0, (ox1 - ox0) - 6.0)
                    t_s = p.title_hint
                    tw_s, _ = measure_text_mm(t_s, eff_title_pt, bold=True, font_family=p_font)
                    while tw_s > max_tw_s and " " in t_s:
                        t_s = t_s.rsplit(" ", 1)[0]
                        tw_s, _ = measure_text_mm(t_s, eff_title_pt, bold=True, font_family=p_font)
                    lo_s = ox0 + (4.6 if sl.tag_label else 1.0) + 0.5 * tw_s
                    hi_s = max(lo_s, ox1 - 0.8 - 0.5 * tw_s)
                    scene.texts.append(
                        _make_styled_text(
                            ov,
                            "TITLE",
                            t_s,
                            max(lo_s, min(hi_s, ix0 + 0.5 * draw_w)),
                            iy0 - 1.15,
                            eff_title_pt,
                            p_font,
                            bold=True,
                            anchor="middle",
                            role="PANEL_TITLE",
                            panel_id=p.panel_id,
                        )
                    )
            continue

        # ---------------- Pass 3: Decoupled Reprojection + Lossless Categorical Gap Compression ----------------
        rx0, ry0, rx1, ry1 = p.spine_box
        rw_sp = max(1e-6, rx1 - rx0)
        rh_sp = max(1e-6, ry1 - ry0)

        # Extract raw categorical centers for piecewise-linear gap compression (`Panel G`!)
        cat_centers = sorted(tk.pos_raw for tk in p.ticks if tk.axis == "x")
        if len(cat_centers) < 2:
            cat_centers = sorted(t.x_raw for t in p.texts if t.role == "X_TICK")

        u_x_map, cat_len_ratio = _build_categorical_x_map(
            rx0,
            rx1,
            cat_centers,
            ov.category_spacing if p.is_categorical_x else 1.0,
        )

        # Apply `frame_width_ratio` AND auto-tighten SpineBox width when `category_spacing < 1.0`!
        eff_w_ratio = max(0.40, min(1.0, ov.frame_width_ratio * (cat_len_ratio if cat_len_ratio < 1.0 else 1.0)))
        if eff_w_ratio < 0.999 and p.elasticity != "L1_ISOTROPIC_VECTOR":
            full_tw = sx1 - sx0
            new_tw = max(12.0, full_tw * eff_w_ratio)
            mid_sp_x = 0.5 * (sx0 + sx1)
            sx0, sx1 = mid_sp_x - 0.5 * new_tw, mid_sp_x + 0.5 * new_tw
            sl.spine_box_mm = (sx0, sy0, sx1, sy1)

        tw_sp = max(4.0, sx1 - sx0)
        th_sp = max(4.0, sy1 - sy0)
        sl.scale_x = tw_sp / rw_sp
        sl.scale_y = th_sp / rh_sp

        def _phi(x_r: float, y_r: float) -> tuple[float, float]:
            return (sx0 + u_x_map(x_r) * tw_sp, sy0 + ((y_r - ry0) / rh_sp) * th_sp)

        clip_id = f"clip-{p.panel_id}"
        scene.clips_mm[clip_id] = (sx0 - 0.15, sy0 - 0.15, sx1 + 0.15, sy1 + 0.15)

        bracket_tops: list[tuple[float, float]] = []
        for sh in p.shapes:
            if sh.role == "ERROR_CAP" and sh.cap_center is not None:
                cx_m, cy_m = _phi(sh.cap_center[0], sh.cap_center[1])
                hw_m = pt_to_mm(sh.cap_half_pt)
                scene.paths.append(
                    CompiledPath(
                        segments_mm=_line_segs_mm(cx_m - hw_m, cy_m, cx_m + hw_m, cy_m),
                        stroke=sh.stroke,
                        stroke_opacity=sh.stroke_opacity,
                        stroke_pt=eff_axis_sw,
                        panel_id=p.panel_id,
                        role="ERROR_CAP",
                        norm_check=(u_x_map(sh.cap_center[0]), (sh.cap_center[1] - ry0) / rh_sp),
                    )
                )
                continue

            t_segs: list[PathSegment] = []
            for seg in sh.segments:
                if seg.op in ("M", "L"):
                    t_segs.append(PathSegment(seg.op, _phi(seg.pts[0], seg.pts[1])))
                elif seg.op == "C":
                    q1 = _phi(seg.pts[0], seg.pts[1])
                    q2 = _phi(seg.pts[2], seg.pts[3])
                    qe = _phi(seg.pts[4], seg.pts[5])
                    t_segs.append(PathSegment("C", (q1[0], q1[1], q2[0], q2[1], qe[0], qe[1])))
                else:
                    t_segs.append(PathSegment("Z", ()))

            if sh.role == "SPINE_BORDER":
                sw_pt = eff_axis_sw
                dash_m = None
            elif sh.role == "GRID":
                sw_pt = eff_grid_sw
                dash_m = "0.9,0.7" if sh.dasharray else None
            elif sh.role in ("BRACKET", "ERROR_STEM"):
                sw_pt = eff_axis_sw
                dash_m = None
                if sh.role == "BRACKET":
                    xs_b = [s.pts[0] for s in t_segs if s.pts]
                    ys_b = [s.pts[1] for s in t_segs if s.pts]
                    if xs_b and ys_b:
                        bracket_tops.append((0.5 * (min(xs_b) + max(xs_b)), min(ys_b)))
            else:
                sw_pt = eff_data_sw if sh.stroke not in ("none", "transparent") else 0.0
                dash_m = "1.0,0.8" if sh.dasharray else None

            scene.paths.append(
                CompiledPath(
                    segments_mm=t_segs,
                    fill=sh.fill,
                    fill_opacity=sh.fill_opacity,
                    stroke=sh.stroke,
                    stroke_opacity=sh.stroke_opacity,
                    stroke_pt=sw_pt,
                    dasharray_mm=dash_m,
                    clip_id=clip_id if sh.clip_to_spine else None,
                    panel_id=p.panel_id,
                    role=sh.role,
                )
            )

        n_mk = len(p.markers)
        dense_factor = 0.72 if n_mk > 250 else (0.86 if n_mk > 80 else 1.0)
        base_r_mm = pt_to_mm(eff_marker_pt * dense_factor)
        for mk in p.markers:
            cx_m, cy_m = _phi(mk.cx, mk.cy)
            if mk.is_proportional_bubble:
                pitch = min(tw_sp / max(1, p.n_x_categories), th_sp / max(1, p.n_y_categories))
                r_m = min(0.42 * pitch, pt_to_mm(eff_marker_pt * 1.35 * mk.rel_size))
            else:
                r_m = base_r_mm
            norm_xy = (u_x_map(mk.cx), (mk.cy - ry0) / rh_sp) if mk.clip_to_spine else None
            scene.circles.append(
                CompiledCircle(
                    cx_mm=cx_m,
                    cy_mm=cy_m,
                    r_mm=r_m,
                    fill=mk.fill,
                    fill_opacity=mk.fill_opacity,
                    stroke=mk.stroke,
                    stroke_pt=0.32 * ov.stroke_scale if mk.stroke not in ("none", "transparent") else 0.0,
                    clip_id=clip_id if mk.clip_to_spine else None,
                    panel_id=p.panel_id,
                    norm_xy=norm_xy,
                )
            )

        tick_len_mm = 0.80
        for tk in p.ticks:
            if tk.axis == "x":
                tx_m, _ = _phi(tk.pos_raw, ry1)
                scene.paths.append(
                    CompiledPath(
                        segments_mm=_line_segs_mm(tx_m, sy1, tx_m, sy1 + tick_len_mm),
                        stroke="#000000",
                        stroke_pt=eff_axis_sw,
                        panel_id=p.panel_id,
                        role="TICK",
                    )
                )
            else:
                _, ty_m = _phi(rx0, tk.pos_raw)
                scene.paths.append(
                    CompiledPath(
                        segments_mm=_line_segs_mm(sx0 - tick_len_mm, ty_m, sx0, ty_m),
                        stroke="#000000",
                        stroke_pt=eff_axis_sw,
                        panel_id=p.panel_id,
                        role="TICK",
                    )
                )

        # ---------------- Pass 4: Margin Box-Chain Reflow & Draggable / Horizontal Legend ----------------
        eff_leg_pos, auto_leg_xy = resolve_effective_legend_pos(p, ov, suppress_legend=(p.panel_id in hoisted_pids))
        sl.effective_legend_pos = eff_leg_pos
        if eff_leg_pos == "top":
            if p.colorbar is not None:
                top_title_offset = 2.0 * ov.legend_scale + pt_to_mm(eff_tick_pt * ov.legend_scale * 1.15) + 1.7
            else:
                top_title_offset = pt_to_mm(eff_tick_pt * ov.legend_scale * 1.45) + 1.3
        else:
            top_title_offset = 0.0

        if eff_show_title:
            titles = [t for t in p.texts if t.role == "PANEL_TITLE"]
            title_str = titles[0].text if titles else p.title_hint
            if title_str:
                tag_pad = 4.8 if sl.tag_label else 1.0
                max_tw = max(12.0, (ox1 - ox0) - tag_pad - 1.2)
                tw_cur, _ = measure_text_mm(title_str, eff_title_pt, bold=True, font_family=p_font)
                if tw_cur > max_tw:
                    title_str = re.sub(r"\s*\([^)]*\)\s*$", "", title_str).strip()
                    tw_cur, _ = measure_text_mm(title_str, eff_title_pt, bold=True, font_family=p_font)
                while tw_cur > max_tw and " " in title_str:
                    title_str = title_str.rsplit(" ", 1)[0].rstrip(".,:")
                    tw_cur, _ = measure_text_mm(title_str, eff_title_pt, bold=True, font_family=p_font)
                lo_cx = ox0 + tag_pad + 0.5 * tw_cur
                hi_cx = max(lo_cx, ox1 - 0.8 - 0.5 * tw_cur)
                title_cx = max(lo_cx, min(hi_cx, 0.5 * (sx0 + sx1)))
                scene.texts.append(
                    _make_styled_text(
                        ov,
                        "TITLE",
                        title_str,
                        title_cx,
                        sy0 - 1.25 - top_title_offset,
                        eff_title_pt,
                        p_font,
                        bold=True,
                        anchor="middle",
                        role="PANEL_TITLE",
                        panel_id=p.panel_id,
                    )
                )

        y_ticks_txt = sorted([t for t in p.texts if t.role == "Y_TICK"], key=lambda t: t.y_raw)
        yt_cap_h = measure_text_mm("0", eff_tick_pt, font_family=p_font)[1]
        min_yt_left = sx0 - tick_len_mm - 0.6
        last_yt_bb: tuple[float, float, float, float] | None = None
        max_yt_avail = max(3.5, (sx0 - ox0) - tick_len_mm - (pt_to_mm(eff_axis_pt * 0.85) + 1.5 if any(t.role == "Y_TITLE" for t in p.texts) else 0.7))
        for yt_idx, yt in enumerate(y_ticks_txt):
            near_t = min((tk.pos_raw for tk in p.ticks if tk.axis == "y"), key=lambda v: abs(v - yt.y_raw), default=yt.y_raw)
            use_yr = near_t if abs(near_t - yt.y_raw) <= 8.0 else yt.y_raw
            _, ym = _phi(rx0, use_yr)
            yt_key = f"YT:{yt_idx}"
            tov_y = ov.text_overrides.get(yt_key)
            yt_str = yt.text
            if not (tov_y and tov_y.text and tov_y.text.strip()):
                while len(yt_str) > 5 and measure_text_mm(yt_str, eff_tick_pt, font_family=p_font)[0] > max_yt_avail + 0.4:
                    yt_str = yt_str[:-2].rstrip() + "."
            ct = _make_styled_text(
                ov,
                yt_key,
                yt_str,
                sx0 - tick_len_mm - 0.55,
                ym + 0.36 * yt_cap_h,
                eff_tick_pt,
                p_font,
                bold=False,
                anchor="end",
                role="Y_TICK",
                panel_id=p.panel_id,
            )
            if last_yt_bb is not None and ct.bbox_mm[1] < last_yt_bb[3] + 0.15:
                continue
            scene.texts.append(ct)
            last_yt_bb = ct.bbox_mm
            min_yt_left = min(min_yt_left, ct.bbox_mm[0])

        y_titles = [t for t in p.texts if t.role == "Y_TITLE"]
        if y_titles:
            yt_x = max(ox0 + pt_to_mm(eff_axis_pt * 0.80), min_yt_left - 1.35)
            scene.texts.append(
                _make_styled_text(
                    ov,
                    "Y_TITLE",
                    y_titles[0].text,
                    yt_x,
                    0.5 * (sy0 + sy1),
                    eff_axis_pt,
                    p_font,
                    bold=True,
                    anchor="middle",
                    angle_deg=-90.0,
                    role="Y_TITLE",
                    panel_id=p.panel_id,
                )
            )

        x_ticks_txt = sorted([t for t in p.texts if t.role == "X_TICK"], key=lambda t: t.x_raw)
        xt_positions: list[tuple[float, str, int]] = []
        for xt_idx, xt in enumerate(x_ticks_txt):
            near_x = min((tk.pos_raw for tk in p.ticks if tk.axis == "x"), key=lambda v: abs(v - xt.x_raw), default=xt.x_raw)
            use_xr = near_x if abs(near_x - xt.x_raw) <= 10.0 else xt.x_raw
            xm, _ = _phi(use_xr, ry1)
            xt_positions.append((xm, xt.text, xt_idx))

        horiz_ok = True
        prev_r = -1e9
        for xm, s_lbl, xt_idx in xt_positions:
            eff_xl, eff_xp, eff_xf, eff_xb, _, _ = _resolve_item_style(
                ov, f"XT:{xt_idx}", s_lbl, eff_tick_pt, p_font, False, "#000000"
            )
            w_l, _ = measure_text_mm(eff_xl, eff_xp, bold=eff_xb, font_family=eff_xf)
            if xm - 0.5 * w_l < prev_r + 0.75:
                horiz_ok = False
                break
            prev_r = xm + 0.5 * w_l

        max_xt_bot = sy1 + tick_len_mm + 0.4
        min_dx_xt = min(
            (xt_positions[k + 1][0] - xt_positions[k][0] for k in range(len(xt_positions) - 1)),
            default=99.0,
        )
        if horiz_ok or not p.is_categorical_x:
            prev_r = -1e9
            for xm, s_lbl, xt_idx in xt_positions:
                ct = _make_styled_text(
                    ov,
                    f"XT:{xt_idx}",
                    s_lbl,
                    xm,
                    sy1 + tick_len_mm + yt_cap_h + 0.55,
                    eff_tick_pt,
                    p_font,
                    bold=False,
                    anchor="middle",
                    angle_deg=0.0,
                    role="X_TICK",
                    panel_id=p.panel_id,
                )
                if ct.bbox_mm[0] < prev_r + 0.35:
                    continue
                scene.texts.append(ct)
                prev_r = ct.bbox_mm[2]
                max_xt_bot = max(max_xt_bot, ct.bbox_mm[3])
        elif min_dx_xt >= 3.1:
            for xm, s_lbl, xt_idx in xt_positions:
                ct = _make_styled_text(
                    ov,
                    f"XT:{xt_idx}",
                    s_lbl,
                    xm + 0.25,
                    sy1 + tick_len_mm + yt_cap_h * 0.92 + 0.45,
                    eff_tick_pt,
                    p_font,
                    bold=False,
                    anchor="end",
                    angle_deg=-38.0,
                    role="X_TICK",
                    panel_id=p.panel_id,
                )
                scene.texts.append(ct)
                max_xt_bot = max(max_xt_bot, ct.bbox_mm[3])
        else:
            for xm, s_lbl, xt_idx in xt_positions:
                tov_x = ov.text_overrides.get(f"XT:{xt_idx}")
                s_short = s_lbl if (tov_x and tov_x.text) or len(s_lbl) <= 9 else s_lbl[:8] + "."
                ct = _make_styled_text(
                    ov,
                    f"XT:{xt_idx}",
                    s_short,
                    xm + 0.35 * yt_cap_h,
                    sy1 + tick_len_mm + 0.55,
                    eff_tick_pt,
                    p_font,
                    bold=False,
                    anchor="end",
                    angle_deg=-90.0,
                    role="X_TICK",
                    panel_id=p.panel_id,
                )
                scene.texts.append(ct)
                max_xt_bot = max(max_xt_bot, min(oy1 - 2.4, ct.bbox_mm[3]))

        if eff_leg_pos == "bottom":
            if p.colorbar is not None:
                bot_leg_reserve = 2.0 * ov.legend_scale + pt_to_mm(eff_tick_pt * ov.legend_scale * 1.15) + 1.8
            else:
                bot_leg_reserve = pt_to_mm(eff_tick_pt * ov.legend_scale * 1.45) + 1.5
        else:
            bot_leg_reserve = 0.0

        bottom_anchor_y = max_xt_bot
        x_titles = [t for t in p.texts if t.role == "X_TITLE"]
        if x_titles:
            at_cap = measure_text_mm("Ag", eff_axis_pt, bold=True, font_family=p_font)[1]
            xt_y = min(oy1 - 0.45 - bot_leg_reserve, max_xt_bot + at_cap + 1.05)
            ct_xt = _make_styled_text(
                ov,
                "X_TITLE",
                x_titles[0].text,
                0.5 * (sx0 + sx1),
                xt_y,
                eff_axis_pt,
                p_font,
                bold=True,
                anchor="middle",
                role="X_TITLE",
                panel_id=p.panel_id,
            )
            scene.texts.append(ct_xt)
            bottom_anchor_y = max(bottom_anchor_y, ct_xt.bbox_mm[3])

        # Colorbar (Vertical OR Horizontal!) OR Draggable / Docked Legend Box!
        if p.colorbar is not None and eff_leg_pos != "hidden":
            use_horiz_cb = (ov.legend_orient == "horizontal") or (
                ov.legend_orient == "auto" and eff_leg_pos in ("top", "bottom")
            )
            sl.effective_legend_orient = "horizontal" if use_horiz_cb else "vertical"
            cb_fpt = max(4.8, eff_tick_pt * 0.90 * ov.legend_scale)
            cb_cap_h = measure_text_mm("0", cb_fpt, bold=ov.legend_bold, font_family=lg_font)[1]
            title_w = measure_text_mm(p.colorbar.title, cb_fpt, bold=True, font_family=lg_font)[0] if p.colorbar.title else 0.0
            cb_txt_role = "INSET_LEGEND" if eff_leg_pos not in ("right", "top", "bottom") else "LEGEND"

            if use_horiz_cb:
                grad_id = f"grad-h-{p.panel_id}"
                scene.gradients.append((grad_id, p.colorbar.stops))
                cb_h = 1.95 * ov.legend_scale
                inline_title = eff_leg_pos in ("top", "bottom") and bool(p.colorbar.title) and (title_w + 14.5 <= (ox1 - ox0) - 2.0)

                if inline_title:
                    cb_w = min(22.0, max(11.5, min(0.46 * tw_sp, (ox1 - ox0) - title_w - 4.2))) * min(1.25, max(0.75, ov.legend_scale))
                    grp_w = title_w + 1.35 + cb_w
                    grp_x0 = max(ox0 + 0.8, min(ox1 - grp_w - 0.8, 0.5 * (sx0 + sx1) - 0.5 * grp_w))
                    cb_x0 = grp_x0 + title_w + 1.35
                    if eff_leg_pos == "top":
                        cb_y0 = sy0 - cb_h - cb_cap_h - 1.15
                    else:
                        cb_y0 = min(oy1 - cb_h - cb_cap_h - 0.65, bottom_anchor_y + 0.90)
                    end_pad = 0.5 * max(
                        (measure_text_mm(lbl, cb_fpt, font_family=lg_font)[0] for _, lbl in p.colorbar.ticks),
                        default=2.0,
                    )
                    sl.legend_box_mm = (
                        grp_x0 - 0.6,
                        cb_y0 - 0.55,
                        min(ox1 - 0.3, cb_x0 + cb_w + end_pad + 0.5),
                        cb_y0 + cb_h + cb_cap_h + 0.72,
                    )
                else:
                    cb_w = min(17.5, max(10.0, 0.44 * tw_sp)) * min(1.25, max(0.75, ov.legend_scale))
                    end_pad = 0.5 * max(
                        (measure_text_mm(lbl, cb_fpt, font_family=lg_font)[0] for _, lbl in p.colorbar.ticks),
                        default=2.0,
                    )
                    card_w = max(title_w, cb_w + 2.0 * end_pad) + 1.2
                    top_lbl_h = (cb_cap_h + 0.75) if p.colorbar.title else 0.3
                    card_h = top_lbl_h + cb_h + cb_cap_h + 0.95
                    if eff_leg_pos == "right":
                        card_x0 = sx1 + 1.5
                        card_y0 = sy0 + 0.5 * (th_sp - card_h)
                    elif eff_leg_pos == "top":
                        card_x0 = max(ox0 + 0.8, 0.5 * (sx0 + sx1) - 0.5 * card_w)
                        card_y0 = sy0 - card_h - 0.55
                    elif eff_leg_pos == "bottom":
                        card_x0 = max(ox0 + 0.8, 0.5 * (sx0 + sx1) - 0.5 * card_w)
                        card_y0 = min(oy1 - card_h - 0.35, bottom_anchor_y + 0.80)
                    elif eff_leg_pos == "custom":
                        use_nx, use_ny = ov.legend_xy_norm
                        card_x0 = max(ox0 + 0.6, min(ox1 - card_w - 0.5, sx0 + use_nx * tw_sp))
                        card_y0 = max(oy0 + 0.8, min(oy1 - card_h - 0.5, sy0 + use_ny * th_sp))
                    else:
                        card_x0 = max(sx0 + 0.9, sx1 - card_w - 0.9) if eff_leg_pos in ("inside_tr", "inside_br") else (sx0 + 1.0)
                        card_y0 = (sy0 + 0.9) if eff_leg_pos in ("inside_tr", "inside_tl") else max(sy0 + 1.0, sy1 - card_h - 0.9)
                    cb_x0 = card_x0 + 0.5 * (card_w - cb_w)
                    cb_y0 = card_y0 + top_lbl_h
                    sl.legend_box_mm = (card_x0 - 0.4, card_y0 - 0.4, card_x0 + card_w + 0.4, card_y0 + card_h + 0.3)

                if ov.legend_bg and eff_leg_pos not in ("right", "top", "bottom"):
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_rect_segs_mm(*sl.legend_box_mm),
                            fill="#FFFFFF",
                            fill_opacity=0.92,
                            stroke="#CBD5E1",
                            stroke_pt=0.28,
                            panel_id=p.panel_id,
                            role="LEGEND_BG",
                        )
                    )

                scene.paths.append(
                    CompiledPath(
                        segments_mm=_rect_segs_mm(cb_x0, cb_y0, cb_x0 + cb_w, cb_y0 + cb_h),
                        fill=f"url(#{grad_id})",
                        stroke="#1E293B",
                        stroke_pt=0.35,
                        panel_id=p.panel_id,
                        role="COLORBAR",
                    )
                )
                if p.colorbar.title:
                    if inline_title:
                        scene.texts.append(
                            _make_styled_text(
                                ov,
                                "CB_TITLE",
                                p.colorbar.title,
                                cb_x0 - 1.25,
                                cb_y0 + 0.5 * cb_h + 0.36 * cb_cap_h,
                                cb_fpt,
                                lg_font,
                                bold=True,
                                fill=leg_txt_col,
                                anchor="end",
                                role=cb_txt_role,
                                panel_id=p.panel_id,
                            )
                        )
                    else:
                        scene.texts.append(
                            _make_styled_text(
                                ov,
                                "CB_TITLE",
                                p.colorbar.title,
                                cb_x0 + 0.5 * cb_w,
                                cb_y0 - 0.65,
                                cb_fpt,
                                lg_font,
                                bold=True,
                                fill=leg_txt_col,
                                anchor="middle",
                                role=cb_txt_role,
                                panel_id=p.panel_id,
                            )
                        )
                for cb_idx, (t_rel, c_lbl) in enumerate(p.colorbar.ticks):
                    tx_cb = cb_x0 + t_rel * cb_w
                    scene.texts.append(
                        _make_styled_text(
                            ov,
                            f"CB_TICK:{cb_idx}",
                            c_lbl,
                            tx_cb,
                            cb_y0 + cb_h + cb_cap_h + 0.42,
                            cb_fpt,
                            lg_font,
                            bold=ov.legend_bold,
                            fill=leg_txt_col,
                            anchor="middle",
                            role=cb_txt_role,
                            panel_id=p.panel_id,
                        )
                    )
            else:
                grad_id = f"grad-{p.panel_id}"
                scene.gradients.append((grad_id, p.colorbar.stops))
                cb_w = 2.2 * ov.legend_scale
                cb_h = min(22.0, 0.58 * th_sp) * min(1.25, max(0.75, ov.legend_scale))
                max_cbt_w = max(
                    (measure_text_mm(c_lbl, cb_fpt, bold=ov.legend_bold, font_family=lg_font)[0] for _, c_lbl in p.colorbar.ticks),
                    default=4.5,
                )
                cb_tot_w = max(title_w, cb_w + 0.8 + max_cbt_w) + 0.8

                if eff_leg_pos == "right":
                    cb_x0 = sx1 + 2.4
                    cb_y0 = sy0 + 0.5 * (th_sp - cb_h) + 1.2
                elif eff_leg_pos == "custom":
                    use_nx, use_ny = ov.legend_xy_norm
                    cb_x0 = max(ox0 + 0.8, min(ox1 - cb_tot_w - 0.4, sx0 + use_nx * tw_sp))
                    cb_y0 = max(oy0 + 2.6, min(oy1 - cb_h - 0.8, sy0 + use_ny * th_sp + 1.8))
                else:
                    cb_x0 = max(sx0 + 1.0, sx1 - cb_tot_w - 1.0) if eff_leg_pos in ("inside_tr", "inside_br") else (sx0 + 1.2)
                    cb_y0 = (sy0 + pt_to_mm(cb_fpt) + 1.8) if eff_leg_pos in ("inside_tr", "inside_tl") else max(sy0 + 2.5, sy1 - cb_h - 1.2)

                sl.legend_box_mm = (cb_x0 - 0.8, cb_y0 - pt_to_mm(cb_fpt) - 1.4, cb_x0 + cb_tot_w + 0.4, cb_y0 + cb_h + 0.8)
                if ov.legend_bg and eff_leg_pos not in ("right",):
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_rect_segs_mm(*sl.legend_box_mm),
                            fill="#FFFFFF",
                            fill_opacity=0.92,
                            stroke="#CBD5E1",
                            stroke_pt=0.28,
                            panel_id=p.panel_id,
                            role="LEGEND_BG",
                        )
                    )

                scene.paths.append(
                    CompiledPath(
                        segments_mm=_rect_segs_mm(cb_x0, cb_y0, cb_x0 + cb_w, cb_y0 + cb_h),
                        fill=f"url(#{grad_id})",
                        stroke="#1E293B",
                        stroke_pt=0.35,
                        panel_id=p.panel_id,
                        role="COLORBAR",
                    )
                )
                scene.texts.append(
                    _make_styled_text(
                        ov,
                        "CB_TITLE",
                        p.colorbar.title,
                        cb_x0 - 0.3,
                        cb_y0 - 1.0,
                        cb_fpt,
                        lg_font,
                        bold=True,
                        fill=leg_txt_col,
                        anchor="start",
                        role=cb_txt_role,
                        panel_id=p.panel_id,
                    )
                )
                for cb_idx, (t_rel, c_lbl) in enumerate(p.colorbar.ticks):
                    ty_cb = cb_y0 + (1.0 - t_rel) * cb_h + 0.35 * cb_cap_h
                    scene.texts.append(
                        _make_styled_text(
                            ov,
                            f"CB_TICK:{cb_idx}",
                            c_lbl,
                            cb_x0 + cb_w + 0.75,
                            ty_cb,
                            cb_fpt,
                            lg_font,
                            bold=ov.legend_bold,
                            fill=leg_txt_col,
                            anchor="start",
                            role=cb_txt_role,
                            panel_id=p.panel_id,
                        )
                    )
        elif p.legend_entries and eff_leg_pos != "hidden":
            lg_pt = max(4.6, eff_tick_pt * 0.92 * ov.legend_scale)
            sw_sz = 1.9 * ov.legend_scale
            n_ent = len(p.legend_entries)
            if ov.legend_orient == "horizontal":
                cols_lg = n_ent
            elif ov.legend_orient == "vertical":
                cols_lg = 1
            else:
                cols_lg = n_ent if eff_leg_pos in ("top", "bottom") else max(1, min(n_ent, ov.legend_cols))
            sl.effective_legend_orient = "horizontal" if cols_lg > 1 else "vertical"
            rows_lg = math.ceil(n_ent / cols_lg)
            col_ws: list[float] = []
            max_lg_pt = lg_pt
            for ci_lg in range(cols_lg):
                mw = 6.0
                for r_l in range(rows_lg):
                    e_i = r_l * cols_lg + ci_lg
                    if e_i >= n_ent:
                        continue
                    le_cur = p.legend_entries[e_i]
                    eff_el, eff_ep, eff_ef, eff_eb, _, _ = _resolve_item_style(
                        ov, f"LEG:{e_i}", le_cur.label, lg_pt, lg_font, ov.legend_bold, leg_txt_col, swatch_hex=le_cur.color
                    )
                    max_lg_pt = max(max_lg_pt, eff_ep)
                    mw = max(mw, measure_text_mm(eff_el, eff_ep, bold=eff_eb, font_family=eff_ef)[0])
                col_ws.append(sw_sz + 0.9 + mw + 2.2)
            box_w = sum(col_ws) - 1.4
            row_pitch = pt_to_mm(max_lg_pt * 1.28)
            box_h = rows_lg * row_pitch + 0.9

            if eff_leg_pos == "right":
                lx0 = sx1 + 1.5
                ly0 = sy0 + 1.4
            elif eff_leg_pos == "top":
                lx0 = max(ox0 + 0.8, 0.5 * (sx0 + sx1) - 0.5 * box_w)
                ly0 = sy0 - box_h - 0.6
            elif eff_leg_pos == "bottom":
                lx0 = max(ox0 + 0.8, 0.5 * (sx0 + sx1) - 0.5 * box_w)
                ly0 = min(oy1 - box_h - 0.35, bottom_anchor_y + 0.85)
            elif eff_leg_pos == "custom":
                # Direct 1:1 cursor-locked placement anywhere within the panel's slot!
                use_nx, use_ny = ov.legend_xy_norm
                lx0 = max(ox0 + 0.6, min(ox1 - box_w - 0.6, sx0 + use_nx * tw_sp))
                ly0 = max(oy0 + 0.6, min(oy1 - box_h - 0.6, sy0 + use_ny * th_sp))
            else:
                if eff_leg_pos in ("inside_tr", "inside_br"):
                    lx0 = max(sx0 + 0.8, sx1 - box_w - 1.1)
                else:
                    lx0 = sx0 + 1.1
                if eff_leg_pos in ("inside_br", "inside_bl"):
                    ly0 = max(sy0 + 0.8, sy1 - box_h - 1.1)
                else:
                    ly0 = sy0 + 1.1

            sl.legend_box_mm = (lx0 - 0.6, ly0 - 0.5, lx0 + box_w + 0.6, ly0 + box_h + 0.3)

            if ov.legend_bg and eff_leg_pos not in ("right", "top", "bottom"):
                scene.paths.append(
                    CompiledPath(
                        segments_mm=_rect_segs_mm(*sl.legend_box_mm),
                        fill="#FFFFFF",
                        fill_opacity=0.92,
                        stroke="#CBD5E1",
                        stroke_pt=0.28,
                        panel_id=p.panel_id,
                        role="LEGEND_BG",
                    )
                )

            for idx_e, le in enumerate(p.legend_entries):
                r_l, c_l = divmod(idx_e, cols_lg)
                ex = lx0 + sum(col_ws[:c_l])
                ey = ly0 + (r_l + 0.82) * row_pitch
                if le.kind == "circle":
                    scene.circles.append(
                        CompiledCircle(
                            cx_mm=ex + 0.5 * sw_sz,
                            cy_mm=ey - 0.36 * row_pitch,
                            r_mm=0.48 * sw_sz,
                            fill=le.color,
                            panel_id=p.panel_id,
                            role="LEGEND_SWATCH",
                        )
                    )
                else:
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_rect_segs_mm(ex, ey - 0.68 * row_pitch, ex + sw_sz, ey - 0.04 * row_pitch),
                            fill=le.color,
                            stroke="none",
                            panel_id=p.panel_id,
                            role="LEGEND_SWATCH",
                        )
                    )
                ent_fill = _readable_swatch_text_color(le.color) if ov.legend_match_swatch else leg_txt_col
                scene.texts.append(
                    _make_styled_text(
                        ov,
                        f"LEG:{idx_e}",
                        le.label,
                        ex + sw_sz + 0.85,
                        ey,
                        lg_pt,
                        lg_font,
                        bold=ov.legend_bold,
                        fill=ent_fill,
                        anchor="start",
                        role="INSET_LEGEND" if eff_leg_pos not in ("right", "top", "bottom") else "LEGEND",
                        panel_id=p.panel_id,
                        swatch_color=le.color,
                    )
                )

        # In-Plot Annotations & Force De-Occlusion
        ann_items = [t for t in p.texts if t.role == "ANNOTATION"]
        placed_callouts: list[tuple[CompiledText, tuple[float, float] | None]] = []
        for idx_a, an in enumerate(ann_items):
            ann_key = f"ANN:{idx_a}"
            if an.target_raw is None and bracket_tops:
                bx_c, by_top = bracket_tops[min(idx_a, len(bracket_tops) - 1)]
                ct = _make_styled_text(
                    ov,
                    ann_key,
                    an.text,
                    bx_c,
                    max(sy0 + 2.2, by_top - 0.75),
                    eff_ann_pt,
                    p_font,
                    bold=an.bold,
                    fill=an.fill,
                    anchor="middle",
                    role="ANNOTATION",
                    panel_id=p.panel_id,
                )
                placed_callouts.append((ct, None))
            else:
                ax_m, ay_m = _phi(an.x_raw, an.y_raw)
                tgt_m = _phi(an.target_raw[0], an.target_raw[1]) if an.target_raw else None
                eff_al, eff_ap, eff_af, eff_ab, _, _ = _resolve_item_style(
                    ov, ann_key, an.text, eff_ann_pt, p_font, an.bold, an.fill
                )
                w_a, h_a = measure_text_mm(eff_al, eff_ap, bold=eff_ab, font_family=eff_af)
                ax_m = max(sx0 + 0.5 * w_a + 0.6, min(sx1 - 0.5 * w_a - 0.6, ax_m))
                ay_m = max(sy0 + h_a + 0.8, min(sy1 - 0.7, ay_m))
                ct = _make_styled_text(
                    ov,
                    ann_key,
                    an.text,
                    ax_m,
                    ay_m,
                    eff_ann_pt,
                    p_font,
                    bold=an.bold,
                    fill=an.fill,
                    anchor="middle",
                    role="ANNOTATION",
                    panel_id=p.panel_id,
                )
                placed_callouts.append((ct, tgt_m))

        if len(placed_callouts) >= 2:
            for _ in range(45):
                moved = False
                for i in range(len(placed_callouts)):
                    for j in range(i + 1, len(placed_callouts)):
                        ci, ti = placed_callouts[i]
                        cj, tj = placed_callouts[j]
                        bi, bj = ci.bbox_mm, cj.bbox_mm
                        ox = min(bi[2], bj[2]) - max(bi[0], bj[0]) + 0.45
                        oy = min(bi[3], bj[3]) - max(bi[1], bj[1]) + 0.35
                        if ox > 0 and oy > 0:
                            moved = True
                            dy_push = 0.55 * oy if ci.y_mm >= cj.y_mm else -0.55 * oy
                            if abs(ci.y_mm - cj.y_mm) < 0.05:
                                dy_push = 0.75
                            wi, hi = bi[2] - bi[0], bi[3] - bi[1]
                            wj, hj = bj[2] - bj[0], bj[3] - bj[1]
                            nyi = max(sy0 + hi + 0.7, min(sy1 - 0.6, ci.y_mm + dy_push))
                            nyj = max(sy0 + hj + 0.7, min(sy1 - 0.6, cj.y_mm - dy_push))
                            nxi, nxj = ci.x_mm, cj.x_mm
                            if abs(nyi - nyj) < max(hi, hj) + 0.25:
                                dx_push = 0.55 * ox if ci.x_mm >= cj.x_mm else -0.55 * ox
                                nxi = max(sx0 + 0.5 * wi + 0.6, min(sx1 - 0.5 * wi - 0.6, ci.x_mm + dx_push))
                                nxj = max(sx0 + 0.5 * wj + 0.6, min(sx1 - 0.5 * wj - 0.6, cj.x_mm - dx_push))
                            placed_callouts[i] = (
                                _make_text(
                                    ci.text,
                                    nxi,
                                    nyi,
                                    ci.font_pt,
                                    ci.font_family,
                                    ci.bold,
                                    ci.fill,
                                    ci.anchor,
                                    0.0,
                                    ci.role,
                                    ci.panel_id,
                                    italic=ci.italic,
                                    item_key=ci.item_key,
                                    orig_text=ci.orig_text,
                                ),
                                ti,
                            )
                            placed_callouts[j] = (
                                _make_text(
                                    cj.text,
                                    nxj,
                                    nyj,
                                    cj.font_pt,
                                    cj.font_family,
                                    cj.bold,
                                    cj.fill,
                                    cj.anchor,
                                    0.0,
                                    cj.role,
                                    cj.panel_id,
                                    italic=cj.italic,
                                    item_key=cj.item_key,
                                    orig_text=cj.orig_text,
                                ),
                                tj,
                            )
                if not moved:
                    break

        for ct, tgt_m in placed_callouts:
            scene.texts.append(ct)
            if tgt_m is not None:
                bb = ct.bbox_mm
                end_x = max(bb[0], min(bb[2], tgt_m[0]))
                end_y = bb[1] - 0.15 if tgt_m[1] < bb[1] else (bb[3] + 0.15 if tgt_m[1] > bb[3] else 0.5 * (bb[1] + bb[3]))
                if math.hypot(end_x - tgt_m[0], end_y - tgt_m[1]) > 0.7:
                    scene.paths.append(
                        CompiledPath(
                            segments_mm=_line_segs_mm(tgt_m[0], tgt_m[1], end_x, end_y),
                            stroke="#475569",
                            stroke_pt=0.32 * ov.stroke_scale,
                            clip_id=clip_id,
                            panel_id=p.panel_id,
                            role="LEADER",
                        )
                    )

    return scene


def render_naive_uniform_svg(panels: list[PanelIR], cfg: TypographyConfig) -> tuple[str, dict[str, float]]:
    """Render traditional Naive Uniform-Scaling Grid to expose real-world scaling & misalignment flaws."""
    spec = _resolve_spec(cfg)
    n = len(panels)
    cols = 1 if spec.width_mm < 72 else (2 if spec.width_mm <= 102 else (3 if spec.width_mm <= 148 or n < 10 else 4))
    rows = max(1, math.ceil(n / cols))
    w_mm = spec.width_mm
    pad = 3.5
    gap = 3.0
    cell_w = (w_mm - 2 * pad - (cols - 1) * gap) / cols
    cell_h = cell_w * 0.88
    h_mm = 2 * pad + rows * cell_h + (rows - 1) * gap

    min_pt_seen = 999.0
    max_pt_seen = 0.0
    min_sw_seen = 999.0
    max_sw_seen = 0.0

    K = 96.0 / 25.4
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w_mm * K:.2f} {h_mm * K:.2f}" width="{w_mm * K:.2f}" height="{h_mm * K:.2f}">',
        f'  <rect x="0" y="0" width="{w_mm * K:.2f}" height="{h_mm * K:.2f}" fill="#FFFFFF"/>',
    ]

    for idx, p in enumerate(panels):
        r, c = divmod(idx, cols)
        ox = pad + c * (cell_w + gap)
        oy = pad + r * (cell_h + gap)
        vx, vy, vw, vh = p.viewbox
        s = min(cell_w / max(1e-6, vw), cell_h / max(1e-6, vh))
        dx = ox + 0.5 * (cell_w - vw * s) - vx * s
        dy = oy + 0.5 * (cell_h - vh * s) - vy * s

        for t in p.texts:
            eff_pt = t.raw_font_px * s * (72.0 / 25.4)
            min_pt_seen = min(min_pt_seen, eff_pt)
            max_pt_seen = max(max_pt_seen, eff_pt)
        for sh in p.shapes:
            if sh.stroke not in ("none", "transparent") and sh.raw_stroke_width > 0:
                eff_sw = sh.raw_stroke_width * s * (72.0 / 25.4)
                min_sw_seen = min(min_sw_seen, eff_sw)
                max_sw_seen = max(max_sw_seen, eff_sw)

        parts.append(
            f'  <rect x="{ox * K:.2f}" y="{oy * K:.2f}" width="{cell_w * K:.2f}" height="{cell_h * K:.2f}" '
            f'fill="none" stroke="#FCA5A5" stroke-width="{0.22 * K:.2f}" stroke-dasharray="{1.2 * K:.1f},{0.8 * K:.1f}"/>'
        )
        inner = _strip_outer_svg(p.raw_svg_bytes)
        inner = inner.replace('id="', f'id="naive-{p.panel_id}-').replace("url(#", f"url(#naive-{p.panel_id}-")
        parts.append(f'  <g transform="translate({dx * K:.3f},{dy * K:.3f}) scale({s * K:.5f})">{inner}</g>')

    parts.append("</svg>")
    stats_naive = {
        "min_font_pt": round(min_pt_seen if min_pt_seen < 900 else 0.0, 2),
        "max_font_pt": round(max_pt_seen, 2),
        "min_stroke_pt": round(min_sw_seen if min_sw_seen < 900 else 0.0, 2),
        "max_stroke_pt": round(max_sw_seen, 2),
    }
    return "\n".join(parts), stats_naive
