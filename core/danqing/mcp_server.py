"""Model Context Protocol (MCP) stdio server for Danqing (`python -m danqing.mcp_server`).

Exposes lossless vector PDF/SVG inspection, manuscript-level comfortable palette matching,
and Gate G0/G6 verified figure recoloring + R/Python code generation to AI research agents
(Google Antigravity, Claude Code, Gemini CLI, Cursor, Codex) with zero extra dependencies.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .exporter import (
    generate_change_report_csv,
    generate_python_mpl_snippet,
    generate_r_ggplot_snippet,
)
from .manuscript_matcher import match_manuscript_palettes
from .palettes import get_palette, list_palettes
from .pdf_engine import export_recolored_pdf, parse_pdf_scene
from .solver import evaluate_gates, solve_scene_colors
from .svg_engine import export_recolored_svg, parse_svg_scene

SERVER_INFO = {
    "name": "danqing_mcp",
    "version": "0.4.0",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "danqing_inspect_figure",
        "description": (
            "Inspect a vector scientific figure (.pdf or .svg): list panels, discrete color groups, "
            "continuous colorbars, protected raw experimental images (Western blots, H&E, microscopy), "
            "and current deuteranopia/protanopia accessibility diagnostics."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the input .pdf or .svg figure.",
                },
                "page_index": {
                    "type": "integer",
                    "description": "Zero-based page index for multi-page PDFs (default 0).",
                    "default": 0,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "danqing_match_manuscript_palettes",
        "description": (
            "Recommend the 3 most comfortable, harmonious, reviewer-safe palettes for a figure or "
            "manuscript brief (e.g. 'Nature Medicine tumor immunology', 'NEJM clinical trial', "
            "'single-cell UMAP', or preset 'cns_clean' / 'clinical' / 'omics' / 'museum')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Optional path to a .pdf or .svg figure to inspect group counts automatically.",
                },
                "brief": {
                    "type": "string",
                    "description": "Target journal, scientific field, or desired aesthetic mood.",
                    "default": "",
                },
                "preset": {
                    "type": "string",
                    "enum": ["cns_clean", "clinical", "omics", "museum"],
                    "description": "Optional one-click scholarly preset.",
                },
                "required_colors": {
                    "type": "integer",
                    "description": "Number of discrete groups if file_path is omitted (default 4).",
                    "default": 4,
                },
            },
        },
    },
    {
        "name": "danqing_recolor_figure",
        "description": (
            "Losslessly recolor a vector .pdf or .svg figure using one of Danqing's 3,434 verified palettes "
            "(with homologous paired sequential/diverging ramps) while guaranteeing bit-identical geometry, text, "
            "and raw experimental images (Western blots, H&E). Optionally writes reusable R (ggplot2) and Python (matplotlib) palette snippets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to the source .pdf or .svg file.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Destination path for the recolored .pdf or .svg file.",
                },
                "palette_id": {
                    "type": "string",
                    "description": "Palette ID (e.g. 'cns_harmony_lineage', 'npg', 'okabe_ito', 'east_ru_celadon').",
                    "default": "cns_harmony_lineage",
                },
                "page_index": {
                    "type": "integer",
                    "description": "Zero-based page index for PDFs (default 0).",
                    "default": 0,
                },
                "cross_panel_rule": {
                    "type": "string",
                    "enum": ["same_name", "unique"],
                    "description": "'same_name' keeps matching labels identical across panels; 'unique' assigns every element a distinct color.",
                    "default": "same_name",
                },
                "vibrancy": {
                    "type": "string",
                    "enum": ["muted", "standard", "vivid"],
                    "default": "standard",
                },
                "write_code_snippets": {
                    "type": "boolean",
                    "description": "If true, writes companion .R, .py, and .csv mapping files next to output_path.",
                    "default": True,
                },
            },
            "required": ["input_path", "output_path"],
        },
    },
    {
        "name": "danqing_list_palettes",
        "description": "Search and filter Danqing's 3,434 verified palettes (including homologous paired gradient stops) by collection, minimum colors, or color-blind safety.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "enum": ["accessible", "journal", "museum", "eastern", "many", "continuous", "convention"],
                },
                "query": {"type": "string", "default": ""},
                "colorblind_safe_only": {"type": "boolean", "default": False},
                "min_colors": {"type": "integer", "default": 1},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
]


def _load_dotenv_gemini_key() -> str:
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    home_env = Path.home() / ".env"
    if home_env.is_file():
        try:
            for line in home_env.read_text("utf-8").splitlines():
                s = line.strip()
                if s.startswith("GEMINI_API_KEY="):
                    return s.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            pass
    return ""


def _parse_any_scene(path: Path, page_index: int = 0) -> tuple[str, Any]:
    raw = path.read_bytes()
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf", parse_pdf_scene(raw, path.name, "mcp_fig", page_index=page_index)
    if ext == ".svg":
        return "svg", parse_svg_scene(raw, path.name, "mcp_fig")
    raise ValueError(f"Unsupported format {ext!r}; expected .pdf or .svg")


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "danqing_inspect_figure":
        p = Path(str(args["file_path"])).expanduser().resolve()
        kind, scene = _parse_any_scene(p, int(args.get("page_index", 0)))
        orig_map = {eid: ent.original_hex for eid, ent in scene.entities.items()}
        gates = evaluate_gates(scene.entities, orig_map, "panel_scoped")
        return {
            "filename": p.name,
            "kind": kind,
            "panels": [pb.panel_id for pb in scene.panels],
            "element_count": len(scene.entities),
            "elements": [
                {
                    "entity_id": ent.entity_id,
                    "label": ent.label,
                    "original_hex": ent.original_hex,
                    "panels": list(ent.panels),
                }
                for ent in scene.entities.values()
            ],
            "continuous_scale_count": len(scene.continuous_scales),
            "protected_raw_image_count": len(scene.evidence_regions),
            "diagnostics": {
                "colorblind_deutan_safe": bool(gates.get("colorblind_deutan_safe", True)),
                "min_de2000_deutan": round(float(gates.get("min_de2000_deutan", 99.0)), 2),
            },
        }

    if name == "danqing_match_manuscript_palettes":
        req_k = int(args.get("required_colors", 4))
        has_cont = False
        has_div = False
        labels: list[str] = []
        fp = args.get("file_path")
        if fp:
            p = Path(str(fp)).expanduser().resolve()
            _, scene = _parse_any_scene(p, 0)
            req_k = max(1, sum(1 for e in scene.entities.values() if e.tier != "background"))
            has_cont = len(scene.continuous_scales) > 0
            has_div = any(s.kind == "continuous_diverging" for s in scene.continuous_scales.values())
            labels = [e.label for e in scene.entities.values()]
        res = match_manuscript_palettes(
            required_k=req_k,
            has_continuous=has_cont,
            has_diverging=has_div,
            element_labels=labels,
            preset=args.get("preset"),
            brief=str(args.get("brief", "")),
            gemini_api_key=_load_dotenv_gemini_key(),
        )
        enriched = []
        for rec in res["recommendations"]:
            pal = get_palette(rec["palette_id"])
            enriched.append(
                {
                    "palette_id": pal.id,
                    "name_en": pal.name_en,
                    "name_zh": pal.name_zh,
                    "collection": pal.collection,
                    "colors": list(pal.colors[:10]),
                    "partners": {
                        "sequential": pal.partner_sequential,
                        "diverging": pal.partner_diverging,
                        "paired_sequential_stops": list(pal.paired_sequential_stops),
                        "paired_diverging_stops": list(pal.paired_diverging_stops),
                    },
                    "colorblind_safe": bool(pal.qc.get("colorblind_safe")),
                    "reason": rec["reason"],
                }
            )
        return {"engine": res["engine"], "recommendations": enriched}

    if name == "danqing_recolor_figure":
        in_p = Path(str(args["input_path"])).expanduser().resolve()
        out_p = Path(str(args["output_path"])).expanduser().resolve()
        pal_id = str(args.get("palette_id", "cns_harmony_lineage"))
        rule = "global_strict" if args.get("cross_panel_rule") == "unique" else "panel_scoped"
        vib = str(args.get("vibrancy", "standard"))
        kind, scene = _parse_any_scene(in_p, int(args.get("page_index", 0)))

        solved = solve_scene_colors(
            scene.entities,
            scene.continuous_scales,
            scene.evidence_regions,
            style_id=pal_id,
            collision_scope=rule,  # type: ignore[arg-type]
            vibrancy=vib,  # type: ignore[arg-type]
        )
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if kind == "pdf":
            out_bytes, audit = export_recolored_pdf(scene, solved.group_hex, solved.scale_stops, verify=True)
        else:
            out_bytes, audit = export_recolored_svg(scene, solved.group_hex, solved.scale_stops, verify=True)
        out_p.write_bytes(out_bytes)

        written_files = [str(out_p)]
        if args.get("write_code_snippets", True):
            r_path = out_p.with_suffix(".palette.R")
            py_path = out_p.with_suffix(".palette.py")
            csv_path = out_p.with_suffix(".changes.csv")
            r_path.write_text(
                generate_r_ggplot_snippet(
                    pal_id,
                    scene.entities,
                    solved.entity_hex,
                    scene.continuous_scales,
                    solved.scale_stops,
                ),
                "utf-8",
            )
            py_path.write_text(
                generate_python_mpl_snippet(
                    pal_id,
                    scene.entities,
                    solved.entity_hex,
                    scene.continuous_scales,
                    solved.scale_stops,
                ),
                "utf-8",
            )
            csv_path.write_text(generate_change_report_csv(scene.entities, solved.entity_hex), "utf-8")
            written_files.extend([str(r_path), str(py_path), str(csv_path)])

        return {
            "output_path": str(out_p),
            "palette_id": pal_id,
            "written_files": written_files,
            "integrity_audit": {
                "geometry_and_text_identical": bool(audit.get("g6_geometry_identical", True)),
                "raw_experimental_images_identical": bool(audit.get("g0_evidence_bit_identical", True)),
            },
        }

    if name == "danqing_list_palettes":
        col = args.get("collection")
        q = str(args.get("query", "")).strip().lower()
        cb_only = bool(args.get("colorblind_safe_only", False))
        min_c = int(args.get("min_colors", 1))
        lim = max(1, min(60, int(args.get("limit", 20))))
        items = []
        for p in list_palettes():
            if col and p.collection != col:
                continue
            if cb_only and not p.qc.get("colorblind_safe"):
                continue
            max_c = int(p.qc.get("max_colors", len(p.colors)))
            if not p.dynamic_generator and max_c < min_c:
                continue
            if q:
                hay = f"{p.id} {p.name_en} {p.name_zh} {p.source.get('author', '')}".lower()
                if q not in hay:
                    continue
            items.append(
                {
                    "id": p.id,
                    "name_en": p.name_en,
                    "name_zh": p.name_zh,
                    "collection": p.collection,
                    "kind": p.kind,
                    "colors": list(p.colors[:8]),
                    "partners": {
                        "sequential": p.partner_sequential,
                        "diverging": p.partner_diverging,
                        "paired_sequential_stops": list(p.paired_sequential_stops),
                        "paired_diverging_stops": list(p.paired_diverging_stops),
                    },
                    "colorblind_safe": bool(p.qc.get("colorblind_safe")),
                }
            )
            if len(items) >= lim:
                break
        return {"count": len(items), "palettes": items}

    raise ValueError(f"Unknown tool: {name}")


def handle_jsonrpc_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if msg_id is None:
        # Notification (e.g. notifications/initialized)
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        t_name = str(params.get("name", ""))
        t_args = params.get("arguments") or {}
        try:
            res = execute_tool(t_name, t_args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_jsonrpc_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
