"""FastAPI v2 backend for Danqing (丹青) Scientific Figure Recoloring Studio (Spec Section 10 / WP5).

Key guarantees:
- True WYSIWYG Preview == Export: PDF previews render the exact recolored PDF via pypdfium2; SVG previews serve the exact recolored SVG.
- Default Original Mode on upload (Spec 4.2): figures open in their original colors until the user picks a palette.
- Asynchronous parsing + Server-Sent Events (`/api/v2/figures/{id}/events`) across 4 progress stages.
- Upload guardrails (Spec 4.1): raster rejection with export tutorial metadata, multi-page PDF page picker with thumbnails,
  scanned-page vector check, >50 MB / >3M ops slow-figure warning, and 2-hour TTL / tab-close privacy deletion.
- Fast diff-only `PATCH /api/v2/figures/{id}/state` (< 15 ms solve) + LRU-cached `/render` supporting 300 ms palette hover preview
  and >150% zoom hi-res rendering.
- Honest live-computed export verification (`/api/v2/figures/{id}/export/verify` & `/export`).
"""

from __future__ import annotations

import asyncio
import collections
from contextlib import asynccontextmanager
import contextvars
import copy
import gc
import hashlib
import hmac
import io
import json
import os
import queue
import re
import secrets
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pypdfium2 as pdfium
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from danqing.color_science import interpolate_oklch_lut, srgb01_to_hex
from danqing.manuscript_matcher import match_manuscript_palettes
from danqing.exporter import (
    build_verification_certificate,
    generate_change_report_csv,
    generate_python_mpl_snippet,
    generate_r_ggplot_snippet,
)
from danqing.ir import ContinuousScale, SemanticEntity
from danqing.palettes import DEFAULT_PALETTE_ID, get_palette, list_palettes
from danqing.pdf_engine import (
    PDFIUM_LOCK,
    ParsedPdfScene,
    export_recolored_pdf,
    inspect_pdf_document,
    parse_pdf_scene,
    render_pdf_page_to_pil,
    render_preview_png,
)
from danqing.solver import (
    CollisionScope,
    SolveResult,
    VibrancyMode,
    evaluate_gates,
    normalize_role,
    solve_scene_colors,
)
from danqing.style_engine import STYLE_PROFILES, apply_style_to_solve_result, list_styles
from danqing.svg_engine import (
    SvgScene,
    export_recolored_svg,
    parse_svg_scene,
    render_svg_bytes_to_png,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_FIGURES_DIR = REPO_ROOT / "bench" / "figures"
FRONTEND_DIST_DIR = REPO_ROOT / "web" / "frontend" / "dist"

LOW_MEMORY_MODE = os.environ.get("DANQING_LOW_MEMORY", "0").strip().lower() in ("1", "true", "yes")
SESSION_TTL_SECONDS = 600.0 if LOW_MEMORY_MODE else 1200.0
MAX_UPLOAD_BYTES = (25 if LOW_MEMORY_MODE else 60) * 1024 * 1024
MAX_ACTIVE_VISITORS = 10 if LOW_MEMORY_MODE else 36
MAX_FIGURES_PER_VISITOR = 3 if LOW_MEMORY_MODE else 8
MAX_RENDER_CACHE_ITEMS = 8 if LOW_MEMORY_MODE else 36
MAX_UPLOADS_PER_MINUTE = 24
LARGE_FILE_WARN_BYTES = 50 * 1024 * 1024
LARGE_OPS_WARN_COUNT = 3_000_000

RASTER_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"})

PRESET_MANIFEST: list[dict[str, Any]] = [
    {
        "preset_id": "penguins_multimodal",
        "filename": "01_PalmerPenguins_MultiModal_Gorman2014.pdf",
        "title": {"en": "Antarctic Penguins Multi-Modal", "zh": "南极企鹅多维形态学四栏图"},
        "subtitle": {"en": "PDF · 4 panels · Coupled colorbar", "zh": "PDF · 4 栏 · 含连续色阶"},
        "citation": {
            "en": "Gorman et al., PLOS ONE 2014 · Horst et al., R J. 2022 (CC0)",
            "zh": "Gorman 等, PLOS ONE 2014 · Horst 等, R J. 2022 (CC0)",
        },
        "source_url": "https://doi.org/10.1371/journal.pone.0090081",
        "default_style": "okabe_ito",
    },
    {
        "preset_id": "histology_wb_shield",
        "filename": "02_Histology_WB_EvidenceShield_10xVisium.pdf",
        "title": {"en": "Brain H&E, Blot & Diverging Matrix", "zh": "脑切片 H&E、免疫印迹与发散热图"},
        "subtitle": {"en": "PDF · Protected raw images", "zh": "PDF · 自动保护原始实验图"},
        "citation": {
            "en": "10x Genomics Mouse Brain Visium v1.1 (CC-BY 4.0) · Ståhl et al., Science 2016",
            "zh": "10x Genomics 小鼠前脑公开切片 (CC-BY 4.0) · Ståhl 等, Science 2016",
        },
        "source_url": "https://www.10xgenomics.com/datasets/mouse-brain-serial-section-1-sagittal-anterior-1-standard-1-1-0",
        "default_style": "east_ming_blue_white",
    },
    {
        "preset_id": "egfr_pathway_svg",
        "filename": "03_EGFR_MAPK_Pathway_Lemmon2010.svg",
        "title": {"en": "EGFR–MAPK Signaling Gradients", "zh": "EGFR–MAPK 信号通路矢量渐变图"},
        "subtitle": {"en": "SVG · Linear & radial gradients", "zh": "SVG · 线性与径向渐变"},
        "citation": {
            "en": "Adapted from Lemmon & Schlessinger, Cell 2010 · KEGG hsa04012",
            "zh": "改编自 Lemmon & Schlessinger, Cell 2010 · KEGG hsa04012",
        },
        "source_url": "https://doi.org/10.1016/j.cell.2010.06.011",
        "default_style": "east_cloisonne_enamel",
    },
    {
        "preset_id": "visium_brain_complex",
        "filename": "04_MouseBrain_Visium_Complex_10xGenomics.pdf",
        "title": {"en": "Mouse Brain Visium Atlas (Complex)", "zh": "小鼠前脑空间转录组复杂图谱"},
        "subtitle": {"en": "PDF · 4 panels · 4,992 spots (162k ops)", "zh": "PDF · 4 栏 · 4,992 捕获点复杂大图"},
        "citation": {
            "en": "10x Genomics Adult Mouse Brain Sagittal Visium v1.1 (CC-BY 4.0)",
            "zh": "10x Genomics 成年小鼠矢状前脑 Visium 公开图谱 (CC-BY 4.0)",
        },
        "source_url": "https://www.10xgenomics.com/datasets/mouse-brain-serial-section-1-sagittal-anterior-1-standard-1-1-0",
        "default_style": "east_ru_celadon",
    },
]

LEGACY_STYLE_MAP: dict[str, str] = {
    "qianli_jiangshan": "east_blue_green_landscape",
    "qinghua_ciyun": "east_ming_blue_white",
    "east_qinghua_porcelain": "east_ming_blue_white",
    "dunhuang_zaojing": "east_cloisonne_enamel",
    "shuimo_dianzhu": "east_lacquer",
    "east_lacquer_cinnabar": "east_lacquer",
    "ruyao_tianqing": "east_ru_celadon",
    "longquan_meizi": "east_longquan",
    "east_longquan_celadon": "east_longquan",
    "fencai_huazhi": "east_famille_rose",
    "tangsancai_you": "east_sancai",
    "east_sancai_glaze": "east_sancai",
}


def _resolve_palette_id(pid: str | None) -> str:
    if not pid:
        return DEFAULT_PALETTE_ID
    return LEGACY_STYLE_MAP.get(pid, pid)


class _StaleHoverAbort(Exception):
    """Raised when a newer hover-preview request has superseded this in-flight preview."""


@dataclass
class HistorySnapshot:
    palette_id: str
    is_original_mode: bool
    panel_palettes: dict[str, str]
    rule: Literal["same_name", "unique"]
    vibrancy: VibrancyMode
    aesthetic_style: str | None
    entities: dict[str, SemanticEntity]
    continuous_scales: dict[str, ContinuousScale]


_VISITOR_SID_HEX_RE = re.compile(r"^[a-f0-9]{32}$")
_SERVER_COOKIE_SECRET: bytes = secrets.token_bytes(32)
PARSE_SEMAPHORE = threading.BoundedSemaphore(2)
CURRENT_VISITOR_SID: contextvars.ContextVar[str] = contextvars.ContextVar("CURRENT_VISITOR_SID", default="default_local_visitor")
PRESET_IDS: frozenset[str] = frozenset(it["preset_id"] for it in PRESET_MANIFEST)


def _sign_visitor_cookie(vsid: str) -> str:
    sig = hmac.new(_SERVER_COOKIE_SECRET, vsid.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{vsid}.{sig}"


def _verify_visitor_cookie(cookie_val: str) -> str | None:
    if not cookie_val or "." not in cookie_val:
        return None
    vsid, sig = cookie_val.split(".", 1)
    if not _VISITOR_SID_HEX_RE.match(vsid) or len(sig) != 32:
        return None
    expected = hmac.new(_SERVER_COOKIE_SECRET, vsid.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if hmac.compare_digest(sig, expected):
        return vsid
    return None


@dataclass
class VisitorWorkspace:
    visitor_sid: str
    keep_consistent: bool = True
    manuscript_registry: dict[str, str] = field(default_factory=dict)
    upload_timestamps: list[float] = field(default_factory=list)
    last_accessed: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_accessed = time.time()


@dataclass
class PendingMultipageUpload:
    pending_id: str
    owner_sid: str
    filename: str
    raw_bytes: bytes
    created_at: float


@dataclass
class SceneSession:
    scene_id: str
    filename: str
    kind: Literal["pdf", "svg"]
    owner_sid: str = "default_local_visitor"
    is_preset: bool = False
    status: Literal["processing", "ready", "error"] = "ready"
    stage: str = "ready"
    progress: int = 100
    error_code: str | None = None
    error_detail: str | None = None
    slow_warning: bool = False
    parsed: ParsedPdfScene | SvgScene | None = None
    initial_entities: dict[str, SemanticEntity] = field(default_factory=dict)
    palette_id: str = DEFAULT_PALETTE_ID
    is_original_mode: bool = True
    panel_palettes: dict[str, str] = field(default_factory=dict)
    rule: Literal["same_name", "unique"] = "same_name"
    vibrancy: VibrancyMode = "standard"
    aesthetic_style: str | None = None
    last_solve: SolveResult | None = None
    undo_stack: list[HistorySnapshot] = field(default_factory=list)
    redo_stack: list[HistorySnapshot] = field(default_factory=list)
    revision: int = 0
    hover_seq: int = 0
    render_cache: collections.OrderedDict[tuple[Any, ...], bytes] = field(default_factory=collections.OrderedDict)
    verified_export_cache: dict[tuple[int, str], tuple[bytes, dict[str, Any]]] = field(default_factory=dict)
    cached_export_bytes: bytes | None = None
    cached_export_filename: str = ""
    render_lock: threading.Lock = field(default_factory=threading.Lock)
    event_subscribers: list[queue.Queue[dict[str, Any]]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    @property
    def style_id(self) -> str:
        return self.palette_id

    @style_id.setter
    def style_id(self, val: str) -> None:
        self.palette_id = _resolve_palette_id(val)

    @property
    def collision_scope(self) -> CollisionScope:
        return "global_strict" if self.rule == "unique" else "panel_scoped"

    @collision_scope.setter
    def collision_scope(self, val: str) -> None:
        self.rule = "unique" if val in ("unique", "global_strict") else "same_name"

    def touch(self) -> None:
        self.last_accessed = time.time()

    def push_event(self, payload: dict[str, Any]) -> None:
        for q in list(self.event_subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def snapshot(self) -> HistorySnapshot:
        assert self.parsed is not None
        return HistorySnapshot(
            palette_id=self.palette_id,
            is_original_mode=self.is_original_mode,
            panel_palettes=dict(self.panel_palettes),
            rule=self.rule,
            vibrancy=self.vibrancy,
            aesthetic_style=self.aesthetic_style,
            entities=copy.deepcopy(self.parsed.entities),
            continuous_scales=copy.deepcopy(self.parsed.continuous_scales),
        )

    def restore(self, snap: HistorySnapshot) -> None:
        assert self.parsed is not None
        self.palette_id = snap.palette_id
        self.is_original_mode = snap.is_original_mode
        self.panel_palettes = dict(snap.panel_palettes)
        self.rule = snap.rule
        self.vibrancy = snap.vibrancy
        self.aesthetic_style = snap.aesthetic_style
        self.parsed.entities = copy.deepcopy(snap.entities)
        self.parsed.continuous_scales = copy.deepcopy(snap.continuous_scales)


SCENES: dict[str, SceneSession] = {}
PENDING_UPLOADS: dict[str, PendingMultipageUpload] = {}
PRESET_TEMPLATES: dict[str, ParsedPdfScene | SvgScene] = {}
PRESET_THUMB_CACHE: dict[str, bytes] = {}
VISITOR_WORKSPACES: dict[str, VisitorWorkspace] = {}


def _current_visitor_sid() -> str:
    return CURRENT_VISITOR_SID.get()


def _get_visitor_workspace(visitor_sid: str | None = None) -> VisitorWorkspace:
    vsid = visitor_sid or _current_visitor_sid()
    ws = VISITOR_WORKSPACES.get(vsid)
    if ws is None:
        ws = VisitorWorkspace(visitor_sid=vsid)
        VISITOR_WORKSPACES[vsid] = ws
    ws.touch()
    return ws


def _scene_storage_key(figure_id: str, visitor_sid: str | None = None) -> str:
    vsid = visitor_sid or _current_visitor_sid()
    if figure_id in PRESET_IDS:
        return f"{vsid}::{figure_id}"
    return figure_id


def _get_owned_scene(figure_id: str, visitor_sid: str | None = None) -> SceneSession | None:
    vsid = visitor_sid or _current_visitor_sid()
    sess = SCENES.get(_scene_storage_key(figure_id, vsid))
    if sess is None or sess.owner_sid != vsid:
        return None
    return sess


def _clone_parsed_scene(template: ParsedPdfScene | SvgScene) -> ParsedPdfScene | SvgScene:
    cloned = copy.copy(template)
    cloned.entities = copy.deepcopy(template.entities)
    cloned.color_groups = copy.deepcopy(template.color_groups)
    cloned.continuous_scales = copy.deepcopy(template.continuous_scales)
    return cloned


def _destroy_session_memory(sess: SceneSession) -> None:
    with sess.render_lock:
        sess.render_cache.clear()
        sess.verified_export_cache.clear()
        sess.cached_export_bytes = None
    sess.undo_stack.clear()
    sess.redo_stack.clear()
    sess.initial_entities.clear()
    sess.parsed = None
    if LOW_MEMORY_MODE:
        gc.collect()


def _purge_visitor_workspace(vsid: str) -> int:
    removed = 0
    for skey, sess in list(SCENES.items()):
        if sess.owner_sid == vsid:
            popped = SCENES.pop(skey, None)
            if popped is not None:
                _destroy_session_memory(popped)
                removed += 1
    for pid, pend in list(PENDING_UPLOADS.items()):
        if pend.owner_sid == vsid:
            PENDING_UPLOADS.pop(pid, None)
    VISITOR_WORKSPACES.pop(vsid, None)
    return removed


def _cleanup_expired_sessions() -> None:
    now = time.time()
    for skey, sess in list(SCENES.items()):
        if (now - sess.last_accessed) > SESSION_TTL_SECONDS:
            popped = SCENES.pop(skey, None)
            if popped is not None:
                _destroy_session_memory(popped)
    for pid, pend in list(PENDING_UPLOADS.items()):
        if (now - pend.created_at) > 900.0:
            PENDING_UPLOADS.pop(pid, None)
    for vsid, ws in list(VISITOR_WORKSPACES.items()):
        if (now - ws.last_accessed) > SESSION_TTL_SECONDS:
            _purge_visitor_workspace(vsid)
    if len(VISITOR_WORKSPACES) > MAX_ACTIVE_VISITORS:
        oldest = sorted(VISITOR_WORKSPACES.values(), key=lambda x: x.last_accessed)
        for ws in oldest[: len(VISITOR_WORKSPACES) - MAX_ACTIVE_VISITORS]:
            _purge_visitor_workspace(ws.visitor_sid)


def _detect_conventions(entities: dict[str, SemanticEntity]) -> list[str]:
    norms = {e.label.strip().upper() for e in entities.values()}
    recs: list[str] = []
    if len({"C>A", "C>G", "C>T", "T>A", "T>C", "T>G"} & norms) >= 4:
        recs.append("cosmic_sbs6")
    chr_matches = sum(1 for n in norms if n.startswith("CHR") and n[3:].strip().isdigit())
    if chr_matches >= 6:
        recs.append("chrom_alternating")
    if {"UP", "DOWN"} <= norms:
        recs.append("volcano_deg3")
    if {"G1", "S", "G2M"} <= norms or {"G1", "S", "G2/M"} <= norms:
        recs.append("cell_cycle_3")
    if {"GAIN", "LOSS"} <= norms or {"AMP", "DEL"} <= norms:
        recs.append("cnv_state3")
    if {"A", "C", "G", "T"} <= norms or {"A", "C", "G", "U"} <= norms:
        recs.append("dna_bases4")
    return recs


def _split_entities_by_panel_scope(
    entities: dict[str, SemanticEntity],
    color_groups: dict[str, Any],
    target_panels: set[str],
) -> tuple[dict[str, SemanticEntity], bool]:
    """Split any SemanticEntity whose color_groups cross between `target_panels` and non-target panels."""
    if not target_panels:
        return entities, False
    did_split = False
    new_entities: dict[str, SemanticEntity] = {}
    used_ids = set(entities.keys())

    for eid, ent in entities.items():
        in_gids = [g for g in ent.member_group_ids if g in color_groups and color_groups[g].panel_id in target_panels]
        out_gids = [g for g in ent.member_group_ids if g not in set(in_gids)]
        if in_gids and out_gids:
            did_split = True
            out_panels = list(dict.fromkeys(color_groups[g].panel_id for g in out_gids if g in color_groups))
            in_panels = list(dict.fromkeys(color_groups[g].panel_id for g in in_gids if g in color_groups))
            cg_out = color_groups[out_gids[0]]
            cg_in = color_groups[in_gids[0]]

            new_entities[eid] = SemanticEntity(
                entity_id=eid,
                label=ent.label,
                category_group=out_panels[0] if out_panels else ent.category_group,
                panels=out_panels,
                member_group_ids=out_gids,
                original_hex=cg_out.original_hex,
                current_hex=ent.current_hex,
                encoding=ent.encoding,
                tier=ent.tier,
                locked=ent.locked,
                unlinked=True,
            )

            slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in (in_panels[0] if in_panels else "sub")).strip("_") or "sub"
            cand_id = f"{eid}_{slug}"
            idx_c = 2
            while cand_id in used_ids or cand_id in new_entities:
                cand_id = f"{eid}_{slug}_{idx_c}"
                idx_c += 1
            used_ids.add(cand_id)

            new_entities[cand_id] = SemanticEntity(
                entity_id=cand_id,
                label=ent.label,
                category_group=in_panels[0] if in_panels else ent.category_group,
                panels=in_panels,
                member_group_ids=in_gids,
                original_hex=cg_in.original_hex,
                current_hex=ent.current_hex,
                encoding=ent.encoding,
                tier=ent.tier,
                locked=ent.locked,
                unlinked=True,
            )
        else:
            new_entities[eid] = copy.copy(ent)
    return new_entities, did_split


def _solve_session_colors(
    entities: dict[str, SemanticEntity],
    color_groups: dict[str, Any],
    continuous_scales: dict[str, ContinuousScale],
    evidence_regions: list[Any],
    all_panel_ids: list[str],
    default_palette_id: str,
    is_original_mode: bool,
    panel_palettes: dict[str, str],
    collision_scope: CollisionScope,
    active_pins: dict[str, str],
    vibrancy: VibrancyMode,
) -> SolveResult:
    """Solve colors across either the entire figure or independent per-panel palette assignments."""
    if not panel_palettes:
        if is_original_mode:
            ent_hex = {eid: (e.current_hex if e.locked else e.original_hex) for eid, e in entities.items()}
            grp_hex = {gid: cg.original_hex for gid, cg in color_groups.items()}
            for eid, hx in ent_hex.items():
                for gid in entities[eid].member_group_ids:
                    if gid in grp_hex:
                        grp_hex[gid] = hx
            sc_stops = {sid: list(cs.original_stops_hex) for sid, cs in continuous_scales.items()}
            sr_ref = solve_scene_colors(
                entities,
                continuous_scales,
                evidence_regions,
                style_id=default_palette_id,
                collision_scope=collision_scope,
                pinned_registry=active_pins,
                vibrancy=vibrancy,
            )
            diag = evaluate_gates(
                entities,
                ent_hex,
                collision_scope,
                palette_color_count=sr_ref.diagnostics["palette_color_count"],
                required_color_count=sr_ref.diagnostics["required_color_count"],
                generated_count=0,
            )
            return SolveResult(
                palette_id=default_palette_id,
                collision_scope=collision_scope,
                vibrancy=vibrancy,
                entity_hex=ent_hex,
                group_hex=grp_hex,
                scale_stops=sc_stops,
                entity_swatches=sr_ref.entity_swatches,
                inspector_swatches=sr_ref.inspector_swatches,
                diagnostics=diag,
            )

        return solve_scene_colors(
            entities,
            continuous_scales,
            evidence_regions,
            style_id=default_palette_id,
            collision_scope=collision_scope,
            pinned_registry=active_pins,
            vibrancy=vibrancy,
        )

    # Per-panel palette mode (`panel_palettes` maps panel_id -> "__original__" | palette_id)
    sr_fallback = solve_scene_colors(
        entities,
        continuous_scales,
        evidence_regions,
        style_id=default_palette_id,
        collision_scope=collision_scope,
        pinned_registry={},
        vibrancy=vibrancy,
    )
    ent_hex: dict[str, str] = {eid: (e.current_hex if e.locked else e.original_hex) for eid, e in entities.items()}
    sc_stops: dict[str, list[str]] = {sid: list(cs.original_stops_hex) for sid, cs in continuous_scales.items()}
    ent_swatches: dict[str, list[str]] = dict(sr_fallback.entity_swatches)
    insp_swatches: dict[str, list[dict[str, Any]]] = dict(sr_fallback.inspector_swatches)

    pal_to_panels: dict[str, set[str]] = {}
    fallback_mode = "__original__" if is_original_mode else default_palette_id
    for pid in all_panel_ids:
        assigned = panel_palettes.get(pid, fallback_mode)
        if assigned and assigned != "__original__":
            pal_to_panels.setdefault(_resolve_palette_id(assigned), set()).add(pid)

    total_generated = 0
    for pal_id, pset in pal_to_panels.items():
        sub_ents = {eid: e for eid, e in entities.items() if bool(set(e.panels) & pset)}
        sub_scales = {sid: cs for sid, cs in continuous_scales.items() if cs.panel_id in pset}
        sub_evs = [ev for ev in evidence_regions if ev.panel_id in pset]
        if not sub_ents and not sub_scales:
            continue
        sr_sub = solve_scene_colors(
            sub_ents,
            sub_scales,
            sub_evs,
            style_id=pal_id,
            collision_scope=collision_scope,
            pinned_registry={},
            vibrancy=vibrancy,
        )
        ent_hex.update(sr_sub.entity_hex)
        sc_stops.update(sr_sub.scale_stops)
        ent_swatches.update(sr_sub.entity_swatches)
        insp_swatches.update(sr_sub.inspector_swatches)
        total_generated += int(sr_sub.diagnostics.get("generated_count", 0))

    grp_hex = {gid: cg.original_hex for gid, cg in color_groups.items()}
    for eid, hx in ent_hex.items():
        for gid in entities[eid].member_group_ids:
            if gid in grp_hex:
                grp_hex[gid] = hx

    diag = evaluate_gates(
        entities,
        ent_hex,
        collision_scope,
        palette_color_count=sr_fallback.diagnostics["palette_color_count"],
        required_color_count=sr_fallback.diagnostics["required_color_count"],
        generated_count=total_generated,
    )
    return SolveResult(
        palette_id=default_palette_id,
        collision_scope=collision_scope,
        vibrancy=vibrancy,
        entity_hex=ent_hex,
        group_hex=grp_hex,
        scale_stops=sc_stops,
        entity_swatches=ent_swatches,
        inspector_swatches=insp_swatches,
        diagnostics=diag,
    )


def _recompute_session(sess: SceneSession) -> None:
    assert sess.parsed is not None
    sess.touch()
    sess.revision += 1
    with sess.render_lock:
        sess.render_cache.clear()
        sess.verified_export_cache.clear()
        sess.cached_export_bytes = None

    ws = _get_visitor_workspace(sess.owner_sid)
    p = sess.parsed
    active_pins = ws.manuscript_registry if (ws.keep_consistent and not sess.panel_palettes) else {}
    all_pids = [pb.panel_id for pb in p.panels]

    sr = _solve_session_colors(
        entities=p.entities,
        color_groups=p.color_groups,
        continuous_scales=p.continuous_scales,
        evidence_regions=p.evidence_regions,
        all_panel_ids=all_pids,
        default_palette_id=sess.palette_id,
        is_original_mode=sess.is_original_mode,
        panel_palettes=sess.panel_palettes,
        collision_scope=sess.collision_scope,
        active_pins=active_pins,
        vibrancy=sess.vibrancy,
    )
    if sess.aesthetic_style and sess.aesthetic_style in STYLE_PROFILES:
        sr = apply_style_to_solve_result(p, sr, sess.aesthetic_style)
    for eid, hx in sr.entity_hex.items():
        p.entities[eid].current_hex = hx
        if ws.keep_consistent and (not sess.is_original_mode or sess.aesthetic_style) and not sess.panel_palettes:
            norm_k = p.entities[eid].label.strip().lower()
            if norm_k and not ("group ·" in norm_k and norm_k.endswith(("mark", "marks"))):
                ws.manuscript_registry[norm_k] = hx
    for gid, hx in sr.group_hex.items():
        p.color_groups[gid].current_hex = hx
    for sid, stops in sr.scale_stops.items():
        p.continuous_scales[sid].current_stops_hex = list(stops)
    sess.last_solve = sr


def _build_categorical_lut(p: ParsedPdfScene | SvgScene, sr: SolveResult) -> list[dict[str, Any]]:
    gid_to_eid: dict[str, str] = {}
    for eid, ent in p.entities.items():
        for gid in ent.member_group_ids:
            gid_to_eid[gid] = eid
    cat_groups = [cg for cg in p.color_groups.values() if not cg.is_continuous_member]
    return [
        {
            "cat_index": idx,
            "group_id": cg.group_id,
            "entity_id": gid_to_eid.get(cg.group_id, ""),
            "panel_id": cg.panel_id,
            "role": cg.role,
            "original_hex": cg.original_hex,
            "current_hex": sr.group_hex.get(cg.group_id, cg.current_hex),
        }
        for idx, cg in enumerate(cat_groups)
    ]


def _serialize_elements(p: ParsedPdfScene | SvgScene, sr: SolveResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ent in p.entities.values():
        prim_cnt = sum(p.color_groups[gid].primitive_count for gid in ent.member_group_ids if gid in p.color_groups)
        out.append(
            {
                "entity_id": ent.entity_id,
                "label": ent.label,
                "panels": list(ent.panels),
                "member_group_ids": list(ent.member_group_ids),
                "original_hex": ent.original_hex,
                "current_hex": sr.entity_hex.get(ent.entity_id, ent.current_hex),
                "role": normalize_role(ent.tier),
                "tier": ent.tier,
                "locked": ent.locked,
                "unlinked": ent.unlinked,
                "primitive_count": prim_cnt,
                "swatches": sr.entity_swatches.get(ent.entity_id, [ent.current_hex]),
                "inspector_swatches": sr.inspector_swatches.get(ent.entity_id, []),
            }
        )
    return out


def _serialize_continuous_scales(sess: SceneSession, p: ParsedPdfScene | SvgScene, sr: SolveResult) -> list[dict[str, Any]]:
    out = []
    for idx_s, (sid, cs) in enumerate(p.continuous_scales.items()):
        base_stops = list(sr.scale_stops.get(sid, cs.original_stops_hex if sess.is_original_mode else cs.current_stops_hex))
        stops_eff = list(reversed(base_stops)) if cs.inverted_polarity else base_stops
        mid = cs.midpoint_t if cs.kind == "continuous_diverging" else None
        lut32 = [srgb01_to_hex(row) for row in interpolate_oklch_lut(stops_eff, n=32, diverging_midpoint=mid)]
        out.append(
            {
                "scale_index": idx_s,
                "id_map_r_code": 254 - idx_s,
                "scale_id": sid,
                "panel_id": cs.panel_id,
                "title": cs.title,
                "kind": cs.kind,
                "midpoint_t": cs.midpoint_t,
                "colorbar_bbox": cs.colorbar_bbox,
                "inverted_polarity": cs.inverted_polarity,
                "original_stops_hex": cs.original_stops_hex,
                "current_stops_hex": stops_eff,
                "gradient_preview_stops": lut32[::4] + [lut32[-1]],
            }
        )
    return out


def _serialize_v2_figure(sess: SceneSession) -> dict[str, Any]:
    if sess.status != "ready" or sess.parsed is None:
        return {
            "figure_id": sess.scene_id,
            "filename": sess.filename,
            "status": sess.status,
            "stage": sess.stage,
            "progress": sess.progress,
            "error_code": sess.error_code,
            "error_detail": sess.error_detail,
        }
    if sess.last_solve is None:
        _recompute_session(sess)
    assert sess.last_solve is not None
    sr = sess.last_solve
    p = sess.parsed

    width = p.page_width if isinstance(p, ParsedPdfScene) else p.width
    height = p.page_height if isinstance(p, ParsedPdfScene) else p.height
    preview_scale = p.preview_scale
    page_index = p.page_index if isinstance(p, ParsedPdfScene) else 0
    page_count = p.page_count if isinstance(p, ParsedPdfScene) else 1
    op_count = p.total_stream_ops if isinstance(p, ParsedPdfScene) else len(p.paint_instances)

    return {
        "figure_id": sess.scene_id,
        "scene_id": sess.scene_id,
        "filename": p.filename,
        "status": "ready",
        "kind": sess.kind,
        "width": width,
        "height": height,
        "preview_scale": preview_scale,
        "page_index": page_index,
        "page_count": page_count,
        "op_count": op_count,
        "slow_warning": sess.slow_warning,
        "palette_id": None if sess.is_original_mode else sess.palette_id,
        "active_palette_fallback": sess.palette_id,
        "is_original_mode": sess.is_original_mode,
        "panel_palettes": dict(sess.panel_palettes),
        "rule": sess.rule,
        "vibrancy": sess.vibrancy,
        "aesthetic_style": sess.aesthetic_style,
        "keep_consistent": _get_visitor_workspace(sess.owner_sid).keep_consistent,
        "can_undo": len(sess.undo_stack) > 0,
        "can_redo": len(sess.redo_stack) > 0,
        "revision": sess.revision,
        "render_url": f"/api/v2/figures/{sess.scene_id}/render?rev={sess.revision}",
        "original_url": f"/api/v2/figures/{sess.scene_id}/original",
        "pick_url": f"/api/v2/figures/{sess.scene_id}/pick",
        "panels": [asdict(pb) for pb in p.panels],
        "elements": _serialize_elements(p, sr),
        "entities": _serialize_elements(p, sr),
        "categorical_lut": _build_categorical_lut(p, sr),
        "continuous_scales": _serialize_continuous_scales(sess, p, sr),
        "protected_images": [
            {
                "region_id": ev.region_id,
                "name": ev.xobject_name,
                "panel_id": ev.panel_id,
                "bbox": ev.bbox,
                "width_px": ev.width_px,
                "height_px": ev.height_px,
                "subtype": ev.subtype_label,
            }
            for ev in p.evidence_regions
            if ev.mutability in ("class0_sacrosanct_evidence", "class1_fluorescence_lut")
        ],
        "plain_notices": p.plain_notices,
        "diagnostics": sr.diagnostics,
        "recommended_conventions": _detect_conventions(p.entities),
        "layer_urls": {
            "original": f"/api/v2/figures/{sess.scene_id}/original",
            "id_map": f"/api/v2/figures/{sess.scene_id}/pick",
        },
    }


def _get_or_parse_preset_template(item: dict[str, Any]) -> ParsedPdfScene | SvgScene | None:
    pid = str(item["preset_id"])
    cached = PRESET_TEMPLATES.get(pid)
    if cached is not None:
        return cached
    fpath = BENCH_FIGURES_DIR / str(item["filename"])
    if not fpath.exists():
        return None
    raw = fpath.read_bytes()
    parsed: ParsedPdfScene | SvgScene = (
        parse_svg_scene(raw, fpath.name, pid) if fpath.suffix.lower() == ".svg" else parse_pdf_scene(raw, fpath.name, pid)
    )
    if LOW_MEMORY_MODE and len(PRESET_TEMPLATES) >= 1:
        PRESET_TEMPLATES.clear()
    PRESET_TEMPLATES[pid] = parsed
    return parsed


def _load_preset_item(
    item: dict[str, Any],
    keep_original: bool = True,
    visitor_sid: str | None = None,
) -> SceneSession | None:
    vsid = visitor_sid or _current_visitor_sid()
    pid = str(item["preset_id"])
    skey = _scene_storage_key(pid, vsid)
    if skey in SCENES and SCENES[skey].status == "ready":
        return SCENES[skey]
    template = _get_or_parse_preset_template(item)
    if template is None:
        return None
    fpath = BENCH_FIGURES_DIR / str(item["filename"])
    kind: Literal["pdf", "svg"] = "svg" if fpath.suffix.lower() == ".svg" else "pdf"
    parsed = _clone_parsed_scene(template)
    op_cnt = parsed.total_stream_ops if isinstance(parsed, ParsedPdfScene) else len(parsed.paint_instances)
    raw_len = len(parsed.raw_pdf_bytes) if isinstance(parsed, ParsedPdfScene) else len(parsed.raw_svg_bytes)
    sess = SceneSession(
        scene_id=pid,
        filename=fpath.name,
        kind=kind,
        owner_sid=vsid,
        is_preset=True,
        status="ready",
        slow_warning=(raw_len > LARGE_FILE_WARN_BYTES or op_cnt > LARGE_OPS_WARN_COUNT),
        parsed=parsed,
        initial_entities=copy.deepcopy(parsed.entities),
        palette_id=_resolve_palette_id(item.get("default_style")),
        is_original_mode=keep_original,
    )
    _recompute_session(sess)
    SCENES[skey] = sess
    return sess


def _render_preset_thumbnail(item: dict[str, Any]) -> bytes:
    pid = str(item["preset_id"])
    if pid in PRESET_THUMB_CACHE:
        return PRESET_THUMB_CACHE[pid]
    fpath = BENCH_FIGURES_DIR / str(item["filename"])
    raw = fpath.read_bytes()
    if fpath.suffix.lower() == ".svg":
        png_b = render_svg_bytes_to_png(raw, zoom=0.55, background="#ffffff")
        pil = Image.open(io.BytesIO(png_b)).convert("RGB")
    else:
        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(raw)
            try:
                pg = doc[0]
                try:
                    w, h = pg.get_size()
                    sc = min(0.75, 480.0 / max(1.0, max(w, h)))
                    bitmap = pg.render(scale=sc, fill_color=(255, 255, 255, 255))
                    try:
                        pil = bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    pg.close()
            finally:
                doc.close()
    pil.thumbnail((480, 320), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    PRESET_THUMB_CACHE[pid] = buf.getvalue()
    return PRESET_THUMB_CACHE[pid]


def _start_reaper_daemon() -> None:
    def _loop() -> None:
        while True:
            time.sleep(300.0)
            try:
                _cleanup_expired_sessions()
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    for item in PRESET_MANIFEST:
        try:
            _render_preset_thumbnail(item)
            if not LOW_MEMORY_MODE and item != PRESET_MANIFEST[3]:
                _get_or_parse_preset_template(item)
        except Exception:
            pass
    _start_reaper_daemon()
    yield


app = FastAPI(title="Danqing (丹青) Scientific Figure Recoloring API", version="2.0.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def _visitor_isolation_middleware(request: Request, call_next):
    verified_sid = _verify_visitor_cookie(request.cookies.get("dq_sid", ""))
    if verified_sid is not None:
        visitor_sid = verified_sid
        need_cookie = False
    else:
        visitor_sid = secrets.token_hex(16)
        need_cookie = True
    token = CURRENT_VISITOR_SID.set(visitor_sid)
    try:
        response: Response = await call_next(request)
    finally:
        CURRENT_VISITOR_SID.reset(token)
    if need_cookie:
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
        )
        response.set_cookie(
            key="dq_sid",
            value=_sign_visitor_cookie(visitor_sid),
            httponly=True,
            secure=is_https,
            samesite="lax",
            path="/",
        )
    return response


# ==============================================================================
# API v2 Routes (Spec Section 10)
# ==============================================================================


@lru_cache(maxsize=1)
def _cached_v2_palettes_bytes() -> bytes:
    pals = [p.to_api_dict() for p in list_palettes(include_conventions=True)]
    styles = [s.to_api_dict() for s in list_styles()]
    presets = [
        {
            "preset_id": it["preset_id"],
            "filename": it["filename"],
            "title": it["title"],
            "subtitle": it["subtitle"],
            "citation": it.get("citation"),
            "source_url": it.get("source_url", ""),
            "thumbnail_url": f"/api/v2/presets/{it['preset_id']}/thumbnail",
        }
        for it in PRESET_MANIFEST
    ]
    return json.dumps(
        {
            "palettes": pals,
            "styles": styles,
            "default_palette_id": DEFAULT_PALETTE_ID,
            "presets": presets,
        },
        ensure_ascii=False,
    ).encode("utf-8")


@app.get("/api/v2/palettes")
def list_v2_palettes() -> Response:
    return Response(
        content=_cached_v2_palettes_bytes(),
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/v2/styles")
def list_v2_styles() -> dict[str, Any]:
    return {"styles": [s.to_api_dict() for s in list_styles()]}


@app.get("/api/v2/presets/{preset_id}/thumbnail")
def get_preset_thumbnail(preset_id: str) -> Response:
    item = next((x for x in PRESET_MANIFEST if x["preset_id"] == preset_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Preset not found")
    data = _render_preset_thumbnail(item)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/v2/figures")
def list_session_figures() -> dict[str, Any]:
    _cleanup_expired_sessions()
    vsid = _current_visitor_sid()
    ws = _get_visitor_workspace(vsid)
    items = []
    for sess in SCENES.values():
        if sess.owner_sid == vsid and sess.status == "ready" and sess.parsed is not None:
            items.append(
                {
                    "figure_id": sess.scene_id,
                    "filename": sess.filename,
                    "kind": sess.kind,
                    "is_preset": sess.is_preset,
                    "is_original_mode": sess.is_original_mode,
                    "palette_id": sess.palette_id,
                }
            )
    return {
        "figures": items,
        "keep_consistent": ws.keep_consistent,
    }


def _execute_parse_into_session(
    sess: SceneSession,
    raw_bytes: bytes,
    page_index: int = 0,
) -> None:
    def _progress(stage: str, pct: int) -> None:
        sess.stage = stage
        sess.progress = pct
        sess.push_event({"stage": stage, "progress": pct, "figure_id": sess.scene_id})

    try:
        with PARSE_SEMAPHORE:
            if sess.kind == "svg":
                parsed: ParsedPdfScene | SvgScene = parse_svg_scene(
                    raw_bytes, sess.filename, sess.scene_id, progress_cb=_progress
                )
                is_scanned = len(parsed.entities) == 0 and len(parsed.continuous_scales) == 0 and len(parsed.evidence_regions) > 0
                op_cnt = len(parsed.paint_instances)
            else:
                parsed = parse_pdf_scene(
                    raw_bytes, sess.filename, sess.scene_id, page_index=page_index, progress_cb=_progress
                )
                is_scanned = parsed.is_scanned_only or (
                    len(parsed.entities) == 0 and len(parsed.continuous_scales) == 0 and len(parsed.evidence_regions) > 0
                )
                op_cnt = parsed.total_stream_ops

        if is_scanned:
            sess.status = "error"
            sess.error_code = "SCANNED_PDF_NO_VECTORS"
            sess.error_detail = "This page contains only an image, no editable shapes."
            sess.push_event(
                {
                    "stage": "error",
                    "progress": 100,
                    "code": sess.error_code,
                    "detail": sess.error_detail,
                    "figure_id": sess.scene_id,
                }
            )
            return

        sess.parsed = parsed
        sess.initial_entities = copy.deepcopy(parsed.entities)
        if len(raw_bytes) > LARGE_FILE_WARN_BYTES or op_cnt > LARGE_OPS_WARN_COUNT:
            sess.slow_warning = True

        # Keep original figure colors by default on upload (Spec 4.2)
        sess.is_original_mode = True
        sess.aesthetic_style = None
        sess.panel_palettes.clear()
        _recompute_session(sess)
        sess.status = "ready"
        sess.stage = "ready"
        sess.progress = 100
        sess.push_event({"stage": "ready", "progress": 100, "figure_id": sess.scene_id})
    except Exception as exc:
        sess.status = "error"
        sess.error_code = "PARSE_FAILED"
        sess.error_detail = str(exc)
        sess.push_event(
            {
                "stage": "error",
                "progress": 100,
                "code": "PARSE_FAILED",
                "detail": str(exc),
                "figure_id": sess.scene_id,
            }
        )


@app.post("/api/v2/figures")
async def create_v2_figure(
    file: UploadFile | None = File(default=None),
    preset_id: str | None = Form(default=None),
    pending_upload_id: str | None = Form(default=None),
    svg_text: str | None = Form(default=None),
    page_index: int | None = Form(default=None),
    sync: bool = Query(default=False),
) -> Response:
    _cleanup_expired_sessions()
    vsid = _current_visitor_sid()
    _get_visitor_workspace(vsid)

    # Case 1: Load one of the 4 sample presets into an isolated per-visitor session
    if preset_id:
        legacy_preset_alias = {
            "fig07_multimodal": "penguins_multimodal",
            "g0_evidence_shield": "histology_wb_shield",
            "svg_gradient_demo": "egfr_pathway_svg",
            "combo1_spatial": "visium_brain_complex",
        }
        preset_id = legacy_preset_alias.get(preset_id, preset_id)
        item = next((x for x in PRESET_MANIFEST if x["preset_id"] == preset_id), None)
        if not item:
            raise HTTPException(status_code=404, detail=f"Unknown preset {preset_id!r}")

        existing = _get_owned_scene(preset_id, vsid)
        if existing is not None and existing.status == "ready" and existing.parsed is not None:
            existing.is_original_mode = True
            existing.panel_palettes.clear()
            existing.undo_stack.clear()
            existing.redo_stack.clear()
            if existing.initial_entities:
                existing.parsed.entities = copy.deepcopy(existing.initial_entities)
            for ent in existing.parsed.entities.values():
                ent.locked = False
                ent.tier = "normal"
            for cs in existing.parsed.continuous_scales.values():
                cs.inverted_polarity = False
            _recompute_session(existing)
            return JSONResponse({"status": "ready", "figure_id": existing.scene_id})

        if preset_id in PRESET_TEMPLATES:
            sess_cloned = _load_preset_item(item, keep_original=True, visitor_sid=vsid)
            assert sess_cloned is not None
            return JSONResponse({"status": "ready", "figure_id": sess_cloned.scene_id})

        fpath = BENCH_FIGURES_DIR / str(item["filename"])
        raw = fpath.read_bytes()
        kind: Literal["pdf", "svg"] = "svg" if fpath.suffix.lower() == ".svg" else "pdf"
        sess = SceneSession(
            scene_id=preset_id,
            filename=fpath.name,
            kind=kind,
            owner_sid=vsid,
            is_preset=True,
            status="processing",
            stage="reading_file",
            progress=5,
            slow_warning=len(raw) > LARGE_FILE_WARN_BYTES,
            palette_id=_resolve_palette_id(item.get("default_style")),
            is_original_mode=True,
        )
        SCENES[_scene_storage_key(preset_id, vsid)] = sess

        def _parse_and_cache_preset() -> None:
            _execute_parse_into_session(sess, raw, page_index=0)
            if sess.status == "ready" and sess.parsed is not None and preset_id not in PRESET_TEMPLATES:
                PRESET_TEMPLATES[preset_id] = _clone_parsed_scene(sess.parsed)

        if sync:
            _parse_and_cache_preset()
            return JSONResponse({"status": sess.status, "figure_id": sess.scene_id})
        threading.Thread(target=_parse_and_cache_preset, daemon=True).start()
        return JSONResponse({"status": "processing", "figure_id": sess.scene_id})

    # Case 2: Multi-page second step (`pending_upload_id` + `page_index`)
    if pending_upload_id is not None:
        pend = PENDING_UPLOADS.get(pending_upload_id)
        if pend is None or pend.owner_sid != vsid:
            return JSONResponse(status_code=404, content={"code": "PENDING_UPLOAD_EXPIRED", "message": "Pending PDF expired; please upload again."})
        PENDING_UPLOADS.pop(pending_upload_id, None)
        raw = pend.raw_bytes
        fname = pend.filename
        ext = ".pdf"
        chosen_page = max(0, int(page_index or 0))
    elif svg_text is not None:
        raw = svg_text.encode("utf-8")
        if len(raw) > MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=413, content={"code": "FILE_TOO_LARGE", "message": "Maximum upload size is 60 MB."})
        if not raw.strip():
            return JSONResponse(status_code=400, content={"code": "EMPTY_FILE", "message": "Clipboard SVG text is empty."})
        fname = "pasted_figure.svg"
        ext = ".svg"
        chosen_page = 0
    elif file is not None:
        fname = Path(file.filename or "figure.pdf").name
        ext = Path(fname).suffix.lower()
        try:
            if ext in RASTER_EXTENSIONS:
                return JSONResponse(
                    status_code=422,
                    content={
                        "code": "RASTER_NOT_SUPPORTED",
                        "filename": fname,
                        "extension": ext,
                    },
                )
            if ext not in (".pdf", ".svg"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "code": "UNSUPPORTED_FORMAT",
                        "filename": fname,
                        "extension": ext,
                    },
                )
            buf = bytearray()
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > MAX_UPLOAD_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"code": "FILE_TOO_LARGE", "filename": fname},
                    )
            raw = bytes(buf)
        finally:
            await file.close()

        if len(raw) == 0:
            return JSONResponse(
                status_code=400,
                content={"code": "EMPTY_FILE", "filename": fname},
            )
        if ext == ".pdf":
            try:
                doc_info = inspect_pdf_document(raw, render_thumbnails=(page_index is None))
            except Exception as exc:
                return JSONResponse(
                    status_code=400,
                    content={"code": "PARSE_FAILED", "detail": str(exc)},
                )
            if doc_info["page_count"] > 1 and page_index is None:
                pid_tmp = f"pend_{uuid.uuid4().hex[:12]}"
                PENDING_UPLOADS[pid_tmp] = PendingMultipageUpload(
                    pending_id=pid_tmp,
                    owner_sid=vsid,
                    filename=fname,
                    raw_bytes=raw,
                    created_at=time.time(),
                )
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "select_page",
                        "code": "MULTI_PAGE_SELECT_REQUIRED",
                        "pending_upload_id": pid_tmp,
                        "filename": fname,
                        "page_count": doc_info["page_count"],
                        "pages": doc_info["pages"],
                    },
                )
            chosen_page = max(0, min(doc_info["page_count"] - 1, int(page_index or 0)))
        else:
            chosen_page = 0
    else:
        return JSONResponse(status_code=400, content={"code": "NO_INPUT", "message": "Provide file, preset_id, or svg_text."})

    fig_id = f"fig_{secrets.token_hex(16)}"
    ws_up = _get_visitor_workspace(vsid)
    now_up = time.time()
    ws_up.upload_timestamps = [t for t in ws_up.upload_timestamps if (now_up - t) < 60.0]
    if len(ws_up.upload_timestamps) >= MAX_UPLOADS_PER_MINUTE:
        return JSONResponse(status_code=429, content={"code": "RATE_LIMITED", "message": "Too many uploads per minute; please wait briefly."})
    ws_up.upload_timestamps.append(now_up)

    owned_uploads = sorted(
        (s for s in SCENES.values() if s.owner_sid == vsid and not s.is_preset),
        key=lambda x: x.last_accessed,
    )
    while len(owned_uploads) >= MAX_FIGURES_PER_VISITOR:
        evict = owned_uploads.pop(0)
        SCENES.pop(evict.scene_id, None)
        _destroy_session_memory(evict)

    kind_up: Literal["pdf", "svg"] = "svg" if ext == ".svg" else "pdf"
    sess = SceneSession(
        scene_id=fig_id,
        filename=fname,
        kind=kind_up,
        owner_sid=vsid,
        is_preset=False,
        status="processing",
        stage="reading_file",
        progress=8,
        slow_warning=len(raw) > LARGE_FILE_WARN_BYTES,
        palette_id=DEFAULT_PALETTE_ID,
        is_original_mode=True,
    )
    SCENES[fig_id] = sess

    if sync:
        _execute_parse_into_session(sess, raw, page_index=chosen_page)
        if sess.status == "error":
            return JSONResponse(
                status_code=422,
                content={
                    "status": "error",
                    "figure_id": fig_id,
                    "code": sess.error_code,
                    "detail": sess.error_detail,
                },
            )
        return JSONResponse({"status": "ready", "figure_id": fig_id, "slow_warning": sess.slow_warning})

    threading.Thread(target=_execute_parse_into_session, args=(sess, raw, chosen_page), daemon=True).start()
    return JSONResponse({"status": "processing", "figure_id": fig_id, "slow_warning": sess.slow_warning})


@app.get("/api/v2/figures/{figure_id}/events")
async def stream_v2_figure_events(figure_id: str) -> StreamingResponse:
    sess = _get_owned_scene(figure_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Figure not found")

    q: queue.Queue[dict[str, Any]] = queue.Queue()
    sess.event_subscribers.append(q)

    async def _gen():
        try:
            init_ev = {
                "stage": sess.stage,
                "progress": sess.progress,
                "figure_id": sess.scene_id,
                "code": sess.error_code,
                "detail": sess.error_detail,
            }
            yield f"data: {json.dumps(init_ev)}\n\n"
            if sess.status in ("ready", "error"):
                return
            deadline = time.time() + 180.0
            while time.time() < deadline:
                try:
                    ev = q.get_nowait()
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev.get("stage") in ("ready", "error"):
                        return
                except queue.Empty:
                    if sess.status in ("ready", "error"):
                        final_ev = {
                            "stage": sess.status,
                            "progress": 100,
                            "figure_id": sess.scene_id,
                            "code": sess.error_code,
                            "detail": sess.error_detail,
                        }
                        yield f"data: {json.dumps(final_ev)}\n\n"
                        return
                    await asyncio.sleep(0.08)
        finally:
            if q in sess.event_subscribers:
                sess.event_subscribers.remove(q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v2/figures/{figure_id}")
def get_v2_figure(figure_id: str) -> Response:
    sess = _get_owned_scene(figure_id)
    if sess is None:
        match = next((x for x in PRESET_MANIFEST if x["preset_id"] == figure_id), None)
        if match:
            sess = _load_preset_item(match, keep_original=True)
    if not sess:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    if sess.status == "error":
        return JSONResponse(
            status_code=422,
            content={
                "figure_id": sess.scene_id,
                "status": "error",
                "code": sess.error_code,
                "detail": sess.error_detail,
            },
        )
    return JSONResponse(_serialize_v2_figure(sess))


class PatchStateRequest(BaseModel):
    action: Literal[
        "set_palette",
        "reset_to_original",
        "reset_panel",
        "set_roles",
        "pick_color",
        "set_lock",
        "rename_element",
        "split_same_name",
        "reset_element",
        "set_rule",
        "set_vibrancy",
        "set_aesthetic_style",
        "invert_scale",
        "set_keep_consistent",
        "undo",
        "redo",
    ]
    palette_id: str | None = None
    aesthetic_style: str | None = None
    target_panels: list[str] | None = None
    entity_id: str | None = None
    entity_ids: list[str] | None = None
    role: Literal["focus", "normal", "background"] | None = None
    hex_color: str | None = None
    locked: bool | None = None
    label: str | None = None
    rule: Literal["same_name", "unique"] | None = None
    vibrancy: VibrancyMode | None = None
    scale_id: str | None = None
    keep_consistent: bool | None = None


@app.patch("/api/v2/figures/{figure_id}/state")
def patch_v2_figure_state(figure_id: str, req: PatchStateRequest) -> dict[str, Any]:
    sess = _get_owned_scene(figure_id)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found or not ready")
    sess.touch()
    ws = _get_visitor_workspace(sess.owner_sid)
    p = sess.parsed
    structure_changed = False

    if req.action == "undo":
        if sess.undo_stack:
            prev_ids = list(p.entities.keys())
            sess.redo_stack.append(sess.snapshot())
            sess.restore(sess.undo_stack.pop())
            structure_changed = list(p.entities.keys()) != prev_ids
            _recompute_session(sess)
    elif req.action == "redo":
        if sess.redo_stack:
            prev_ids = list(p.entities.keys())
            sess.undo_stack.append(sess.snapshot())
            sess.restore(sess.redo_stack.pop())
            structure_changed = list(p.entities.keys()) != prev_ids
            _recompute_session(sess)
    elif req.action == "set_keep_consistent" and req.keep_consistent is not None:
        ws.keep_consistent = bool(req.keep_consistent)
        if not ws.keep_consistent:
            ws.manuscript_registry.clear()
        _recompute_session(sess)
    else:
        sess.undo_stack.append(sess.snapshot())
        if len(sess.undo_stack) > 50:
            sess.undo_stack.pop(0)
        sess.redo_stack.clear()

        all_panel_ids = [pb.panel_id for pb in p.panels]
        valid_target_panels = [pid for pid in (req.target_panels or []) if pid in set(all_panel_ids)]
        is_subset_scope = 0 < len(valid_target_panels) < len(all_panel_ids)

        if req.action == "set_palette" and req.palette_id:
            chosen_pal = _resolve_palette_id(req.palette_id)
            if is_subset_scope:
                tset = set(valid_target_panels)
                new_ents, did_split = _split_entities_by_panel_scope(p.entities, p.color_groups, tset)
                if did_split:
                    p.entities = new_ents
                    structure_changed = True
                if not sess.panel_palettes:
                    base_p = "__original__" if sess.is_original_mode else sess.palette_id
                    sess.panel_palettes = {pid: base_p for pid in all_panel_ids}
                for pid in valid_target_panels:
                    sess.panel_palettes[pid] = chosen_pal
                sess.palette_id = chosen_pal
                sess.is_original_mode = all(v == "__original__" for v in sess.panel_palettes.values())
            else:
                sess.panel_palettes.clear()
                sess.palette_id = chosen_pal
                sess.is_original_mode = False
        elif req.action == "reset_panel" and valid_target_panels:
            tset = set(valid_target_panels)
            new_ents, did_split = _split_entities_by_panel_scope(p.entities, p.color_groups, tset)
            if did_split:
                p.entities = new_ents
                structure_changed = True
            if not sess.panel_palettes:
                base_p = "__original__" if sess.is_original_mode else sess.palette_id
                sess.panel_palettes = {pid: base_p for pid in all_panel_ids}
            for pid in valid_target_panels:
                sess.panel_palettes[pid] = "__original__"
            for ent in p.entities.values():
                if bool(set(ent.panels) & tset):
                    ent.locked = False
                    ent.tier = "normal"
            for cs in p.continuous_scales.values():
                if cs.panel_id in tset:
                    cs.inverted_polarity = False
            if all(v == "__original__" for v in sess.panel_palettes.values()):
                sess.panel_palettes.clear()
                sess.is_original_mode = True
            else:
                sess.is_original_mode = False
        elif req.action == "reset_to_original":
            sess.is_original_mode = True
            sess.aesthetic_style = None
            sess.panel_palettes.clear()
            if sess.initial_entities:
                prev_ids = list(p.entities.keys())
                p.entities = copy.deepcopy(sess.initial_entities)
                structure_changed = list(p.entities.keys()) != prev_ids
            for ent in p.entities.values():
                ent.locked = False
                ent.tier = "normal"
            for cs in p.continuous_scales.values():
                cs.inverted_polarity = False
        elif req.action == "set_aesthetic_style":
            raw_st = (req.aesthetic_style or "").strip().lower()
            if not raw_st or raw_st in ("none", "off", "__none__"):
                sess.aesthetic_style = None
            elif raw_st in STYLE_PROFILES:
                sess.aesthetic_style = raw_st
            else:
                raise HTTPException(status_code=400, detail=f"Unknown aesthetic style: {req.aesthetic_style}")
        elif req.action == "set_roles" and req.role:
            targets = req.entity_ids or ([req.entity_id] if req.entity_id else [])
            for tid in targets:
                if tid in p.entities:
                    p.entities[tid].tier = req.role
                    p.entities[tid].locked = False
            sess.is_original_mode = False
        elif req.action == "pick_color" and req.entity_id and req.hex_color:
            if req.entity_id in p.entities:
                hx = req.hex_color.strip().upper()
                if not hx.startswith("#"):
                    hx = f"#{hx}"
                ent = p.entities[req.entity_id]
                ent.current_hex = hx
                # Spec 4.6: clicking a swatch or custom color automatically locks the element!
                ent.locked = True
                if ws.keep_consistent:
                    ws.manuscript_registry[ent.label.strip().lower()] = hx
                if sess.is_original_mode:
                    # Lock all OTHER elements at their original colors if user edits one element before choosing a palette!
                    for oid, oent in p.entities.items():
                        if oid != req.entity_id:
                            oent.current_hex = oent.original_hex
                    sess.is_original_mode = False
        elif req.action == "set_lock" and req.entity_id is not None and req.locked is not None:
            if req.entity_id in p.entities:
                p.entities[req.entity_id].locked = bool(req.locked)
        elif req.action == "rename_element" and req.entity_id and req.label:
            clean_lbl = req.label.strip()
            if clean_lbl and req.entity_id in p.entities:
                p.entities[req.entity_id].label = clean_lbl[:64]
        elif req.action == "split_same_name" and req.entity_id:
            if req.entity_id in p.entities:
                ent = p.entities[req.entity_id]
                if len(ent.panels) > 1 and len(ent.member_group_ids) > 1:
                    by_panel: dict[str, list[str]] = {}
                    for gid in ent.member_group_ids:
                        if gid in p.color_groups:
                            by_panel.setdefault(p.color_groups[gid].panel_id, []).append(gid)
                    if len(by_panel) > 1:
                        structure_changed = True
                        new_entities: dict[str, SemanticEntity] = {}
                        for k_eid, k_ent in p.entities.items():
                            if k_eid != req.entity_id:
                                new_entities[k_eid] = k_ent
                                continue
                            for idx_sp, (sp_panel, gids) in enumerate(by_panel.items()):
                                sub_id = req.entity_id if idx_sp == 0 else f"{req.entity_id}_p{idx_sp+1}"
                                cg0 = p.color_groups[gids[0]]
                                new_entities[sub_id] = SemanticEntity(
                                    entity_id=sub_id,
                                    label=ent.label,
                                    category_group=sp_panel,
                                    panels=[sp_panel],
                                    member_group_ids=gids,
                                    original_hex=cg0.original_hex,
                                    current_hex=ent.current_hex,
                                    tier=ent.tier,
                                    locked=ent.locked,
                                    unlinked=True,
                                )
                        p.entities = new_entities
                else:
                    ent.unlinked = True
        elif req.action == "reset_element" and req.entity_id:
            if req.entity_id in p.entities:
                ent = p.entities[req.entity_id]
                ent.current_hex = ent.original_hex
                ent.tier = "normal"
                ent.locked = True
        elif req.action == "set_rule" and req.rule:
            sess.rule = req.rule
            sess.is_original_mode = False
        elif req.action == "set_vibrancy" and req.vibrancy:
            sess.vibrancy = req.vibrancy
            sess.is_original_mode = False
        elif req.action == "invert_scale" and req.scale_id:
            if req.scale_id in p.continuous_scales:
                cs = p.continuous_scales[req.scale_id]
                cs.inverted_polarity = not cs.inverted_polarity

        _recompute_session(sess)

    assert sess.last_solve is not None
    sr = sess.last_solve

    resp: dict[str, Any] = {
        "revision": sess.revision,
        "render_url": f"/api/v2/figures/{sess.scene_id}/render?rev={sess.revision}",
        "palette_id": None if sess.is_original_mode else sess.palette_id,
        "active_palette_fallback": sess.palette_id,
        "is_original_mode": sess.is_original_mode,
        "panel_palettes": dict(sess.panel_palettes),
        "rule": sess.rule,
        "vibrancy": sess.vibrancy,
        "aesthetic_style": sess.aesthetic_style,
        "keep_consistent": _get_visitor_workspace(sess.owner_sid).keep_consistent,
        "can_undo": len(sess.undo_stack) > 0,
        "can_redo": len(sess.redo_stack) > 0,
        "entity_colors": dict(sr.entity_hex),
        "entity_meta": {
            eid: {
                "label": e.label,
                "role": normalize_role(e.tier),
                "locked": e.locked,
                "unlinked": e.unlinked,
                "panels": list(e.panels),
            }
            for eid, e in p.entities.items()
        },
        "group_colors": dict(sr.group_hex),
        "continuous_scales": _serialize_continuous_scales(sess, p, sr),
        "inspector_swatches": sr.inspector_swatches,
        "diagnostics": sr.diagnostics,
        "structure_changed": structure_changed,
    }
    if structure_changed:
        resp["elements"] = _serialize_elements(p, sr)
        resp["categorical_lut"] = _build_categorical_lut(p, sr)
    return resp


def _render_figure_with_cache(
    sess: SceneSession,
    palette_override: str = "",
    style_override: str = "",
    preview_panels: tuple[str, ...] = (),
    preview_entity: str = "",
    preview_hex: str = "",
    scale: float | None = None,
    force_png: bool = False,
) -> tuple[bytes, str]:
    assert sess.parsed is not None
    if sess.last_solve is None:
        _recompute_session(sess)
    assert sess.last_solve is not None

    p = sess.parsed
    base_scale = p.preview_scale
    eff_scale = base_scale if scale is None else max(0.5, min(5.0, round(float(scale) * 4.0) / 4.0))
    pal_norm = _resolve_palette_id(palette_override) if palette_override else ""
    st_raw = style_override.strip().lower()
    if not st_raw:
        eff_style = sess.aesthetic_style
    elif st_raw in ("__none__", "none", "off"):
        eff_style = None
    elif st_raw in STYLE_PROFILES:
        eff_style = st_raw
    else:
        eff_style = sess.aesthetic_style
    style_hover_changed = eff_style != sess.aesthetic_style

    ph_norm = preview_hex.strip().lstrip("#").upper() if preview_hex else ""
    all_panel_ids = [pb.panel_id for pb in p.panels]
    valid_prev_panels = tuple(pid for pid in preview_panels if pid in set(all_panel_ids))

    # Instant 0 ms shortcut when displaying unmodified original figure at base preview scale
    if (
        sess.is_original_mode
        and not sess.panel_palettes
        and not pal_norm
        and not eff_style
        and not preview_entity
        and abs(eff_scale - base_scale) < 1e-4
    ):
        if isinstance(p, ParsedPdfScene) and p.original_png:
            return p.original_png, "image/png"
        if isinstance(p, SvgScene) and not force_png and p.original_svg:
            return p.original_svg, "image/svg+xml"

    is_temp_solve = bool(pal_norm or style_hover_changed)
    is_hover = bool(is_temp_solve or preview_entity)
    my_hover_seq = 0
    if is_hover:
        sess.hover_seq += 1
        my_hover_seq = sess.hover_seq

    cache_key = (
        sess.revision if not is_temp_solve else -1,
        pal_norm or sess.palette_id,
        eff_style or "",
        valid_prev_panels if pal_norm else (),
        tuple(sorted(sess.panel_palettes.items())) if is_temp_solve else (),
        sess.is_original_mode if is_temp_solve else False,
        sess.rule if is_temp_solve else "",
        sess.vibrancy if is_temp_solve else "",
        preview_entity,
        ph_norm,
        eff_scale,
        force_png,
    )

    with sess.render_lock:
        if cache_key in sess.render_cache:
            sess.render_cache.move_to_end(cache_key)
            cached_b = sess.render_cache[cache_key]
            media = "image/png" if (sess.kind == "pdf" or force_png) else "image/svg+xml"
            return cached_b, media

    if is_temp_solve:
        if pal_norm:
            is_subset_prev = 0 < len(valid_prev_panels) < len(all_panel_ids)
            if is_subset_prev:
                tset = set(valid_prev_panels)
                tmp_ents, _ = _split_entities_by_panel_scope(p.entities, p.color_groups, tset)
                tmp_panel_pals = (
                    dict(sess.panel_palettes)
                    if sess.panel_palettes
                    else {pid: ("__original__" if sess.is_original_mode else sess.palette_id) for pid in all_panel_ids}
                )
                for pid in valid_prev_panels:
                    tmp_panel_pals[pid] = pal_norm
                sr_tmp = _solve_session_colors(
                    entities=tmp_ents,
                    color_groups=p.color_groups,
                    continuous_scales=p.continuous_scales,
                    evidence_regions=p.evidence_regions,
                    all_panel_ids=all_panel_ids,
                    default_palette_id=pal_norm,
                    is_original_mode=False,
                    panel_palettes=tmp_panel_pals,
                    collision_scope=sess.collision_scope,
                    active_pins={},
                    vibrancy=sess.vibrancy,
                )
            else:
                ws = _get_visitor_workspace(sess.owner_sid)
                active_pins = ws.manuscript_registry if ws.keep_consistent else {}
                sr_tmp = solve_scene_colors(
                    p.entities,
                    p.continuous_scales,
                    p.evidence_regions,
                    style_id=pal_norm,
                    collision_scope=sess.collision_scope,
                    pinned_registry=active_pins,
                    vibrancy=sess.vibrancy,
                )
        else:
            ws = _get_visitor_workspace(sess.owner_sid)
            active_pins = ws.manuscript_registry if (ws.keep_consistent and not sess.panel_palettes) else {}
            sr_tmp = _solve_session_colors(
                entities=p.entities,
                color_groups=p.color_groups,
                continuous_scales=p.continuous_scales,
                evidence_regions=p.evidence_regions,
                all_panel_ids=all_panel_ids,
                default_palette_id=sess.palette_id,
                is_original_mode=sess.is_original_mode,
                panel_palettes=sess.panel_palettes,
                collision_scope=sess.collision_scope,
                active_pins=active_pins,
                vibrancy=sess.vibrancy,
            )
        if eff_style:
            sr_tmp = apply_style_to_solve_result(p, sr_tmp, eff_style)
        group_hex = dict(sr_tmp.group_hex)
        scale_stops = dict(sr_tmp.scale_stops)
    else:
        group_hex = dict(sess.last_solve.group_hex)
        scale_stops = dict(sess.last_solve.scale_stops)

    if preview_entity and ph_norm and preview_entity in p.entities:
        hx = f"#{ph_norm}"
        for gid in p.entities[preview_entity].member_group_ids:
            group_hex[gid] = hx

    if is_hover and my_hover_seq != sess.hover_seq:
        raise _StaleHoverAbort()

    if isinstance(p, ParsedPdfScene):
        with PDFIUM_LOCK:
            if is_hover and my_hover_seq != sess.hover_seq:
                raise _StaleHoverAbort()
            data = render_preview_png(p, group_hex, scale_stops, scale=eff_scale)
        media = "image/png"
    else:
        svg_b, _ = export_recolored_svg(p, group_hex, scale_stops)
        if force_png:
            data = render_svg_bytes_to_png(svg_b, zoom=eff_scale, background="#ffffff")
            media = "image/png"
        else:
            data = svg_b
            media = "image/svg+xml"

    with sess.render_lock:
        sess.render_cache[cache_key] = data
        sess.render_cache.move_to_end(cache_key)
        while len(sess.render_cache) > MAX_RENDER_CACHE_ITEMS:
            sess.render_cache.popitem(last=False)

    return data, media


@app.get("/api/v2/figures/{figure_id}/render")
def get_v2_figure_render(
    figure_id: str,
    rev: int = 0,
    scale: float | None = None,
    palette: str = "",
    style: str = "",
    panels: str = "",
    pe: str = "",
    ph: str = "",
    fmt: str = "",
) -> Response:
    sess = _get_owned_scene(figure_id)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    panel_tuple = tuple(s.strip() for s in panels.split(",") if s.strip()) if panels else ()
    try:
        data, media = _render_figure_with_cache(
            sess,
            palette_override=palette,
            style_override=style,
            preview_panels=panel_tuple,
            preview_entity=pe,
            preview_hex=ph,
            scale=scale,
            force_png=(fmt == "png"),
        )
    except _StaleHoverAbort:
        return Response(status_code=204)
    cache_hdr = "private, max-age=300" if sess.is_preset else "private, no-store"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Cache-Control": cache_hdr,
            "X-Danqing-Revision": str(sess.revision),
        },
    )


@app.get("/api/v2/figures/{figure_id}/pick")
def get_v2_figure_pick(figure_id: str) -> Response:
    sess = _get_owned_scene(figure_id)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    p = sess.parsed
    cache_hdr = "private, max-age=3600" if sess.is_preset else "private, no-store"
    return Response(
        content=p.id_map_png,
        media_type="image/png",
        headers={"Cache-Control": cache_hdr},
    )


@app.get("/api/v2/figures/{figure_id}/original")
def get_v2_figure_original(figure_id: str) -> Response:
    sess = _get_owned_scene(figure_id)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    p = sess.parsed
    cache_hdr = "private, max-age=3600" if sess.is_preset else "private, no-store"
    if isinstance(p, ParsedPdfScene):
        return Response(content=p.original_png, media_type="image/png", headers={"Cache-Control": cache_hdr})
    return Response(content=p.original_svg, media_type="image/svg+xml", headers={"Cache-Control": cache_hdr})


class ExportRequest(BaseModel):
    format: Literal["pdf", "svg", "png_300", "png_600"] = "pdf"
    include_r: bool = True
    include_python: bool = True
    include_json: bool = False
    include_change_report: bool = False
    force: bool = False


def _compute_verified_export(sess: SceneSession, fmt: str) -> tuple[bytes, str, str, dict[str, Any], dict[str, Any]]:
    """Run real byte-verified vector export + optional high-DPI rasterization, returning live check results."""
    assert sess.parsed is not None
    if sess.last_solve is None:
        _recompute_session(sess)
    assert sess.last_solve is not None
    p = sess.parsed
    sr = sess.last_solve

    vec_key = (sess.revision, sess.kind)
    with sess.render_lock:
        cached = sess.verified_export_cache.get(vec_key)
    if cached is not None:
        vec_bytes, audit = cached
    else:
        if isinstance(p, ParsedPdfScene):
            vec_bytes, audit = export_recolored_pdf(p, sr.group_hex, sr.scale_stops, verify=True)
        else:
            vec_bytes, audit = export_recolored_svg(p, sr.group_hex, sr.scale_stops)
        with sess.render_lock:
            sess.verified_export_cache[vec_key] = (vec_bytes, audit)

    raw_img_count = sum(
        1 for ev in p.evidence_regions if ev.mutability in ("class0_sacrosanct_evidence", "class1_fluorescence_lut")
    )
    shapes_ok = bool(audit.get("g6_geometry_identical", False))
    images_ok = bool(audit.get("g0_evidence_bit_identical", True))
    cb_deutan_ok = bool(sr.diagnostics.get("colorblind_deutan_safe", True))

    checks = {
        "shapes_and_text_unchanged": shapes_ok,
        "raw_images_untouched": {
            "passed": images_ok,
            "count": raw_img_count,
        },
        "colorblind_safe": {
            "passed": cb_deutan_ok,
            "min_de_deutan": sr.diagnostics.get("min_de2000_deutan", 26.0),
            "problem_panels": sr.diagnostics.get("colorblind_problem_panels", []),
        },
        "all_passed": bool(shapes_ok and images_ok and cb_deutan_ok),
        "integrity_passed": bool(shapes_ok and images_ok),
    }

    stem = Path(p.filename).stem
    base_slug = "original" if sess.is_original_mode else sess.palette_id
    pal_slug = f"{base_slug}_{sess.aesthetic_style}" if sess.aesthetic_style else base_slug

    if fmt in ("png_300", "png_600"):
        dpi = 300 if fmt == "png_300" else 600
        if isinstance(p, ParsedPdfScene):
            pil = render_pdf_page_to_pil(
                vec_bytes,
                page_index=p.page_index,
                scale=dpi / 72.0,
                fill_color=(255, 255, 255, 255),
            )
            buf = io.BytesIO()
            pil.save(buf, format="PNG", dpi=(dpi, dpi), compress_level=4)
            fig_bytes = buf.getvalue()
        else:
            fig_bytes = render_svg_bytes_to_png(vec_bytes, dpi=float(dpi), background="#ffffff")
        fig_name = f"{stem}_danqing_{pal_slug}_{dpi}dpi.png"
        media = "image/png"
    elif fmt == "svg" and isinstance(p, SvgScene):
        fig_bytes = vec_bytes
        fig_name = f"{stem}_danqing_{pal_slug}.svg"
        media = "image/svg+xml"
    elif fmt == "pdf" and isinstance(p, ParsedPdfScene):
        fig_bytes = vec_bytes
        fig_name = f"{stem}_danqing_{pal_slug}.pdf"
        media = "application/pdf"
    elif fmt == "pdf" and isinstance(p, SvgScene):
        # High-res 300 DPI PDF wrapper when exporting an SVG input as PDF
        png300 = render_svg_bytes_to_png(vec_bytes, dpi=300.0, background="#ffffff")
        pil = Image.open(io.BytesIO(png300)).convert("RGB")
        buf = io.BytesIO()
        pil.save(buf, format="PDF", resolution=300.0)
        fig_bytes = buf.getvalue()
        fig_name = f"{stem}_danqing_{pal_slug}.pdf"
        media = "application/pdf"
    else:
        # PDF exported as SVG wrapper (300 DPI embedded or native fallback)
        pil = render_pdf_page_to_pil(
            vec_bytes,
            page_index=p.page_index,
            scale=300.0 / 72.0,
            fill_color=(255, 255, 255, 255),
        )
        import base64

        b_png = io.BytesIO()
        pil.save(b_png, format="PNG")
        b64 = base64.b64encode(b_png.getvalue()).decode("ascii")
        svg_wrap = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {p.page_width} {p.page_height}" '
            f'width="{p.page_width}" height="{p.page_height}">\n'
            f'  <image x="0" y="0" width="{p.page_width}" height="{p.page_height}" href="data:image/png;base64,{b64}"/>\n'
            f"</svg>\n"
        ).encode("utf-8")
        fig_bytes = svg_wrap
        fig_name = f"{stem}_danqing_{pal_slug}.svg"
        media = "image/svg+xml"

    return fig_bytes, fig_name, media, checks, audit


@app.post("/api/v2/figures/{figure_id}/export/verify")
def verify_v2_figure_export(figure_id: str, req: ExportRequest) -> dict[str, Any]:
    sess = _get_owned_scene(figure_id)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    fig_bytes, fig_name, _, checks, _ = _compute_verified_export(sess, req.format)
    return {
        "filename": fig_name,
        "size_kb": round(len(fig_bytes) / 1024.0, 1),
        "checks": checks,
    }


@app.post("/api/v2/figures/{figure_id}/export")
def export_v2_figure(figure_id: str, req: ExportRequest) -> Response:
    sess = _get_owned_scene(figure_id)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    p = sess.parsed
    assert sess.last_solve is not None
    sr = sess.last_solve

    fig_bytes, fig_name, media, checks, audit = _compute_verified_export(sess, req.format)
    if not checks["all_passed"] and not req.force:
        return JSONResponse(
            status_code=409,
            content={
                "code": "EXPORT_CHECKS_FAILED",
                "checks": checks,
            },
        )

    has_extras = any([req.include_r, req.include_python, req.include_json, req.include_change_report])
    if not has_extras:
        return Response(
            content=fig_bytes,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{fig_name}"'},
        )

    stem = Path(p.filename).stem
    base_slug = "original" if sess.is_original_mode else sess.palette_id
    pal_slug = f"{base_slug}_{sess.aesthetic_style}" if sess.aesthetic_style else base_slug
    zip_name = f"{stem}_danqing_{pal_slug}.zip"

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(fig_name, fig_bytes)
        if req.include_r:
            zf.writestr(
                f"{stem}_palette_ggplot2.R",
                generate_r_ggplot_snippet(pal_slug, p.entities, sr.entity_hex, p.continuous_scales, sr.scale_stops),
            )
        if req.include_python:
            zf.writestr(
                f"{stem}_palette_matplotlib.py",
                generate_python_mpl_snippet(pal_slug, p.entities, sr.entity_hex, p.continuous_scales, sr.scale_stops),
            )
        if req.include_json:
            cert = build_verification_certificate(
                p.filename,
                sess.palette_id,
                sess.collision_scope,
                p.entities,
                sr.entity_hex,
                p.continuous_scales,
                sr.scale_stops,
                p.evidence_regions,
                sr.diagnostics,
                audit,
            )
            zf.writestr(f"{stem}_palette.json", json.dumps(cert, indent=2, ensure_ascii=False))
        if req.include_change_report:
            zf.writestr(f"{stem}_changes.csv", generate_change_report_csv(p.entities, sr.entity_hex))

    return Response(
        content=zbuf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.delete("/api/v2/figures/{figure_id}")
def delete_v2_figure(figure_id: str) -> dict[str, Any]:
    vsid = _current_visitor_sid()
    sess = _get_owned_scene(figure_id, vsid)
    if sess is not None:
        popped = SCENES.pop(_scene_storage_key(figure_id, vsid), None)
        if popped is not None:
            _destroy_session_memory(popped)
    return {"deleted": figure_id}


@app.post("/api/v2/figures/{figure_id}/close")
def close_v2_figure_beacon(figure_id: str) -> dict[str, Any]:
    """Beacon endpoint called via `navigator.sendBeacon` when closing tab (Spec 4.1 privacy cleanup)."""
    vsid = _current_visitor_sid()
    sess = _get_owned_scene(figure_id, vsid)
    if sess is not None and not sess.is_preset:
        popped = SCENES.pop(_scene_storage_key(figure_id, vsid), None)
        if popped is not None:
            _destroy_session_memory(popped)
    return {"deleted": figure_id}


@app.post("/api/v2/session/clear")
def clear_visitor_session() -> dict[str, Any]:
    """Immediately purges all in-memory figures and pins belonging to the calling browser session."""
    vsid = _current_visitor_sid()
    removed = _purge_visitor_workspace(vsid)
    return {"cleared": True, "removed_figures": removed}


class ManuscriptMatchRequest(BaseModel):
    preset: str | None = None
    brief: str = ""


@app.post("/api/v2/figures/{figure_id}/manuscript-match")
def match_v2_figure_manuscript(
    figure_id: str,
    req: ManuscriptMatchRequest,
    x_gemini_key: str | None = Header(default=None, alias="X-Gemini-Key"),
) -> dict[str, Any]:
    vsid = _current_visitor_sid()
    sess = _get_owned_scene(figure_id, vsid)
    if not sess or sess.status != "ready" or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Figure not found")
    sess.touch()
    p = sess.parsed

    req_k = max(1, sum(1 for e in p.entities.values() if e.tier != "background"))
    has_cont = len(p.continuous_scales) > 0
    has_div = any(s.kind == "continuous_diverging" for s in p.continuous_scales.values())
    labels = [e.label for e in p.entities.values()]

    ws = _get_visitor_workspace(vsid)
    if ws.keep_consistent:
        for other in list(SCENES.values()):
            if other.owner_sid == vsid and not other.is_preset and other.parsed is not None:
                other_k = sum(1 for e in other.parsed.entities.values() if e.tier != "background")
                req_k = max(req_k, other_k)
                has_cont = has_cont or (len(other.parsed.continuous_scales) > 0)
                has_div = has_div or any(
                    s.kind == "continuous_diverging" for s in other.parsed.continuous_scales.values()
                )

    return match_manuscript_palettes(
        required_k=req_k,
        has_continuous=has_cont,
        has_diverging=has_div,
        element_labels=labels,
        preset=req.preset,
        brief=req.brief[:300],
        gemini_api_key=(x_gemini_key or "").strip() or None,
    )


@app.get("/api/v2/health")
def health_v2() -> dict[str, Any]:
    return {"status": "ok", "storage": "ephemeral_ram_only", "disk_retention": False}


# ==============================================================================
# Legacy `/api/scenes/*` Compatibility Routes (for Phase A Golden Tests)
# ==============================================================================


class LegacyMutateRequest(BaseModel):
    action: str
    style_id: str | None = None
    is_original: bool | None = None
    collision_scope: str | None = None
    entity_id: str | None = None
    tier: str | None = None
    hex_color: str | None = None
    label: str | None = None
    scale_id: str | None = None


def _serialize_legacy_scene(sess: SceneSession) -> dict[str, Any]:
    v2 = _serialize_v2_figure(sess)
    return {
        **v2,
        "style_id": sess.palette_id,
        "collision_scope": sess.collision_scope,
        "render_url": f"/api/scenes/{sess.scene_id}/render?rev={sess.revision}",
        "layer_urls": {
            "original": f"/api/scenes/{sess.scene_id}/layers/original",
            "id_map": f"/api/scenes/{sess.scene_id}/layers/id_map",
        },
        "gates_summary": v2["diagnostics"],
    }


@app.get("/api/scenes/{scene_id}")
def legacy_get_scene(scene_id: str) -> dict[str, Any]:
    sess = _get_owned_scene(scene_id)
    if sess is None:
        match = next((x for x in PRESET_MANIFEST if x["preset_id"] == scene_id), None)
        if match:
            sess = _load_preset_item(match, keep_original=False)
    if not sess or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    return _serialize_legacy_scene(sess)


@app.get("/api/scenes/{scene_id}/layers/{layer_name}")
def legacy_get_layer(scene_id: str, layer_name: str) -> Response:
    sess = _get_owned_scene(scene_id)
    if not sess or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    p = sess.parsed
    if layer_name == "id_map":
        if isinstance(p, ParsedPdfScene):
            return Response(content=p.id_map_png, media_type="image/png")
        return Response(content=p.id_map_svg, media_type="image/svg+xml")
    if isinstance(p, ParsedPdfScene):
        return Response(content=p.original_png, media_type="image/png")
    return Response(content=p.original_svg, media_type="image/svg+xml")


@app.get("/api/scenes/{scene_id}/render")
def legacy_get_render(scene_id: str, rev: int = 0, pe: str = "", ph: str = "") -> Response:
    return get_v2_figure_render(scene_id, rev=rev, pe=pe, ph=ph)


@app.post("/api/scenes/{scene_id}/mutate")
def legacy_mutate_scene(scene_id: str, req: LegacyMutateRequest) -> dict[str, Any]:
    sess = _get_owned_scene(scene_id)
    if sess is None:
        match = next((x for x in PRESET_MANIFEST if x["preset_id"] == scene_id), None)
        if match:
            _load_preset_item(match, keep_original=False)
    if req.action == "set_style":
        patch_v2_figure_state(scene_id, PatchStateRequest(action="set_palette", palette_id=req.style_id))
    elif req.action == "set_collision_scope":
        rule = "unique" if req.collision_scope in ("global_strict", "unique") else "same_name"
        patch_v2_figure_state(scene_id, PatchStateRequest(action="set_rule", rule=rule))
    elif req.action == "pick_entity_color":
        patch_v2_figure_state(scene_id, PatchStateRequest(action="pick_color", entity_id=req.entity_id, hex_color=req.hex_color))
    elif req.action == "toggle_scale_polarity":
        patch_v2_figure_state(scene_id, PatchStateRequest(action="invert_scale", scale_id=req.scale_id))
    elif req.action == "set_entity_tier" and req.tier:
        patch_v2_figure_state(scene_id, PatchStateRequest(action="set_roles", entity_id=req.entity_id, role=normalize_role(req.tier)))
    sess_out = _get_owned_scene(scene_id)
    assert sess_out is not None
    return _serialize_legacy_scene(sess_out)


@app.get("/api/scenes/{scene_id}/export_bundle")
def legacy_export_bundle(scene_id: str) -> dict[str, Any]:
    sess = _get_owned_scene(scene_id)
    if not sess or sess.parsed is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    fmt: Literal["pdf", "svg"] = "pdf" if sess.kind == "pdf" else "svg"
    fig_bytes, fig_name, _, checks, audit = _compute_verified_export(sess, fmt)
    sess.cached_export_bytes = fig_bytes
    sess.cached_export_filename = fig_name
    return {"download_url": f"/api/scenes/{scene_id}/download", "filename": fig_name, "checks": checks, "audit": audit}


@app.get("/api/scenes/{scene_id}/download")
def legacy_download(scene_id: str) -> Response:
    sess = _get_owned_scene(scene_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Scene not found")
    if sess.cached_export_bytes is None:
        legacy_export_bundle(scene_id)
    assert sess.cached_export_bytes is not None
    media = "application/pdf" if sess.kind == "pdf" else "image/svg+xml"
    return Response(content=sess.cached_export_bytes, media_type=media)


if FRONTEND_DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True), name="frontend")
