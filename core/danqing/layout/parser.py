"""Semantic Vector & Evidence Decomposer (SVG with <style>/<use>, Vector PDF, and Raster inputs -> PanelIR)."""

from __future__ import annotations

import base64
from decimal import Decimal
import hashlib
import io
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pikepdf
import pypdfium2 as pdfium
from PIL import Image

from .ir import (
    ColorbarSpec,
    DataMarker,
    DataShape,
    ElasticityClass,
    LegendEntry,
    PanelIR,
    PathSegment,
    RasterEvidence,
    ROIOverlaySpec,
    TextItem,
    TextRole,
    TickMark,
)

_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TOKEN_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)")
_CSS_RULE_RE = re.compile(r"([^{}@]+)\{([^{}]*)\}")


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _is_numeric_label(s: str) -> bool:
    cleaned = s.strip().replace(",", "").replace("%", "").replace("−", "-")
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _mat_mul(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float, float, float, float]:
    return (
        a[0] * b[0] + a[2] * b[1],
        a[1] * b[0] + a[3] * b[1],
        a[0] * b[2] + a[2] * b[3],
        a[1] * b[2] + a[3] * b[3],
        a[0] * b[4] + a[2] * b[5] + a[4],
        a[1] * b[4] + a[3] * b[5] + a[5],
    )


def _apply_mat(m: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _parse_transform(attr: str | None) -> tuple[tuple[float, float, float, float, float, float], float]:
    cur = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    rot_deg = 0.0
    if not attr:
        return cur, rot_deg
    for kind, body in _TRANSFORM_RE.findall(attr):
        nums = [float(v) for v in _NUM_RE.findall(body)]
        if kind == "translate":
            tx = nums[0] if nums else 0.0
            ty = nums[1] if len(nums) > 1 else 0.0
            cur = _mat_mul(cur, (1.0, 0.0, 0.0, 1.0, tx, ty))
        elif kind == "scale":
            sx = nums[0] if nums else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            cur = _mat_mul(cur, (sx, 0.0, 0.0, sy, 0.0, 0.0))
        elif kind == "rotate" and nums:
            ang = nums[0]
            rot_deg += ang
            rad = math.radians(ang)
            ca, sa = math.cos(rad), math.sin(rad)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                cur = _mat_mul(cur, (1.0, 0.0, 0.0, 1.0, cx, cy))
                cur = _mat_mul(cur, (ca, sa, -sa, ca, 0.0, 0.0))
                cur = _mat_mul(cur, (1.0, 0.0, 0.0, 1.0, -cx, -cy))
            else:
                cur = _mat_mul(cur, (ca, sa, -sa, ca, 0.0, 0.0))
        elif kind == "matrix" and len(nums) >= 6:
            m = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
            cur = _mat_mul(cur, m)
            rot_deg += math.degrees(math.atan2(nums[1], nums[0]))
    return cur, rot_deg


def _parse_css_sheet(root: ET.Element) -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    for el in root.iter():
        if _local_tag(el.tag) == "style" and el.text:
            clean = re.sub(r"/\*.*?\*/", "", el.text, flags=re.S)
            for sel_block, body in _CSS_RULE_RE.findall(clean):
                props: dict[str, str] = {}
                for chunk in body.split(";"):
                    if ":" in chunk:
                        k, v = chunk.split(":", 1)
                        props[k.strip()] = v.strip()
                for sel in sel_block.split(","):
                    s = sel.strip()
                    if s:
                        rules.setdefault(s, {}).update(props)
    return rules


def _parse_style(el: ET.Element, inherited: dict[str, str], css_rules: dict[str, dict[str, str]]) -> dict[str, str]:
    st = dict(inherited)
    tag = _local_tag(el.tag)
    if tag in css_rules:
        st.update(css_rules[tag])
    cls_attr = el.attrib.get("class", "")
    for c in cls_attr.split():
        if f".{c}" in css_rules:
            st.update(css_rules[f".{c}"])
        if f"{tag}.{c}" in css_rules:
            st.update(css_rules[f"{tag}.{c}"])
    for k in (
        "fill",
        "fill-opacity",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-dasharray",
        "font-size",
        "font-family",
        "font-weight",
        "text-anchor",
        "opacity",
    ):
        if k in el.attrib:
            st[k] = el.attrib[k].strip()
    style_attr = el.attrib.get("style", "")
    if style_attr:
        for chunk in style_attr.split(";"):
            if ":" in chunk:
                k, v = chunk.split(":", 1)
                st[k.strip()] = v.strip()
    return st


def _parse_float(val: str | None, default: float = 0.0) -> float:
    if not val:
        return default
    m = _NUM_RE.search(val)
    return float(m.group(0)) if m else default


def _arc_to_cubics(
    x1: float, y1: float, rx: float, ry: float, phi_deg: float, fa: int, fs: int, x2: float, y2: float
) -> list[PathSegment]:
    if abs(x1 - x2) < 1e-7 and abs(y1 - y2) < 1e-7:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-7 or ry < 1e-7:
        return [PathSegment("L", (x2, y2))]
    phi = math.radians(phi_deg % 360.0)
    c_phi, s_phi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = c_phi * dx2 + s_phi * dy2
    y1p = -s_phi * dx2 + c_phi * dy2
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1.0:
        sq = math.sqrt(lam)
        rx *= sq
        ry *= sq
    num = max(0.0, (rx ** 2) * (ry ** 2) - (rx ** 2) * (y1p ** 2) - (ry ** 2) * (x1p ** 2))
    den = max(1e-12, (rx ** 2) * (y1p ** 2) + (ry ** 2) * (x1p ** 2))
    coef = math.sqrt(num / den) * (-1.0 if fa == fs else 1.0)
    cxp = coef * (rx * y1p / ry)
    cyp = coef * (-ry * x1p / rx)
    cx = c_phi * cxp - s_phi * cyp + (x1 + x2) / 2.0
    cy = s_phi * cxp + c_phi * cyp + (y1 + y2) / 2.0

    def _ang(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        n = max(1e-12, math.hypot(ux, uy) * math.hypot(vx, vy))
        a = math.acos(max(-1.0, min(1.0, dot / n)))
        return -a if (ux * vy - uy * vx) < 0 else a

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = _ang(1.0, 0.0, ux, uy)
    dtheta = _ang(ux, uy, vx, vy)
    if fs == 0 and dtheta > 0:
        dtheta -= 2.0 * math.pi
    elif fs == 1 and dtheta < 0:
        dtheta += 2.0 * math.pi

    n_segs = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2.0))))
    dt = dtheta / n_segs
    alpha = 4.0 / 3.0 * math.tan(dt / 4.0)
    segs: list[PathSegment] = []
    for k in range(n_segs):
        t0 = theta1 + k * dt
        t1 = t0 + dt
        c0, s0 = math.cos(t0), math.sin(t0)
        c1, s1 = math.cos(t1), math.sin(t1)
        q1x, q1y = c0 - alpha * s0, s0 + alpha * c0
        q2x, q2y = c1 + alpha * s1, s1 - alpha * c1

        def _pt(px: float, py: float) -> tuple[float, float]:
            return (cx + c_phi * rx * px - s_phi * ry * py, cy + s_phi * rx * px + c_phi * ry * py)

        p1 = _pt(q1x, q1y)
        p2 = _pt(q2x, q2y)
        pe = _pt(c1, s1)
        segs.append(PathSegment("C", (p1[0], p1[1], p2[0], p2[1], pe[0], pe[1])))
    return segs


def parse_svg_path(d: str, ctm: tuple[float, ...]) -> list[PathSegment]:
    tokens = _TOKEN_RE.findall(d or "")
    segs: list[PathSegment] = []
    i = 0
    cmd = ""
    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    last_ctrl: tuple[float, float] | None = None

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in ("Z", "z"):
                segs.append(PathSegment("Z", ()))
                cx, cy = sx, sy
                last_ctrl = None
                continue
        if not cmd:
            break

        if cmd in ("M", "m"):
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
            if cmd == "m":
                x += cx
                y += cy
            cx, cy = x, y
            sx, sy = x, y
            wx, wy = _apply_mat(ctm, cx, cy)
            segs.append(PathSegment("M", (wx, wy)))
            cmd = "L" if cmd == "M" else "l"
            last_ctrl = None
        elif cmd in ("L", "l"):
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
            if cmd == "l":
                x += cx
                y += cy
            cx, cy = x, y
            wx, wy = _apply_mat(ctm, cx, cy)
            segs.append(PathSegment("L", (wx, wy)))
            last_ctrl = None
        elif cmd in ("H", "h"):
            x = float(tokens[i])
            i += 1
            cx = cx + x if cmd == "h" else x
            wx, wy = _apply_mat(ctm, cx, cy)
            segs.append(PathSegment("L", (wx, wy)))
            last_ctrl = None
        elif cmd in ("V", "v"):
            y = float(tokens[i])
            i += 1
            cy = cy + y if cmd == "v" else y
            wx, wy = _apply_mat(ctm, cx, cy)
            segs.append(PathSegment("L", (wx, wy)))
            last_ctrl = None
        elif cmd in ("C", "c"):
            x1, y1, x2, y2, x, y = (float(tokens[i + k]) for k in range(6))
            i += 6
            if cmd == "c":
                x1 += cx
                y1 += cy
                x2 += cx
                y2 += cy
                x += cx
                y += cy
            p1 = _apply_mat(ctm, x1, y1)
            p2 = _apply_mat(ctm, x2, y2)
            pe = _apply_mat(ctm, x, y)
            segs.append(PathSegment("C", (p1[0], p1[1], p2[0], p2[1], pe[0], pe[1])))
            last_ctrl = (x2, y2)
            cx, cy = x, y
        elif cmd in ("S", "s"):
            x2, y2, x, y = (float(tokens[i + k]) for k in range(4))
            i += 4
            if cmd == "s":
                x2 += cx
                y2 += cy
                x += cx
                y += cy
            x1 = 2 * cx - last_ctrl[0] if last_ctrl else cx
            y1 = 2 * cy - last_ctrl[1] if last_ctrl else cy
            p1 = _apply_mat(ctm, x1, y1)
            p2 = _apply_mat(ctm, x2, y2)
            pe = _apply_mat(ctm, x, y)
            segs.append(PathSegment("C", (p1[0], p1[1], p2[0], p2[1], pe[0], pe[1])))
            last_ctrl = (x2, y2)
            cx, cy = x, y
        elif cmd in ("Q", "q"):
            qx, qy, x, y = (float(tokens[i + k]) for k in range(4))
            i += 4
            if cmd == "q":
                qx += cx
                qy += cy
                x += cx
                y += cy
            c1x, c1y = cx + 2.0 / 3.0 * (qx - cx), cy + 2.0 / 3.0 * (qy - cy)
            c2x, c2y = x + 2.0 / 3.0 * (qx - x), y + 2.0 / 3.0 * (qy - y)
            p1 = _apply_mat(ctm, c1x, c1y)
            p2 = _apply_mat(ctm, c2x, c2y)
            pe = _apply_mat(ctm, x, y)
            segs.append(PathSegment("C", (p1[0], p1[1], p2[0], p2[1], pe[0], pe[1])))
            last_ctrl = (qx, qy)
            cx, cy = x, y
        elif cmd in ("A", "a"):
            rx, ry, rot, fa, fs, x, y = (
                float(tokens[i]),
                float(tokens[i + 1]),
                float(tokens[i + 2]),
                int(float(tokens[i + 3])),
                int(float(tokens[i + 4])),
                float(tokens[i + 5]),
                float(tokens[i + 6]),
            )
            i += 7
            if cmd == "a":
                x += cx
                y += cy
            for sub in _arc_to_cubics(cx, cy, rx, ry, rot, fa, fs, x, y):
                if sub.op == "L":
                    pe = _apply_mat(ctm, sub.pts[0], sub.pts[1])
                    segs.append(PathSegment("L", pe))
                elif sub.op == "C":
                    p1 = _apply_mat(ctm, sub.pts[0], sub.pts[1])
                    p2 = _apply_mat(ctm, sub.pts[2], sub.pts[3])
                    pe = _apply_mat(ctm, sub.pts[4], sub.pts[5])
                    segs.append(PathSegment("C", (p1[0], p1[1], p2[0], p2[1], pe[0], pe[1])))
            cx, cy = x, y
            last_ctrl = None
        else:
            i += 1
    return segs


def _segments_bbox(segs: list[PathSegment]) -> tuple[float, float, float, float] | None:
    xs, ys = [], []
    for s in segs:
        if s.op in ("M", "L"):
            xs.append(s.pts[0])
            ys.append(s.pts[1])
        elif s.op == "C":
            xs.extend((s.pts[0], s.pts[2], s.pts[4]))
            ys.extend((s.pts[1], s.pts[3], s.pts[5]))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def parse_svg_panel(
    svg_bytes: bytes,
    panel_id: str,
    title_hint: str = "",
    category_badge: str = "",
    source_citation: str = "",
    force_locked_special: bool | None = None,
    default_roi: ROIOverlaySpec | None = None,
) -> PanelIR:
    root = ET.fromstring(svg_bytes)
    vb_attr = root.attrib.get("viewBox", "")
    if vb_attr:
        vb_nums = [float(v) for v in _NUM_RE.findall(vb_attr)]
        vx, vy, vw, vh = vb_nums[0], vb_nums[1], vb_nums[2], vb_nums[3]
    else:
        vx, vy = 0.0, 0.0
        vw = _parse_float(root.attrib.get("width"), 400.0)
        vh = _parse_float(root.attrib.get("height"), 300.0)

    raw_w = _parse_float(root.attrib.get("width"), vw)
    raw_h = _parse_float(root.attrib.get("height"), vh)

    locked_attr = root.attrib.get("data-locked-special", "").lower() == "true"
    elasticity_attr = root.attrib.get("data-elasticity", "")
    css_rules = _parse_css_sheet(root)

    # Index <defs> by id for <use> symbol resolution & gradients
    defs_by_id: dict[str, ET.Element] = {}
    grad_map: dict[str, list[tuple[float, str]]] = {}
    for el in root.iter():
        eid = el.attrib.get("id", "")
        if eid:
            defs_by_id[eid] = el
        if _local_tag(el.tag) == "linearGradient":
            stops: list[tuple[float, str]] = []
            for ch in el:
                if _local_tag(ch.tag) == "stop":
                    off_s = ch.attrib.get("offset", "0")
                    off = _parse_float(off_s, 0.0) / (100.0 if "%" in off_s else 1.0)
                    sc = ch.attrib.get("stop-color", "#000000")
                    st_stop = ch.attrib.get("style", "")
                    for chunk in st_stop.split(";"):
                        if "stop-color" in chunk and ":" in chunk:
                            sc = chunk.split(":", 1)[1].strip()
                    stops.append((off, sc))
            if eid and stops:
                grad_map[eid] = stops

    explicit_spine: tuple[float, float, float, float] | None = None
    candidate_rects: list[tuple[float, float, float, float]] = []
    horiz_lines: list[tuple[float, float, float]] = []
    vert_lines: list[tuple[float, float, float]] = []

    raw_elements: list[tuple[str, ET.Element, tuple[float, ...], float, dict[str, str], str]] = []

    def _walk(node: ET.Element, ctm: tuple[float, ...], rot: float, style: dict[str, str], group_role: str, depth: int = 0) -> None:
        nonlocal explicit_spine
        if depth > 40:
            return
        tag = _local_tag(node.tag)
        if tag in ("defs", "clipPath", "style", "metadata", "mask", "symbol"):
            return
        l_mat, l_rot = _parse_transform(node.attrib.get("transform"))
        cur_ctm = _mat_mul(ctm, l_mat)
        cur_rot = rot + l_rot
        cur_style = _parse_style(node, style, css_rules)
        role_here = node.attrib.get("data-role", group_role)
        if not role_here and tag == "g":
            gid_lc = f"{node.attrib.get('id', '')} {node.attrib.get('class', '')}".lower()
            if "colorbar" in gid_lc:
                role_here = "colorbar"
            elif "legend" in gid_lc:
                role_here = "legend"

        # Expand <use href="#..."/> (matplotlib scatter dots & ticks!)
        if tag == "use":
            href = (
                node.attrib.get("href")
                or node.attrib.get("{http://www.w3.org/1999/xlink}href")
                or ""
            ).lstrip("#")
            if href and href in defs_by_id:
                ux = _parse_float(node.attrib.get("x"), 0.0)
                uy = _parse_float(node.attrib.get("y"), 0.0)
                u_ctm = _mat_mul(cur_ctm, (1.0, 0.0, 0.0, 1.0, ux, uy))
                ref_node = defs_by_id[href]
                if _local_tag(ref_node.tag) == "symbol":
                    for sub_ch in ref_node:
                        _walk(sub_ch, u_ctm, cur_rot, cur_style, role_here, depth + 1)
                else:
                    _walk(ref_node, u_ctm, cur_rot, cur_style, role_here, depth + 1)
            return

        if role_here == "spine-box":
            if tag == "rect":
                rx = _parse_float(node.attrib.get("x"))
                ry = _parse_float(node.attrib.get("y"))
                rw = _parse_float(node.attrib.get("width"))
                rh = _parse_float(node.attrib.get("height"))
                p0 = _apply_mat(cur_ctm, rx, ry)
                p1 = _apply_mat(cur_ctm, rx + rw, ry + rh)
                explicit_spine = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
            elif tag == "path":
                segs = parse_svg_path(node.attrib.get("d", ""), cur_ctm)
                bb = _segments_bbox(segs)
                if bb:
                    explicit_spine = bb

        if tag in ("rect", "line", "polyline", "polygon", "path", "circle", "ellipse", "text", "image"):
            raw_elements.append((tag, node, cur_ctm, cur_rot, cur_style, role_here))
            if tag == "rect":
                rx = _parse_float(node.attrib.get("x"))
                ry = _parse_float(node.attrib.get("y"))
                rw = _parse_float(node.attrib.get("width"))
                rh = _parse_float(node.attrib.get("height"))
                p0 = _apply_mat(cur_ctm, rx, ry)
                p1 = _apply_mat(cur_ctm, rx + rw, ry + rh)
                area = abs((p1[0] - p0[0]) * (p1[1] - p0[1]))
                if 0.12 * vw * vh < area < 0.88 * vw * vh:
                    candidate_rects.append((min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1])))
            elif tag == "line":
                p0 = _apply_mat(cur_ctm, _parse_float(node.attrib.get("x1")), _parse_float(node.attrib.get("y1")))
                p1 = _apply_mat(cur_ctm, _parse_float(node.attrib.get("x2")), _parse_float(node.attrib.get("y2")))
                if abs(p0[1] - p1[1]) < 1.0 and abs(p1[0] - p0[0]) > 0.30 * vw:
                    horiz_lines.append((p0[1], min(p0[0], p1[0]), max(p0[0], p1[0])))
                elif abs(p0[0] - p1[0]) < 1.0 and abs(p1[1] - p0[1]) > 0.30 * vh:
                    vert_lines.append((p0[0], min(p0[1], p1[1]), max(p0[1], p1[1])))
            elif tag == "path":
                segs_p = parse_svg_path(node.attrib.get("d", ""), cur_ctm)
                if len(segs_p) == 2 and segs_p[0].op == "M" and segs_p[1].op == "L":
                    p0, p1 = segs_p[0].pts, segs_p[1].pts
                    if abs(p0[1] - p1[1]) < 1.0 and abs(p1[0] - p0[0]) > 0.30 * vw:
                        horiz_lines.append((p0[1], min(p0[0], p1[0]), max(p0[0], p1[0])))
                    elif abs(p0[0] - p1[0]) < 1.0 and abs(p1[1] - p0[1]) > 0.30 * vh:
                        vert_lines.append((p0[0], min(p0[1], p1[1]), max(p0[1], p1[1])))
                elif 4 <= len(segs_p) <= 6 and segs_p[-1].op == "Z":
                    bb_r = _segments_bbox(segs_p)
                    if bb_r:
                        area = (bb_r[2] - bb_r[0]) * (bb_r[3] - bb_r[1])
                        if 0.14 * vw * vh < area < 0.88 * vw * vh:
                            candidate_rects.append(bb_r)

        for ch in node:
            _walk(ch, cur_ctm, cur_rot, cur_style, role_here, depth + 1)

    _walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 0.0, {"fill": "#000000", "stroke": "none"}, "")

    # Extract embedded raster images
    rasters: list[RasterEvidence] = []
    img_area_total = 0.0
    for tag, el, ctm, _, _, _ in raw_elements:
        if tag == "image":
            href = (
                el.attrib.get("href")
                or el.attrib.get("{http://www.w3.org/1999/xlink}href")
                or ""
            )
            if "base64," in href:
                b64_part = href.split("base64,", 1)[1].strip()
                raw_img = base64.b64decode(b64_part)
                with Image.open(io.BytesIO(raw_img)) as im:
                    w_px, h_px = im.size
                    if im.format != "PNG":
                        buf = io.BytesIO()
                        im.save(buf, format="PNG", compress_level=9)
                        raw_img = buf.getvalue()
                ix = _parse_float(el.attrib.get("x"))
                iy = _parse_float(el.attrib.get("y"))
                iw = _parse_float(el.attrib.get("width"), float(w_px))
                ih = _parse_float(el.attrib.get("height"), float(h_px))
                p0 = _apply_mat(ctm, ix, iy)
                p1 = _apply_mat(ctm, ix + iw, iy + ih)
                rw_box, rh_box = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])
                img_area_total += rw_box * rh_box
                rasters.append(
                    RasterEvidence(
                        png_bytes=raw_img,
                        width_px=w_px,
                        height_px=h_px,
                        x_raw=min(p0[0], p1[0]),
                        y_raw=min(p0[1], p1[1]),
                        w_raw=rw_box,
                        h_raw=rh_box,
                        sha256=hashlib.sha256(raw_img).hexdigest(),
                    )
                )

    if explicit_spine is not None:
        sx0, sy0, sx1, sy1 = explicit_spine
    elif candidate_rects:
        sx0, sy0, sx1, sy1 = max(candidate_rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    elif horiz_lines and vert_lines:
        hy, hx0, hx1 = max(horiz_lines, key=lambda h: h[0])
        vx_line, vy0, vy1 = min(vert_lines, key=lambda v: v[0])
        sx0, sy0, sx1, sy1 = vx_line, vy0, hx1, hy
    else:
        sx0, sy0, sx1, sy1 = vx + 0.08 * vw, vy + 0.08 * vh, vx + 0.92 * vw, vy + 0.92 * vh

    has_live_text = any(t == "text" for t, _, _, _, _, _ in raw_elements)
    has_cartesian_axes = (explicit_spine is not None) or bool(candidate_rects) or (bool(horiz_lines) and bool(vert_lines))
    is_locked = (
        force_locked_special
        if force_locked_special is not None
        else (locked_attr or (img_area_total > 0.22 * vw * vh) or (not has_cartesian_axes) or (not has_live_text))
    )

    if is_locked:
        elasticity: ElasticityClass = "L0_LOCKED_SPECIAL" if (rasters and len(raw_elements) <= 10) else "T2_COUPLED_LOCKED"
    elif elasticity_attr in ("L0_LOCKED_SPECIAL", "L1_ISOTROPIC_VECTOR", "L2_ELASTIC_CARTESIAN", "T2_COUPLED_LOCKED"):
        elasticity = elasticity_attr  # type: ignore[assignment]
    else:
        spine_ratio = (sx1 - sx0) / max(1e-6, sy1 - sy0)
        elasticity = "L1_ISOTROPIC_VECTOR" if 0.94 <= spine_ratio <= 1.06 and len(raw_elements) > 180 else "L2_ELASTIC_CARTESIAN"

    shapes: list[DataShape] = []
    markers: list[DataMarker] = []
    ticks: list[TickMark] = []
    texts: list[TextItem] = []
    legend_entries: list[LegendEntry] = []
    colorbar: ColorbarSpec | None = None
    cb_ticks: list[tuple[float, str]] = []
    cb_rect: tuple[float, float, float, float, str] | None = None
    cb_title = ""

    # Collect right-of-spine potential legend swatches & labels for arbitrary external SVGs
    auto_right_swatches: list[tuple[float, float, str, str]] = []  # (x, y, color, kind)
    auto_right_texts: list[tuple[float, float, str]] = []

    spine_w = max(1e-6, sx1 - sx0)
    spine_h = max(1e-6, sy1 - sy0)

    for tag, el, ctm, rot_deg, st, role_hint in raw_elements:
        if tag == "image":
            continue
        fill = st.get("fill", "#000000")
        stroke = st.get("stroke", "none")
        fill_op = _parse_float(st.get("fill-opacity"), 1.0) * _parse_float(st.get("opacity"), 1.0)
        stroke_op = _parse_float(st.get("stroke-opacity"), 1.0) * _parse_float(st.get("opacity"), 1.0)
        sw = _parse_float(st.get("stroke-width"), 1.0) * math.hypot(ctm[0], ctm[1])
        dash = st.get("stroke-dasharray")
        if dash == "none":
            dash = None

        if role_hint == "legend":
            if tag in ("rect", "circle", "ellipse", "line", "path"):
                if tag == "path":
                    bb_lg = _segments_bbox(parse_svg_path(el.attrib.get("d", ""), ctm))
                    if bb_lg and ((bb_lg[2] - bb_lg[0]) > 34.0 or (bb_lg[3] - bb_lg[1]) > 26.0):
                        continue  # Skip outer legend frame patch
                elif tag == "rect":
                    rw_lg = _parse_float(el.attrib.get("width")) * math.hypot(ctm[0], ctm[1])
                    rh_lg = _parse_float(el.attrib.get("height")) * math.hypot(ctm[0], ctm[1])
                    if rw_lg > 34.0 or rh_lg > 26.0:
                        continue
                col = fill if fill not in ("none", "transparent") else stroke
                if col.upper() in ("#FFFFFF", "WHITE", "#FFF", "#F8FAFC", "NONE", "TRANSPARENT"):
                    continue
                kind = "circle" if tag in ("circle", "ellipse") else ("line" if tag == "line" else "rect")
                if legend_entries and not legend_entries[-1].label:
                    legend_entries[-1].color = col
                    legend_entries[-1].kind = kind  # type: ignore[assignment]
                else:
                    legend_entries.append(LegendEntry(label="", color=col, kind=kind))  # type: ignore[arg-type]
            elif tag == "text":
                txt = "".join(el.itertext()).strip()
                if txt and legend_entries and not legend_entries[-1].label:
                    legend_entries[-1].label = txt
            continue

        if role_hint == "colorbar":
            if tag == "rect" and fill.startswith("url(#"):
                gid = fill[5:-1]
                rx = _parse_float(el.attrib.get("x"))
                ry = _parse_float(el.attrib.get("y"))
                rw = _parse_float(el.attrib.get("width"))
                rh = _parse_float(el.attrib.get("height"))
                p0 = _apply_mat(ctm, rx, ry)
                p1 = _apply_mat(ctm, rx + rw, ry + rh)
                cb_rect = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]), gid)
            elif tag == "text":
                txt = "".join(el.itertext()).strip()
                tx, ty = _apply_mat(ctm, _parse_float(el.attrib.get("x")), _parse_float(el.attrib.get("y")))
                if cb_rect and ty < cb_rect[1] - 2.0 and not cb_title:
                    cb_title = txt
                elif cb_rect and txt:
                    t_rel = 1.0 - max(0.0, min(1.0, (ty - cb_rect[1]) / max(1e-6, cb_rect[3] - cb_rect[1])))
                    cb_ticks.append((t_rel, txt))
            continue

        if tag == "text":
            txt = "".join(el.itertext()).strip()
            if not txt:
                continue
            tx, ty = _apply_mat(ctm, _parse_float(el.attrib.get("x")), _parse_float(el.attrib.get("y")))
            fpx = _parse_float(st.get("font-size"), 11.0) * math.hypot(ctm[0], ctm[1])
            ffam = st.get("font-family", "Helvetica").split(",")[0].strip("'\" ")
            bold = st.get("font-weight", "normal") in ("bold", "700", "800", "600")
            anc_raw = st.get("text-anchor", "start")
            anchor = anc_raw if anc_raw in ("start", "middle", "end") else "start"

            if tx > sx1 + 5.0 and sy0 - 10.0 <= ty <= sy1 + 10.0 and cb_rect is None:
                auto_right_texts.append((tx, ty, txt))
                continue

            t_role: TextRole = "ANNOTATION"
            target_pt: tuple[float, float] | None = None
            if len(txt) == 1 and txt.isalpha() and bold and tx < sx0 + 0.12 * vw and ty < sy0 + 0.12 * vh:
                t_role = "PANEL_TAG"
            elif role_hint == "annotation":
                t_role = "ANNOTATION"
                if "data-target-x" in el.attrib and "data-target-y" in el.attrib:
                    target_pt = (float(el.attrib["data-target-x"]), float(el.attrib["data-target-y"]))
            elif ty < sy0 - 1.5 and sx0 - 0.15 * vw <= tx <= sx1 + 0.15 * vw:
                t_role = "PANEL_TITLE"
            elif abs(abs(rot_deg) - 90.0) < 15.0 and tx < sx0 - 8.0:
                t_role = "Y_TITLE"
            elif tx <= sx0 + 2.0 and sy0 - 8.0 <= ty <= sy1 + 8.0:
                t_role = "Y_TICK"
            elif ty >= sy1 + 2.0 and sx0 - 12.0 <= tx <= sx1 + 18.0:
                if ty <= sy1 + 0.11 * vh + 18.0 and not (bold and ty > sy1 + 28.0):
                    t_role = "X_TICK"
                else:
                    t_role = "X_TITLE"
                if ty > sy1 + 32.0:
                    t_role = "X_TITLE"

            texts.append(
                TextItem(
                    text=txt,
                    role=t_role,
                    x_raw=tx,
                    y_raw=ty,
                    raw_font_px=fpx,
                    raw_font_family=ffam,
                    bold=bold,
                    fill=fill if fill != "none" else "#000000",
                    anchor=anchor,  # type: ignore[arg-type]
                    angle_deg=rot_deg,
                    target_raw=target_pt,
                )
            )
            continue

        if tag in ("circle", "ellipse"):
            cx, cy = _apply_mat(ctm, _parse_float(el.attrib.get("cx")), _parse_float(el.attrib.get("cy")))
            rx = _parse_float(el.attrib.get("r", el.attrib.get("rx")), 2.5) * math.hypot(ctm[0], ctm[1])
            if cx > sx1 + 4.0 and rx <= 12.0:
                auto_right_swatches.append((cx, cy, fill if fill != "none" else stroke, "circle"))
                continue
            bub_attr = el.attrib.get("data-bubble-rel")
            is_bub = bub_attr is not None
            rel_sz = float(bub_attr) if bub_attr is not None else 1.0
            in_sp = (sx0 - 4.0 <= cx <= sx1 + 4.0) and (sy0 - 4.0 <= cy <= sy1 + 4.0)
            markers.append(
                DataMarker(
                    cx=cx,
                    cy=cy,
                    raw_r=rx,
                    rel_size=rel_sz,
                    is_proportional_bubble=is_bub,
                    fill=fill,
                    fill_opacity=fill_op,
                    stroke=stroke,
                    stroke_width_pt=0.35 if stroke != "none" else 0.0,
                    clip_to_spine=in_sp,
                )
            )
            continue

        segs: list[PathSegment] = []
        if tag == "rect":
            rx = _parse_float(el.attrib.get("x"))
            ry = _parse_float(el.attrib.get("y"))
            rw = _parse_float(el.attrib.get("width"))
            rh = _parse_float(el.attrib.get("height"))
            if rw >= 0.96 * vw and rh >= 0.96 * vh and fill.upper() in ("#FFFFFF", "WHITE", "#FFF"):
                continue
            p0 = _apply_mat(ctm, rx, ry)
            p2 = _apply_mat(ctm, rx + rw, ry + rh)
            if min(p0[0], p2[0]) > sx1 + 3.0 and abs(p2[0] - p0[0]) <= 22.0 and abs(p2[1] - p0[1]) <= 22.0:
                auto_right_swatches.append((0.5 * (p0[0] + p2[0]), 0.5 * (p0[1] + p2[1]), fill if fill != "none" else stroke, "rect"))
                continue
            p1 = _apply_mat(ctm, rx + rw, ry)
            p3 = _apply_mat(ctm, rx, ry + rh)
            segs = [PathSegment("M", p0), PathSegment("L", p1), PathSegment("L", p2), PathSegment("L", p3), PathSegment("Z", ())]
        elif tag == "line":
            p0 = _apply_mat(ctm, _parse_float(el.attrib.get("x1")), _parse_float(node_y1 := el.attrib.get("y1")))
            p1 = _apply_mat(ctm, _parse_float(el.attrib.get("x2")), _parse_float(el.attrib.get("y2")))
            _ = node_y1
            if role_hint == "tick-x" or (
                abs(p0[0] - p1[0]) < 0.8 and abs(min(p0[1], p1[1]) - sy1) < 2.5 and 1.5 <= abs(p1[1] - p0[1]) <= 12.0
            ):
                ticks.append(TickMark("x", p0[0]))
                continue
            if role_hint == "tick-y" or (
                abs(p0[1] - p1[1]) < 0.8 and abs(max(p0[0], p1[0]) - sx0) < 2.5 and 1.5 <= abs(p1[0] - p0[0]) <= 12.0
            ):
                ticks.append(TickMark("y", p0[1]))
                continue
            if role_hint == "leader":
                continue
            if role_hint == "error-cap":
                shapes.append(
                    DataShape(
                        role="ERROR_CAP",
                        segments=[PathSegment("M", p0), PathSegment("L", p1)],
                        stroke=stroke if stroke != "none" else "#000000",
                        stroke_opacity=stroke_op,
                        raw_stroke_width=sw,
                        clip_to_spine=False,
                        cap_center=((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0),
                        cap_half_pt=2.0,
                    )
                )
                continue
            segs = [PathSegment("M", p0), PathSegment("L", p1)]
        elif tag in ("polyline", "polygon"):
            nums = [float(v) for v in _NUM_RE.findall(el.attrib.get("points", ""))]
            pts = [_apply_mat(ctm, nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
            if pts:
                segs = [PathSegment("M", pts[0])] + [PathSegment("L", p) for p in pts[1:]]
                if tag == "polygon":
                    segs.append(PathSegment("Z", ()))
        elif tag == "path":
            segs = parse_svg_path(el.attrib.get("d", ""), ctm)
            bb_p = _segments_bbox(segs)
            if bb_p and role_hint == "":
                pw_b, ph_b = bb_p[2] - bb_p[0], bb_p[3] - bb_p[1]
                cx_p, cy_p = 0.5 * (bb_p[0] + bb_p[2]), 0.5 * (bb_p[1] + bb_p[3])
                # Legend swatches & outer legend frames located to the right of SpineBox
                if bb_p[0] > sx1 + 2.5 and cb_rect is None:
                    if pw_b <= 28.0 and ph_b <= 22.0:
                        sw_col = fill if fill not in ("none", "transparent", "#FFFFFF") else stroke
                        if sw_col not in ("none", "transparent", "#FFFFFF"):
                            sw_kind = "line" if (ph_b <= 2.2 and fill in ("none", "transparent")) else (
                                "circle" if (0.80 <= pw_b / max(1e-6, ph_b) <= 1.25 and pw_b <= 14.0) else "rect"
                            )
                            auto_right_swatches.append((cx_p, cy_p, sw_col, sw_kind))
                    continue
                # Small isotropic closed paths inside SpineBox (e.g. matplotlib <use> circle paths!) -> DataMarker!
                if 1.2 <= pw_b <= 14.0 and 1.2 <= ph_b <= 14.0 and 0.80 <= pw_b / max(1e-6, ph_b) <= 1.25 and segs[-1].op == "Z":
                    if sx0 - 3.0 <= cx_p <= sx1 + 3.0 and sy0 - 3.0 <= cy_p <= sy1 + 3.0:
                        markers.append(
                            DataMarker(
                                cx=cx_p,
                                cy=cy_p,
                                raw_r=0.5 * max(pw_b, ph_b),
                                fill=fill if fill != "none" else stroke,
                                fill_opacity=fill_op,
                                stroke=stroke,
                                clip_to_spine=True,
                            )
                        )
                        continue
                # Short axis ticks encoded as <path d="M x y L x y+4"/> in matplotlib/svglite
                if len(segs) == 2 and segs[0].op == "M" and segs[1].op == "L":
                    q0, q1 = segs[0].pts, segs[1].pts
                    if abs(q0[0] - q1[0]) < 0.8 and abs(min(q0[1], q1[1]) - sy1) < 2.5 and 1.5 <= abs(q1[1] - q0[1]) <= 12.0:
                        ticks.append(TickMark("x", q0[0]))
                        continue
                    if abs(q0[1] - q1[1]) < 0.8 and abs(max(q0[0], q1[0]) - sx0) < 2.5 and 1.5 <= abs(q1[0] - q0[0]) <= 12.0:
                        ticks.append(TickMark("y", q0[1]))
                        continue

        if not segs:
            continue

        if role_hint == "spine-box":
            s_role = "SPINE_BORDER"
        elif role_hint == "grid" or (dash is not None and fill == "none"):
            s_role = "GRID"
        elif role_hint == "bracket":
            s_role = "BRACKET"
        elif role_hint == "error-stem":
            s_role = "ERROR_STEM"
        elif fill not in ("none", "transparent"):
            s_role = "DATA_FILL"
        else:
            s_role = "DATA_STROKE"

        shapes.append(
            DataShape(
                role=s_role,  # type: ignore[arg-type]
                segments=segs,
                fill=fill,
                fill_opacity=fill_op,
                stroke=stroke,
                stroke_opacity=stroke_op,
                raw_stroke_width=sw,
                dasharray=dash,
                clip_to_spine=s_role not in ("SPINE_BORDER", "BRACKET"),
            )
        )

    # Auto-bind right-of-spine swatches & texts if no explicit data-role="legend" was present
    if not legend_entries and auto_right_swatches and auto_right_texts:
        for sx_w, sy_w, scol, skind in sorted(auto_right_swatches, key=lambda item: item[1]):
            best_t = min(auto_right_texts, key=lambda t_it: abs(t_it[1] - sy_w))
            if abs(best_t[1] - sy_w) <= 12.0 and best_t[0] >= sx_w - 2.0:
                legend_entries.append(LegendEntry(label=best_t[2], color=scol, kind=skind))  # type: ignore[arg-type]

    if cb_rect and cb_rect[4] in grad_map:
        colorbar = ColorbarSpec(title=cb_title or "Scale", stops=grad_map[cb_rect[4]], ticks=cb_ticks)

    x_ticks_txt = [t for t in texts if t.role == "X_TICK"]
    if len(x_ticks_txt) >= 2:
        min_tick_y = min(t.y_raw for t in x_ticks_txt)
        for t in texts:
            if t.role == "X_TICK" and t.y_raw > min_tick_y + 7.5:
                t.role = "X_TITLE"

    x_ticks_final = [t for t in texts if t.role == "X_TICK"]
    y_tick_count = sum(1 for t in texts if t.role == "Y_TICK")
    x_tick_count = len(x_ticks_final)
    is_cat_x = x_tick_count >= 2 and any(not _is_numeric_label(t.text) for t in x_ticks_final)

    raw_aspect = spine_w / spine_h if not is_locked else (vw / max(1e-6, vh))
    if rasters and is_locked and len(shapes) <= 4:
        r0 = rasters[0]
        raw_aspect = r0.w_raw / max(1e-6, r0.h_raw)

    if is_locked or elasticity == "L1_ISOTROPIC_VECTOR":
        ideal_asp = raw_aspect if is_locked else 1.0
        min_asp = ideal_asp
        max_asp = ideal_asp
    else:
        ideal_asp = max(0.75, min(1.80, raw_aspect))
        min_asp = max(0.62, ideal_asp * 0.65)
        max_asp = min(2.25, ideal_asp * 1.48)

    if not title_hint:
        t_items = [t.text for t in texts if t.role == "PANEL_TITLE"]
        title_hint = t_items[0] if t_items else panel_id

    return PanelIR(
        panel_id=panel_id,
        title_hint=title_hint,
        category_badge=category_badge or ("1:1 Locked" if is_locked else "Vector"),
        source_citation=source_citation,
        raw_width_pt=raw_w,
        raw_height_pt=raw_h,
        viewbox=(vx, vy, vw, vh),
        spine_box=(sx0, sy0, sx1, sy1),
        elasticity=elasticity,
        locked_special=is_locked,
        raw_svg_bytes=svg_bytes,
        shapes=shapes,
        markers=markers,
        ticks=ticks,
        texts=texts,
        legend_entries=[le for le in legend_entries if le.label],
        colorbar=colorbar,
        rasters=rasters,
        default_roi=default_roi or ROIOverlaySpec(enabled=False),
        n_y_categories=y_tick_count,
        n_x_categories=x_tick_count,
        is_categorical_x=is_cat_x,
        ideal_aspect=ideal_asp,
        min_aspect=min_asp,
        max_aspect=max_asp,
    )


def _rgb_hex_from_pdf_vals(vals: list[float]) -> str:
    if len(vals) == 1:
        g = max(0, min(255, int(round(vals[0] * 255))))
        return f"#{g:02X}{g:02X}{g:02X}"
    if len(vals) == 3:
        r, g, b = (max(0, min(255, int(round(v * 255)))) for v in vals)
        return f"#{r:02X}{g:02X}{b:02X}"
    if len(vals) == 4:
        c, m, y, k = vals
        r = max(0, min(255, int(round(255 * (1 - c) * (1 - k)))))
        g = max(0, min(255, int(round(255 * (1 - m) * (1 - k)))))
        b = max(0, min(255, int(round(255 * (1 - y) * (1 - k)))))
        return f"#{r:02X}{g:02X}{b:02X}"
    return "#000000"


def _decompile_pdf_to_svg_if_vector(content: bytes) -> bytes | None:
    """Decompile a single-panel vector chart PDF (R pdf(), matplotlib, Prism) into clean semantic SVG bytes.
    Returns None if the PDF contains dominant raster evidence (H&E/WB) or outlined Form XObjects without live text.
    """
    try:
        pdf = pikepdf.open(io.BytesIO(content))
        if len(pdf.pages) == 0:
            return None
        page = pdf.pages[0]
        mb = [float(x) for x in page.mediabox]
        pw, ph = mb[2] - mb[0], mb[3] - mb[1]
        if pw <= 10 or ph <= 10:
            return None

        res = page.get("/Resources", pikepdf.Dictionary())
        xobjs = res.get("/XObject", pikepdf.Dictionary())
        for _, xo in xobjs.items():
            if xo.get("/Subtype") == pikepdf.Name("/Image"):
                return None  # Contains raw image -> protect via lossless 1:1 special path!

        doc_f = pdfium.PdfDocument(content)
        fpage = doc_f[0]
        tpage = fpage.get_textpage()
        full_text = tpage.get_text_range().strip()
        if len(full_text) < 3:
            return None  # Outlined cairo_pdf or pure graphic -> protect 1:1 without risking missing labels!

        # Extract text bounding boxes via PDFium get_rect() + get_text_bounded()
        n_rects = tpage.count_rects()
        raw_rects: list[tuple[float, float, float, float, str]] = []
        for ri in range(n_rects):
            lb, bb, rb, tb = tpage.get_rect(ri)
            s_piece = tpage.get_text_bounded(lb, bb, rb, tb).replace("\r", " ").replace("\n", " ").strip()
            if s_piece:
                raw_rects.append((float(lb), float(bb), float(rb), float(tb), s_piece))

        # Merge split adjacent glyph fragments on the same baseline (e.g. Unicode minus '−' + '3')
        merged_rects: list[tuple[float, float, float, float, str]] = []
        for lb, bb, rb, tb, sp in raw_rects:
            if merged_rects:
                pl, pb, pr, pt, ps = merged_rects[-1]
                prev_cy = 0.5 * (pb + pt)
                cur_cy = 0.5 * (bb + tb)
                if abs(cur_cy - prev_cy) <= 4.0 and -1.8 <= (lb - pr) <= 4.5 and max(pt - pb, tb - bb) <= 18.0:
                    merged_rects[-1] = (min(pl, lb), min(pb, bb), max(pr, rb), max(pt, tb), ps + sp)
                    continue
            merged_rects.append((lb, bb, rb, tb, sp))

        text_runs: list[tuple[str, float, float, float, float, str]] = []  # (str, x_svg, y_svg, font_px, angle_deg, anchor)
        for x0, y0_pdf, x1, y1_pdf, s in merged_rects:
            w_b = max(1.0, x1 - x0)
            h_b = max(1.0, y1_pdf - y0_pdf)
            if h_b > 1.85 * w_b and len(s) >= 3:
                fs = max(6.0, min(16.0, w_b * 1.18))
                cx_s = 0.5 * (x0 + x1) - mb[0]
                cy_s = ph - (0.5 * (y0_pdf + y1_pdf) - mb[1])
                text_runs.append((s, cx_s, cy_s, fs, -90.0, "middle"))
            else:
                fs = max(6.0, min(18.0, h_b * 1.15))
                ty_s = ph - (y0_pdf - mb[1])
                if (x1 - mb[0]) < 0.22 * pw and len(s) <= 9:
                    text_runs.append((s, x1 - mb[0], ty_s, fs, 0.0, "end"))
                elif (x0 - mb[0]) > 0.66 * pw:
                    text_runs.append((s, x0 - mb[0], ty_s, fs, 0.0, "start"))
                else:
                    text_runs.append((s, 0.5 * (x0 + x1) - mb[0], ty_s, fs, 0.0, "middle"))

        if len(text_runs) < 3:
            return None

        # Parse vector paths (including matplotlib /Form marker XObjects!) from PDF content stream
        ctm_stack: list[tuple[float, float, float, float, float, float]] = [(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)]
        style_stack: list[tuple[str, str, float]] = [("#000000", "#000000", 1.0)]
        state = {"fill": "#000000", "stroke": "#000000", "lw": 1.0}
        cur_d: list[str] = []
        svg_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {pw:.2f} {ph:.2f}" width="{pw:.2f}" height="{ph:.2f}">',
            f'  <rect x="0" y="0" width="{pw:.2f}" height="{ph:.2f}" fill="#FFFFFF"/>',
        ]

        def _p2s(x_p: float, y_p: float) -> tuple[float, float]:
            wx, wy = _apply_mat(ctm_stack[-1], x_p, y_p)
            return (wx - mb[0], ph - (wy - mb[1]))

        def _walk_pdf_stream(stream_obj: object, res_dict: pikepdf.Dictionary, depth: int = 0) -> None:
            if depth > 4:
                return
            xo_map = res_dict.get("/XObject", pikepdf.Dictionary()) if isinstance(res_dict, pikepdf.Dictionary) else pikepdf.Dictionary()
            for operands, operator in pikepdf.parse_content_stream(stream_obj):
                op = str(operator)
                if op == "q":
                    ctm_stack.append(ctm_stack[-1])
                    style_stack.append((state["fill"], state["stroke"], state["lw"]))
                elif op == "Q":
                    if len(ctm_stack) > 1:
                        ctm_stack.pop()
                    if len(style_stack) > 1:
                        f_p, s_p, w_p = style_stack.pop()
                        state["fill"], state["stroke"], state["lw"] = f_p, s_p, w_p
                elif op == "cm" and len(operands) >= 6:
                    m = tuple(float(operands[k]) for k in range(6))
                    ctm_stack[-1] = _mat_mul(ctm_stack[-1], m)
                elif op == "w" and operands:
                    state["lw"] = float(operands[0]) * math.hypot(ctm_stack[-1][0], ctm_stack[-1][1])
                elif op in ("g", "rg", "k", "sc", "scn"):
                    nums = [float(x) for x in operands if isinstance(x, (int, float, Decimal))]
                    if nums:
                        state["fill"] = _rgb_hex_from_pdf_vals(nums)
                elif op in ("G", "RG", "K", "SC", "SCN"):
                    nums = [float(x) for x in operands if isinstance(x, (int, float, Decimal))]
                    if nums:
                        state["stroke"] = _rgb_hex_from_pdf_vals(nums)
                elif op == "Do" and operands:
                    xname = str(operands[0])
                    sub_xo = xo_map.get(xname)
                    if sub_xo is not None and sub_xo.get("/Subtype") == pikepdf.Name("/Form"):
                        ctm_stack.append(ctm_stack[-1])
                        style_stack.append((state["fill"], state["stroke"], state["lw"]))
                        fmat = sub_xo.get("/Matrix")
                        if fmat and len(fmat) >= 6:
                            ctm_stack[-1] = _mat_mul(ctm_stack[-1], tuple(float(fmat[k]) for k in range(6)))
                        sub_res = sub_xo.get("/Resources", res_dict)
                        _walk_pdf_stream(sub_xo, sub_res, depth + 1)
                        ctm_stack.pop()
                        f_p, s_p, w_p = style_stack.pop()
                        state["fill"], state["stroke"], state["lw"] = f_p, s_p, w_p
                elif op == "m" and len(operands) >= 2:
                    sx, sy = _p2s(float(operands[0]), float(operands[1]))
                    cur_d.append(f"M {sx:.2f} {sy:.2f}")
                elif op == "l" and len(operands) >= 2:
                    sx, sy = _p2s(float(operands[0]), float(operands[1]))
                    cur_d.append(f"L {sx:.2f} {sy:.2f}")
                elif op == "c" and len(operands) >= 6:
                    p1 = _p2s(float(operands[0]), float(operands[1]))
                    p2 = _p2s(float(operands[2]), float(operands[3]))
                    pe = _p2s(float(operands[4]), float(operands[5]))
                    cur_d.append(f"C {p1[0]:.2f} {p1[1]:.2f} {p2[0]:.2f} {p2[1]:.2f} {pe[0]:.2f} {pe[1]:.2f}")
                elif op == "re" and len(operands) >= 4:
                    rx, ry, rw, rh = (float(operands[k]) for k in range(4))
                    q0 = _p2s(rx, ry)
                    q1 = _p2s(rx + rw, ry)
                    q2 = _p2s(rx + rw, ry + rh)
                    q3 = _p2s(rx, ry + rh)
                    cur_d.append(
                        f"M {q0[0]:.2f} {q0[1]:.2f} L {q1[0]:.2f} {q1[1]:.2f} "
                        f"L {q2[0]:.2f} {q2[1]:.2f} L {q3[0]:.2f} {q3[1]:.2f} Z"
                    )
                elif op == "h":
                    cur_d.append("Z")
                elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*"):
                    if op in ("s", "b", "b*"):
                        cur_d.append("Z")
                    if cur_d:
                        d_str = " ".join(cur_d)
                        do_f = op in ("f", "F", "f*", "B", "B*", "b", "b*")
                        do_s = op in ("S", "s", "B", "B*", "b", "b*")
                        f_val = state["fill"] if do_f else "none"
                        s_val = state["stroke"] if do_s else "none"
                        svg_lines.append(
                            f'  <path d="{d_str}" fill="{f_val}" stroke="{s_val}" stroke-width="{max(0.3, float(state["lw"])):.2f}"/>'
                        )
                    cur_d.clear()
                elif op == "n":
                    cur_d.clear()

        _walk_pdf_stream(page, res, 0)

        for txt, tx, ty, fs, ang, anc in text_runs:
            if abs(ang) > 45.0:
                svg_lines.append(
                    f'  <text x="{tx:.2f}" y="{ty:.2f}" text-anchor="middle" '
                    f'transform="rotate({ang:.1f} {tx:.2f} {ty:.2f})" font-family="Arial" font-size="{fs:.2f}" fill="#000000">{escape(txt)}</text>'
                )
            else:
                svg_lines.append(
                    f'  <text x="{tx:.2f}" y="{ty:.2f}" text-anchor="{anc}" font-family="Arial" font-size="{fs:.2f}" fill="#000000">{escape(txt)}</text>'
                )
        svg_lines.append("</svg>")
        return "\n".join(svg_lines).encode("utf-8")
    except Exception:
        return None


def parse_uploaded_file(filename: str, content: bytes, panel_id: str) -> PanelIR:
    """Parse user-uploaded .svg, .pdf (true vector decompile + 1:1 evidence fallback), or raster into PanelIR."""
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem[:32]
    if ext == ".svg":
        return parse_svg_panel(content, panel_id=panel_id, title_hint=stem, source_citation=filename)

    if ext == ".pdf":
        vec_svg = _decompile_pdf_to_svg_if_vector(content)
        if vec_svg is not None:
            ir = parse_svg_panel(vec_svg, panel_id=panel_id, title_hint=stem, source_citation=filename)
            if not ir.locked_special and (len(ir.shapes) + len(ir.markers)) >= 2 and len(ir.texts) >= 2:
                return ir

        # Fallback for histology/WB/coupled-diagram PDFs -> Lossless 1:1 Aspect-Locked Container
        doc = pdfium.PdfDocument(content)
        page = doc[0]
        pw, ph = page.get_size()
        scale = max(3.0, 1400.0 / max(pw, ph, 1.0))
        bitmap = page.render(scale=scale)
        pil_im = bitmap.to_pil().convert("RGB")
        buf = io.BytesIO()
        pil_im.save(buf, format="PNG", compress_level=9)
        png_bytes = buf.getvalue()
        b64 = base64.b64encode(png_bytes).decode("ascii")
        svg_wrap = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {pw:.1f} {ph:.1f}" '
            f'width="{pw:.1f}" height="{ph:.1f}" data-locked-special="true">'
            f'<rect x="0" y="0" width="{pw:.1f}" height="{ph:.1f}" fill="#FFFFFF" data-role="spine-box"/>'
            f'<image x="0" y="0" width="{pw:.1f}" height="{ph:.1f}" href="data:image/png;base64,{b64}"/>'
            f"</svg>"
        ).encode("utf-8")
        return parse_svg_panel(
            svg_wrap,
            panel_id=panel_id,
            title_hint=stem,
            category_badge="1:1 Locked PDF",
            source_citation=filename,
            force_locked_special=True,
            default_roi=ROIOverlaySpec(enabled=False, x_norm=0.25, y_norm=0.25, w_norm=0.35, h_norm=0.35, label="ROI"),
        )

    # Raster image (.png, .jpg, .tif, .webp) -> Strictly Locked Special Evidence!
    with Image.open(io.BytesIO(content)) as im:
        im_rgb = im.convert("RGB")
        w_px, h_px = im_rgb.size
        buf = io.BytesIO()
        im_rgb.save(buf, format="PNG", compress_level=9)
        png_bytes = buf.getvalue()
    b64 = base64.b64encode(png_bytes).decode("ascii")
    svg_wrap = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w_px} {h_px}" '
        f'width="{w_px}" height="{h_px}" data-locked-special="true">'
        f'<rect x="0" y="0" width="{w_px}" height="{h_px}" fill="none" data-role="spine-box"/>'
        f'<image x="0" y="0" width="{w_px}" height="{h_px}" href="data:image/png;base64,{b64}"/>'
        f"</svg>"
    ).encode("utf-8")
    return parse_svg_panel(
        svg_wrap,
        panel_id=panel_id,
        title_hint=stem,
        category_badge="1:1 Locked Image",
        source_citation=filename,
        force_locked_special=True,
        default_roi=ROIOverlaySpec(enabled=False, x_norm=0.25, y_norm=0.25, w_norm=0.35, h_norm=0.35, label="ROI"),
    )
