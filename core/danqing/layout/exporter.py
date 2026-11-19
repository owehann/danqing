"""Multi-format Exporters: Layered Editable SVG, Native Vector PDF 1.7, High-DPI PNG, and Mode B R/Python Slot Lockfile."""

from __future__ import annotations

import base64
import io
import json
import math
from xml.sax.saxutils import escape

import numpy as np
import pikepdf
from PIL import Image
import resvg_py

from .ir import CompositePageScene, PathSegment
from .specs import FONT_FAMILIES, JOURNAL_SPECS, MM_TO_PT, measure_text_mm, mm_to_pt, pt_to_mm


def _segs_to_svg_d(segs: list[PathSegment], scale: float = 1.0) -> str:
    out: list[str] = []
    for s in segs:
        if s.op in ("M", "L"):
            out.append(f"{s.op} {s.pts[0] * scale:.2f} {s.pts[1] * scale:.2f}")
        elif s.op == "C":
            out.append(
                f"C {s.pts[0] * scale:.2f} {s.pts[1] * scale:.2f} {s.pts[2] * scale:.2f} "
                f"{s.pts[3] * scale:.2f} {s.pts[4] * scale:.2f} {s.pts[5] * scale:.2f}"
            )
        elif s.op == "Z":
            out.append("Z")
    return " ".join(out)


def render_scene_svg(scene: CompositePageScene, show_guides: bool = False) -> str:
    """Render CompositePageScene to clean, Illustrator- & Danqing-ready layered SVG in standard 96-DPI CSS pixels."""
    K = 96.0 / 25.4
    w_mm, h_mm = scene.width_mm, scene.height_mm
    px_w = w_mm * K
    px_h = h_mm * K
    css_font = FONT_FAMILIES.get(scene.font_family, "Arial, Helvetica, sans-serif")

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {px_w:.2f} {px_h:.2f}" width="{px_w:.2f}" height="{px_h:.2f}" data-width-mm="{w_mm:.2f}" data-height-mm="{h_mm:.2f}">',
        "  <defs>",
    ]
    for cid, (cx0, cy0, cx1, cy1) in scene.clips_mm.items():
        lines.append(
            f'    <clipPath id="{cid}"><rect x="{cx0 * K:.2f}" y="{cy0 * K:.2f}" width="{(cx1 - cx0) * K:.2f}" height="{(cy1 - cy0) * K:.2f}"/></clipPath>'
        )
    for gid, stops in scene.gradients:
        if gid.startswith("grad-h-"):
            lines.append(f'    <linearGradient id="{gid}" x1="0%" y1="0%" x2="100%" y2="0%">')
        else:
            lines.append(f'    <linearGradient id="{gid}" x1="0%" y1="100%" x2="0%" y2="0%">')
        for off, col in stops:
            lines.append(f'      <stop offset="{off * 100:.1f}%" stop-color="{col}"/>')
        lines.append("    </linearGradient>")
    lines.append("  </defs>")

    lines.append(f'  <rect id="page-canvas" x="0" y="0" width="{px_w:.2f}" height="{px_h:.2f}" fill="#FFFFFF"/>')

    # Optional Modular Bento Outer Slots & Spine Alignment Rails Overlay
    if show_guides:
        lines.append('  <g id="modular-alignment-guides" opacity="0.88">')
        for sl in scene.slots:
            ox0, oy0, ox1, oy1 = sl.outer_box_mm
            sx0, sy0, sx1, sy1 = sl.spine_box_mm
            lines.append(
                f'    <rect x="{ox0 * K:.2f}" y="{oy0 * K:.2f}" width="{(ox1 - ox0) * K:.2f}" height="{(oy1 - oy0) * K:.2f}" '
                f'fill="none" stroke="#CBD5E1" stroke-width="{0.16 * K:.2f}" stroke-dasharray="{1.0 * K:.1f},{0.8 * K:.1f}"/>'
            )
            guide_col = "#B45309" if sl.locked_special else "#0F766E"
            lines.append(
                f'    <rect x="{sx0 * K:.2f}" y="{sy0 * K:.2f}" width="{(sx1 - sx0) * K:.2f}" height="{(sy1 - sy0) * K:.2f}" '
                f'fill="none" stroke="{guide_col}" stroke-width="{0.24 * K:.2f}" stroke-dasharray="{0.9 * K:.1f},{0.6 * K:.1f}"/>'
            )
            if not sl.locked_special:
                lines.append(
                    f'    <line x1="{2 * K:.1f}" y1="{sy1 * K:.2f}" x2="{(w_mm - 2) * K:.2f}" y2="{sy1 * K:.2f}" '
                    f'stroke="#0F766E" stroke-opacity="0.32" stroke-width="{0.15 * K:.2f}" stroke-dasharray="{0.8 * K:.1f},{0.8 * K:.1f}"/>'
                )
                lines.append(
                    f'    <line x1="{sx0 * K:.2f}" y1="{2 * K:.1f}" x2="{sx0 * K:.2f}" y2="{(h_mm - 2) * K:.2f}" '
                    f'stroke="#2563EB" stroke-opacity="0.25" stroke-width="{0.15 * K:.2f}" stroke-dasharray="{0.8 * K:.1f},{0.8 * K:.1f}"/>'
                )
        lines.append("  </g>")

    slot_by_id = {sl.panel_id: sl for sl in scene.slots}
    panel_ids = ["SHARED"] + [sl.panel_id for sl in scene.slots]
    for pid in panel_ids:
        p_rasters = [r for r in scene.rasters if r.panel_id == pid]
        p_lsvgs = [ls for ls in scene.locked_svgs if ls.panel_id == pid]
        p_paths = [pt_item for pt_item in scene.paths if (pt_item.panel_id or "SHARED") == pid]
        p_circs = [c for c in scene.circles if (c.panel_id or "SHARED") == pid]
        p_txts = [t for t in scene.texts if (t.panel_id or "SHARED") == pid]
        if not (p_rasters or p_lsvgs or p_paths or p_circs or p_txts):
            continue

        if pid in slot_by_id:
            sl_m = slot_by_id[pid]
            ox0, oy0, ox1, oy1 = sl_m.outer_box_mm
            p_attr = (
                f' data-danqing-panel="Panel {sl_m.tag_label}" '
                f'data-panel-bbox="{ox0 * K:.2f},{oy0 * K:.2f},{ox1 * K:.2f},{oy1 * K:.2f}"'
            )
        else:
            p_attr = ""
        lines.append(f'  <g id="layer-{pid}"{p_attr}>')
        for r in p_rasters:
            b64 = base64.b64encode(r.png_bytes).decode("ascii")
            lines.append(
                f'    <image x="{r.x_mm * K:.2f}" y="{r.y_mm * K:.2f}" width="{r.w_mm * K:.2f}" height="{r.h_mm * K:.2f}" '
                f'preserveAspectRatio="none" href="data:image/png;base64,{b64}"/>'
            )
        for ls in p_lsvgs:
            vx, vy, _, _ = ls.raw_vb
            inner_ns = ls.svg_inner_xml.replace('id="', f'id="lk-{pid}-').replace("url(#", f"url(#lk-{pid}-")
            sc_px = ls.scale_isotropic * K
            tx_l = ls.x_mm * K - vx * sc_px
            ty_l = ls.y_mm * K - vy * sc_px
            lines.append(
                f'    <g transform="translate({tx_l:.3f},{ty_l:.3f}) scale({sc_px:.5f})">{inner_ns}</g>'
            )
        def _emit_path(cp_item) -> str:
            d = _segs_to_svg_d(cp_item.segments_mm, scale=K)
            sw_px = pt_to_mm(cp_item.stroke_pt) * K
            clip_attr = f' clip-path="url(#{cp_item.clip_id})"' if cp_item.clip_id else ""
            if cp_item.dasharray_mm:
                d_px = ",".join(f"{float(v) * K:.2f}" for v in cp_item.dasharray_mm.split(","))
                dash_attr = f' stroke-dasharray="{d_px}"'
            else:
                dash_attr = ""
            fop_attr = f' fill-opacity="{cp_item.fill_opacity:.3f}"' if cp_item.fill_opacity < 0.999 else ""
            sop_attr = f' stroke-opacity="{cp_item.stroke_opacity:.3f}"' if cp_item.stroke_opacity < 0.999 else ""
            return (
                f'    <path d="{d}" fill="{cp_item.fill}"{fop_attr} stroke="{cp_item.stroke}"{sop_attr} '
                f'stroke-width="{sw_px:.3f}" stroke-linecap="butt" stroke-linejoin="miter"{dash_attr}{clip_attr}/>'
            )

        def _emit_circle(cc_item) -> str:
            clip_attr = f' clip-path="url(#{cc_item.clip_id})"' if cc_item.clip_id else ""
            sw_px = pt_to_mm(cc_item.stroke_pt) * K if cc_item.stroke not in ("none", "transparent") else 0.0
            st_attr = f' stroke="{cc_item.stroke}" stroke-width="{sw_px:.3f}"' if sw_px > 0 else ""
            return (
                f'    <circle cx="{cc_item.cx_mm * K:.2f}" cy="{cc_item.cy_mm * K:.2f}" r="{cc_item.r_mm * K:.2f}" '
                f'fill="{cc_item.fill}" fill-opacity="{cc_item.fill_opacity:.3f}"{st_attr}{clip_attr}/>'
            )

        def _emit_text(ct_item) -> str:
            fs_px = pt_to_mm(ct_item.font_pt) * K
            fw = "bold" if ct_item.bold else "normal"
            fst = ' font-style="italic"' if getattr(ct_item, "italic", False) else ""
            ikey = f' data-item-key="{escape(ct_item.item_key)}"' if getattr(ct_item, "item_key", "") else ""
            item_font = FONT_FAMILIES.get(ct_item.font_family, css_font)
            tf_attr = (
                f' transform="rotate({ct_item.angle_deg:.1f} {ct_item.x_mm * K:.2f} {ct_item.y_mm * K:.2f})"'
                if abs(ct_item.angle_deg) > 0.1
                else ""
            )
            return (
                f'    <text x="{ct_item.x_mm * K:.2f}" y="{ct_item.y_mm * K:.2f}" text-anchor="{ct_item.anchor}" '
                f'font-family="{escape(item_font)}" font-size="{fs_px:.3f}" font-weight="{fw}"{fst} '
                f'fill="{ct_item.fill}"{ikey}{tf_attr}>{escape(ct_item.text)}</text>'
            )

        leg_roles = {"LEGEND_BG", "LEGEND_SWATCH", "COLORBAR"}
        leg_txt_roles = {"LEGEND", "INSET_LEGEND"}
        main_paths = [cp for cp in p_paths if cp.role not in leg_roles]
        leg_paths = sorted(
            [cp for cp in p_paths if cp.role in leg_roles],
            key=lambda cp: 0 if cp.role == "LEGEND_BG" else 1,
        )
        main_circs = [cc for cc in p_circs if getattr(cc, "role", "MARKER") != "LEGEND_SWATCH"]
        leg_circs = [cc for cc in p_circs if getattr(cc, "role", "MARKER") == "LEGEND_SWATCH"]
        main_txts = [ct for ct in p_txts if ct.role not in leg_txt_roles]
        leg_txts = [ct for ct in p_txts if ct.role in leg_txt_roles]

        for cp in main_paths:
            lines.append(_emit_path(cp))
        for cc in main_circs:
            lines.append(_emit_circle(cc))
        for ct in main_txts:
            lines.append(_emit_text(ct))

        if leg_paths or leg_circs or leg_txts:
            lines.append(f'    <g id="legend-layer-{pid}" data-legend-panel="{pid}">')
            for cp in leg_paths:
                lines.append("  " + _emit_path(cp))
            for cc in leg_circs:
                lines.append("  " + _emit_circle(cc))
            for ct in leg_txts:
                lines.append("  " + _emit_text(ct))
            lines.append("    </g>")
        lines.append("  </g>")

    lines.append("</svg>")
    return "\n".join(lines)


def render_svg_to_png(svg_str: str, dpi: int = 300, width_mm: float = 183.0) -> bytes:
    """Rasterize physical-mm SVG at exact target DPI using resvg."""
    target_w_px = max(400, int(round((width_mm / 25.4) * dpi)))
    return resvg_py.svg_to_bytes(svg_string=svg_str, width=target_w_px, background="#FFFFFF")


def _hex_to_rgb01(col: str) -> tuple[float, float, float] | None:
    if not col or col in ("none", "transparent") or col.startswith("url("):
        return None
    h = col.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        try:
            return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
        except ValueError:
            return (0.0, 0.0, 0.0)
    return (0.0, 0.0, 0.0)


def _escape_pdf_bytes(s: str) -> str:
    raw = s.encode("cp1252", errors="replace")
    out: list[str] = []
    for b in raw:
        ch = chr(b)
        if ch in ("(", ")", "\\"):
            out.append("\\" + ch)
        elif 32 <= b <= 126:
            out.append(ch)
        else:
            out.append(f"\\{b:03o}")
    return "".join(out)


def render_scene_pdf(scene: CompositePageScene) -> bytes:
    """Compile CompositePageScene into a true Print-Ready Vector PDF 1.7 with exact physical `pt` coordinates & lossless XObjects."""
    pdf = pikepdf.Pdf.new()
    W_pt = scene.width_mm * MM_TO_PT
    H_pt = scene.height_mm * MM_TO_PT

    def py(y_mm: float) -> float:
        return H_pt - y_mm * MM_TO_PT

    def px(x_mm: float) -> float:
        return x_mm * MM_TO_PT

    def _type1(base_name: str):
        return pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type1"),
                BaseFont=pikepdf.Name(base_name),
                Encoding=pikepdf.Name("/WinAnsiEncoding"),
            )
        )

    f_sans_reg = _type1("/Helvetica")
    f_sans_bold = _type1("/Helvetica-Bold")
    f_sans_ital = _type1("/Helvetica-Oblique")
    f_sans_bi = _type1("/Helvetica-BoldOblique")
    f_serif_reg = _type1("/Times-Roman")
    f_serif_bold = _type1("/Times-Bold")
    f_serif_ital = _type1("/Times-Italic")
    f_serif_bi = _type1("/Times-BoldItalic")

    xobjects = pikepdf.Dictionary()
    ext_gstates = pikepdf.Dictionary()
    alpha_cache: dict[tuple[int, int], str] = {}

    def _gs_name(fill_op: float, stroke_op: float) -> str:
        key = (int(round(fill_op * 100)), int(round(stroke_op * 100)))
        if key not in alpha_cache:
            gname = f"GS{len(alpha_cache) + 1}"
            ext_gstates[f"/{gname}"] = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/ExtGState"),
                    ca=round(fill_op, 3),
                    CA=round(stroke_op, 3),
                )
            )
            alpha_cache[key] = gname
        return alpha_cache[key]

    cmds: list[str] = [f"1 1 1 rg 0 0 {W_pt:.2f} {H_pt:.2f} re f"]

    # 1. Lossless Raster Evidence XObjects (Gate L0 bit-identical RGB stream)
    for idx, r in enumerate(scene.rasters):
        with Image.open(io.BytesIO(r.png_bytes)) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
        st = pdf.make_stream(arr.tobytes())
        st["/Type"] = pikepdf.Name("/XObject")
        st["/Subtype"] = pikepdf.Name("/Image")
        st["/Width"] = r.width_px
        st["/Height"] = r.height_px
        st["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
        st["/BitsPerComponent"] = 8
        im_key = f"Im{idx + 1}"
        xobjects[f"/{im_key}"] = st
        w_p = r.w_mm * MM_TO_PT
        h_p = r.h_mm * MM_TO_PT
        x_p = px(r.x_mm)
        y_p = py(r.y_mm + r.h_mm)
        cmds.append(f"q {w_p:.3f} 0 0 {h_p:.3f} {x_p:.3f} {y_p:.3f} cm /{im_key} Do Q")

    # 2. Locked Special Schematics (rendered as high-resolution 600 DPI lossless XObject if present)
    for idx, ls in enumerate(scene.locked_svgs):
        vx, vy, vw, vh = ls.raw_vb
        sub_svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx} {vy} {vw} {vh}" '
            f'width="{ls.w_mm * (96.0 / 25.4):.2f}" height="{ls.h_mm * (96.0 / 25.4):.2f}">{ls.svg_inner_xml}</svg>'
        )
        png_sub = render_svg_to_png(sub_svg, dpi=600, width_mm=ls.w_mm)
        with Image.open(io.BytesIO(png_sub)) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
            sw_px, sh_px = im.size
        st = pdf.make_stream(arr.tobytes())
        st["/Type"] = pikepdf.Name("/XObject")
        st["/Subtype"] = pikepdf.Name("/Image")
        st["/Width"] = sw_px
        st["/Height"] = sh_px
        st["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
        st["/BitsPerComponent"] = 8
        im_key = f"ImSpec{idx + 1}"
        xobjects[f"/{im_key}"] = st
        w_p = ls.w_mm * MM_TO_PT
        h_p = ls.h_mm * MM_TO_PT
        cmds.append(f"q {w_p:.3f} 0 0 {h_p:.3f} {px(ls.x_mm):.3f} {py(ls.y_mm + ls.h_mm):.3f} cm /{im_key} Do Q")

    # Gradient map lookup for Colorbar rects
    grad_dict = dict(scene.gradients)

    # 3. Vector Paths (exact `pt` strokes, clips, dashes)
    for cp in scene.paths:
        if cp.fill.startswith("url(#"):
            gid = cp.fill[5:-1]
            stops = grad_dict.get(gid, [(0.0, "#2E6F95"), (0.5, "#F4EFE6"), (1.0, "#C6593F")])
            xs_g = [s.pts[0] for s in cp.segments_mm if s.pts]
            ys_g = [s.pts[1] for s in cp.segments_mm if s.pts]
            if xs_g and ys_g:
                gx0, gx1 = min(xs_g), max(xs_g)
                gy0, gy1 = min(ys_g), max(ys_g)
                is_horiz_grad = gid.startswith("grad-h-")
                n_strip = 32
                for si in range(n_strip):
                    t_v = (si + 0.5) / n_strip
                    c_hex = stops[-1][1]
                    for k_s in range(len(stops) - 1):
                        if stops[k_s][0] <= t_v <= stops[k_s + 1][0]:
                            c_hex = stops[k_s][1] if (t_v - stops[k_s][0]) < 0.5 * (stops[k_s + 1][0] - stops[k_s][0]) else stops[k_s + 1][1]
                            break
                    rgb = _hex_to_rgb01(c_hex) or (0.5, 0.5, 0.5)
                    if is_horiz_grad:
                        sx_l = gx0 + (si / n_strip) * (gx1 - gx0)
                        sw_m = (gx1 - gx0) / n_strip + 0.05
                        cmds.append(
                            f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg "
                            f"{px(sx_l):.3f} {py(gy1):.3f} {sw_m * MM_TO_PT:.3f} {(gy1 - gy0) * MM_TO_PT:.3f} re f"
                        )
                    else:
                        sy_bot = gy1 - (si + 1) / n_strip * (gy1 - gy0)
                        sh_m = (gy1 - gy0) / n_strip + 0.05
                        cmds.append(
                            f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg "
                            f"{px(gx0):.3f} {py(sy_bot + sh_m):.3f} {(gx1 - gx0) * MM_TO_PT:.3f} {sh_m * MM_TO_PT:.3f} re f"
                        )
            if cp.stroke in ("none", "transparent"):
                continue

        f_rgb = _hex_to_rgb01(cp.fill)
        s_rgb = _hex_to_rgb01(cp.stroke) if cp.stroke_pt > 0 else None
        if f_rgb is None and s_rgb is None:
            continue

        cmds.append("q")
        if cp.clip_id and cp.clip_id in scene.clips_mm:
            cx0, cy0, cx1, cy1 = scene.clips_mm[cp.clip_id]
            cmds.append(f"{px(cx0):.3f} {py(cy1):.3f} {(cx1 - cx0) * MM_TO_PT:.3f} {(cy1 - cy0) * MM_TO_PT:.3f} re W n")
        gs = _gs_name(cp.fill_opacity, cp.stroke_opacity)
        cmds.append(f"/{gs} gs")
        if f_rgb is not None:
            cmds.append(f"{f_rgb[0]:.4f} {f_rgb[1]:.4f} {f_rgb[2]:.4f} rg")
        if s_rgb is not None:
            cmds.append(f"{s_rgb[0]:.4f} {s_rgb[1]:.4f} {s_rgb[2]:.4f} RG {cp.stroke_pt:.3f} w")
            if cp.dasharray_mm:
                d_nums = [float(x) * MM_TO_PT for x in cp.dasharray_mm.split(",")]
                cmds.append(f"[{' '.join(f'{v:.2f}' for v in d_nums)}] 0 d")
            else:
                cmds.append("[] 0 d")

        p_ops: list[str] = []
        for s in cp.segments_mm:
            if s.op == "M":
                p_ops.append(f"{px(s.pts[0]):.3f} {py(s.pts[1]):.3f} m")
            elif s.op == "L":
                p_ops.append(f"{px(s.pts[0]):.3f} {py(s.pts[1]):.3f} l")
            elif s.op == "C":
                p_ops.append(
                    f"{px(s.pts[0]):.3f} {py(s.pts[1]):.3f} {px(s.pts[2]):.3f} {py(s.pts[3]):.3f} "
                    f"{px(s.pts[4]):.3f} {py(s.pts[5]):.3f} c"
                )
            elif s.op == "Z":
                p_ops.append("h")

        paint_op = "B" if (f_rgb is not None and s_rgb is not None) else ("f" if f_rgb is not None else "S")
        cmds.append(" ".join(p_ops) + f" {paint_op} Q")

    # 4. Isotropic Vector Circles (`eccentricity == 0.000` cubic Bézier circles in PDF points)
    kappa = 0.55228475
    for cc in scene.circles:
        f_rgb = _hex_to_rgb01(cc.fill)
        s_rgb = _hex_to_rgb01(cc.stroke) if cc.stroke_pt > 0 else None
        if f_rgb is None and s_rgb is None:
            continue
        cmds.append("q")
        if cc.clip_id and cc.clip_id in scene.clips_mm:
            cx0, cy0, cx1, cy1 = scene.clips_mm[cc.clip_id]
            cmds.append(f"{px(cx0):.3f} {py(cy1):.3f} {(cx1 - cx0) * MM_TO_PT:.3f} {(cy1 - cy0) * MM_TO_PT:.3f} re W n")
        gs = _gs_name(cc.fill_opacity, 1.0)
        cmds.append(f"/{gs} gs")
        if f_rgb is not None:
            cmds.append(f"{f_rgb[0]:.4f} {f_rgb[1]:.4f} {f_rgb[2]:.4f} rg")
        if s_rgb is not None:
            cmds.append(f"{s_rgb[0]:.4f} {s_rgb[1]:.4f} {s_rgb[2]:.4f} RG {cc.stroke_pt:.3f} w")
        cx_p, cy_p, r_p = px(cc.cx_mm), py(cc.cy_mm), cc.r_mm * MM_TO_PT
        kp = kappa * r_p
        c_path = (
            f"{cx_p + r_p:.3f} {cy_p:.3f} m "
            f"{cx_p + r_p:.3f} {cy_p + kp:.3f} {cx_p + kp:.3f} {cy_p + r_p:.3f} {cx_p:.3f} {cy_p + r_p:.3f} c "
            f"{cx_p - kp:.3f} {cy_p + r_p:.3f} {cx_p - r_p:.3f} {cy_p + kp:.3f} {cx_p - r_p:.3f} {cy_p:.3f} c "
            f"{cx_p - r_p:.3f} {cy_p - kp:.3f} {cx_p - kp:.3f} {cy_p - r_p:.3f} {cx_p:.3f} {cy_p - r_p:.3f} c "
            f"{cx_p + kp:.3f} {cy_p - r_p:.3f} {cx_p + r_p:.3f} {cy_p - kp:.3f} {cx_p + r_p:.3f} {cy_p:.3f} c h"
        )
        paint_op = "B" if (f_rgb is not None and s_rgb is not None) else ("f" if f_rgb is not None else "S")
        cmds.append(f"{c_path} {paint_op} Q")

    # 5. Live Vector Typography (`BT /F1 <pt> Tf ... Tj ET`)
    gs_solid = _gs_name(1.0, 1.0)
    for ct in scene.texts:
        rgb = _hex_to_rgb01(ct.fill) or (0.0, 0.0, 0.0)
        eff_fam = ct.font_family or scene.font_family
        w_mm_est, _ = measure_text_mm(ct.text, ct.font_pt, bold=ct.bold, font_family=eff_fam)
        shift_mm = -0.5 * w_mm_est if ct.anchor == "middle" else (-w_mm_est if ct.anchor == "end" else 0.0)
        # In PDF, y increases upward, so SVG `rotate(angle_deg)` corresponds to `-angle_deg` in PDF CCW coordinates!
        pdf_rad = math.radians(-ct.angle_deg)
        ca, sa = math.cos(pdf_rad), math.sin(pdf_rad)
        ax_p = px(ct.x_mm) + (shift_mm * MM_TO_PT) * ca
        ay_p = py(ct.y_mm) + (shift_mm * MM_TO_PT) * sa
        is_serif = "Times" in eff_fam
        is_ital = bool(getattr(ct, "italic", False))
        if is_serif:
            f_ref = ("/F8" if ct.bold else "/F7") if is_ital else ("/F4" if ct.bold else "/F3")
        else:
            f_ref = ("/F6" if ct.bold else "/F5") if is_ital else ("/F2" if ct.bold else "/F1")
        esc_txt = _escape_pdf_bytes(ct.text)
        cmds.append(
            f"q /{gs_solid} gs BT {f_ref} {ct.font_pt:.2f} Tf {rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg "
            f"{ca:.5f} {sa:.5f} {-sa:.5f} {ca:.5f} {ax_p:.3f} {ay_p:.3f} Tm ({esc_txt}) Tj ET Q"
        )

    resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=f_sans_reg,
            F2=f_sans_bold,
            F3=f_serif_reg,
            F4=f_serif_bold,
            F5=f_sans_ital,
            F6=f_sans_bi,
            F7=f_serif_ital,
            F8=f_serif_bi,
        ),
        XObject=xobjects,
        ExtGState=ext_gstates,
    )
    page_dict = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, round(W_pt, 3), round(H_pt, 3)]),
        Resources=resources,
        Contents=pdf.make_stream("\n".join(cmds).encode("latin1")),
    )
    pdf.pages.append(pikepdf.Page(page_dict))
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def build_mode_b_slot_contract(scene: CompositePageScene) -> dict[str, object]:
    """Export Mode B Upstream 1.000x Physical-Millimeter Slot Lockfile + R ggplot2 & Python matplotlib helpers."""
    spec = JOURNAL_SPECS.get(scene.journal_id, JOURNAL_SPECS["nature_double"])
    slots_json = []
    for sl in scene.slots:
        ox0, oy0, ox1, oy1 = sl.outer_box_mm
        sx0, sy0, sx1, sy1 = sl.spine_box_mm
        slots_json.append(
            {
                "tag": sl.tag_label,
                "panel_id": sl.panel_id,
                "locked_special": sl.locked_special,
                "outer_width_mm": round(ox1 - ox0, 2),
                "outer_height_mm": round(oy1 - oy0, 2),
                "spine_width_mm": round(sx1 - sx0, 2),
                "spine_height_mm": round(sy1 - sy0, 2),
                "outer_box_mm": [round(v, 2) for v in sl.outer_box_mm],
                "spine_box_mm": [round(v, 2) for v in sl.spine_box_mm],
            }
        )

    s0 = slots_json[0] if slots_json else {"tag": "a", "outer_width_mm": 45.0, "outer_height_mm": 40.0}
    r_snippet = f"""# Mode B · R (ggplot2) 1.000× Native Slot Renderer (Zero Post-Hoc Rescaling!)
library(ggplot2)
library(jsonlite)

jianjia_ggsave <- function(plot, lockfile = "figure_layout.lock.json", tag = "{s0['tag']}", out_pdf = paste0("panel_", tag, ".pdf")) {{
  lk <- fromJSON(lockfile)
  sl <- lk$slots[lk$slots$tag == tag, ][1, ]
  p_styled <- plot + theme_classic(base_size = {spec.tick_pt}, base_family = "{scene.font_family}") +
    theme(
      plot.title = element_text(size = {spec.title_pt}, face = "bold", colour = "#000000"),
      plot.subtitle = element_blank(),
      axis.title = element_text(size = {spec.axis_title_pt}, face = "bold", colour = "#000000"),
      axis.text = element_text(size = {spec.tick_pt}, colour = "#000000"),
      axis.line = element_line(linewidth = {spec.axis_stroke_pt / 2.13:.3f}, colour = "#000000"),
      axis.ticks = element_line(linewidth = {spec.axis_stroke_pt / 2.13:.3f}, colour = "#000000")
    )
  ggsave(out_pdf, p_styled, width = sl$outer_width_mm, height = sl$outer_height_mm, units = "mm", device = cairo_pdf)
}}"""

    py_snippet = f"""# Mode B · Python (matplotlib) 1.000× Native Slot Context (Zero Post-Hoc Rescaling!)
import json, matplotlib as mpl, matplotlib.pyplot as plt

def jianjia_figure(lockfile="figure_layout.lock.json", tag="{s0['tag']}"):
    lk = json.load(open(lockfile, "r", encoding="utf-8"))
    sl = next(s for s in lk["slots"] if s["tag"] == tag)
    mpl.rcParams.update({{
        "pdf.fonttype": 42, "svg.fonttype": "none",
        "font.family": "sans-serif", "font.sans-serif": ["{scene.font_family}", "Arial", "Helvetica"],
        "font.size": {spec.tick_pt}, "axes.titlesize": {spec.title_pt}, "axes.labelsize": {spec.axis_title_pt},
        "xtick.labelsize": {spec.tick_pt}, "ytick.labelsize": {spec.tick_pt},
        "axes.linewidth": {spec.axis_stroke_pt}, "lines.linewidth": {spec.data_stroke_pt},
    }})
    return plt.subplots(figsize=(sl["outer_width_mm"] / 25.4, sl["outer_height_mm"] / 25.4))"""

    return {
        "schema": "jianjia.layout.lock/v1",
        "journal_id": scene.journal_id,
        "page_width_mm": round(scene.width_mm, 2),
        "page_height_mm": round(scene.height_mm, 2),
        "font_family": scene.font_family,
        "typography_pt": {
            "tag_pt": spec.tag_pt,
            "title_pt": spec.title_pt,
            "axis_title_pt": spec.axis_title_pt,
            "tick_pt": spec.tick_pt,
            "axis_stroke_pt": spec.axis_stroke_pt,
        },
        "slots": slots_json,
        "r_snippet": r_snippet,
        "python_snippet": py_snippet,
    }
