#!/usr/bin/env python3
"""Build the WP4/Section 11.1 34-figure benchmark corpus in `bench/corpus/` + `MANIFEST.json` + WP4 coverage report.

Covers:
- Tools: ggplot2 (cairo_pdf & svglite CSS), matplotlib (PDF & SVG <use>), seaborn-style, GraphPad Prism (CMYK & ICCBased),
  Adobe Illustrator (nested /Form + /Separation + .stX SVG), Inkscape (layered inline style), BioRender-style pathway SVG,
  and Excel-style (/Indexed CS + bottom legend) PDF.
- Chart types: bar, boxplot, violin, UMAP/scatter (>= 22 classes), heatmap (sequential & diverging), volcano,
  GWAS Manhattan, SBS-6 rainfall, oncology waterfall, Kaplan-Meier survival, network graph, signaling pathway,
  multi-panel wet-lab WB/H&E/IF, multi-page PDF, and scanned raster-only PDF.
- Strictly deterministic closed-form geometry (zero RNG calls).
"""

from __future__ import annotations

import io
import json
import math
import shutil
import sys
import zlib
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pikepdf
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core"))

from danqing.pdf_engine import parse_pdf_scene  # noqa: E402
from danqing.svg_engine import parse_svg_scene  # noqa: E402

BENCH_FIGS = REPO / "bench" / "figures"
CORPUS_DIR = REPO / "bench" / "corpus"

plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["svg.fonttype"] = "none"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Helvetica"]


def _save_mpl(fig: plt.Figure, out_path: Path) -> None:
    fmt = out_path.suffix.lstrip(".").lower()
    fig.savefig(out_path, format=fmt, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _gen_mpl_figures() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    # c05 & c06: Grouped bar (PDF & SVG)
    for cid, ext in (("c05_mpl_grouped_bar", "pdf"), ("c06_mpl_grouped_bar", "svg")):
        fig, ax = plt.subplots(figsize=(6.2, 3.8))
        x = np.arange(4)
        arms = [("Vehicle", "#F8766D", [1.0, 1.2, 0.9, 1.1]), ("Cisplatin", "#7CAE00", [1.8, 2.1, 1.6, 1.9]),
                ("Olaparib", "#00BFC4", [1.5, 1.7, 1.4, 1.6]), ("Dual_Regimen", "#C77CFF", [3.1, 3.5, 2.9, 3.3])]
        for i, (lbl, col, vals) in enumerate(arms):
            ax.bar(x + (i - 1.5) * 0.18, vals, width=0.17, color=col, label=lbl)
        ax.set_xticks(x, ["Day 7", "Day 14", "Day 21", "Day 28"])
        ax.set_ylabel("Fold response")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
        fp = CORPUS_DIR / f"{cid}.{ext}"
        _save_mpl(fig, fp)
        entries.append({"id": cid, "filename": fp.name, "tool": f"matplotlib_{ext}", "chart_type": "bar", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c07: Boxplot (PDF)
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    groups = [("Ctrl", "#E41A1C"), ("LowDose", "#377EB8"), ("MidDose", "#4DAF4A"), ("HighDose", "#984EA3"), ("Rescue", "#FF7F00")]
    data = [[1.2 + 0.35 * i + 0.4 * math.sin(k * 0.7 + i) for k in range(18)] for i in range(5)]
    bp = ax.boxplot(data, patch_artist=True, tick_labels=[g[0] for g in groups], widths=0.52)
    handles = []
    for patch, (lbl, col) in zip(bp["boxes"], groups):
        patch.set_facecolor(col)
        patch.set_edgecolor("#222222")
        handles.append(plt.Rectangle((0, 0), 1, 1, facecolor=col, label=lbl))
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
    ax.set_ylabel("Normalized score")
    fp = CORPUS_DIR / "c07_mpl_boxplot_arms.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c07_mpl_boxplot_arms", "filename": fp.name, "tool": "matplotlib_pdf", "chart_type": "boxplot", "has_legend": True, "expected_labeled": 5, "license": "CC0-1.0"})

    # c08: Violin (SVG)
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    v_groups = [("G1_Quiescent", "#66C2A5"), ("G2_Cycling", "#FC8D62"), ("G3_Stress", "#8DA0CB"), ("G4_Effector", "#E78AC3")]
    v_data = [[2.0 + 0.5 * i + 0.6 * math.cos(k * 0.45 + i) for k in range(28)] for i in range(4)]
    vp = ax.violinplot(v_data, positions=[1, 2, 3, 4], showextrema=False, widths=0.65)
    v_handles = []
    for body, (lbl, col) in zip(vp["bodies"], v_groups):
        body.set_facecolor(col)
        body.set_alpha(0.82)
        v_handles.append(plt.Rectangle((0, 0), 1, 1, facecolor=col, label=lbl))
    ax.set_xticks([1, 2, 3, 4], [g[0] for g in v_groups])
    ax.legend(handles=v_handles, loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
    fp = CORPUS_DIR / "c08_mpl_violin_distribution.svg"
    _save_mpl(fig, fp)
    entries.append({"id": "c08_mpl_violin_distribution", "filename": fp.name, "tool": "matplotlib_svg", "chart_type": "violin", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c09 & c10: 22-cluster PDF & 24-cluster SVG UMAP (>= 20 classes + hierarchical names + <use> markers)
    umap_names_24 = [
        "CD4_Naive", "CD4_Treg", "CD4_Th1", "CD8_Naive", "CD8_Tem", "CD8_Tex",
        "NK_Dim", "NK_Bright", "B_Naive", "B_Memory", "Plasma_IgG", "Plasma_IgA",
        "Mono_Classical", "Mono_Patrol", "Mac_Kupffer", "Mac_SPP1", "DC_cDC1", "DC_cDC2",
        "Fib_Portal", "Fib_Myofib", "Endo_LSEC", "Endo_Arterial", "Hep_Periportal", "Hep_Pericentral",
    ]
    cmap24 = [
        "#1F77B4", "#AEC7E8", "#FF7F0E", "#FFBB78", "#2CA02C", "#98DF8A",
        "#D62728", "#FF9896", "#9467BD", "#C5B0D5", "#8C564B", "#C49C94",
        "#E377C2", "#F7B6D2", "#17BECF", "#9EDAE5", "#BCBD22", "#DBDB8D",
        "#393B79", "#637939", "#8C6D31", "#843C39", "#7B4173", "#3182BD",
    ]
    for cid, ext, n_cls in (("c09_mpl_umap_22clusters", "pdf", 22), ("c10_mpl_umap_24clusters", "svg", 24)):
        fig, ax = plt.subplots(figsize=(8.4, 5.4))
        for ci in range(n_cls):
            ang = 2.0 * math.pi * ci / n_cls
            cx = (5.0 + 2.2 * (ci % 2)) * math.cos(ang)
            cy = (5.0 + 2.2 * (ci % 2)) * math.sin(ang)
            pts_x = [cx + 0.42 * math.cos(k * 1.1 + ci) for k in range(14)]
            pts_y = [cy + 0.42 * math.sin(k * 1.3 + ci) for k in range(14)]
            ax.scatter(pts_x, pts_y, s=18, color=cmap24[ci], label=umap_names_24[ci], edgecolors="none")
        ax.set_xlabel("UMAP 1")
        ax.set_ylabel("UMAP 2")
        ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), ncol=2, frameon=False, fontsize=8, markerscale=1.3)
        fp = CORPUS_DIR / f"{cid}.{ext}"
        _save_mpl(fig, fp)
        entries.append({"id": cid, "filename": fp.name, "tool": f"matplotlib_{ext}", "chart_type": "umap_scatter_20plus", "has_legend": True, "expected_labeled": n_cls, "license": "CC0-1.0"})

    # c11: Sequential Heatmap with colorbar (PDF)
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    yy, xx = np.mgrid[0:6, 0:6]
    mat = 0.5 + 0.5 * np.sin(xx * 0.65 + yy * 0.45)
    im = ax.imshow(mat, cmap="YlOrRd", aspect="auto")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("Module score")
    ax.set_xticks(range(6), [f"S{i+1}" for i in range(6)])
    ax.set_yticks(range(6), [f"Path_{i+1}" for i in range(6)])
    fp = CORPUS_DIR / "c11_mpl_heatmap_colorbar.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c11_mpl_heatmap_colorbar", "filename": fp.name, "tool": "matplotlib_pdf", "chart_type": "heatmap", "has_legend": False, "expected_labeled": 0, "license": "CC0-1.0"})

    # c12 & c13: Volcano plot (PDF & SVG)
    for cid, ext in (("c12_mpl_volcano_deg", "pdf"), ("c13_mpl_volcano_deg", "svg")):
        fig, ax = plt.subplots(figsize=(5.8, 4.0))
        xs_up = [1.4 + 0.15 * k for k in range(16)]
        ys_up = [2.2 + 0.25 * (k % 7) + 0.1 * k for k in range(16)]
        xs_dn = [-1.4 - 0.14 * k for k in range(15)]
        ys_dn = [2.0 + 0.28 * (k % 6) + 0.08 * k for k in range(15)]
        xs_ns = [-0.9 + 0.08 * k for k in range(24)]
        ys_ns = [0.3 + 0.06 * (k % 9) for k in range(24)]
        ax.scatter(xs_ns, ys_ns, s=20, color="#B0B7C0", label="NS")
        ax.scatter(xs_dn, ys_dn, s=24, color="#2B6CB0", label="Down-regulated")
        ax.scatter(xs_up, ys_up, s=24, color="#E53E3E", label="Up-regulated")
        ax.set_xlabel("log2 Fold Change")
        ax.set_ylabel("-log10(FDR)")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
        fp = CORPUS_DIR / f"{cid}.{ext}"
        _save_mpl(fig, fp)
        entries.append({"id": cid, "filename": fp.name, "tool": f"matplotlib_{ext}", "chart_type": "volcano", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c14: GWAS Manhattan plot (PDF)
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    chr_cols = ["#1D4E89", "#7DCFB6", "#F79256", "#9B5DE5"]
    for ch_i in range(8):
        pos = [ch_i * 20 + k * 1.4 for k in range(12)]
        pvals = [1.2 + 1.8 * abs(math.sin(k * 0.8 + ch_i)) + (4.2 if (ch_i == 3 and k == 6) else 0.0) for k in range(12)]
        lbl = f"Group_{(ch_i % 4) + 1}" if ch_i < 4 else None
        ax.scatter(pos, pvals, s=16, color=chr_cols[ch_i % 4], label=lbl)
    ax.axhline(5.0, color="#333333", linestyle="--", linewidth=0.8)
    ax.set_xlabel("Genomic position (Mb)")
    ax.set_ylabel("-log10(P)")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    fp = CORPUS_DIR / "c14_mpl_manhattan_gwas.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c14_mpl_manhattan_gwas", "filename": fp.name, "tool": "matplotlib_pdf", "chart_type": "manhattan", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c15: SBS-6 Kataegis Rainfall plot (PDF)
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    sbs_types = [("C>A", "#5AB4E5"), ("C>G", "#4A4A4A"), ("C>T", "#E63946"), ("T>A", "#A8A8A8"), ("T>C", "#8AC926"), ("T>G", "#F4A261")]
    for si, (mut, col) in enumerate(sbs_types):
        xs = [si * 12 + k * 5.2 for k in range(14)]
        ys = [2.4 + 1.4 * math.sin(k * 0.9 + si) - (1.3 if (si == 2 and 4 <= k <= 8) else 0.0) for k in range(14)]
        ax.scatter(xs, ys, s=22, color=col, label=mut)
    ax.set_xlabel("Ordered somatic variant index")
    ax.set_ylabel("log10 inter-mutation distance (bp)")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    fp = CORPUS_DIR / "c15_mpl_rainfall_sbs6.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c15_mpl_rainfall_sbs6", "filename": fp.name, "tool": "matplotlib_pdf", "chart_type": "rainfall", "has_legend": True, "expected_labeled": 6, "license": "CC0-1.0"})

    # c16: Oncology Waterfall response plot (PDF)
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    wf_specs = [
        ("PD", "#D95F02", [55, 42, 34, 26, 21]),
        ("SD", "#7570B3", [14, 8, 2, -5, -12, -18, -24]),
        ("PR", "#1B9E77", [-33, -41, -48, -56, -64, -72]),
        ("CR", "#E7298A", [-85, -92, -100, -100]),
    ]
    cursor = 0
    for resp_lbl, col, heights in wf_specs:
        xs = list(range(cursor, cursor + len(heights)))
        ax.bar(xs, heights, width=0.76, color=col, label=resp_lbl)
        cursor += len(heights)
    ax.axhline(0, color="#111111", linewidth=0.8)
    ax.set_ylabel("Best change from baseline (%)")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    fp = CORPUS_DIR / "c16_mpl_waterfall_response.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c16_mpl_waterfall_response", "filename": fp.name, "tool": "matplotlib_pdf", "chart_type": "waterfall", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c17 & c18: Kaplan-Meier survival curves (PDF & SVG)
    for cid, ext in (("c17_mpl_kaplan_meier", "pdf"), ("c18_mpl_kaplan_meier", "svg")):
        fig, ax = plt.subplots(figsize=(6.0, 3.8))
        t_pts = [0, 3, 6, 9, 12, 16, 20, 24]
        km_arms = [
            ("Placebo", "#E41A1C", [1.0, 0.86, 0.68, 0.48, 0.32, 0.18, 0.10, 0.05]),
            ("LowDose", "#377EB8", [1.0, 0.90, 0.78, 0.62, 0.48, 0.36, 0.26, 0.20]),
            ("MidDose", "#4DAF4A", [1.0, 0.92, 0.82, 0.70, 0.58, 0.46, 0.38, 0.32]),
            ("HighDose", "#984EA3", [1.0, 0.97, 0.93, 0.88, 0.83, 0.78, 0.75, 0.73]),
        ]
        for lbl, col, surv in km_arms:
            ax.step(t_pts, surv, where="post", linewidth=2.2, color=col, label=lbl)
        ax.set_ylim(0, 1.05)
        ax.set_xlabel("Months since randomization")
        ax.set_ylabel("Progression-free survival")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
        fp = CORPUS_DIR / f"{cid}.{ext}"
        _save_mpl(fig, fp)
        entries.append({"id": cid, "filename": fp.name, "tool": f"matplotlib_{ext}", "chart_type": "kaplan_meier", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c19: Network interactome graph (SVG)
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    modules = [("Receptor", "#E64B35"), ("Kinase", "#4DBBD5"), ("Adaptor", "#00A087"), ("TF_Core", "#3C5488"), ("Effector", "#F39B7F")]
    coords: list[tuple[float, float]] = []
    for mi in range(5):
        for ni in range(4):
            ang = 2 * math.pi * (mi * 4 + ni) / 20.0
            rad = 2.6 if ni % 2 == 0 else 1.7
            coords.append((rad * math.cos(ang), rad * math.sin(ang)))
    for i in range(len(coords)):
        j = (i + 3) % len(coords)
        ax.plot([coords[i][0], coords[j][0]], [coords[i][1], coords[j][1]], color="#CBD5E1", linewidth=0.9, zorder=1)
    for mi, (mlbl, mcol) in enumerate(modules):
        sub = coords[mi * 4 : (mi + 1) * 4]
        ax.scatter([p[0] for p in sub], [p[1] for p in sub], s=95, color=mcol, label=mlbl, zorder=3)
    ax.axis("off")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
    fp = CORPUS_DIR / "c19_mpl_network_interactome.svg"
    _save_mpl(fig, fp)
    entries.append({"id": "c19_mpl_network_interactome", "filename": fp.name, "tool": "matplotlib_svg", "chart_type": "network", "has_legend": True, "expected_labeled": 5, "license": "CC0-1.0"})

    # c20: Multi-panel with inconsistent same-name colors across Panel A & Panel B (PDF)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.2, 3.5))
    ax1.text(-0.18, 1.06, "A", transform=ax1.transAxes, fontsize=14, fontweight="bold")
    ax2.text(-0.18, 1.06, "B", transform=ax2.transAxes, fontsize=14, fontweight="bold")
    for idx_a, (lbl, col, v) in enumerate([("WT", "#E41A1C", 1.2), ("KO", "#377EB8", 2.6), ("Rescue", "#4DAF4A", 1.5)]):
        ax1.bar([idx_a], [v], width=0.55, color=col, label=lbl)
    ax1.legend(loc="upper right", frameon=False, fontsize=8)
    # Intentionally swapped colors in Panel B to trigger Spec 4.2 plain-language inconsistency notice
    for idx_b, (lbl, col, v) in enumerate([("WT", "#984EA3", 3.1), ("KO", "#FF7F00", 1.1), ("Rescue", "#A65628", 2.8)]):
        ax2.bar([idx_b], [v], width=0.55, color=col, label=lbl)
    ax2.legend(loc="upper right", frameon=False, fontsize=8)
    fp = CORPUS_DIR / "c20_mpl_multipanel_same_name.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c20_mpl_multipanel_same_name", "filename": fp.name, "tool": "matplotlib_pdf", "chart_type": "multipanel_bar", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c24: Seaborn-style diverging heatmap (PDF)
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    yy, xx = np.mgrid[0:7, 0:7]
    zmat = np.cos(xx * 0.7 - yy * 0.5) * 2.4
    im2 = ax.imshow(zmat, cmap="RdBu_r", vmin=-2.5, vmax=2.5, aspect="auto")
    cb2 = fig.colorbar(im2, ax=ax)
    cb2.set_label("Z-score")
    ax.set_xticks(range(7), [f"C{i+1}" for i in range(7)])
    ax.set_yticks(range(7), [f"Gene_{i+1}" for i in range(7)])
    fp = CORPUS_DIR / "c24_seaborn_clustermap_div.pdf"
    _save_mpl(fig, fp)
    entries.append({"id": "c24_seaborn_clustermap_div", "filename": fp.name, "tool": "seaborn_pdf", "chart_type": "heatmap_diverging", "has_legend": False, "expected_labeled": 0, "license": "CC0-1.0"})

    return entries


def _gen_tool_dialect_files() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    # c21: svglite CSS-class dodged bar SVG
    c21 = """<?xml version='1.0' encoding='UTF-8' ?>
<svg xmlns='http://www.w3.org/2000/svg' class='svglite' viewBox='0 0 520 300'>
  <defs>
    <style type='text/css'><![CDATA[
      .svglite line, .svglite polyline { fill: none; stroke: #333333; }
      .cls-adelie { fill: #F8766D; }
      .cls-chinstrap { fill: #00BA38; }
      .cls-gentoo { fill: #619CFF; }
    ]]></style>
  </defs>
  <rect width='100%' height='100%' style='fill: #FFFFFF;'/>
  <line x1='55' y1='250' x2='375' y2='250'/>
  <line x1='55' y1='35' x2='55' y2='250'/>
  <rect class='cls-adelie' x='75' y='150' width='26' height='100'/>
  <rect class='cls-chinstrap' x='105' y='115' width='26' height='135'/>
  <rect class='cls-gentoo' x='135' y='65' width='26' height='185'/>
  <rect class='cls-adelie' x='225' y='162' width='26' height='88'/>
  <rect class='cls-chinstrap' x='255' y='108' width='26' height='142'/>
  <rect class='cls-gentoo' x='285' y='52' width='26' height='198'/>
  <rect class='cls-adelie' x='402' y='92' width='14' height='14'/>
  <text x='424' y='103' font-size='11'>Adelie</text>
  <rect class='cls-chinstrap' x='402' y='116' width='14' height='14'/>
  <text x='424' y='127' font-size='11'>Chinstrap</text>
  <rect class='cls-gentoo' x='402' y='140' width='14' height='14'/>
  <text x='424' y='151' font-size='11'>Gentoo</text>
</svg>"""
    (CORPUS_DIR / "c21_svglite_css_dodged_bar.svg").write_text(c21, encoding="utf-8")
    entries.append({"id": "c21_svglite_css_dodged_bar", "filename": "c21_svglite_css_dodged_bar.svg", "tool": "ggplot2_svglite", "chart_type": "bar", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c22: svglite faceted stroke kinetics SVG
    c22 = """<?xml version='1.0' encoding='UTF-8' ?>
<svg xmlns='http://www.w3.org/2000/svg' class='svglite' viewBox='0 0 600 280'>
  <defs>
    <style type='text/css'><![CDATA[
      .st-wt { stroke: #E64B35; stroke-width: 2.5; fill: none; }
      .st-mut { stroke: #4DBBD5; stroke-width: 2.5; fill: none; }
      .st-ko { stroke: #00A087; stroke-width: 2.5; fill: none; }
    ]]></style>
  </defs>
  <rect width='600' height='280' fill='#FFFFFF'/>
  <text x='24' y='28' font-size='14' font-weight='bold'>A</text>
  <polyline class='st-wt' points='45,210 95,180 145,140 195,120'/>
  <polyline class='st-mut' points='45,215 95,155 145,95 195,65'/>
  <polyline class='st-ko' points='45,220 95,212 145,204 195,198'/>
  <text x='250' y='28' font-size='14' font-weight='bold'>B</text>
  <polyline class='st-wt' points='275,205 325,175 375,150 425,130'/>
  <polyline class='st-mut' points='275,210 325,140 375,85 425,55'/>
  <polyline class='st-ko' points='275,218 325,208 375,195 425,188'/>
  <line class='st-wt' x1='468' y1='95' x2='488' y2='95'/>
  <text x='496' y='99' font-size='11'>Wildtype</text>
  <line class='st-mut' x1='468' y1='120' x2='488' y2='120'/>
  <text x='496' y='124' font-size='11'>GainOfFunc</text>
  <line class='st-ko' x1='468' y1='145' x2='488' y2='145'/>
  <text x='496' y='149' font-size='11'>Knockout</text>
</svg>"""
    (CORPUS_DIR / "c22_svglite_faceted_lines.svg").write_text(c22, encoding="utf-8")
    entries.append({"id": "c22_svglite_faceted_lines", "filename": "c22_svglite_faceted_lines.svg", "tool": "ggplot2_svglite", "chart_type": "line_kinetics", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c23: seaborn joint scatter + KDE opacity SVG
    c23 = """<?xml version='1.0' encoding='UTF-8' ?>
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 480 340'>
  <rect width='480' height='340' fill='#FFFFFF'/>
  <polygon points='60,70 110,32 170,48 230,70' fill='#1F77B4' fill-opacity='0.35'/>
  <polygon points='130,70 190,26 255,38 310,70' fill='#FF7F0E' fill-opacity='0.35'/>
  <g fill='#1F77B4' fill-opacity='0.85'>
    <circle cx='105' cy='190' r='5'/><circle cx='128' cy='175' r='5'/><circle cx='146' cy='210' r='5'/><circle cx='162' cy='182' r='5'/>
    <circle cx='366' cy='116' r='5'/>
  </g>
  <g fill='#FF7F0E' fill-opacity='0.85'>
    <circle cx='215' cy='140' r='5'/><circle cx='238' cy='125' r='5'/><circle cx='252' cy='158' r='5'/><circle cx='274' cy='132' r='5'/>
    <circle cx='366' cy='142' r='5'/>
  </g>
  <text x='380' y='120' font-size='11'>Luminal_A</text>
  <text x='380' y='146' font-size='11'>Basal_Like</text>
</svg>"""
    (CORPUS_DIR / "c23_seaborn_joint_scatter.svg").write_text(c23, encoding="utf-8")
    entries.append({"id": "c23_seaborn_joint_scatter", "filename": "c23_seaborn_joint_scatter.svg", "tool": "seaborn_svg", "chart_type": "scatter_kde", "has_legend": True, "expected_labeled": 2, "license": "CC0-1.0"})

    # Helper to build clean valid single-page PDF with Type1 Helvetica text + arbitrary stream & resources
    def _make_dialect_pdf(filename: str, stream_bytes: bytes, extra_res: dict[str, Any] | None = None, size: tuple[int, int] = (500, 320)) -> None:
        pdf = pikepdf.Pdf.new()
        page = pdf.add_blank_page(page_size=size)
        font_dict = pikepdf.Dictionary({
            "/F1": pikepdf.Dictionary({"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")})
        })
        res = pikepdf.Dictionary({"/Font": font_dict})
        if extra_res:
            for rk, rv in extra_res.items():
                res[rk] = rv
        page.Resources = res
        page.Contents = pdf.make_stream(stream_bytes)
        pdf.save(str(CORPUS_DIR / filename))

    # c25: GraphPad Prism CMYK (`k` / `K`) PDF with legend
    c25_stream = (
        b"0 0 0 1 K 1 w 55 50 m 340 50 l S 55 50 m 55 270 l S "
        b"0.05 0.82 0.78 0.02 K 2.2 w 65 75 m 140 95 l 215 165 l 310 235 l S "
        b"0.05 0.82 0.78 0.02 k 370 210 12 12 re f "
        b"0.82 0.18 0.05 0.02 K 2.2 w 65 70 m 140 80 l 215 110 l 310 145 l S "
        b"0.82 0.18 0.05 0.02 k 370 184 12 12 re f "
        b"0.72 0.05 0.78 0.05 K 2.2 w 65 68 m 140 70 l 215 74 l 310 78 l S "
        b"0.72 0.05 0.78 0.05 k 370 158 12 12 re f "
        b"0 0 0 1 k BT /F1 11 Tf 390 212 Td (Agonist_WT) Tj ET "
        b"BT /F1 11 Tf 390 186 Td (Antagonist_M1) Tj ET "
        b"BT /F1 11 Tf 390 160 Td (Vehicle_DMSO) Tj ET"
    )
    _make_dialect_pdf("c25_prism_cmyk_dose_response.pdf", c25_stream)
    entries.append({"id": "c25_prism_cmyk_dose_response", "filename": "c25_prism_cmyk_dose_response.pdf", "tool": "graphpad_prism_pdf", "chart_type": "dose_response", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c26: GraphPad Prism ICCBased `/CS1 cs ... scn` grouped bar PDF
    pdf26 = pikepdf.Pdf.new()
    p26 = pdf26.add_blank_page(page_size=(500, 320))
    icc26 = pdf26.make_stream(zlib.compress(b"\x00" * 128))
    icc26["/N"] = 3
    icc26["/Alternate"] = pikepdf.Name("/DeviceRGB")
    p26.Resources = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": pikepdf.Dictionary({"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")})}),
        "/ColorSpace": pikepdf.Dictionary({"/CS1": pikepdf.Array([pikepdf.Name("/ICCBased"), icc26])}),
    })
    p26.Contents = pdf26.make_stream(
        b"/CS1 cs 0.88 0.32 0.28 scn 80 60 36 140 re f 365 210 12 12 re f "
        b"0.22 0.56 0.78 scn 130 60 36 185 re f 365 184 12 12 re f "
        b"0.28 0.72 0.48 scn 180 60 36 110 re f 365 158 12 12 re f "
        b"0 0 0 rg BT /F1 11 Tf 385 212 Td (Baseline) Tj ET "
        b"BT /F1 11 Tf 385 186 Td (Stimulated) Tj ET "
        b"BT /F1 11 Tf 385 160 Td (Inhibitor) Tj ET"
    )
    pdf26.save(str(CORPUS_DIR / "c26_prism_icc_grouped_bar.pdf"))
    entries.append({"id": "c26_prism_icc_grouped_bar", "filename": "c26_prism_icc_grouped_bar.pdf", "tool": "graphpad_prism_pdf", "chart_type": "bar", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c27: Adobe Illustrator nested `/Form` XObjects + `/Separation` + `/ICCBased` PDF
    pdf27 = pikepdf.Pdf.new()
    p27 = pdf27.add_blank_page(page_size=(520, 320))
    icc27 = pdf27.make_stream(zlib.compress(b"\x00" * 128))
    icc27["/N"] = 3
    icc27["/Alternate"] = pikepdf.Name("/DeviceRGB")
    tint_fn = pikepdf.Dictionary({
        "/FunctionType": 2,
        "/Domain": pikepdf.Array([0.0, 1.0]),
        "/C0": pikepdf.Array([1.0, 1.0, 1.0]),
        "/C1": pikepdf.Array([0.82, 0.24, 0.45]),
        "/N": 1.0,
    })
    cs27 = pikepdf.Dictionary({
        "/CS1": pikepdf.Array([pikepdf.Name("/ICCBased"), icc27]),
        "/CS2": pikepdf.Array([pikepdf.Name("/Separation"), pikepdf.Name("/SpotMagenta"), pikepdf.Name("/DeviceRGB"), tint_fn]),
    })
    fm_inner = pdf27.make_stream(b"q /CS2 cs 1.0 scn 90 70 42 155 re f 375 210 12 12 re f Q")
    fm_inner["/Type"] = pikepdf.Name("/XObject")
    fm_inner["/Subtype"] = pikepdf.Name("/Form")
    fm_inner["/BBox"] = pikepdf.Array([0, 0, 520, 320])
    fm_inner["/Resources"] = pikepdf.Dictionary({"/ColorSpace": cs27})

    fm_outer = pdf27.make_stream(b"q /FmInner Do /CS1 cs 0.20 0.62 0.58 scn 155 70 42 190 re f 375 184 12 12 re f Q")
    fm_outer["/Type"] = pikepdf.Name("/XObject")
    fm_outer["/Subtype"] = pikepdf.Name("/Form")
    fm_outer["/BBox"] = pikepdf.Array([0, 0, 520, 320])
    fm_outer["/Resources"] = pikepdf.Dictionary({"/ColorSpace": cs27, "/XObject": pikepdf.Dictionary({"/FmInner": fm_inner})})

    p27.Resources = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": pikepdf.Dictionary({"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")})}),
        "/ColorSpace": cs27,
        "/XObject": pikepdf.Dictionary({"/FmOuter": fm_outer}),
    })
    p27.Contents = pdf27.make_stream(
        b"/FmOuter Do /CS1 cs 0.90 0.62 0.18 scn 220 70 42 120 re f 375 158 12 12 re f "
        b"0 0 0 rg BT /F1 11 Tf 395 212 Td (Clone_Alpha) Tj ET "
        b"BT /F1 11 Tf 395 186 Td (Clone_Beta) Tj ET "
        b"BT /F1 11 Tf 395 160 Td (Clone_Gamma) Tj ET"
    )
    pdf27.save(str(CORPUS_DIR / "c27_illustrator_form_separation.pdf"))
    entries.append({"id": "c27_illustrator_form_separation", "filename": "c27_illustrator_form_separation.pdf", "tool": "illustrator_pdf", "chart_type": "bar", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c28: Adobe Illustrator `.st0..st3` SVG export
    c28 = """<?xml version="1.0" encoding="utf-8"?>
<svg version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 300">
<style type="text/css">
  .st0{fill:#FFFFFF;}
  .st1{fill:#D94848;}
  .st2{fill:#3B7EA1;}
  .st3{fill:#5C9E6E;}
  .st4{fill:#9A6FB0;}
</style>
<rect class="st0" width="500" height="300"/>
<path class="st1" d="M70,240 L70,110 L110,110 L110,240 Z"/>
<path class="st2" d="M130,240 L130,75 L170,75 L170,240 Z"/>
<path class="st3" d="M190,240 L190,145 L230,145 L230,240 Z"/>
<path class="st4" d="M250,240 L250,60 L290,60 L290,240 Z"/>
<rect class="st1" x="355" y="80" width="13" height="13"/><text x="376" y="91" font-size="11">Stage_I</text>
<rect class="st2" x="355" y="104" width="13" height="13"/><text x="376" y="115" font-size="11">Stage_II</text>
<rect class="st3" x="355" y="128" width="13" height="13"/><text x="376" y="139" font-size="11">Stage_III</text>
<rect class="st4" x="355" y="152" width="13" height="13"/><text x="376" y="163" font-size="11">Stage_IV</text>
</svg>"""
    (CORPUS_DIR / "c28_illustrator_svg_classes.svg").write_text(c28, encoding="utf-8")
    entries.append({"id": "c28_illustrator_svg_classes", "filename": "c28_illustrator_svg_classes.svg", "tool": "illustrator_svg", "chart_type": "bar", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c29: Inkscape layered inline-style SVG
    c29 = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" viewBox="0 0 500 300">
  <rect width="500" height="300" style="fill:#ffffff"/>
  <g inkscape:groupmode="layer" id="layer1" transform="translate(20,10)">
    <ellipse cx="90" cy="140" rx="26" ry="70" style="fill:#e05a47;fill-opacity:0.85;stroke:#e05a47;stroke-width:1.2"/>
    <ellipse cx="170" cy="125" rx="28" ry="82" style="fill:#4589b0;fill-opacity:0.85;stroke:#4589b0;stroke-width:1.2"/>
    <ellipse cx="250" cy="155" rx="24" ry="56" style="fill:#63a375;fill-opacity:0.85;stroke:#63a375;stroke-width:1.2"/>
    <rect x="335" y="75" width="13" height="13" style="fill:#e05a47"/><text x="356" y="86" style="font-size:11px">Parenchyma</text>
    <rect x="335" y="100" width="13" height="13" style="fill:#4589b0"/><text x="356" y="111" style="font-size:11px">Stroma</text>
    <rect x="335" y="125" width="13" height="13" style="fill:#63a375"/><text x="356" y="136" style="font-size:11px">Interface</text>
  </g>
</svg>"""
    (CORPUS_DIR / "c29_inkscape_layered_violin.svg").write_text(c29, encoding="utf-8")
    entries.append({"id": "c29_inkscape_layered_violin", "filename": "c29_inkscape_layered_violin.svg", "tool": "inkscape_svg", "chart_type": "violin", "has_legend": True, "expected_labeled": 3, "license": "CC0-1.0"})

    # c30: BioRender-style signaling diagram SVG (<g fill>, currentColor, <linearGradient>, legend)
    c30 = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 320">
  <defs>
    <linearGradient id="memGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#DCE8F2"/><stop offset="100%" stop-color="#5B8FB9"/>
    </linearGradient>
  </defs>
  <rect width="560" height="320" fill="#FFFFFF"/>
  <rect x="30" y="78" width="340" height="18" rx="6" fill="url(#memGrad)"/>
  <g fill="#E76F51">
    <rect x="95" y="55" width="32" height="58" rx="10"/>
    <rect x="405" y="70" width="14" height="14" rx="3"/>
  </g>
  <g fill="#2A9D8F">
    <ellipse cx="180" cy="165" rx="36" ry="22"/>
    <rect x="405" y="96" width="14" height="14" rx="3"/>
  </g>
  <g fill="#6D597A">
    <rect x="145" y="232" width="76" height="32" rx="8"/>
    <rect x="405" y="122" width="14" height="14" rx="3"/>
  </g>
  <g color="#E9C46A" stroke="currentColor" fill="none" stroke-width="3">
    <path d="M 127 112 L 165 145"/>
    <path d="M 180 188 L 180 230"/>
    <line x1="405" y1="155" x2="421" y2="155"/>
  </g>
  <text x="428" y="81" font-size="11">TIM3_Receptor</text>
  <text x="428" y="107" font-size="11">SHP2_Kinase</text>
  <text x="428" y="133" font-size="11">NFAT_Target</text>
  <text x="428" y="159" font-size="11">Phospho_Flux</text>
</svg>"""
    (CORPUS_DIR / "c30_biorender_signaling_pathway.svg").write_text(c30, encoding="utf-8")
    entries.append({"id": "c30_biorender_signaling_pathway", "filename": "c30_biorender_signaling_pathway.svg", "tool": "biorender_svg", "chart_type": "pathway_diagram", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c31: Excel PDF export dialect (/Indexed palette + horizontal bottom legend)
    pdf31 = pikepdf.Pdf.new()
    p31 = pdf31.add_blank_page(page_size=(520, 320))
    lut31 = bytes([
        68, 114, 196,   # 0: Excel blue
        237, 125, 49,   # 1: Excel orange
        112, 173, 71,   # 2: Excel green
        255, 192, 0,    # 3: Excel gold
    ])
    p31.Resources = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": pikepdf.Dictionary({"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")})}),
        "/ColorSpace": pikepdf.Dictionary({"/CS0": pikepdf.Array([pikepdf.Name("/Indexed"), pikepdf.Name("/DeviceRGB"), 3, pikepdf.String(lut31)])}),
    })
    p31.Contents = pdf31.make_stream(
        b"/CS0 cs 0 scn 80 85 38 150 re f 95 28 11 11 re f "
        b"1 scn 140 85 38 185 re f 185 28 11 11 re f "
        b"2 scn 200 85 38 125 re f 275 28 11 11 re f "
        b"3 scn 260 85 38 205 re f 365 28 11 11 re f "
        b"0 0 0 rg BT /F1 10 Tf 112 30 Td (Q1_Ctrl) Tj ET "
        b"BT /F1 10 Tf 202 30 Td (Q2_DrugA) Tj ET "
        b"BT /F1 10 Tf 292 30 Td (Q3_DrugB) Tj ET "
        b"BT /F1 10 Tf 382 30 Td (Q4_Dual) Tj ET"
    )
    pdf31.save(str(CORPUS_DIR / "c31_excel_indexed_chart.pdf"))
    entries.append({"id": "c31_excel_indexed_chart", "filename": "c31_excel_indexed_chart.pdf", "tool": "excel_pdf", "chart_type": "bar", "has_legend": True, "expected_labeled": 4, "license": "CC0-1.0"})

    # c32: Multi-page 3-page PDF (tests multi-page selector & page_index=1)
    pdf32 = pikepdf.Pdf.new()
    for pg_i in range(3):
        pg = pdf32.add_blank_page(page_size=(460, 280))
        pg.Resources = pikepdf.Dictionary({
            "/Font": pikepdf.Dictionary({"/F1": pikepdf.Dictionary({"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")})}),
        })
        pg.Contents = pdf32.make_stream(
            f"0.85 0.25 0.22 rg 70 60 45 {110 + pg_i * 25} re f 330 190 12 12 re f "
            f"0.22 0.52 0.82 rg 140 60 45 {155 - pg_i * 15} re f 330 165 12 12 re f "
            f"0 0 0 rg BT /F1 11 Tf 350 192 Td (Arm_A_P{pg_i+1}) Tj ET "
            f"BT /F1 11 Tf 350 167 Td (Arm_B_P{pg_i+1}) Tj ET".encode("ascii")
        )
    pdf32.save(str(CORPUS_DIR / "c32_multipage_manuscript_3p.pdf"))
    entries.append({"id": "c32_multipage_manuscript_3p", "filename": "c32_multipage_manuscript_3p.pdf", "tool": "multipage_pdf", "chart_type": "multipage_bar", "page_index": 1, "has_legend": True, "expected_labeled": 2, "license": "CC0-1.0"})

    # c33: Scanned raster-only PDF (negative test: expect_editable = False)
    pdf33 = pikepdf.Pdf.new()
    p33 = pdf33.add_blank_page(page_size=(400, 300))
    yy, xx = np.mgrid[0:120, 0:160]
    scan_arr = np.zeros((120, 160, 3), dtype=np.uint8)
    scan_arr[..., 0] = np.clip(210 - (xx % 40), 0, 255)
    scan_arr[..., 1] = np.clip(180 - (yy % 40), 0, 255)
    scan_arr[..., 2] = 195
    im_xo = pdf33.make_stream(zlib.compress(scan_arr.tobytes()))
    im_xo["/Type"] = pikepdf.Name("/XObject")
    im_xo["/Subtype"] = pikepdf.Name("/Image")
    im_xo["/Width"] = 160
    im_xo["/Height"] = 120
    im_xo["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
    im_xo["/BitsPerComponent"] = 8
    im_xo["/Filter"] = pikepdf.Name("/FlateDecode")
    p33.Resources = pikepdf.Dictionary({"/XObject": pikepdf.Dictionary({"/Scan0": im_xo})})
    p33.Contents = pdf33.make_stream(b"q 400 0 0 300 0 0 cm /Scan0 Do Q")
    pdf33.save(str(CORPUS_DIR / "c33_scanned_page_only.pdf"))
    entries.append({"id": "c33_scanned_page_only", "filename": "c33_scanned_page_only.pdf", "tool": "scanned_pdf", "chart_type": "scanned_raster_only", "expect_editable": False, "has_legend": False, "expected_labeled": 0, "license": "CC0-1.0"})

    # c34: 24-element hierarchical somatic alteration SVG (K > N hierarchical stress test)
    genes = [
        ("TP53_Missense", "#D53E4F"), ("TP53_Nonsense", "#F46D43"), ("TP53_Splice", "#FDAE61"),
        ("CTNNB1_Exon3", "#3288BD"), ("CTNNB1_Armadillo", "#66C2A5"), ("CTNNB1_Amp", "#ABDDA4"),
        ("AXIN1_Frameshift", "#5E4FA2"), ("AXIN1_Del", "#8073AC"), ("AXIN1_Missense", "#B2ABD2"),
        ("ARID1A_Trunc", "#01665E"), ("ARID1A_Del", "#35978F"), ("ARID1A_Missense", "#80CDC1"),
        ("TERT_Promoter", "#8C510A"), ("TERT_Amp", "#BF812D"), ("TERT_Rearr", "#DFC27D"),
        ("MYC_HighAmp", "#C51B7D"), ("MYC_Gain", "#DE77AE"), ("MYC_Transloc", "#F1B6DA"),
        ("RB1_HomDel", "#4D9221"), ("RB1_Trunc", "#7FBC41"), ("RB1_Splice", "#B8E186"),
        ("NFE2L2_Hotspot", "#B35806"), ("NFE2L2_Amp", "#E08214"), ("NFE2L2_Gain", "#FDB863"),
    ]
    bars_svg = []
    leg_svg = []
    for gi, (glbl, gcol) in enumerate(genes):
        bx = 40 + gi * 18
        bh = 55 + ((gi * 23) % 150)
        by = 240 - bh
        bars_svg.append(f"<rect x='{bx}' y='{by}' width='13' height='{bh}' fill='{gcol}'/>")
        col_i = gi // 12
        row_i = gi % 12
        lx = 490 + col_i * 145
        ly = 30 + row_i * 19
        leg_svg.append(f"<rect x='{lx}' y='{ly}' width='10' height='10' fill='{gcol}'/><text x='{lx+15}' y='{ly+9}' font-size='9.5'>{glbl}</text>")
    c34 = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 790 280'>"
        "<rect width='790' height='280' fill='#FFFFFF'/>"
        + "".join(bars_svg)
        + "".join(leg_svg)
        + "</svg>"
    )
    (CORPUS_DIR / "c34_waterfall_24genes_hier.svg").write_text(c34, encoding="utf-8")
    entries.append({"id": "c34_waterfall_24genes_hier", "filename": "c34_waterfall_24genes_hier.svg", "tool": "custom_svg", "chart_type": "waterfall_24classes", "has_legend": True, "expected_labeled": 24, "license": "CC0-1.0"})

    return entries


def main() -> int:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    for old_f in CORPUS_DIR.iterdir():
        if old_f.is_file():
            old_f.unlink()
    figures: list[dict[str, Any]] = []

    # Copy 4 published public-dataset benchmark figures into corpus
    preset_copies = [
        ("c01_penguins_multimodal", "01_PalmerPenguins_MultiModal_Gorman2014.pdf", "pikepdf_public", "multipanel_heatmap_bar_scatter", True, 11, "CC0-1.0"),
        ("c02_mouse_brain_visium", "04_MouseBrain_Visium_Complex_10xGenomics.pdf", "pikepdf_public", "multipanel_spatial_visium", True, 11, "CC-BY-4.0"),
        ("c03_composite_wb_he_if_diverging", "02_Histology_WB_EvidenceShield_10xVisium.pdf", "pikepdf_composite", "multipanel_wb_he_if_heatmap", True, 7, "CC-BY-4.0"),
        ("c04_svg_pathway_gradients", "03_EGFR_MAPK_Pathway_Lemmon2010.svg", "svg_native", "pathway_gradients_raster", True, 4, "CC-BY-4.0"),
    ]
    for cid, src_name, tool, ctype, has_leg, exp_lbl, lic in preset_copies:
        src = BENCH_FIGS / src_name
        dst_name = f"{cid}{src.suffix}"
        shutil.copy2(src, CORPUS_DIR / dst_name)
        figures.append({
            "id": cid,
            "filename": dst_name,
            "tool": tool,
            "chart_type": ctype,
            "has_legend": has_leg,
            "expected_labeled": exp_lbl,
            "expect_editable": True,
            "heavy": cid == "c02_mouse_brain_visium",
            "license": lic,
        })

    figures.extend(_gen_mpl_figures())
    figures.extend(_gen_tool_dialect_files())

    manifest = {
        "version": "1.0",
        "total_figures": len(figures),
        "figures": figures,
    }
    (CORPUS_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Run WP4 Coverage & Legend Binding Verification across all corpus items
    editable_items = [it for it in figures if it.get("expect_editable", True)]
    detected_editable = 0
    legend_total_elements = 0
    legend_named_elements = 0
    per_fig_results: list[dict[str, Any]] = []

    for it in figures:
        fp = CORPUS_DIR / it["filename"]
        raw = fp.read_bytes()
        page_idx = int(it.get("page_index", 0))
        sc = (
            parse_pdf_scene(raw, fp.name, it["id"], page_index=page_idx)
            if fp.suffix.lower() == ".pdf"
            else parse_svg_scene(raw, fp.name, it["id"])
        )
        n_mutable = len(sc.entities) + len(sc.continuous_scales)
        if it.get("expect_editable", True):
            if n_mutable >= 1:
                detected_editable += 1
        else:
            assert n_mutable == 0, f"Scanned negative test {it['id']} unexpectedly had {n_mutable} mutable items!"

        named_cnt = sum(
            1
            for e in sc.entities.values()
            if not ("group ·" in e.label and e.label.endswith(("mark", "marks")))
        )
        if it.get("has_legend", False) and len(sc.entities) > 0:
            legend_total_elements += len(sc.entities)
            legend_named_elements += named_cnt

        per_fig_results.append({
            "id": it["id"],
            "tool": it["tool"],
            "chart_type": it["chart_type"],
            "entities": len(sc.entities),
            "continuous_scales": len(sc.continuous_scales),
            "protected_images": len(sc.evidence_regions),
            "named_entities": named_cnt,
        })

    det_rate = detected_editable / max(1, len(editable_items))
    leg_rate = legend_named_elements / max(1, legend_total_elements)
    wp4_report = {
        "total_corpus_figures": len(figures),
        "editable_figures": len(editable_items),
        "detected_editable_figures": detected_editable,
        "editable_detection_rate": round(det_rate, 4),
        "legend_total_entities": legend_total_elements,
        "legend_bound_entities": legend_named_elements,
        "legend_binding_rate": round(leg_rate, 4),
        "details": per_fig_results,
    }
    (REPO / "bench" / "wp4_engine_coverage_report.json").write_text(json.dumps(wp4_report, indent=2), encoding="utf-8")

    print("=" * 84)
    print("Danqing WP4 Corpus & Engine Coverage Report")
    print("=" * 84)
    print(f"Total corpus figures     : {len(figures)} (target >= 30)")
    print(f"Editable detection rate  : {detected_editable}/{len(editable_items)} = {det_rate * 100:.1f}% (target >= 90.0%)")
    print(f"Legend binding rate      : {legend_named_elements}/{legend_total_elements} = {leg_rate * 100:.1f}% (target >= 85.0%)")
    print("-" * 84)
    for r in per_fig_results:
        print(
            f"  {r['id']:<34} | {r['tool']:<18} | ent={r['entities']:<2} named={r['named_entities']:<2} scales={r['continuous_scales']} img={r['protected_images']}"
        )
    if len(figures) < 30 or det_rate < 0.90 or leg_rate < 0.85:
        print("FAIL: WP4 corpus or coverage rate below threshold!", file=sys.stderr)
        return 1
    print("PASS: WP4 corpus size, editable detection (>= 90%), and legend binding (>= 85%) verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
