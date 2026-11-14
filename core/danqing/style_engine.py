"""Palette-independent Aesthetic Style Sculpting Engine for Danqing (`danqing.style_engine`).

Operates *after* palette assignment (or directly on a figure's initial colors) to sculpt both
discrete entities and continuous colorbars/heatmaps into a unified, harmonious, low-fatigue
aesthetic envelope in OKLCH — while strictly preserving:
1. Input Palette individuality (two distinct palettes sculpted by the same style remain distinct).
2. Pure-white `#FFFFFF` / original paper canvas & pure-black `#000000` structural typography.
3. Zero "muddy gray mixing" (pure OKLCH interval reshaping & circular elastic hue attraction).
4. Control/background layers (`tier == "control"` / `"background"`, `Out of Tissue`, `PASS`) and
   Gate G0 raw experimental images (`evidence_regions`: Western blots, H&E, microscopy).
5. Synchronous continuous scale updates across BOTH colorbar `scale_stops` AND every vector
   primitive group in `ContinuousScale.member_group_ids`, preserving strict `L(t)` monotonicity
   (and midpoint symmetry on `continuous_diverging`).
6. Panel-scoped CIEDE2000 & Machado Deuteranopia anti-collision guardrails.

License: Apache-2.0 (Xinyin Han).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .color_science import (
    ciede2000_matrix,
    hex_to_oklch,
    hex_to_srgb01,
    interpolate_oklch_lut,
    oklab_to_oklch,
    oklch_to_hex,
    simulate_cvd,
    srgb01_to_hex,
    srgb_to_oklab,
)
from .ir import ColorGroup, ContinuousScale, SemanticEntity
from .palettes import get_palette
from .pdf_engine import ParsedPdfScene, export_recolored_pdf
from .solver import CollisionScope, SolveResult, VibrancyMode, evaluate_gates, normalize_role, solve_scene_colors
from .svg_engine import SvgScene, export_recolored_svg

_RECESSIVE_CONTROL_LABELS: frozenset[str] = frozenset(
    {
        "out of tissue",
        "out_of_tissue",
        "outside tissue",
        "empty glass",
        "non-tissue",
        "nontissue",
        "pass",
        "background",
        "unassigned",
    }
)


def _wrap180(deg: float) -> float:
    """Signed shortest angular difference in [-180.0, 180.0)."""
    return ((float(deg) + 180.0) % 360.0) - 180.0


def _angle_in_sector(h: float, sector: tuple[float, float]) -> bool:
    """Check whether angle `h` (mod 360) lies inside directed sector `[start, end]`."""
    s = sector[0] % 360.0
    e = sector[1] % 360.0
    span = (e - s) % 360.0
    rel = (h % 360.0 - s) % 360.0
    return rel <= span + 1e-6


def _project_into_sector(h: float, sector: tuple[float, float]) -> float:
    """Continuously fold circular hue `[0, 360)` into `[start, end]` without boundary pile-up.

    - Inside `[start, end]`: exact identity (`h -> h`).
    - Outside `[start, end]`: smooth folded-arc reflection across `[start, end]` so distinct
      out-of-sector hues remain separated rather than collapsing onto the endpoints.
    """
    s = sector[0] % 360.0
    e = sector[1] % 360.0
    span = (e - s) % 360.0
    if span <= 1e-3 or span >= 359.9:
        return h % 360.0
    rel = (h % 360.0 - s) % 360.0
    if rel <= span:
        return (s + rel) % 360.0
    outside_span = 360.0 - span
    d_past_end = rel - span  # in (0, outside_span)
    u_reflected = 1.0 - (d_past_end / outside_span)  # smoothly maps (0, outside_span) -> (1, 0)
    margin = min(2.0, 0.04 * span)
    u_clamped = margin / span + u_reflected * (1.0 - 2.0 * margin / span)
    return (s + u_clamped * span) % 360.0


def _clamp_to_sector(h: float, sector: tuple[float, float] | None, pad_deg: float = 0.5) -> float:
    if sector is None:
        return h % 360.0
    s = sector[0] % 360.0
    e = sector[1] % 360.0
    span = (e - s) % 360.0
    if span <= 2.0 * pad_deg:
        return (s + 0.5 * span) % 360.0
    rel = (h % 360.0 - s) % 360.0
    if rel <= span:
        rel_c = min(max(rel, pad_deg), span - pad_deg)
        return (s + rel_c) % 360.0
    # Pick nearer endpoint
    d_end = rel - span
    d_start = 360.0 - rel
    return ((e - pad_deg) if d_end <= d_start else (s + pad_deg)) % 360.0


@dataclass(frozen=True)
class StyleProfile:
    """Perceptual OKLCH style envelope independent of any concrete discrete palette."""

    id: str
    name_en: str
    name_zh: str
    description_en: str
    description_zh: str
    l_band: tuple[float, float]
    c_band: tuple[float, float]
    hue_anchors: tuple[float, ...]
    anchor_weights: tuple[float, ...] = ()
    hue_sector: tuple[float, float] | None = None
    accent_hue_sector: tuple[float, float] | None = None
    accent_max_ratio: float = 0.28
    accent_c_band: tuple[float, float] | None = None
    accent_hue_anchors: tuple[float, ...] = ()
    hue_pull: float = 0.50
    ink_accent_mode: bool = False
    seq_hue_pair: tuple[float, float] = (210.0, 235.0)
    div_hue_poles: tuple[float, float] = (230.0, 28.0)
    recessive_control_hex: str = "#DCE3EA"
    preview_swatches: tuple[str, ...] = ()

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": {"en": self.name_en, "zh": self.name_zh},
            "description": {"en": self.description_en, "zh": self.description_zh},
            "l_band": [round(self.l_band[0], 3), round(self.l_band[1], 3)],
            "c_band": [round(self.c_band[0], 3), round(self.c_band[1], 3)],
            "hue_anchors": [round(a, 1) for a in self.hue_anchors],
            "hue_sector": [round(self.hue_sector[0], 1), round(self.hue_sector[1], 1)] if self.hue_sector else None,
            "hue_pull": round(self.hue_pull, 2),
            "preview_swatches": list(self.preview_swatches),
        }


@dataclass
class StyleSculptResult:
    """Result of applying a `StyleProfile` to a parsed PDF or SVG scene."""

    style_id: str
    entity_hex: dict[str, str]
    group_hex: dict[str, str]
    scale_stops: dict[str, list[str]]
    diagnostics: dict[str, Any] = field(default_factory=dict)


STYLE_PROFILES: dict[str, StyleProfile] = {
    "aegean_blue_white": StyleProfile(
        id="aegean_blue_white",
        name_en="Aegean Blue & White",
        name_zh="地中海蓝白",
        description_en="Crisp 200°–240° marine blues and cerulean cyan paired with sunlit limestone sand.",
        description_zh="以 200°–240° 蓝青为主搭配暖沙点缀，清爽通透。",
        l_band=(0.38, 0.80),
        c_band=(0.068, 0.142),
        hue_anchors=(202.0, 216.0, 228.0, 239.0),
        anchor_weights=(1.0, 1.05, 1.05, 1.0),
        hue_sector=(200.0, 240.0),
        accent_hue_sector=(56.0, 80.0),
        accent_max_ratio=0.26,
        accent_c_band=(0.052, 0.102),
        accent_hue_anchors=(66.0, 75.0),
        hue_pull=0.48,
        seq_hue_pair=(204.0, 236.0),
        div_hue_poles=(226.0, 66.0),
        recessive_control_hex="#DCE5EC",
        preview_swatches=("#276298", "#488AB8", "#74B2C9", "#D7B27B"),
    ),
    "qingbai_porcelain": StyleProfile(
        id="qingbai_porcelain",
        name_en="Qingbai Porcelain",
        name_zh="青白瓷",
        description_en="Song Yingqing 170°–215° shadow-celadon glaze and warm ivory with gentle translucency.",
        description_zh="170°–215° 影青玉调搭配暖象牙，低色度温润清透。",
        l_band=(0.46, 0.85),
        c_band=(0.030, 0.080),
        hue_anchors=(172.0, 186.0, 200.0, 213.0),
        anchor_weights=(1.0, 1.05, 1.05, 0.95),
        hue_sector=(170.0, 215.0),
        accent_hue_sector=(72.0, 96.0),
        accent_max_ratio=0.26,
        accent_c_band=(0.026, 0.060),
        accent_hue_anchors=(80.0, 90.0),
        hue_pull=0.50,
        seq_hue_pair=(178.0, 206.0),
        div_hue_poles=(194.0, 78.0),
        recessive_control_hex="#DFE6E5",
        preview_swatches=("#4F8184", "#72A2A0", "#9BC0C3", "#D8CEB8"),
    ),
    "warm_terracotta": StyleProfile(
        id="warm_terracotta",
        name_en="Warm Terracotta",
        name_zh="暖陶土与砂岩",
        description_en="Pure 15°–72° baked terracotta, burnt sienna, and sandstone ochre with zero cool blue.",
        description_zh="15°–72° 纯暖陶土、赭石与砂岩金调，零冷蓝。",
        l_band=(0.37, 0.80),
        c_band=(0.058, 0.144),
        hue_anchors=(20.0, 36.0, 53.0, 69.0),
        anchor_weights=(1.0, 1.0, 1.0, 1.0),
        hue_sector=(15.0, 72.0),
        hue_pull=0.48,
        seq_hue_pair=(68.0, 22.0),
        div_hue_poles=(21.0, 69.0),
        recessive_control_hex="#E6DFD7",
        preview_swatches=("#9E442F", "#C86B43", "#DBA058", "#E7C58B"),
    ),
    "bauhaus_airy": StyleProfile(
        id="bauhaus_airy",
        name_en="Bauhaus Airy Pastel",
        name_zh="包豪斯空气粉彩",
        description_en="Luminous high-lightness (L 0.64–0.84) architectural primaries with buoyant clarity.",
        description_zh="高明度柔光几何粉彩，轻盈明快而不泛白。",
        l_band=(0.64, 0.84),
        c_band=(0.060, 0.124),
        hue_anchors=(28.0, 84.0, 162.0, 226.0, 298.0),
        anchor_weights=(1.0, 0.95, 0.95, 1.0, 0.85),
        hue_sector=None,
        hue_pull=0.45,
        seq_hue_pair=(86.0, 226.0),
        div_hue_poles=(226.0, 28.0),
        recessive_control_hex="#E5E8EC",
        preview_swatches=("#EB9783", "#E6C76D", "#7FC4AE", "#80B1DE"),
    ),
    "ink_vermilion": StyleProfile(
        id="ink_vermilion",
        name_en="Sumi Ink & Vermilion",
        name_zh="水墨朱砂",
        description_en="Restrained mineral ink-wash slates punctuated by cinnabar vermilion and indigo focal accents.",
        description_zh="克制水墨灰阶搭配少量朱砂与花青焦点，层次分明。",
        l_band=(0.30, 0.80),
        c_band=(0.015, 0.048),
        hue_anchors=(66.0, 218.0, 248.0),
        anchor_weights=(0.85, 1.0, 0.95),
        hue_sector=None,
        hue_pull=0.55,
        ink_accent_mode=True,
        accent_c_band=(0.112, 0.164),
        accent_hue_anchors=(28.0, 252.0),
        seq_hue_pair=(74.0, 28.0),
        div_hue_poles=(250.0, 28.0),
        recessive_control_hex="#E3E5E7",
        preview_swatches=("#C44737", "#364F6B", "#626C75", "#A4ACB3"),
    ),
    "vermeer_jewel": StyleProfile(
        id="vermeer_jewel",
        name_en="Vermeer Jewel",
        name_zh="维米尔深沉油画",
        description_en="Deep chiaroscuro ultramarine, yellow ochre, madder carmine, and verdigris (L 0.34–0.68).",
        description_zh="低明度群青、赭石、茜红与铜绿，深沉典雅。",
        l_band=(0.34, 0.68),
        c_band=(0.072, 0.148),
        hue_anchors=(254.0, 76.0, 22.0, 172.0),
        anchor_weights=(1.05, 1.0, 0.98, 0.92),
        hue_sector=None,
        hue_pull=0.50,
        seq_hue_pair=(78.0, 254.0),
        div_hue_poles=(254.0, 23.0),
        recessive_control_hex="#DDDAD2",
        preview_swatches=("#274478", "#B68330", "#8E3338", "#356862"),
    ),
    "twilight_indigo": StyleProfile(
        id="twilight_indigo",
        name_en="Twilight Indigo",
        name_zh="暮色靛紫",
        description_en="Dusk 235°–330° cobalt indigo, periwinkle, wisteria, and smoky plum.",
        description_zh="235°–330° 暮色靛蓝、紫藤与烟熏紫调。",
        l_band=(0.37, 0.78),
        c_band=(0.056, 0.136),
        hue_anchors=(242.0, 268.0, 296.0, 322.0),
        anchor_weights=(1.0, 1.0, 1.0, 1.0),
        hue_sector=(235.0, 330.0),
        hue_pull=0.50,
        seq_hue_pair=(318.0, 246.0),
        div_hue_poles=(243.0, 324.0),
        recessive_control_hex="#E2E1EA",
        preview_swatches=("#384B8C", "#625BA3", "#8F6CB2", "#BA8AB9"),
    ),
    "kyoto_moss": StyleProfile(
        id="kyoto_moss",
        name_en="Kyoto Moss Garden",
        name_zh="京都苔庭",
        description_en="Botanical 65°–145° cedar pine, moss green, bamboo celadon, and hinoki wood.",
        description_zh="65°–145° 松绿、苔绿、竹青与桧木原木调。",
        l_band=(0.37, 0.78),
        c_band=(0.048, 0.120),
        hue_anchors=(70.0, 96.0, 120.0, 141.0),
        anchor_weights=(0.95, 1.0, 1.0, 1.0),
        hue_sector=(65.0, 145.0),
        hue_pull=0.50,
        seq_hue_pair=(92.0, 140.0),
        div_hue_poles=(139.0, 70.0),
        recessive_control_hex="#DFE4DC",
        preview_swatches=("#3B6447", "#638752", "#8EA769", "#B49C66"),
    ),
}


def list_styles() -> list[StyleProfile]:
    """Return all built-in aesthetic `StyleProfile` definitions in canonical UI order."""
    return list(STYLE_PROFILES.values())


def get_style(style: str | StyleProfile) -> StyleProfile:
    """Resolve a built-in style ID or pass through a custom/extracted `StyleProfile`."""
    if isinstance(style, StyleProfile):
        return style
    key = style.strip().lower()
    if key not in STYLE_PROFILES:
        raise KeyError(f"Unknown style {style!r}; expected one of {sorted(STYLE_PROFILES)}")
    return STYLE_PROFILES[key]


def _smallest_enclosing_hue_arc(hues_deg: Sequence[float]) -> tuple[float, float, float]:
    """Return `(start_deg, end_deg, arc_span_deg)` of the smallest circular arc enclosing `hues_deg`."""
    if not hues_deg:
        return 0.0, 360.0, 360.0
    if len(hues_deg) == 1:
        h0 = hues_deg[0] % 360.0
        return (h0 - 20.0) % 360.0, (h0 + 20.0) % 360.0, 40.0
    sorted_h = sorted(float(h) % 360.0 for h in hues_deg)
    m = len(sorted_h)
    max_gap = -1.0
    max_gap_idx = 0
    for i in range(m):
        nxt = sorted_h[(i + 1) % m]
        gap = (nxt - sorted_h[i]) % 360.0
        if gap == 0.0 and m > 1 and sorted_h[0] == sorted_h[-1]:
            gap = 360.0
        if gap > max_gap:
            max_gap = gap
            max_gap_idx = i
    start = sorted_h[(max_gap_idx + 1) % m]
    end = sorted_h[max_gap_idx]
    span = max(0.0, 360.0 - max_gap)
    return start, end, span


def extract_style_profile(
    reference: str | Sequence[str],
    *,
    style_id: str = "extracted_style",
    name_en: str = "Reference Style",
    name_zh: str = "参考提取风格",
    hue_pull: float = 0.50,
) -> StyleProfile:
    """Automatically extract a reusable `StyleProfile` from any palette ID or list of `#RRGGBB` colors."""
    if isinstance(reference, str):
        pal = get_palette(reference)
        ref_hexes = list(pal.colors)
        if style_id == "extracted_style":
            style_id = f"style_from_{pal.id}"
        if name_en == "Reference Style":
            name_en = f"{pal.name_en} Style"
        if name_zh == "参考提取风格":
            name_zh = f"{pal.name_zh}风格"
    else:
        ref_hexes = [str(c).strip() for c in reference if str(c).strip()]

    if not ref_hexes:
        raise ValueError("Reference color sequence cannot be empty.")

    lchs = [hex_to_oklch(h) for h in ref_hexes]
    valid = [(L, C, h) for (L, C, h) in lchs if 0.08 <= L <= 0.96]
    if not valid:
        valid = lchs

    ls = [x[0] for x in valid]
    cs = [x[1] for x in valid]
    l_lo = float(np.clip(min(ls), 0.28, 0.72))
    l_hi = float(np.clip(max(ls), l_lo + 0.20, 0.86))
    if l_hi - l_lo < 0.20:
        mid_l = 0.5 * (l_lo + l_hi)
        l_lo = float(np.clip(mid_l - 0.11, 0.28, 0.72))
        l_hi = float(np.clip(mid_l + 0.11, l_lo + 0.18, 0.86))

    chromatic = [(L, C, h) for (L, C, h) in valid if C >= 0.018]
    if chromatic:
        c_vals = [x[1] for x in chromatic]
        c_lo = float(np.clip(np.percentile(c_vals, 15), 0.024, 0.120))
        c_hi = float(np.clip(np.percentile(c_vals, 90), max(c_lo + 0.028, 0.045), 0.165))
        sorted_by_c = sorted(chromatic, key=lambda x: x[1], reverse=True)
        anchors: list[float] = []
        for _, _, h_cand in sorted_by_c:
            if all(abs(_wrap180(h_cand - a)) >= 18.0 for a in anchors):
                anchors.append(round(h_cand, 1))
            if len(anchors) >= 4:
                break
        if not anchors:
            anchors = [round(sorted_by_c[0][2], 1)]
        arc_s, arc_e, arc_span = _smallest_enclosing_hue_arc([x[2] for x in chromatic])
        sector: tuple[float, float] | None = None
        if len(chromatic) >= 2 and arc_span <= 125.0:
            pad = min(10.0, 0.5 * (140.0 - arc_span))
            sector = ((arc_s - pad) % 360.0, (arc_e + pad) % 360.0)
    else:
        c_lo, c_hi = 0.020, 0.050
        anchors = [220.0, 65.0]
        sector = None

    h0 = anchors[0]
    h1 = anchors[1] if len(anchors) >= 2 else ((h0 + 28.0) % 360.0 if sector is None else _clamp_to_sector(h0 + 24.0, sector))
    div_b = anchors[-1] if len(anchors) >= 2 and abs(_wrap180(anchors[-1] - h0)) >= 35.0 else (
        _clamp_to_sector(h0 + 180.0, sector)
    )
    swatches = tuple(ref_hexes[:4]) if len(ref_hexes) >= 4 else tuple(ref_hexes)
    return StyleProfile(
        id=style_id,
        name_en=name_en,
        name_zh=name_zh,
        description_en="Automatically extracted OKLCH lightness, chroma, and hue envelope.",
        description_zh="从参考配色自动提取的明度带、色度包络与主色相锚点。",
        l_band=(l_lo, l_hi),
        c_band=(c_lo, c_hi),
        hue_anchors=tuple(anchors),
        hue_sector=sector,
        hue_pull=float(np.clip(hue_pull, 0.25, 0.80)),
        seq_hue_pair=(h1, h0),
        div_hue_poles=(h0, div_b),
        preview_swatches=swatches,
    )


def _pull_hue(
    h_deg: float,
    anchors: Sequence[float],
    weights: Sequence[float],
    pull: float,
    sector: tuple[float, float] | None = None,
) -> float:
    """Pull circular hue `h_deg` toward the nearest weighted style anchor, respecting `sector` if bounded."""
    h_work = _project_into_sector(h_deg, sector) if sector is not None else (h_deg % 360.0)
    if not anchors:
        return h_work
    best_a = anchors[0]
    best_cost = 1e9
    for idx, a in enumerate(anchors):
        w = weights[idx] if idx < len(weights) and weights[idx] > 0 else 1.0
        cost = abs(_wrap180(a - h_work)) / w
        if cost < best_cost:
            best_cost = cost
            best_a = a
    dh = _wrap180(best_a - h_work)
    pulled = (h_work + float(pull) * dh) % 360.0
    return _clamp_to_sector(pulled, sector, pad_deg=0.6)


def _is_recessive_control_entity(ent: SemanticEntity) -> bool:
    raw_tier = (ent.tier or "normal").strip().lower()
    if raw_tier in ("control", "background", "context"):
        return True
    norm_lbl = ent.label.strip().lower()
    if norm_lbl in _RECESSIVE_CONTROL_LABELS:
        return True
    return False


@dataclass
class _SculptVar:
    var_id: str
    label: str
    role: str
    is_recessive_control: bool
    is_locked: bool
    panels: set[str]
    entity_ids: list[str]
    input_hex: str
    L_in: float
    C_in: float
    h_in: float


def _enforce_panel_de2000_guardrail(
    vars_list: list[_SculptVar],
    target_lch: dict[str, tuple[float, float, float]],
    var_bounds: dict[str, tuple[tuple[float, float], tuple[float, float], tuple[float, float] | None]],
    fixed_hex: dict[str, str],
    collision_scope: CollisionScope,
    min_de_target: float = 9.0,
) -> dict[str, str]:
    """Ensure intra-panel (or global) pairs meet `min_de_target` & Deutan separation inside the style envelope."""
    n = len(vars_list)
    cur_lch: dict[str, list[float]] = {k: [v[0], v[1], v[2]] for k, v in target_lch.items()}
    cur_hex: dict[str, str] = {}
    for sv in vars_list:
        if sv.var_id in fixed_hex:
            cur_hex[sv.var_id] = fixed_hex[sv.var_id]
        else:
            L0, C0, h0 = cur_lch[sv.var_id]
            cur_hex[sv.var_id] = oklch_to_hex(L0, C0, h0)

    if n < 2:
        return cur_hex

    # Count active non-recessive variables per panel to scale `min_de_target` gracefully when k > 8
    panel_k: dict[str, int] = {}
    for sv in vars_list:
        if not sv.is_recessive_control:
            for p in sv.panels:
                panel_k[p] = panel_k.get(p, 0) + 1
    if collision_scope == "global_strict":
        total_k = sum(1 for sv in vars_list if not sv.is_recessive_control)
        panel_k["__global__"] = total_k

    # Precompute constrained variable pairs and their adaptive target ΔE2000
    pairs: list[tuple[int, int, float, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            va, vb = vars_list[i], vars_list[j]
            if va.is_recessive_control and vb.is_recessive_control:
                continue
            shared = sorted(va.panels & vb.panels)
            if not shared and collision_scope != "global_strict":
                continue
            if va.is_locked and vb.is_locked:
                continue
            max_k = max((panel_k.get(p, 2) for p in shared), default=panel_k.get("__global__", 2))
            if max_k <= 8:
                t_norm = float(min_de_target)
            else:
                t_norm = max(6.8, float(min_de_target) * math.sqrt(8.0 / float(max_k)))
            # Slightly softer floor against recessive background points while keeping data crisp
            if va.is_recessive_control or vb.is_recessive_control:
                t_norm = min(t_norm, 8.0)
            t_deut = max(4.8, 0.62 * t_norm)
            pairs.append((i, j, t_norm, t_deut))

    if not pairs:
        return cur_hex

    def _eval_matrices() -> tuple[np.ndarray, np.ndarray]:
        arr = np.stack([hex_to_srgb01(cur_hex[sv.var_id]) for sv in vars_list], axis=0)
        m_n = ciede2000_matrix(arr)
        m_d = ciede2000_matrix(simulate_cvd(arr, "deutan", 0.85))
        return m_n, m_d

    # Phase 1: Smooth elastic pairwise repulsion in OKLCH within style bounds
    for step_idx in range(48):
        m_n, m_d = _eval_matrices()
        worst_deficit = 0.0
        worst_pair: tuple[int, int, float, float, float, float] | None = None
        for i, j, tn, td in pairs:
            dn = float(m_n[i, j])
            dd = float(m_d[i, j])
            deficit = max(tn - dn, 0.85 * (td - dd))
            if deficit > worst_deficit:
                worst_deficit = deficit
                worst_pair = (i, j, dn, dd, tn, td)
        if worst_pair is None or worst_deficit <= 0.05:
            break

        ia, ib, dn, dd, tn, td = worst_pair
        va, vb = vars_list[ia], vars_list[ib]
        movable_a = va.var_id not in fixed_hex
        movable_b = vb.var_id not in fixed_hex
        if not movable_a and not movable_b:
            break

        La, Ca, ha = (cur_lch[va.var_id] if movable_a else list(hex_to_oklch(cur_hex[va.var_id])))
        Lb, Cb, hb = (cur_lch[vb.var_id] if movable_b else list(hex_to_oklch(cur_hex[vb.var_id])))

        # Push L apart (crucial for both normal & deutan separation!) and h apart within sector
        gain = min(1.0, 0.35 + 0.08 * worst_deficit)
        sign_L = -1.0 if (La < Lb or (abs(La - Lb) < 1e-4 and ia < ib)) else 1.0
        dL_step = 0.024 * gain
        dh_raw = _wrap180(ha - hb)
        sign_h = -1.0 if (dh_raw < 0 or (abs(dh_raw) < 1e-3 and ia < ib)) else 1.0
        dh_step = 7.5 * gain
        sign_C = -sign_L  # Counter-stagger chroma vs lightness to open 3D separation without leaving band
        dC_step = 0.008 * gain

        for sv_m, sL, sC, sh, is_mov in (
            (va, sign_L, sign_C, sign_h, movable_a),
            (vb, -sign_L, -sign_C, -sign_h, movable_b),
        ):
            if not is_mov:
                continue
            l_b, c_b, sec_b = var_bounds[sv_m.var_id]
            L0, C0, h0 = target_lch[sv_m.var_id]
            Lc, Cc, hc = cur_lch[sv_m.var_id]
            share = 0.55 if (movable_a and movable_b) else 1.0
            Ln = float(np.clip(Lc + share * sL * dL_step, l_b[0], l_b[1]))
            Cn = float(np.clip(Cc + share * sC * dC_step, c_b[0], c_b[1]))
            hn_cand = (hc + share * sh * dh_step) % 360.0
            # Soft tether when unbounded so hues stay faithful to style + palette identity (max +/- 42 deg drift)
            if sec_b is None:
                drift = _wrap180(hn_cand - h0)
                if abs(drift) > 42.0:
                    hn_cand = (h0 + math.copysign(42.0, drift)) % 360.0
            else:
                hn_cand = _clamp_to_sector(hn_cand, sec_b, pad_deg=0.6)
            cur_lch[sv_m.var_id] = [Ln, Cn, hn_cand]
            cur_hex[sv_m.var_id] = oklch_to_hex(Ln, Cn, hn_cand)

    # Phase 2: Deterministic local style-bounded lattice polish if any pair still violates `min_de_target`
    for _ in range(28):
        m_n, m_d = _eval_matrices()
        offending_idx: int | None = None
        worst_def = 0.0
        for i, j, tn, td in pairs:
            def_ij = max(tn - float(m_n[i, j]), 0.80 * (td - float(m_d[i, j])))
            if def_ij > worst_def:
                if vars_list[i].var_id not in fixed_hex and vars_list[j].var_id not in fixed_hex:
                    # Pick the one with smaller L/C span or later order
                    offending_idx = j
                    worst_def = def_ij
                elif vars_list[i].var_id not in fixed_hex:
                    offending_idx = i
                    worst_def = def_ij
                elif vars_list[j].var_id not in fixed_hex:
                    offending_idx = j
                    worst_def = def_ij
        if offending_idx is None or worst_def <= 0.05:
            break

        sv_off = vars_list[offending_idx]
        vid = sv_off.var_id
        l_b, c_b, sec_b = var_bounds[vid]
        L0, C0, h0 = target_lch[vid]

        rel_peers = [
            (j if i == offending_idx else i, tn, td)
            for (i, j, tn, td) in pairs
            if i == offending_idx or j == offending_idx
        ]
        peer_srgb = np.stack([hex_to_srgb01(cur_hex[vars_list[p_idx].var_id]) for p_idx, _, _ in rel_peers], axis=0)
        peer_deut = simulate_cvd(peer_srgb, "deutan", 0.85)

        l_grid = np.linspace(l_b[0], l_b[1], 7)
        c_grid = np.linspace(c_b[0], c_b[1], 4)
        if sec_b is not None:
            s_ang = sec_b[0] % 360.0
            span_ang = (sec_b[1] - sec_b[0]) % 360.0
            h_grid = [(s_ang + u * span_ang) % 360.0 for u in np.linspace(0.03, 0.97, 9)]
        else:
            h_grid = [(h0 + dh) % 360.0 for dh in (-44.0, -30.0, -18.0, -8.0, 0.0, 8.0, 18.0, 30.0, 44.0)]

        cur_rgb = hex_to_srgb01(cur_hex[vid])[None, :]
        cur_dn = ciede2000_matrix(cur_rgb, peer_srgb)[0]
        cur_dd = ciede2000_matrix(simulate_cvd(cur_rgb, "deutan", 0.85), peer_deut)[0]
        best_worst_def = max(
            max(tn - float(cur_dn[k]), 0.80 * (td - float(cur_dd[k])))
            for k, (_, tn, td) in enumerate(rel_peers)
        )
        best_score = -1e9
        best_choice: tuple[float, float, float, str] | None = None

        for Lg in l_grid:
            for Cg in c_grid:
                for hg in h_grid:
                    hx_c = oklch_to_hex(float(Lg), float(Cg), float(hg))
                    rgb_c = hex_to_srgb01(hx_c)[None, :]
                    dn_vec = ciede2000_matrix(rgb_c, peer_srgb)[0]
                    dd_vec = ciede2000_matrix(simulate_cvd(rgb_c, "deutan", 0.85), peer_deut)[0]
                    cand_def = max(
                        max(tn - float(dn_vec[k]), 0.80 * (td - float(dd_vec[k])))
                        for k, (_, tn, td) in enumerate(rel_peers)
                    )
                    drift = (
                        2.5 * abs(float(Lg) - L0)
                        + 4.0 * abs(float(Cg) - C0)
                        + 0.012 * abs(_wrap180(float(hg) - h0))
                    )
                    sc = -12.0 * max(0.0, cand_def) + 0.35 * float(dn_vec.min()) + 0.20 * float(dd_vec.min()) - drift
                    if cand_def < best_worst_def - 0.05 and sc > best_score:
                        best_score = sc
                        best_choice = (float(Lg), float(Cg), float(hg), hx_c)

        if best_choice is None:
            break
        cur_lch[vid] = [best_choice[0], best_choice[1], best_choice[2]]
        cur_hex[vid] = best_choice[3]
        best_worst_def = 0.0

    return cur_hex


def sculpt_continuous_stops(
    stops_hex: Sequence[str],
    profile: StyleProfile,
    *,
    kind: str = "continuous_sequential",
    midpoint_t: float = 0.5,
) -> list[str]:
    """Sculpt a continuous sequential or diverging stop sequence into `profile` while preserving monotonicity."""
    if len(stops_hex) < 2:
        return list(stops_hex)

    is_div = kind == "continuous_diverging"
    lut7 = interpolate_oklch_lut(
        stops_hex,
        n=7,
        diverging_midpoint=(midpoint_t if is_div else None),
    )
    lch7 = oklab_to_oklch(srgb_to_oklab(lut7))  # (7, 3)

    if is_div:
        L_mid = 0.955
        L_pole = float(np.clip(min(profile.l_band[0], 0.48), 0.30, 0.52))
        c_peak = float(
            max(
                profile.accent_c_band[1] if (profile.ink_accent_mode and profile.accent_c_band) else profile.c_band[1],
                0.075 if not profile.id == "qingbai_porcelain" else 0.068,
            )
        )
        # Extract left (idx 0,1) and right (idx 5,6) input hues
        h_in_left = float(lch7[0, 2]) if lch7[0, 1] >= 0.015 else float(lch7[1, 2])
        h_in_right = float(lch7[6, 2]) if lch7[6, 1] >= 0.015 else float(lch7[5, 2])

        pole_a, pole_b = profile.div_hue_poles
        # Match input poles to whichever assignment of (pole_a, pole_b) requires smaller rotation
        cost_direct = abs(_wrap180(pole_a - h_in_left)) + abs(_wrap180(pole_b - h_in_right))
        cost_swapped = abs(_wrap180(pole_b - h_in_left)) + abs(_wrap180(pole_a - h_in_right))
        targ_left, targ_right = (pole_a, pole_b) if cost_direct <= cost_swapped else (pole_b, pole_a)

        p_eff = max(profile.hue_pull, 0.58)

        def _pole_sector(target_deg: float) -> tuple[float, float] | None:
            if profile.accent_hue_sector is not None and _angle_in_sector(target_deg, profile.accent_hue_sector):
                return profile.accent_hue_sector
            return profile.hue_sector

        sec_l = _pole_sector(targ_left)
        sec_r = _pole_sector(targ_right)
        base_l = _project_into_sector(h_in_left, sec_l) if sec_l else h_in_left
        base_r = _project_into_sector(h_in_right, sec_r) if sec_r else h_in_right
        h_left = _clamp_to_sector(base_l + p_eff * _wrap180(targ_left - base_l), sec_l)
        h_right = _clamp_to_sector(base_r + p_eff * _wrap180(targ_right - base_r), sec_r)
        if abs(_wrap180(h_left - h_right)) < 28.0:
            h_left = targ_left
            h_right = targ_right

        out_div: list[str] = []
        for idx in range(7):
            if idx == 3:
                out_div.append(oklch_to_hex(L_mid, 0.005, targ_right))
                continue
            d = abs(idx - 3) / 3.0  # in {1/3, 2/3, 1.0}
            L_k = L_mid - (L_mid - L_pole) * (d**0.88)
            C_k = 0.012 + (c_peak - 0.012) * (d**0.85)
            h_k = h_left if idx < 3 else h_right
            out_div.append(oklch_to_hex(L_k, C_k, h_k))
        return out_div

    # Sequential scale: strictly preserve L(t) monotonicity (light->dark or dark->light)
    light_to_dark = bool(float(lch7[0, 0]) >= float(lch7[-1, 0]))
    L_airy = float(np.clip(max(profile.l_band[1] + 0.11, 0.915), 0.885, 0.955))
    L_deep = float(np.clip(min(profile.l_band[0] - 0.04, 0.52), 0.28, 0.54))

    # Extract input normalized lightness shape in s in [0, 1] (0 = airy light end, 1 = deep pole)
    l_seq_in = lch7[:, 0].copy() if light_to_dark else lch7[::-1, 0].copy()
    l_span_in = float(l_seq_in[0] - l_seq_in[-1])

    # Extract chromatic hues near airy-mid (idx 2) and deep pole (idx 5..6)
    c_seq_in = lch7[:, 1] if light_to_dark else lch7[::-1, 1]
    h_seq_in = lch7[:, 2] if light_to_dark else lch7[::-1, 2]
    idx_lo = 2 if float(c_seq_in[2]) >= 0.012 else int(np.argmax(c_seq_in))
    idx_hi = 5 if float(c_seq_in[5]) >= 0.012 else int(np.argmax(c_seq_in))
    h_lo_pulled = _pull_hue(
        float(h_seq_in[idx_lo]),
        profile.accent_hue_anchors if profile.ink_accent_mode else profile.hue_anchors,
        () if profile.ink_accent_mode else profile.anchor_weights,
        max(profile.hue_pull, 0.54),
        profile.hue_sector,
    )
    h_hi_pulled = _pull_hue(
        float(h_seq_in[idx_hi]),
        profile.accent_hue_anchors if profile.ink_accent_mode else profile.hue_anchors,
        () if profile.ink_accent_mode else profile.anchor_weights,
        max(profile.hue_pull, 0.54),
        profile.hue_sector,
    )
    # Add gentle natural hue depth (~14 deg toward style's seq_hue_pair[1]) if single-hue flat ramp
    if abs(_wrap180(h_hi_pulled - h_lo_pulled)) < 8.0:
        sh_dir = _wrap180(profile.seq_hue_pair[1] - h_hi_pulled)
        step_deg = math.copysign(min(16.0, max(8.0, abs(sh_dir) * 0.35)), sh_dir if abs(sh_dir) > 1e-3 else 1.0)
        h_hi_pulled = _clamp_to_sector((h_lo_pulled + step_deg) % 360.0, profile.hue_sector)

    c_lo_style = profile.c_band[0]
    c_hi_style = (
        0.128 if profile.ink_accent_mode else min(0.156, max(profile.c_band[1] * 1.05, 0.068))
    )
    c_start = max(0.012, min(0.026, 0.28 * c_lo_style))

    stops_airy_to_deep: list[str] = []
    prev_L = L_airy + 0.05
    min_step = (L_airy - L_deep) / 9.5
    for k in range(7):
        s = k / 6.0
        u_lin = s
        if l_span_in >= 0.12:
            u_in = float(np.clip((l_seq_in[0] - l_seq_in[k]) / l_span_in, 0.0, 1.0))
            u_s = 0.45 * u_in + 0.55 * u_lin
        else:
            u_s = u_lin
        L_cand = L_airy - u_s * (L_airy - L_deep)
        # Guarantee strict step-by-step monotonic decrease from airy to deep even after 8-bit hex rounding
        max_allowed = prev_L - min_step if k > 0 else L_airy
        min_allowed = L_deep + (6 - k) * min_step
        L_k = float(np.clip(min(L_cand, max_allowed), min_allowed, L_airy))
        prev_L = L_k

        C_k = c_start + (c_hi_style - c_start) * (s**0.76) * (1.0 - 0.10 * (s**3))
        dh_arc = _wrap180(h_hi_pulled - h_lo_pulled)
        h_k = _clamp_to_sector((h_lo_pulled + s * dh_arc) % 360.0, profile.hue_sector)
        hx = oklch_to_hex(L_k, C_k, h_k)
        # Read back actual quantized L so `prev_L` tracks exact 8-bit hex lightness
        prev_L = hex_to_oklch(hx)[0]
        stops_airy_to_deep.append(hx)

    return stops_airy_to_deep if light_to_dark else list(reversed(stops_airy_to_deep))


def sculpt_scene_style(
    scene: ParsedPdfScene | SvgScene,
    style: str | StyleProfile,
    *,
    entity_hex: dict[str, str] | None = None,
    group_hex: dict[str, str] | None = None,
    scale_stops: dict[str, list[str]] | None = None,
    collision_scope: CollisionScope = "panel_scoped",
    min_de_target: float = 9.0,
) -> StyleSculptResult:
    """Sculpt discrete entities and continuous scales of `scene` into `style` cleanly in OKLCH.

    Updates BOTH `scale_stops[scale_id]` AND every `gid` in `cs.member_group_ids` inside `group_hex`.
    Protects locked elements, recessive control/background layers, canvas `#FFFFFF`, and Gate G0 images.
    """
    profile = get_style(style)
    scope: CollisionScope = "global_strict" if collision_scope in ("unique", "global_strict") else "panel_scoped"

    in_entity_hex = {
        eid: (entity_hex[eid] if (entity_hex and eid in entity_hex) else ent.current_hex)
        for eid, ent in scene.entities.items()
    }
    out_group_hex: dict[str, str] = {
        gid: (group_hex[gid] if (group_hex and gid in group_hex) else cg.current_hex)
        for gid, cg in scene.color_groups.items()
    }

    # 1. Group entities into shared color variables (preserving `same_name` cross-panel links unless `unlinked`
    #    or unless input colors already differ across panels due to per-panel palettes)
    vars_by_key: dict[str, _SculptVar] = {}
    ordered_vars: list[_SculptVar] = []
    for eid, ent in scene.entities.items():
        hx_in = in_entity_hex[eid].upper()
        L_in, C_in, h_in = hex_to_oklch(hx_in)
        norm_lbl = ent.label.strip().lower()
        vkey = f"__id__{eid}" if (ent.unlinked or not norm_lbl) else f"__lbl__{norm_lbl}__{hx_in}"
        is_ctrl = _is_recessive_control_entity(ent)
        role = normalize_role(ent.tier)

        if vkey not in vars_by_key:
            sv = _SculptVar(
                var_id=vkey,
                label=ent.label,
                role=role,
                is_recessive_control=is_ctrl,
                is_locked=bool(ent.locked),
                panels=set(ent.panels),
                entity_ids=[eid],
                input_hex=hx_in,
                L_in=L_in,
                C_in=C_in,
                h_in=h_in,
            )
            vars_by_key[vkey] = sv
            ordered_vars.append(sv)
        else:
            sv = vars_by_key[vkey]
            sv.panels.update(ent.panels)
            sv.entity_ids.append(eid)
            sv.is_locked = sv.is_locked or bool(ent.locked)
            if role == "focus":
                sv.role = "focus"
            if is_ctrl and sv.role != "focus":
                sv.is_recessive_control = True

    fixed_var_hex: dict[str, str] = {}
    sculptable_vars: list[_SculptVar] = []
    for sv in ordered_vars:
        if sv.is_locked:
            fixed_var_hex[sv.var_id] = sv.input_hex
        elif sv.is_recessive_control:
            # Constraint 4: Keep already-recessive light neutral untouched; otherwise lock to recessive light gray
            if sv.L_in >= 0.70 and sv.C_in <= 0.030:
                fixed_var_hex[sv.var_id] = sv.input_hex
            else:
                fixed_var_hex[sv.var_id] = profile.recessive_control_hex
        else:
            sculptable_vars.append(sv)

    target_lch: dict[str, tuple[float, float, float]] = {}
    var_bounds: dict[str, tuple[tuple[float, float], tuple[float, float], tuple[float, float] | None]] = {}

    # Populate fixed entries in `target_lch` for reference
    for vid, fhx in fixed_var_hex.items():
        target_lch[vid] = hex_to_oklch(fhx)
        var_bounds[vid] = (profile.l_band, profile.c_band, profile.hue_sector)

    # 2. Discrete OKLCH Elastic Sculpting across `sculptable_vars`
    k_sc = len(sculptable_vars)
    if k_sc > 0:
        l_lo, l_hi = profile.l_band
        # Slight inset for tiny K=1..2 so 2-bar figures sit comfortably inside the band
        inset = 0.14 * (l_hi - l_lo) if k_sc == 1 else (0.06 * (l_hi - l_lo) if k_sc == 2 else 0.0)
        eff_l_lo, eff_l_hi = l_lo + inset, l_hi - inset

        # Order-preserving Lightness rank + continuous blend
        by_L = sorted(range(k_sc), key=lambda idx: (round(sculptable_vars[idx].L_in, 4), idx))
        L_min = min(sv.L_in for sv in sculptable_vars)
        L_max = max(sv.L_in for sv in sculptable_vars)
        L_span = L_max - L_min
        alpha_L = float(np.clip(L_span / 0.22, 0.0, 0.68)) if k_sc > 1 else 0.0

        u_L_map: dict[int, float] = {}
        for rank_i, orig_idx in enumerate(by_L):
            if k_sc == 1:
                u_L_map[orig_idx] = 0.45
            else:
                u_rank = rank_i / float(k_sc - 1)
                u_cont = (sculptable_vars[orig_idx].L_in - L_min) / max(L_span, 1e-6) if L_span > 1e-4 else u_rank
                u_L_map[orig_idx] = alpha_L * u_cont + (1.0 - alpha_L) * u_rank

        # Determine focal variables if `profile.ink_accent_mode` (`ink_vermilion`)
        focal_set: set[str] = set()
        if profile.ink_accent_mode:
            explicit_focus = [sv.var_id for sv in sculptable_vars if sv.role == "focus"]
            if explicit_focus:
                focal_set.update(explicit_focus)
            else:
                n_acc = 1 if k_sc <= 4 else 2
                ranked_focal = sorted(
                    sculptable_vars,
                    key=lambda s: (round(s.C_in, 4), -round(abs(s.L_in - 0.52), 4)),
                    reverse=True,
                )
                for sv_f in ranked_focal[:n_acc]:
                    focal_set.add(sv_f.var_id)

        # Determine warm-sand / warm-ivory accent variables when `profile.accent_hue_sector` is configured
        accent_sector_set: set[str] = set()
        if profile.accent_hue_sector is not None and not profile.ink_accent_mode and k_sc >= 3:
            acc_s = profile.accent_hue_sector[0] % 360.0
            acc_span = (profile.accent_hue_sector[1] - profile.accent_hue_sector[0]) % 360.0
            acc_mid = (acc_s + 0.5 * acc_span) % 360.0
            max_acc = max(1, int(round(profile.accent_max_ratio * k_sc)))
            warm_cands = [
                sv
                for sv in sculptable_vars
                if sv.C_in >= 0.020 and abs(_wrap180(sv.h_in - acc_mid)) <= 95.0
            ]
            warm_cands.sort(key=lambda s: (round(abs(_wrap180(s.h_in - acc_mid)), 3), -round(s.C_in, 4)))
            for sv_w in warm_cands[:max_acc]:
                accent_sector_set.add(sv_w.var_id)

        # Order-preserving Chroma rank + continuous blend
        by_C = sorted(range(k_sc), key=lambda idx: (round(sculptable_vars[idx].C_in, 4), idx))
        C_min = min(sv.C_in for sv in sculptable_vars)
        C_max = max(sv.C_in for sv in sculptable_vars)
        C_span = C_max - C_min
        alpha_C = float(np.clip(C_span / 0.12, 0.0, 0.65)) if k_sc > 1 else 0.0

        u_C_map: dict[int, float] = {}
        for rank_i, orig_idx in enumerate(by_C):
            if k_sc == 1:
                u_C_map[orig_idx] = 0.65
            else:
                u_rank = rank_i / float(k_sc - 1)
                u_cont = (sculptable_vars[orig_idx].C_in - C_min) / max(C_span, 1e-6) if C_span > 1e-4 else u_rank
                u_C_map[orig_idx] = alpha_C * u_cont + (1.0 - alpha_C) * u_rank

        for idx, sv in enumerate(sculptable_vars):
            L_new = eff_l_lo + u_L_map[idx] * (eff_l_hi - eff_l_lo)
            if sv.var_id in focal_set and profile.accent_c_band is not None:
                c_b = profile.accent_c_band
                C_new = c_b[0] + max(0.45, u_C_map[idx]) * (c_b[1] - c_b[0])
                L_new = float(np.clip(L_new, max(l_lo, 0.40), min(l_hi, 0.64)))
                h_pulled = _pull_hue(
                    sv.h_in,
                    profile.accent_hue_anchors or profile.hue_anchors,
                    (),
                    max(profile.hue_pull, 0.58),
                    None,
                )
                focal_sec = (
                    (16.0, 40.0)
                    if abs(_wrap180(h_pulled - 28.0)) <= abs(_wrap180(h_pulled - 252.0))
                    else (238.0, 265.0)
                )
                h_new = _clamp_to_sector(h_pulled, focal_sec, pad_deg=0.6)
                var_bounds[sv.var_id] = ((max(l_lo, 0.36), min(l_hi, 0.68)), c_b, focal_sec)
            elif sv.var_id in accent_sector_set and profile.accent_hue_sector is not None:
                c_b = profile.accent_c_band or profile.c_band
                C_new = c_b[0] + u_C_map[idx] * (c_b[1] - c_b[0])
                h_new = _pull_hue(
                    sv.h_in,
                    profile.accent_hue_anchors or profile.hue_anchors,
                    (),
                    max(profile.hue_pull, 0.52),
                    profile.accent_hue_sector,
                )
                var_bounds[sv.var_id] = (profile.l_band, c_b, profile.accent_hue_sector)
            else:
                c_b = profile.c_band
                u_c_eff = max(0.75, u_C_map[idx]) if sv.role == "focus" else u_C_map[idx]
                C_new = c_b[0] + u_c_eff * (c_b[1] - c_b[0])
                h_new = _pull_hue(
                    sv.h_in,
                    profile.hue_anchors,
                    profile.anchor_weights,
                    profile.hue_pull,
                    profile.hue_sector,
                )
                var_bounds[sv.var_id] = (profile.l_band, c_b, profile.hue_sector)

            target_lch[sv.var_id] = (float(L_new), float(C_new), float(h_new))

    # 3. Panel-Scoped ΔE2000 & Deutan Anti-Collision Guardrail
    final_var_hex = _enforce_panel_de2000_guardrail(
        vars_list=ordered_vars,
        target_lch=target_lch,
        var_bounds=var_bounds,
        fixed_hex=fixed_var_hex,
        collision_scope=scope,
        min_de_target=min_de_target,
    )

    out_entity_hex: dict[str, str] = {}
    for sv in ordered_vars:
        hx_final = final_var_hex[sv.var_id]
        for eid in sv.entity_ids:
            out_entity_hex[eid] = hx_final
            for gid in scene.entities[eid].member_group_ids:
                if gid in out_group_hex:
                    out_group_hex[gid] = hx_final

    # 4. Synchronous Continuous Scales Sculpting (`scale_stops` + `cs.member_group_ids` in `group_hex`)
    out_scale_stops: dict[str, list[str]] = {}
    for sid, cs in scene.continuous_scales.items():
        base_stops = list(
            scale_stops[sid]
            if (scale_stops and sid in scale_stops)
            else cs.current_stops_hex
        )
        if cs.locked:
            sculpted_stops = base_stops
        else:
            sculpted_stops = sculpt_continuous_stops(
                base_stops,
                profile,
                kind=cs.kind,
                midpoint_t=cs.midpoint_t,
            )
        out_scale_stops[sid] = sculpted_stops

        # Synchronize EVERY vector primitive group belonging to `cs.member_group_ids`
        eff_stops = list(reversed(sculpted_stops)) if cs.inverted_polarity else sculpted_stops
        mid = cs.midpoint_t if cs.kind == "continuous_diverging" else None
        lut256 = interpolate_oklch_lut(eff_stops, n=256, diverging_midpoint=mid)
        for gid in cs.member_group_ids:
            if gid in scene.color_groups:
                cg: ColorGroup = scene.color_groups[gid]
                idx_lut = max(0, min(255, int(round(cg.continuous_t * 255.0))))
                out_group_hex[gid] = srgb01_to_hex(lut256[idx_lut])

    diagnostics = evaluate_gates(
        entities=scene.entities,
        entity_hex=out_entity_hex,
        collision_scope=scope,
        palette_color_count=max(8, len(out_entity_hex)),
        required_color_count=sum(1 for sv in ordered_vars if not sv.is_recessive_control),
        generated_count=0,
    )
    diagnostics["aesthetic_style"] = profile.id
    return StyleSculptResult(
        style_id=profile.id,
        entity_hex=out_entity_hex,
        group_hex=out_group_hex,
        scale_stops=out_scale_stops,
        diagnostics=diagnostics,
    )


def apply_style_to_solve_result(
    scene: ParsedPdfScene | SvgScene,
    solved: SolveResult,
    style: str | StyleProfile,
    *,
    min_de_target: float = 9.0,
) -> SolveResult:
    """Compose `StyleProfile` sculpting on top of an existing `SolveResult` (updating inspector swatches too)."""
    sculpted = sculpt_scene_style(
        scene,
        style,
        entity_hex=solved.entity_hex,
        group_hex=solved.group_hex,
        scale_stops=solved.scale_stops,
        collision_scope=solved.collision_scope,
        min_de_target=min_de_target,
    )
    profile = get_style(style)

    # Refresh inspector swatches so manual picks offer the sculpted style colors + active palette colors
    swatch_pool = list(
        dict.fromkeys(
            [sculpted.entity_hex[eid] for eid in sculpted.entity_hex]
            + list(profile.preview_swatches)
            + [profile.recessive_control_hex]
        )
    )
    entity_swatches: dict[str, list[str]] = {}
    inspector_swatches: dict[str, list[dict[str, Any]]] = {}
    for ent in scene.entities.values():
        others = [
            (other.label, hex_to_srgb01(sculpted.entity_hex[oid]))
            for oid, other in scene.entities.items()
            if oid != ent.entity_id
            and other.label.strip().lower() != ent.label.strip().lower()
            and (solved.collision_scope == "global_strict" or bool(set(ent.panels) & set(other.panels)))
        ]
        if not others:
            items = [{"hex": sw, "min_de": 99.0, "too_close_to": None} for sw in swatch_pool]
        else:
            o_labels = [x[0] for x in others]
            o_arr = np.stack([x[1] for x in others], axis=0)
            sw_arr = np.stack([hex_to_srgb01(sw) for sw in swatch_pool], axis=0)
            d_mat = ciede2000_matrix(sw_arr, o_arr)
            items = []
            for s_i, sw in enumerate(swatch_pool):
                min_idx = int(np.argmin(d_mat[s_i]))
                min_d = float(d_mat[s_i, min_idx])
                items.append(
                    {
                        "hex": sw,
                        "min_de": round(min_d, 1),
                        "too_close_to": o_labels[min_idx] if min_d < 10.0 else None,
                    }
                )
            items.sort(key=lambda it: float(it["min_de"]), reverse=True)
        inspector_swatches[ent.entity_id] = items
        entity_swatches[ent.entity_id] = [it["hex"] for it in items]

    merged_diag = dict(solved.diagnostics)
    merged_diag.update(sculpted.diagnostics)
    return SolveResult(
        palette_id=solved.palette_id,
        collision_scope=solved.collision_scope,
        vibrancy=solved.vibrancy,
        entity_hex=sculpted.entity_hex,
        group_hex=sculpted.group_hex,
        scale_stops=sculpted.scale_stops,
        entity_swatches=entity_swatches,
        inspector_swatches=inspector_swatches,
        diagnostics=merged_diag,
    )


def export_styled_figure(
    scene: ParsedPdfScene | SvgScene,
    style: str | StyleProfile,
    *,
    palette_id: str | None = None,
    collision_scope: CollisionScope = "panel_scoped",
    vibrancy: VibrancyMode = "standard",
    min_de_target: float = 9.0,
    verify: bool = True,
) -> tuple[bytes, dict[str, Any], StyleSculptResult]:
    """One-call helper: optionally assign `palette_id`, sculpt with `style`, and export byte-verified PDF/SVG."""
    if palette_id is not None:
        sr = solve_scene_colors(
            scene.entities,
            scene.continuous_scales,
            scene.evidence_regions,
            style_id=palette_id,
            collision_scope=collision_scope,
            vibrancy=vibrancy,
        )
        sculpted = sculpt_scene_style(
            scene,
            style,
            entity_hex=sr.entity_hex,
            group_hex=sr.group_hex,
            scale_stops=sr.scale_stops,
            collision_scope=sr.collision_scope,
            min_de_target=min_de_target,
        )
    else:
        sculpted = sculpt_scene_style(
            scene,
            style,
            collision_scope=collision_scope,
            min_de_target=min_de_target,
        )

    if isinstance(scene, ParsedPdfScene):
        out_bytes, audit = export_recolored_pdf(
            scene,
            sculpted.group_hex,
            sculpted.scale_stops,
            verify=verify,
        )
    else:
        out_bytes, audit = export_recolored_svg(
            scene,
            sculpted.group_hex,
            sculpted.scale_stops,
        )
    return out_bytes, audit, sculpted
