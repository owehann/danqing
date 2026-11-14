"""Verified scientific, museum, and CC0 Eastern artifact palette library (WP1 & WP2)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from ..color_science import (
    ciede2000_matrix,
    hex_to_oklch,
    hex_to_srgb01,
    linear_to_srgb,
    oklab_to_linear_unclipped,
    oklch_to_hex,
    oklch_to_oklab,
    srgb01_to_hex,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_PALETTE_ID = "okabe_ito"

COLLECTION_ORDER = (
    "accessible",
    "journal",
    "museum",
    "eastern",
    "many",
    "continuous",
    "convention",
)


@dataclass(frozen=True)
class PaletteDefinition:
    id: str
    name_en: str
    name_zh: str
    collection: str
    kind: str  # qualitative | sequential | diverging
    order: str  # discrete | gradient
    colors: tuple[str, ...]
    neutral: str
    partner_sequential: str
    partner_diverging: str
    source: dict[str, Any]
    artifact: dict[str, Any] | None = None
    qc: dict[str, Any] = field(default_factory=dict)
    dynamic_generator: str | None = None
    convention_keys: tuple[str, ...] = ()

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": {"en": self.name_en, "zh": self.name_zh},
            "collection": self.collection,
            "kind": self.kind,
            "order": self.order,
            "colors": list(self.colors),
            "neutral": self.neutral,
            "partners": {
                "sequential": self.partner_sequential,
                "diverging": self.partner_diverging,
            },
            "source": self.source,
            "artifact": self.artifact,
            "qc": self.qc,
            "dynamic_generator": self.dynamic_generator,
            "convention_keys": list(self.convention_keys),
        }


def _parse_palette_json(raw: dict[str, Any]) -> PaletteDefinition:
    partners = raw.get("partners") or {}
    return PaletteDefinition(
        id=str(raw["id"]),
        name_en=str(raw["name"]["en"]),
        name_zh=str(raw["name"]["zh"]),
        collection=str(raw["collection"]),
        kind=str(raw.get("kind", "qualitative")),
        order=str(raw.get("order", "discrete")),
        colors=tuple(str(c).upper() for c in raw["colors"]),
        neutral=str(raw.get("neutral") or "#BDBDBD").upper(),
        partner_sequential=str(partners.get("sequential") or "viridis"),
        partner_diverging=str(partners.get("diverging") or "vik"),
        source=dict(raw.get("source") or {}),
        artifact=dict(raw["artifact"]) if raw.get("artifact") else None,
        qc=dict(raw.get("qc") or {}),
        dynamic_generator=raw.get("dynamic_generator"),
        convention_keys=tuple(raw.get("convention_keys") or ()),
    )


@lru_cache(maxsize=1)
def _load_all_cached() -> dict[str, PaletteDefinition]:
    items: list[PaletteDefinition] = []
    for fp in sorted(DATA_DIR.glob("*.json")):
        raw = json.loads(fp.read_text(encoding="utf-8"))
        items.append(_parse_palette_json(raw))
    col_rank = {c: idx for idx, c in enumerate(COLLECTION_ORDER)}
    items.sort(key=lambda p: (col_rank.get(p.collection, 99), p.id))
    return {p.id: p for p in items}


def list_palettes(include_conventions: bool = False) -> list[PaletteDefinition]:
    all_pals = list(_load_all_cached().values())
    if include_conventions:
        return all_pals
    return [p for p in all_pals if p.collection != "convention"]


def get_palette(palette_id: str) -> PaletteDefinition:
    catalog = _load_all_cached()
    if palette_id in catalog:
        return catalog[palette_id]
    return catalog[DEFAULT_PALETTE_ID]


def apply_vibrancy(hex_colors: list[str] | tuple[str, ...], vibrancy: str = "standard") -> list[str]:
    """Scale chroma uniformly in OKLCH (`muted`, `standard`, `vivid`) while keeping achromatic neutrals intact."""
    if vibrancy == "standard" or not vibrancy:
        return [c.upper() for c in hex_colors]
    c_mul = 0.72 if vibrancy == "muted" else (1.24 if vibrancy == "vivid" else 1.0)
    out: list[str] = []
    for hx in hex_colors:
        L, C, h = hex_to_oklch(hx)
        if C < 0.015:
            out.append(hx.upper())
        else:
            out.append(oklch_to_hex(L, float(np.clip(C * c_mul, 0.02, 0.24)), h))
    return out


def expand_glasbey_in_hull(seed_hexes: list[str], total_k: int) -> list[str]:
    """Greedily generate additional colors within the palette's OKLCH range maximizing min ΔE2000 (< 3 ms vectorized)."""
    if total_k <= len(seed_hexes):
        return list(seed_hexes[:total_k])

    # Prune near-duplicate gradient twins (< 9.0 ΔE2000) from seeds when expanding to large K
    filtered_seeds: list[str] = []
    filtered_rgbs: list[np.ndarray] = []
    for hx in seed_hexes:
        rgb = hex_to_srgb01(hx)
        if not filtered_rgbs:
            filtered_seeds.append(hx.upper())
            filtered_rgbs.append(rgb)
        else:
            d = float(ciede2000_matrix(rgb[None, :], np.stack(filtered_rgbs, axis=0)).min())
            if d >= 9.0:
                filtered_seeds.append(hx.upper())
                filtered_rgbs.append(rgb)

    lch_seeds = [hex_to_oklch(c) for c in filtered_seeds if hex_to_oklch(c)[1] >= 0.018]
    if lch_seeds:
        l_min = float(max(0.26, min(x[0] for x in lch_seeds) - 0.14))
        l_max = float(min(0.84, max(x[0] for x in lch_seeds) + 0.14))
        c_min = float(max(0.042, min(x[1] for x in lch_seeds) * 0.72))
        c_max = float(min(0.210, max(x[1] for x in lch_seeds) * 1.25))
    else:
        l_min, l_max, c_min, c_max = 0.28, 0.82, 0.05, 0.19

    Ls = np.linspace(l_min, l_max, 11)
    Cs = np.linspace(c_min, c_max, 6)
    hs = np.linspace(0.0, 360.0, 40, endpoint=False)
    gL, gC, gh = np.meshgrid(Ls, Cs, hs, indexing="ij")
    lch_grid = np.stack([gL.ravel(), gC.ravel(), gh.ravel()], axis=-1)
    lin_rgb = oklab_to_linear_unclipped(oklch_to_oklab(lch_grid))
    in_gamut = (lin_rgb >= -0.015).all(axis=1) & (lin_rgb <= 1.015).all(axis=1)
    cand_arr = linear_to_srgb(np.clip(lin_rgb[in_gamut], 0.0, 1.0))

    white = np.array([[1.0, 1.0, 1.0]], dtype=np.float64)
    d_white = ciede2000_matrix(cand_arr, white)[:, 0]
    keep = d_white >= 14.5
    if int(keep.sum()) >= (total_k - len(filtered_seeds)):
        cand_arr = cand_arr[keep]

    selected = list(filtered_seeds)
    sel_arr = np.stack(filtered_rgbs, axis=0)
    min_dists = ciede2000_matrix(cand_arr, sel_arr).min(axis=1)

    while len(selected) < total_k and len(cand_arr) > 0:
        best_i = int(np.argmax(min_dists))
        nxt_rgb = cand_arr[best_i]
        nxt_hex = srgb01_to_hex(nxt_rgb)
        if nxt_hex not in selected:
            selected.append(nxt_hex)
        d_new = ciede2000_matrix(cand_arr, nxt_rgb[None, :])[:, 0]
        min_dists = np.minimum(min_dists, d_new)
        min_dists[best_i] = -1.0

    return selected[:total_k]
