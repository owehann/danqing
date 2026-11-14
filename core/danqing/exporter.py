"""Code snippet, CSV change report, and JSON export builders for Danqing (Spec Section 4.8)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from .ir import ContinuousScale, EvidenceRegion, SemanticEntity
from .palettes import get_palette
from .solver import normalize_role


def generate_r_ggplot_snippet(
    style_id: str,
    entities: dict[str, SemanticEntity],
    entity_hex: dict[str, str],
    continuous_scales: dict[str, ContinuousScale],
    scale_stops: dict[str, list[str]],
) -> str:
    pal = get_palette(style_id)
    src_title = pal.source.get("title", pal.name_en)
    lines = [
        f"# Danqing Palette: {pal.name_en} ({pal.id})",
        f"# Source: {src_title}",
        "danqing_palette <- c(",
    ]
    items: list[str] = []
    seen: set[str] = set()
    for ent in entities.values():
        key = ent.label.replace('"', '\\"')
        if key in seen:
            continue
        seen.add(key)
        items.append(f'  "{key}" = "{entity_hex.get(ent.entity_id, ent.current_hex)}"')
    lines.append(",\n".join(items))
    lines.append(")\n")
    lines.append("scale_fill_danqing  <- function(...) ggplot2::scale_fill_manual(values = danqing_palette, ...)")
    lines.append("scale_color_danqing <- function(...) ggplot2::scale_colour_manual(values = danqing_palette, ...)")

    for sid, cs in continuous_scales.items():
        stops = list(scale_stops.get(sid, cs.current_stops_hex))
        if cs.inverted_polarity:
            stops = list(reversed(stops))
        quoted = ", ".join(f'"{h}"' for h in stops)
        lines.append(f"\n# Continuous scale: {cs.title} ({cs.panel_id})")
        lines.append(f"danqing_{sid}_ramp <- c({quoted})")
        lines.append(
            f"scale_fill_{sid} <- function(...) ggplot2::scale_fill_gradientn(colours = danqing_{sid}_ramp, ...)"
        )
    return "\n".join(lines) + "\n"


def generate_python_mpl_snippet(
    style_id: str,
    entities: dict[str, SemanticEntity],
    entity_hex: dict[str, str],
    continuous_scales: dict[str, ContinuousScale],
    scale_stops: dict[str, list[str]],
) -> str:
    pal = get_palette(style_id)
    lines = [
        f"# Danqing Palette: {pal.name_en} ({pal.id})",
        "from matplotlib.colors import LinearSegmentedColormap",
        "",
        "DANQING_PALETTE = {",
    ]
    seen: set[str] = set()
    for ent in entities.values():
        if ent.label in seen:
            continue
        seen.add(ent.label)
        lines.append(f"    {ent.label!r}: {entity_hex.get(ent.entity_id, ent.current_hex)!r},")
    lines.append("}")

    for sid, cs in continuous_scales.items():
        stops = list(scale_stops.get(sid, cs.current_stops_hex))
        if cs.inverted_polarity:
            stops = list(reversed(stops))
        lines.append(
            f"\nDANQING_{sid.upper()}_CMAP = LinearSegmentedColormap.from_list({cs.title!r}, {stops!r}, N=256)"
        )
    return "\n".join(lines) + "\n"


def generate_change_report_csv(
    entities: dict[str, SemanticEntity],
    entity_hex: dict[str, str],
) -> str:
    """Build CSV report with columns `element,panels,original_hex,new_hex,role` (Spec Section 4.8)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["element", "panels", "original_hex", "new_hex", "role"])
    for ent in entities.values():
        writer.writerow(
            [
                ent.label,
                "; ".join(ent.panels),
                ent.original_hex,
                entity_hex.get(ent.entity_id, ent.current_hex),
                normalize_role(ent.tier),
            ]
        )
    return buf.getvalue()


def build_verification_certificate(
    filename: str,
    style_id: str,
    collision_scope: str,
    entities: dict[str, SemanticEntity],
    entity_hex: dict[str, str],
    continuous_scales: dict[str, ContinuousScale],
    scale_stops: dict[str, list[str]],
    evidence_regions: list[EvidenceRegion],
    gates_summary: dict[str, Any],
    export_audit: dict[str, Any],
) -> dict[str, Any]:
    pal = get_palette(style_id)
    shapes_unchanged = bool(export_audit.get("g6_geometry_identical", False))
    raw_images_untouched = bool(export_audit.get("g0_evidence_bit_identical", True))
    cb_deutan_safe = bool(gates_summary.get("colorblind_deutan_safe", gates_summary.get("min_de2000_deutan", 0.0) >= 8.0))

    return {
        "schema": "danqing.export_manifest.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": filename,
        "palette": {
            "id": pal.id,
            "name": {"en": pal.name_en, "zh": pal.name_zh},
            "collection": pal.collection,
            "source": pal.source,
            "artifact": pal.artifact,
        },
        "rule": "every_element_unique" if collision_scope == "global_strict" else "same_name_same_color",
        "checks": {
            "shapes_and_text_unchanged": shapes_unchanged,
            "raw_images_untouched": raw_images_untouched,
            "protected_image_count": sum(
                1 for ev in evidence_regions if ev.mutability in ("class0_sacrosanct_evidence", "class1_fluorescence_lut")
            ),
            "colorblind_safe_deuteranopia": cb_deutan_safe,
            "min_de2000_normal": gates_summary.get("min_de2000_normal"),
            "min_de2000_deuteranopia": gates_summary.get("min_de2000_deutan"),
            "min_de2000_protanopia": gates_summary.get("min_de2000_protan"),
            "generated_colors": gates_summary.get("generated_count", 0),
        },
        "integrity_gates": {
            "G0_raw_evidence_shield": {
                "status": "PASS" if raw_images_untouched else "FAIL",
                "protected_regions": [
                    {
                        "region_id": ev.region_id,
                        "panel_id": ev.panel_id,
                        "subtype": ev.subtype_label,
                        "sha256": ev.sha256_original,
                    }
                    for ev in evidence_regions
                ],
                "verified_bit_identical_locks": export_audit.get("g0_locked_objects", []),
            },
            "G6_canonical_geometry_invariance": {
                "status": "PASS" if shapes_unchanged else "FAIL",
                "sha256_non_color_ast_before": export_audit.get("g6_geometry_hash_before", ""),
                "sha256_non_color_ast_after": export_audit.get("g6_geometry_hash_after", ""),
                "modified_vector_color_ops": export_audit.get("modified_vector_ops", 0),
                "modified_coupled_colorbar_rasters": export_audit.get("modified_colorbar_rasters", 0),
            },
        },
        "elements": [
            {
                "id": e.entity_id,
                "name": e.label,
                "panels": e.panels,
                "role": normalize_role(e.tier),
                "locked": e.locked,
                "original_hex": e.original_hex,
                "new_hex": entity_hex.get(e.entity_id, e.current_hex),
            }
            for e in entities.values()
        ],
        "continuous_scales": [
            {
                "id": sid,
                "panel": cs.panel_id,
                "name": cs.title,
                "kind": cs.kind,
                "original_stops": cs.original_stops_hex,
                "new_stops": scale_stops.get(sid, cs.current_stops_hex),
                "inverted_polarity": cs.inverted_polarity,
            }
            for sid, cs in continuous_scales.items()
        ],
    }
