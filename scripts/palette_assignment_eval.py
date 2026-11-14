#!/usr/bin/env python3
"""WP3 / Section 8.3 Corpus Palette Assignment Evaluator for Danqing.

Evaluates `solve_scene_colors` across all editable vector figures in `bench/corpus/` against Section 8.3 criteria:
1. Intra-panel pairwise ΔE2000 >= 12.0 when palette N >= K_panel (and >= 8.0 when K_panel > N).
2. Accessible collection palettes: simulated Deuteranopia & Protanopia intra-panel min ΔE2000 >= 8.0 (when N >= K_panel).
3. Under `same_name` ("Same name, same color") rule, when K_total <= N, cross-panel duplicate colors == 0.
4. Inter-palette distinctness: across distinct qualitative palettes, mean per-element ΔE2000 >= 15.0.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core"))

from danqing.color_science import ciede2000_matrix, hex_to_srgb01  # noqa: E402
from danqing.palettes import list_palettes  # noqa: E402
from danqing.pdf_engine import parse_pdf_scene  # noqa: E402
from danqing.solver import solve_scene_colors  # noqa: E402
from danqing.svg_engine import parse_svg_scene  # noqa: E402

CORPUS_DIR = REPO / "bench" / "corpus"


def main() -> int:
    manifest_path = CORPUS_DIR / "MANIFEST.json"
    if not manifest_path.exists():
        print(f"ERROR: Missing {manifest_path}. Run scripts/build_corpus.py first.", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qual_palettes = [p for p in list_palettes(include_conventions=False) if p.kind == "qualitative"]
    eval_palettes = [
        p
        for p in qual_palettes
        if p.id
        in (
            "okabe_ito",
            "tol_bright",
            "tol_muted",
            "tol_medium_contrast",
            "petroff6",
            "petroff10",
            "ibm_cbs",
            "carto_safe",
            "npg",
            "nejm",
            "bmj",
            "frontiers",
            "carto_bold",
            "observable10",
            "cns_harmony_lineage",
            "met_hiroshige",
            "met_klimt",
            "met_signac",
            "met_isfahan1",
            "met_nizami",
            "moma_picasso",
            "moma_lupi",
            "pnw_bay",
            "np_acadia",
            "east_ru_celadon",
            "east_ming_blue_white",
            "east_famille_rose",
            "east_sancai",
            "east_blue_green_landscape",
            "east_cloisonne_enamel",
            "east_lacquer",
            "east_edo_rimpa_irises",
            "east_ming_fahua",
            "east_tibet_thangka",
            "d3_category20",
            "kelly22",
            "glasbey",
            "polychrome_36",
            "scanpy_godsnot64",
            "scanpy_vega20",
        )
    ]
    accessible_ids = {p.id for p in eval_palettes if p.collection == "accessible"}

    scenes = []
    for item in manifest["figures"]:
        if not item.get("expect_editable", True):
            continue
        fp = CORPUS_DIR / item["filename"]
        raw = fp.read_bytes()
        page_idx = int(item.get("page_index", 0))
        sc = (
            parse_pdf_scene(raw, fp.name, item["id"], page_index=page_idx)
            if fp.suffix.lower() == ".pdf"
            else parse_svg_scene(raw, fp.name, item["id"])
        )
        if len(sc.entities) >= 2:
            scenes.append((item, sc))

    failures: list[str] = []
    solve_times_ms: list[float] = []
    inter_palette_means: list[float] = []
    total_runs = 0

    for item, sc in scenes:
        # Count max elements in any single panel and total merged variables
        panel_counts: dict[str, int] = {}
        norm_names = set()
        for e in sc.entities.values():
            norm_names.add(e.label.strip().lower())
            for pid in e.panels:
                panel_counts[pid] = panel_counts.get(pid, 0) + 1
        max_k_panel = max(panel_counts.values()) if panel_counts else 0
        k_total = len(norm_names)

        palette_vectors: dict[str, np.ndarray] = {}
        eids_sorted = sorted(sc.entities.keys())

        for pal in eval_palettes:
            n_pal = len(pal.colors)
            t0 = time.perf_counter()
            sr = solve_scene_colors(
                sc.entities,
                sc.continuous_scales,
                sc.evidence_regions,
                style_id=pal.id,
                collision_scope="same_name",
            )
            solve_times_ms.append((time.perf_counter() - t0) * 1000.0)
            total_runs += 1

            diag = sr.diagnostics
            min_de = float(diag["min_de2000_normal"])
            req_de = 12.0 if n_pal >= max_k_panel else 8.0
            if min_de < req_de - 0.2:
                failures.append(
                    f"[Intra-panel ΔE] {item['id']} x {pal.id} (N={n_pal}, K_panel={max_k_panel}): min_de={min_de:.1f} < {req_de}"
                )

            if pal.id in accessible_ids and n_pal >= max_k_panel:
                cvd_min = min(float(diag["min_de2000_deutan"]), float(diag["min_de2000_protan"]))
                if cvd_min < 8.0 - 0.2:
                    failures.append(
                        f"[Accessible CVD ΔE] {item['id']} x {pal.id} (N={n_pal}, K_panel={max_k_panel}): cvd_min={cvd_min:.1f} < 8.0"
                    )

            if k_total <= n_pal and int(diag["cross_panel_reused_count"]) > 0:
                failures.append(
                    f"[Cross-panel reuse when K_total<=N] {item['id']} x {pal.id} (K_total={k_total}, N={n_pal}): reused={diag['cross_panel_reused_count']}"
                )

            palette_vectors[pal.id] = np.stack([hex_to_srgb01(sr.entity_hex[eid]) for eid in eids_sorted], axis=0)

        # Pairwise inter-palette mean per-element ΔE2000
        pids = list(palette_vectors.keys())
        fig_pair_means = []
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                va = palette_vectors[pids[i]]
                vb = palette_vectors[pids[j]]
                # Element-wise diagonal of ciede2000_matrix(va, vb)
                d_mat = ciede2000_matrix(va, vb)
                elem_de = np.diag(d_mat)
                fig_pair_means.append(float(elem_de.mean()))
        mean_inter = float(np.mean(fig_pair_means))
        inter_palette_means.append(mean_inter)
        if mean_inter < 15.0:
            failures.append(f"[Inter-palette convergence] {item['id']}: mean inter-palette ΔE={mean_inter:.2f} < 15.0")

    report: dict[str, Any] = {
        "evaluated_figures": len(scenes),
        "evaluated_palettes": len(eval_palettes),
        "total_solver_runs": total_runs,
        "median_solve_ms": round(float(np.median(solve_times_ms)), 3) if solve_times_ms else 0.0,
        "p95_solve_ms": round(float(np.percentile(solve_times_ms, 95)), 3) if solve_times_ms else 0.0,
        "overall_mean_inter_palette_de2000": round(float(np.mean(inter_palette_means)), 2) if inter_palette_means else 0.0,
        "min_figure_inter_palette_de2000": round(float(np.min(inter_palette_means)), 2) if inter_palette_means else 0.0,
        "failure_count": len(failures),
        "failures": failures[:25],
    }
    out_json = REPO / "bench" / "palette_assignment_eval_report.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 84)
    print("Danqing WP3 Solver Corpus Evaluation (Section 8.3)")
    print("=" * 84)
    print(f"Evaluated corpus figures : {report['evaluated_figures']}")
    print(f"Evaluated palettes       : {report['evaluated_palettes']}")
    print(f"Total solver assignments : {report['total_solver_runs']}")
    print(f"Solver latency           : median {report['median_solve_ms']:.2f} ms | p95 {report['p95_solve_ms']:.2f} ms (target < 20 ms)")
    print(f"Inter-palette ΔE2000     : mean {report['overall_mean_inter_palette_de2000']:.2f} | min {report['min_figure_inter_palette_de2000']:.2f} (target >= 15.0)")
    print(f"Constraint violations    : {report['failure_count']}")
    if failures:
        for f in failures[:20]:
            print("  FAIL:", f)
        return 1
    print("PASS: All Section 8.3 solver invariants satisfied across corpus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
