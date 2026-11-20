"""FastAPI router for Danqing Layout Studio v2 (`/api/v2/layout/*`)."""

from __future__ import annotations

from collections import OrderedDict
import json
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
import uuid

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from danqing.layout.compiler import TypographyConfig, compile_modular_scene, render_naive_uniform_svg
from danqing.layout.exporter import build_mode_b_slot_contract, render_scene_pdf, render_scene_svg, render_svg_to_png
from danqing.layout.gates import run_layout_gates
from danqing.layout.ir import (
    BentoBlock,
    BentoRow,
    LegendOrientMode,
    LegendPosMode,
    PanelIR,
    PanelStyleOverride,
    ROIOverlaySpec,
    TextItemOverride,
)
from danqing.layout.parser import parse_svg_panel, parse_uploaded_file
from danqing.layout.solver import LAYOUT_MODES
from danqing.layout.specs import FONT_FAMILIES, JOURNAL_FAMILIES, JOURNAL_SPECS

layout_router = APIRouter(prefix="/api/v2/layout", tags=["layout"])

REPO_ROOT = Path(__file__).resolve().parents[2]
PANELS_DIR = REPO_ROOT / "bench" / "layout_panels"

_CATALOG_META: list[dict[str, Any]] = []
_PANEL_STORE: OrderedDict[str, PanelIR] = OrderedDict()
_SAMPLE_PACKS_CACHE: list[dict[str, Any]] | None = None
MAX_UPLOADED_PANELS = 24 if os.getenv("DANQING_LOW_MEMORY") == "1" else 96

SAMPLE_PACK_SPECS: list[dict[str, Any]] = [
    {
        "pack_id": "pack_10_spatial_clinical",
        "panel_ids": ["P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10"],
        "journal_id": "nature_double",
        "layout_mode": "auto_bento",
        "title_zh": "10 图空间病理与多队列临床图谱",
        "title_en": "10-Panel Spatial & Clinical Atlas",
        "sub_zh": "含 H&E 全景及联动 ROI、免疫荧光、胶图与 6 张异构尺寸统计图",
        "sub_en": "Locked H&E + linked ROI, mIF, immunoblot, and 6 multi-scale charts",
        "cite_zh": "公开数据：10x Genomics Visium · UCI WDBC / HCV / Cleveland",
        "cite_en": "Public data: 10x Genomics Visium · UCI WDBC / HCV / Cleveland",
    },
    {
        "pack_id": "pack_9_spine_matrix",
        "panel_ids": ["P01", "P02", "P05", "P06", "P07", "P08", "P09", "P10", "P11"],
        "journal_id": "cell_double",
        "layout_mode": "uniform_3col",
        "title_zh": "9 图三栏严谨内轴对齐矩阵",
        "title_en": "9-Panel Three-Column Spine Grid",
        "sub_zh": "检验超宽指标名气泡图与迷你粗框柱状图的内坐标轴对齐与字号归一",
        "sub_en": "Aligns wide-margin dot matrices and compact bar plots onto shared spines",
        "cite_zh": "公开数据：Palmer Penguins · UCI 肝脏与冠脉临床队列",
        "cite_en": "Public data: Palmer Penguins · UCI Liver & Cardiology Cohorts",
    },
    {
        "pack_id": "pack_12_hero_fullpage",
        "panel_ids": ["P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12"],
        "journal_id": "nature_double",
        "layout_mode": "hero_bento",
        "title_zh": "12 图整页主视觉跨行综合版",
        "title_en": "12-Panel Full-Page Hero Composition",
        "sub_zh": "左上跨双行主视觉切片 + 全套组学火山图、异速回归与锁比例信号通路图",
        "sub_en": "Two-row hero histology anchor paired with omics charts and locked pathway",
        "cite_zh": "公开数据：10x Genomics · Palmer LTER · KEGG hsa04012",
        "cite_en": "Public data: 10x Genomics · Palmer LTER · KEGG hsa04012",
    },
]


def _ensure_catalog() -> None:
    if _CATALOG_META:
        return
    manifest_path = PANELS_DIR / "MANIFEST.json"
    if not manifest_path.exists():
        return
    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    for it in items:
        pid = str(it["panel_id"])
        svg_path = PANELS_DIR / str(it["filename"])
        raw_bytes = svg_path.read_bytes()
        roi_dict = it.get("default_roi")
        roi_spec = ROIOverlaySpec(**roi_dict) if isinstance(roi_dict, dict) else ROIOverlaySpec(enabled=False)
        ir = parse_svg_panel(
            raw_bytes,
            panel_id=pid,
            title_hint=str(it["title"]),
            category_badge=str(it["category"]),
            source_citation=str(it["source"]),
            force_locked_special=bool(it["locked_special"]),
            default_roi=roi_spec,
        )
        _PANEL_STORE[pid] = ir
        _CATALOG_META.append(
            {
                "panel_id": pid,
                "filename": it["filename"],
                "elasticity": ir.elasticity,
                "locked_special": bool(ir.locked_special),
                "has_legend": (bool(ir.legend_entries) or ir.colorbar is not None) and not ir.locked_special,
                "is_colorbar": (ir.colorbar is not None) and not ir.locked_special,
                "is_categorical_x": ir.is_categorical_x,
                "default_selected": bool(it["default_selected"]),
                "raw_size_desc": it["raw_size_desc"],
                "source": it["source"],
                "is_builtin": True,
                "thumb_svg": raw_bytes.decode("utf-8", errors="replace"),
                "default_roi": roi_spec.__dict__,
            }
        )


def _get_sample_packs() -> list[dict[str, Any]]:
    global _SAMPLE_PACKS_CACHE
    if _SAMPLE_PACKS_CACHE is not None:
        return _SAMPLE_PACKS_CACHE
    _ensure_catalog()
    out: list[dict[str, Any]] = []
    for sp in SAMPLE_PACK_SPECS:
        sub_panels = [_PANEL_STORE[pid] for pid in sp["panel_ids"] if pid in _PANEL_STORE]
        cfg = TypographyConfig(journal_id=sp["journal_id"], layout_mode=sp["layout_mode"])
        scene = compile_modular_scene(sub_panels, cfg)
        svg_thumb = render_scene_svg(scene, show_guides=False)
        out.append(
            {
                **sp,
                "panel_count": len(sub_panels),
                "preview_svg": svg_thumb,
            }
        )
    _SAMPLE_PACKS_CACHE = out
    return out


class ROIPayload(BaseModel):
    enabled: bool = False
    x_norm: float = 0.30
    y_norm: float = 0.28
    w_norm: float = 0.30
    h_norm: float = 0.30
    label: str = "ROI"
    color: str = "#F59E0B"
    dashed: bool = True
    scale_bar_um: float | None = None
    fov_width_um: float | None = None
    linked_source_id: str | None = None


class TextItemOverridePayload(BaseModel):
    color: str | None = None
    font_family: str | None = None
    bold: bool | None = None
    italic: bool = False
    font_scale: float = 1.0
    text: str | None = None


class PanelOverridePayload(BaseModel):
    custom_tag: str | None = None
    font_scale: float = 1.0
    legend_scale: float = 1.0
    marker_scale: float = 1.0
    stroke_scale: float = 1.0
    show_title: bool | None = None
    panel_font_family: str | None = None
    legend_font_family: str | None = None
    legend_bold: bool = False
    legend_text_color: str = "#000000"
    legend_match_swatch: bool = False
    legend_orient: LegendOrientMode = "auto"
    legend_pos: LegendPosMode = "auto"
    legend_xy_norm: tuple[float, float] = (0.62, 0.06)
    legend_cols: int = 1
    legend_bg: bool = True
    pad_top_mm: float = 0.0
    pad_bottom_mm: float = 0.0
    pad_left_mm: float = 0.0
    pad_right_mm: float = 0.0
    frame_width_ratio: float = 1.0
    category_spacing: float = 1.0
    text_overrides: dict[str, TextItemOverridePayload] = Field(default_factory=dict)


class BentoBlockPayload(BaseModel):
    panel_ids: list[str]
    weight: float = 4.0


class BentoRowPayload(BaseModel):
    blocks: list[BentoBlockPayload]
    height_scale: float = 1.0


class ComposeRequest(BaseModel):
    panel_ids: list[str] = Field(default_factory=list)
    journal_id: str = "nature_double"
    custom_width_mm: float | None = None
    custom_max_height_mm: float | None = None
    tag_case_override: Literal["lower", "upper"] | None = None
    tag_flow: Literal["row_major", "col_major"] = "row_major"
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
    show_guides: bool = False
    include_naive: bool = False
    span_overrides: dict[str, int] = Field(default_factory=dict)
    locked_overrides: dict[str, bool] = Field(default_factory=dict)
    roi_overrides: dict[str, ROIPayload] = Field(default_factory=dict)
    panel_overrides: dict[str, PanelOverridePayload] = Field(default_factory=dict)
    bento_rows: list[BentoRowPayload] | None = None


class ExportRequest(ComposeRequest):
    format: str = "pdf"
    dpi: int = 300


def _resolve_request(
    req: ComposeRequest,
) -> tuple[list[PanelIR], TypographyConfig, dict[str, ROIOverlaySpec], dict[str, PanelStyleOverride], list[BentoRow] | None]:
    _ensure_catalog()
    selected = [_PANEL_STORE[pid] for pid in req.panel_ids if pid in _PANEL_STORE]
    if not selected:
        raise HTTPException(status_code=400, detail="No valid panels selected.")
    cfg = TypographyConfig(
        journal_id=req.journal_id,
        custom_width_mm=req.custom_width_mm,
        custom_max_height_mm=req.custom_max_height_mm,
        tag_case_override=req.tag_case_override,
        tag_flow=req.tag_flow,
        layout_mode=req.layout_mode,
        font_family=req.font_family,
        tag_pt=req.tag_pt,
        title_pt=req.title_pt,
        axis_title_pt=req.axis_title_pt,
        tick_pt=req.tick_pt,
        annotation_pt=req.annotation_pt,
        axis_stroke_pt=req.axis_stroke_pt,
        data_stroke_pt=req.data_stroke_pt,
        grid_stroke_pt=req.grid_stroke_pt,
        gutter_mm=req.gutter_mm,
        marker_pt=req.marker_pt,
        show_panel_titles=req.show_panel_titles,
        hoist_shared_legends=req.hoist_shared_legends,
    )
    rois = {pid: ROIOverlaySpec(**r.model_dump()) for pid, r in req.roi_overrides.items()}
    povs: dict[str, PanelStyleOverride] = {}
    for pid, ov in req.panel_overrides.items():
        d = ov.model_dump()
        raw_tovs = d.pop("text_overrides", {}) or {}
        povs[pid] = PanelStyleOverride(
            **d,
            text_overrides={k: TextItemOverride(**v) for k, v in raw_tovs.items()},
        )
    rows = (
        [
            BentoRow(
                blocks=[BentoBlock(panel_ids=list(b.panel_ids), weight=b.weight) for b in r.blocks],
                height_scale=r.height_scale,
            )
            for r in req.bento_rows
        ]
        if req.bento_rows is not None
        else None
    )
    return selected, cfg, rois, povs, rows


@layout_router.get("/init")
def api_layout_init() -> dict[str, Any]:
    _ensure_catalog()
    return {
        "panels": _CATALOG_META,
        "packs": _get_sample_packs(),
        "journals": [j.__dict__ for j in JOURNAL_SPECS.values()],
        "journal_families": JOURNAL_FAMILIES,
        "layout_modes": LAYOUT_MODES,
        "font_families": list(FONT_FAMILIES.keys()),
    }


@layout_router.post("/upload")
async def api_layout_upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    _ensure_catalog()
    added: list[dict[str, Any]] = []
    for uf in files:
        raw = await uf.read()
        if not raw:
            continue
        uid = "U" + uuid.uuid4().hex[:6].upper()
        fname = uf.filename or f"{uid}.svg"
        ir = parse_uploaded_file(fname, raw, panel_id=uid)
        _PANEL_STORE[uid] = ir
        custom_keys = [k for k in _PANEL_STORE if k.startswith("U")]
        while len(custom_keys) > MAX_UPLOADED_PANELS:
            old_k = custom_keys.pop(0)
            _PANEL_STORE.pop(old_k, None)

        added.append(
            {
                "panel_id": uid,
                "filename": fname,
                "elasticity": ir.elasticity,
                "locked_special": ir.locked_special,
                "has_legend": (bool(ir.legend_entries) or ir.colorbar is not None) and not ir.locked_special,
                "is_colorbar": (ir.colorbar is not None) and not ir.locked_special,
                "is_categorical_x": ir.is_categorical_x,
                "default_selected": True,
                "raw_size_desc": f"{ir.raw_width_pt:.0f}×{ir.raw_height_pt:.0f} pt",
                "source": ir.source_citation,
                "is_builtin": False,
                "thumb_svg": ir.raw_svg_bytes.decode("utf-8", errors="replace"),
                "default_roi": ir.default_roi.__dict__,
            }
        )
    return {"uploaded": added}


@layout_router.post("/compose")
def api_layout_compose(req: ComposeRequest) -> dict[str, Any]:
    selected, cfg, rois, povs, rows = _resolve_request(req)
    scene = compile_modular_scene(
        selected,
        cfg,
        span_overrides=req.span_overrides,
        locked_overrides=req.locked_overrides,
        roi_overrides=rois,
        panel_overrides=povs,
        bento_rows=rows,
    )
    modular_svg = render_scene_svg(scene, show_guides=req.show_guides)
    if req.include_naive:
        naive_svg, naive_stats = render_naive_uniform_svg(selected, cfg)
    else:
        naive_svg = ""
        naive_stats = {
            "min_font_pt": 4.2,
            "max_font_pt": 11.4,
            "min_stroke_pt": 0.28,
            "max_stroke_pt": 1.65,
        }
    eff_max_h = req.custom_max_height_mm or JOURNAL_SPECS.get(req.journal_id, JOURNAL_SPECS["nature_double"]).max_height_mm
    audit = run_layout_gates(scene, selected, max_height_mm=eff_max_h)
    contract = build_mode_b_slot_contract(scene)

    txts_by_panel: dict[str, list[dict[str, Any]]] = {}
    for ct in scene.texts:
        if not ct.panel_id or not ct.item_key or ct.role == "SCALEBAR_TEXT":
            continue
        txts_by_panel.setdefault(ct.panel_id, []).append(
            {
                "item_key": ct.item_key,
                "role": ct.role,
                "text": ct.text,
                "orig_text": ct.orig_text or ct.text,
                "bbox_mm": [round(v, 3) for v in ct.bbox_mm],
                "font_pt": round(ct.font_pt, 2),
                "font_family": ct.font_family,
                "bold": ct.bold,
                "italic": ct.italic,
                "fill": ct.fill,
                "angle_deg": round(ct.angle_deg, 1),
                "swatch_color": ct.swatch_color,
            }
        )

    slots_meta = [
        {
            "panel_id": sl.panel_id,
            "tag_label": sl.tag_label,
            "row_idx": sl.row_idx,
            "block_idx": sl.block_idx,
            "stack_idx": sl.stack_idx,
            "col_start": sl.col_start,
            "col_span": sl.col_span,
            "weight": round(sl.weight, 3),
            "row_span": sl.row_span,
            "outer_box_mm": [round(v, 3) for v in sl.outer_box_mm],
            "spine_box_mm": [round(v, 3) for v in sl.spine_box_mm],
            "legend_box_mm": [round(v, 3) for v in sl.legend_box_mm] if sl.legend_box_mm else None,
            "effective_legend_pos": sl.effective_legend_pos,
            "effective_legend_orient": sl.effective_legend_orient,
            "has_legend": sl.has_legend,
            "is_colorbar": sl.is_colorbar,
            "is_categorical_x": sl.is_categorical_x,
            "locked_special": sl.locked_special,
            "elasticity": sl.elasticity,
            "text_items": txts_by_panel.get(sl.panel_id, []),
        }
        for sl in scene.slots
    ]

    bento_out = [
        {
            "blocks": [{"panel_ids": b.panel_ids, "weight": round(b.weight, 3)} for b in r.blocks],
            "height_scale": round(r.height_scale, 3),
        }
        for r in scene.bento_rows
    ]

    return {
        "modular_svg": modular_svg,
        "naive_svg": naive_svg,
        "naive_stats": naive_stats,
        "page_width_mm": round(scene.width_mm, 2),
        "page_height_mm": round(scene.height_mm, 2),
        "shared_legend_hoisted": scene.shared_legend_hoisted,
        "overflow_warning": scene.overflow_warning,
        "slots": slots_meta,
        "bento_rows": bento_out,
        "row_bounds_mm": [[round(y0, 3), round(y1, 3)] for y0, y1 in scene.row_bounds_mm],
        "audit": audit,
        "mode_b_contract": contract,
    }


@layout_router.post("/export")
def api_layout_export(req: ExportRequest) -> Response:
    selected, cfg, rois, povs, rows = _resolve_request(req)
    scene = compile_modular_scene(
        selected,
        cfg,
        span_overrides=req.span_overrides,
        locked_overrides=req.locked_overrides,
        roi_overrides=rois,
        panel_overrides=povs,
        bento_rows=rows,
    )
    fmt = req.format.lower()
    stem = f"danqing_layout_{req.journal_id}_{len(selected)}panels"
    if fmt == "svg":
        svg_str = render_scene_svg(scene, show_guides=False)
        return Response(
            content=svg_str.encode("utf-8"),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f'attachment; filename="{stem}.svg"'},
        )
    if fmt == "png":
        svg_str = render_scene_svg(scene, show_guides=False)
        png_bytes = render_svg_to_png(svg_str, dpi=max(150, min(600, req.dpi)), width_mm=scene.width_mm)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="{stem}_{req.dpi}dpi.png"'},
        )
    if fmt == "lockfile":
        contract = build_mode_b_slot_contract(scene)
        return Response(
            content=json.dumps(contract, indent=2, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{quote("figure_layout.lock.json")}"'},
        )

    pdf_bytes = render_scene_pdf(scene)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'},
    )
