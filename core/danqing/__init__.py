"""Danqing (丹青) — Semantic & Artifact-Inspired Color Engine for Scientific Figures.

License: Apache-2.0
"""

from .style_engine import (
    STYLE_PROFILES,
    StyleProfile,
    StyleSculptResult,
    apply_style_to_solve_result,
    export_styled_figure,
    extract_style_profile,
    get_style,
    list_styles,
    sculpt_continuous_stops,
    sculpt_scene_style,
)

__version__ = "0.6.2"

__all__ = [
    "STYLE_PROFILES",
    "StyleProfile",
    "StyleSculptResult",
    "__version__",
    "apply_style_to_solve_result",
    "export_styled_figure",
    "extract_style_profile",
    "get_style",
    "list_styles",
    "sculpt_continuous_stops",
    "sculpt_scene_style",
]
