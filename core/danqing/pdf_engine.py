"""Streaming PDF scene parser, multi-colorspace & recursive Form XObject rewriter, and WYSIWYG preview renderer.

Supports (Spec Section 9 / WP4):
- DeviceRGB (`rg/RG`), DeviceGray (`g/G`), DeviceCMYK (`k/K`)
- Named ColorSpaces (`cs/CS` + `sc/scn/SC/SCN`): ICCBased (1/3/4ch), CalRGB, CalGray, Lab, Indexed LUT, Separation/Spot (`/FunctionType 2`), DeviceN
- Recursive `/Subtype /Form` XObject traversal & stream rewriting (page-isolated on multi-page PDFs)
- Multi-page PDF inspection (`inspect_pdf_document`) + `page_index` selection + scanned-page detection
- Bezier curve (`c/v/y`) & per-subpath bounding boxes (accurate scatter circle & low-chroma slate `#C9D6DF` category detection)
- Generalized legend key binding (rectangles, circles, line segments, hollow symbols; right or below text; multi-column stacks)
- Human-readable fallback element names (`"Blue group · 1,234 marks"`)

License: Apache-2.0 (uses pikepdf [MPL-2.0] and pypdfium2 [Apache-2.0/BSD] — zero GPL/AGPL code).
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pikepdf
import pypdfium2 as pdfium
from PIL import Image

# PDFium C++ library is strictly single-threaded across the entire OS process,
# including handle creation, rendering, and destruction (`close()`).
PDFIUM_LOCK = threading.RLock()


def render_pdf_page_to_pil(
    pdf_bytes: bytes,
    page_index: int = 0,
    scale: float = 1.0,
    fill_color: tuple[int, int, int, int] = (255, 255, 255, 255),
    no_smooth: bool = False,
) -> Image.Image:
    """Thread-safe PDFium page renderer with deterministic C++ handle cleanup inside PDFIUM_LOCK."""
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_bytes)
        try:
            page = doc[page_index]
            try:
                if no_smooth:
                    bitmap = page.render(
                        scale=scale,
                        fill_color=fill_color,
                        no_smoothpath=True,
                        no_smoothtext=True,
                        no_smoothimage=True,
                    )
                else:
                    bitmap = page.render(scale=scale, fill_color=fill_color)
                try:
                    return bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            doc.close()

from .color_science import (
    ciede2000_matrix,
    describe_color_group,
    hex_to_oklch,
    hex_to_srgb01,
    interpolate_oklch_lut,
    optimal_cell_text_hex,
    project_colors_onto_lut,
    simulate_cvd,
    srgb01_to_hex,
    srgb_to_oklab,
)
from .evidence_shield import classify_raster_object
from .ir import (
    CellTextLabel,
    CollisionNotice,
    ColorGroup,
    ContinuousScale,
    EvidenceRegion,
    PanelBox,
    SemanticEntity,
)

_CONTROL_PATTERNS = (
    "igg",
    "vehicle",
    "ctrl",
    "control",
    "wt",
    "wildtype",
    "sham",
    "pbs",
    "dmso",
    "nc",
    "pass",
    "uninfected",
    "naive",
)

# Possessive left-factored PDF operator scanner (Python 3.11+ atomic/possessive quantifiers -> zero backtracking on 50+ MB streams)
_NUM_P = rb"[+-]?(?:\d++\.?\d*+|\.\d++)"
_STREAM_CMD_RE = re.compile(
    rb"(?<![A-Za-z0-9_./])(?:"
    rb"(?P<tf>/[A-Za-z0-9_.-]++\s++" + _NUM_P + rb"\s++Tf)|"
    rb"(?P<tr>[0-7]\s++Tr)|"
    rb"(?P<numop>(?:" + _NUM_P + rb"\s++)++(?:/[A-Za-z0-9_.-]++\s++)?(?:cm|Tm|T[dD]|re|rg|RG|g|G|k|K|scn?|SCN?|m|l|c|v|y))|"
    rb"(?P<cs>/[A-Za-z0-9_.-]++\s++(?:cs|CS))|"
    rb"(?P<q>q)|(?P<Q>Q)|"
    rb"(?P<BT>BT)|(?P<ET>ET)|"
    rb"(?P<h>h)|"
    rb"(?P<clip>W\*?\s++n)|"
    rb"(?P<gs>/[A-Za-z0-9_.-]++\s++gs)|"
    rb"(?P<do>/[A-Za-z0-9_.-]++\s++Do)|"
    rb"(?P<sh>/[A-Za-z0-9_.-]++\s++sh)|"
    rb"(?P<dash>\[[^\]]*+\]\s*+" + _NUM_P + rb"\s++d)|"
    rb"(?P<paint>f\*?|F|B\*?|b\*?|S|s)|"
    rb"(?P<tj>TJ|Tj)"
    rb")(?![A-Za-z0-9_])"
)

_COLOR_STRIP_RE = re.compile(
    rb"(?<![A-Za-z0-9_./])(?:"
    rb"(?:" + _NUM_P + rb"\s++)++(?:/[A-Za-z0-9_.-]++\s++)?(?:rg|RG|g|G|k|K|scn?|SCN?)|"
    rb"/[A-Za-z0-9_.-]++\s++(?:cs|CS)|"
    rb"/Dq[FS]A\d{1,3}\s++gs"
    rb")(?![A-Za-z0-9_])"
)


def _mat_mul(m1: tuple[float, ...], m2: tuple[float, ...]) -> tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _apply_ctm(ctm: tuple[float, ...], x: float, y: float, page_h: float) -> tuple[float, float]:
    a, b, c, d, e, f = ctm
    pdf_x = a * x + c * y + e
    pdf_y = b * x + d * y + f
    return pdf_x, page_h - pdf_y


def _rect_to_page_bbox(
    ctm: tuple[float, ...], rx: float, ry: float, rw: float, rh: float, page_h: float
) -> tuple[float, float, float, float]:
    pts = [
        _apply_ctm(ctm, rx, ry, page_h),
        _apply_ctm(ctm, rx + rw, ry, page_h),
        _apply_ctm(ctm, rx, ry + rh, page_h),
        _apply_ctm(ctm, rx + rw, ry + rh, page_h),
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _cmyk_to_rgb01(c: float, m: float, y: float, k: float) -> tuple[float, float, float]:
    c_c, m_c, y_c, k_c = (max(0.0, min(1.0, v)) for v in (c, m, y, k))
    return ((1.0 - c_c) * (1.0 - k_c), (1.0 - m_c) * (1.0 - k_c), (1.0 - y_c) * (1.0 - k_c))


def _hash_resources_recursively(res: pikepdf.Object | None, h: hashlib._Hash, visited: set[tuple[int, int]]) -> None:
    if not res or "/XObject" not in res:
        return
    for k in sorted(res["/XObject"].keys()):
        xo = res["/XObject"][k]
        og = getattr(xo, "objgen", (0, 0))
        if og != (0, 0) and og in visited:
            continue
        if og != (0, 0):
            visited.add(og)
        st = str(xo.get("/Subtype", ""))
        if st == "/Image":
            w = int(xo.get("/Width", 0))
            ht = int(xo.get("/Height", 0))
            h.update(f"xo:{k}:{st}:{w}x{ht}\n".encode())
        elif st == "/Form":
            try:
                f_bytes = xo.read_bytes()
            except Exception:
                f_bytes = b""
            stripped = _COLOR_STRIP_RE.sub(b" ", f_bytes)
            norm = re.sub(rb"\s+", b" ", stripped).strip()
            h.update(f"form:{k}:".encode() + norm + b"\n")
            _hash_resources_recursively(xo.get("/Resources"), h, visited)


def canonical_geometry_hash_pdf_bytes(pdf_bytes: bytes) -> str:
    """Gate G6: Compute SHA-256 over all non-color stream tokens (page + nested Form XObjects), image dims, and MediaBoxes."""
    h = hashlib.sha256()
    visited: set[tuple[int, int]] = set()
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        h.update(f"pages:{len(pdf.pages)}\n".encode())
        for idx, page in enumerate(pdf.pages):
            mb = [round(float(v), 4) for v in page.MediaBox]
            h.update(f"p{idx}:mb={mb}\n".encode())
            contents = page.obj.get("/Contents")
            if contents is not None:
                if isinstance(contents, pikepdf.Array):
                    raw_stream = b"\n".join(s.read_bytes() for s in contents)
                else:
                    raw_stream = contents.read_bytes()
                stripped = _COLOR_STRIP_RE.sub(b" ", raw_stream)
                norm = re.sub(rb"\s+", b" ", stripped).strip()
                h.update(norm)
            _hash_resources_recursively(page.obj.get("/Resources"), h, visited)
    return h.hexdigest()


def inspect_pdf_document(pdf_bytes: bytes, render_thumbnails: bool = True) -> dict[str, Any]:
    """Inspect a PDF before full scene parsing (multi-page detection, thumbnails, file-size/op-count check)."""
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_bytes)
        try:
            n_pages = len(doc)
            pages_info: list[dict[str, Any]] = []
            for idx in range(n_pages):
                pg = doc[idx]
                try:
                    w, h = pg.get_size()
                    thumb_url = ""
                    if render_thumbnails and n_pages > 1 and idx < 24:
                        sc = min(0.4, 180.0 / max(1.0, max(w, h)))
                        bitmap = pg.render(scale=sc, fill_color=(255, 255, 255, 255))
                        try:
                            pil = bitmap.to_pil().convert("RGB")
                        finally:
                            bitmap.close()
                        buf = io.BytesIO()
                        pil.save(buf, format="JPEG", quality=78)
                        thumb_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                    pages_info.append({"index": idx, "width": round(w, 1), "height": round(h, 1), "thumbnail": thumb_url})
                finally:
                    pg.close()
        finally:
            doc.close()
    return {
        "page_count": n_pages,
        "pages": pages_info,
        "size_bytes": len(pdf_bytes),
    }


@dataclass
class ColorSpaceInfo:
    name: str
    kind: str  # "rgb" | "gray" | "cmyk" | "indexed" | "separation" | "pattern"
    n_comp: int
    lut_rgb01: np.ndarray | None = None
    spot_rgb01: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _resolve_cs_obj(cs_obj: Any) -> ColorSpaceInfo:
    if isinstance(cs_obj, pikepdf.Name):
        nm = str(cs_obj)
        if nm in ("/DeviceRGB", "/CalRGB"):
            return ColorSpaceInfo(nm, "rgb", 3)
        if nm in ("/DeviceGray", "/CalGray"):
            return ColorSpaceInfo(nm, "gray", 1)
        if nm == "/DeviceCMYK":
            return ColorSpaceInfo(nm, "cmyk", 4)
        if nm == "/Pattern":
            return ColorSpaceInfo(nm, "pattern", 0)
        return ColorSpaceInfo(nm, "rgb", 3)

    if isinstance(cs_obj, pikepdf.Array) and len(cs_obj) >= 1:
        head = str(cs_obj[0])
        if head in ("/CalRGB", "/Lab"):
            return ColorSpaceInfo(head, "rgb", 3)
        if head == "/CalGray":
            return ColorSpaceInfo(head, "gray", 1)
        if head == "/Pattern":
            return ColorSpaceInfo(head, "pattern", 0)
        if head == "/ICCBased" and len(cs_obj) >= 2:
            try:
                n_c = int(cs_obj[1].get("/N", 3))
            except Exception:
                n_c = 3
            kind = "gray" if n_c == 1 else ("cmyk" if n_c == 4 else "rgb")
            return ColorSpaceInfo(head, kind, n_c)
        if head == "/Indexed" and len(cs_obj) >= 4:
            base_info = _resolve_cs_obj(cs_obj[1])
            hival = int(cs_obj[2])
            lookup_obj = cs_obj[3]
            try:
                raw_lut = lookup_obj.read_bytes() if isinstance(lookup_obj, pikepdf.Stream) else bytes(lookup_obj)
            except Exception:
                raw_lut = b""
            bpc = max(1, base_info.n_comp)
            lut = np.zeros((hival + 1, 3), dtype=np.float64)
            for idx in range(hival + 1):
                off = idx * bpc
                if off + bpc <= len(raw_lut):
                    vals = [raw_lut[off + j] / 255.0 for j in range(bpc)]
                    if base_info.kind == "gray":
                        lut[idx] = [vals[0], vals[0], vals[0]]
                    elif base_info.kind == "cmyk" and len(vals) >= 4:
                        lut[idx] = _cmyk_to_rgb01(vals[0], vals[1], vals[2], vals[3])
                    else:
                        lut[idx] = vals[:3] if len(vals) >= 3 else [vals[0]] * 3
            return ColorSpaceInfo(head, "indexed", 1, lut_rgb01=lut)
        if head == "/Separation" and len(cs_obj) >= 4:
            spot_name = str(cs_obj[1]).lstrip("/").lower()
            alt_info = _resolve_cs_obj(cs_obj[2])
            fn_obj = cs_obj[3]
            spot_rgb = (0.2, 0.2, 0.2)
            # Illustrator/Prism Spot colors use FunctionType 2 with /C1 at tint=1.0
            try:
                c1 = fn_obj.get("/C1")
                if c1 is not None:
                    c1_vals = [float(x) for x in c1]
                    if alt_info.kind == "cmyk" and len(c1_vals) >= 4:
                        spot_rgb = _cmyk_to_rgb01(*c1_vals[:4])
                    elif alt_info.kind == "gray" and len(c1_vals) >= 1:
                        spot_rgb = (c1_vals[0], c1_vals[0], c1_vals[0])
                    elif len(c1_vals) >= 3:
                        spot_rgb = (c1_vals[0], c1_vals[1], c1_vals[2])
                elif spot_name in ("cyan",):
                    spot_rgb = (0.0, 0.68, 0.94)
                elif spot_name in ("magenta",):
                    spot_rgb = (0.93, 0.0, 0.55)
                elif spot_name in ("yellow",):
                    spot_rgb = (1.0, 0.95, 0.0)
                elif spot_name in ("black", "all"):
                    spot_rgb = (0.0, 0.0, 0.0)
            except Exception:
                pass
            return ColorSpaceInfo(head, "separation", 1, spot_rgb01=spot_rgb)
        if head == "/DeviceN" and len(cs_obj) >= 4:
            try:
                n_names = len(cs_obj[1])
            except Exception:
                n_names = 3
            alt_info = _resolve_cs_obj(cs_obj[2])
            return ColorSpaceInfo(head, "cmyk" if n_names == 4 else "rgb", max(1, n_names))

    return ColorSpaceInfo("/DeviceRGB", "rgb", 3)


def _extract_colorspaces(res: pikepdf.Object | None, inherited: dict[str, ColorSpaceInfo] | None = None) -> dict[str, ColorSpaceInfo]:
    out: dict[str, ColorSpaceInfo] = {
        "/DeviceRGB": ColorSpaceInfo("/DeviceRGB", "rgb", 3),
        "/DeviceGray": ColorSpaceInfo("/DeviceGray", "gray", 1),
        "/DeviceCMYK": ColorSpaceInfo("/DeviceCMYK", "cmyk", 4),
        "/Pattern": ColorSpaceInfo("/Pattern", "pattern", 0),
    }
    if inherited:
        out.update(inherited)
    if res and "/ColorSpace" in res:
        for k, v in res["/ColorSpace"].items():
            info = _resolve_cs_obj(v)
            info.name = str(k)
            out[str(k)] = info
    return out


@dataclass
class ColorOpSpan:
    span_id: int
    stream_key: str
    start: int
    end: int
    is_stroke: bool
    cs_op: str  # "rg" | "RG" | "g" | "G" | "k" | "K" | "sc" | "scn" | "SC" | "SCN"
    srgb_hex: str
    alpha: float
    panel_id: str
    active_cs_name: str = ""
    active_cs_kind: str = "rgb"
    active_cs_ncomp: int = 3
    consumed_by_shape: bool = False
    consumed_by_text: bool = False
    is_dashed_grid: bool = False
    used_with_diff_fill: bool = False
    used_with_same_fill: bool = False
    used_standalone: bool = False
    max_rect_area: float = 0.0
    max_subpath_area: float = 0.0
    max_subpath_dim: float = 0.0
    total_area: float = 0.0
    min_dim: float = 9999.0
    paint_count: int = 0
    bbox: list[float] = field(default_factory=lambda: [1e9, 1e9, -1e9, -1e9])
    swatch_bboxes: list[tuple[float, float, float, float]] = field(default_factory=list, repr=False)
    post_gs_ends: list[int] = field(default_factory=list, repr=False)
    mutable: bool = False
    group_id: str | None = None
    is_cell_text_op: bool = False


@dataclass
class TextItem:
    text: str
    bbox: tuple[float, float, float, float]
    panel_id: str = "P1"


@dataclass
class ParsedPdfScene:
    scene_id: str
    filename: str
    raw_pdf_bytes: bytes
    page_width: float
    page_height: float
    panels: list[PanelBox]
    texts: list[TextItem]
    evidence_regions: list[EvidenceRegion]
    color_groups: dict[str, ColorGroup]
    continuous_scales: dict[str, ContinuousScale]
    entities: dict[str, SemanticEntity]
    cell_text_labels: list[CellTextLabel]
    collisions: list[CollisionNotice]
    page_index: int = 0
    page_count: int = 1
    total_stream_ops: int = 0
    is_scanned_only: bool = False
    plain_notices: list[dict[str, Any]] = field(default_factory=list)
    raw_content_bytes: bytes = field(repr=False, default=b"")
    raw_streams: dict[str, bytes] = field(repr=False, default_factory=dict)
    form_xobj_paths: dict[str, list[str]] = field(repr=False, default_factory=dict)
    cs_tokens_by_stream: dict[str, list[tuple[int, int]]] = field(repr=False, default_factory=dict)
    op_spans: list[ColorOpSpan] = field(repr=False, default_factory=list)
    colorbar_raw_rgb: dict[str, np.ndarray] = field(repr=False, default_factory=dict)
    colorbar_lut_t: dict[str, np.ndarray] = field(repr=False, default_factory=dict)
    geometry_hash_original: str = ""
    preview_scale: float = 1.5
    original_png: bytes = field(repr=False, default=b"")
    id_map_png: bytes = field(repr=False, default=b"")


def _decode_pdf_image_rgb01(xo: pikepdf.Object) -> np.ndarray | None:
    try:
        pimg = pikepdf.PdfImage(xo)
        pil_img = pimg.as_pil_image().convert("RGB")
        return np.asarray(pil_img, dtype=np.float64) / 255.0
    except Exception:
        try:
            w = int(xo.get("/Width", 0))
            h = int(xo.get("/Height", 0))
            raw = xo.read_bytes()
            if w > 0 and h > 0 and len(raw) == w * h * 3:
                return np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3)).astype(np.float64) / 255.0
        except Exception:
            return None
    return None


def _extract_text_items(pdf_bytes: bytes, page_h: float, page_index: int = 0) -> list[TextItem]:
    items: list[TextItem] = []
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_bytes)
        try:
            page = doc[page_index]
            try:
                tp = page.get_textpage()
                try:
                    n = tp.count_rects()
                    for i in range(n):
                        left, bottom, right, top = tp.get_rect(i)
                        txt = tp.get_text_bounded(left, bottom, right, top).strip()
                        if not txt:
                            continue
                        x0, x1 = min(left, right), max(left, right)
                        y0, y1 = min(page_h - top, page_h - bottom), max(page_h - top, page_h - bottom)
                        items.append(TextItem(text=txt, bbox=(x0, y0, x1, y1)))
                finally:
                    tp.close()
            finally:
                page.close()
        finally:
            doc.close()
    return items


def _assign_panel_id(panels: list[PanelBox], cx: float, cy: float) -> str:
    best_id = panels[0].panel_id
    best_area = 1e18
    for p in panels:
        x0, y0, x1, y1 = p.bbox
        if (x0 - 4.0) <= cx <= (x1 + 4.0) and (y0 - 4.0) <= cy <= (y1 + 4.0):
            area = (x1 - x0) * (y1 - y0)
            if area < best_area:
                best_area = area
                best_id = p.panel_id
    if best_area < 1e17:
        return best_id
    best_d = 1e18
    for p in panels:
        px = 0.5 * (p.bbox[0] + p.bbox[2])
        py = 0.5 * (p.bbox[1] + p.bbox[3])
        d = (cx - px) ** 2 + (cy - py) ** 2
        if d < best_d:
            best_d = d
            best_id = p.panel_id
    return best_id


def _discover_panels(
    clip_rects: list[tuple[float, float, float, float]],
    texts: list[TextItem],
    page_w: float,
    page_h: float,
) -> list[PanelBox]:
    page_area = page_w * page_h
    candidates: list[tuple[float, float, float, float]] = []
    for x0, y0, x1, y1 in clip_rects:
        w, h = x1 - x0, y1 - y0
        area = w * h
        if w < 90.0 or h < 90.0:
            continue
        if area > 0.90 * page_area or area < 0.035 * page_area:
            continue
        if any(
            abs(x0 - cx0) < 12 and abs(y0 - cy0) < 12 and abs(x1 - cx1) < 12 and abs(y1 - cy1) < 12
            for cx0, cy0, cx1, cy1 in candidates
        ):
            continue
        candidates.append((x0, y0, x1, y1))

    outer: list[tuple[float, float, float, float]] = []
    for i, (ax0, ay0, ax1, ay1) in enumerate(candidates):
        a_area = (ax1 - ax0) * (ay1 - ay0)
        is_inside_larger = False
        for j, (bx0, by0, bx1, by1) in enumerate(candidates):
            if i == j:
                continue
            b_area = (bx1 - bx0) * (by1 - by0)
            if b_area > a_area * 1.15 and ax0 >= bx0 - 4 and ay0 >= by0 - 4 and ax1 <= bx1 + 4 and ay1 <= by1 + 4:
                is_inside_larger = True
                break
        if not is_inside_larger:
            outer.append((ax0, ay0, ax1, ay1))

    if not outer:
        outer = [(0.0, 0.0, page_w, page_h)]

    outer.sort(key=lambda b: (round(b[1] / 90.0), b[0]))
    tag_texts = [t for t in texts if len(t.text) == 1 and "A" <= t.text <= "Z"]
    panels: list[PanelBox] = []
    used_ids: set[str] = set()
    for idx, bbox in enumerate(outer):
        x0, y0, x1, y1 = bbox
        pid = ""
        for tt in tag_texts:
            tx = 0.5 * (tt.bbox[0] + tt.bbox[2])
            ty = 0.5 * (tt.bbox[1] + tt.bbox[3])
            if (x0 - 18) <= tx <= (x0 + 85) and (y0 - 18) <= ty <= (y0 + 65):
                cand = f"Panel {tt.text}"
                if cand not in used_ids:
                    pid = cand
                    break
        if not pid:
            pid = f"Panel {chr(ord('A') + idx)}" if idx < 26 else f"Panel {idx + 1}"
        used_ids.add(pid)

        title = pid
        best_ty = 1e9
        for t in texts:
            if len(t.text) < 4 or t.text.replace(".", "").isdigit():
                continue
            tx = 0.5 * (t.bbox[0] + t.bbox[2])
            ty = 0.5 * (t.bbox[1] + t.bbox[3])
            if x0 <= tx <= x1 and y0 <= ty <= y0 + 0.22 * (y1 - y0):
                if ty < best_ty and (t.bbox[2] - t.bbox[0]) > 32:
                    best_ty = ty
                    title = t.text
        panels.append(PanelBox(panel_id=pid, title=title, bbox=bbox))
    return panels


def _tail_tokens_start_offset(b_tok: bytes, count: int) -> int:
    pos = len(b_tok)
    for _ in range(count):
        while pos > 0 and b_tok[pos - 1] in b" \t\r\n":
            pos -= 1
        while pos > 0 and b_tok[pos - 1] not in b" \t\r\n":
            pos -= 1
    return pos


def _vals_to_hex_via_cs(vals: list[float], cs_info: ColorSpaceInfo) -> str:
    if cs_info.kind == "gray" and len(vals) >= 1:
        v = max(0.0, min(1.0, vals[0]))
        return srgb01_to_hex((v, v, v))
    if cs_info.kind == "cmyk" and len(vals) >= 4:
        return srgb01_to_hex(_cmyk_to_rgb01(vals[0], vals[1], vals[2], vals[3]))
    if cs_info.kind == "indexed" and cs_info.lut_rgb01 is not None and len(vals) >= 1:
        idx = max(0, min(len(cs_info.lut_rgb01) - 1, int(round(vals[0]))))
        return srgb01_to_hex(cs_info.lut_rgb01[idx])
    if cs_info.kind == "separation" and len(vals) >= 1:
        t = max(0.0, min(1.0, vals[0]))
        sr, sg, sb = cs_info.spot_rgb01
        return srgb01_to_hex((1.0 - t * (1.0 - sr), 1.0 - t * (1.0 - sg), 1.0 - t * (1.0 - sb)))
    if len(vals) >= 3:
        return srgb01_to_hex(vals[:3])
    if len(vals) == 1:
        v = max(0.0, min(1.0, vals[0]))
        return srgb01_to_hex((v, v, v))
    return "#000000"


def parse_pdf_scene(
    pdf_bytes: bytes,
    filename: str = "figure.pdf",
    scene_id: str = "s_01",
    page_index: int = 0,
    progress_cb: Callable[[str, int], None] | None = None,
) -> ParsedPdfScene:
    """Stream-parse a scientific PDF page (including nested Form XObjects & ICC/CMYK/Indexed/Spot spaces)."""
    if progress_cb:
        progress_cb("reading", 15)
    geom_hash = canonical_geometry_hash_pdf_bytes(pdf_bytes)

    raw_streams: dict[str, bytes] = {}
    form_xobj_paths: dict[str, list[str]] = {}
    cs_tokens_by_stream: dict[str, list[tuple[int, int]]] = {}
    xobj_images: dict[str, tuple[pikepdf.Object, np.ndarray, bytes]] = {}
    xobj_placements: list[tuple[str, tuple[float, float, float, float]]] = []
    clip_rects: list[tuple[float, float, float, float]] = []
    op_spans: list[ColorOpSpan] = []
    tj_records: list[tuple[str, int, int, int | None, tuple[float, float]]] = []
    stream_op_counter = 0

    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        n_pages = len(pdf.pages)
        p_idx = max(0, min(n_pages - 1, int(page_index)))
        page = pdf.pages[p_idx]
        mb = [float(v) for v in page.MediaBox]
        page_w = mb[2] - mb[0]
        page_h = mb[3] - mb[1]

        contents = page.obj.get("/Contents")
        if contents is None:
            page_stream = b""
        elif isinstance(contents, pikepdf.Array):
            page_stream = b"\n".join(s.read_bytes() for s in contents)
        else:
            page_stream = contents.read_bytes()
        raw_streams["__page__"] = page_stream

        if progress_cb:
            progress_cb("colors", 40)

        form_inherited_cache: dict[
            str,
            list[tuple[tuple[float, float, float, float], list[tuple[float, float, float, float]], bool, bool, bool]],
        ] = {}
        form_local_spans: dict[str, tuple[tuple[float, float, float, float, float, float], list[int]]] = {}

        def _extract_dingbats_fonts(res_o: pikepdf.Object | None, inh_fonts: set[bytes] | None) -> set[bytes]:
            out_f: set[bytes] = set(inh_fonts) if inh_fonts else set()
            if res_o and "/Font" in res_o:
                for k_f, f_obj in res_o["/Font"].items():
                    try:
                        bf = str(f_obj.get("/BaseFont", "")).lower()
                        fd = f_obj.get("/FontDescriptor")
                        fn = str(fd.get("/FontName", "")).lower() if fd else ""
                        if "dingbats" in bf or "dingbats" in fn:
                            out_f.add(str(k_f).encode("latin1"))
                        else:
                            out_f.discard(str(k_f).encode("latin1"))
                    except Exception:
                        pass
            return out_f

        def _apply_local_2d(
            mat: tuple[float, float, float, float, float, float], lx: float, ly: float
        ) -> tuple[float, float]:
            a, b, c, d, e, f = mat
            return a * lx + c * ly + e, b * lx + d * ly + f

        def _xform_local_bbox(
            mat: tuple[float, float, float, float, float, float], bb: tuple[float, float, float, float]
        ) -> tuple[float, float, float, float]:
            pts = [
                _apply_local_2d(mat, bb[0], bb[1]),
                _apply_local_2d(mat, bb[2], bb[1]),
                _apply_local_2d(mat, bb[0], bb[3]),
                _apply_local_2d(mat, bb[2], bb[3]),
            ]
            return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))

        def _analyze_form_inherited_ops(
            f_skey: str,
            xo_obj: pikepdf.Object,
            f_bytes: bytes,
            res_o: pikepdf.Object | None,
            depth: int,
        ) -> list[tuple[tuple[float, float, float, float], list[tuple[float, float, float, float]], bool, bool, bool]]:
            if f_skey in form_inherited_cache:
                return form_inherited_cache[f_skey]
            inh_ops: list[
                tuple[tuple[float, float, float, float], list[tuple[float, float, float, float]], bool, bool, bool]
            ] = []
            form_inherited_cache[f_skey] = inh_ops  # Guard against cyclic Form references
            if depth > 6 or not f_bytes:
                return inh_ops

            l_ctm: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            has_loc_fill = False
            has_loc_stroke = False
            l_dashed = False
            l_stack: list[tuple[Any, ...]] = []
            l_path = [1e9, 1e9, -1e9, -1e9]
            l_sub = [1e9, 1e9, -1e9, -1e9]
            l_subs: list[tuple[float, float, float, float]] = []
            sub_xobjs = res_o.get("/XObject") if res_o else None

            def _l_flush() -> None:
                nonlocal l_sub
                if l_sub[0] < 1e8:
                    l_subs.append((l_sub[0], l_sub[1], l_sub[2], l_sub[3]))
                    l_sub = [1e9, 1e9, -1e9, -1e9]

            for fm in _STREAM_CMD_RE.finditer(f_bytes):
                fk = fm.lastgroup
                ftok = fm.group(0)
                if fk == "numop":
                    fps = ftok.split()
                    fop = fps[-1]
                    if fop == b"m" and len(fps) >= 3:
                        _l_flush()
                        lx, ly = _apply_local_2d(l_ctm, float(fps[-3]), float(fps[-2]))
                        l_path = [min(l_path[0], lx), min(l_path[1], ly), max(l_path[2], lx), max(l_path[3], ly)]
                        l_sub = [lx, ly, lx, ly]
                    elif fop == b"l" and len(fps) >= 3:
                        lx, ly = _apply_local_2d(l_ctm, float(fps[-3]), float(fps[-2]))
                        l_path = [min(l_path[0], lx), min(l_path[1], ly), max(l_path[2], lx), max(l_path[3], ly)]
                        l_sub = [min(l_sub[0], lx), min(l_sub[1], ly), max(l_sub[2], lx), max(l_sub[3], ly)]
                    elif fop in (b"c", b"v", b"y"):
                        nc = 6 if fop == b"c" else 4
                        if len(fps) >= nc + 1:
                            cs_f = [float(x) for x in fps[-(nc + 1) : -1]]
                            for jc in range(0, nc, 2):
                                lx, ly = _apply_local_2d(l_ctm, cs_f[jc], cs_f[jc + 1])
                                l_path = [min(l_path[0], lx), min(l_path[1], ly), max(l_path[2], lx), max(l_path[3], ly)]
                                l_sub = [min(l_sub[0], lx), min(l_sub[1], ly), max(l_sub[2], lx), max(l_sub[3], ly)]
                    elif fop == b"re" and len(fps) >= 5:
                        _l_flush()
                        ns_f = [float(x) for x in fps[-5:-1]]
                        rb_f = _xform_local_bbox(l_ctm, (ns_f[0], ns_f[1], ns_f[0] + ns_f[2], ns_f[1] + ns_f[3]))
                        l_path = [min(l_path[0], rb_f[0]), min(l_path[1], rb_f[1]), max(l_path[2], rb_f[2]), max(l_path[3], rb_f[3])]
                        l_subs.append(rb_f)
                    elif fop in (b"rg", b"g", b"k", b"sc", b"scn"):
                        has_loc_fill = True
                    elif fop in (b"RG", b"G", b"K", b"SC", b"SCN"):
                        has_loc_stroke = True
                    elif fop == b"cm" and len(fps) >= 7:
                        l_ctm = _mat_mul(tuple(float(x) for x in fps[-7:-1]), l_ctm)
                elif fk == "h":
                    _l_flush()
                elif fk == "q":
                    l_stack.append((l_ctm, has_loc_fill, has_loc_stroke, l_dashed))
                elif fk == "Q" and l_stack:
                    l_ctm, has_loc_fill, has_loc_stroke, l_dashed = l_stack.pop()
                elif fk == "dash":
                    br_e = ftok.find(b"]")
                    l_dashed = len(ftok[1:br_e].strip()) > 0
                elif fk == "clip":
                    l_path = [1e9, 1e9, -1e9, -1e9]
                    l_sub = [1e9, 1e9, -1e9, -1e9]
                    l_subs.clear()
                elif fk == "paint":
                    _l_flush()
                    ops_f = ftok.decode("ascii")
                    uf = ops_f in ("f", "f*", "F", "B", "B*", "b", "b*") and not has_loc_fill
                    us = ops_f in ("S", "s", "B", "B*", "b", "b*") and not has_loc_stroke
                    if uf or us:
                        if l_path[0] < 1e8:
                            ob = (l_path[0], l_path[1], l_path[2], l_path[3])
                            inh_ops.append((ob, list(l_subs) if l_subs else [ob], uf, us, l_dashed))
                        elif xo_obj.get("/BBox") is not None:
                            bb_r = [float(x) for x in xo_obj["/BBox"]]
                            fb = _xform_local_bbox(l_ctm, (min(bb_r[0], bb_r[2]), min(bb_r[1], bb_r[3]), max(bb_r[0], bb_r[2]), max(bb_r[1], bb_r[3])))
                            inh_ops.append((fb, [fb], uf, us, l_dashed))
                    l_path = [1e9, 1e9, -1e9, -1e9]
                    l_sub = [1e9, 1e9, -1e9, -1e9]
                    l_subs.clear()
                elif fk == "do" and sub_xobjs and (not has_loc_fill or not has_loc_stroke):
                    sx_name = ftok.split()[0].decode("latin1")
                    if sx_name in sub_xobjs:
                        sx_obj = sub_xobjs[sx_name]
                        if str(sx_obj.get("/Subtype", "")) == "/Form":
                            try:
                                sx_bytes = sx_obj.read_bytes()
                            except Exception:
                                sx_bytes = b""
                            sm_raw = sx_obj.get("/Matrix")
                            sm = tuple(float(x) for x in sm_raw) if sm_raw is not None else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                            sub_ctm = _mat_mul(sm, l_ctm)
                            sub_inh = _analyze_form_inherited_ops(
                                f"{f_skey}/{sx_name}",
                                sx_obj,
                                sx_bytes,
                                sx_obj.get("/Resources") or res_o,
                                depth + 1,
                            )
                            for sb_all, sb_list, sub_uf, sub_us, sub_dash in sub_inh:
                                eff_uf = sub_uf and not has_loc_fill
                                eff_us = sub_us and not has_loc_stroke
                                if eff_uf or eff_us:
                                    inh_ops.append(
                                        (
                                            _xform_local_bbox(sub_ctm, sb_all),
                                            [_xform_local_bbox(sub_ctm, sbi) for sbi in sb_list],
                                            eff_uf,
                                            eff_us,
                                            sub_dash or l_dashed,
                                        )
                                    )
            return inh_ops

        def _credit_shape_paint(
            overall_bbox: tuple[float, float, float, float],
            subpaths: list[tuple[float, float, float, float]],
            uses_fill: bool,
            uses_stroke: bool,
            f_span_idx: int | None,
            s_span_idx: int | None,
            f_alpha: float,
            s_alpha: float,
            dashed_flag: bool,
        ) -> None:
            pw = max(0.2, overall_bbox[2] - overall_bbox[0])
            ph = max(0.2, overall_bbox[3] - overall_bbox[1])
            p_area = pw * ph
            p_min = min(pw, ph)
            subs = subpaths if subpaths else [overall_bbox]
            max_sub_a = max(max(0.2, sb[2] - sb[0]) * max(0.2, sb[3] - sb[1]) for sb in subs)
            max_sub_d = max(max(sb[2] - sb[0], sb[3] - sb[1]) for sb in subs)
            small_subs = [
                sb
                for sb in subs
                if 1.0 <= max(sb[2] - sb[0], sb[3] - sb[1]) <= 36.0
                and (sb[2] - sb[0]) <= 36.0
                and (sb[3] - sb[1]) <= 28.0
            ]
            both_painted = uses_fill and uses_stroke and f_span_idx is not None and s_span_idx is not None
            same_fs = both_painted and op_spans[f_span_idx].srgb_hex == op_spans[s_span_idx].srgb_hex  # type: ignore[index]
            diff_fs = both_painted and not same_fs

            if uses_fill and f_span_idx is not None:
                sp = op_spans[f_span_idx]
                sp.alpha = f_alpha
                sp.consumed_by_shape = True
                sp.paint_count += max(1, len(subpaths))
                sp.total_area += p_area
                sp.max_rect_area = max(sp.max_rect_area, p_area)
                sp.max_subpath_area = max(sp.max_subpath_area, max_sub_a)
                sp.max_subpath_dim = max(sp.max_subpath_dim, max_sub_d)
                sp.min_dim = min(sp.min_dim, p_min)
                sp.bbox = [
                    min(sp.bbox[0], overall_bbox[0]),
                    min(sp.bbox[1], overall_bbox[1]),
                    max(sp.bbox[2], overall_bbox[2]),
                    max(sp.bbox[3], overall_bbox[3]),
                ]
                if len(sp.swatch_bboxes) < 16 and len(subs) <= 12:
                    sp.swatch_bboxes.extend(small_subs[: 16 - len(sp.swatch_bboxes)])

            if uses_stroke and s_span_idx is not None:
                sp = op_spans[s_span_idx]
                sp.alpha = s_alpha
                sp.consumed_by_shape = True
                sp.paint_count += max(1, len(subpaths))
                sp.is_dashed_grid = sp.is_dashed_grid or dashed_flag
                if diff_fs:
                    sp.used_with_diff_fill = True
                elif same_fs:
                    sp.used_with_same_fill = True
                else:
                    sp.used_standalone = True
                sp.total_area += max(pw, ph) * 1.2
                sp.max_rect_area = max(sp.max_rect_area, p_area)
                sp.max_subpath_area = max(sp.max_subpath_area, max_sub_a)
                sp.max_subpath_dim = max(sp.max_subpath_dim, max_sub_d)
                sp.min_dim = min(sp.min_dim, 1.5)
                sp.bbox = [
                    min(sp.bbox[0], overall_bbox[0]),
                    min(sp.bbox[1], overall_bbox[1]),
                    max(sp.bbox[2], overall_bbox[2]),
                    max(sp.bbox[3], overall_bbox[3]),
                ]
                if len(sp.swatch_bboxes) < 16 and len(subs) <= 12:
                    sp.swatch_bboxes.extend(small_subs[: 16 - len(sp.swatch_bboxes)])

        def _parse_stream_scope(
            s_key: str,
            s_bytes: bytes,
            res_obj: pikepdf.Object | None,
            init_ctm: tuple[float, float, float, float, float, float],
            inherited_cs: dict[str, ColorSpaceInfo] | None,
            xobj_chain: list[str],
            depth: int,
            init_fill_alpha: float = 1.0,
            init_stroke_alpha: float = 1.0,
            inherited_dingbats: set[bytes] | None = None,
        ) -> None:
            nonlocal stream_op_counter
            cs_map = _extract_colorspaces(res_obj, inherited_cs)
            dingbats_fonts = _extract_dingbats_fonts(res_obj, inherited_dingbats)
            gs_alpha: dict[bytes, tuple[float, float]] = {}
            if res_obj and "/ExtGState" in res_obj:
                for k_gs, v_gs in res_obj["/ExtGState"].items():
                    gs_alpha[str(k_gs).encode()] = (float(v_gs.get("/ca", 1.0)), float(v_gs.get("/CA", 1.0)))

            local_xobjs = res_obj.get("/XObject") if res_obj else None
            if local_xobjs:
                for k_xo, xo in local_xobjs.items():
                    if str(xo.get("/Subtype", "")) == "/Image":
                        full_img_key = "/".join(xobj_chain + [str(k_xo)]) if xobj_chain else str(k_xo)
                        if full_img_key not in xobj_images:
                            rgb01 = _decode_pdf_image_rgb01(xo)
                            if rgb01 is not None:
                                try:
                                    raw_b = xo.read_raw_bytes()
                                except Exception:
                                    raw_b = xo.read_bytes()
                                xobj_images[full_img_key] = (xo, rgb01, raw_b)

            ctm = init_ctm
            fill_alpha, stroke_alpha = init_fill_alpha, init_stroke_alpha
            is_dashed = False
            in_text = False
            act_font = b""
            act_font_size = 10.0
            act_tr = 0
            act_fill_cs = cs_map["/DeviceRGB"]
            act_stroke_cs = cs_map["/DeviceRGB"]
            state_stack: list[tuple[Any, ...]] = []

            last_rect_page: tuple[float, float, float, float] | None = None
            cur_path_bbox = [1e9, 1e9, -1e9, -1e9]
            cur_subpath_bbox = [1e9, 1e9, -1e9, -1e9]
            completed_subpaths: list[tuple[float, float, float, float]] = []

            cur_fill_span: int | None = None
            cur_stroke_span: int | None = None
            text_mat: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            cur_bt_pt: tuple[float, float] = (0.0, 0.0)

            def _flush_subpath() -> None:
                nonlocal cur_subpath_bbox
                if cur_subpath_bbox[0] < 1e8:
                    completed_subpaths.append(
                        (cur_subpath_bbox[0], cur_subpath_bbox[1], cur_subpath_bbox[2], cur_subpath_bbox[3])
                    )
                    cur_subpath_bbox = [1e9, 1e9, -1e9, -1e9]

            for m in _STREAM_CMD_RE.finditer(s_bytes):
                stream_op_counter += 1
                kind = m.lastgroup
                tok = m.group(0)
                if kind == "tf":
                    tf_parts = tok.split()
                    if len(tf_parts) >= 3:
                        act_font = tf_parts[0]
                        try:
                            act_font_size = abs(float(tf_parts[1]))
                        except ValueError:
                            act_font_size = 10.0
                    continue
                if kind == "tr":
                    try:
                        act_tr = int(tok.split()[0])
                    except ValueError:
                        act_tr = 0
                    continue
                if kind == "cs":
                    cs_parts = tok.split()
                    cs_nm = cs_parts[0].decode("latin1")
                    is_st = cs_parts[-1] == b"CS"
                    info = cs_map.get(cs_nm, ColorSpaceInfo(cs_nm, "rgb", 3))
                    if is_st:
                        act_stroke_cs = info
                    else:
                        act_fill_cs = info
                    cs_tokens_by_stream.setdefault(s_key, []).append((m.start(), m.end()))
                    continue

                if kind == "numop":
                    parts = tok.split()
                    op_b = parts[-1]
                    if op_b == b"m" and len(parts) >= 3:
                        _flush_subpath()
                        px, py = _apply_ctm(ctm, float(parts[-3]), float(parts[-2]), page_h)
                        cur_path_bbox = [min(cur_path_bbox[0], px), min(cur_path_bbox[1], py), max(cur_path_bbox[2], px), max(cur_path_bbox[3], py)]
                        cur_subpath_bbox = [px, py, px, py]
                        continue
                    if op_b == b"l" and len(parts) >= 3:
                        px, py = _apply_ctm(ctm, float(parts[-3]), float(parts[-2]), page_h)
                        cur_path_bbox = [min(cur_path_bbox[0], px), min(cur_path_bbox[1], py), max(cur_path_bbox[2], px), max(cur_path_bbox[3], py)]
                        cur_subpath_bbox = [min(cur_subpath_bbox[0], px), min(cur_subpath_bbox[1], py), max(cur_subpath_bbox[2], px), max(cur_subpath_bbox[3], py)]
                        continue
                    if op_b in (b"c", b"v", b"y"):
                        need_coords = 6 if op_b == b"c" else 4
                        if len(parts) >= need_coords + 1:
                            coords = [float(x) for x in parts[-(need_coords + 1) : -1]]
                            for j_c in range(0, need_coords, 2):
                                px, py = _apply_ctm(ctm, coords[j_c], coords[j_c + 1], page_h)
                                cur_path_bbox = [min(cur_path_bbox[0], px), min(cur_path_bbox[1], py), max(cur_path_bbox[2], px), max(cur_path_bbox[3], py)]
                                cur_subpath_bbox = [min(cur_subpath_bbox[0], px), min(cur_subpath_bbox[1], py), max(cur_subpath_bbox[2], px), max(cur_subpath_bbox[3], py)]
                        continue
                    if op_b == b"re" and len(parts) >= 5:
                        _flush_subpath()
                        nums = [float(x) for x in parts[-5:-1]]
                        rb = _rect_to_page_bbox(ctm, nums[0], nums[1], nums[2], nums[3], page_h)
                        last_rect_page = rb
                        cur_path_bbox = [min(cur_path_bbox[0], rb[0]), min(cur_path_bbox[1], rb[1]), max(cur_path_bbox[2], rb[2]), max(cur_path_bbox[3], rb[3])]
                        completed_subpaths.append(rb)
                        continue

                    if op_b in (b"rg", b"g", b"k", b"RG", b"G", b"K", b"sc", b"scn", b"SC", b"SCN"):
                        cs_s = op_b.decode("ascii")
                        is_st = cs_s in ("RG", "G", "K", "SC", "SCN")
                        # Pattern color (`0.2 ... /P0 scn`) is skipped as pattern
                        if len(parts) >= 2 and parts[-2].startswith(b"/"):
                            continue
                        if cs_s in ("rg", "RG"):
                            need = 3
                            c_info = cs_map["/DeviceRGB"]
                        elif cs_s in ("g", "G"):
                            need = 1
                            c_info = cs_map["/DeviceGray"]
                        elif cs_s in ("k", "K"):
                            need = 4
                            c_info = cs_map["/DeviceCMYK"]
                        else:
                            c_info = act_stroke_cs if is_st else act_fill_cs
                            if c_info.n_comp <= 0:
                                continue
                            need = c_info.n_comp
                        if len(parts) >= need + 1:
                            try:
                                vals = [float(x) for x in parts[-(need + 1) : -1]]
                            except ValueError:
                                continue
                            rel_off = _tail_tokens_start_offset(tok, need + 1)
                            s_off = m.start() + rel_off
                            hx = _vals_to_hex_via_cs(vals, c_info)
                            sid = len(op_spans)
                            op_spans.append(
                                ColorOpSpan(
                                    span_id=sid,
                                    stream_key=s_key,
                                    start=s_off,
                                    end=m.end(),
                                    is_stroke=is_st,
                                    cs_op=cs_s,
                                    srgb_hex=hx,
                                    alpha=stroke_alpha if is_st else fill_alpha,
                                    panel_id="P1",
                                    active_cs_name=c_info.name,
                                    active_cs_kind=c_info.kind,
                                    active_cs_ncomp=c_info.n_comp,
                                )
                            )
                            if is_st:
                                cur_stroke_span = sid
                            else:
                                cur_fill_span = sid
                        continue

                    if op_b == b"cm" and len(parts) >= 7:
                        nums = [float(x) for x in parts[-7:-1]]
                        ctm = _mat_mul(tuple(nums), ctm)
                        if in_text:
                            cur_bt_pt = _apply_ctm(_mat_mul(text_mat, ctm), 0.0, 0.0, page_h)
                        continue
                    if op_b == b"Tm" and len(parts) >= 7:
                        nums = [float(x) for x in parts[-7:-1]]
                        text_mat = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
                        cur_bt_pt = _apply_ctm(_mat_mul(text_mat, ctm), 0.0, 0.0, page_h)
                        continue
                    if op_b in (b"Td", b"TD") and len(parts) >= 3:
                        nums = [float(x) for x in parts[-3:-1]]
                        text_mat = _mat_mul((1.0, 0.0, 0.0, 1.0, nums[0], nums[1]), text_mat)
                        cur_bt_pt = _apply_ctm(_mat_mul(text_mat, ctm), 0.0, 0.0, page_h)
                        continue
                    continue

                if kind == "h":
                    _flush_subpath()
                elif kind == "q":
                    state_stack.append(
                        (
                            ctm,
                            fill_alpha,
                            stroke_alpha,
                            is_dashed,
                            cur_fill_span,
                            cur_stroke_span,
                            act_fill_cs,
                            act_stroke_cs,
                            act_font,
                            act_font_size,
                            act_tr,
                        )
                    )
                elif kind == "Q":
                    if state_stack:
                        (
                            ctm,
                            fill_alpha,
                            stroke_alpha,
                            is_dashed,
                            cur_fill_span,
                            cur_stroke_span,
                            act_fill_cs,
                            act_stroke_cs,
                            act_font,
                            act_font_size,
                            act_tr,
                        ) = state_stack.pop()
                elif kind == "BT":
                    in_text = True
                    text_mat = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                    cur_bt_pt = _apply_ctm(ctm, 0.0, 0.0, page_h)
                elif kind == "ET":
                    in_text = False
                elif kind == "gs":
                    gs_name = tok.split()[0]
                    if gs_name in gs_alpha:
                        fill_alpha, stroke_alpha = gs_alpha[gs_name]
                        if (
                            cur_fill_span is not None
                            and op_spans[cur_fill_span].stream_key == s_key
                            and op_spans[cur_fill_span].paint_count == 0
                        ):
                            op_spans[cur_fill_span].alpha = fill_alpha
                            op_spans[cur_fill_span].post_gs_ends.append(m.end())
                        if (
                            cur_stroke_span is not None
                            and op_spans[cur_stroke_span].stream_key == s_key
                            and op_spans[cur_stroke_span].paint_count == 0
                        ):
                            op_spans[cur_stroke_span].alpha = stroke_alpha
                            op_spans[cur_stroke_span].post_gs_ends.append(m.end())
                elif kind == "dash":
                    br_end = tok.find(b"]")
                    inside = tok[1:br_end].strip()
                    is_dashed = len(inside) > 0
                elif kind == "clip":
                    if last_rect_page is not None:
                        clip_rects.append(last_rect_page)
                    cur_path_bbox = [1e9, 1e9, -1e9, -1e9]
                    cur_subpath_bbox = [1e9, 1e9, -1e9, -1e9]
                    completed_subpaths.clear()
                elif kind == "paint":
                    _flush_subpath()
                    op_s = tok.decode("ascii")
                    uses_fill = op_s in ("f", "f*", "F", "B", "B*", "b", "b*")
                    uses_stroke = op_s in ("S", "s", "B", "B*", "b", "b*")
                    if cur_path_bbox[0] < 1e8:
                        _credit_shape_paint(
                            overall_bbox=(cur_path_bbox[0], cur_path_bbox[1], cur_path_bbox[2], cur_path_bbox[3]),
                            subpaths=completed_subpaths,
                            uses_fill=uses_fill,
                            uses_stroke=uses_stroke,
                            f_span_idx=cur_fill_span,
                            s_span_idx=cur_stroke_span,
                            f_alpha=fill_alpha,
                            s_alpha=stroke_alpha,
                            dashed_flag=is_dashed,
                        )
                    cur_path_bbox = [1e9, 1e9, -1e9, -1e9]
                    cur_subpath_bbox = [1e9, 1e9, -1e9, -1e9]
                    completed_subpaths.clear()
                    last_rect_page = None
                elif kind == "tj":
                    if act_font and act_font in dingbats_fonts:
                        # R `grDevices::pdf(useDingbats=TRUE)` geometric scatter symbols (e.g. `(l) Tj` circles)
                        eff_tm = _mat_mul(text_mat, ctm)
                        sc_pt = max(0.5, float(np.hypot(eff_tm[0], eff_tm[1]) or np.hypot(eff_tm[2], eff_tm[3]) or 1.0))
                        r_pt = max(1.2, min(16.0, 0.38 * max(1.0, act_font_size) * sc_pt))
                        bx, by = cur_bt_pt
                        db = (bx - r_pt, by - r_pt, bx + r_pt, by + r_pt)
                        _credit_shape_paint(
                            overall_bbox=db,
                            subpaths=[db],
                            uses_fill=act_tr in (0, 2, 4, 6),
                            uses_stroke=act_tr in (1, 2, 5, 6),
                            f_span_idx=cur_fill_span,
                            s_span_idx=cur_stroke_span,
                            f_alpha=fill_alpha,
                            s_alpha=stroke_alpha,
                            dashed_flag=is_dashed,
                        )
                    elif cur_fill_span is not None:
                        op_spans[cur_fill_span].consumed_by_text = True
                        if s_key == "__page__":
                            look_start = max(0, m.start() - 256)
                            chunk_before = s_bytes[look_start : m.start()]
                            br_pos = chunk_before.rfind(b"[") if tok == b"TJ" else chunk_before.rfind(b"(")
                            tj_s = (look_start + br_pos) if br_pos >= 0 else m.start()
                            tj_records.append((s_key, tj_s, m.end(), cur_fill_span, cur_bt_pt))
                elif kind == "do":
                    xo_name = tok.split()[0].decode("latin1")
                    if local_xobjs and xo_name in local_xobjs:
                        xo_obj = local_xobjs[xo_name]
                        st_type = str(xo_obj.get("/Subtype", ""))
                        next_chain = xobj_chain + [xo_name]
                        full_key = "/".join(next_chain)
                        if st_type == "/Image":
                            ib = _rect_to_page_bbox(ctm, 0.0, 0.0, 1.0, 1.0, page_h)
                            xobj_placements.append((full_key, ib))
                        elif st_type == "/Form" and depth < 6:
                            f_mat_raw = xo_obj.get("/Matrix")
                            f_mat = tuple(float(x) for x in f_mat_raw) if f_mat_raw is not None else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                            form_ctm = _mat_mul(f_mat, ctm)
                            f_skey = f"form:{full_key}"
                            f_res = xo_obj.get("/Resources") or res_obj
                            if f_skey not in raw_streams:
                                try:
                                    f_bytes = xo_obj.read_bytes()
                                except Exception:
                                    f_bytes = b""
                                raw_streams[f_skey] = f_bytes
                                form_xobj_paths[f_skey] = next_chain
                                span_before = len(op_spans)
                                _parse_stream_scope(
                                    s_key=f_skey,
                                    s_bytes=f_bytes,
                                    res_obj=f_res,
                                    init_ctm=form_ctm,
                                    inherited_cs=cs_map,
                                    xobj_chain=next_chain,
                                    depth=depth + 1,
                                    init_fill_alpha=fill_alpha,
                                    init_stroke_alpha=stroke_alpha,
                                    inherited_dingbats=dingbats_fonts,
                                )
                                created_sids = [
                                    sid_f
                                    for sid_f in range(span_before, len(op_spans))
                                    if op_spans[sid_f].stream_key == f_skey and op_spans[sid_f].consumed_by_shape
                                ]
                                if created_sids:
                                    form_local_spans[f_skey] = (form_ctm, created_sids)
                            else:
                                f_bytes = raw_streams[f_skey]
                                if f_skey in form_local_spans:
                                    first_ctm, loc_sids = form_local_spans[f_skey]
                                    p0_x, p0_y = _apply_ctm(first_ctm, 0.0, 0.0, page_h)
                                    pn_x, pn_y = _apply_ctm(form_ctm, 0.0, 0.0, page_h)
                                    dx_p, dy_p = pn_x - p0_x, pn_y - p0_y
                                    for sid_f in loc_sids:
                                        sp_f = op_spans[sid_f]
                                        sp_f.paint_count += 1
                                        if sp_f.bbox[0] < 1e8:
                                            sb_shift = (
                                                sp_f.bbox[0] + dx_p,
                                                sp_f.bbox[1] + dy_p,
                                                sp_f.bbox[2] + dx_p,
                                                sp_f.bbox[3] + dy_p,
                                            )
                                            sp_f.bbox = [
                                                min(sp_f.bbox[0], sb_shift[0]),
                                                min(sp_f.bbox[1], sb_shift[1]),
                                                max(sp_f.bbox[2], sb_shift[2]),
                                                max(sp_f.bbox[3], sb_shift[3]),
                                            ]
                                            if len(sp_f.swatch_bboxes) < 16 and (sb_shift[2] - sb_shift[0]) <= 36.0 and (sb_shift[3] - sb_shift[1]) <= 28.0:
                                                sp_f.swatch_bboxes.append(sb_shift)

                            # Stamp any caller-inherited paint ops inside this Form XObject (e.g. Matplotlib `/M0 Do`, `/P0 Do` scatter points!)
                            inh_list = _analyze_form_inherited_ops(f_skey, xo_obj, f_bytes, f_res, depth + 1)
                            for lb_all, lb_subs, uf_inh, us_inh, dash_inh in inh_list:
                                pb_all = _rect_to_page_bbox(
                                    form_ctm, lb_all[0], lb_all[1], lb_all[2] - lb_all[0], lb_all[3] - lb_all[1], page_h
                                )
                                pb_subs = [
                                    _rect_to_page_bbox(form_ctm, sb_i[0], sb_i[1], sb_i[2] - sb_i[0], sb_i[3] - sb_i[1], page_h)
                                    for sb_i in lb_subs
                                ]
                                _credit_shape_paint(
                                    overall_bbox=pb_all,
                                    subpaths=pb_subs,
                                    uses_fill=uf_inh,
                                    uses_stroke=us_inh,
                                    f_span_idx=cur_fill_span if uf_inh else None,
                                    s_span_idx=cur_stroke_span if us_inh else None,
                                    f_alpha=fill_alpha,
                                    s_alpha=stroke_alpha,
                                    dashed_flag=is_dashed or dash_inh,
                                )

        _parse_stream_scope(
            s_key="__page__",
            s_bytes=page_stream,
            res_obj=page.obj.get("/Resources"),
            init_ctm=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            inherited_cs=None,
            xobj_chain=[],
            depth=0,
        )

    texts = _extract_text_items(pdf_bytes, page_h, page_index=p_idx)
    panels = _discover_panels(clip_rects, texts, page_w, page_h)
    for t in texts:
        t.panel_id = _assign_panel_id(panels, 0.5 * (t.bbox[0] + t.bbox[2]), 0.5 * (t.bbox[1] + t.bbox[3]))

    # Assign panel_id to each op_span and decide structural vs mutable
    for sp in op_spans:
        if sp.bbox[0] < 1e8:
            cx = 0.5 * (sp.bbox[0] + sp.bbox[2])
            cy = 0.5 * (sp.bbox[1] + sp.bbox[3])
            sp.panel_id = _assign_panel_id(panels, cx, cy)
        if not sp.consumed_by_shape or sp.consumed_by_text:
            sp.mutable = False
            continue
        L, C, _ = hex_to_oklch(sp.srgb_hex)
        # Protect pure white (#FFFFFF) canvas/scalebar/label-box fills & frames
        if L > 0.985 and C < 0.015:
            sp.mutable = False
            continue
        # Protect pure black (#000000) axes, ticks, borders, and point outlines
        if L < 0.08 and C < 0.015:
            sp.mutable = False
            continue
        # Protect achromatic outline strokes around differently-colored filled shapes (e.g. `#222222`/`#333333` scatter & boxplot borders)
        # and achromatic dashed reference/threshold lines (`#555555` median lines), while keeping data categories!
        if sp.is_stroke and C < 0.012:
            if sp.is_dashed_grid or (sp.used_with_diff_fill and not sp.used_with_same_fill and not sp.used_standalone):
                sp.mutable = False
                continue
        # Protect only TRUE achromatic light-gray gridlines & panel backdrop rects (`C < 0.012`),
        # preserving low-chroma tinted data categories such as mist-slate (`#C9D6DF`, C ~ 0.019)!
        if C < 0.012 and L > 0.87 and (sp.is_dashed_grid or sp.is_stroke or sp.max_subpath_area > 2200.0):
            sp.mutable = False
            continue
        sp.mutable = True

    if progress_cb:
        progress_cb("legends", 68)

    # Classify XObject images under Gate G0
    evidence_regions: list[EvidenceRegion] = []
    colorbar_luts: dict[str, tuple[str, tuple[float, float, float, float], np.ndarray, bool, float]] = {}
    colorbar_raw_rgb: dict[str, np.ndarray] = {}
    colorbar_lut_t: dict[str, np.ndarray] = {}

    pending_2d_xobjs: list[tuple[str, str, tuple[float, float, float, float], np.ndarray, bytes, list[str]]] = []
    for xo_name, ibbox in xobj_placements:
        if xo_name not in xobj_images:
            continue
        _, rgb01, raw_b = xobj_images[xo_name]
        pid = _assign_panel_id(panels, 0.5 * (ibbox[0] + ibbox[2]), 0.5 * (ibbox[1] + ibbox[3]))
        near_txts = [
            t.text
            for t in texts
            if t.panel_id == pid
            and t.bbox[0] >= ibbox[0] - 90
            and t.bbox[2] <= ibbox[2] + 120
            and t.bbox[1] >= ibbox[1] - 60
            and t.bbox[3] <= ibbox[3] + 60
        ]
        ev, lut, is_div, mid_t = classify_raster_object(xo_name, pid, ibbox, rgb01, raw_b, near_txts)
        if ev.subtype_label == "colorbar_strip" and lut is not None:
            evidence_regions.append(ev)
            colorbar_luts[xo_name] = (pid, ibbox, lut, is_div, mid_t)
            colorbar_raw_rgb[xo_name] = rgb01
            t_px, _ = project_colors_onto_lut(rgb01.reshape(-1, 3), lut)
            colorbar_lut_t[xo_name] = t_px.reshape(rgb01.shape[:2])
        else:
            pending_2d_xobjs.append((xo_name, pid, ibbox, rgb01, raw_b, near_txts))

    known_luts = [v[2] for v in colorbar_luts.values()]
    raster_heatmaps_by_panel: dict[str, list[tuple[str, np.ndarray, bool, float]]] = {}
    for xo_name, pid, ibbox, rgb01, raw_b, near_txts in pending_2d_xobjs:
        ev, lut, is_div, mid_t = classify_raster_object(
            xo_name, pid, ibbox, rgb01, raw_b, near_txts, known_colorbar_luts=known_luts
        )
        evidence_regions.append(ev)
        if ev.subtype_label == "heatmap_raster_1d" and lut is not None:
            colorbar_raw_rgb[xo_name] = rgb01
            t_px, _ = project_colors_onto_lut(rgb01.reshape(-1, 3), lut)
            colorbar_lut_t[xo_name] = t_px.reshape(rgb01.shape[:2])
            raster_heatmaps_by_panel.setdefault(pid, []).append((xo_name, lut, is_div, mid_t))

    # Aggregate mutable ColorOpSpans into ColorGroups per (panel_id, quantized_hex_cluster, overlay_mark_layer)
    color_groups: dict[str, ColorGroup] = {}
    panel_color_buckets: dict[str, list[tuple[np.ndarray, list[ColorOpSpan]]]] = {}
    exact_bucket_cache: dict[tuple[str, str], list[ColorOpSpan]] = {}

    for sp in op_spans:
        if not sp.mutable:
            continue
        b_key = (sp.panel_id, sp.srgb_hex)
        bucket = exact_bucket_cache.get(b_key)
        if bucket is None:
            lab = srgb_to_oklab(hex_to_srgb01(sp.srgb_hex))
            existing = panel_color_buckets.setdefault(sp.panel_id, [])
            for c_lab, b_list in existing:
                if float(np.linalg.norm(lab - c_lab)) <= 0.016:
                    bucket = b_list
                    break
            if bucket is None:
                bucket = []
                existing.append((lab, bucket))
            exact_bucket_cache[b_key] = bucket
        bucket.append(sp)

    def _emit_color_group(sps: list[ColorOpSpan], m_kind: str) -> str:
        sp0 = sps[0]
        gid = f"g_{len(color_groups) + 1:03d}"
        has_fill = any(not s.is_stroke for s in sps)
        bx0 = min(s.bbox[0] for s in sps)
        by0 = min(s.bbox[1] for s in sps)
        bx1 = max(s.bbox[2] for s in sps)
        by1 = max(s.bbox[3] for s in sps)
        color_groups[gid] = ColorGroup(
            group_id=gid,
            panel_id=sp0.panel_id,
            role="fill" if has_fill else "stroke",
            original_hex=sp0.srgb_hex,
            current_hex=sp0.srgb_hex,
            alpha=round(sp0.alpha, 3),
            primitive_count=sum(s.paint_count for s in sps),
            total_area_pt2=round(sum(s.total_area for s in sps), 2),
            min_mark_pt=round(min(s.min_dim for s in sps), 2),
            sample_bbox=(round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2)),
            mark_kind=m_kind,  # type: ignore[arg-type]
            op_indices=[s.span_id for s in sps],
        )
        for s in sps:
            s.group_id = gid
        return gid

    sibling_layer_pairs: list[tuple[str, str]] = []
    for pid_b, clusters_b in panel_color_buckets.items():
        for _, b_spans in clusters_b:
            pt_spans = [s for s in b_spans if s.max_subpath_dim <= 18.0]
            non_pt_spans = [s for s in b_spans if s.max_subpath_dim > 18.0]
            n_pt_marks = sum(s.paint_count for s in pt_spans)
            emitted_gids: list[str] = []
            if non_pt_spans and pt_spans and n_pt_marks >= 3:
                # Genuine overlaying graph (e.g. Violin/Boxplot/Ribbon + Curve + >= 3 Individual Data Points):
                # emit clean independent ColorGroups for `area`, `line`, and `point` so each picks and adjusts opacity cleanly!
                area_spans = [
                    s for s in non_pt_spans if (not s.is_stroke) or (s.used_with_same_fill and not s.used_standalone)
                ]
                line_spans = [
                    s for s in non_pt_spans if s.is_stroke and not (s.used_with_same_fill and not s.used_standalone)
                ]
                if area_spans:
                    emitted_gids.append(_emit_color_group(area_spans, "area"))
                if line_spans:
                    emitted_gids.append(_emit_color_group(line_spans, "line"))
                emitted_gids.append(_emit_color_group(pt_spans, "point"))
            elif non_pt_spans:
                area_spans = [
                    s for s in b_spans if (not s.is_stroke) or (s.used_with_same_fill and not s.used_standalone)
                ]
                line_spans = [
                    s for s in b_spans if s.is_stroke and not (s.used_with_same_fill and not s.used_standalone)
                ]
                if area_spans and line_spans:
                    emitted_gids.append(_emit_color_group(area_spans, "area"))
                    emitted_gids.append(_emit_color_group(line_spans, "line"))
                elif area_spans:
                    emitted_gids.append(_emit_color_group(b_spans, "area"))
                else:
                    emitted_gids.append(_emit_color_group(b_spans, "line"))
            else:
                emitted_gids.append(_emit_color_group(b_spans, "point"))

            if len(emitted_gids) > 1:
                for i_em in range(len(emitted_gids)):
                    for j_em in range(i_em + 1, len(emitted_gids)):
                        sibling_layer_pairs.append((emitted_gids[i_em], emitted_gids[j_em]))

    # Couple ContinuousScales per panel
    continuous_scales: dict[str, ContinuousScale] = {}
    for xo_name, (pid, cb_bbox, lut, is_div, mid_t) in colorbar_luts.items():
        scale_id = f"scale_{len(continuous_scales) + 1:02d}"
        cb_title = f"{pid} Continuous Scale"
        best_dy = 1e9
        for t in texts:
            if t.panel_id != pid or t.text.replace(".", "").replace("-", "").isdigit():
                continue
            dy = cb_bbox[1] - t.bbox[3]
            dx = abs(t.bbox[0] - cb_bbox[0])
            if -6.0 <= dy <= 36.0 and dx <= 55.0 and dy < best_dy:
                best_dy = dy
                cb_title = t.text

        cand_groups = [cg for cg in color_groups.values() if cg.panel_id == pid]
        matched_members: list[str] = []
        if cand_groups:
            srgbs = np.stack([hex_to_srgb01(cg.original_hex) for cg in cand_groups], axis=0)
            ts, res = project_colors_onto_lut(srgbs, lut)
            for cg, t_val, r_val in zip(cand_groups, ts, res):
                if r_val <= 0.045 and not (cg.role == "stroke" and len(cand_groups) > 8 and r_val > 0.014):
                    cg.is_continuous_member = True
                    cg.continuous_scale_id = scale_id
                    cg.continuous_t = round(float(t_val), 4)
                    matched_members.append(cg.group_id)

        r_hm_list = raster_heatmaps_by_panel.get(pid, [])
        r_hm_xo = r_hm_list[0][0] if r_hm_list else None
        stop_idx = [0, 64, 128, 192, 255]
        orig_stops = [srgb01_to_hex(lut[i]) for i in stop_idx]
        continuous_scales[scale_id] = ContinuousScale(
            scale_id=scale_id,
            panel_id=pid,
            title=cb_title,
            kind="continuous_diverging" if is_div else "continuous_sequential",
            midpoint_t=round(mid_t, 3),
            colorbar_xobject=xo_name,
            colorbar_bbox=tuple(round(x, 2) for x in cb_bbox),
            raster_heatmap_xobject=r_hm_xo,
            member_group_ids=matched_members,
            original_stops_hex=orig_stops,
            current_stops_hex=list(orig_stops),
        )

    # Detect vector colorbar stacks (e.g. matplotlib/seaborn/svglite 32+ adjacent thin color rectangles without an /Image strip!)
    _detect_vector_colorbar_scales(op_spans, color_groups, continuous_scales, texts)

    # Detect Gate G3b In-Cell Numeric Labels inside matrix heatmaps (<= 600 tiles)
    cell_text_labels: list[CellTextLabel] = []
    cont_panels = {
        cs.panel_id
        for cs in continuous_scales.values()
        if cs.member_group_ids
        and sum(color_groups[gid].primitive_count for gid in cs.member_group_ids) <= 600
    }
    if cont_panels and tj_records:
        tile_rects: list[tuple[str, tuple[float, float, float, float], str]] = []
        ctm_t: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        cur_f_t: int | None = None
        st_t: list[tuple[Any, ...]] = []
        pb_t = [1e9, 1e9, -1e9, -1e9]
        span_by_end = {sp.end: idx_s for idx_s, sp in enumerate(op_spans) if sp.stream_key == "__page__"}
        for m_t in _STREAM_CMD_RE.finditer(raw_streams["__page__"]):
            k_t = m_t.lastgroup
            tk_t = m_t.group(0)
            if k_t == "numop":
                ps = tk_t.split()
                op_t = ps[-1]
                if op_t == b"cm" and len(ps) >= 7:
                    ctm_t = _mat_mul(tuple(float(x) for x in ps[-7:-1]), ctm_t)
                elif op_t in (b"rg", b"g", b"k", b"sc", b"scn"):
                    cur_f_t = span_by_end.get(m_t.end())
                elif op_t == b"re" and len(ps) >= 5:
                    ns = [float(x) for x in ps[-5:-1]]
                    rb = _rect_to_page_bbox(ctm_t, ns[0], ns[1], ns[2], ns[3], page_h)
                    pb_t = [min(pb_t[0], rb[0]), min(pb_t[1], rb[1]), max(pb_t[2], rb[2]), max(pb_t[3], rb[3])]
                elif op_t in (b"m", b"l") and len(ps) >= 3:
                    px, py = _apply_ctm(ctm_t, float(ps[-3]), float(ps[-2]), page_h)
                    pb_t = [min(pb_t[0], px), min(pb_t[1], py), max(pb_t[2], px), max(pb_t[3], py)]
                continue
            if k_t == "q":
                st_t.append((ctm_t, cur_f_t))
            elif k_t == "Q" and st_t:
                ctm_t, cur_f_t = st_t.pop()
            elif k_t == "clip":
                pb_t = [1e9, 1e9, -1e9, -1e9]
            elif k_t == "paint":
                if pb_t[0] < 1e8 and cur_f_t is not None and tk_t.decode("ascii") in ("f", "f*", "F", "B", "B*"):
                    sp_c = op_spans[cur_f_t]
                    if sp_c.panel_id in cont_panels and sp_c.group_id and color_groups[sp_c.group_id].is_continuous_member:
                        tile_rects.append((sp_c.panel_id, (pb_t[0], pb_t[1], pb_t[2], pb_t[3]), sp_c.group_id))
                pb_t = [1e9, 1e9, -1e9, -1e9]

        for _, tj_s, tj_e, c_span, (bx, by) in tj_records:
            if c_span is None:
                continue
            pid_tj = _assign_panel_id(panels, bx, by)
            if pid_tj not in cont_panels:
                continue
            enc_gid: str | None = None
            enc_tb: tuple[float, float, float, float] | None = None
            best_area = 1e18
            for pid_r, tb_r, gid_r in tile_rects:
                if pid_r == pid_tj and (tb_r[0] + 1.0) <= (bx + 5.0) <= (tb_r[2] - 1.0) and (tb_r[1] + 1.0) <= (by - 2.0) <= (tb_r[3] - 1.0):
                    area = (tb_r[2] - tb_r[0]) * (tb_r[3] - tb_r[1])
                    if area < best_area:
                        best_area = area
                        enc_gid = gid_r
                        enc_tb = tb_r
            if enc_gid is not None and enc_tb is not None:
                cell_text_labels.append(
                    CellTextLabel(
                        op_index=tj_s,
                        color_op_index=tj_e,
                        panel_id=pid_tj,
                        text="cell_val",
                        bbox=tuple(round(v, 2) for v in enc_tb),
                        enclosing_group_id=enc_gid,
                        original_hex=op_spans[c_span].srgb_hex,
                        current_hex=op_spans[c_span].srgb_hex,
                    )
                )

    # Generalized Legend Swatch -> Text Binding
    _bind_legend_labels(op_spans, color_groups, texts, panels)

    # Sync labels between overlaid sibling layers (`area`/`line` <-> `point`) in the same panel & color cluster
    for gid_a, gid_b in sibling_layer_pairs:
        cg_a = color_groups.get(gid_a)
        cg_b = color_groups.get(gid_b)
        if cg_a and cg_b:
            if cg_a.local_label and not cg_b.local_label:
                cg_b.local_label = cg_a.local_label
            elif cg_b.local_label and not cg_a.local_label:
                cg_a.local_label = cg_b.local_label

    # Propagate unambiguous shared figure-wide legend labels (`fig.legend`, `patchwork`, `ggpubr`) across panels
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
                cand_norms = {_normalize_factor_key(labeled_cgs[idx_l].local_label).lower() for idx_l in near_idxs}
                if len(cand_norms) != 1:
                    continue
                best_lbl = labeled_cgs[min(near_idxs, key=lambda idx_l: float(d_vec[idx_l]))].local_label
                target_norm = next(iter(cand_norms))
                panel_conflict = any(
                    other.panel_id == cg.panel_id
                    and other.local_label
                    and _normalize_factor_key(other.local_label).lower() == target_norm
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

    # Prune unlabeled pure-achromatic standalone strokes (boxplot whiskers, medians, caps, error bars, gray spines)
    for gid_p in list(color_groups.keys()):
        cg_p = color_groups[gid_p]
        if cg_p.is_continuous_member or cg_p.role != "stroke" or cg_p.local_label:
            continue
        _, C_p, _ = hex_to_oklch(cg_p.original_hex)
        if C_p < 0.012 and not any(op_spans[sid].used_with_same_fill for sid in cg_p.op_indices):
            for sid in cg_p.op_indices:
                op_spans[sid].mutable = False
                op_spans[sid].group_id = None
            del color_groups[gid_p]

    # Build Semantic Entities & Detect Plain-Language Notices
    entities, collisions, plain_notices = _build_entities_and_collisions(
        color_groups, continuous_scales, panels, sibling_layer_pairs=sibling_layer_pairs
    )

    # Scanned-PDF check (Spec 4.1: "This page contains only an image, no editable shapes.")
    has_big_img = any(
        (ib[2] - ib[0]) * (ib[3] - ib[1]) >= 0.45 * page_w * page_h
        for _, ib in xobj_placements
    )
    is_scanned_only = bool(has_big_img and len(color_groups) == 0 and len(continuous_scales) == 0)

    if progress_cb:
        progress_cb("preview", 85)

    scene = ParsedPdfScene(
        scene_id=scene_id,
        filename=filename,
        raw_pdf_bytes=pdf_bytes,
        page_width=page_w,
        page_height=page_h,
        panels=panels,
        texts=texts,
        evidence_regions=evidence_regions,
        color_groups=color_groups,
        continuous_scales=continuous_scales,
        entities=entities,
        cell_text_labels=cell_text_labels,
        collisions=collisions,
        page_index=p_idx,
        page_count=n_pages,
        total_stream_ops=stream_op_counter,
        is_scanned_only=is_scanned_only,
        plain_notices=plain_notices,
        raw_content_bytes=raw_streams["__page__"],
        raw_streams=raw_streams,
        form_xobj_paths=form_xobj_paths,
        cs_tokens_by_stream=cs_tokens_by_stream,
        op_spans=op_spans,
        colorbar_raw_rgb=colorbar_raw_rgb,
        colorbar_lut_t=colorbar_lut_t,
        geometry_hash_original=geom_hash,
    )
    _render_interactive_layers(scene)
    if progress_cb:
        progress_cb("done", 100)
    return scene


def _detect_vector_colorbar_scales(
    op_spans: list[ColorOpSpan],
    color_groups: dict[str, ColorGroup],
    continuous_scales: dict[str, ContinuousScale],
    texts: list[TextItem],
) -> None:
    """Detect vector-drawn colorbar strips (e.g. matplotlib QuadMesh/Polygon colorbar with >= 16 stacked thin rects)."""
    panels_with_cb = {cs.panel_id for cs in continuous_scales.values()}
    by_panel: dict[str, list[ColorOpSpan]] = {}
    for sp in op_spans:
        if sp.mutable and sp.group_id and not sp.is_stroke and sp.panel_id not in panels_with_cb:
            sw = sp.bbox[2] - sp.bbox[0]
            sh = sp.bbox[3] - sp.bbox[1]
            if sp.paint_count <= 2 and 3.0 <= sw <= 28.0 and 0.3 <= sh <= 8.0:
                by_panel.setdefault(sp.panel_id, []).append(sp)

    for pid, sps in by_panel.items():
        if len(sps) < 16:
            continue
        # Cluster by x0 alignment (within 3 pt)
        x_buckets: dict[int, list[ColorOpSpan]] = {}
        for sp in sps:
            x_buckets.setdefault(int(round(sp.bbox[0] / 3.0)), []).append(sp)
        best_col = max(x_buckets.values(), key=len)
        if len(best_col) < 16:
            continue
        # Sort bottom-to-top (in top-left coords, larger y is bottom = low value)
        best_col.sort(key=lambda s: s.bbox[1], reverse=True)
        unique_hexes = list(dict.fromkeys(s.srgb_hex for s in best_col))
        if len(unique_hexes) < 10:
            continue
        strip_arr = np.stack([hex_to_srgb01(s.srgb_hex) for s in best_col], axis=0)[:, None, :]
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
            if t.panel_id == pid and not t.text.replace(".", "").replace("-", "").isdigit():
                if -8.0 <= (cb_bbox[1] - t.bbox[3]) <= 36.0 and abs(t.bbox[0] - cb_bbox[0]) <= 60.0:
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


def _bind_legend_labels(
    op_spans: list[ColorOpSpan],
    color_groups: dict[str, ColorGroup],
    texts: list[TextItem],
    panels: list[PanelBox],
) -> None:
    """Match legend keys (rectangles, circles, line segments, hollow symbols) to right-of-key or below-key text labels."""
    panel_texts: dict[str, list[TextItem]] = {}
    for t in texts:
        panel_texts.setdefault(t.panel_id, []).append(t)
    panel_map = {p.panel_id: p for p in panels}

    # Gather candidate key boxes: (panel_id, group_id, bbox, paint_count)
    raw_keys: list[tuple[str, str, tuple[float, float, float, float], int]] = []
    for sp in op_spans:
        if not sp.mutable or sp.group_id is None:
            continue
        cg = color_groups[sp.group_id]
        if cg.is_continuous_member:
            continue
        sw = sp.bbox[2] - sp.bbox[0]
        sh = sp.bbox[3] - sp.bbox[1]
        if sw <= 36.0 and sh <= 28.0 and sp.paint_count <= 8:
            raw_keys.append((sp.panel_id, cg.group_id, (sp.bbox[0], sp.bbox[1], sp.bbox[2], sp.bbox[3]), sp.paint_count))
        elif sp.swatch_bboxes and sp.paint_count <= 12:
            for sb in sp.swatch_bboxes:
                raw_keys.append((sp.panel_id, cg.group_id, sb, sp.paint_count))

    # Pre-score candidate (key -> text) pairs per panel (and shared figure margins) so aligned legend stacks win!
    cand_matches: list[tuple[str, str, tuple[float, float, float, float], TextItem, float, bool]] = []
    for pid, gid, kbox, pcnt in raw_keys:
        pb = panel_map[pid].bbox
        rel_x = (kbox[0] - pb[0]) / max(1.0, pb[2] - pb[0])
        rel_y = (kbox[1] - pb[1]) / max(1.0, pb[3] - pb[1])
        in_margin = bool(rel_x > 0.66 or rel_x < 0.24 or rel_y > 0.80 or rel_y < 0.18)
        margin_bonus = 35.0 if in_margin else 0.0
        single_bonus = 18.0 if pcnt <= 3 else 0.0
        fill_bonus = 2.5 if color_groups[gid].role == "fill" else 0.0
        scx = 0.5 * (kbox[0] + kbox[2])
        scy = 0.5 * (kbox[1] + kbox[3])

        # For margin / shared figure legends (`fig.legend`, `patchwork`), also allow text just across a panel split
        cand_texts = texts if (in_margin and len(panels) > 1) else panel_texts.get(pid, [])
        for t in cand_texts:
            txt_clean = t.text.strip()
            if (
                not txt_clean
                or re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?%?", txt_clean)
                or re.fullmatch(r"[\u25a0-\u25ff\u2022\u2219\u2605\u2606\u2713-\u2718\s]+", txt_clean)
            ):
                continue
            if len(txt_clean) == 1 and "A" <= txt_clean <= "Z" and (t.bbox[1] - pb[1]) < 35.0:
                continue
            tcx = 0.5 * (t.bbox[0] + t.bbox[2])
            tcy = 0.5 * (t.bbox[1] + t.bbox[3])

            # Case 1: label to the right of key (vertical or multi-column legend)
            dx_r = t.bbox[0] - kbox[2]
            dy_r = abs(tcy - scy)
            if -3.5 <= dx_r <= 34.0 and dy_r <= 8.5:
                base_sc = 50.0 + margin_bonus + single_bonus + fill_bonus - abs(dx_r) - 2.2 * dy_r
                cand_matches.append((pid, gid, kbox, t, base_sc, in_margin))
                continue

            # Case 2: label directly below key (horizontal bottom/top legend)
            dy_b = t.bbox[1] - kbox[3]
            dx_b = abs(tcx - scx)
            if pcnt <= 4 and (kbox[2] - kbox[0]) <= 26.0 and (kbox[3] - kbox[1]) <= 20.0 and -1.0 <= dy_b <= 15.0 and dx_b <= 20.0:
                base_sc = 36.0 + margin_bonus + single_bonus + fill_bonus - 1.5 * dy_b - 1.5 * dx_b
                cand_matches.append((pid, gid, kbox, t, base_sc, in_margin))

    # Boost matches that form an aligned column (`|x0_a - x0_b| <= 4.5`) or row (`|y0_a - y0_b| <= 4.5`) with DIFFERENT group_ids!
    scored_matches: list[tuple[float, str, TextItem, tuple[float, float, float, float]]] = []
    for i, (pid, gid, kbox, t, base_sc, in_margin) in enumerate(cand_matches):
        peers = sum(
            1
            for j, (pid2, gid2, kbox2, t2, _, in_margin2) in enumerate(cand_matches)
            if i != j
            and (pid2 == pid or (in_margin and in_margin2))
            and gid2 != gid
            and t2.text != t.text
            and (abs(kbox[0] - kbox2[0]) <= 4.5 or abs(kbox[1] - kbox2[1]) <= 4.5)
        )
        # Require either margin position OR >= 1 aligned legend peer so random inside-plot bars don't steal axis/annotation text
        if peers == 0 and base_sc < 75.0:
            continue
        total_sc = base_sc + min(3, peers) * 24.0
        scored_matches.append((total_sc, gid, t, kbox))

    # Sort best-first and prevent a differently-colored border stroke at the exact same kbox from stealing a filled swatch's label
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


def _normalize_factor_key(label: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()


def _build_entities_and_collisions(
    color_groups: dict[str, ColorGroup],
    continuous_scales: dict[str, ContinuousScale],
    panels: list[PanelBox],
    sibling_layer_pairs: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, SemanticEntity], list[CollisionNotice], list[dict[str, Any]]]:
    entities: dict[str, SemanticEntity] = {}
    label_to_eid: dict[str, str] = {}
    sibling_partners: dict[str, list[str]] = {}
    for ga, gb in sibling_layer_pairs or []:
        sibling_partners.setdefault(ga, []).append(gb)
        sibling_partners.setdefault(gb, []).append(ga)
    gid_to_eid: dict[str, str] = {}
    label_panel_hexes: dict[str, list[tuple[str, str, str]]] = {}

    cat_groups = [cg for cg in color_groups.values() if not cg.is_continuous_member]

    for cg in cat_groups:
        raw_lbl = cg.local_label.strip()
        norm_key = _normalize_factor_key(raw_lbl).lower() if raw_lbl else ""
        matched_sib_eid = next(
            (gid_to_eid[sg] for sg in sibling_partners.get(cg.group_id, []) if sg in gid_to_eid),
            None,
        )
        if norm_key and norm_key in label_to_eid:
            eid = label_to_eid[norm_key]
            ent = entities[eid]
            ent.member_group_ids.append(cg.group_id)
            if cg.panel_id not in ent.panels:
                ent.panels.append(cg.panel_id)
            gid_to_eid[cg.group_id] = eid
            label_panel_hexes[norm_key].append((cg.panel_id, cg.original_hex, eid))
        elif not norm_key and matched_sib_eid is not None:
            # Merge unlabeled overlaid points + lines + area in the same panel & color cluster into one cohort entity by default
            eid = matched_sib_eid
            ent = entities[eid]
            ent.member_group_ids.append(cg.group_id)
            gid_to_eid[cg.group_id] = eid
            tot_cnt = sum(color_groups[g].primitive_count for g in ent.member_group_ids if g in color_groups)
            ent.label = describe_color_group(ent.original_hex, tot_cnt)
        else:
            eid = f"e_{len(entities) + 1:02d}"
            disp = _normalize_factor_key(raw_lbl) if raw_lbl else describe_color_group(cg.original_hex, cg.primitive_count)
            if norm_key:
                label_to_eid[norm_key] = eid
                label_panel_hexes[norm_key] = [(cg.panel_id, cg.original_hex, eid)]
            gid_to_eid[cg.group_id] = eid
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
                original_alpha=cg.alpha,
                encoding="categorical",
                tier="normal",
                tier_reason="",
                is_control_candidate=is_ctrl,
            )

    collisions: list[CollisionNotice] = []
    plain_notices: list[dict[str, Any]] = []

    # Check if the uploaded figure used inconsistent colors for the SAME element name across panels (Spec 4.2)
    for norm_key, ph_list in label_panel_hexes.items():
        if len(ph_list) >= 2:
            hexes = [h for _, h, _ in ph_list]
            arr = np.stack([hex_to_srgb01(h) for h in hexes], axis=0)
            if float(ciede2000_matrix(arr).max()) >= 10.0:
                eid = ph_list[0][2]
                p_a, p_b = ph_list[0][0], ph_list[-1][0]
                plain_notices.append(
                    {
                        "kind": "inconsistent_same_name",
                        "entity_ids": [eid],
                        "label": entities[eid].label,
                        "panel_a": p_a,
                        "panel_b": p_b,
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
                shared_panels = set(ea.panels) & set(eb.panels)
                if shared_panels and (d_n < 12.0 or d_cvd < 8.5):
                    p_str = ", ".join(sorted(shared_panels))
                    for sp_id in shared_panels:
                        cb_by_panel.setdefault(sp_id, set()).update((ea.entity_id, eb.entity_id))
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
                elif not shared_panels and d_n < 9.5:
                    collisions.append(
                        CollisionNotice(
                            collision_id=f"col_{len(collisions) + 1:02d}",
                            scope="cross_panel",
                            original_hex_a=ea.original_hex,
                            original_hex_b=eb.original_hex,
                            delta_e00=round(d_n, 2),
                            entities_involved=[
                                {"entity_id": ea.entity_id, "label": ea.label, "panel_id": ",".join(ea.panels)},
                                {"entity_id": eb.entity_id, "label": eb.label, "panel_id": ",".join(eb.panels)},
                            ],
                            description=f"{ea.label} / {eb.label}",
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

    return entities, collisions, plain_notices[:2]


def _rewrite_stream_arbitrary(
    raw_stream: bytes,
    slice_replacements: list[tuple[int, int, bytes]],
) -> bytes:
    if not slice_replacements:
        return raw_stream
    is_monotonic = True
    prev_s = -1
    for s, _, _ in slice_replacements:
        if s < prev_s:
            is_monotonic = False
            break
        prev_s = s
    ordered = slice_replacements if is_monotonic else sorted(slice_replacements, key=lambda x: x[0])
    out = bytearray()
    cursor = 0
    for s, e, b in ordered:
        if s < cursor:
            continue
        out.extend(raw_stream[cursor:s])
        out.extend(b)
        cursor = e
    out.extend(raw_stream[cursor:])
    return bytes(out)


def _format_rgb_op(hex_str: str, is_stroke: bool) -> bytes:
    r, g, b = hex_to_srgb01(hex_str)
    op = "RG" if is_stroke else "rg"
    return f"{r:.5f} {g:.5f} {b:.5f} {op}".encode("ascii")


def _png_bytes(pil_img: Image.Image) -> bytes:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", compress_level=3)
    return buf.getvalue()


def _resolve_nested_xobject(
    page_obj: pikepdf.Object,
    chain: list[str],
    pdf_doc: pikepdf.Pdf,
    clone_for_isolation: bool = False,
) -> pikepdf.Object | None:
    cur = page_obj
    for depth_i, key in enumerate(chain):
        res = cur.get("/Resources")
        if not res or "/XObject" not in res or key not in res["/XObject"]:
            return None
        xo = res["/XObject"][key]
        if clone_for_isolation and depth_i == len(chain) - 1:
            cloned = pdf_doc.make_stream(xo.read_bytes())
            for dk in xo.keys():
                if str(dk) not in ("/Length", "/Filter", "/DecodeParms"):
                    cloned[dk] = xo[dk]
            res["/XObject"][key] = cloned
            return cloned
        cur = xo
    return cur


def _neutralize_resources_for_id_map(
    res: pikepdf.Object | None,
    pdf_doc: pikepdf.Pdf,
    mutable_xos: dict[str, tuple[int, int]],
    colorbar_lut_t: dict[str, np.ndarray],
    prefix: list[str],
    visited: set[tuple[int, int]],
) -> None:
    if not res:
        return
    if "/ExtGState" not in res:
        res["/ExtGState"] = pikepdf.Dictionary()
    for k_gs in list(res["/ExtGState"].keys()):
        gs_obj = res["/ExtGState"][k_gs]
        gs_obj["/ca"] = 1
        gs_obj["/CA"] = 1
        if "/SMask" in gs_obj:
            gs_obj["/SMask"] = pikepdf.Name("/None")
        if "/BM" in gs_obj:
            gs_obj["/BM"] = pikepdf.Name("/Normal")
    res["/ExtGState"]["/DqS0"] = pikepdf.Dictionary({"/Type": pikepdf.Name("/ExtGState"), "/CA": 0})
    res["/ExtGState"]["/DqS1"] = pikepdf.Dictionary({"/Type": pikepdf.Name("/ExtGState"), "/CA": 1})

    if "/XObject" in res:
        for k_xo in list(res["/XObject"].keys()):
            xo = res["/XObject"][k_xo]
            og = getattr(xo, "objgen", (0, 0))
            if og != (0, 0) and og in visited:
                continue
            if og != (0, 0):
                visited.add(og)
            st = str(xo.get("/Subtype", ""))
            full_key = "/".join(prefix + [str(k_xo)]) if prefix else str(k_xo)
            if st == "/Image":
                if full_key in mutable_xos and full_key in colorbar_lut_t:
                    s_code, p_code = mutable_xos[full_key]
                    t_grid = colorbar_lut_t[full_key]
                    h_i, w_i = t_grid.shape
                    enc = np.zeros((h_i, w_i, 3), dtype=np.uint8)
                    enc[..., 0] = s_code
                    enc[..., 1] = np.clip(np.round(t_grid * 255.0), 0, 255).astype(np.uint8)
                    enc[..., 2] = p_code
                    xo.write(enc.tobytes())
                    xo["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
                    xo["/BitsPerComponent"] = 8
                    for k_rm in ("/Filter", "/DecodeParms", "/SMask", "/Mask", "/Decode"):
                        if k_rm in xo:
                            del xo[k_rm]
                else:
                    w_i, h_i = int(xo.get("/Width", 1)), int(xo.get("/Height", 1))
                    smask = pdf_doc.make_stream(b"\x00" * (w_i * h_i))
                    smask["/Type"] = pikepdf.Name("/XObject")
                    smask["/Subtype"] = pikepdf.Name("/Image")
                    smask["/Width"] = w_i
                    smask["/Height"] = h_i
                    smask["/ColorSpace"] = pikepdf.Name("/DeviceGray")
                    smask["/BitsPerComponent"] = 8
                    xo["/SMask"] = smask
            elif st == "/Form":
                if "/Resources" in xo:
                    _neutralize_resources_for_id_map(
                        xo.get("/Resources"), pdf_doc, mutable_xos, colorbar_lut_t, prefix + [str(k_xo)], visited
                    )


def _render_interactive_layers(scene: ParsedPdfScene) -> None:
    """Build original_png and non-antialiased id_map_png (used strictly for picking/hit-testing)."""
    max_dim = max(scene.page_width, scene.page_height)
    scale = min(2.0, max(1.25, 1920.0 / max(1.0, max_dim)))
    scene.preview_scale = scale

    pil_orig = render_pdf_page_to_pil(
        scene.raw_pdf_bytes, page_index=scene.page_index, scale=scale, fill_color=(255, 255, 255, 255)
    )
    scene.original_png = _png_bytes(pil_orig)

    cat_group_ids_ordered = [gid for gid, cg in scene.color_groups.items() if not cg.is_continuous_member]
    cat_gid_to_idx: dict[str, int] = {gid: i for i, gid in enumerate(cat_group_ids_ordered)}
    scale_ids_ordered = list(scene.continuous_scales.keys())
    sid_to_code: dict[str, int] = {sid: 254 - i for i, sid in enumerate(scale_ids_ordered)}
    panel_to_idx = {p.panel_id: idx + 1 for idx, p in enumerate(scene.panels)}

    mutable_xos: dict[str, tuple[int, int]] = {}
    for cs in scene.continuous_scales.values():
        s_code = sid_to_code[cs.scale_id]
        p_code = panel_to_idx.get(cs.panel_id, 1)
        for xo_key in (cs.colorbar_xobject, cs.raster_heatmap_xobject):
            if xo_key:
                mutable_xos[xo_key] = (s_code, p_code)

    with pikepdf.open(io.BytesIO(scene.raw_pdf_bytes)) as pdf_id:
        p0 = pdf_id.pages[scene.page_index]
        if "/Resources" not in p0.obj:
            p0.obj["/Resources"] = pikepdf.Dictionary()
        _neutralize_resources_for_id_map(
            p0.obj["/Resources"], pdf_id, mutable_xos, scene.colorbar_lut_t, [], set()
        )

        # Group span replacements by stream_key and blank out `/CSx cs` operators so `rg/RG` id-colors apply cleanly
        slices_by_stream: dict[str, list[tuple[int, int, bytes]]] = {
            sk: [(s, e, b" ") for s, e in cs_list]
            for sk, cs_list in scene.cs_tokens_by_stream.items()
        }
        for sp in scene.op_spans:
            op_tok = "RG" if sp.is_stroke else "rg"
            if not sp.mutable or sp.group_id is None:
                # Hide immutable strokes (`/CA = 0`) in pick map so point/boxplot outlines never eat or punch holes in fills
                rep = b"/DqS0 gs 0 0 0 RG" if sp.is_stroke else b"0 0 0 rg"
            else:
                cg = scene.color_groups[sp.group_id]
                p_code = panel_to_idx.get(cg.panel_id, 1)
                if cg.is_continuous_member and cg.continuous_scale_id:
                    r_u8 = sid_to_code[cg.continuous_scale_id]
                    g_u8 = int(round(cg.continuous_t * 255.0))
                else:
                    c_idx = cat_gid_to_idx[cg.group_id]
                    r_u8 = 1 + (c_idx % 240)
                    g_u8 = (c_idx // 240) & 0xFF
                prefix_gs = "/DqS1 gs " if sp.is_stroke else ""
                rep = f"{prefix_gs}{r_u8 / 255.0:.6f} {g_u8 / 255.0:.6f} {p_code / 255.0:.6f} {op_tok}".encode("ascii")
            slices_by_stream.setdefault(sp.stream_key, []).append((sp.start, sp.end, rep))

        for sk, raw_b in scene.raw_streams.items():
            rewritten = _rewrite_stream_arbitrary(raw_b, slices_by_stream.get(sk, []))
            if sk == "__page__":
                p0.Contents = pdf_id.make_stream(rewritten)
            elif sk in scene.form_xobj_paths:
                fxo = _resolve_nested_xobject(p0.obj, scene.form_xobj_paths[sk], pdf_id, clone_for_isolation=(scene.page_count > 1))
                if fxo is not None:
                    fxo.write(rewritten)

        buf_id = io.BytesIO()
        pdf_id.save(buf_id, compress_streams=False)

    pil_id = render_pdf_page_to_pil(
        buf_id.getvalue(),
        page_index=scene.page_index,
        scale=scale,
        fill_color=(0, 0, 0, 255),
        no_smooth=True,
    )
    scene.id_map_png = _png_bytes(pil_id)


def render_preview_png(
    scene: ParsedPdfScene,
    group_hex_map: dict[str, str],
    scale_stops_map: dict[str, list[str]],
    scale: float | None = None,
    group_alpha_map: dict[str, float] | None = None,
) -> bytes:
    """Render the EXACT recolored PDF at `scale` (default `scene.preview_scale`), ensuring preview == export."""
    pdf_bytes, _ = export_recolored_pdf(
        scene,
        group_hex_map,
        scale_stops_map,
        verify=False,
        group_alpha_map=group_alpha_map,
    )
    target_scale = float(scale) if scale is not None else scene.preview_scale
    if pdf_bytes is scene.raw_pdf_bytes and abs(target_scale - scene.preview_scale) < 1e-4 and scene.original_png:
        return scene.original_png
    pil = render_pdf_page_to_pil(
        pdf_bytes,
        page_index=scene.page_index,
        scale=target_scale,
        fill_color=(255, 255, 255, 255),
    )
    buf = io.BytesIO()
    pil.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def export_recolored_pdf(
    scene: ParsedPdfScene,
    group_hex_map: dict[str, str],
    scale_stops_map: dict[str, list[str]],
    verify: bool = True,
    group_alpha_map: dict[str, float] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Write byte-exact vector PDF on `scene.page_index` with G0 raw-image lock and G6 geometry verification."""
    resolved_group_hex = dict(group_hex_map)
    alpha_changed_groups: dict[str, float] = {}
    if group_alpha_map:
        for gid_a, raw_a in group_alpha_map.items():
            if raw_a is not None and gid_a in scene.color_groups:
                clamped_a = max(0.0, min(1.0, float(raw_a)))
                if abs(clamped_a - scene.color_groups[gid_a].alpha) >= 0.005:
                    alpha_changed_groups[gid_a] = clamped_a

    scale_luts: dict[str, np.ndarray] = {}
    scale_modified: dict[str, bool] = {}
    for sid, cs in scene.continuous_scales.items():
        stops = scale_stops_map.get(sid, cs.current_stops_hex)
        is_orig_scale = (
            not cs.inverted_polarity
            and [s.upper() for s in stops] == [s.upper() for s in cs.original_stops_hex]
        )
        scale_modified[sid] = not is_orig_scale
        if is_orig_scale:
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

    any_changed = (
        any(
            resolved_group_hex.get(gid, cg.original_hex).upper() != cg.original_hex.upper()
            for gid, cg in scene.color_groups.items()
        )
        or bool(alpha_changed_groups)
        or any(scale_modified.values())
    )
    if not any_changed:
        return scene.raw_pdf_bytes, {
            "g0_evidence_bit_identical": True,
            "g0_locked_objects": [
                ev.xobject_name
                for ev in scene.evidence_regions
                if ev.mutability in ("class0_sacrosanct_evidence", "class1_fluorescence_lut")
            ],
            "g6_geometry_hash_before": scene.geometry_hash_original,
            "g6_geometry_hash_after": scene.geometry_hash_original,
            "g6_geometry_identical": True,
            "modified_vector_ops": 0,
            "modified_colorbar_rasters": 0,
            "g3b_inverted_cell_labels": 0,
        }

    # Pre-compute RGB byte tokens once per changed group_id (O(groups) instead of O(10^6 spans))
    changed_groups: dict[str, tuple[bytes, bytes, str]] = {}
    for gid, cg in scene.color_groups.items():
        nh = resolved_group_hex.get(gid, cg.original_hex).upper()
        if nh != cg.original_hex.upper():
            changed_groups[gid] = (_format_rgb_op(nh, False), _format_rgb_op(nh, True), nh)

    has_named_cs = any(bool(v) for v in scene.cs_tokens_by_stream.values())
    streams_switching_cs: set[str] = set()
    if has_named_cs and changed_groups:
        for sp in scene.op_spans:
            if sp.mutable and sp.group_id in changed_groups and sp.cs_op in ("sc", "scn", "SC", "SCN"):
                if not (sp.active_cs_kind == "rgb" and sp.active_cs_ncomp == 3):
                    streams_switching_cs.add(sp.stream_key)

    streams_switching_alpha: set[str] = set()
    if alpha_changed_groups:
        for sp in scene.op_spans:
            if sp.mutable and sp.group_id in alpha_changed_groups:
                streams_switching_alpha.add(sp.stream_key)

    needed_alpha_gs: dict[str, dict[str, tuple[bool, int]]] = {}
    slices_by_stream: dict[str, list[tuple[int, int, bytes]]] = {}
    sc_rep_cache: dict[tuple[str, str], bytes] = {}
    mod_ops = 0

    def _alpha_gs_suffix(stream_k: str, is_st: bool, a_val: float) -> bytes:
        pct = max(0, min(100, int(round(a_val * 100.0))))
        gs_tag = f"/DqSA{pct}" if is_st else f"/DqFA{pct}"
        needed_alpha_gs.setdefault(stream_k, {})[gs_tag] = (is_st, pct)
        return f" {gs_tag} gs".encode("ascii")

    for sp in scene.op_spans:
        gid = sp.group_id
        in_alpha_stream = sp.stream_key in streams_switching_alpha
        has_custom_alpha = bool(sp.mutable and gid is not None and gid in alpha_changed_groups)
        alpha_suffix = b""
        if in_alpha_stream:
            target_a = alpha_changed_groups[gid] if has_custom_alpha and gid is not None else sp.alpha
            alpha_suffix = _alpha_gs_suffix(sp.stream_key, sp.is_stroke, target_a)

        if sp.mutable and gid is not None and gid in changed_groups:
            fill_rep, stroke_rep, new_h = changed_groups[gid]
            if sp.cs_op in ("sc", "scn", "SC", "SCN") and sp.active_cs_kind == "rgb" and sp.active_cs_ncomp == 3:
                ck = (new_h, sp.cs_op)
                rep = sc_rep_cache.get(ck)
                if rep is None:
                    r, g, b = hex_to_srgb01(new_h)
                    rep = f"{r:.5f} {g:.5f} {b:.5f} {sp.cs_op}".encode("ascii")
                    sc_rep_cache[ck] = rep
            else:
                rep = stroke_rep if sp.is_stroke else fill_rep
            slices_by_stream.setdefault(sp.stream_key, []).append((sp.start, sp.end, rep + alpha_suffix))
            if has_custom_alpha and sp.post_gs_ends:
                for gs_end in sp.post_gs_ends:
                    slices_by_stream[sp.stream_key].append((gs_end, gs_end, alpha_suffix))
            mod_ops += 1
            continue

        need_cs_reassert = (
            streams_switching_cs
            and sp.stream_key in streams_switching_cs
            and sp.cs_op in ("sc", "scn", "SC", "SCN")
            and sp.active_cs_name.startswith("/")
        )
        if need_cs_reassert or in_alpha_stream:
            orig_slice = scene.raw_streams[sp.stream_key][sp.start : sp.end]
            prefix_cs = f"{sp.active_cs_name} {'CS' if sp.is_stroke else 'cs'} ".encode("latin1") if need_cs_reassert else b""
            slices_by_stream.setdefault(sp.stream_key, []).append((sp.start, sp.end, prefix_cs + orig_slice + alpha_suffix))
            if has_custom_alpha:
                mod_ops += 1
                for gs_end in sp.post_gs_ends:
                    slices_by_stream[sp.stream_key].append((gs_end, gs_end, alpha_suffix))

    # Gate G3b: Adaptive in-cell text polarity (#000000 <-> #FFFFFF) on dark heatmap cells
    g3b_flips = 0
    for ctl in scene.cell_text_labels:
        tile_hex = resolved_group_hex.get(ctl.enclosing_group_id, scene.color_groups[ctl.enclosing_group_id].original_hex)
        best_txt_hex = optimal_cell_text_hex(hex_to_srgb01(tile_hex), threshold_lc=55.0)
        if best_txt_hex.upper() != ctl.original_hex.upper():
            orig_bt = scene.raw_streams["__page__"][ctl.op_index : ctl.color_op_index]
            slices_by_stream.setdefault("__page__", []).append(
                (
                    ctl.op_index,
                    ctl.color_op_index,
                    _format_rgb_op(best_txt_hex, False) + b" " + orig_bt + b" " + _format_rgb_op(ctl.original_hex, False),
                )
            )
            g3b_flips += 1

    def _register_alpha_extgstates(holder_obj: pikepdf.Object, gs_defs: dict[str, tuple[bool, int]]) -> None:
        if not gs_defs:
            return
        if "/Resources" not in holder_obj:
            holder_obj["/Resources"] = pikepdf.Dictionary()
        res_d = holder_obj["/Resources"]
        if "/ExtGState" not in res_d:
            res_d["/ExtGState"] = pikepdf.Dictionary()
        ext_gs = res_d["/ExtGState"]
        for gs_tag, (is_st, pct) in gs_defs.items():
            ext_gs[gs_tag] = pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/ExtGState"),
                    ("/CA" if is_st else "/ca"): round(pct / 100.0, 3),
                }
            )

    with pikepdf.open(io.BytesIO(scene.raw_pdf_bytes)) as pdf_out:
        p0 = pdf_out.pages[scene.page_index]
        for sk, repl_list in slices_by_stream.items():
            if not repl_list:
                continue
            rewritten = _rewrite_stream_arbitrary(scene.raw_streams[sk], repl_list)
            if sk == "__page__":
                p0.Contents = pdf_out.make_stream(rewritten)
                _register_alpha_extgstates(p0.obj, needed_alpha_gs.get(sk, {}))
            elif sk in scene.form_xobj_paths:
                fxo = _resolve_nested_xobject(
                    p0.obj, scene.form_xobj_paths[sk], pdf_out, clone_for_isolation=(scene.page_count > 1)
                )
                if fxo is not None:
                    fxo.write(rewritten)
                    _register_alpha_extgstates(fxo, needed_alpha_gs.get(sk, {}))

        mod_rasters = 0
        for sid, cs in scene.continuous_scales.items():
            if not scale_modified.get(sid, False):
                continue
            lut = scale_luts[sid]
            for xo_key in (cs.colorbar_xobject, cs.raster_heatmap_xobject):
                if xo_key and xo_key in scene.colorbar_lut_t:
                    chain = [seg if seg.startswith("/") else f"/{seg}" for seg in xo_key.lstrip("/").split("/")]
                    xo_target = _resolve_nested_xobject(p0.obj, chain, pdf_out, clone_for_isolation=(scene.page_count > 1))
                    if xo_target is not None:
                        t_grid = scene.colorbar_lut_t[xo_key]
                        idx_grid = np.clip(np.round(t_grid * 255.0), 0, 255).astype(np.int32)
                        remapped_u8 = np.clip(np.round(lut[idx_grid] * 255.0), 0, 255).astype(np.uint8)
                        xo_target.write(remapped_u8.tobytes())
                        xo_target["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
                        xo_target["/BitsPerComponent"] = 8
                        mod_rasters += 1

        out_buf = io.BytesIO()
        pdf_out.save(out_buf, compress_streams=verify)
        out_bytes = out_buf.getvalue()

    if not verify:
        return out_bytes, {
            "modified_vector_ops": mod_ops,
            "modified_colorbar_rasters": mod_rasters,
            "g3b_inverted_cell_labels": g3b_flips,
        }

    g0_pass = True
    evidence_audit: list[dict[str, Any]] = []
    with pikepdf.open(io.BytesIO(out_bytes)) as pdf_check:
        p_c = pdf_check.pages[scene.page_index]
        for ev in scene.evidence_regions:
            if ev.mutability in ("class0_sacrosanct_evidence", "class1_fluorescence_lut"):
                chain = [seg if seg.startswith("/") else f"/{seg}" for seg in ev.xobject_name.lstrip("/").split("/")]
                xo_c = _resolve_nested_xobject(p_c.obj, chain, pdf_check, clone_for_isolation=False)
                if xo_c is None:
                    continue
                try:
                    after_b = xo_c.read_raw_bytes()
                except Exception:
                    after_b = xo_c.read_bytes()
                sha_after = hashlib.sha256(after_b).hexdigest()
                same = sha_after == ev.sha256_original
                if not same:
                    g0_pass = False
                evidence_audit.append({"xobject": ev.xobject_name, "sha256_match": same})

    geom_after = canonical_geometry_hash_pdf_bytes(out_bytes)
    g6_pass = geom_after == scene.geometry_hash_original
    if not g0_pass:
        raise RuntimeError("CRITICAL Gate G0 Violation: Protected raw evidence image bytes changed during export!")
    if not g6_pass:
        raise RuntimeError("CRITICAL Gate G6 Violation: Non-color PDF geometry stream changed during export!")

    return out_bytes, {
        "g0_evidence_bit_identical": g0_pass,
        "g0_locked_objects": evidence_audit,
        "g6_geometry_hash_before": scene.geometry_hash_original,
        "g6_geometry_hash_after": geom_after,
        "g6_geometry_identical": g6_pass,
        "modified_vector_ops": mod_ops,
        "modified_colorbar_rasters": mod_rasters,
        "g3b_inverted_cell_labels": g3b_flips,
    }
