---
name: danqing
description: >-
  Losslessly recolor finished scientific vector figures (.pdf or .svg from R/ggplot2,
  Python/matplotlib/scanpy, GraphPad Prism, or Illustrator) and match whole manuscript
  figure sets to comfortable, reviewer-safe palettes without re-running plotting scripts
  or altering raw experimental images (Western blots, H&E, microscopy). Includes 3,406
  verified palettes (with homologous paired sequential/diverging ramps), Manuscript Match
  (Gemini + perceptual comfort ranker), MCP server (`danqing_mcp`), and interactive Web Studio.
---

# Danqing (丹青) — Scientific Figure & Manuscript Recoloring Skill

**Author**: Xinyin Han (`@owehann`) · **License**: Apache-2.0

Use this skill whenever a researcher wants to stop wasting time tweaking hex codes and:
1. **Match a manuscript's tone (`Manuscript Match` / `论文配色定调`)**: Recommend 3 visually comfortable, eye-friendly, reviewer-safe palettes tailored to a target journal (*Nature / Science / Cell*, *NEJM / Lancet / JAMA*, single-cell omics, or museum mineral glazes).
2. **Recolor finished PDF or SVG figures losslessly**: Replace colors across multi-panel vector figures without re-running upstream R/Python code while keeping raw experimental images (Western blots, H&E, immunofluorescence) bit-identical.
3. **Unify multi-figure manuscripts**: Enforce `same_name` color consistency across Panels A–F or across Figure 1–Figure 6, and export ready-to-paste `ggplot2` (`.R`) and `matplotlib` (`.py`) code snippets.

## 1. MCP Tools (`danqing_mcp`)

When the `danqing_mcp` MCP server is enabled (`danqing-mcp` or `python -m danqing.mcp_server`), prefer calling its deterministic tools directly:
- `danqing_inspect_figure`: Inspect discrete groups, panels, continuous scales, protected raw images, and deuteranopia diagnostics on any `.pdf` or `.svg`.
- `danqing_match_manuscript_palettes`: Get the top 3 comfortable palette matches for a figure + journal/topic brief (`preset`: `"cns_clean"`, `"clinical"`, `"omics"`, `"museum"`).
- `danqing_recolor_figure`: Write a byte-verified recolored `.pdf`/`.svg` alongside `.palette.R`, `.palette.py`, and `.changes.csv`.
- `danqing_list_palettes`: Search the 3,406 verified palettes by collection, group count, or color-blind safety.

## 2. Interactive Web Studio

- **24/7 Cloud Studio**: `https://danqing.onrender.com`
- **Local Studio**:
  ```bash
  ./scripts/start_studio.sh
  ```
  Then open `http://127.0.0.1:8765` (use **Manuscript Match / 论文配色定调** in the right sidebar to pick a comfortable tone in one click).

## 3. Programmatic Python API

```python
from pathlib import Path
from danqing.manuscript_matcher import match_manuscript_palettes
from danqing.pdf_engine import parse_pdf_scene, export_recolored_pdf
from danqing.solver import solve_scene_colors

scene = parse_pdf_scene(Path("figure.pdf").read_bytes(), "figure.pdf", "fig1", page_index=0)

# 1. Recommend 3 comfortable palettes for the manuscript
recs = match_manuscript_palettes(
    required_k=len(scene.entities),
    has_continuous=bool(scene.continuous_scales),
    preset="cns_clean",
    brief="Nature Medicine tumor immunology",
)
best_palette_id = recs["recommendations"][0]["palette_id"]

# 2. Recolor losslessly with geometry & raw-image verification
solved = solve_scene_colors(
    scene.entities,
    scene.continuous_scales,
    scene.evidence_regions,
    style_id=best_palette_id,
    collision_scope="panel_scoped",
)
out_pdf, audit = export_recolored_pdf(scene, solved.group_hex, solved.scale_stops, verify=True)
assert audit["g6_geometry_identical"] and audit["g0_evidence_bit_identical"]
Path("figure_danqing.pdf").write_bytes(out_pdf)
```
