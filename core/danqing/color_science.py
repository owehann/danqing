"""Perceptual color science primitives for Danqing (OKLab/OKLCH, CIEDE2000, APCA, Machado CVD, 1D Manifold LUTs).

All functions are pure NumPy vectorized with zero GPL/AGPL dependencies (Apache-2.0).
References:
- Ottosson, B. (2020). A perceptual color space for image processing (OKLab / OKLCH).
- Sharma, G., Wu, W., & Dalal, E. N. (2005). The CIEDE2000 color-difference formula.
- Machado, G. M., Oliveira, M. M., & Fernandes, L. A. F. (2009). A physiologically-based model for simulation of color vision deficiency. IEEE TVCG.
- Myndex / Somers, A. (2022). Accessible Perceptual Contrast Algorithm (APCA 0.0.98G-4g).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Literal, Sequence

import numpy as np

CVDType = Literal["normal", "protan", "deutan", "tritan", "grayscale"]

# Machado et al. (2009) 100% severity matrices in linear RGB
_MACHADO_100: dict[str, np.ndarray] = {
    "protan": np.array(
        [
            [0.152286, 1.052583, -0.204868],
            [0.114503, 0.786281, 0.099216],
            [-0.003882, -0.048116, 1.051998],
        ],
        dtype=np.float64,
    ),
    "deutan": np.array(
        [
            [0.367322, 0.860646, -0.227968],
            [0.280085, 0.672501, 0.047413],
            [-0.011820, 0.042940, 0.968881],
        ],
        dtype=np.float64,
    ),
    "tritan": np.array(
        [
            [1.255528, -0.076749, -0.178779],
            [-0.078411, 0.930809, 0.147602],
            [0.004733, 0.691367, 0.303900],
        ],
        dtype=np.float64,
    ),
}

_M1_OKLAB = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float64,
)

_M2_OKLAB = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float64,
)

_M1_OKLAB_INV = np.linalg.inv(_M1_OKLAB)
_M2_OKLAB_INV = np.linalg.inv(_M2_OKLAB)

_M_SRGB_TO_XYZ_D65 = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)


def hex_to_srgb01(hex_str: str) -> np.ndarray:
    """Convert '#RRGGBB' or 'RRGGBB' to float64 [r, g, b] in [0, 1]."""
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_str!r}")
    return np.array(
        [int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0],
        dtype=np.float64,
    )


def srgb01_to_hex(rgb: Sequence[float] | np.ndarray) -> str:
    """Convert [r, g, b] in [0, 1] to '#RRGGBB'."""
    arr = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    r, g, b = (int(round(float(v) * 255.0)) for v in arr[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    """IEC 61966-2-1 sRGB [0,1] -> linear RGB [0,1]."""
    x = np.clip(np.asarray(srgb, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    """Linear RGB [0,1] -> IEC 61966-2-1 sRGB [0,1]."""
    x = np.clip(np.asarray(lin, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * (np.maximum(x, 0.0) ** (1.0 / 2.4)) - 0.055)


def srgb_to_oklab(srgb: np.ndarray) -> np.ndarray:
    """Convert (..., 3) sRGB [0,1] array to (..., 3) OKLab [L, a, b]."""
    lin = srgb_to_linear(srgb)
    lms = lin @ _M1_OKLAB.T
    lms_cbrt = np.cbrt(np.maximum(lms, 0.0))
    return lms_cbrt @ _M2_OKLAB.T


def oklab_to_linear_unclipped(lab: np.ndarray) -> np.ndarray:
    """Convert (..., 3) OKLab to unclipped linear RGB (for gamut checks)."""
    lms_cbrt = np.asarray(lab, dtype=np.float64) @ _M2_OKLAB_INV.T
    lms = lms_cbrt ** 3
    return lms @ _M1_OKLAB_INV.T


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """Convert (..., 3) OKLab to clipped sRGB [0,1]."""
    return linear_to_srgb(np.clip(oklab_to_linear_unclipped(lab), 0.0, 1.0))


def oklab_to_oklch(lab: np.ndarray) -> np.ndarray:
    """Convert (..., 3) OKLab [L, a, b] to OKLCH [L, C, h_deg in [0, 360)]."""
    arr = np.asarray(lab, dtype=np.float64)
    L = arr[..., 0]
    a = arr[..., 1]
    b = arr[..., 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360.0
    return np.stack([L, C, h], axis=-1)


def oklch_to_oklab(lch: np.ndarray) -> np.ndarray:
    """Convert (..., 3) OKLCH [L, C, h_deg] to OKLab [L, a, b]."""
    arr = np.asarray(lch, dtype=np.float64)
    L = arr[..., 0]
    C = arr[..., 1]
    rad = np.radians(arr[..., 2])
    return np.stack([L, C * np.cos(rad), C * np.sin(rad)], axis=-1)


def oklch_to_srgb_gamut_mapped(L: float, C: float, h_deg: float) -> np.ndarray:
    """Map single OKLCH color into sRGB gamut by preserving (L, h) and bisecting C."""
    L_clamped = float(np.clip(L, 0.02, 0.99))
    C_pos = max(0.0, float(C))
    rad = math.radians(float(h_deg))
    cos_h, sin_h = math.cos(rad), math.sin(rad)

    def in_gamut(c_val: float) -> tuple[bool, np.ndarray]:
        lab = np.array([L_clamped, c_val * cos_h, c_val * sin_h], dtype=np.float64)
        lin = oklab_to_linear_unclipped(lab)
        ok = bool(np.all(lin >= -1e-5) and np.all(lin <= 1.0 + 1e-5))
        return ok, lin

    ok_full, lin_full = in_gamut(C_pos)
    if ok_full:
        return linear_to_srgb(np.clip(lin_full, 0.0, 1.0))

    lo, hi = 0.0, C_pos
    best_lin = oklab_to_linear_unclipped(np.array([L_clamped, 0.0, 0.0], dtype=np.float64))
    for _ in range(18):
        mid = 0.5 * (lo + hi)
        ok_m, lin_m = in_gamut(mid)
        if ok_m:
            lo = mid
            best_lin = lin_m
        else:
            hi = mid
    return linear_to_srgb(np.clip(best_lin, 0.0, 1.0))


def oklch_to_hex(L: float, C: float, h_deg: float) -> str:
    """Convert OKLCH to gamut-mapped '#RRGGBB' without hue shift."""
    return srgb01_to_hex(oklch_to_srgb_gamut_mapped(L, C, h_deg))


@lru_cache(maxsize=8192)
def hex_to_oklch(hex_str: str) -> tuple[float, float, float]:
    """Convert '#RRGGBB' to (L, C, h_deg)."""
    lch = oklab_to_oklch(srgb_to_oklab(hex_to_srgb01(hex_str)))
    return float(lch[0]), float(lch[1]), float(lch[2])


def srgb_to_cielab(srgb: np.ndarray) -> np.ndarray:
    """Convert (..., 3) sRGB [0,1] to CIE 1976 L*a*b* (D65/2°)."""
    lin = srgb_to_linear(srgb)
    xyz = lin @ _M_SRGB_TO_XYZ_D65.T
    # D65 white point
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    r = xyz / np.array([xn, yn, zn], dtype=np.float64)
    delta = 6.0 / 29.0
    f = np.where(r > delta**3, np.cbrt(np.maximum(r, 0.0)), r / (3.0 * delta**2) + 4.0 / 29.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def ciede2000_matrix(srgb_a: np.ndarray, srgb_b: np.ndarray | None = None) -> np.ndarray:
    """Vectorized pairwise CIEDE2000 ΔE00 matrix between (N,3) and (M,3) sRGB [0,1] arrays."""
    lab1 = srgb_to_cielab(np.atleast_2d(srgb_a))[:, None, :]  # (N, 1, 3)
    lab2 = srgb_to_cielab(np.atleast_2d(srgb_a if srgb_b is None else srgb_b))[None, :, :]  # (1, M, 3)

    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    C_bar = 0.5 * (C1 + C2)
    c7 = C_bar**7
    G = 0.5 * (1.0 - np.sqrt(c7 / (c7 + 25.0**7)))

    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2
    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    prod_C = C1p * C2p
    dh_raw = h2p - h1p
    dhp = np.where(
        prod_C == 0.0,
        0.0,
        np.where(np.abs(dh_raw) <= 180.0, dh_raw, np.where(dh_raw > 180.0, dh_raw - 360.0, dh_raw + 360.0)),
    )
    dHp = 2.0 * np.sqrt(prod_C) * np.sin(np.radians(0.5 * dhp))

    Lp_bar = 0.5 * (L1 + L2)
    Cp_bar = 0.5 * (C1p + C2p)

    sum_h = h1p + h2p
    hp_bar = np.where(
        prod_C == 0.0,
        sum_h,
        np.where(
            np.abs(h1p - h2p) <= 180.0,
            0.5 * sum_h,
            np.where(sum_h < 360.0, 0.5 * (sum_h + 360.0), 0.5 * (sum_h - 360.0)),
        ),
    )

    T = (
        1.0
        - 0.17 * np.cos(np.radians(hp_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hp_bar))
        + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0))
    )

    dtheta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    cp7 = Cp_bar**7
    RC = 2.0 * np.sqrt(cp7 / (cp7 + 25.0**7))
    SL = 1.0 + (0.015 * ((Lp_bar - 50.0) ** 2)) / np.sqrt(20.0 + (Lp_bar - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cp_bar
    SH = 1.0 + 0.015 * Cp_bar * T
    RT = -np.sin(np.radians(2.0 * dtheta)) * RC

    return np.sqrt((dLp / SL) ** 2 + (dCp / SC) ** 2 + (dHp / SH) ** 2 + RT * (dCp / SC) * (dHp / SH))


def simulate_cvd(srgb: np.ndarray, mode: CVDType, severity: float = 1.0) -> np.ndarray:
    """Simulate Machado 2009 CVD or CIE luminance grayscale on (..., 3) sRGB [0,1]."""
    arr = np.clip(np.asarray(srgb, dtype=np.float64), 0.0, 1.0)
    if mode == "normal" or severity <= 0.0:
        return arr
    lin = srgb_to_linear(arr)
    sev = float(np.clip(severity, 0.0, 1.0))
    if mode == "grayscale":
        y = lin[..., 0] * 0.2126729 + lin[..., 1] * 0.7151522 + lin[..., 2] * 0.0721750
        gray_lin = np.stack([y, y, y], axis=-1)
        mixed = (1.0 - sev) * lin + sev * gray_lin
        return linear_to_srgb(mixed)
    mat100 = _MACHADO_100[mode]
    mat = (1.0 - sev) * np.eye(3, dtype=np.float64) + sev * mat100
    sim_lin = np.clip(lin @ mat.T, 0.0, 1.0)
    return linear_to_srgb(sim_lin)


def apca_contrast(text_srgb: np.ndarray, bg_srgb: np.ndarray) -> float:
    """Compute APCA 0.0.98G-4g Lc perceptual contrast (signed in [-108, +106])."""
    txt_lin = srgb_to_linear(np.asarray(text_srgb, dtype=np.float64)[:3])
    bg_lin = srgb_to_linear(np.asarray(bg_srgb, dtype=np.float64)[:3])
    coeffs = np.array([0.2126729, 0.7151522, 0.0721750], dtype=np.float64)
    yt = float(np.dot(txt_lin, coeffs))
    yb = float(np.dot(bg_lin, coeffs))

    # Soft clamp near black
    yt = yt + (0.022 - yt) ** 1.414 if yt < 0.022 else yt
    yb = yb + (0.022 - yb) ** 1.414 if yb < 0.022 else yb

    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:
        sapc = (yb**0.56 - yt**0.57) * 1.14
        return 0.0 if sapc < 0.1 else (sapc - 0.027) * 100.0
    sapc = (yb**0.65 - yt**0.62) * 1.14
    return 0.0 if sapc > -0.1 else (sapc + 0.027) * 100.0


def wcag2_contrast(srgb_a: np.ndarray, srgb_b: np.ndarray) -> float:
    """Compute classic WCAG 2.1 relative luminance contrast ratio [1, 21]."""
    coeffs = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
    l1 = float(np.dot(srgb_to_linear(np.asarray(srgb_a)[:3]), coeffs))
    l2 = float(np.dot(srgb_to_linear(np.asarray(srgb_b)[:3]), coeffs))
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def optimal_cell_text_hex(bg_srgb: np.ndarray, threshold_lc: float = 55.0) -> str:
    """Gate G3b: keep pure #000000 unless dark heatmap cell pushes |Lc(#000)| < threshold_lc."""
    lc_black = abs(apca_contrast(np.zeros(3), bg_srgb))
    if lc_black >= threshold_lc:
        return "#000000"
    lc_white = abs(apca_contrast(np.ones(3), bg_srgb))
    return "#FFFFFF" if lc_white > lc_black else "#000000"


@dataclass(frozen=True)
class ColormapManifoldResult:
    """Result of testing/projecting colors onto a 1D continuous colormap curve."""

    is_1d_manifold: bool
    is_diverging: bool
    midpoint_t: float
    lut_srgb: np.ndarray  # (256, 3) float64 in [0, 1]
    t_values: np.ndarray  # (N,) float64 in [0, 1]
    ortho_residual_p95: float


def interpolate_oklch_lut(
    stops_hex: Sequence[str],
    n: int = 256,
    diverging_midpoint: float | None = None,
) -> np.ndarray:
    """Build a smooth (n, 3) sRGB [0,1] LUT interpolated in OKLCH without muddy midtones."""
    if len(stops_hex) < 2:
        raise ValueError("Need at least 2 hex stops to build LUT")
    srgbs = np.stack([hex_to_srgb01(h) for h in stops_hex], axis=0)
    labs = srgb_to_oklab(srgbs)
    lchs = oklab_to_oklch(labs)

    m = len(stops_hex)
    if diverging_midpoint is not None and m >= 3 and m % 2 == 1:
        mid_idx = m // 2
        left_pos = np.linspace(0.0, diverging_midpoint, mid_idx + 1)
        right_pos = np.linspace(diverging_midpoint, 1.0, m - mid_idx)
        stop_pos = np.concatenate([left_pos[:-1], right_pos])
    else:
        stop_pos = np.linspace(0.0, 1.0, m)

    ts = np.linspace(0.0, 1.0, n)
    out = np.zeros((n, 3), dtype=np.float64)

    # Unwrap hue angles acrosschromatic stops (skip near-achromatic C < 0.012 stops)
    hues = lchs[:, 2].copy()
    chromas = lchs[:, 1]
    for idx in range(1, m):
        if chromas[idx] < 0.012:
            hues[idx] = hues[idx - 1]
        elif chromas[idx - 1] < 0.012 and idx >= 2:
            # Propagate forward from next chromatic stop instead of neutral midpoint
            pass
        else:
            diff = ((hues[idx] - hues[idx - 1] + 180.0) % 360.0) - 180.0
            hues[idx] = hues[idx - 1] + diff

    # Fix neutral stops (e.g., ivory midpoint in diverging map): blend in OKLab directly near neutral
    for i, t in enumerate(ts):
        seg = int(np.searchsorted(stop_pos, t, side="right")) - 1
        seg = max(0, min(m - 2, seg))
        t0, t1 = stop_pos[seg], stop_pos[seg + 1]
        u = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        if chromas[seg] < 0.018 or chromas[seg + 1] < 0.018:
            # Smooth OKLab interpolation into/out of neutral ivory/white prevents rainbow hue-spin!
            lab_interp = (1.0 - u) * labs[seg] + u * labs[seg + 1]
            lch_i = oklab_to_oklch(lab_interp)
            out[i] = oklch_to_srgb_gamut_mapped(float(lch_i[0]), float(lch_i[1]), float(lch_i[2]))
        else:
            L_i = (1.0 - u) * lchs[seg, 0] + u * lchs[seg + 1, 0]
            C_i = (1.0 - u) * chromas[seg] + u * chromas[seg + 1]
            h_i = ((1.0 - u) * hues[seg] + u * hues[seg + 1]) % 360.0
            out[i] = oklch_to_srgb_gamut_mapped(float(L_i), float(C_i), float(h_i))
    return out


def extract_1d_lut_from_strip(strip_rgb01: np.ndarray, n: int = 256) -> tuple[np.ndarray, bool, float]:
    """Extract ordered (n, 3) LUT from a 2D colorbar image strip (H, W, 3) in [0,1].

    Orientations handled automatically: vertical (bottom=low or top=low) and horizontal.
    Convention: t=0 corresponds to low value (typically bottom of vertical ggplot colorbar or left of horizontal).
    """
    h, w, _ = strip_rgb01.shape
    if h >= w:
        # Vertical colorbar: average central columns, flip so index 0 = bottom (low value in ggplot/mpl)
        x0, x1 = max(0, w // 4), max(1, w - w // 4)
        profile = strip_rgb01[::-1, x0:x1, :].mean(axis=1)
    else:
        y0, y1 = max(0, h // 4), max(1, h - h // 4)
        profile = strip_rgb01[y0:y1, :, :].mean(axis=0)

    src_t = np.linspace(0.0, 1.0, len(profile))
    dst_t = np.linspace(0.0, 1.0, n)
    lut = np.stack([np.interp(dst_t, src_t, profile[:, c]) for c in range(3)], axis=-1)

    labs = srgb_to_oklab(lut)
    L_curve = labs[:, 0]
    mid_slice = L_curve[int(0.25 * n) : int(0.75 * n)]
    mid_rel_idx = int(np.argmax(mid_slice)) + int(0.25 * n)
    L_ends_max = max(float(L_curve[0]), float(L_curve[-1]))
    is_div = bool(L_curve[mid_rel_idx] - L_ends_max > 0.08 and abs(float(L_curve[0]) - float(L_curve[-1])) < 0.28)
    midpoint_t = float(mid_rel_idx / (n - 1)) if is_div else 0.5
    return lut, is_div, midpoint_t


def project_colors_onto_lut(srgb_samples: np.ndarray, lut_srgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project (N, 3) sRGB [0,1] colors onto (M, 3) LUT in OKLab space.

    Returns:
        t_values: (N,) float64 in [0, 1]
        residuals: (N,) float64 Euclidean distance in OKLab to nearest LUT point
    """
    pts_lab = srgb_to_oklab(np.atleast_2d(srgb_samples))  # (N, 3)
    lut_lab = srgb_to_oklab(lut_srgb)  # (M, 3)
    m = len(lut_lab)

    # Chunked projection to keep peak RAM tiny even on 500k pixels
    n = len(pts_lab)
    t_out = np.empty(n, dtype=np.float64)
    res_out = np.empty(n, dtype=np.float64)
    chunk = 16384
    for start in range(0, n, chunk):
        end = min(n, start + chunk)
        sub = pts_lab[start:end, None, :]  # (B, 1, 3)
        d2 = np.sum((sub - lut_lab[None, :, :]) ** 2, axis=-1)  # (B, M)
        idx = np.argmin(d2, axis=1)
        res_out[start:end] = np.sqrt(d2[np.arange(end - start), idx])
        t_out[start:end] = idx / max(1, m - 1)
    return t_out, res_out


def test_2d_image_1d_manifold(
    img_rgb01: np.ndarray,
    reference_luts: Iterable[np.ndarray] = (),
    max_samples: int = 4096,
) -> ColormapManifoldResult:
    """Test whether a 2D raster image is a synthetic 1D-colormap data plot vs natural/histology photo (Gate G0)."""
    flat = img_rgb01.reshape(-1, 3)
    # Exclude pure white/black border pixels when fitting intrinsic curve
    non_bg_mask = ~((np.all(flat > 0.985, axis=1)) | (np.all(flat < 0.015, axis=1)))
    active = flat[non_bg_mask] if np.count_nonzero(non_bg_mask) >= 64 else flat

    if len(active) > max_samples:
        step = max(1, len(active) // max_samples)
        sampled = active[::step][:max_samples]
    else:
        sampled = active

    # 1. First check against any coupled colorbar LUTs on the same page
    for ref_lut in reference_luts:
        _, res = project_colors_onto_lut(sampled, ref_lut)
        p95 = float(np.percentile(res, 95))
        if p95 <= 0.026:
            t_all, _ = project_colors_onto_lut(flat, ref_lut)
            labs = srgb_to_oklab(ref_lut)
            L_c = labs[:, 0]
            L_ends = max(float(L_c[0]), float(L_c[-1]))
            mid_idx = int(np.argmax(L_c[64:192])) + 64
            is_div = bool(L_c[mid_idx] - L_ends > 0.08)
            return ColormapManifoldResult(
                is_1d_manifold=True,
                is_diverging=is_div,
                midpoint_t=mid_idx / 255.0 if is_div else 0.5,
                lut_srgb=ref_lut,
                t_values=t_all,
                ortho_residual_p95=p95,
            )

    # 2. Intrinsic 1D curve check in OKLab via sorted lightness/principal axis binning
    labs = srgb_to_oklab(sampled)
    centered = labs - labs.mean(axis=0, keepdims=True)
    cov = (centered.T @ centered) / max(1, len(centered) - 1)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order_ev = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order_ev]
    pc1 = eigvecs[:, order_ev[0]]

    # Sort along PC1 and build piecewise smooth spline LUT
    proj = centered @ pc1
    if np.corrcoef(proj, labs[:, 0])[0, 1] > 0:
        # Orient t=0 -> lighter background-adjacent end or darker low end consistently (low L -> high L or vice versa)
        pass
    bins = np.percentile(proj, np.linspace(0, 100, 33))
    knots = []
    for b0, b1 in zip(bins[:-1], bins[1:]):
        mask = (proj >= b0) & (proj <= b1)
        if np.any(mask):
            knots.append(sampled[mask].mean(axis=0))
    if len(knots) < 4:
        return ColormapManifoldResult(False, False, 0.5, np.zeros((256, 3)), np.zeros(len(flat)), 1.0)

    knots_arr = np.stack(knots, axis=0)
    src_t = np.linspace(0.0, 1.0, len(knots_arr))
    dst_t = np.linspace(0.0, 1.0, 256)
    fit_lut = np.stack([np.interp(dst_t, src_t, knots_arr[:, c]) for c in range(3)], axis=-1)
    _, res = project_colors_onto_lut(sampled, fit_lut)
    p95 = float(np.percentile(res, 95))

    # Also check chromaticity & continuity:
    # - Grayscale Western blots have near-zero chroma everywhere -> NEVER auto-recolor!
    # - Discrete 2..10 flat-color patches or discontinuous multi-stain jumps are NOT continuous 1D heatmaps!
    chroma = np.hypot(labs[:, 1], labs[:, 2])
    c_p95 = float(np.percentile(chroma, 95))
    unique_quantized = len(np.unique(np.round(sampled * 64.0).astype(np.int32), axis=0))
    knots_oklab = srgb_to_oklab(knots_arr)
    max_knot_step = float(np.linalg.norm(np.diff(knots_oklab, axis=0), axis=1).max()) if len(knots_oklab) >= 2 else 1.0
    is_valid_1d_heatmap = bool(
        p95 <= 0.018 and c_p95 >= 0.045 and unique_quantized >= 12 and max_knot_step <= 0.18
    )

    t_all = project_colors_onto_lut(flat, fit_lut)[0] if is_valid_1d_heatmap else np.zeros(len(flat))
    return ColormapManifoldResult(
        is_1d_manifold=is_valid_1d_heatmap,
        is_diverging=False,
        midpoint_t=0.5,
        lut_srgb=fit_lut,
        t_values=t_all,
        ortho_residual_p95=p95,
    )


def describe_color_group(hex_str: str, primitive_count: int) -> str:
    """Format human-readable fallback name per Spec Section 4.3: e.g. 'Blue group · 1,234 marks'."""
    L, C, h = hex_to_oklch(hex_str)
    if C < 0.022:
        name = "Light gray" if L >= 0.72 else ("Dark gray" if L <= 0.38 else "Slate")
    elif h < 18.0 or h >= 345.0:
        name = "Pink" if L >= 0.70 else "Red"
    elif h < 42.0:
        name = "Coral" if L >= 0.66 else ("Brown" if L <= 0.46 and C < 0.11 else "Red-orange")
    elif h < 68.0:
        name = "Orange" if C >= 0.10 else "Brown"
    elif h < 92.0:
        name = "Amber" if L < 0.76 else "Gold"
    elif h < 118.0:
        name = "Yellow" if L >= 0.78 else "Olive"
    elif h < 166.0:
        name = "Green"
    elif h < 205.0:
        name = "Teal"
    elif h < 232.0:
        name = "Cyan"
    elif h < 276.0:
        name = "Blue"
    elif h < 306.0:
        name = "Indigo" if L < 0.48 else "Purple"
    else:
        name = "Magenta" if C >= 0.14 else "Rose"
    noun = "mark" if primitive_count == 1 else "marks"
    return f"{name} group · {primitive_count:,} {noun}"


# Prevent pytest from collecting imported helper as a test function
test_2d_image_1d_manifold.__test__ = False  # type: ignore[attr-defined]
