#!/usr/bin/env python3
"""Compute perceptual & accessibility QC metadata for all palettes in `core/danqing/palettes/data/` (WP1).

Never modifies original palette hex values — strictly computes and writes `qc` metadata:
- `min_de2000_first6`: minimum pairwise CIEDE2000 among the first min(6, N) colors
- `min_de2000_deutan_first6`: minimum pairwise CIEDE2000 under deuteranopia simulation (first min(6, N))
- `min_de2000_protan_first6`: minimum pairwise CIEDE2000 under protanopia simulation (first min(6, N))
- `min_de2000_tritan_first6`: minimum pairwise CIEDE2000 under tritanopia simulation (first min(6, N))
- `optimal6_min_de2000_deutan` / `optimal6_min_de2000_protan`: subset min ΔE when `order == "gradient"`
- `grayscale_L_spread`: OKLab lightness range `max(L) - min(L)`
- `colorblind_safe`: boolean used by UI `CB-safe` badge and `Color-blind safe` filter
- `print_friendly`: boolean used by UI `Print-friendly (grayscale)` filter (`grayscale_L_spread >= 0.30`)
- `max_colors`: effective maximum distinct categories supported without color generation
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))

from danqing.color_science import ciede2000_matrix, hex_to_srgb01, simulate_cvd, srgb_to_oklab  # noqa: E402

DATA_DIR = REPO_ROOT / "core" / "danqing" / "palettes" / "data"


def _min_pairwise_de(arr: np.ndarray) -> float:
    if len(arr) < 2:
        return 100.0
    mat = ciede2000_matrix(arr)
    np.fill_diagonal(mat, 999.0)
    return float(mat.min())


def _maxmin_subset(arr: np.ndarray, k: int) -> np.ndarray:
    if len(arr) <= k:
        return arr
    mat = ciede2000_matrix(arr)
    i0, i1 = np.unravel_index(int(np.argmax(mat)), mat.shape)
    chosen = [int(i0), int(i1)]
    while len(chosen) < k:
        rem = [i for i in range(len(arr)) if i not in chosen]
        best_i = max(rem, key=lambda r: float(min(mat[r, c] for c in chosen)))
        chosen.append(best_i)
    return arr[chosen]


def compute_palette_qc(pal: dict[str, Any]) -> dict[str, Any]:
    colors: list[str] = pal["colors"]
    n = len(colors)
    arr = np.stack([hex_to_srgb01(c) for c in colors], axis=0)
    labs = srgb_to_oklab(arr)
    l_vals = labs[:, 0]
    l_spread = float(l_vals.max() - l_vals.min()) if n >= 2 else 0.0

    k6 = min(6, n)
    first6 = arr[:k6]
    min_de6 = _min_pairwise_de(first6)
    min_deut6 = _min_pairwise_de(simulate_cvd(first6, "deutan", 1.0))
    min_prot6 = _min_pairwise_de(simulate_cvd(first6, "protan", 1.0))
    min_trit6 = _min_pairwise_de(simulate_cvd(first6, "tritan", 1.0))

    opt6 = _maxmin_subset(arr, k6) if pal.get("order") == "gradient" else first6
    opt_de6 = _min_pairwise_de(opt6)
    opt_deut6 = _min_pairwise_de(simulate_cvd(opt6, "deutan", 1.0))
    opt_prot6 = _min_pairwise_de(simulate_cvd(opt6, "protan", 1.0))

    kind = pal.get("kind", "qualitative")
    if kind in ("sequential", "diverging"):
        # For continuous scales: check monotonic lightness (sequential) or distinguishable opposing poles under CVD (diverging)
        if kind == "sequential":
            diffs = np.diff(l_vals)
            monotonic = bool(np.all(diffs >= -0.025) or np.all(diffs <= 0.025))
            cb_safe = monotonic and l_spread >= 0.42
        else:
            poles = arr[[0, -1]]
            pole_deut = _min_pairwise_de(simulate_cvd(poles, "deutan", 1.0))
            pole_prot = _min_pairwise_de(simulate_cvd(poles, "protan", 1.0))
            cb_safe = bool(pole_deut >= 18.0 and pole_prot >= 16.0)
    else:
        cb_safe = bool(
            pal.get("collection") == "accessible"
            or (opt_de6 >= 12.0 and opt_deut6 >= 9.0 and opt_prot6 >= 8.5)
        )

    dyn = pal.get("dynamic_generator")
    max_colors = 64 if dyn in ("glasbey", "chrom_alternating") else n

    return {
        "color_count": n,
        "max_colors": max_colors,
        "min_de2000_first6": round(min_de6, 2),
        "min_de2000_deutan_first6": round(min_deut6, 2),
        "min_de2000_protan_first6": round(min_prot6, 2),
        "min_de2000_tritan_first6": round(min_trit6, 2),
        "optimal6_min_de2000": round(opt_de6, 2),
        "optimal6_min_de2000_deutan": round(opt_deut6, 2),
        "optimal6_min_de2000_protan": round(opt_prot6, 2),
        "grayscale_L_spread": round(l_spread, 3),
        "colorblind_safe": cb_safe,
        "print_friendly": bool(l_spread >= 0.30),
    }


def main() -> int:
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        print("No palette JSON files found in", DATA_DIR, file=sys.stderr)
        return 1

    cb_count = 0
    pf_count = 0
    by_col: dict[str, int] = {}
    for fp in files:
        pal = json.loads(fp.read_text())
        qc = compute_palette_qc(pal)
        pal["qc"] = qc
        fp.write_text(json.dumps(pal, indent=2, ensure_ascii=False) + "\n")
        col = pal.get("collection", "other")
        by_col[col] = by_col.get(col, 0) + 1
        cb_count += int(qc["colorblind_safe"])
        pf_count += int(qc["print_friendly"])
        print(
            f"[QC] {pal['id']:28s} col={col:10s} n={qc['color_count']:2d} "
            f"dE6={qc['min_de2000_first6']:5.2f} deut6={qc['min_de2000_deutan_first6']:5.2f} "
            f"prot6={qc['min_de2000_protan_first6']:5.2f} L_span={qc['grayscale_L_spread']:.3f} "
            f"CB={str(qc['colorblind_safe']):5s} Print={str(qc['print_friendly']):5s}"
        )

    print(
        f"\n[palette_qc] Certified {len(files)} palettes across {by_col} | "
        f"CB-safe={cb_count}/{len(files)} | Print-friendly={pf_count}/{len(files)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
