"""Core intermediate representation (IR) models for Danqing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

MutabilityClass = Literal[
    "class0_sacrosanct_evidence",  # WB/gel strips, H&E/IHC/brightfield/EM/gross crops (100% SHA-256 byte locked)
    "class1_fluorescence_lut",     # Multiplex IF/FISH (locked by default; optional pure linear channel matrix)
    "class2_convention_locked",    # CNV gain/loss, ACGT logos, organ schematics (hue-quadrant locked)
    "class3_symbolic_mutable",     # Abstract categorical & 5-type continuous/diverging gradient encodings
    "structural_immutable",        # Pure-black axes, text, ticks, white backgrounds, scalebar boxes
]

EncodingKind = Literal[
    "categorical",
    "continuous_sequential",
    "continuous_diverging",
    "fluorescence_channel",
    "structural",
]

EmphasisTier = Literal["protagonist", "supporting", "context", "focus", "normal", "background", "control"]


@dataclass
class PanelBox:
    panel_id: str
    title: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1) in top-left page pt coords


@dataclass
class EvidenceRegion:
    """Gate G0 record for any embedded raster object on the page."""

    region_id: str
    xobject_name: str
    panel_id: str
    bbox: tuple[float, float, float, float]
    width_px: int
    height_px: int
    mutability: MutabilityClass
    subtype_label: str  # e.g. "colorbar_strip", "heatmap_raster_1d", "western_blot", "histology_he_ihc", "fluorescence_if"
    sha256_original: str
    dominant_stain_hex: list[str] = field(default_factory=list)
    can_linear_cvd_lut: bool = False
    reason: str = ""


@dataclass
class ColorGroup:
    """Aggregated vector/gradient color group inside a single panel (scales to >10^6 primitives in O(1) JSON)."""

    group_id: str
    panel_id: str
    role: Literal["fill", "stroke", "gradient_stop"]
    original_hex: str
    current_hex: str
    alpha: float
    primitive_count: int
    total_area_pt2: float
    min_mark_pt: float
    sample_bbox: tuple[float, float, float, float]
    # Matched legend/label text if discovered locally inside this panel
    local_label: str = ""
    mark_kind: Literal["area", "point", "line"] = "area"
    current_alpha: float | None = None
    is_continuous_member: bool = False
    continuous_scale_id: str | None = None
    continuous_t: float = 0.0
    # Internal op indices in content stream (kept in server session, omitted in lightweight public JSON)
    op_indices: list[int] = field(default_factory=list, repr=False)

    def to_public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("op_indices", None)
        return d


@dataclass
class CellTextLabel:
    """Gate G3b record for numeric text labels sitting directly inside continuous heatmap cells."""

    op_index: int
    color_op_index: int
    panel_id: str
    text: str
    bbox: tuple[float, float, float, float]
    enclosing_group_id: str
    original_hex: str
    current_hex: str


@dataclass
class ContinuousScale:
    """Unified continuous/diverging gradient entity coupling colorbar strip(s), vector tiles/points, or 1D-manifold rasters."""

    scale_id: str
    panel_id: str
    title: str
    kind: Literal["continuous_sequential", "continuous_diverging"]
    midpoint_t: float
    colorbar_xobject: str | None
    colorbar_bbox: tuple[float, float, float, float] | None
    raster_heatmap_xobject: str | None
    member_group_ids: list[str]
    original_stops_hex: list[str]
    current_stops_hex: list[str]
    inverted_polarity: bool = False
    locked: bool = False


@dataclass
class SemanticEntity:
    """Semantic factor bound across one or more panels (or scoped per panel)."""

    entity_id: str
    label: str
    category_group: str  # e.g., "Treatment", "2 µm Subcellular Shell", "Track", "Tissue Island", "QC Flag"
    panels: list[str]
    member_group_ids: list[str]
    original_hex: str
    current_hex: str
    original_alpha: float = 1.0
    alpha: float | None = None
    encoding: EncodingKind = "categorical"
    tier: EmphasisTier = "supporting"
    tier_reason: str = "标准数据组"
    locked: bool = False
    pinned_manuscript: bool = False
    is_control_candidate: bool = False
    unlinked: bool = False


@dataclass
class CollisionNotice:
    """Intra-panel (fatal, auto-repaired) or Cross-panel (governed by panel_scoped vs global_strict) color collision."""

    collision_id: str
    scope: Literal["intra_panel", "cross_panel", "continuous_vs_categorical"]
    original_hex_a: str
    original_hex_b: str
    delta_e00: float
    entities_involved: list[dict[str, str]]  # [{"entity_id": ..., "label": ..., "panel_id": ...}]
    description: str
