---
name: danqing
description: Recolor existing vector scientific figures (PDF or SVG from R/ggplot2, Python/matplotlib, GraphPad Prism, or Illustrator) using verified accessible, journal-inspired, museum, and CC0 Eastern artifact palettes without modifying geometry, text, or raw experimental images (Western blots, H&E, microscopy). Includes interactive Web Studio (`http://127.0.0.1:8765`) and Python programmatic API.
---

# Danqing (丹青) — Scientific Figure Recoloring Skill

Use this skill whenever the user wants to:
1. Recolor an existing scientific PDF or SVG figure without re-running upstream plotting scripts.
2. Preview or compare color-blind safe, journal-inspired, museum (`MetBrewer`), or CC0 Eastern museum artifact palettes on multi-panel figures.
3. Emphasize (`focus`), de-emphasize (`background`), or lock specific categories while keeping raw experimental images (blots, H&E, fluorescence crops) untouched.
4. Export byte-verified vector PDF/SVG figures alongside reusable `ggplot2` (R) and `matplotlib` (Python) palette code.

## Interactive Web Studio

Start the local studio server:

```bash
./scripts/start_studio.sh
```

Open `http://127.0.0.1:8765` in a desktop browser (`≥ 1024 px`).

## Programmatic Python Usage

```python
from pathlib import Path
from danqing.pdf_engine import parse_pdf_scene, export_recolored_pdf
from danqing.solver import solve_scene_colors
from danqing.exporter import generate_r_ggplot_snippet, generate_python_mpl_snippet

raw_pdf = Path("figure.pdf").read_bytes()
scene = parse_pdf_scene(raw_pdf, "figure.pdf", "fig1", page_index=0)

# Optional: set an element to focus or lock a custom hex color
for ent in scene.entities.values():
    if ent.label == "Gentoo":
        ent.tier = "focus"

result = solve_scene_colors(
    scene.entities,
    scene.continuous_scales,
    scene.evidence_regions,
    style_id="east_ru_celadon",          # or "okabe_ito", "npg_inspired", "met_hiroshige", etc.
    collision_scope="panel_scoped",      # "panel_scoped" (Same name, same color) or "global_strict" (Every element unique)
    vibrancy="standard",                 # "muted" | "standard" | "vivid"
)

out_pdf, audit = export_recolored_pdf(scene, result.group_hex, result.scale_stops, verify=True)
assert audit["g6_geometry_identical"] and audit["g0_evidence_bit_identical"]
Path("figure_danqing.pdf").write_bytes(out_pdf)
```
