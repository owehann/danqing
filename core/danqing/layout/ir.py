"""Scientific Figure Scene Graph (SFSG) Intermediate Representation & 2D Bento Topology."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ElasticityClass = Literal["L0_LOCKED_SPECIAL", "L1_ISOTROPIC_VECTOR", "L2_ELASTIC_CARTESIAN", "T2_COUPLED_LOCKED"]
TextRole = Literal[
    "PANEL_TAG",
    "PANEL_TITLE",
    "X_TICK",
    "Y_TICK",
    "X_TITLE",
    "Y_TITLE",
    "LEGEND",
    "ANNOTATION",
    "INTERNAL_LOCKED",
]
LegendPosMode = Literal[
    "auto",
    "right",
    "top",
    "bottom",
    "inside_tr",
    "inside_tl",
    "inside_br",
    "inside_bl",
    "custom",
    "hidden",
]
LegendOrientMode = Literal["auto", "vertical", "horizontal"]
ROIShapeMode = Literal["rect", "rounded", "circle", "ellipse"]
ROILineStyle = Literal["dashed", "solid", "dotted"]
ROIInsetPos = Literal["tr", "tl", "br", "bl", "custom"]


@dataclass
class ROIOverlaySpec:
    """Non-destructive vector ROI callout, multi-shape crop, PiP inset & physical scale-bar spec for any panel."""

    enabled: bool = False
    x_norm: float = 0.32
    y_norm: float = 0.28
    w_norm: float = 0.30
    h_norm: float = 0.30
    label: str = "ROI"
    color: str = "#F59E0B"
    dashed: bool = True
    shape: ROIShapeMode = "rect"
    line_style: ROILineStyle | None = None
    stroke_pt: float = 0.85
    show_leaders: bool = False
    inset_enabled: bool = False
    inset_pos: ROIInsetPos = "br"
    inset_x_norm: float = 0.58
    inset_y_norm: float = 0.54
    inset_scale: float = 0.36
    own_crop: bool = False
    scale_bar_um: float | None = None
    fov_width_um: float | None = None
    linked_source_id: str | None = None

    def resolved_line_style(self) -> ROILineStyle:
        if self.line_style in ("dashed", "solid", "dotted"):
            return self.line_style
        return "dashed" if self.dashed else "solid"


@dataclass
class TextItemOverride:
    """Fine-grained style & label override for a single text element (1 legend entry, 1 X/Y tick, 1 gene callout, etc.)."""

    color: str | None = None          # "#B91C1C", "SWATCH", or None (inherit)
    font_family: str | None = None    # "Times New Roman", "Arial", etc., or None (inherit)
    bold: bool | None = None          # True = force bold, False = force normal, None = inherit
    italic: bool = False              # True = italic (gene symbols, p-values, emphasis)
    font_scale: float = 1.0           # 0.70 .. 1.50 individual size multiplier
    text: str | None = None           # Optional custom display text


@dataclass
class PanelStyleOverride:
    """Per-panel independent fine-tuning (typography, draggable legend, margin trim, categorical compactness, custom tag)."""

    custom_tag: str | None = None  # None = auto numbering; "" = hide tag; "b" = explicit author tag
    font_scale: float = 1.0        # 0.70 .. 1.40
    legend_scale: float = 1.0      # 0.65 .. 1.40
    marker_scale: float = 1.0      # 0.50 .. 1.80
    stroke_scale: float = 1.0      # 0.60 .. 1.60
    show_title: bool | None = None
    panel_font_family: str | None = None
    legend_font_family: str | None = None
    legend_bold: bool = False
    legend_text_color: str = "#000000"
    legend_match_swatch: bool = False
    legend_orient: LegendOrientMode = "auto"
    legend_pos: LegendPosMode = "auto"
    legend_xy_norm: tuple[float, float] = (0.62, 0.06)  # Normalized [0..1] inside SpineBox when dragged!
    legend_cols: int = 1
    legend_bg: bool = True
    pad_top_mm: float = 0.0
    pad_bottom_mm: float = 0.0
    pad_left_mm: float = 0.0
    pad_right_mm: float = 0.0
    frame_width_ratio: float = 1.0  # 0.50 .. 1.00
    category_spacing: float = 1.0   # 0.35 .. 1.25 (Piecewise-Linear Categorical Gap Compression!)
    text_overrides: dict[str, TextItemOverride] = field(default_factory=dict)


@dataclass
class BentoBlock:
    """One column unit inside a BentoRow; holds 1 panel or 2-3 vertically stacked panels."""

    panel_ids: list[str]
    weight: float = 4.0  # Relative horizontal share across the row (normalized to 12.0)


@dataclass
class BentoRow:
    """One horizontal row band in the 2D Bento Grid."""

    blocks: list[BentoBlock]
    height_scale: float = 1.0  # Continuous user row-height multiplier [0.55 .. 1.85]


@dataclass
class PathSegment:
    op: Literal["M", "L", "C", "Z"]
    pts: tuple[float, ...] = ()


@dataclass
class DataShape:
    role: Literal["SPINE_BORDER", "GRID", "DATA_FILL", "DATA_STROKE", "ERROR_STEM", "ERROR_CAP", "BRACKET", "LEADER"]
    segments: list[PathSegment]
    fill: str = "none"
    fill_opacity: float = 1.0
    stroke: str = "none"
    stroke_opacity: float = 1.0
    raw_stroke_width: float = 1.0
    dasharray: str | None = None
    clip_to_spine: bool = True
    cap_center: tuple[float, float] | None = None
    cap_half_pt: float = 2.0


@dataclass
class DataMarker:
    cx: float
    cy: float
    raw_r: float
    rel_size: float = 1.0
    is_proportional_bubble: bool = False
    fill: str = "#4E79A7"
    fill_opacity: float = 0.88
    stroke: str = "none"
    stroke_width_pt: float = 0.35
    clip_to_spine: bool = True


@dataclass
class TickMark:
    axis: Literal["x", "y"]
    pos_raw: float


@dataclass
class TextItem:
    text: str
    role: TextRole
    x_raw: float
    y_raw: float
    raw_font_px: float
    raw_font_family: str = "Helvetica"
    bold: bool = False
    fill: str = "#000000"
    anchor: Literal["start", "middle", "end"] = "middle"
    angle_deg: float = 0.0
    target_raw: tuple[float, float] | None = None


@dataclass
class LegendEntry:
    label: str
    color: str
    kind: Literal["rect", "circle", "line"] = "rect"


@dataclass
class ColorbarSpec:
    title: str
    stops: list[tuple[float, str]]
    ticks: list[tuple[float, str]]


@dataclass
class RasterEvidence:
    png_bytes: bytes
    width_px: int
    height_px: int
    x_raw: float
    y_raw: float
    w_raw: float
    h_raw: float
    sha256: str


@dataclass
class PanelIR:
    panel_id: str
    title_hint: str
    category_badge: str
    source_citation: str
    raw_width_pt: float
    raw_height_pt: float
    viewbox: tuple[float, float, float, float]
    spine_box: tuple[float, float, float, float]
    elasticity: ElasticityClass
    locked_special: bool
    raw_svg_bytes: bytes
    shapes: list[DataShape] = field(default_factory=list)
    markers: list[DataMarker] = field(default_factory=list)
    ticks: list[TickMark] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    legend_entries: list[LegendEntry] = field(default_factory=list)
    colorbar: ColorbarSpec | None = None
    rasters: list[RasterEvidence] = field(default_factory=list)
    default_roi: ROIOverlaySpec = field(default_factory=ROIOverlaySpec)
    n_y_categories: int = 0
    n_x_categories: int = 0
    is_categorical_x: bool = False
    ideal_aspect: float = 1.25
    min_aspect: float = 0.75
    max_aspect: float = 1.85


# ---------------- Compiled Physical Page Scene (exact mm coordinates) ----------------


@dataclass
class CompiledText:
    text: str
    x_mm: float
    y_mm: float
    font_pt: float
    font_family: str
    bold: bool = False
    italic: bool = False
    fill: str = "#000000"
    anchor: Literal["start", "middle", "end"] = "start"
    angle_deg: float = 0.0
    role: str = "TEXT"
    panel_id: str = ""
    item_key: str = ""
    orig_text: str = ""
    swatch_color: str | None = None
    bbox_mm: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class CompiledPath:
    segments_mm: list[PathSegment]
    fill: str = "none"
    fill_opacity: float = 1.0
    stroke: str = "none"
    stroke_opacity: float = 1.0
    stroke_pt: float = 0.50
    dasharray_mm: str | None = None
    clip_id: str | None = None
    panel_id: str = ""
    role: str = "DATA"
    norm_check: tuple[float, float] | None = None


@dataclass
class CompiledCircle:
    cx_mm: float
    cy_mm: float
    r_mm: float
    fill: str
    fill_opacity: float = 0.88
    stroke: str = "none"
    stroke_pt: float = 0.30
    clip_id: str | None = None
    panel_id: str = ""
    role: str = "MARKER"
    norm_xy: tuple[float, float] | None = None


@dataclass
class CompiledRaster:
    png_bytes: bytes
    sha256: str
    width_px: int
    height_px: int
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    panel_id: str
    effective_dpi: float
    aspect_ratio_error: float
    clip_id: str | None = None
    is_overlay: bool = False


@dataclass
class CompiledRawLockedSVG:
    svg_inner_xml: str
    raw_vb: tuple[float, float, float, float]
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    scale_isotropic: float
    panel_id: str
    clip_id: str | None = None
    is_overlay: bool = False


@dataclass
class CompiledROIBoxMeta:
    owner_id: str
    box_mm: tuple[float, float, float, float]
    x_norm: float
    y_norm: float
    w_norm: float
    h_norm: float
    shape: ROIShapeMode
    line_style: ROILineStyle
    color: str
    stroke_pt: float
    label: str
    show_leaders: bool = False


@dataclass
class CompiledPanelSlot:
    panel_id: str
    tag_label: str
    row_idx: int
    block_idx: int = 0
    stack_idx: int = 0
    col_start: int = 0
    col_span: int = 4
    weight: float = 4.0
    row_span: int = 1
    outer_box_mm: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    spine_box_mm: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    legend_box_mm: tuple[float, float, float, float] | None = None
    inset_box_mm: tuple[float, float, float, float] | None = None
    roi_boxes: list[CompiledROIBoxMeta] = field(default_factory=list)
    effective_legend_pos: str = "hidden"
    effective_legend_orient: str = "vertical"
    has_legend: bool = False
    is_colorbar: bool = False
    is_categorical_x: bool = False
    elasticity: ElasticityClass = "L2_ELASTIC_CARTESIAN"
    locked_special: bool = False
    scale_x: float = 1.0
    scale_y: float = 1.0


@dataclass
class CompositePageScene:
    width_mm: float
    height_mm: float
    journal_id: str
    font_family: str
    slots: list[CompiledPanelSlot] = field(default_factory=list)
    bento_rows: list[BentoRow] = field(default_factory=list)
    row_bounds_mm: list[tuple[float, float]] = field(default_factory=list)
    clips_mm: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    clip_paths_mm: dict[str, list[PathSegment]] = field(default_factory=dict)
    rasters: list[CompiledRaster] = field(default_factory=list)
    locked_svgs: list[CompiledRawLockedSVG] = field(default_factory=list)
    paths: list[CompiledPath] = field(default_factory=list)
    circles: list[CompiledCircle] = field(default_factory=list)
    texts: list[CompiledText] = field(default_factory=list)
    gradients: list[tuple[str, list[tuple[float, str]]]] = field(default_factory=list)
    shared_legend_hoisted: bool = False
    overflow_warning: str | None = None
