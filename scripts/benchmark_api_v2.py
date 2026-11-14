#!/usr/bin/env python3
"""WP5 / Section 10 Performance Benchmark for Danqing Backend API v2.

Verifies exact Spec Section 10 latency targets on Apple Silicon:
1. Small figure (< 100k ops) switch palette -> rendered frame ready: <= 250 ms
2. Palette card hover preview (`?palette=...`): cold miss <= 400 ms; warm cache hit <= 50 ms
3. Visium large figure (1.6M ops) switch palette -> rendered frame ready: <= 2000 ms (2.0 s)
4. Initial parse of Visium large figure (with staged progress callbacks): <= 12000 ms (12.0 s)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(REPO))

from danqing.pdf_engine import parse_pdf_scene  # noqa: E402
from web.backend.app import BENCH_FIGURES_DIR, PRESET_MANIFEST, _load_preset_item, app  # noqa: E402


def main() -> int:
    client = TestClient(app)

    # 1. Measure cold complex spatial atlas parse with staged progress callbacks
    vis_path = BENCH_FIGURES_DIR / "04_MouseBrain_Visium_Complex_10xGenomics.pdf"
    vis_raw = vis_path.read_bytes()
    stages_seen: list[tuple[str, int]] = []
    t0 = time.perf_counter()
    vis_parsed = parse_pdf_scene(vis_raw, vis_path.name, "bench_visium", progress_cb=lambda s, p: stages_seen.append((s, p)))
    vis_parse_ms = (time.perf_counter() - t0) * 1000.0

    # Ensure presets loaded for switching benchmarks
    for item in PRESET_MANIFEST:
        _load_preset_item(item, keep_original=True)

    # 2. Small figure (`penguins_multimodal`) palette switch + render end-to-end
    switch_times = []
    for pal in ("okabe_ito", "east_ru_celadon", "met_hiroshige", "npg_inspired"):
        t_sw = time.perf_counter()
        st = client.patch("/api/v2/figures/penguins_multimodal/state", json={"action": "set_palette", "palette_id": pal}).json()
        r = client.get(st["render_url"])
        assert r.status_code == 200 and len(r.content) > 5000
        switch_times.append((time.perf_counter() - t_sw) * 1000.0)
    small_switch_median_ms = sorted(switch_times)[len(switch_times) // 2]

    # 3. Hover preview cold miss vs warm hit on `penguins_multimodal`
    t_cold = time.perf_counter()
    r_cold = client.get("/api/v2/figures/penguins_multimodal/render?palette=east_cloisonne_enamel")
    cold_hover_ms = (time.perf_counter() - t_cold) * 1000.0
    assert r_cold.status_code == 200

    t_warm = time.perf_counter()
    r_warm = client.get("/api/v2/figures/penguins_multimodal/render?palette=east_cloisonne_enamel")
    warm_hover_ms = (time.perf_counter() - t_warm) * 1000.0
    assert r_warm.status_code == 200

    # 4. Complex Visium spatial figure palette switch + render end-to-end
    t_vis_sw = time.perf_counter()
    st_vis = client.patch("/api/v2/figures/visium_brain_complex/state", json={"action": "set_palette", "palette_id": "okabe_ito"}).json()
    r_vis = client.get(st_vis["render_url"])
    vis_switch_ms = (time.perf_counter() - t_vis_sw) * 1000.0
    assert r_vis.status_code == 200 and len(r_vis.content) > 20000

    report = {
        "small_figure_switch_and_render_ms": round(small_switch_median_ms, 1),
        "small_figure_target_ms": 250.0,
        "hover_preview_cold_ms": round(cold_hover_ms, 1),
        "hover_preview_cold_target_ms": 400.0,
        "hover_preview_warm_ms": round(warm_hover_ms, 2),
        "hover_preview_warm_target_ms": 50.0,
        "complex_visium_switch_and_render_ms": round(vis_switch_ms, 1),
        "complex_visium_switch_target_ms": 2000.0,
        "complex_visium_initial_parse_ms": round(vis_parse_ms, 1),
        "complex_visium_parse_target_ms": 12000.0,
        "complex_visium_op_count": vis_parsed.total_stream_ops,
        "complex_visium_stages_emitted": [s[0] for s in stages_seen],
    }
    report["all_targets_met"] = bool(
        small_switch_median_ms <= 250.0
        and cold_hover_ms <= 400.0
        and warm_hover_ms <= 50.0
        and vis_switch_ms <= 2000.0
        and vis_parse_ms <= 12000.0
        and len(stages_seen) >= 4
    )
    (REPO / "bench" / "wp5_performance_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 84)
    print("Danqing WP5 API v2 Performance Report (Spec Section 10)")
    print("=" * 84)
    print(f"Small figure switch + render : {report['small_figure_switch_and_render_ms']:>7.1f} ms  (target <=   250 ms)")
    print(f"Hover preview (cold miss)    : {report['hover_preview_cold_ms']:>7.1f} ms  (target <=   400 ms)")
    print(f"Hover preview (warm LRU hit) : {report['hover_preview_warm_ms']:>7.2f} ms  (target <=    50 ms)")
    print(f"Complex Visium switch+render : {report['complex_visium_switch_and_render_ms']:>7.1f} ms  (target <=  2000 ms)")
    print(f"Complex Visium initial parse : {report['complex_visium_initial_parse_ms']:>7.1f} ms  (target <= 12000 ms)")
    print(f"SSE progress stages emitted  : {report['complex_visium_stages_emitted']}")
    print("-" * 84)
    if not report["all_targets_met"]:
        print("FAIL: One or more WP5 latency targets exceeded!", file=sys.stderr)
        return 1
    print("PASS: All WP5 API v2 performance targets met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
