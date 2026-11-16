"""Lossless SVG parser, CSS/<use>/inheritance resolver, legend binder & OKLCH rewriter for Danqing.

Handles (Spec Section 9 P0):
- <style> CSS rules (.class, #id, tag, compound selectors), inline style="...", presentation attributes,
  ancestor <g>/<svg> inherited fill/stroke/color, currentColor, named CSS colors, and opacity.
- <use href="#..." / xlink:href="#..."> symbol/marker references (e.g. matplotlib scatter & legend markers).
- Native <linearGradient>/<radialGradient> <stop> elements + vector colorbar strip detection, with 7-stop OKLCH enrichment.
- Embedded <image> href data-URIs protected byte-for-byte (SHA-256 verified).
- Transformed element bounding boxes, multi-panel partitioning, generalized SVG legend binding, and plain-language fallback naming.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import resvg_py
from coloraide import Color
from lxml import etree

from .color_science import (
    ciede2000_matrix,
    describe_color_group,
    hex_to_oklch,
    hex_to_srgb01,
    interpolate_oklch_lut,
    project_colors_onto_lut,
    simulate_cvd,
    srgb01_to_hex,
    srgb_to_oklab,
)
from .ir import CollisionNotice, ColorGroup, ContinuousScale, EvidenceRegion, PanelBox, SemanticEntity

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_FN_RE = re.compile(r"^rgba?\(\s*([0-9.]+%?)\s*,\s*([0-9.]+%?)\s*,\s*([0-9.]+%?)(?:\s*[,/]\s*[0-9.]+%?)?\s*\)$", re.I)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_CSS_RULE_RE = re.compile(r"([^{}@]+)\{([^{}]*)\}")
_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_TRANSFORM_FN_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")

_CONTROL_PATTERNS = (
    "igg",
    "ctrl",
    "control",
    "vehicle",
    "wt",
    "normal",
    "unassigned",
    "other",
    "background",
    "ns",
    "non-sig",
    "nonsig",
    "pass",
    "dmso",
    "pbs",
    "mock",
    "sham",
)

_SHAPE_TAGS = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "use"})
_SKIP_CONTAINERS = frozenset({"defs", "clipPath", "mask", "marker", "pattern", "symbol", "metadata", "title", "desc"})


def _parse_len(val: str | None, default: float = 0.0, ref: float = 100.0) -> float:
    if not val:
        return default
    s = val.strip().lower()
    if s.endswith("%"):
        try:
            return float(s[:-1]) * 0.01 * ref
        except ValueError:
            return default
    for unit in ("px", "pt", "mm", "cm", "in", "em", "rem"):
        if s.endswith(unit):
            s = s[: -len(unit)].strip()
            scale = {"pt": 1.3333, "mm": 3.7795, "cm": 37.795, "in": 96.0, "em": 12.0, "rem": 12.0}.get(unit, 1.0)
            try:
                return float(s) * scale
            except ValueError:
                return default
    try:
        return float(s)
    except ValueError:
        return default


def _norm_svg_color(val: str | None, current_color_hex: str | None = None) -> str | None:
    if not val:
        return None
    v = re.sub(r"\s*!important\s*$", "", val.strip(), flags=re.I)
    low = v.lower()
    if not low or low in ("none", "transparent", "inherit", "initial", "unset") or low.startswith("url("):
        return None
    if low == "currentcolor":
        return current_color_hex
    m_hex = _HEX_RE.match(v)
    if m_hex:
        h = m_hex.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        elif len(h) == 8:
            h = h[:6]
        return f"#{h.upper()}"
    m_rgb = _RGB_FN_RE.match(v)
    if m_rgb:
        comps = []
        for idx in (1, 2, 3):
            tok = m_rgb.group(idx)
            if tok.endswith("%"):
                c_i = int(round(float(tok[:-1]) * 2.55))
            else:
                c_i = int(round(float(tok)))
            comps.append(max(0, min(255, c_i)))
        return f"#{comps[0]:02X}{comps[1]:02X}{comps[2]:02X}"
    try:
        c = Color(v).convert("srgb")
        r, g, b = (max(0, min(255, int(round(float(ch) * 255.0)))) for ch in c.coords()[:3])
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return None


def _parse_style_attr(style_str: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not style_str:
        return out
    for part in style_str.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = re.sub(r"\s*!important\s*$", "", v.strip(), flags=re.I)
    return out


@dataclass
class CssRule:
    selector_parts: list[str]
    specificity: tuple[int, int, int, int]
    declarations: dict[str, str]


def _selector_specificity(sel: str, order_idx: int) -> tuple[int, int, int, int]:
    ids = sel.count("#")
    classes = sel.count(".") + sel.count("[")
    tags = sum(1 for tok in re.split(r"[\s>+~]+", sel.strip()) if tok and not tok.startswith((".", "#", "*", "[")))
    return (ids, classes, tags, order_idx)


def _parse_css_stylesheets(root: etree._Element) -> list[CssRule]:
    rules: list[CssRule] = []
    order_idx = 0
    for el in root.iter():
        if not isinstance(el.tag, str) or etree.QName(el).localname != "style":
            continue
        css_txt = "".join(el.itertext())
        css_txt = _CSS_COMMENT_RE.sub("", css_txt)
        for m in _CSS_RULE_RE.finditer(css_txt):
            sel_group = m.group(1).strip()
            decl_map = _parse_style_attr(m.group(2))
            if not decl_map:
                continue
            for raw_sel in sel_group.split(","):
                s = raw_sel.strip()
                if not s or ":" in s:
                    continue
                parts = [p for p in re.split(r"[\s>]+", s) if p]
                if parts:
                    rules.append(CssRule(parts, _selector_specificity(s, order_idx), decl_map))
                    order_idx += 1
    rules.sort(key=lambda r: r.specificity)
    return rules


def _match_simple_selector(el: etree._Element, sel: str) -> bool:
    if sel == "*":
        return True
    local = etree.QName(el).localname
    el_id = el.get("id") or ""
    el_classes = set((el.get("class") or "").split())

    # Extract tag, #id, and .class tokens
    tag_m = re.match(r"^([a-zA-Z0-9_-]+)", sel)
    if tag_m and tag_m.group(1) != local:
        return False
    for id_tok in re.findall(r"#([a-zA-Z0-9_-]+)", sel):
        if el_id != id_tok:
            return False
    for cls_tok in re.findall(r"\.([a-zA-Z0-9_-]+)", sel):
        if cls_tok not in el_classes:
            return False
    return True


def _match_css_rule(el: etree._Element, ancestors: list[etree._Element], rule: CssRule) -> bool:
    if not _match_simple_selector(el, rule.selector_parts[-1]):
        return False
    if len(rule.selector_parts) == 1:
        return True
    anc_idx = len(ancestors) - 1
    for part in reversed(rule.selector_parts[:-1]):
        matched = False
        while anc_idx >= 0:
            if _match_simple_selector(ancestors[anc_idx], part):
                matched = True
                anc_idx -= 1
                break
            anc_idx -= 1
        if not matched:
            return False
    return True


def _mat_mul2d(m1: tuple[float, ...], m2: tuple[float, ...]) -> tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_svg_transform(tr_str: str | None) -> tuple[float, float, float, float, float, float]:
    mat = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not tr_str:
        return mat
    for fn_m in _TRANSFORM_FN_RE.finditer(tr_str):
        fn = fn_m.group(1).lower()
        nums = [float(x) for x in _NUM_RE.findall(fn_m.group(2))]
        if fn == "matrix" and len(nums) >= 6:
            sub = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif fn == "translate" and len(nums) >= 1:
            tx = nums[0]
            ty = nums[1] if len(nums) >= 2 else 0.0
            sub = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif fn == "scale" and len(nums) >= 1:
            sx = nums[0]
            sy = nums[1] if len(nums) >= 2 else sx
            sub = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif fn == "rotate" and len(nums) >= 1:
            rad = math.radians(nums[0])
            cs, sn = math.cos(rad), math.sin(rad)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                sub = _mat_mul2d(
                    (1.0, 0.0, 0.0, 1.0, cx, cy),
                    _mat_mul2d((cs, sn, -sn, cs, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, -cx, -cy)),
                )
            else:
                sub = (cs, sn, -sn, cs, 0.0, 0.0)
        else:
            continue
        mat = _mat_mul2d(mat, sub)
    return mat


def _xform_bbox(
    mat: tuple[float, float, float, float, float, float], x0: float, y0: float, x1: float, y1: float
) -> tuple[float, float, float, float]:
    a, b, c, d, e, f = mat
    pts = [
        (a * x0 + c * y0 + e, b * x0 + d * y0 + f),
        (a * x1 + c * y0 + e, b * x1 + d * y0 + f),
        (a * x0 + c * y1 + e, b * x0 + d * y1 + f),
        (a * x1 + c * y1 + e, b * x1 + d * y1 + f),
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _path_local_bbox(d_str: str | None) -> tuple[float, float, float, float] | None:
    if not d_str:
        return None
    tokens = re.findall(r"[a-zA-Z]|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", d_str)
    if not tokens:
        return None
    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    xs: list[float] = []
    ys: list[float] = []
    cmd = "M"
    i = 0
    n = len(tokens)

    def _rec(px: float, py: float) -> None:
        xs.append(px)
        ys.append(py)

    while i < n:
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in ("Z", "z"):
                cx, cy = sx, sy
                continue
            if i >= n:
                break
        try:
            if cmd in ("M", "m"):
                dx, dy = float(tokens[i]), float(tokens[i + 1])
                i += 2
                cx = dx if cmd == "M" else cx + dx
                cy = dy if cmd == "M" else cy + dy
                sx, sy = cx, cy
                _rec(cx, cy)
                cmd = "L" if cmd == "M" else "l"
            elif cmd in ("L", "l", "T", "t"):
                dx, dy = float(tokens[i]), float(tokens[i + 1])
                i += 2
                cx = dx if cmd.isupper() else cx + dx
                cy = dy if cmd.isupper() else cy + dy
                _rec(cx, cy)
            elif cmd in ("H", "h"):
                dx = float(tokens[i])
                i += 1
                cx = dx if cmd == "H" else cx + dx
                _rec(cx, cy)
            elif cmd in ("V", "v"):
                dy = float(tokens[i])
                i += 1
                cy = dy if cmd == "V" else cy + dy
                _rec(cx, cy)
            elif cmd in ("C", "c"):
                vals = [float(tokens[i + k]) for k in range(6)]
                i += 6
                for k in (0, 2, 4):
                    px = vals[k] if cmd == "C" else cx + vals[k]
                    py = vals[k + 1] if cmd == "C" else cy + vals[k + 1]
                    _rec(px, py)
                cx = vals[4] if cmd == "C" else cx + vals[4]
                cy = vals[5] if cmd == "C" else cy + vals[5]
            elif cmd in ("S", "s", "Q", "q"):
                vals = [float(tokens[i + k]) for k in range(4)]
                i += 4
                for k in (0, 2):
                    px = vals[k] if cmd.isupper() else cx + vals[k]
                    py = vals[k + 1] if cmd.isupper() else cy + vals[k + 1]
                    _rec(px, py)
                cx = vals[2] if cmd.isupper() else cx + vals[2]
                cy = vals[3] if cmd.isupper() else cy + vals[3]
            elif cmd in ("A", "a"):
                rx, ry = abs(float(tokens[i])), abs(float(tokens[i + 1]))
                ex = float(tokens[i + 5])
                ey = float(tokens[i + 6])
                i += 7
                nx = ex if cmd == "A" else cx + ex
                ny = ey if cmd == "A" else cy + ey
                _rec(nx - rx * 0.5, ny - ry * 0.5)
                _rec(nx + rx * 0.5, ny + ry * 0.5)
                cx, cy = nx, ny
            else:
                i += 1
        except (IndexError, ValueError):
            break

    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _local_shape_bbox(
    el: etree._Element, defs_by_id: dict[str, etree._Element], view_w: float, view_h: float
) -> tuple[float, float, float, float] | None:
    local = etree.QName(el).localname
    if local == "rect":
        x = _parse_len(el.get("x"), 0.0, view_w)
        y = _parse_len(el.get("y"), 0.0, view_h)
        w = _parse_len(el.get("width"), 0.0, view_w)
        h = _parse_len(el.get("height"), 0.0, view_h)
        return (x, y, x + w, y + h) if (w > 0 or h > 0) else None
    if local == "circle":
        cx = _parse_len(el.get("cx"), 0.0, view_w)
        cy = _parse_len(el.get("cy"), 0.0, view_h)
        r = _parse_len(el.get("r"), 0.0, view_w)
        return (cx - r, cy - r, cx + r, cy + r) if r > 0 else None
    if local == "ellipse":
        cx = _parse_len(el.get("cx"), 0.0, view_w)
        cy = _parse_len(el.get("cy"), 0.0, view_h)
        rx = _parse_len(el.get("rx"), 0.0, view_w)
        ry = _parse_len(el.get("ry"), 0.0, view_h)
        return (cx - rx, cy - ry, cx + rx, cy + ry) if (rx > 0 or ry > 0) else None
    if local == "line":
        x1 = _parse_len(el.get("x1"), 0.0, view_w)
        y1 = _parse_len(el.get("y1"), 0.0, view_h)
        x2 = _parse_len(el.get("x2"), 0.0, view_w)
        y2 = _parse_len(el.get("y2"), 0.0, view_h)
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    if local in ("polyline", "polygon"):
        nums = [float(v) for v in _NUM_RE.findall(el.get("points") or "")]
        if len(nums) >= 4:
            xs = nums[0::2]
            ys = nums[1::2]
            return (min(xs), min(ys), max(xs), max(ys))
        return None
    if local == "path":
        return _path_local_bbox(el.get("d"))
    if local in ("g", "symbol"):
        ub: list[float] | None = None
        for ch in el:
            if not isinstance(ch.tag, str) or etree.QName(ch).localname in _SKIP_CONTAINERS:
                continue
            cb = _local_shape_bbox(ch, defs_by_id, view_w, view_h)
            if cb is not None:
                c_mat = _parse_svg_transform(ch.get("transform"))
                xb = _xform_bbox(c_mat, *cb)
                if ub is None:
                    ub = [xb[0], xb[1], xb[2], xb[3]]
                else:
                    ub = [min(ub[0], xb[0]), min(ub[1], xb[1]), max(ub[2], xb[2]), max(ub[3], xb[3])]
        return (ub[0], ub[1], ub[2], ub[3]) if ub is not None else None
    if local == "use":
        ux = _parse_len(el.get("x"), 0.0, view_w)
        uy = _parse_len(el.get("y"), 0.0, view_h)
        href = (el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or "").strip()
        ref_id = href[1:] if href.startswith("#") else ""
        ref_el = defs_by_id.get(ref_id)
        if ref_el is not None and ref_el is not el:
            sub_bb = _local_shape_bbox(ref_el, defs_by_id, view_w, view_h)
            if sub_bb is not None:
                ref_mat = _parse_svg_transform(ref_el.get("transform"))
                rb = _xform_bbox(ref_mat, *sub_bb)
                return (rb[0] + ux, rb[1] + uy, rb[2] + ux, rb[3] + uy)
        return (ux - 3.5, uy - 3.5, ux + 3.5, uy + 3.5)
    return None


@dataclass
class SvgTextItem:
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    panel_id: str = "Panel A"


@dataclass
class SvgPaintInstance:
    elem_idx: int
    panel_id: str
    bbox: tuple[float, float, float, float]
    fill_hex: str | None
    stroke_hex: str | None
    grad_id: str | None
    fill_gid: str | None = None
    stroke_gid: str | None = None
    is_bg_white: bool = False
    use_ref_id: str | None = None
    alpha: float = 1.0
    is_dashed: bool = False
    in_axis_group: bool = False
    is_line_only: bool = False


@dataclass
class SvgScene:
    scene_id: str
    filename: str
    raw_svg_bytes: bytes
    width: float
    height: float
    panels: list[PanelBox]
    evidence_regions: list[EvidenceRegion]
    color_groups: dict[str, ColorGroup]
    continuous_scales: dict[str, ContinuousScale]
    entities: dict[str, SemanticEntity]
    collisions: list[CollisionNotice]
    geometry_hash_original: str
    grad_id_to_scale: dict[str, str] = field(default_factory=dict)
    paint_instances: dict[int, SvgPaintInstance] = field(default_factory=dict, repr=False)
    defs_ids_to_strip_color: set[str] = field(default_factory=set, repr=False)
    plain_notices: list[dict[str, Any]] = field(default_factory=list)
    preview_scale: float = 1.5
    original_svg: bytes = field(repr=False, default=b"")
    structural_svg: bytes = field(repr=False, default=b"")
    id_map_svg: bytes = field(repr=False, default=b"")
    coverage_svg: bytes = field(repr=False, default=b"")
    original_png: bytes = field(repr=False, default=b"")
    id_map_png: bytes = field(repr=False, default=b"")


def canonical_svg_geometry_hash(svg_bytes: bytes) -> str:
    """Gate G6 for SVG: hash tag structure, path 'd', coordinates, text content, and image hrefs (ignoring fill/stroke/style/stop-color)."""
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    root = etree.fromstring(svg_bytes, parser=parser)
    h = hashlib.sha256()
    ignore_attrs = frozenset(
        {"fill", "stroke", "color", "stop-color", "style", "offset", "data-danqing-interp"}
    )
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        local = etree.QName(el).localname
        if local == "stop":
            continue
        h.update(f"<{local}".encode())
        for k in sorted(el.attrib.keys()):
            if k in ignore_attrs:
                continue
            h.update(f" {k}={el.attrib[k]!r}".encode())
        if local != "style" and el.text and el.text.strip():
            h.update(f">{el.text.strip()}".encode())
    return h.hexdigest()


def _extract_grad_id_ref(val: str | None) -> str | None:
    if not val:
        return None
    m = re.match(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)", val.strip())
    return m.group(1) if m else None


def _detect_svg_panels(
    texts: list[SvgTextItem],
    width: float,
    height: float,
    filename: str,
    clip_rects: list[tuple[float, float, float, float]] | None = None,
) -> list[PanelBox]:
    tags = [
        t
        for t in texts
        if len(t.text) == 1 and "A" <= t.text <= "H" and t.font_size >= 11.0
    ]
    seen_letters: dict[str, SvgTextItem] = {}
    for t in sorted(tags, key=lambda x: (-x.font_size, x.bbox[1], x.bbox[0])):
        if t.text not in seen_letters:
            seen_letters[t.text] = t
    if len(seen_letters) >= 2 and "A" in seen_letters:
        ordered = sorted(seen_letters.values(), key=lambda x: x.text)
        y_vals = sorted(t.bbox[1] for t in ordered)
        row_splits: list[float] = [0.0]
        cur_row = [y_vals[0]]
        for y in y_vals[1:]:
            if y - cur_row[-1] > 0.18 * height:
                row_splits.append(max(0.0, y - 10.0))
                cur_row = [y]
            else:
                cur_row.append(y)
        row_splits.append(height)

        panels: list[PanelBox] = []
        for r_i in range(len(row_splits) - 1):
            ry0, ry1 = row_splits[r_i], row_splits[r_i + 1]
            row_tags = sorted([t for t in ordered if ry0 - 12.0 <= t.bbox[1] < ry1], key=lambda x: x.bbox[0])
            if not row_tags:
                continue
            col_splits = [0.0] + [max(0.0, rt.bbox[0] - 8.0) for rt in row_tags[1:]] + [width]
            for c_i, rt in enumerate(row_tags):
                cx0, cx1 = col_splits[c_i], col_splits[c_i + 1]
                pid = f"Panel {rt.text}"
                panels.append(PanelBox(panel_id=pid, title=pid, bbox=(round(cx0, 2), round(ry0, 2), round(cx1, 2), round(ry1, 2))))
        if panels:
            return panels

    # Fallback for multi-subplot SVGs without single-letter A/B tags (e.g. Matplotlib/Seaborn `<clipPath>` subplots)
    if clip_rects:
        page_area = width * height
        cands: list[tuple[float, float, float, float]] = []
        for x0, y0, x1, y1 in clip_rects:
            w_c, h_c = x1 - x0, y1 - y0
            a_c = w_c * h_c
            if w_c < 90.0 or h_c < 90.0 or a_c > 0.90 * page_area or a_c < 0.035 * page_area:
                continue
            if any(
                abs(x0 - cx0) < 12.0 and abs(y0 - cy0) < 12.0 and abs(x1 - cx1) < 12.0 and abs(y1 - cy1) < 12.0
                for cx0, cy0, cx1, cy1 in cands
            ):
                continue
            cands.append((x0, y0, x1, y1))
        outer: list[tuple[float, float, float, float]] = []
        for i, (ax0, ay0, ax1, ay1) in enumerate(cands):
            a_area = (ax1 - ax0) * (ay1 - ay0)
            if any(
                i != j
                and (bx1 - bx0) * (by1 - by0) > a_area * 1.15
                and ax0 >= bx0 - 4.0
                and ay0 >= by0 - 4.0
                and ax1 <= bx1 + 4.0
                and ay1 <= by1 + 4.0
                for j, (bx0, by0, bx1, by1) in enumerate(cands)
            ):
                continue
            outer.append((ax0, ay0, ax1, ay1))
        if len(outer) >= 2:
            outer.sort(key=lambda b: (round(b[1] / 90.0), b[0]))
            clip_panels: list[PanelBox] = []
            for idx_p, (x0, y0, x1, y1) in enumerate(outer):
                pid = f"Panel {chr(ord('A') + idx_p)}" if idx_p < 26 else f"Panel {idx_p + 1}"
                title = pid
                best_ty = 1e9
                for t in texts:
                    if len(t.text) < 4 or t.text.replace(".", "").isdigit():
                        continue
                    tx = 0.5 * (t.bbox[0] + t.bbox[2])
                    ty = 0.5 * (t.bbox[1] + t.bbox[3])
                    if x0 <= tx <= x1 and max(0.0, y0 - 36.0) <= ty <= y0 + 0.20 * (y1 - y0):
                        if ty < best_ty and (t.bbox[2] - t.bbox[0]) > 28.0:
                            best_ty = ty
                            title = t.text
                clip_panels.append(
                    PanelBox(panel_id=pid, title=title, bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)))
                )
            return clip_panels

    return [PanelBox(panel_id="Panel A", title=filename.rsplit(".", 1)[0], bbox=(0.0, 0.0, width, height))]


def _assign_panel(bbox: tuple[float, float, float, float], panels: list[PanelBox]) -> str:
    if len(panels) == 1:
        return panels[0].panel_id
    cx = 0.5 * (bbox[0] + bbox[2])
    cy = 0.5 * (bbox[1] + bbox[3])
    for p in panels:
        if p.bbox[0] <= cx <= p.bbox[2] and p.bbox[1] <= cy <= p.bbox[3]:
            return p.panel_id
    best_p = min(
        panels,
        key=lambda p: (cx - 0.5 * (p.bbox[0] + p.bbox[2])) ** 2 + (cy - 0.5 * (p.bbox[1] + p.bbox[3])) ** 2,
    )
    return best_p.panel_id


def _bind_svg_legend_labels(
    instances: list[SvgPaintInstance],
    color_groups: dict[str, ColorGroup],
    texts: list[SvgTextItem],
    panels: list[PanelBox],
) -> None:
    panel_texts: dict[str, list[SvgTextItem]] = {}
    for t in texts:
        panel_texts.setdefault(t.panel_id, []).append(t)
    panel_map = {p.panel_id: p for p in panels}

    raw_keys: list[tuple[str, str, tuple[float, float, float, float], int]] = []
    for inst in instances:
        w = inst.bbox[2] - inst.bbox[0]
        h = inst.bbox[3] - inst.bbox[1]
        if w <= 44.0 and h <= 34.0:
            for gid in (inst.fill_gid, inst.stroke_gid):
                if gid and gid in color_groups and not color_groups[gid].is_continuous_member:
                    raw_keys.append((inst.panel_id, gid, inst.bbox, color_groups[gid].primitive_count))

    cand_matches: list[tuple[str, str, tuple[float, float, float, float], SvgTextItem, float, bool]] = []
    for pid, gid, kbox, pcnt in raw_keys:
        pb = panel_map[pid].bbox
        rel_x = (kbox[0] - pb[0]) / max(1.0, pb[2] - pb[0])
        rel_y = (kbox[1] - pb[1]) / max(1.0, pb[3] - pb[1])
        in_margin = bool(rel_x > 0.62 or rel_x < 0.25 or rel_y > 0.78 or rel_y < 0.20)
        margin_bonus = 35.0 if in_margin else 0.0
        single_bonus = 15.0 if pcnt <= 4 else 0.0
        fill_bonus = 2.5 if color_groups[gid].role == "fill" else 0.0
        scx = 0.5 * (kbox[0] + kbox[2])
        scy = 0.5 * (kbox[1] + kbox[3])

        cand_texts = texts if (in_margin and len(panels) > 1) else panel_texts.get(pid, [])
        for t in cand_texts:
            txt_clean = t.text.strip()
            if (
                not txt_clean
                or re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?%?", txt_clean)
                or re.fullmatch(r"[\u25a0-\u25ff\u2022\u2219\u2605\u2606\u2713-\u2718\s]+", txt_clean)
            ):
                continue
            if len(txt_clean) == 1 and "A" <= txt_clean <= "H" and t.font_size >= 11.0:
                continue
            tcx = 0.5 * (t.bbox[0] + t.bbox[2])
            tcy = 0.5 * (t.bbox[1] + t.bbox[3])

            dx_r = t.bbox[0] - kbox[2]
            dy_r = abs(tcy - scy)
            if -5.0 <= dx_r <= 40.0 and dy_r <= 10.5:
                base_sc = 50.0 + margin_bonus + single_bonus + fill_bonus - abs(dx_r) * 0.8 - 2.0 * dy_r
                cand_matches.append((pid, gid, kbox, t, base_sc, in_margin))
                continue

            dy_b = t.bbox[1] - kbox[3]
            dx_b = abs(tcx - scx)
            if -2.0 <= dy_b <= 18.0 and dx_b <= 26.0:
                base_sc = 36.0 + margin_bonus + single_bonus + fill_bonus - 1.4 * abs(dy_b) - 1.2 * dx_b
                cand_matches.append((pid, gid, kbox, t, base_sc, in_margin))

    scored_matches: list[tuple[float, str, SvgTextItem, tuple[float, float, float, float]]] = []
    for i, (pid, gid, kbox, t, base_sc, in_margin) in enumerate(cand_matches):
        peers = sum(
            1
            for j, (pid2, gid2, kbox2, t2, _, in_margin2) in enumerate(cand_matches)
            if i != j
            and (pid2 == pid or (in_margin and in_margin2))
            and gid2 != gid
            and t2.text != t.text
            and (abs(kbox[0] - kbox2[0]) <= 6.0 or abs(kbox[1] - kbox2[1]) <= 6.0)
        )
        if peers == 0 and base_sc < 72.0:
            continue
        total_sc = base_sc + min(3, peers) * 24.0
        scored_matches.append((total_sc, gid, t, kbox))

    scored_matches.sort(key=lambda x: x[0], reverse=True)
    best_match_for_group: dict[str, tuple[float, str]] = {}
    claimed_text_keys: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for total_sc, gid, t, kbox in scored_matches:
        if gid in best_match_for_group:
            continue
        cg_cur = color_groups[gid]
        conflict_same_swatch = False
        for t_id, prev_hex, prev_kb in claimed_text_keys:
            if t_id == id(t) and abs(kbox[0] - prev_kb[0]) <= 2.5 and abs(kbox[1] - prev_kb[1]) <= 2.5:
                de_pair = float(
                    ciede2000_matrix(
                        hex_to_srgb01(cg_cur.original_hex)[None, :],
                        hex_to_srgb01(prev_hex)[None, :],
                    )[0, 0]
                )
                if de_pair >= 6.0:
                    conflict_same_swatch = True
                    break
        if conflict_same_swatch:
            continue
        best_match_for_group[gid] = (total_sc, t.text.strip())
        claimed_text_keys.append((id(t), cg_cur.original_hex, kbox))

    for gid, (_, lbl) in best_match_for_group.items():
        color_groups[gid].local_label = lbl


def _detect_svg_vector_colorbars(
    instances: list[SvgPaintInstance],
    color_groups: dict[str, ColorGroup],
    continuous_scales: dict[str, ContinuousScale],
    texts: list[SvgTextItem],
) -> None:
    panels_with_cb = {cs.panel_id for cs in continuous_scales.values()}
    by_panel: dict[str, list[SvgPaintInstance]] = {}
    for inst in instances:
        if inst.fill_gid and inst.fill_hex and inst.panel_id not in panels_with_cb:
            w = inst.bbox[2] - inst.bbox[0]
            h = inst.bbox[3] - inst.bbox[1]
            if (3.0 <= w <= 32.0 and 0.3 <= h <= 9.0) or (0.3 <= w <= 9.0 and 3.0 <= h <= 32.0):
                by_panel.setdefault(inst.panel_id, []).append(inst)

    for pid, sps in by_panel.items():
        if len(sps) < 16:
            continue
        x_buckets: dict[int, list[SvgPaintInstance]] = {}
        for sp in sps:
            x_buckets.setdefault(int(round(sp.bbox[0] / 3.5)), []).append(sp)
        best_col = max(x_buckets.values(), key=len)
        if len(best_col) < 16:
            continue
        best_col.sort(key=lambda s: s.bbox[1], reverse=True)
        unique_hexes = list(dict.fromkeys(s.fill_hex for s in best_col if s.fill_hex))
        if len(unique_hexes) < 10:
            continue
        strip_arr = np.stack([hex_to_srgb01(s.fill_hex) for s in best_col if s.fill_hex], axis=0)[:, None, :]
        cb_bbox = (
            min(s.bbox[0] for s in best_col),
            min(s.bbox[1] for s in best_col),
            max(s.bbox[2] for s in best_col),
            max(s.bbox[3] for s in best_col),
        )
        lut_idx = np.linspace(0, len(strip_arr) - 1, 256)
        lut = np.stack([np.interp(lut_idx, np.arange(len(strip_arr)), strip_arr[:, 0, c]) for c in range(3)], axis=-1)
        labs = srgb_to_oklab(lut)
        l_curve = labs[:, 0]
        mid_rel = int(np.argmax(l_curve[64:192])) + 64
        is_div = bool(l_curve[mid_rel] - max(float(l_curve[0]), float(l_curve[-1])) > 0.08)

        scale_id = f"scale_{len(continuous_scales) + 1:02d}"
        cb_title = f"{pid} Continuous Scale"
        for t in texts:
            if t.panel_id == pid and not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?%?", t.text):
                if -10.0 <= (cb_bbox[1] - t.bbox[3]) <= 40.0 and abs(t.bbox[0] - cb_bbox[0]) <= 70.0:
                    cb_title = t.text
                    break

        cand_groups = [cg for cg in color_groups.values() if cg.panel_id == pid]
        srgbs = np.stack([hex_to_srgb01(cg.original_hex) for cg in cand_groups], axis=0)
        ts, res = project_colors_onto_lut(srgbs, lut)
        members: list[str] = []
        for cg, tv, rv in zip(cand_groups, ts, res):
            if rv <= 0.042:
                cg.is_continuous_member = True
                cg.continuous_scale_id = scale_id
                cg.continuous_t = round(float(tv), 4)
                members.append(cg.group_id)

        if len(members) >= 8:
            orig_stops = [srgb01_to_hex(lut[i]) for i in (0, 64, 128, 192, 255)]
            continuous_scales[scale_id] = ContinuousScale(
                scale_id=scale_id,
                panel_id=pid,
                title=cb_title,
                kind="continuous_diverging" if is_div else "continuous_sequential",
                midpoint_t=round(mid_rel / 255.0, 3) if is_div else 0.5,
                colorbar_xobject=None,
                colorbar_bbox=tuple(round(v, 2) for v in cb_bbox),
                raster_heatmap_xobject=None,
                member_group_ids=members,
                original_stops_hex=orig_stops,
                current_stops_hex=list(orig_stops),
            )


def parse_svg_scene(
    svg_bytes: bytes,
    filename: str = "figure.svg",
    scene_id: str = "svg_01",
    progress_cb: Callable[[str, int], None] | None = None,
) -> SvgScene:
    if progress_cb:
        progress_cb("reading_file", 10)
    geom_hash = canonical_svg_geometry_hash(svg_bytes)
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    root = etree.fromstring(svg_bytes, parser=parser)

    vb_raw = root.get("viewBox")
    if vb_raw:
        vb = [float(x) for x in _NUM_RE.findall(vb_raw)]
        width = vb[2] if len(vb) >= 4 else 800.0
        height = vb[3] if len(vb) >= 4 else 600.0
    else:
        width = _parse_len(root.get("width"), 800.0, 800.0)
        height = _parse_len(root.get("height"), 600.0, 600.0)
    width = max(1.0, width)
    height = max(1.0, height)

    if progress_cb:
        progress_cb("detecting_colors", 35)

    css_rules = _parse_css_stylesheets(root)
    all_elems = list(root.iter())
    elem_to_idx = {id(el): idx for idx, el in enumerate(all_elems)}

    defs_by_id: dict[str, etree._Element] = {}
    for el in all_elems:
        if isinstance(el.tag, str) and el.get("id"):
            defs_by_id[el.get("id", "")] = el

    evidence_regions: list[EvidenceRegion] = []
    continuous_scales: dict[str, ContinuousScale] = {}
    grad_id_to_scale: dict[str, str] = {}
    texts: list[SvgTextItem] = []
    raw_instances: list[SvgPaintInstance] = []
    defs_ids_to_strip_color: set[str] = set()

    def _effective_props(
        el: etree._Element,
        ancestors: list[etree._Element],
        inh_fill: str | None,
        inh_stroke: str | None,
        inh_color: str | None,
        inh_alpha: float,
    ) -> tuple[str | None, str | None, str | None, float]:
        matched_css: dict[str, str] = {}
        for rule in css_rules:
            if _match_css_rule(el, ancestors, rule):
                matched_css.update(rule.declarations)
        inline_map = _parse_style_attr(el.get("style"))

        raw_col = inline_map.get("color") or matched_css.get("color") or el.get("color")
        eff_col = _norm_svg_color(raw_col, inh_color) if raw_col else inh_color

        def _pick_paint(prop: str, inh_val: str | None) -> str | None:
            cand = inline_map.get(prop) or matched_css.get(prop) or el.get(prop)
            if cand is None:
                return inh_val
            c_low = cand.strip().lower()
            if c_low == "inherit":
                return inh_val
            if c_low in ("none", "transparent"):
                return "none"
            if c_low.startswith("url("):
                return cand.strip()
            return _norm_svg_color(cand, eff_col) or "none"

        eff_fill = _pick_paint("fill", inh_fill)
        eff_stroke = _pick_paint("stroke", inh_stroke)
        op_s = inline_map.get("opacity") or matched_css.get("opacity") or el.get("opacity")
        fop_s = inline_map.get("fill-opacity") or matched_css.get("fill-opacity") or el.get("fill-opacity")
        alpha = inh_alpha
        for s_val in (op_s, fop_s):
            if s_val:
                try:
                    alpha *= max(0.0, min(1.0, float(s_val.strip())))
                except ValueError:
                    pass
        return eff_fill, eff_stroke, eff_col, alpha

    def _walk(
        el: etree._Element,
        ancestors: list[etree._Element],
        ctm: tuple[float, float, float, float, float, float],
        inh_fill: str | None,
        inh_stroke: str | None,
        inh_color: str | None,
        inh_alpha: float,
        in_defs: bool,
    ) -> None:
        if not isinstance(el.tag, str):
            return
        local = etree.QName(el).localname
        cur_ctm = _mat_mul2d(ctm, _parse_svg_transform(el.get("transform")))
        eff_fill, eff_stroke, eff_col, eff_alpha = _effective_props(
            el, ancestors, inh_fill, inh_stroke, inh_color, inh_alpha
        )

        if local in ("linearGradient", "radialGradient"):
            gid_attr = el.get("id", f"grad_{len(continuous_scales) + 1}")
            stops_hex: list[str] = []
            for child in el:
                if isinstance(child.tag, str) and etree.QName(child).localname == "stop":
                    st_map = _parse_style_attr(child.get("style"))
                    sc = _norm_svg_color(st_map.get("stop-color") or child.get("stop-color"), eff_col)
                    if sc:
                        stops_hex.append(sc)
            if len(stops_hex) >= 2 and gid_attr not in grad_id_to_scale:
                sid = f"scale_{len(continuous_scales) + 1:02d}"
                grad_id_to_scale[gid_attr] = sid
                labs = srgb_to_oklab(np.stack([hex_to_srgb01(h) for h in stops_hex], axis=0))
                is_div = len(stops_hex) >= 3 and (
                    float(labs[len(labs) // 2, 0]) - max(float(labs[0, 0]), float(labs[-1, 0])) > 0.08
                )
                continuous_scales[sid] = ContinuousScale(
                    scale_id=sid,
                    panel_id="Panel A",
                    title=f"SVG Gradient #{gid_attr}",
                    kind="continuous_diverging" if is_div else "continuous_sequential",
                    midpoint_t=0.5,
                    colorbar_xobject=None,
                    colorbar_bbox=None,
                    raster_heatmap_xobject=None,
                    member_group_ids=[],
                    original_stops_hex=stops_hex,
                    current_stops_hex=list(stops_hex),
                )
            return

        now_in_defs = in_defs or (local in _SKIP_CONTAINERS)
        if not now_in_defs:
            # Handle Matplotlib `svg.fonttype = 'path'` outlined glyph groups (`<g id="text_..."> <!-- label --> ... </g>`)
            # so gray/colored text glyphs are never misclassified as scatter points and legend/panel texts are preserved!
            el_id_cur = el.get("id") or ""
            if local == "g" and re.match(r"^text_\d+$", el_id_cur):
                has_real_text_tag = any(
                    isinstance(d.tag, str) and etree.QName(d).localname == "text" for d in el.iter()
                )
                if not has_real_text_tag:
                    comments = [
                        (c.text or "").strip()
                        for c in el
                        if isinstance(c, etree._Comment) and (c.text or "").strip()
                    ]
                    comment_txt = " ".join(" ".join(comments).split()).strip()
                    if comment_txt:
                        loc_tb = _local_shape_bbox(el, defs_by_id, width, height)
                        if loc_tb is not None:
                            g_tb = _xform_bbox(cur_ctm, *loc_tb)
                            est_fs = max(6.0, min(36.0, g_tb[3] - g_tb[1]))
                            texts.append(SvgTextItem(text=comment_txt, bbox=g_tb, font_size=est_fs))
                    return

            if local == "image":
                href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
                sha = hashlib.sha256(href.encode()).hexdigest()
                ix = _parse_len(el.get("x"), 0.0, width)
                iy = _parse_len(el.get("y"), 0.0, height)
                iw = _parse_len(el.get("width"), 100.0, width)
                ih = _parse_len(el.get("height"), 100.0, height)
                ibb = _xform_bbox(cur_ctm, ix, iy, ix + iw, iy + ih)
                evidence_regions.append(
                    EvidenceRegion(
                        region_id=f"ev_img_{len(evidence_regions) + 1}",
                        xobject_name=el.get("id", f"image_{len(evidence_regions) + 1}"),
                        panel_id="Panel A",
                        bbox=ibb,
                        width_px=max(1, int(round(iw))),
                        height_px=max(1, int(round(ih))),
                        mutability="class0_sacrosanct_evidence",
                        subtype_label="svg_embedded_raster",
                        sha256_original=sha,
                        reason="Raw image pixels are never changed.",
                    )
                )
                return

            if local == "text":
                txt_str = " ".join("".join(el.itertext()).split()).strip()
                if txt_str:
                    inline_t = _parse_style_attr(el.get("style"))
                    fs = _parse_len(inline_t.get("font-size") or el.get("font-size"), 11.0, height)
                    tx = _parse_len(el.get("x", "0").split()[0] if el.get("x") else "0", 0.0, width)
                    ty = _parse_len(el.get("y", "0").split()[0] if el.get("y") else "0", 0.0, height)
                    for child in el:
                        if isinstance(child.tag, str) and etree.QName(child).localname == "tspan":
                            if child.get("x") and tx == 0.0:
                                tx = _parse_len(child.get("x", "0").split()[0], 0.0, width)
                            if child.get("y") and ty == 0.0:
                                ty = _parse_len(child.get("y", "0").split()[0], 0.0, height)
                    anchor = (inline_t.get("text-anchor") or el.get("text-anchor") or "start").strip().lower()
                    approx_w = max(fs * 0.6, len(txt_str) * fs * 0.54)
                    if anchor == "middle":
                        lx0, lx1 = tx - 0.5 * approx_w, tx + 0.5 * approx_w
                    elif anchor == "end":
                        lx0, lx1 = tx - approx_w, tx
                    else:
                        lx0, lx1 = tx, tx + approx_w
                    tbb = _xform_bbox(cur_ctm, lx0, ty - fs * 0.85, lx1, ty + fs * 0.2)
                    scale_f = math.hypot(cur_ctm[0], cur_ctm[1]) or 1.0
                    texts.append(SvgTextItem(text=txt_str, bbox=tbb, font_size=fs * scale_f))
                return

            if local in _SHAPE_TAGS:
                if local == "use":
                    href_chk = (el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or "").strip()
                    ref_chk = href_chk[1:] if href_chk.startswith("#") else ""
                    # Skip Cairo/R/Matplotlib outlined font glyph `<use>` references (`glyph0-1`, `DejaVuSans-41`, etc.)
                    if re.match(
                        r"^(?:glyph\d+-\d+|(?:DejaVu|Arial|Helvetica|Liberation|Nimbus|CM[A-Z]+|STIX|Bitstream|Times|Courier)[A-Za-z0-9_]*-[0-9a-fA-F]+)$",
                        ref_chk,
                    ):
                        return
                loc_bb = _local_shape_bbox(el, defs_by_id, width, height)
                if loc_bb is not None:
                    g_bb = _xform_bbox(cur_ctm, *loc_bb)
                    use_ref_id: str | None = None
                    final_f = eff_fill
                    final_s = eff_stroke
                    if local == "use":
                        href = (el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or "").strip()
                        ref_id = href[1:] if href.startswith("#") else ""
                        ref_el = defs_by_id.get(ref_id)
                        if ref_el is not None:
                            use_ref_id = ref_id
                            rf, rs, _, _ = _effective_props(ref_el, [], None, None, eff_col, 1.0)
                            if (rf is None and rs is None) and etree.QName(ref_el).localname in ("g", "symbol"):
                                for sub_ch in ref_el:
                                    if isinstance(sub_ch.tag, str) and etree.QName(sub_ch).localname in _SHAPE_TAGS:
                                        crf, crs, _, _ = _effective_props(sub_ch, [ref_el], None, None, eff_col, 1.0)
                                        rf = rf or crf
                                        rs = rs or crs
                            if rf and rf != "none" and (final_f is None or final_f == "none"):
                                final_f = rf
                                defs_ids_to_strip_color.add(ref_id)
                            elif rf and rf != "none":
                                defs_ids_to_strip_color.add(ref_id)
                            if rs and rs != "none" and (final_s is None or final_s == "none"):
                                final_s = rs
                                defs_ids_to_strip_color.add(ref_id)
                            elif rs and rs != "none":
                                defs_ids_to_strip_color.add(ref_id)

                    # In SVG, default fill when unspecified is black (#000000) except on <line>/<polyline>
                    if final_f is None and local not in ("line",):
                        final_f = "#000000"
                    grad_ref = _extract_grad_id_ref(final_f)
                    hx_f = None if (not final_f or final_f == "none" or grad_ref) else final_f
                    hx_s = None if (not final_s or final_s == "none" or final_s.startswith("url(")) else final_s

                    inline_sh = _parse_style_attr(el.get("style"))
                    dash_val = (inline_sh.get("stroke-dasharray") or el.get("stroke-dasharray") or "").strip().lower()
                    has_dash = bool(dash_val and dash_val not in ("none", "0"))
                    in_axis_g = any(
                        (anc.get("id") or "").startswith(("matplotlib.axis_", "xtick_", "ytick_"))
                        for anc in ancestors
                    )

                    is_bg_w = False
                    if local == "rect" and hx_f:
                        Lf, Cf, _ = hex_to_oklch(hx_f)
                        bw = g_bb[2] - g_bb[0]
                        bh = g_bb[3] - g_bb[1]
                        if Lf > 0.975 and Cf < 0.015 and bw > 0.55 * width and bh > 0.55 * height:
                            is_bg_w = True

                    raw_instances.append(
                        SvgPaintInstance(
                            elem_idx=elem_to_idx[id(el)],
                            panel_id="Panel A",
                            bbox=g_bb,
                            fill_hex=hx_f,
                            stroke_hex=hx_s,
                            grad_id=grad_ref if (grad_ref and grad_ref in grad_id_to_scale) else None,
                            is_bg_white=is_bg_w,
                            use_ref_id=use_ref_id,
                            alpha=eff_alpha,
                            is_dashed=has_dash,
                            in_axis_group=in_axis_g,
                            is_line_only=(local in ("line", "polyline") or hx_f is None),
                        )
                    )
                return

        next_anc = ancestors + [el]
        for child in el:
            _walk(child, next_anc, cur_ctm, eff_fill, eff_stroke, eff_col, eff_alpha, now_in_defs)

    svg_clip_rects: list[tuple[float, float, float, float]] = []
    for el_cp in all_elems:
        if isinstance(el_cp.tag, str) and etree.QName(el_cp).localname == "clipPath":
            shape_children = [
                ch for ch in el_cp if isinstance(ch.tag, str) and etree.QName(ch).localname in _SHAPE_TAGS
            ]
            if len(shape_children) == 1:
                cbb = _local_shape_bbox(shape_children[0], defs_by_id, width, height)
                if cbb is not None:
                    c_mat = _parse_svg_transform(shape_children[0].get("transform"))
                    svg_clip_rects.append(_xform_bbox(c_mat, *cbb))

    _walk(root, [], (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), None, None, "#000000", 1.0, False)

    panels = _detect_svg_panels(texts, width, height, filename, clip_rects=svg_clip_rects)
    for t in texts:
        t.panel_id = _assign_panel(t.bbox, panels)
    for ev in evidence_regions:
        ev.panel_id = _assign_panel(ev.bbox, panels)
    for inst in raw_instances:
        inst.panel_id = _assign_panel(inst.bbox, panels)

    def _is_mutable_svg_color(hx: str, bbox: tuple[float, float, float, float], is_bg_w: bool) -> bool:
        if is_bg_w:
            return False
        L, C, _ = hex_to_oklch(hx)
        if L > 0.985 and C < 0.015:
            return False
        if L < 0.09 and C < 0.015:
            return False
        # Structural gridlines / axes / frames: near-achromatic neutral gray
        if C < 0.012:
            bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if L > 0.88 and (bw * bh > 900.0 or max(bw, bh) > 0.45 * max(width, height)):
                return False
            if (bw < 1.5 and bh > 18.0) or (bh < 1.5 and bw > 18.0):
                return False
        return True

    # Collect mutable fill/stroke paint records per (panel_id, hex), separating overlay points vs area/line when >= 3 points!
    panel_hex_records: dict[tuple[str, str], list[tuple[SvgPaintInstance, Literal["fill", "stroke"], bool]]] = {}
    for inst in raw_instances:
        bw = inst.bbox[2] - inst.bbox[0]
        bh = inst.bbox[3] - inst.bbox[1]
        is_pt = max(bw, bh) <= 18.0
        has_mut_fill = bool(
            inst.fill_hex
            and not (inst.in_axis_group and hex_to_oklch(inst.fill_hex)[1] < 0.014)
            and _is_mutable_svg_color(inst.fill_hex, inst.bbox, inst.is_bg_white)
        )
        if has_mut_fill and inst.fill_hex:
            panel_hex_records.setdefault((inst.panel_id, inst.fill_hex), []).append((inst, "fill", is_pt))

        if inst.stroke_hex and _is_mutable_svg_color(inst.stroke_hex, inst.bbox, False):
            _, Cs, _ = hex_to_oklch(inst.stroke_hex)
            # Protect achromatic outline strokes on differently-colored fills, dashed threshold lines, and axis ticks
            if Cs < 0.014 and (
                inst.in_axis_group
                or inst.is_dashed
                or (inst.fill_hex is not None and inst.fill_hex.upper() != inst.stroke_hex.upper())
            ):
                continue
            panel_hex_records.setdefault((inst.panel_id, inst.stroke_hex), []).append((inst, "stroke", is_pt))

    color_groups: dict[str, ColorGroup] = {}
    sibling_layer_pairs: list[tuple[str, str]] = []

    def _emit_svg_group(
        pid_g: str,
        hx_g: str,
        recs: list[tuple[SvgPaintInstance, Literal["fill", "stroke"], bool]],
        m_kind: Literal["area", "point", "line"],
    ) -> str:
        gid = f"g_{len(color_groups) + 1:03d}"
        has_fill_r = any(r_kind == "fill" for _, r_kind, _ in recs)
        seen_inst_ids: set[int] = set()
        tot_area = 0.0
        min_mk = 9999.0
        bx0, by0, bx1, by1 = 1e9, 1e9, -1e9, -1e9
        alpha_v = recs[0][0].alpha
        for inst_r, r_kind, _ in recs:
            if r_kind == "fill":
                inst_r.fill_gid = gid
            else:
                inst_r.stroke_gid = gid
            if inst_r.elem_idx not in seen_inst_ids:
                seen_inst_ids.add(inst_r.elem_idx)
                iw_r = inst_r.bbox[2] - inst_r.bbox[0]
                ih_r = inst_r.bbox[3] - inst_r.bbox[1]
                tot_area += max(1.0, iw_r * ih_r)
                min_mk = min(min_mk, max(0.5, min(iw_r, ih_r)))
                bx0 = min(bx0, inst_r.bbox[0])
                by0 = min(by0, inst_r.bbox[1])
                bx1 = max(bx1, inst_r.bbox[2])
                by1 = max(by1, inst_r.bbox[3])
        color_groups[gid] = ColorGroup(
            group_id=gid,
            panel_id=pid_g,
            role="fill" if has_fill_r else "stroke",
            original_hex=hx_g,
            current_hex=hx_g,
            alpha=round(alpha_v, 3),
            primitive_count=max(1, len(seen_inst_ids)),
            total_area_pt2=round(tot_area, 2),
            min_mark_pt=round(min_mk if min_mk < 9000.0 else 1.0, 2),
            sample_bbox=(round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2)),
            mark_kind=m_kind,
        )
        return gid

    for (pid_g, hx_g), recs in panel_hex_records.items():
        pt_recs = [r for r in recs if r[2]]
        non_pt_recs = [r for r in recs if not r[2]]
        n_pt_elems = len({r[0].elem_idx for r in pt_recs})
        if non_pt_recs and pt_recs and n_pt_elems >= 3:
            base_kind: Literal["area", "line"] = "area" if any(r[1] == "fill" for r in non_pt_recs) else "line"
            gid_base = _emit_svg_group(pid_g, hx_g, non_pt_recs, base_kind)
            gid_pts = _emit_svg_group(pid_g, hx_g, pt_recs, "point")
            sibling_layer_pairs.append((gid_base, gid_pts))
        elif non_pt_recs:
            base_kind = "area" if any(r[1] == "fill" for r in non_pt_recs) else "line"
            _emit_svg_group(pid_g, hx_g, recs, base_kind)
        else:
            _emit_svg_group(pid_g, hx_g, recs, "point")

    if progress_cb:
        progress_cb("binding_legends", 68)

    _detect_svg_vector_colorbars(raw_instances, color_groups, continuous_scales, texts)
    _bind_svg_legend_labels(raw_instances, color_groups, texts, panels)

    # Sync labels across same-(panel, original_hex) sibling layers (`area`/`line` <-> `point`)
    hex_panel_label: dict[tuple[str, str], str] = {}
    for cg in color_groups.values():
        if cg.local_label and not cg.is_continuous_member:
            hex_panel_label[(cg.panel_id, cg.original_hex)] = cg.local_label
    for cg in color_groups.values():
        if not cg.local_label and not cg.is_continuous_member:
            shared = hex_panel_label.get((cg.panel_id, cg.original_hex))
            if shared:
                cg.local_label = shared

    # Propagate unambiguous shared figure-wide legend labels across sibling panels (e.g. `fig.legend`, `facet_wrap`)
    if len(panels) > 1:
        labeled_cgs = [cg for cg in color_groups.values() if cg.local_label and not cg.is_continuous_member]
        if labeled_cgs:
            lbl_srgbs = np.stack([hex_to_srgb01(cg.original_hex) for cg in labeled_cgs], axis=0)
            for cg in color_groups.values():
                if cg.local_label or cg.is_continuous_member:
                    continue
                d_vec = ciede2000_matrix(hex_to_srgb01(cg.original_hex)[None, :], lbl_srgbs)[0]
                near_idxs = [idx_l for idx_l, dv in enumerate(d_vec) if float(dv) < 2.0]
                if not near_idxs:
                    continue
                cand_norms = {
                    re.sub(r"\s*\([^)]*\)\s*$", "", labeled_cgs[idx_l].local_label).strip().lower()
                    for idx_l in near_idxs
                }
                if len(cand_norms) != 1:
                    continue
                best_lbl = labeled_cgs[min(near_idxs, key=lambda idx_l: float(d_vec[idx_l]))].local_label
                target_norm = next(iter(cand_norms))
                panel_conflict = any(
                    other.panel_id == cg.panel_id
                    and other.local_label
                    and re.sub(r"\s*\([^)]*\)\s*$", "", other.local_label).strip().lower() == target_norm
                    and float(
                        ciede2000_matrix(
                            hex_to_srgb01(cg.original_hex)[None, :],
                            hex_to_srgb01(other.original_hex)[None, :],
                        )[0, 0]
                    )
                    >= 5.0
                    for other in color_groups.values()
                )
                if not panel_conflict:
                    cg.local_label = best_lbl

    # Prune unlabeled pure-achromatic stroke-only groups (boxplot whiskers, medians, caps, error bars, gray spines)
    for gid_p in list(color_groups.keys()):
        cg_p = color_groups[gid_p]
        if cg_p.is_continuous_member or cg_p.role != "stroke" or cg_p.local_label:
            continue
        _, C_p, _ = hex_to_oklch(cg_p.original_hex)
        if C_p < 0.012:
            for inst_p in raw_instances:
                if inst_p.stroke_gid == gid_p:
                    inst_p.stroke_gid = None
            del color_groups[gid_p]

    entities: dict[str, SemanticEntity] = {}
    label_to_eid: dict[str, str] = {}
    hex_panel_to_eid: dict[tuple[str, str], str] = {}
    label_panel_hexes: dict[str, list[tuple[str, str, str]]] = {}

    for cg in color_groups.values():
        if cg.is_continuous_member:
            continue
        raw_lbl = cg.local_label.strip()
        norm_key = re.sub(r"\s*\([^)]*\)\s*$", "", raw_lbl).strip().lower() if raw_lbl else ""
        hp_key = (cg.panel_id, cg.original_hex)
        if norm_key and norm_key in label_to_eid:
            eid = label_to_eid[norm_key]
            ent = entities[eid]
            ent.member_group_ids.append(cg.group_id)
            if cg.panel_id not in ent.panels:
                ent.panels.append(cg.panel_id)
            hex_panel_to_eid[hp_key] = eid
            label_panel_hexes[norm_key].append((cg.panel_id, cg.original_hex, eid))
        elif not norm_key and hp_key in hex_panel_to_eid:
            eid = hex_panel_to_eid[hp_key]
            ent = entities[eid]
            ent.member_group_ids.append(cg.group_id)
            tot_cnt = sum(color_groups[g].primitive_count for g in ent.member_group_ids if g in color_groups)
            ent.label = describe_color_group(ent.original_hex, tot_cnt)
        else:
            eid = f"e_{len(entities) + 1:02d}"
            disp = (
                re.sub(r"\s*\([^)]*\)\s*$", "", raw_lbl).strip()
                if raw_lbl
                else describe_color_group(cg.original_hex, cg.primitive_count)
            )
            if norm_key:
                label_to_eid[norm_key] = eid
                label_panel_hexes[norm_key] = [(cg.panel_id, cg.original_hex, eid)]
            hex_panel_to_eid[hp_key] = eid
            low_l = disp.lower()
            is_ctrl = any(
                low_l == pat or low_l.startswith(pat + "_") or low_l.startswith(pat + " ")
                for pat in _CONTROL_PATTERNS
            )
            entities[eid] = SemanticEntity(
                entity_id=eid,
                label=disp,
                category_group=cg.panel_id,
                panels=[cg.panel_id],
                member_group_ids=[cg.group_id],
                original_hex=cg.original_hex,
                current_hex=cg.current_hex,
                tier="normal",
                is_control_candidate=is_ctrl,
            )

    collisions: list[CollisionNotice] = []
    plain_notices: list[dict[str, Any]] = []
    for norm_key, ph_list in label_panel_hexes.items():
        if len(ph_list) >= 2:
            arr = np.stack([hex_to_srgb01(h) for _, h, _ in ph_list], axis=0)
            if float(ciede2000_matrix(arr).max()) >= 10.0:
                eid = ph_list[0][2]
                plain_notices.append(
                    {
                        "kind": "inconsistent_same_name",
                        "entity_ids": [eid],
                        "label": entities[eid].label,
                        "panel_a": ph_list[0][0],
                        "panel_b": ph_list[-1][0],
                    }
                )

    ent_list = list(entities.values())
    if len(ent_list) >= 2:
        srgbs = np.stack([hex_to_srgb01(e.original_hex) for e in ent_list], axis=0)
        de_norm = ciede2000_matrix(srgbs)
        de_deut = ciede2000_matrix(simulate_cvd(srgbs, "deutan", 1.0))
        de_prot = ciede2000_matrix(simulate_cvd(srgbs, "protan", 1.0))
        cb_by_panel: dict[str, set[str]] = {}
        for i in range(len(ent_list)):
            for j in range(i + 1, len(ent_list)):
                ea, eb = ent_list[i], ent_list[j]
                d_n = float(de_norm[i, j])
                d_cvd = min(float(de_deut[i, j]), float(de_prot[i, j]))
                shared = set(ea.panels) & set(eb.panels)
                if shared and (d_n < 12.0 or d_cvd < 8.5):
                    for sp_id in shared:
                        cb_by_panel.setdefault(sp_id, set()).update((ea.entity_id, eb.entity_id))
                    p_str = ", ".join(sorted(shared))
                    collisions.append(
                        CollisionNotice(
                            collision_id=f"col_{len(collisions) + 1:02d}",
                            scope="intra_panel",
                            original_hex_a=ea.original_hex,
                            original_hex_b=eb.original_hex,
                            delta_e00=round(d_n, 2),
                            entities_involved=[
                                {"entity_id": ea.entity_id, "label": ea.label, "panel_id": p_str},
                                {"entity_id": eb.entity_id, "label": eb.label, "panel_id": p_str},
                            ],
                            description=f"{ea.label} vs {eb.label} ({p_str})",
                        )
                    )
        for sp_id, eids in sorted(cb_by_panel.items()):
            plain_notices.insert(
                0,
                {
                    "kind": "colorblind_hard_to_tell",
                    "panel": sp_id,
                    "count": len(eids),
                    "entity_ids": sorted(eids),
                },
            )

    if progress_cb:
        progress_cb("rendering_preview", 88)

    paint_map = {inst.elem_idx: inst for inst in raw_instances}
    max_dim = max(width, height)
    preview_scale = min(2.5, max(1.0, 1600.0 / max(1.0, max_dim)))

    scene = SvgScene(
        scene_id=scene_id,
        filename=filename,
        raw_svg_bytes=svg_bytes,
        width=width,
        height=height,
        panels=panels,
        evidence_regions=evidence_regions,
        color_groups=color_groups,
        continuous_scales=continuous_scales,
        entities=entities,
        collisions=collisions,
        geometry_hash_original=geom_hash,
        grad_id_to_scale=grad_id_to_scale,
        paint_instances=paint_map,
        defs_ids_to_strip_color=defs_ids_to_strip_color,
        plain_notices=plain_notices[:2],
        preview_scale=preview_scale,
    )
    _render_svg_layers(scene)
    if progress_cb:
        progress_cb("ready", 100)
    return scene


def _apply_inline_paint(el: etree._Element, fill_val: str | None, stroke_val: str | None) -> None:
    style_map = _parse_style_attr(el.get("style"))
    if fill_val is not None:
        el.set("fill", fill_val)
        if "fill" in style_map or el.get("class"):
            style_map["fill"] = fill_val
    if stroke_val is not None:
        el.set("stroke", stroke_val)
        if "stroke" in style_map or el.get("class"):
            style_map["stroke"] = stroke_val
    if style_map:
        el.set("style", ";".join(f"{k}:{v}" for k, v in style_map.items()))


def _strip_element_paint_for_use_cascade(el: etree._Element) -> None:
    for node in el.iter():
        if not isinstance(node.tag, str):
            continue
        for attr in ("fill", "stroke"):
            if attr in node.attrib and node.attrib[attr].strip().lower() != "none":
                del node.attrib[attr]
        if node.get("style"):
            smap = _parse_style_attr(node.get("style"))
            for attr in ("fill", "stroke"):
                if attr in smap and smap[attr].strip().lower() != "none":
                    del smap[attr]
            if smap:
                node.set("style", ";".join(f"{k}:{v}" for k, v in smap.items()))
            else:
                del node.attrib["style"]


def _render_svg_layers(scene: SvgScene) -> None:
    """Build original/id_map SVG & crisp resvg PNG buffers for uniform picking and outlines."""
    scene.original_svg = scene.raw_svg_bytes
    cat_ids = [gid for gid, cg in scene.color_groups.items() if not cg.is_continuous_member]
    cat_gid_to_idx = {gid: i for i, gid in enumerate(cat_ids)}
    scale_ids = list(scene.continuous_scales.keys())
    sid_to_code = {sid: 254 - i for i, sid in enumerate(scale_ids)}
    panel_to_idx = {p.panel_id: idx + 1 for idx, p in enumerate(scene.panels)}

    def _build_id_map_svg() -> bytes:
        parser = etree.XMLParser(remove_blank_text=False, recover=True)
        root = etree.fromstring(scene.raw_svg_bytes, parser=parser)
        all_elems = list(root.iter())
        svg_ns = root.nsmap.get(None, "http://www.w3.org/2000/svg")
        root.set("shape-rendering", "crispEdges")

        for idx, el in enumerate(all_elems):
            if not isinstance(el.tag, str) or el is root:
                continue
            local = etree.QName(el).localname
            if el.get("id") in scene.defs_ids_to_strip_color:
                _strip_element_paint_for_use_cascade(el)
            if local in ("linearGradient", "radialGradient"):
                gid_attr = el.get("id", "")
                sid = scene.grad_id_to_scale.get(gid_attr)
                if sid:
                    s_code = sid_to_code[sid]
                    p_code = panel_to_idx.get(scene.continuous_scales[sid].panel_id, 1)
                    for child in list(el):
                        if isinstance(child.tag, str) and etree.QName(child).localname == "stop":
                            el.remove(child)
                    for idx_s, g_val in ((0, 0), (1, 255)):
                        st = etree.SubElement(el, f"{{{svg_ns}}}stop" if svg_ns else "stop")
                        st.set("offset", f"{idx_s * 100}%")
                        st.set("stop-color", f"rgb({s_code},{g_val},{p_code})")
                continue
            if local in ("text", "tspan", "image"):
                el.set("opacity", "0")
                continue
            if local not in _SHAPE_TAGS:
                continue

            inst = scene.paint_instances.get(idx)
            if inst is None or not (inst.fill_gid or inst.stroke_gid or inst.grad_id):
                el.set("opacity", "0")
                continue

            p_code = panel_to_idx.get(inst.panel_id, 1)
            f_rgb: str | None = "none"
            s_rgb: str | None = "none"
            if inst.grad_id:
                f_rgb = None
            elif inst.fill_gid:
                cg_f = scene.color_groups[inst.fill_gid]
                if cg_f.is_continuous_member and cg_f.continuous_scale_id:
                    r_u8 = sid_to_code[cg_f.continuous_scale_id]
                    g_u8 = int(round(cg_f.continuous_t * 255.0))
                else:
                    c_idx = cat_gid_to_idx[inst.fill_gid]
                    r_u8 = 1 + (c_idx % 240)
                    g_u8 = (c_idx // 240) & 0xFF
                f_rgb = f"rgb({r_u8},{g_u8},{p_code})"

            if inst.stroke_gid:
                cg_s = scene.color_groups[inst.stroke_gid]
                if cg_s.is_continuous_member and cg_s.continuous_scale_id:
                    r_u8 = sid_to_code[cg_s.continuous_scale_id]
                    g_u8 = int(round(cg_s.continuous_t * 255.0))
                else:
                    c_idx = cat_gid_to_idx[inst.stroke_gid]
                    r_u8 = 1 + (c_idx % 240)
                    g_u8 = (c_idx // 240) & 0xFF
                s_rgb = f"rgb({r_u8},{g_u8},{p_code})"

            el.set("opacity", "1")
            el.set("fill-opacity", "1" if (inst.fill_gid or inst.grad_id) else "0")
            el.set("stroke-opacity", "1" if inst.stroke_gid else "0")
            smap = _parse_style_attr(el.get("style"))
            for op_k in ("opacity", "fill-opacity", "stroke-opacity"):
                smap.pop(op_k, None)
            if smap:
                el.set("style", ";".join(f"{k}:{v}" for k, v in smap.items()))
            else:
                el.attrib.pop("style", None)
            _apply_inline_paint(el, f_rgb, s_rgb)

        bg = etree.Element(f"{{{svg_ns}}}rect" if svg_ns else "rect")
        bg.set("x", "0")
        bg.set("y", "0")
        bg.set("width", str(scene.width))
        bg.set("height", str(scene.height))
        bg.set("fill", "#000000")
        root.insert(0, bg)
        return etree.tostring(root, xml_declaration=True, encoding="utf-8")

    scene.id_map_svg = _build_id_map_svg()
    scene.structural_svg = scene.raw_svg_bytes
    scene.coverage_svg = scene.id_map_svg
    scene.original_png = render_svg_bytes_to_png(scene.raw_svg_bytes, zoom=scene.preview_scale, background="#ffffff")
    scene.id_map_png = resvg_py.svg_to_bytes(
        svg_string=_ensure_svg_dimensions_for_raster(scene.id_map_svg, scene.width, scene.height),
        dpi=96.0,
        zoom=scene.preview_scale,
        background="#000000",
        shape_rendering="crisp_edges",
    )


def _ensure_svg_dimensions_for_raster(svg_bytes: bytes, fallback_w: float = 800.0, fallback_h: float = 600.0) -> str:
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    root = etree.fromstring(svg_bytes, parser=parser)
    vb_raw = root.get("viewBox")
    if vb_raw:
        vb = [float(x) for x in _NUM_RE.findall(vb_raw)]
        rw = vb[2] if len(vb) >= 4 else fallback_w
        rh = vb[3] if len(vb) >= 4 else fallback_h
    else:
        rw = _parse_len(root.get("width"), fallback_w, fallback_w)
        rh = _parse_len(root.get("height"), fallback_h, fallback_h)
    root.set("width", f"{max(1.0, rw):.2f}")
    root.set("height", f"{max(1.0, rh):.2f}")
    return etree.tostring(root, encoding="unicode")


def render_svg_bytes_to_png(
    svg_bytes: bytes,
    dpi: float = 96.0,
    zoom: float | None = None,
    background: str = "#ffffff",
) -> bytes:
    z = zoom if zoom is not None else (dpi / 96.0)
    return resvg_py.svg_to_bytes(
        svg_string=_ensure_svg_dimensions_for_raster(svg_bytes),
        dpi=96.0,
        zoom=float(z),
        background=background,
    )


def render_svg_preview_png(
    scene: SvgScene,
    group_hex_map: dict[str, str],
    scale_stops_map: dict[str, list[str]],
    scale: float | None = None,
) -> bytes:
    svg_out, _ = export_recolored_svg(scene, group_hex_map, scale_stops_map)
    z = float(scale) if scale is not None else scene.preview_scale
    return render_svg_bytes_to_png(svg_out, zoom=z, background="#ffffff")


def export_recolored_svg(
    scene: SvgScene,
    group_hex_map: dict[str, str],
    scale_stops_map: dict[str, list[str]],
) -> tuple[bytes, dict[str, Any]]:
    resolved_group_hex = dict(group_hex_map)
    scale_modified: dict[str, bool] = {}
    scale_luts: dict[str, np.ndarray] = {}

    for sid, cs in scene.continuous_scales.items():
        stops = scale_stops_map.get(sid, cs.current_stops_hex)
        is_orig = (
            not cs.inverted_polarity
            and [s.upper() for s in stops] == [s.upper() for s in cs.original_stops_hex]
        )
        scale_modified[sid] = not is_orig
        if is_orig:
            continue
        if cs.inverted_polarity:
            stops = list(reversed(stops))
        mid = cs.midpoint_t if cs.kind == "continuous_diverging" else None
        lut = interpolate_oklch_lut(stops, n=256, diverging_midpoint=mid)
        scale_luts[sid] = lut
        for gid in cs.member_group_ids:
            cg = scene.color_groups[gid]
            idx = int(round(cg.continuous_t * 255.0))
            resolved_group_hex[gid] = srgb01_to_hex(lut[max(0, min(255, idx))])

    any_changed = any(
        resolved_group_hex.get(gid, cg.original_hex).upper() != cg.original_hex.upper()
        for gid, cg in scene.color_groups.items()
    ) or any(scale_modified.values())
    if not any_changed:
        return scene.raw_svg_bytes, {
            "g0_evidence_bit_identical": True,
            "g0_locked_objects": [
                {"xobject": ev.xobject_name, "sha256_match": True} for ev in scene.evidence_regions
            ],
            "g6_geometry_hash_before": scene.geometry_hash_original,
            "g6_geometry_hash_after": scene.geometry_hash_original,
            "g6_geometry_identical": True,
            "modified_vector_ops": 0,
            "modified_colorbar_rasters": 0,
            "g3b_inverted_cell_labels": 0,
        }

    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    root = etree.fromstring(scene.raw_svg_bytes, parser=parser)
    all_elems = list(root.iter())

    mod_ops = 0
    mod_grads = 0
    svg_ns = root.nsmap.get(None, "http://www.w3.org/2000/svg")

    for idx, el in enumerate(all_elems):
        if not isinstance(el.tag, str):
            continue
        local = etree.QName(el).localname
        if el.get("id") in scene.defs_ids_to_strip_color:
            _strip_element_paint_for_use_cascade(el)

        if local in ("linearGradient", "radialGradient"):
            gid_attr = el.get("id", "")
            sid = scene.grad_id_to_scale.get(gid_attr)
            if sid and scale_modified.get(sid, False):
                cs = scene.continuous_scales[sid]
                stops = list(scale_stops_map.get(sid, cs.current_stops_hex))
                if cs.inverted_polarity:
                    stops = list(reversed(stops))
                mid = cs.midpoint_t if cs.kind == "continuous_diverging" else None
                lut7 = interpolate_oklch_lut(stops, n=7, diverging_midpoint=mid)
                for child in list(el):
                    if isinstance(child.tag, str) and etree.QName(child).localname == "stop":
                        el.remove(child)
                for idx_s, row in enumerate(lut7):
                    st_el = etree.SubElement(el, f"{{{svg_ns}}}stop" if svg_ns else "stop")
                    st_el.set("offset", f"{round(idx_s * 100.0 / 6.0, 2)}%")
                    st_el.set("stop-color", srgb01_to_hex(row))
                    if idx_s not in (0, 6):
                        st_el.set("data-danqing-interp", "1")
                mod_grads += 1
            continue

        inst = scene.paint_instances.get(idx)
        if inst is None:
            continue
        new_f: str | None = None
        new_s: str | None = None
        if inst.fill_gid and inst.fill_gid in resolved_group_hex:
            cand_f = resolved_group_hex[inst.fill_gid]
            if cand_f.upper() != (inst.fill_hex or "").upper():
                new_f = cand_f
        elif inst.use_ref_id and inst.use_ref_id in scene.defs_ids_to_strip_color and inst.fill_hex:
            new_f = inst.fill_hex

        if inst.stroke_gid and inst.stroke_gid in resolved_group_hex:
            cand_s = resolved_group_hex[inst.stroke_gid]
            if cand_s.upper() != (inst.stroke_hex or "").upper():
                new_s = cand_s
        elif inst.use_ref_id and inst.use_ref_id in scene.defs_ids_to_strip_color and inst.stroke_hex:
            new_s = inst.stroke_hex

        if new_f is not None or new_s is not None:
            _apply_inline_paint(el, new_f, new_s)
            mod_ops += (1 if new_f is not None else 0) + (1 if new_s is not None else 0)

    out_bytes = etree.tostring(root, xml_declaration=True, encoding="utf-8")

    # Verify G0 embedded raster <image> integrity
    root_check = etree.fromstring(out_bytes, parser=parser)
    imgs_after = [
        e for e in root_check.iter() if isinstance(e.tag, str) and etree.QName(e).localname == "image"
    ]
    g0_ok = len(imgs_after) == len(scene.evidence_regions)
    g0_audit: list[dict[str, Any]] = []
    for ev, img_el in zip(scene.evidence_regions, imgs_after):
        href = img_el.get("{http://www.w3.org/1999/xlink}href") or img_el.get("href") or ""
        same = hashlib.sha256(href.encode()).hexdigest() == ev.sha256_original
        if not same:
            g0_ok = False
        g0_audit.append({"xobject": ev.xobject_name, "sha256_match": same})

    geom_after = canonical_svg_geometry_hash(out_bytes)
    g6_ok = geom_after == scene.geometry_hash_original
    if not g0_ok:
        raise RuntimeError("SVG Gate G0 raw image integrity check failed")
    if not g6_ok:
        raise RuntimeError("SVG Gate G6 geometry invariance failed")
    return out_bytes, {
        "g0_evidence_bit_identical": g0_ok,
        "g0_locked_objects": g0_audit,
        "g6_geometry_hash_before": scene.geometry_hash_original,
        "g6_geometry_hash_after": geom_after,
        "g6_geometry_identical": g6_ok,
        "modified_vector_ops": mod_ops,
        "modified_colorbar_rasters": mod_grads,
        "g3b_inverted_cell_labels": 0,
    }
