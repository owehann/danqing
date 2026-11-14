"""Gate G0: Raw Experimental Evidence Shield (Western Blots, Gels, H&E/IHC Crops, Fluorescence Microscopy).

Implements conservative Fail-Closed classification on all embedded 2D raster images so wet-lab physical
evidence is 100% SHA-256 byte-locked while coupled colorbars and proven 1D-manifold synthetic heatmaps are
unlocked for lossless LUT remapping.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

import numpy as np

from .color_science import (
    extract_1d_lut_from_strip,
    oklab_to_oklch,
    srgb01_to_hex,
    srgb_to_oklab,
    test_2d_image_1d_manifold,
)
from .ir import EvidenceRegion

_BLOT_KEYWORDS = (
    "kda",
    "mw",
    "gapdh",
    "actin",
    "b-actin",
    "β-actin",
    "tubulin",
    "vinculin",
    "histone",
    "hsp90",
    "ponceau",
    "coomassie",
    "blot",
    "ip:",
    "ib:",
    "lysate",
)

_FLUOR_KEYWORDS = (
    "dapi",
    "hoechst",
    "gfp",
    "rfp",
    "egfp",
    "mcherry",
    "cy3",
    "cy5",
    "fitc",
    "tritc",
    "alexa",
    "merge",
    "rnascope",
    "codex",
)


def classify_raster_object(
    xobject_name: str,
    panel_id: str,
    bbox: tuple[float, float, float, float],
    rgb01: np.ndarray,
    raw_stream_bytes: bytes,
    nearby_texts: Sequence[str],
    known_colorbar_luts: Iterable[np.ndarray] = (),
) -> tuple[EvidenceRegion, np.ndarray | None, bool, float]:
    """Classify a decoded (H, W, 3) [0,1] PDF/SVG raster image under Gate G0.

    Returns:
        (EvidenceRegion, extracted_lut_if_colorbar_or_1d_heatmap, is_diverging, midpoint_t)
    """
    h, w, _ = rgb01.shape
    sha = hashlib.sha256(raw_stream_bytes).hexdigest()
    joined_txt = " ".join(t.lower() for t in nearby_texts)

    # 1. Check 1D Colorbar Strip: narrow geometry OR literally 1-8 px minor dimension with smooth 1D gradient
    bx0, by0, bx1, by1 = bbox
    disp_w = max(1e-3, abs(bx1 - bx0))
    disp_h = max(1e-3, abs(by1 - by0))
    disp_aspect = max(disp_w / disp_h, disp_h / disp_w)
    px_minor = min(h, w)
    px_major = max(h, w)

    if (px_minor <= 12 and px_major >= 24) or (disp_aspect >= 4.2 and px_minor <= 64 and px_major >= 32):
        # Verify scanlines perpendicular to major axis are nearly constant (true 1D gradient strip)
        cross_std = float(rgb01.std(axis=1).mean() if h >= w else rgb01.std(axis=0).mean())
        major_span = float(np.ptp(rgb01.mean(axis=1 if h >= w else 0), axis=0).max())
        if cross_std < 0.035 and major_span > 0.08:
            lut, is_div, mid_t = extract_1d_lut_from_strip(rgb01, n=256)
            return (
                EvidenceRegion(
                    region_id=f"ev_{xobject_name.lstrip('/')}",
                    xobject_name=xobject_name,
                    panel_id=panel_id,
                    bbox=bbox,
                    width_px=w,
                    height_px=h,
                    mutability="class3_symbolic_mutable",
                    subtype_label="colorbar_strip",
                    sha256_original=sha,
                    reason="一维单调渐变图例色条 (Coupled Colorbar)，与面板连续数据同步重映射",
                ),
                lut,
                is_div,
                mid_t,
            )

    # Sample pixels for chromatic statistics
    flat = rgb01.reshape(-1, 3)
    if len(flat) > 8192:
        sampled = flat[:: max(1, len(flat) // 8192)][:8192]
    else:
        sampled = flat

    labs = srgb_to_oklab(sampled)
    lchs = oklab_to_oklch(labs)
    L_vals, C_vals, H_vals = lchs[:, 0], lchs[:, 1], lchs[:, 2]

    # 2. Check Western Blot / Gel Strip (Class 0 Sacrosanct!)
    c_p95 = float(np.percentile(C_vals, 95))
    has_blot_kw = any(kw in joined_txt for kw in _BLOT_KEYWORDS)
    if c_p95 < 0.028 or has_blot_kw:
        if c_p95 < 0.045:
            return (
                EvidenceRegion(
                    region_id=f"ev_{xobject_name.lstrip('/')}",
                    xobject_name=xobject_name,
                    panel_id=panel_id,
                    bbox=bbox,
                    width_px=w,
                    height_px=h,
                    mutability="class0_sacrosanct_evidence",
                    subtype_label="western_blot_or_gel",
                    sha256_original=sha,
                    reason="检测到实验条带/胶图灰度原片（G0 学术诚信红线：100% 字节锁定，仅允许联动周边分组矢量标注）",
                ),
                None,
                False,
                0.5,
            )

    # 3. Check Dark-Field Fluorescence Microscopy (Class 1 Pseudocolor)
    dark_frac = float(np.mean(L_vals < 0.18))
    has_fluor_kw = any(kw in joined_txt for kw in _FLUOR_KEYWORDS)
    if (dark_frac > 0.42 and float(np.percentile(C_vals, 98)) > 0.14) or (has_fluor_kw and dark_frac > 0.25):
        # Check if simultaneous Pure Red + Pure Green channels exist (deuteranopia trap!)
        bright = sampled[L_vals > 0.25]
        rg_conflict = False
        if len(bright) > 20:
            red_dom = np.mean((bright[:, 0] > 0.45) & (bright[:, 1] < 0.22) & (bright[:, 2] < 0.22))
            grn_dom = np.mean((bright[:, 1] > 0.45) & (bright[:, 0] < 0.22) & (bright[:, 2] < 0.22))
            rg_conflict = bool(red_dom > 0.02 and grn_dom > 0.02)
        return (
            EvidenceRegion(
                region_id=f"ev_{xobject_name.lstrip('/')}",
                xobject_name=xobject_name,
                panel_id=panel_id,
                bbox=bbox,
                width_px=w,
                height_px=h,
                mutability="class1_fluorescence_lut",
                subtype_label="fluorescence_microscopy",
                sha256_original=sha,
                can_linear_cvd_lut=rg_conflict,
                reason=(
                    "多通道荧光显微原片（默认字节锁定；检测到红+绿双通道，可一键启用『品红+绿』纯线性色盲无障碍映射）"
                    if rg_conflict
                    else "荧光显微原片（G0 默认字节锁定，保护原始光子强度线性度）"
                ),
            ),
            None,
            False,
            0.5,
        )

    # 4. Test 1D Chromatic Manifold for 2D Rasterized Data Heatmaps (geom_raster / ComplexHeatmap / imshow)
    manifold = test_2d_image_1d_manifold(rgb01, reference_luts=known_colorbar_luts)
    if manifold.is_1d_manifold:
        return (
            EvidenceRegion(
                region_id=f"ev_{xobject_name.lstrip('/')}",
                xobject_name=xobject_name,
                panel_id=panel_id,
                bbox=bbox,
                width_px=w,
                height_px=h,
                mutability="class3_symbolic_mutable",
                subtype_label="heatmap_raster_1d",
                sha256_original=sha,
                reason=f"满足 OKLab 一维色彩流形判据 (残差 p95={manifold.ortho_residual_p95:.3f})，识别为光栅化连续数据热图，支持无损重映射",
            ),
            manifold.lut_srgb,
            manifold.is_diverging,
            manifold.midpoint_t,
        )

    # 5. Fail-Closed Default -> Class 0 Pathology / Histology / Specimen Photograph (摘片! Extract stain obstacles!)
    chromatic = sampled[C_vals > 0.035]
    stain_hexes: list[str] = []
    if len(chromatic) >= 30:
        c_labs = srgb_to_oklab(chromatic)
        c_hues = oklab_to_oklch(c_labs)[:, 2]
        # Extract up to 2 dominant stain clusters (e.g., Eosin pink + Hematoxylin purple, or DAB brown)
        med_h = float(np.median(c_hues))
        mask_a = np.abs(((c_hues - med_h + 180.0) % 360.0) - 180.0) <= 60.0
        if np.any(mask_a):
            stain_hexes.append(srgb01_to_hex(chromatic[mask_a].mean(axis=0)))
        if np.any(~mask_a):
            stain_hexes.append(srgb01_to_hex(chromatic[~mask_a].mean(axis=0)))

    return (
        EvidenceRegion(
            region_id=f"ev_{xobject_name.lstrip('/')}",
            xobject_name=xobject_name,
            panel_id=panel_id,
            bbox=bbox,
            width_px=w,
            height_px=h,
            mutability="class0_sacrosanct_evidence",
            subtype_label="histology_or_specimen_photo",
            sha256_original=sha,
            dominant_stain_hex=stain_hexes,
            reason="病理摘片/实验实拍图像（呈多维染色云，已按 G0 字节级锁定保护，并提取主染色作为上方矢量标注避让色障）",
        ),
        None,
        False,
        0.5,
    )
