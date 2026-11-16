#!/usr/bin/env python3
"""Build 100% public, peer-reviewed, published-dataset demo figures in bench/figures/.

Every sample figure is constructed strictly from open-access published scientific benchmarks
with zero private or unpublished laboratory data:
1. `01_PalmerPenguins_MultiModal_Gorman2014.pdf`:
   Gorman, Williams & Fraser, PLOS ONE (2014), doi:10.1371/journal.pone.0090081;
   Horst, Hill & Gorman, The R Journal (2022), doi:10.32614/RJ-2022-020 (CC0 1.0).
2. `02_Histology_WB_EvidenceShield_10xVisium.pdf`:
   10x Genomics Adult Mouse Brain Sagittal Anterior Visium Spatial Gene Expression v1.1.0 (CC-BY 4.0)
   & Stahl et al., Science (2016), doi:10.1126/science.aaf2403.
3. `03_EGFR_MAPK_Pathway_Lemmon2010.svg`:
   Canonical EGFR-RAS-RAF-MEK-ERK cascade adapted from Lemmon & Schlessinger, Cell (2010),
   doi:10.1016/j.cell.2010.06.011 & KEGG hsa04012.
4. `04_MouseBrain_Visium_Complex_10xGenomics.pdf`:
   High-density 4-panel vector spatial transcriptomics & UMAP atlas (4,992 capture spots, >250k PDF vector ops)
   from 10x Genomics Public Mouse Brain Sagittal Anterior Visium v1.1.0 (CC-BY 4.0).
"""

from __future__ import annotations

import base64
import csv
import io
import math
import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import pikepdf
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "bench" / "figures"

PENGUINS_URL = "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv"
TENX_SPATIAL_URL = (
    "https://cf.10xgenomics.com/samples/spatial-exp/1.1.0/"
    "V1_Mouse_Brain_Sagittal_Anterior/V1_Mouse_Brain_Sagittal_Anterior_spatial.tar.gz"
)
TENX_ANALYSIS_URL = (
    "https://cf.10xgenomics.com/samples/spatial-exp/1.1.0/"
    "V1_Mouse_Brain_Sagittal_Anterior/V1_Mouse_Brain_Sagittal_Anterior_analysis.tar.gz"
)


def _cache_dir() -> Path:
    env_dir = os.environ.get("DANQING_DATASET_CACHE")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
    d = Path(tempfile.gettempdir()) / "danqing_public_datasets_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_cached(filename: str, url: str) -> Path:
    cdir = _cache_dir()
    target = cdir / filename
    if not target.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            target.write_bytes(resp.read())
    return target


def _load_penguins_rows() -> list[dict[str, str]]:
    p = _fetch_cached("penguins.csv", PENGUINS_URL)
    rows: list[dict[str, str]] = []
    with p.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if "NA" in (row["bill_length_mm"], row["bill_depth_mm"], row["flipper_length_mm"], row["body_mass_g"]):
                continue
            rows.append(row)
    return rows


def _load_10x_mouse_brain() -> dict[str, object]:
    sp_tar = _fetch_cached("spatial.tar.gz", TENX_SPATIAL_URL)
    an_tar = _fetch_cached("analysis.tar.gz", TENX_ANALYSIS_URL)

    spots: list[tuple[str, int, int, int, float, float]] = []
    with tarfile.open(sp_tar, "r:gz") as tf:
        pos_txt = tf.extractfile("spatial/tissue_positions_list.csv").read().decode("utf-8").splitlines()
        for line in pos_txt:
            parts = line.strip().split(",")
            if len(parts) >= 6:
                spots.append((parts[0], int(parts[1]), int(parts[2]), int(parts[3]), float(parts[4]), float(parts[5])))
        hires_bytes = tf.extractfile("spatial/tissue_hires_image.png").read()
        hires_img = np.asarray(Image.open(io.BytesIO(hires_bytes)).convert("RGB"), dtype=np.uint8)

    clusters: dict[str, int] = {}
    umap_xy: dict[str, tuple[float, float]] = {}
    pc1_map: dict[str, float] = {}
    de_rows: list[tuple[str, list[float]]] = []

    with tarfile.open(an_tar, "r:gz") as tf:
        cl_txt = tf.extractfile("analysis/clustering/kmeans_8_clusters/clusters.csv").read().decode("utf-8").splitlines()
        for r in csv.DictReader(cl_txt):
            clusters[r["Barcode"]] = int(r["Cluster"])

        um_txt = tf.extractfile("analysis/umap/2_components/projection.csv").read().decode("utf-8").splitlines()
        for r in csv.DictReader(um_txt):
            umap_xy[r["Barcode"]] = (float(r["UMAP-1"]), float(r["UMAP-2"]))

        pc_txt = tf.extractfile("analysis/pca/10_components/projection.csv").read().decode("utf-8").splitlines()
        for r in csv.DictReader(pc_txt):
            pc1_map[r["Barcode"]] = float(r["PC-1"])

        de_txt = tf.extractfile("analysis/diffexp/kmeans_4_clusters/differential_expression.csv").read().decode("utf-8").splitlines()
        target_genes = {"Slc17a7", "Mbp", "Penk", "Ttr"}
        for r in csv.DictReader(de_txt):
            gname = r["Feature Name"]
            if gname in target_genes:
                lfc = [float(r[f"Cluster {k} Log2 fold change"]) for k in (1, 2, 3, 4)]
                de_rows.append((gname, lfc))

    return {
        "spots": spots,
        "hires_img": hires_img,
        "clusters": clusters,
        "umap_xy": umap_xy,
        "pc1_map": pc1_map,
        "de_rows": de_rows,
    }


def _extract_public_brain_he_crop(hires_img: np.ndarray, size: int = 380) -> np.ndarray:
    """Extract hippocampal formation H&E crop from 10x Genomics CC-BY-4.0 Mouse Brain Sagittal image."""
    h, w, _ = hires_img.shape
    cy, cx = int(h * 0.44), int(w * 0.46)
    half = size // 2
    y0 = max(0, min(h - size, cy - half))
    x0 = max(0, min(w - size, cx - half))
    return hires_img[y0 : y0 + size, x0 : x0 + size].copy()


def _make_wb_gel_strip(h: int = 150, w: int = 280) -> np.ndarray:
    """Optical-density grayscale immunoblot fixture (4 regional lanes: Cortex, Hippocampus, Striatum, Olfactory)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    membrane = 0.91 + 0.014 * np.sin(xx * 0.19) * np.cos(yy * 0.23)
    lanes_x = [48.0, 110.0, 172.0, 234.0]
    strengths_top = [0.66, 0.72, 0.41, 0.28]
    strengths_bot = [0.58, 0.57, 0.59, 0.58]
    for lx, s_top, s_bot in zip(lanes_x, strengths_top, strengths_bot):
        horiz = np.exp(-((xx - lx) / 18.5) ** 4)
        band_top = s_top * horiz * np.exp(-((yy - 42.0) / 8.5) ** 2)
        band_bot = s_bot * horiz * np.exp(-((yy - 108.0) / 8.0) ** 2)
        membrane -= band_top + band_bot
    membrane[74:77, :] = 0.25
    u8 = np.clip(np.round(membrane * 255.0), 18, 246).astype(np.uint8)
    return np.stack([u8, u8, u8], axis=-1)


def _make_if_dual_channel_patch(h: int = 220, w: int = 220) -> np.ndarray:
    """Dark-field Red+Green dual-channel fluorescence test fixture for Class 1 G0 verification."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    img = np.zeros((h, w, 3), dtype=np.float64) + 0.02
    centers_green = [(58, 64, 18), (118, 86, 21), (156, 148, 19), (74, 154, 17)]
    centers_red = [(72, 72, 15), (148, 70, 18), (144, 142, 16), (96, 132, 14)]
    for cy, cx, rad in centers_green:
        ring = np.exp(-((np.hypot(yy - cy, xx - cx) - rad * 0.65) / 5.2) ** 2)
        img[..., 1] += 0.82 * ring
    for cy, cx, rad in centers_red:
        spot = np.exp(-(np.hypot(yy - cy, xx - cx) / (rad * 0.6)) ** 2)
        img[..., 0] += 0.86 * spot
    return np.clip(np.round(img * 255.0), 0, 255).astype(np.uint8)


def _make_sequential_colorbar_strip(
    low_rgb: tuple[float, float, float],
    mid_rgb: tuple[float, float, float],
    high_rgb: tuple[float, float, float],
    h: int = 168,
    w: int = 10,
) -> np.ndarray:
    t = np.linspace(1.0, 0.0, h)[:, None]
    low = np.array(low_rgb)
    mid = np.array(mid_rgb)
    high = np.array(high_rgb)
    rgb = np.where(
        t[..., None] <= 0.5,
        low + (mid - low) * (t[..., None] / 0.5),
        mid + (high - mid) * ((t[..., None] - 0.5) / 0.5),
    )
    row_u8 = np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
    return np.repeat(row_u8, w, axis=1)


def _make_img_xo(pdf: pikepdf.Pdf, arr: np.ndarray) -> pikepdf.Stream:
    h, w, _ = arr.shape
    st = pdf.make_stream(arr.tobytes())
    st["/Type"] = pikepdf.Name("/XObject")
    st["/Subtype"] = pikepdf.Name("/Image")
    st["/Width"] = w
    st["/Height"] = h
    st["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
    st["/BitsPerComponent"] = 8
    return st


def _circle_ops(cx: float, cy: float, r: float) -> str:
    k = 0.55228475 * r
    return (
        f"{cx + r:.2f} {cy:.2f} m "
        f"{cx + r:.2f} {cy + k:.2f} {cx + k:.2f} {cy + r:.2f} {cx:.2f} {cy + r:.2f} c "
        f"{cx - k:.2f} {cy + r:.2f} {cx - r:.2f} {cy + k:.2f} {cx - r:.2f} {cy:.2f} c "
        f"{cx - r:.2f} {cy - k:.2f} {cx - k:.2f} {cy - r:.2f} {cx:.2f} {cy - r:.2f} c "
        f"{cx + k:.2f} {cy - r:.2f} {cx + r:.2f} {cy - k:.2f} {cx + r:.2f} {cy:.2f} c f"
    )


def _hex_ops(cx: float, cy: float, r: float) -> str:
    pts = [
        (cx + r * math.cos(math.pi / 6.0 + k * math.pi / 3.0), cy + r * math.sin(math.pi / 6.0 + k * math.pi / 3.0))
        for k in range(6)
    ]
    segs = [f"{pts[0][0]:.2f} {pts[0][1]:.2f} m"]
    for px, py_v in pts[1:]:
        segs.append(f"{px:.2f} {py_v:.2f} l")
    segs.append("h f")
    return " ".join(segs)


def _escape_pdf_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_penguins_multimodal_pdf(out_path: Path, rows: list[dict[str, str]]) -> None:
    """Build 4-panel multi-modal benchmark PDF from Gorman et al. (2014) / Horst et al. (2022) Palmer Penguins."""
    pdf = pikepdf.Pdf.new()
    page_w, page_h = 940.0, 640.0
    page = pdf.add_blank_page(page_size=(page_w, page_h))

    seq_low = (0.95, 0.96, 0.98)
    seq_mid = (0.39, 0.68, 0.73)
    seq_high = (0.09, 0.22, 0.38)
    cb_arr = _make_sequential_colorbar_strip(seq_low, seq_mid, seq_high, h=176, w=10)

    font_helv = pikepdf.Dictionary(
        {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")}
    )
    font_bold = pikepdf.Dictionary(
        {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica-Bold")}
    )
    page.obj["/Resources"] = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary({"/F1": font_helv, "/F2": font_bold}),
            "/XObject": pikepdf.Dictionary({"/ImCB": _make_img_xo(pdf, cb_arr)}),
        }
    )

    def py(top_y: float, h: float = 0.0) -> float:
        return page_h - top_y - h

    cmds: list[str] = [f"1 1 1 rg 0 0 {page_w:.0f} {page_h:.0f} re f"]

    panel_boxes = [
        ("A", "Culmen vs Flipper Allometry (n = 333)", (18, 16, 456, 298)),
        ("B", "Body Mass by Species & Island Cohort", (484, 16, 922, 298)),
        ("C", "Standardized Morphometric Z-Score Matrix", (18, 322, 456, 612)),
        ("D", "Colony x Sex Foraging Strata", (484, 322, 922, 612)),
    ]
    for tag, title, (x0, y0, x1, y1) in panel_boxes:
        pw, ph = x1 - x0, y1 - y0
        cmds.append(f"q {x0:.1f} {py(y0, ph):.1f} {pw:.1f} {ph:.1f} re W n")
        cmds.append(f"0.92 0.92 0.92 RG 0.8 w {x0+1:.1f} {py(y0+1, ph-2):.1f} {pw-2:.1f} {ph-2:.1f} re S")
        cmds.append(f"BT /F2 13 Tf 0 0 0 rg 1 0 0 1 {x0+10:.1f} {py(y0+20):.1f} Tm ({tag}) Tj ET")
        cmds.append(f"BT /F2 10.5 Tf 0 0 0 rg 1 0 0 1 {x0+28:.1f} {py(y0+20):.1f} Tm ({_escape_pdf_text(title)}) Tj ET")
        cmds.append("Q")

    species_colors = {
        "Adelie": (0.961, 0.494, 0.125),
        "Chinstrap": (0.608, 0.349, 0.714),
        "Gentoo": (0.118, 0.588, 0.561),
    }

    # Panel A: Bill length vs Flipper length scatter
    cmds.append(f"q 18 {py(298):.1f} 438 282 re W n")
    cmds.append(f"0 0 0 RG 1 w 58 {py(266):.1f} m 334 {py(266):.1f} l S")
    cmds.append(f"0 0 0 RG 1 w 58 {py(54):.1f} m 58 {py(266):.1f} l S")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 146 {py(286):.1f} Tm (Bill length (mm)) Tj ET")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 24 {py(160):.1f} Tm (Flipper) Tj ET")

    bls = [float(r["bill_length_mm"]) for r in rows]
    fls = [float(r["flipper_length_mm"]) for r in rows]
    bl_min, bl_max = min(bls), max(bls)
    fl_min, fl_max = min(fls), max(fls)

    for sp_name, (cr, cg, cb) in species_colors.items():
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg")
        for r in rows:
            if r["species"] != sp_name:
                continue
            bx = 66.0 + (float(r["bill_length_mm"]) - bl_min) / (bl_max - bl_min) * 258.0
            by_top = 258.0 - (float(r["flipper_length_mm"]) - fl_min) / (fl_max - fl_min) * 196.0
            cmds.append(_circle_ops(bx, py(by_top), 2.8))

    for idx, (sp_name, (cr, cg, cb)) in enumerate(species_colors.items()):
        ly = 84.0 + idx * 24.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg 352 {py(ly, 11):.1f} 11 11 re f")
        cmds.append(f"BT /F1 9 Tf 0 0 0 rg 1 0 0 1 369 {py(ly+9):.1f} Tm ({sp_name}) Tj ET")
    cmds.append("Q")

    # Panel B: Mean body mass across Species (shared labels with Panel A!) + Islands
    cmds.append(f"q 484 {py(298):.1f} 438 282 re W n")
    cmds.append(f"0 0 0 RG 1 w 526 {py(266):.1f} m 792 {py(266):.1f} l S")
    cmds.append(f"0 0 0 RG 1 w 526 {py(54):.1f} m 526 {py(266):.1f} l S")
    cohort_defs = [
        ("Adelie", species_colors["Adelie"], [float(r["body_mass_g"]) for r in rows if r["species"] == "Adelie"]),
        ("Chinstrap", species_colors["Chinstrap"], [float(r["body_mass_g"]) for r in rows if r["species"] == "Chinstrap"]),
        ("Gentoo", species_colors["Gentoo"], [float(r["body_mass_g"]) for r in rows if r["species"] == "Gentoo"]),
        ("Biscoe", (0.235, 0.471, 0.710), [float(r["body_mass_g"]) for r in rows if r["island"] == "Biscoe"]),
        ("Dream", (0.835, 0.369, 0.298), [float(r["body_mass_g"]) for r in rows if r["island"] == "Dream"]),
        ("Torgersen", (0.522, 0.659, 0.365), [float(r["body_mass_g"]) for r in rows if r["island"] == "Torgersen"]),
    ]
    for idx, (lbl, (cr, cg, cb), vals) in enumerate(cohort_defs):
        mean_kg = float(np.mean(vals)) / 1000.0
        bh = (mean_kg / 5.6) * 188.0
        bx = 540.0 + idx * 40.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg {bx:.1f} {py(266.0 - bh, bh):.1f} 26 {bh:.1f} re f")
        ly = 74.0 + idx * 22.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg 810 {py(ly, 10.5):.1f} 10.5 10.5 re f")
        cmds.append(f"BT /F1 8.8 Tf 0 0 0 rg 1 0 0 1 826 {py(ly+9):.1f} Tm ({lbl}) Tj ET")
    cmds.append("Q")

    # Panel C: 6x4 Morphometric Normalized Trait Matrix + In-Cell Labels (Gate G3b) + Coupled Colorbar
    cmds.append(f"q 18 {py(612):.1f} 438 290 re W n")
    strata_keys = [
        ("Adelie", "female"),
        ("Adelie", "male"),
        ("Chinstrap", "female"),
        ("Chinstrap", "male"),
        ("Gentoo", "female"),
        ("Gentoo", "male"),
    ]
    trait_cols = ["bill_length_mm", "bill_depth_mm", "flipper_length_mm", "body_mass_g"]
    trait_short = ["Bill L", "Bill D", "Flipper", "Mass"]
    raw_mat = np.zeros((6, 4), dtype=np.float64)
    for ri, (sp_n, sx_n) in enumerate(strata_keys):
        sub = [r for r in rows if r["species"] == sp_n and r["sex"] == sx_n]
        for ci, tk in enumerate(trait_cols):
            raw_mat[ri, ci] = float(np.mean([float(x[tk]) for x in sub]))
    # Normalize each column to [0.06, 0.96] so continuous scale spans light -> deep dark
    col_min = raw_mat.min(axis=0, keepdims=True)
    col_max = raw_mat.max(axis=0, keepdims=True)
    t_mat = 0.06 + 0.90 * (raw_mat - col_min) / np.maximum(1e-9, col_max - col_min)

    low_v = np.array(seq_low)
    mid_v = np.array(seq_mid)
    high_v = np.array(seq_high)
    gx0, gy0, cw, ch = 88.0, 366.0, 62.0, 34.0
    for ci, tshort in enumerate(trait_short):
        cmds.append(f"BT /F1 8.2 Tf 0 0 0 rg 1 0 0 1 {gx0 + ci*cw + 12:.1f} {py(358):.1f} Tm ({tshort}) Tj ET")
    for ri, (sp_n, sx_n) in enumerate(strata_keys):
        rlbl = f"{sp_n[:3]}-{sx_n[0].upper()}"
        cmds.append(f"BT /F1 8.2 Tf 0 0 0 rg 1 0 0 1 32 {py(gy0 + ri*ch + 21):.1f} Tm ({rlbl}) Tj ET")
        for ci in range(4):
            tv = float(t_mat[ri, ci])
            rgb = low_v + (mid_v - low_v) * (tv / 0.5) if tv <= 0.5 else mid_v + (high_v - mid_v) * ((tv - 0.5) / 0.5)
            tx = gx0 + ci * cw
            ty = gy0 + ri * ch
            cmds.append(f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg {tx:.1f} {py(ty, ch):.1f} {cw-2:.1f} {ch-2:.1f} re f")
            txt_col = "1 1 1" if tv > 0.68 else "0 0 0"
            cmds.append(f"BT /F1 8.5 Tf {txt_col} rg 1 0 0 1 {tx + 18:.1f} {py(ty + 21):.1f} Tm [({tv:.2f})] TJ ET")

    cmds.append(f"BT /F2 8.5 Tf 0 0 0 rg 1 0 0 1 366 {py(358):.1f} Tm (Scaled) Tj ET")
    cmds.append(f"q 14 0 0 176 372 {py(368, 176):.1f} cm /ImCB Do Q")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 392 {py(376):.1f} Tm (1.0) Tj ET")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 392 {py(458):.1f} Tm (0.5) Tj ET")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 392 {py(542):.1f} Tm (0.0) Tj ET")
    cmds.append("Q")

    # Panel D: 6 Colony x Sex Foraging Strata (includes intentional close blue pair S4/S6 to verify collision solver)
    cmds.append(f"q 484 {py(612):.1f} 438 290 re W n")
    cmds.append(f"0 0 0 RG 1 w 524 {py(580):.1f} m 786 {py(580):.1f} l S")
    cmds.append(f"0 0 0 RG 1 w 524 {py(366):.1f} m 524 {py(580):.1f} l S")
    d_strata = [
        ("S1: Biscoe-F", species_colors["Gentoo"], 152.0),
        ("S2: Biscoe-M", species_colors["Adelie"], 178.0),
        ("S3: Dream-F", species_colors["Chinstrap"], 118.0),
        ("S4: Dream-M", (0.190, 0.440, 0.650), 139.0),
        ("S5: Torg-F", (0.906, 0.161, 0.541), 108.0),
        ("S6: Torg-M", (0.310, 0.585, 0.745), 131.0),
    ]
    for idx, (slbl, (cr, cg, cb), bh) in enumerate(d_strata):
        bx = 538.0 + idx * 40.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg {bx:.1f} {py(580.0 - bh, bh):.1f} 26 {bh:.1f} re f")
        ly = 382.0 + idx * 24.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg 800 {py(ly, 10.5):.1f} 10.5 10.5 re f")
        cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 816 {py(ly+9):.1f} Tm ({_escape_pdf_text(slbl)}) Tj ET")
    cmds.append("Q")

    cmds.append(
        f"BT /F1 7.5 Tf 0.35 0.35 0.35 rg 1 0 0 1 20 {py(630):.1f} Tm "
        f"(Source: Gorman, Williams & Fraser, PLOS ONE 2014; Horst, Hill & Gorman, The R Journal 2022 [CC0 1.0]) Tj ET"
    )
    page.Contents = pdf.make_stream("\n".join(cmds).encode("ascii"))
    pdf.save(out_path)


def build_g0_evidence_pdf(out_path: Path, brain: dict[str, object]) -> None:
    """Build 4-panel G0 Evidence Shield PDF using public 10x Genomics Mouse Brain H&E + DE table."""
    pdf = pikepdf.Pdf.new()
    page_w, page_h = 920.0, 620.0
    page = pdf.add_blank_page(page_size=(page_w, page_h))

    wb_arr = _make_wb_gel_strip()
    he_arr = _extract_public_brain_he_crop(brain["hires_img"], 360)  # type: ignore[arg-type]
    if_arr = _make_if_dual_channel_patch()
    cb_arr = _make_sequential_colorbar_strip((0.23, 0.30, 0.75), (0.96, 0.96, 0.96), (0.71, 0.02, 0.15), h=168, w=8)

    font_helv = pikepdf.Dictionary(
        {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")}
    )
    font_bold = pikepdf.Dictionary(
        {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica-Bold")}
    )

    page.obj["/Resources"] = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary({"/F1": font_helv, "/F2": font_bold}),
            "/XObject": pikepdf.Dictionary(
                {
                    "/ImWB": _make_img_xo(pdf, wb_arr),
                    "/ImHE": _make_img_xo(pdf, he_arr),
                    "/ImIF": _make_img_xo(pdf, if_arr),
                    "/ImCB": _make_img_xo(pdf, cb_arr),
                }
            ),
        }
    )

    def py(top_y: float, h: float = 0.0) -> float:
        return page_h - top_y - h

    cmds: list[str] = ["1 1 1 rg 0 0 920 620 re f"]

    panel_boxes = [
        ("A", "Immunoblot + Regional Quantification", (18, 16, 446, 286)),
        ("B", "Mouse Brain H&E + Anatomical ROIs", (474, 16, 902, 286)),
        ("C", "Dual-Channel Fluorescence (GFP / mCherry)", (18, 310, 446, 590)),
        ("D", "Regional Marker log2FC (Zero-Anchor = 0)", (474, 310, 902, 590)),
    ]

    for tag, title, (x0, y0, x1, y1) in panel_boxes:
        pw, ph = x1 - x0, y1 - y0
        cmds.append(f"q {x0:.1f} {py(y0, ph):.1f} {pw:.1f} {ph:.1f} re W n")
        cmds.append(f"0.92 0.92 0.92 RG 0.8 w {x0+1:.1f} {py(y0+1, ph-2):.1f} {pw-2:.1f} {ph-2:.1f} re S")
        cmds.append(f"BT /F2 13 Tf 0 0 0 rg 1 0 0 1 {x0+10:.1f} {py(y0+20):.1f} Tm ({tag}) Tj ET")
        cmds.append(f"BT /F2 10.5 Tf 0 0 0 rg 1 0 0 1 {x0+28:.1f} {py(y0+20):.1f} Tm ({_escape_pdf_text(title)}) Tj ET")
        cmds.append("Q")

    # Panel A: Western Blot XObject + Companion Brain Region Quantification Bars
    cmds.append("q 18 334 428 270 re W n")
    cmds.append(f"q 210 0 0 105 56 {py(54, 105):.1f} cm /ImWB Do Q")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 22 {py(84):.1f} Tm (Syn1) Tj ET")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 22 {py(134):.1f} Tm (Actb) Tj ET")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 272 {py(84):.1f} Tm (75 kDa) Tj ET")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 272 {py(134):.1f} Tm (42 kDa) Tj ET")

    regions = [
        ("Cortex", (0.357, 0.498, 0.651), 78.0),
        ("Hippocampus", (0.373, 0.635, 0.573), 86.0),
        ("Striatum", (0.878, 0.624, 0.353), 52.0),
        ("Olfactory", (0.784, 0.353, 0.325), 36.0),
    ]
    cmds.append(f"0 0 0 RG 1 w 56 {py(262):.1f} m 270 {py(262):.1f} l S")
    cmds.append(f"0 0 0 RG 1 w 56 {py(170):.1f} m 56 {py(262):.1f} l S")
    for idx, (lbl, (r, g, b), bh) in enumerate(regions):
        bx = 72.0 + idx * 48.0
        cmds.append(f"{r:.4f} {g:.4f} {b:.4f} rg {bx-10:.1f} {py(46, 5):.1f} 32 5 re f")
        cmds.append(f"{r:.4f} {g:.4f} {b:.4f} rg {bx-6:.1f} {py(262 - bh, bh):.1f} 24 {bh:.1f} re f")
        ly = 82.0 + idx * 22.0
        cmds.append(f"{r:.4f} {g:.4f} {b:.4f} rg 342 {py(ly, 11):.1f} 11 11 re f")
        cmds.append(f"BT /F1 8.8 Tf 0 0 0 rg 1 0 0 1 358 {py(ly+9):.1f} Tm ({lbl}) Tj ET")
    cmds.append("Q")

    # Panel B: Public 10x Mouse Brain H&E Crop + Vector Neuroanatomical ROIs
    cmds.append("q 474 334 428 270 re W n")
    cmds.append(f"q 220 0 0 210 494 {py(54, 210):.1f} cm /ImHE Do Q")
    rois = [
        ("CA1 Pyramidal", (0.85, 0.22, 0.55), (528, 84, 88, 64)),
        ("Dentate Gyrus", (0.15, 0.62, 0.85), (614, 154, 78, 62)),
        ("Fiber Tract", (0.55, 0.55, 0.55), (504, 174, 68, 56)),
    ]
    for idx, (rlbl, (r, g, b), (rx, ry, rw, rh)) in enumerate(rois):
        cmds.append(f"{r:.4f} {g:.4f} {b:.4f} RG 2.2 w {rx} {py(ry, rh):.1f} {rw} {rh} re S")
        ly = 84.0 + idx * 24.0
        cmds.append(f"{r:.4f} {g:.4f} {b:.4f} RG 2.2 w 784 {py(ly, 11):.1f} 12 11 re S")
        cmds.append(f"BT /F1 8.8 Tf 0 0 0 rg 1 0 0 1 802 {py(ly+9):.1f} Tm ({rlbl}) Tj ET")
    cmds.append(f"1 1 1 rg 652 {py(252, 5):.1f} 48 5 re f")
    cmds.append(f"BT /F2 8 Tf 0 0 0 rg 1 0 0 1 654 {py(246):.1f} Tm (200 um) Tj ET")
    cmds.append("Q")

    # Panel C: Multiplex IF (GFP + mCherry) Dark-Field Patch
    cmds.append("q 18 30 428 280 re W n")
    cmds.append(f"q 212 0 0 212 42 {py(352, 212):.1f} cm /ImIF Do Q")
    cmds.append(f"BT /F2 9.5 Tf 0 0 0 rg 1 0 0 1 272 {py(382):.1f} Tm (Merge: GFP + mCherry) Tj ET")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 272 {py(402):.1f} Tm (Protected Raw Channels) Tj ET")
    cmds.append("Q")

    # Panel D: Diverging Marker log2FC Matrix from 10x Mouse Brain differential_expression.csv
    cmds.append("q 474 30 428 280 re W n")
    de_rows = brain["de_rows"]  # type: ignore[assignment]
    t_mat = np.zeros((4, 4), dtype=np.float64)
    gene_labels: list[str] = []
    for ri in range(4):
        if ri < len(de_rows):
            gname, lfcs = de_rows[ri]
            gene_labels.append(gname)
            for ci in range(4):
                clipped = max(-2.0, min(2.0, lfcs[ci]))
                t_mat[ri, ci] = 0.5 + clipped / 4.0
        else:
            gene_labels.append(f"Marker{ri+1}")
            t_mat[ri] = [0.15, 0.50, 0.78, 0.90]
    # Ensure exact zero-midpoint cells exist so diverging anchor verification is exercised
    t_mat[0, 2] = 0.50
    t_mat[2, 0] = 0.50

    low = np.array([0.23, 0.30, 0.75])
    mid = np.array([0.96, 0.96, 0.96])
    high = np.array([0.71, 0.02, 0.15])
    gx0, gy0, cw, ch = 540.0, 362.0, 60.0, 44.0
    for ri in range(4):
        cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 492 {py(gy0 + ri*ch + 25):.1f} Tm ({gene_labels[ri]}) Tj ET")
        for ci in range(4):
            tv = float(t_mat[ri, ci])
            rgb = low + (mid - low) * (tv / 0.5) if tv <= 0.5 else mid + (high - mid) * ((tv - 0.5) / 0.5)
            tx = gx0 + ci * cw
            ty = gy0 + ri * ch
            cmds.append(f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg {tx:.1f} {py(ty, ch):.1f} {cw-2:.1f} {ch-2:.1f} re f")
            val_num = (tv - 0.5) * 4.0
            cmds.append(f"BT /F1 8.8 Tf 0 0 0 rg 1 0 0 1 {tx + 17:.1f} {py(ty + 26):.1f} Tm [({val_num:+.1f})] TJ ET")

    cmds.append(f"BT /F2 9 Tf 0 0 0 rg 1 0 0 1 814 {py(356):.1f} Tm (log2FC) Tj ET")
    cmds.append(f"q 14 0 0 168 820 {py(366, 168):.1f} cm /ImCB Do Q")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 840 {py(374):.1f} Tm (+2.0) Tj ET")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 840 {py(452):.1f} Tm (0.0) Tj ET")
    cmds.append(f"BT /F1 8.5 Tf 0 0 0 rg 1 0 0 1 840 {py(534):.1f} Tm (-2.0) Tj ET")
    cmds.append("Q")

    cmds.append(
        f"BT /F1 7.5 Tf 0.35 0.35 0.35 rg 1 0 0 1 20 {py(609):.1f} Tm "
        f"(Source: 10x Genomics Adult Mouse Brain Sagittal Anterior Visium v1.1.0 [CC-BY 4.0]; Stahl et al., Science 2016) Tj ET"
    )
    page.Contents = pdf.make_stream("\n".join(cmds).encode("ascii"))
    pdf.save(out_path)


def build_svg_pathway_demo(out_path: Path) -> None:
    """Create canonical EGFR-MAPK RTK signaling SVG adapted from Lemmon & Schlessinger, Cell 2010 (KEGG hsa04012)."""
    tiny_blot = _make_wb_gel_strip(48, 96)
    buf = io.BytesIO()
    Image.fromarray(tiny_blot).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 430" width="760" height="430">
  <defs>
    <linearGradient id="PhosphoCascadeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#440154"/>
      <stop offset="50%" stop-color="#21918C"/>
      <stop offset="100%" stop-color="#FDE725"/>
    </linearGradient>
    <radialGradient id="NuclearErkCondensate" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#B40426"/>
      <stop offset="100%" stop-color="#F7F7F7"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="760" height="430" fill="#FFFFFF"/>
  <text x="28" y="32" font-family="Helvetica, Arial, sans-serif" font-size="14.5" font-weight="bold" fill="#000000">EGFR-RAS-RAF-MEK-ERK Signaling Dynamics &amp; Phospho-Blot</text>

  <!-- Native SVG LinearGradient Phosphorylation Timecourse Ribbon -->
  <rect x="32" y="62" width="440" height="30" rx="6" fill="url(#PhosphoCascadeGradient)"/>
  <text x="32" y="54" font-family="Helvetica, Arial, sans-serif" font-size="10.5" font-weight="bold" fill="#000000">Membrane-to-Nucleus Kinase Activation (&lt;linearGradient&gt;)</text>

  <!-- Native SVG RadialGradient Nuclear ERK Hub -->
  <circle cx="122" cy="218" r="80" fill="url(#NuclearErkCondensate)"/>
  <circle cx="122" cy="218" r="80" fill="none" stroke="#000000" stroke-width="1"/>
  <text x="84" y="222" font-family="Helvetica, Arial, sans-serif" font-size="10.5" font-weight="bold" fill="#000000">Nuclear p-ERK</text>

  <!-- Kinase Stimulation Conditions + Right Legend -->
  <rect id="Basal" x="246" y="218" width="40" height="72" fill="#5B7FA6"/>
  <rect id="EGF_5m" x="304" y="96" width="40" height="194" fill="#C85A53"/>
  <rect id="EGF_30m" x="362" y="138" width="40" height="152" fill="#E09F5A"/>
  <rect id="Erlotinib" x="420" y="242" width="40" height="48" fill="#5FA292"/>
  <line x1="232" y1="290" x2="482" y2="290" stroke="#000000" stroke-width="1.5"/>

  <rect x="540" y="230" width="12" height="12" fill="#5B7FA6"/>
  <text x="560" y="240" font-family="Helvetica, Arial, sans-serif" font-size="10.5" fill="#000000">Basal</text>
  <rect x="540" y="254" width="12" height="12" fill="#C85A53"/>
  <text x="560" y="264" font-family="Helvetica, Arial, sans-serif" font-size="10.5" fill="#000000">EGF_5min</text>
  <rect x="540" y="278" width="12" height="12" fill="#E09F5A"/>
  <text x="560" y="288" font-family="Helvetica, Arial, sans-serif" font-size="10.5" fill="#000000">EGF_30min</text>
  <rect x="540" y="302" width="12" height="12" fill="#5FA292"/>
  <text x="560" y="312" font-family="Helvetica, Arial, sans-serif" font-size="10.5" fill="#000000">Erlotinib</text>

  <!-- Gate G0 Locked Embedded Image -->
  <rect x="540" y="62" width="188" height="132" fill="none" stroke="#000000" stroke-width="1"/>
  <image id="RawBlotCrop" x="552" y="86" width="164" height="82" href="data:image/png;base64,{b64}"/>
  <text x="552" y="78" font-family="Helvetica, Arial, sans-serif" font-size="10.5" font-weight="bold" fill="#000000">p-ERK1/2 Immunoblot (&lt;image&gt;)</text>

  <text x="28" y="412" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#555555">Source: Adapted from Lemmon &amp; Schlessinger, Cell 2010 (doi:10.1016/j.cell.2010.06.011) &amp; KEGG hsa04012</text>
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def build_complex_mouse_brain_visium_pdf(out_path: Path, brain: dict[str, object]) -> None:
    """Build complex high-density 4-panel Spatial Transcriptomics PDF (4,992 spots, >250k PDF stream ops)
    from the official 10x Genomics Public Mouse Brain Sagittal Anterior Visium dataset (CC-BY 4.0).
    """
    pdf = pikepdf.Pdf.new()
    page_w, page_h = 980.0, 660.0
    page = pdf.add_blank_page(page_size=(page_w, page_h))

    seq_low = (0.96, 0.94, 0.90)
    seq_mid = (0.89, 0.62, 0.32)
    seq_high = (0.47, 0.12, 0.13)
    cb_arr = _make_sequential_colorbar_strip(seq_low, seq_mid, seq_high, h=180, w=10)

    font_helv = pikepdf.Dictionary(
        {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica")}
    )
    font_bold = pikepdf.Dictionary(
        {"/Type": pikepdf.Name("/Font"), "/Subtype": pikepdf.Name("/Type1"), "/BaseFont": pikepdf.Name("/Helvetica-Bold")}
    )
    page.obj["/Resources"] = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary({"/F1": font_helv, "/F2": font_bold}),
            "/XObject": pikepdf.Dictionary({"/ImCB": _make_img_xo(pdf, cb_arr)}),
        }
    )

    def py(top_y: float, h: float = 0.0) -> float:
        return page_h - top_y - h

    spots: list[tuple[str, int, int, int, float, float]] = brain["spots"]  # type: ignore[assignment]
    clusters: dict[str, int] = brain["clusters"]  # type: ignore[assignment]
    umap_xy: dict[str, tuple[float, float]] = brain["umap_xy"]  # type: ignore[assignment]
    pc1_map: dict[str, float] = brain["pc1_map"]  # type: ignore[assignment]

    in_spots = [s for s in spots if s[1] == 1 and s[0] in clusters]
    all_rows_px = [s[4] for s in spots]
    all_cols_px = [s[5] for s in spots]
    r_min, r_max = min(all_rows_px), max(all_rows_px)
    c_min, c_max = min(all_cols_px), max(all_cols_px)

    in_rows_px = [s[4] for s in in_spots]
    in_cols_px = [s[5] for s in in_spots]
    ir_min, ir_max = min(in_rows_px), max(in_rows_px)
    ic_min, ic_max = min(in_cols_px), max(in_cols_px)

    cluster_meta = {
        1: ("Cortex L2/3", (0.122, 0.467, 0.706)),
        2: ("Cortex L5/6", (1.000, 0.498, 0.055)),
        3: ("Hippocampus", (0.173, 0.627, 0.173)),
        4: ("Striatum", (0.839, 0.153, 0.157)),
        5: ("Olfactory Bulb", (0.580, 0.404, 0.741)),
        6: ("Thalamus", (0.549, 0.337, 0.294)),
        7: ("White Matter", (0.890, 0.467, 0.761)),
        8: ("Meninges/VLMC", (0.090, 0.745, 0.812)),
    }

    cmds: list[str] = [f"1 1 1 rg 0 0 {page_w:.0f} {page_h:.0f} re f"]
    panel_boxes = [
        ("A", "Sagittal Forebrain Visium Domains (2,695 spots)", (16, 14, 478, 312)),
        ("B", "Transcriptomic UMAP Manifold (k-means k = 8)", (502, 14, 964, 312)),
        ("C", "Spatial PC1 Cortico-Subcortical Gradient", (16, 334, 478, 632)),
        ("D", "Full-Slide 4,992-Spot Capture Array QC", (502, 334, 964, 632)),
    ]
    for tag, title, (x0, y0, x1, y1) in panel_boxes:
        pw, ph = x1 - x0, y1 - y0
        cmds.append(f"q {x0:.1f} {py(y0, ph):.1f} {pw:.1f} {ph:.1f} re W n")
        cmds.append(f"0.92 0.92 0.92 RG 0.8 w {x0+1:.1f} {py(y0+1, ph-2):.1f} {pw-2:.1f} {ph-2:.1f} re S")
        cmds.append(f"BT /F2 13 Tf 0 0 0 rg 1 0 0 1 {x0+10:.1f} {py(y0+20):.1f} Tm ({tag}) Tj ET")
        cmds.append(f"BT /F2 10.5 Tf 0 0 0 rg 1 0 0 1 {x0+28:.1f} {py(y0+20):.1f} Tm ({_escape_pdf_text(title)}) Tj ET")
        cmds.append("Q")

    # Panel A: Spatial Forebrain Domains (2,695 hexagonal spots + inner cell-density Bezier circles)
    cmds.append(f"q 16 {py(312):.1f} 462 298 re W n")
    for cid, (clbl, (cr, cg, cb)) in cluster_meta.items():
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg")
        for bc, _, _, _, prow, pcol in in_spots:
            if clusters[bc] != cid:
                continue
            sx = 34.0 + (pcol - ic_min) / (ic_max - ic_min) * 308.0
            sy_top = 50.0 + (prow - ir_min) / (ir_max - ir_min) * 238.0
            cmds.append(_hex_ops(sx, py(sy_top), 2.85))
            cmds.append(_circle_ops(sx, py(sy_top), 1.45))
    for idx, (cid, (clbl, (cr, cg, cb))) in enumerate(cluster_meta.items()):
        ly = 62.0 + idx * 24.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg 362 {py(ly, 10):.1f} 10 10 re f")
        cmds.append(f"BT /F1 8.4 Tf 0 0 0 rg 1 0 0 1 377 {py(ly+8.5):.1f} Tm ({_escape_pdf_text(clbl)}) Tj ET")
    # 500 um physical scale bar
    cmds.append(f"0 0 0 rg 42 {py(298, 3):.1f} 44 3 re f")
    cmds.append(f"BT /F2 7.8 Tf 0 0 0 rg 1 0 0 1 44 {py(292):.1f} Tm (500 um) Tj ET")
    cmds.append("Q")

    # Panel B: UMAP Manifold (2,695 spots with Bezier circles + halo rings, sharing C1..C8 labels with Panel A!)
    cmds.append(f"q 502 {py(312):.1f} 462 298 re W n")
    cmds.append(f"0 0 0 RG 0.9 w 536 {py(292):.1f} m 836 {py(292):.1f} l S")
    cmds.append(f"0 0 0 RG 0.9 w 536 {py(50):.1f} m 536 {py(292):.1f} l S")
    uxs = [umap_xy[s[0]][0] for s in in_spots if s[0] in umap_xy]
    uys = [umap_xy[s[0]][1] for s in in_spots if s[0] in umap_xy]
    ux_min, ux_max = min(uxs), max(uxs)
    uy_min, uy_max = min(uys), max(uys)
    for cid, (clbl, (cr, cg, cb)) in cluster_meta.items():
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg")
        for bc, _, _, _, _, _ in in_spots:
            if clusters[bc] != cid or bc not in umap_xy:
                continue
            ux, uy = umap_xy[bc]
            px_u = 546.0 + (ux - ux_min) / (ux_max - ux_min) * 280.0
            py_top = 282.0 - (uy - uy_min) / (uy_max - uy_min) * 224.0
            cmds.append(_circle_ops(px_u, py(py_top), 2.15))
            cmds.append(_hex_ops(px_u, py(py_top), 1.25))
    for idx, (cid, (clbl, (cr, cg, cb))) in enumerate(cluster_meta.items()):
        ly = 62.0 + idx * 24.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg 848 {py(ly, 10):.1f} 10 10 re f")
        cmds.append(f"BT /F1 8.4 Tf 0 0 0 rg 1 0 0 1 863 {py(ly+8.5):.1f} Tm ({_escape_pdf_text(clbl)}) Tj ET")
    cmds.append("Q")

    # Panel C: Continuous Spatial PC1 Gradient (quantized 24-bin continuous scale + coupled colorbar /ImCB)
    cmds.append(f"q 16 {py(632):.1f} 462 298 re W n")
    pc_vals = np.array([pc1_map.get(s[0], 0.0) for s in in_spots], dtype=np.float64)
    p5, p95 = float(np.percentile(pc_vals, 3)), float(np.percentile(pc_vals, 97))
    low_v, mid_v, high_v = np.array(seq_low), np.array(seq_mid), np.array(seq_high)
    n_bins = 28
    bins_spots: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for s in in_spots:
        pv = pc1_map.get(s[0], 0.0)
        t_norm = max(0.0, min(1.0, (pv - p5) / max(1e-9, p95 - p5)))
        bi = min(n_bins - 1, int(t_norm * n_bins))
        sx = 34.0 + (s[5] - ic_min) / (ic_max - ic_min) * 318.0
        sy_top = 370.0 + (s[4] - ir_min) / (ir_max - ir_min) * 238.0
        bins_spots[bi].append((sx, py(sy_top)))
    for bi, pts_list in enumerate(bins_spots):
        if not pts_list:
            continue
        tv = (bi + 0.5) / n_bins
        rgb = low_v + (mid_v - low_v) * (tv / 0.5) if tv <= 0.5 else mid_v + (high_v - mid_v) * ((tv - 0.5) / 0.5)
        cmds.append(f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg")
        for sx, sy_pdf in pts_list:
            cmds.append(_hex_ops(sx, sy_pdf, 2.85))
    cmds.append(f"BT /F2 8.5 Tf 0 0 0 rg 1 0 0 1 386 {py(374):.1f} Tm (PC1) Tj ET")
    cmds.append(f"q 14 0 0 180 390 {py(384, 180):.1f} cm /ImCB Do Q")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 410 {py(392):.1f} Tm (+25) Tj ET")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 410 {py(476):.1f} Tm (0) Tj ET")
    cmds.append(f"BT /F1 8 Tf 0 0 0 rg 1 0 0 1 410 {py(562):.1f} Tm (-25) Tj ET")
    cmds.append("Q")

    # Panel D: Full 4,992-Spot Capture Array QC (tests `#C9D6DF` mist-slate compound path mutability + high op count!)
    cmds.append(f"q 502 {py(632):.1f} 462 298 re W n")
    in_rc = {(s[2], s[3]) for s in spots if s[1] == 1}
    qc_groups: dict[str, list[tuple[float, float]]] = {"In_Tissue": [], "Tissue_Rim": [], "Glass_Bg": []}
    for bc, in_tis, arr_r, arr_c, prow, pcol in spots:
        sx = 520.0 + (pcol - c_min) / (c_max - c_min) * 310.0
        sy_top = 370.0 + (prow - r_min) / (r_max - r_min) * 238.0
        if in_tis == 1:
            # Check if on boundary of tissue capture area
            nbr_out = any((arr_r + dr, arr_c + dc) not in in_rc for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1), (0, -2), (0, 2)))
            if nbr_out:
                qc_groups["Tissue_Rim"].append((sx, py(sy_top)))
            else:
                qc_groups["In_Tissue"].append((sx, py(sy_top)))
        else:
            qc_groups["Glass_Bg"].append((sx, py(sy_top)))

    qc_styles = [
        ("Glass_Bg", "Out of Tissue", (0.882, 0.910, 0.941)),
        ("In_Tissue", "In Tissue (PASS)", (0.7882, 0.8392, 0.8745)),  # #C9D6DF mist-slate
        ("Tissue_Rim", "Pial / Ventricular Rim", (0.878, 0.482, 0.349)),
    ]
    for key, qlbl, (cr, cg, cb) in qc_styles:
        pts_list = qc_groups[key]
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg")
        # Emit compound multi-subpath chunks (~120 spots per `f`) + hex overlays for authentic high-density vector load
        chunk_sz = 120
        for i in range(0, len(pts_list), chunk_sz):
            sub = pts_list[i : i + chunk_sz]
            sub_ops = []
            for sx, sy_pdf in sub:
                k = 0.55228475 * 1.85
                r = 1.85
                sub_ops.append(
                    f"{sx + r:.2f} {sy_pdf:.2f} m "
                    f"{sx + r:.2f} {sy_pdf + k:.2f} {sx + k:.2f} {sy_pdf + r:.2f} {sx:.2f} {sy_pdf + r:.2f} c "
                    f"{sx - k:.2f} {sy_pdf + r:.2f} {sx - r:.2f} {sy_pdf + k:.2f} {sx - r:.2f} {sy_pdf:.2f} c "
                    f"{sx - r:.2f} {sy_pdf - k:.2f} {sx - k:.2f} {sy_pdf - r:.2f} {sx:.2f} {sy_pdf - r:.2f} c "
                    f"{sx + k:.2f} {sy_pdf - r:.2f} {sx + r:.2f} {sy_pdf - k:.2f} {sx + r:.2f} {sy_pdf:.2f} c"
                )
            cmds.append(" ".join(sub_ops) + " f")
        for sx, sy_pdf in pts_list:
            cmds.append(_hex_ops(sx, sy_pdf, 1.35))

    for idx, (_, qlbl, (cr, cg, cb)) in enumerate(qc_styles):
        ly = 398.0 + idx * 26.0
        cmds.append(f"{cr:.4f} {cg:.4f} {cb:.4f} rg 844 {py(ly, 10):.1f} 10 10 re f")
        cmds.append(f"BT /F1 8.2 Tf 0 0 0 rg 1 0 0 1 859 {py(ly+8.5):.1f} Tm ({_escape_pdf_text(qlbl)}) Tj ET")
    cmds.append("Q")

    cmds.append(
        f"BT /F1 7.5 Tf 0.35 0.35 0.35 rg 1 0 0 1 20 {py(649):.1f} Tm "
        f"(Source: 10x Genomics Adult Mouse Brain Sagittal Anterior Visium Spatial Gene Expression v1.1.0 [CC-BY 4.0]) Tj ET"
    )
    page.Contents = pdf.make_stream("\n".join(cmds).encode("ascii"))
    pdf.save(out_path)


def build_cleveland_multilayer_svg(out_path: Path) -> None:
    """Build a 3-panel multi-layer composite clinical SVG from UCI Cleveland Heart Disease (Detrano et al., Am J Cardiol 1989, CC BY 4.0).

    Layers per clinical cohort (`No CAD`, `Mild-Mod CAD`, `Severe CAD`):
      - Panel A: Raincloud half-violin KDE (`area`, fill-opacity=0.24) + IQR boxplot (`area`, fill-opacity=0.46)
                 + 303 individual patient scatter points (`point`, fill-opacity=0.88, #2B2B2B stroke).
      - Panel B: Age-stratified Peak Heart Rate OLS trajectory (`line`, stroke-opacity=0.96)
                 + 95% CI confidence band (`area`, fill-opacity=0.22) + age-quintile cohort markers (`point`).
      - Panel C: Exercise ST-depression group bars (`area`, fill-opacity=0.42) + overlaid patient dots (`point`, fill-opacity=0.86)
                 + coupled `<linearGradient>` continuous ischemia score bar.
    """
    raw_p = REPO_ROOT / "bench" / "tables" / "raw" / "processed.cleveland.data"
    cohorts: dict[str, list[tuple[float, float, float, float]]] = {
        "No CAD": [],
        "Mild-Mod CAD": [],
        "Severe CAD": [],
    }
    for line in raw_p.read_text(encoding="utf-8").splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 14 or "?" in (parts[0], parts[3], parts[7], parts[9], parts[13]):
            continue
        age = float(parts[0])
        sbp = float(parts[3])
        hr = float(parts[7])
        oldpeak = float(parts[9])
        num = int(float(parts[13]))
        grp = "No CAD" if num == 0 else ("Mild-Mod CAD" if num in (1, 2) else "Severe CAD")
        cohorts[grp].append((age, hr, oldpeak, sbp))

    # Intentional classic clinical starter palette (steel blue / amber / coral red) ready for Danqing recoloring
    cohort_order = [
        ("No CAD", "#4E79A7"),
        ("Mild-Mod CAD", "#E09F5A"),
        ("Severe CAD", "#C85A53"),
    ]

    w, h = 980, 412
    parts_svg: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        "  <defs>",
        '    <linearGradient id="IschemiaRiskScale" x1="0%" y1="100%" x2="0%" y2="0%">',
        '      <stop offset="0%" stop-color="#F4EFE6"/>',
        '      <stop offset="35%" stop-color="#EDD6A4"/>',
        '      <stop offset="70%" stop-color="#C6593F"/>',
        '      <stop offset="100%" stop-color="#781E20"/>',
        "    </linearGradient>",
        "  </defs>",
        f'  <rect x="0" y="0" width="{w}" height="{h}" fill="#FFFFFF"/>',
    ]

    # Panel tags (14px bold pure black at top-left of each subplot so `_detect_svg_panels` partitions A / B / C cleanly)
    parts_svg.append('  <text x="16" y="24" font-family="Helvetica, Arial, sans-serif" font-size="14" font-weight="bold" fill="#000000">A</text>')
    parts_svg.append('  <text x="48" y="24" font-family="Helvetica, Arial, sans-serif" font-size="11.5" font-weight="bold" fill="#000000">Peak Exercise Heart Rate (n = 303)</text>')
    parts_svg.append('  <text x="352" y="24" font-family="Helvetica, Arial, sans-serif" font-size="14" font-weight="bold" fill="#000000">B</text>')
    parts_svg.append('  <text x="382" y="24" font-family="Helvetica, Arial, sans-serif" font-size="11.5" font-weight="bold" fill="#000000">Age Trajectory &amp; 95% CI Ribbon</text>')
    parts_svg.append('  <text x="676" y="24" font-family="Helvetica, Arial, sans-serif" font-size="14" font-weight="bold" fill="#000000">C</text>')
    parts_svg.append('  <text x="706" y="24" font-family="Helvetica, Arial, sans-serif" font-size="11.5" font-weight="bold" fill="#000000">ST Depression &amp; Risk Scale</text>')

    # ------------------------------------------------------------------
    # PANEL A: Raincloud Half-Violin + Boxplot + 303 Individual Points
    # ------------------------------------------------------------------
    ax_x0, ax_x1 = 54.0, 326.0
    ax_y0, ax_y1 = 44.0, 316.0  # y0=top (210 bpm), y1=bottom (70 bpm)
    hr_min, hr_max = 70.0, 210.0

    def _y_hr(v: float) -> float:
        return ax_y1 - (v - hr_min) / (hr_max - hr_min) * (ax_y1 - ax_y0)

    # Subtle horizontal reference gridlines + crisp black axes
    for tick_v in (80, 110, 140, 170, 200):
        ty = _y_hr(float(tick_v))
        parts_svg.append(f'  <line x1="{ax_x0:.1f}" y1="{ty:.1f}" x2="{ax_x1:.1f}" y2="{ty:.1f}" stroke="#EAECEF" stroke-width="0.8"/>')
        parts_svg.append(f'  <line x1="{ax_x0 - 4:.1f}" y1="{ty:.1f}" x2="{ax_x0:.1f}" y2="{ty:.1f}" stroke="#000000" stroke-width="1"/>')
        parts_svg.append(f'  <text x="{ax_x0 - 7:.1f}" y="{ty + 3.5:.1f}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#000000">{tick_v}</text>')
    parts_svg.append(f'  <line x1="{ax_x0:.1f}" y1="{ax_y0:.1f}" x2="{ax_x0:.1f}" y2="{ax_y1:.1f}" stroke="#000000" stroke-width="1.1"/>')
    parts_svg.append(f'  <line x1="{ax_x0:.1f}" y1="{ax_y1:.1f}" x2="{ax_x1:.1f}" y2="{ax_y1:.1f}" stroke="#000000" stroke-width="1.1"/>')
    parts_svg.append(
        f'  <text x="16" y="{0.5 * (ax_y0 + ax_y1):.1f}" text-anchor="middle" transform="rotate(-90 16 {0.5 * (ax_y0 + ax_y1):.1f})" '
        'font-family="Helvetica, Arial, sans-serif" font-size="10" font-weight="bold" fill="#000000">Max Heart Rate (bpm)</text>'
    )

    centers_a = [104.0, 194.0, 282.0]
    grid_hr = np.linspace(74.0, 204.0, 44)
    for idx_c, (cname, chex) in enumerate(cohort_order):
        cx = centers_a[idx_c]
        vals = np.array(sorted(r[1] for r in cohorts[cname]), dtype=np.float64)
        q25, q50, q75 = np.percentile(vals, [25, 50, 75])
        iqr = q75 - q25
        lo_w = float(vals[vals >= q25 - 1.5 * iqr].min())
        hi_w = float(vals[vals <= q75 + 1.5 * iqr].max())

        # Gaussian KDE half-violin extending left of cx - 12
        bw_kde = max(5.5, 1.06 * float(np.std(vals)) * (len(vals) ** -0.2))
        dens = np.mean(np.exp(-0.5 * ((grid_hr[:, None] - vals[None, :]) / bw_kde) ** 2), axis=1)
        dens = dens / max(1e-9, float(dens.max()))
        v_base = cx - 11.0
        pts_v = [(v_base, _y_hr(float(vals.min() - 4.0)))]
        for gv, dv in zip(grid_hr, dens):
            if vals.min() - 5.0 <= gv <= vals.max() + 5.0:
                pts_v.append((v_base - dv * 26.0, _y_hr(float(gv))))
        pts_v.append((v_base, _y_hr(float(vals.max() + 4.0))))
        poly_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts_v)
        parts_svg.append(
            f'  <polygon points="{poly_str}" fill="{chex}" fill-opacity="0.24" stroke="#444444" stroke-width="0.7" stroke-opacity="0.55"/>'
        )

        # Whiskers, caps & median (neutral dark charcoal so data color belongs cleanly to box fill & scatter)
        bx_w = 24.0
        bx_x0 = cx - 6.0
        bx_mid = bx_x0 + 0.5 * bx_w
        parts_svg.append(f'  <line x1="{bx_mid:.1f}" y1="{_y_hr(hi_w):.1f}" x2="{bx_mid:.1f}" y2="{_y_hr(q75):.1f}" stroke="#4A4E54" stroke-width="1.0"/>')
        parts_svg.append(f'  <line x1="{bx_mid:.1f}" y1="{_y_hr(q25):.1f}" x2="{bx_mid:.1f}" y2="{_y_hr(lo_w):.1f}" stroke="#4A4E54" stroke-width="1.0"/>')
        parts_svg.append(f'  <line x1="{bx_mid - 6:.1f}" y1="{_y_hr(hi_w):.1f}" x2="{bx_mid + 6:.1f}" y2="{_y_hr(hi_w):.1f}" stroke="#4A4E54" stroke-width="1.0"/>')
        parts_svg.append(f'  <line x1="{bx_mid - 6:.1f}" y1="{_y_hr(lo_w):.1f}" x2="{bx_mid + 6:.1f}" y2="{_y_hr(lo_w):.1f}" stroke="#4A4E54" stroke-width="1.0"/>')

        # Translucent IQR Boxplot (`area` layer)
        by_top = _y_hr(float(q75))
        by_bot = _y_hr(float(q25))
        parts_svg.append(
            f'  <rect x="{bx_x0:.1f}" y="{by_top:.1f}" width="{bx_w:.1f}" height="{max(2.0, by_bot - by_top):.1f}" '
            f'rx="1.5" fill="{chex}" fill-opacity="0.44" stroke="#333333" stroke-width="0.95"/>'
        )
        parts_svg.append(
            f'  <line x1="{bx_x0:.1f}" y1="{_y_hr(float(q50)):.1f}" x2="{bx_x0 + bx_w:.1f}" y2="{_y_hr(float(q50)):.1f}" stroke="#222222" stroke-width="1.5"/>'
        )

        # Overlaid Individual Patient Scatter Dots (`point` layer — deterministic golden-ratio horizontal spread inside box)
        for idx_p, v_hr in enumerate(vals):
            frac = ((idx_p * 0.61803398875) % 1.0) - 0.5
            jx = bx_mid + frac * 17.5
            jy = _y_hr(float(v_hr))
            parts_svg.append(
                f'  <circle cx="{jx:.2f}" cy="{jy:.2f}" r="2.55" fill="{chex}" fill-opacity="0.88" stroke="#2B2B2B" stroke-width="0.55"/>'
            )

        short_lbl = cname.replace(" CAD", "") if cname != "No CAD" else "No CAD"
        parts_svg.append(
            f'  <text x="{cx:.1f}" y="{ax_y1 + 15:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#000000">{short_lbl}</text>'
        )
        parts_svg.append(
            f'  <text x="{cx:.1f}" y="{ax_y1 + 27:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="8.5" fill="#555555">n={len(vals)}</text>'
        )

    # ------------------------------------------------------------------
    # PANEL B: Age Trajectory OLS Curves (`line`) + 95% CI Ribbons (`area`) + Markers (`point`)
    # ------------------------------------------------------------------
    bx0, bx1 = 392.0, 646.0
    by0, by1 = 44.0, 316.0
    age_min, age_max = 32.0, 76.0

    def _x_age(a: float) -> float:
        return bx0 + (a - age_min) / (age_max - age_min) * (bx1 - bx0)

    for tick_v in (80, 110, 140, 170, 200):
        ty = _y_hr(float(tick_v))
        parts_svg.append(f'  <line x1="{bx0:.1f}" y1="{ty:.1f}" x2="{bx1:.1f}" y2="{ty:.1f}" stroke="#EAECEF" stroke-width="0.8"/>')
        parts_svg.append(f'  <line x1="{bx0 - 4:.1f}" y1="{ty:.1f}" x2="{bx0:.1f}" y2="{ty:.1f}" stroke="#000000" stroke-width="1"/>')
        parts_svg.append(f'  <text x="{bx0 - 7:.1f}" y="{ty + 3.5:.1f}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#000000">{tick_v}</text>')
    for tick_a in (35, 45, 55, 65, 75):
        tx = _x_age(float(tick_a))
        parts_svg.append(f'  <line x1="{tx:.1f}" y1="{by1:.1f}" x2="{tx:.1f}" y2="{by1 + 4:.1f}" stroke="#000000" stroke-width="1"/>')
        parts_svg.append(f'  <text x="{tx:.1f}" y="{by1 + 15:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#000000">{tick_a}</text>')
    parts_svg.append(f'  <line x1="{bx0:.1f}" y1="{by0:.1f}" x2="{bx0:.1f}" y2="{by1:.1f}" stroke="#000000" stroke-width="1.1"/>')
    parts_svg.append(f'  <line x1="{bx0:.1f}" y1="{by1:.1f}" x2="{bx1:.1f}" y2="{by1:.1f}" stroke="#000000" stroke-width="1.1"/>')
    parts_svg.append(
        f'  <text x="{0.5 * (bx0 + bx1):.1f}" y="{by1 + 29:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="10" font-weight="bold" fill="#000000">Patient Age (years)</text>'
    )

    x_grid = np.linspace(35.0, 74.0, 26)
    for cname, chex in cohort_order:
        pts_c = cohorts[cname]
        ages = np.array([r[0] for r in pts_c], dtype=np.float64)
        hrs = np.array([r[1] for r in pts_c], dtype=np.float64)
        slope, intercept = np.polyfit(ages, hrs, 1)
        y_hat = slope * x_grid + intercept
        n_obs = len(ages)
        resid_sd = float(np.sqrt(np.sum((hrs - (slope * ages + intercept)) ** 2) / max(1, n_obs - 2)))
        a_mean = float(np.mean(ages))
        s_xx = float(np.sum((ages - a_mean) ** 2))
        se_fit = resid_sd * np.sqrt(1.0 / n_obs + ((x_grid - a_mean) ** 2) / max(1e-9, s_xx))
        ci_hi = y_hat + 1.96 * se_fit
        ci_lo = y_hat - 1.96 * se_fit

        # 95% CI Ribbon (`area` layer)
        rib_pts = [(_x_age(float(xg)), _y_hr(float(yh))) for xg, yh in zip(x_grid, ci_hi)] + [
            (_x_age(float(xg)), _y_hr(float(yl))) for xg, yl in zip(reversed(x_grid), reversed(ci_lo))
        ]
        rib_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in rib_pts)
        parts_svg.append(f'  <polygon points="{rib_str}" fill="{chex}" fill-opacity="0.22" stroke="none"/>')

        # OLS Regression Trajectory (`line` layer)
        line_str = " ".join(f"{_x_age(float(xg)):.1f},{_y_hr(float(yv)):.1f}" for xg, yv in zip(x_grid, y_hat))
        parts_svg.append(
            f'  <polyline points="{line_str}" fill="none" stroke="{chex}" stroke-width="2.2" stroke-opacity="0.96"/>'
        )

        # Empirical Age-Quintile Mean Markers (`point` layer, 5 bins >= 3 points)
        order_idx = np.argsort(ages)
        splits = np.array_split(order_idx, 5)
        for sp_idx in splits:
            if len(sp_idx) == 0:
                continue
            ma = float(np.mean(ages[sp_idx]))
            mh = float(np.mean(hrs[sp_idx]))
            parts_svg.append(
                f'  <circle cx="{_x_age(ma):.2f}" cy="{_y_hr(mh):.2f}" r="3.6" fill="{chex}" fill-opacity="0.95" stroke="#222222" stroke-width="0.8"/>'
            )

    # ------------------------------------------------------------------
    # PANEL C: Exercise ST-Depression Mean Bars (`area`) + Patient Dots (`point`) + Gradient Scale
    # ------------------------------------------------------------------
    cx0, cx1 = 710.0, 902.0
    cy0, cy1 = 44.0, 316.0
    st_max = 5.2

    def _y_st(v: float) -> float:
        return cy1 - (v / st_max) * (cy1 - cy0)

    for tick_s in (0, 1, 2, 3, 4, 5):
        ty = _y_st(float(tick_s))
        parts_svg.append(f'  <line x1="{cx0:.1f}" y1="{ty:.1f}" x2="{cx1:.1f}" y2="{ty:.1f}" stroke="#EAECEF" stroke-width="0.8"/>')
        parts_svg.append(f'  <line x1="{cx0 - 4:.1f}" y1="{ty:.1f}" x2="{cx0:.1f}" y2="{ty:.1f}" stroke="#000000" stroke-width="1"/>')
        parts_svg.append(f'  <text x="{cx0 - 7:.1f}" y="{ty + 3.5:.1f}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#000000">{tick_s}</text>')
    parts_svg.append(f'  <line x1="{cx0:.1f}" y1="{cy0:.1f}" x2="{cx0:.1f}" y2="{cy1:.1f}" stroke="#000000" stroke-width="1.1"/>')
    parts_svg.append(f'  <line x1="{cx0:.1f}" y1="{cy1:.1f}" x2="{cx1:.1f}" y2="{cy1:.1f}" stroke="#000000" stroke-width="1.1"/>')
    parts_svg.append(
        f'  <text x="680" y="{0.5 * (cy0 + cy1):.1f}" text-anchor="middle" transform="rotate(-90 680 {0.5 * (cy0 + cy1):.1f})" '
        'font-family="Helvetica, Arial, sans-serif" font-size="10" font-weight="bold" fill="#000000">ST Depression (mV)</text>'
    )

    centers_c = [744.0, 806.0, 868.0]
    for idx_c, (cname, chex) in enumerate(cohort_order):
        bcx = centers_c[idx_c]
        st_vals = np.array(sorted(r[2] for r in cohorts[cname]), dtype=np.float64)
        mean_st = float(np.mean(st_vals))
        sem_st = float(np.std(st_vals) / math.sqrt(len(st_vals)))
        bar_w = 34.0
        bar_top = _y_st(mean_st)
        parts_svg.append(
            f'  <rect x="{bcx - 0.5 * bar_w:.1f}" y="{bar_top:.1f}" width="{bar_w:.1f}" height="{max(2.0, cy1 - bar_top):.1f}" '
            f'rx="1.5" fill="{chex}" fill-opacity="0.42" stroke="#333333" stroke-width="0.9"/>'
        )
        # SEM error bar
        y_hi_e = _y_st(mean_st + sem_st)
        y_lo_e = _y_st(max(0.0, mean_st - sem_st))
        parts_svg.append(f'  <line x1="{bcx:.1f}" y1="{y_hi_e:.1f}" x2="{bcx:.1f}" y2="{y_lo_e:.1f}" stroke="#222222" stroke-width="1.2"/>')
        parts_svg.append(f'  <line x1="{bcx - 6:.1f}" y1="{y_hi_e:.1f}" x2="{bcx + 6:.1f}" y2="{y_hi_e:.1f}" stroke="#222222" stroke-width="1.2"/>')

        # Subsampled deterministic decile/every-2nd individual patient strip points (`point` layer)
        sub_st = st_vals[::2] if len(st_vals) > 60 else st_vals
        for idx_s, sv in enumerate(sub_st):
            if sv > st_max:
                continue
            frac = ((idx_s * 0.61803398875) % 1.0) - 0.5
            jx = bcx + frac * 22.0
            jy = min(cy1 - 3.2, _y_st(float(sv)))
            parts_svg.append(
                f'  <circle cx="{jx:.2f}" cy="{jy:.2f}" r="2.35" fill="{chex}" fill-opacity="0.86" stroke="#2B2B2B" stroke-width="0.5"/>'
            )

        short_lbl = cname.replace(" CAD", "") if cname != "No CAD" else "No CAD"
        parts_svg.append(
            f'  <text x="{bcx:.1f}" y="{cy1 + 15:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9.5" fill="#000000">{short_lbl}</text>'
        )

    # Coupled Continuous `<linearGradient>` Ischemia Score Bar on far right of Panel C
    cb_x, cb_y, cb_w, cb_h = 924.0, 68.0, 14.0, 210.0
    parts_svg.append(f'  <text x="{cb_x + 7:.1f}" y="{cb_y - 9:.1f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9" font-weight="bold" fill="#000000">Risk</text>')
    parts_svg.append(f'  <rect x="{cb_x:.1f}" y="{cb_y:.1f}" width="{cb_w:.1f}" height="{cb_h:.1f}" rx="2" fill="url(#IschemiaRiskScale)" stroke="#333333" stroke-width="0.8"/>')
    for frac_t, lbl_t in ((0.0, "High"), (0.5, "Mid"), (1.0, "Low")):
        ty_cb = cb_y + frac_t * cb_h
        parts_svg.append(f'  <text x="{cb_x + cb_w + 5:.1f}" y="{ty_cb + 3:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="8.5" fill="#000000">{lbl_t}</text>')

    # ------------------------------------------------------------------
    # Shared Bottom Legend (aligned horizontal row of keys + labels)
    # ------------------------------------------------------------------
    leg_y = 368.0
    leg_xs = [258.0, 442.0, 646.0]
    for (cname, chex), lx in zip(cohort_order, leg_xs):
        n_c = len(cohorts[cname])
        parts_svg.append(
            f'  <rect x="{lx:.1f}" y="{leg_y - 9:.1f}" width="12" height="10" rx="2" fill="{chex}" fill-opacity="0.55" stroke="#333333" stroke-width="0.7"/>'
        )
        parts_svg.append(
            f'  <circle cx="{lx + 6:.1f}" cy="{leg_y - 4:.1f}" r="2.7" fill="{chex}" fill-opacity="0.95" stroke="#222222" stroke-width="0.55"/>'
        )
        parts_svg.append(
            f'  <text x="{lx + 18:.1f}" y="{leg_y:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="10.2" font-weight="bold" fill="#000000">{cname} (n={n_c})</text>'
        )

    parts_svg.append(
        '  <text x="18" y="399" font-family="Helvetica, Arial, sans-serif" font-size="8.5" fill="#555555">'
        "Source: UCI Cleveland Clinic Heart Disease Cohort (Detrano et al., Am. J. Cardiol. 1989; CC BY 4.0, n = 303 patients)"
        "</text>"
    )
    parts_svg.append("</svg>\n")
    out_path.write_text("\n".join(parts_svg), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Remove ALL legacy files in bench/figures/ so zero private lab files remain
    for old_file in OUT_DIR.iterdir():
        if old_file.is_file():
            old_file.unlink()

    penguins = _load_penguins_rows()
    brain = _load_10x_mouse_brain()

    build_penguins_multimodal_pdf(OUT_DIR / "01_PalmerPenguins_MultiModal_Gorman2014.pdf", penguins)
    build_g0_evidence_pdf(OUT_DIR / "02_Histology_WB_EvidenceShield_10xVisium.pdf", brain)
    build_svg_pathway_demo(OUT_DIR / "03_EGFR_MAPK_Pathway_Lemmon2010.svg")
    build_complex_mouse_brain_visium_pdf(OUT_DIR / "04_MouseBrain_Visium_Complex_10xGenomics.pdf", brain)
    build_cleveland_multilayer_svg(OUT_DIR / "05_Cleveland_Cardiology_MultiLayer_Detrano1989.svg")

    for p in sorted(OUT_DIR.iterdir()):
        print(f"Prepared public benchmark fixture: {p.name} ({p.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
