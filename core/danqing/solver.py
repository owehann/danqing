"""Palette assignment & local-swap optimization solver for Danqing (Spec Section 8 / WP3).

Implements exact Section 8.2 algorithm:
1. Merge same-name elements into unified color variables across panels (unless explicitly unlinked).
2. Pre-assign locked and manuscript-consistent variables.
3. Background role -> palette's low-chroma neutral (or `#BDBDBD`), stepped gently if multiple background items share a panel.
4. Focus role -> palette color maximizing contrast against assigned colors & white paper + OKLCH chroma.
5. Normal role:
   - K <= N: designer order (`order == "discrete"`) or max-min ΔE2000 subset (`order == "gradient"`),
     followed by <= 200 local swap iterations enforcing same-panel ΔE2000 >= 12 and CVD ΔE2000 >= 8.
     Zero cross-panel color reuse whenever K_total <= N (even under `panel_scoped` / "Same name, same color").
   - K > N:
     * Under `panel_scoped`, reuse unused-in-panel palette colors only after all N palette colors are in use,
       preferring variables from semantically distant legend groups (`category_group`).
     * When a single panel exceeds N (or under `global_strict` / "Every element unique"), expand via
       hierarchical prefix lightness rungs (`L +/- 0.12`) when prefix families exist, else OKLCH convex-hull
       Glasbey max-min ΔE2000 generation, reporting `generated_count`.
6. Continuous scales -> palette's paired sequential/diverging ramp (midpoint anchored for diverging),
   automatically switching partner if high-end stop has ΔE2000 < 15 against any Focus element.
7. Inspector swatches -> ALL colors of the active palette sorted by minimum ΔE2000 against co-panel elements,
   annotating `too_close_to` when ΔE2000 < 10.0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .color_science import (
    apca_contrast,
    ciede2000_matrix,
    hex_to_oklch,
    hex_to_srgb01,
    oklch_to_hex,
    simulate_cvd,
)
from .ir import ContinuousScale, EvidenceRegion, SemanticEntity
from .palettes import (
    DEFAULT_PALETTE_ID,
    PaletteDefinition,
    apply_vibrancy,
    expand_glasbey_in_hull,
    get_palette,
)

CollisionScope = Literal["panel_scoped", "global_strict"]
VibrancyMode = Literal["muted", "standard", "vivid"]


def normalize_role(tier: str) -> Literal["focus", "normal", "background"]:
    t = (tier or "normal").strip().lower()
    if t in ("focus", "protagonist"):
        return "focus"
    if t in ("background", "context", "control"):
        return "background"
    return "normal"


@dataclass
class SolveResult:
    palette_id: str
    collision_scope: CollisionScope
    vibrancy: VibrancyMode
    entity_hex: dict[str, str]
    group_hex: dict[str, str]
    scale_stops: dict[str, list[str]]
    entity_swatches: dict[str, list[str]]
    inspector_swatches: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def style_id(self) -> str:
        return self.palette_id

    @property
    def gates_summary(self) -> dict[str, Any]:
        return self.diagnostics


@dataclass
class _ColorVar:
    var_id: str
    norm_key: str
    label: str
    category_group: str
    role: Literal["focus", "normal", "background"]
    panels: set[str]
    entity_ids: list[str]
    locked_hex: str | None = None


def _extract_prefix_family(label: str) -> str | None:
    """Return shared prefix token (e.g. `CD4` from `CD4_T`, `CD4_Treg`) for hierarchical clustering."""
    clean = label.strip()
    parts = re.split(r"[_\-/:.\s]+", clean)
    if len(parts) >= 2 and len(parts[0]) >= 2 and not parts[0].isdigit():
        # Ignore generic fallback words like "Group", "Cluster", "Blue", "Item"
        if parts[0].lower() not in {"group", "cluster", "item", "panel", "blue", "red", "green", "orange", "purple", "gray", "grey", "teal", "brown"}:
            return parts[0]
    return None


def _select_maxmin_subset_indices(arr: np.ndarray, k: int, avoid_arr: np.ndarray | None = None) -> list[int]:
    """Deterministically pick `k` indices from `arr` maximizing pairwise min CIEDE2000 (for gradient-ordered palettes)."""
    n = len(arr)
    if k <= 0 or n == 0:
        return []
    if k >= n:
        return list(range(n))
    mat = ciede2000_matrix(arr)
    if k == 1:
        if avoid_arr is not None and len(avoid_arr) > 0:
            d_av = ciede2000_matrix(arr, avoid_arr).min(axis=1)
            return [int(np.argmax(d_av))]
        return [0]

    if avoid_arr is not None and len(avoid_arr) > 0:
        d_av = ciede2000_matrix(arr, avoid_arr).min(axis=1)
        chosen = [int(np.argmax(d_av))]
    else:
        # Start with the two most distinct colors in the gradient
        i0, i1 = np.unravel_index(int(np.argmax(mat)), mat.shape)
        chosen = [int(min(i0, i1)), int(max(i0, i1))]

    while len(chosen) < k:
        best_i = -1
        best_d = -1.0
        for idx in range(n):
            if idx in chosen:
                continue
            d_sel = min(float(mat[idx, c]) for c in chosen)
            if avoid_arr is not None and len(avoid_arr) > 0:
                d_sel = min(d_sel, float(ciede2000_matrix(arr[[idx]], avoid_arr).min()))
            if d_sel > best_d:
                best_d = d_sel
                best_i = idx
        if best_i < 0:
            break
        chosen.append(best_i)
    return chosen[:k]


def _expand_hierarchical_or_glasbey(
    base_pool: list[str],
    vars_to_color: list[_ColorVar],
) -> tuple[dict[str, str], int]:
    """Assign `K > N` variables using prefix lightness rungs when hierarchy exists, else OKLCH Glasbey expansion."""
    k = len(vars_to_color)
    n = len(base_pool)
    fam_map: dict[str, list[_ColorVar]] = {}
    singletons: list[_ColorVar] = []
    for v in vars_to_color:
        fam = _extract_prefix_family(v.label)
        if fam:
            fam_map.setdefault(fam, []).append(v)
        else:
            singletons.append(v)

    real_fams = {f: members for f, members in fam_map.items() if len(members) >= 2}
    for f, members in fam_map.items():
        if len(members) < 2:
            singletons.extend(members)

    if real_fams:
        total_anchors = len(real_fams) + len(singletons)
        if total_anchors <= n:
            b_arr = np.stack([hex_to_srgb01(c) for c in base_pool], axis=0)
            sub_i = _select_maxmin_subset_indices(b_arr, total_anchors)
            anchor_pool = [base_pool[i] for i in sub_i]
        else:
            anchor_pool = expand_glasbey_in_hull(base_pool, total_anchors)

        # Pre-generate a large collision-free hull reserve (`k + 8` colors) so congested hue corridors stay >= 9 ΔE
        hull_reserve = expand_glasbey_in_hull(anchor_pool, k + 8)

        assigned: dict[str, str] = {}
        used_rgbs: list[np.ndarray] = []
        anchor_idx = 0

        # Assign all primary family anchors + singletons first so sub-rungs avoid every anchor hue
        fam_anchors: dict[str, str] = {}
        for fam_key, members in real_fams.items():
            base_hex = anchor_pool[anchor_idx]
            anchor_idx += 1
            fam_anchors[fam_key] = base_hex
            assigned[members[0].var_id] = base_hex
            used_rgbs.append(hex_to_srgb01(base_hex))

        for sv in singletons:
            shx = anchor_pool[anchor_idx]
            anchor_idx += 1
            assigned[sv.var_id] = shx
            used_rgbs.append(hex_to_srgb01(shx))

        rung_offsets = [
            (-0.15, 0.94, 0.0),
            (+0.15, 0.86, 0.0),
            (-0.25, 0.92, -8.0),
            (+0.24, 0.78, +8.0),
            (-0.18, 1.08, +14.0),
            (+0.18, 0.95, -14.0),
            (-0.28, 0.88, +18.0),
            (+0.26, 0.74, -18.0),
        ]
        white = np.array([[1.0, 1.0, 1.0]], dtype=np.float64)

        for fam_key, members in real_fams.items():
            bL, bC, bh = hex_to_oklch(fam_anchors[fam_key])
            for mv in members[1:]:
                u_arr = np.stack(used_rgbs, axis=0)
                best_cand: str | None = None
                best_min_d = -1.0
                for dL, c_sc, dh in rung_offsets:
                    tL = float(np.clip(bL + dL, 0.25, 0.83))
                    tC = float(np.clip(bC * c_sc, 0.045, 0.205))
                    th = (bh + dh) % 360.0
                    chx = oklch_to_hex(tL, tC, th)
                    crgb = hex_to_srgb01(chx)[None, :]
                    if float(ciede2000_matrix(crgb, white)[0, 0]) < 14.5:
                        continue
                    md = float(ciede2000_matrix(crgb, u_arr).min())
                    if md >= 9.5 and md > best_min_d:
                        best_min_d = md
                        best_cand = chx
                if best_cand is None:
                    # Fallback to the Glasbey reserve color maximizing min ΔE (with slight preference for hue proximity)
                    for rhx in hull_reserve:
                        rrgb = hex_to_srgb01(rhx)[None, :]
                        md = float(ciede2000_matrix(rrgb, u_arr).min())
                        _, _, rh = hex_to_oklch(rhx)
                        h_diff = min(abs(rh - bh), 360.0 - abs(rh - bh))
                        sc = md - 0.015 * h_diff
                        if md >= 8.5 and sc > best_min_d:
                            best_min_d = sc
                            best_cand = rhx
                if best_cand is None:
                    best_cand = max(
                        hull_reserve,
                        key=lambda rhx: float(ciede2000_matrix(hex_to_srgb01(rhx)[None, :], u_arr).min()),
                    )
                assigned[mv.var_id] = best_cand
                used_rgbs.append(hex_to_srgb01(best_cand))

        return assigned, max(0, k - n)

    expanded = expand_glasbey_in_hull(base_pool, k)
    assigned = {v.var_id: expanded[i] for i, v in enumerate(vars_to_color)}
    return assigned, max(0, k - n)


def _optimize_local_swaps(
    normal_vars: list[_ColorVar],
    var_hex: dict[str, str],
    candidate_pool: list[str],
    fixed_vars: list[_ColorVar],
    collision_scope: CollisionScope,
    max_iters: int = 200,
) -> None:
    """Up to 200 local swap iterations to eliminate same-panel ΔE2000 < 12 or CVD < 8 (Spec 8.2.5)."""
    if len(normal_vars) == 0:
        return

    all_vars = fixed_vars + normal_vars
    n_fixed = len(fixed_vars)
    n_norm = len(normal_vars)
    if len(all_vars) < 2 and len(candidate_pool) <= 1:
        return

    # Prebuild boolean constraint mask among all_vars (excluding background-vs-background)
    n_all = len(all_vars)
    constrained = np.zeros((n_all, n_all), dtype=bool)
    for i in range(n_all):
        for j in range(i + 1, n_all):
            va, vb = all_vars[i], all_vars[j]
            if va.role == "background" and vb.role == "background":
                continue
            if collision_scope == "global_strict" or bool(va.panels & vb.panels):
                constrained[i, j] = True
                constrained[j, i] = True

    if not constrained.any():
        return

    pool_unique = list(dict.fromkeys([var_hex[v.var_id] for v in all_vars] + candidate_pool))
    pool_arr = np.stack([hex_to_srgb01(c) for c in pool_unique], axis=0)
    de_norm_mat = ciede2000_matrix(pool_arr)
    de_deut_mat = ciede2000_matrix(simulate_cvd(pool_arr, "deutan", 1.0))
    de_prot_mat = ciede2000_matrix(simulate_cvd(pool_arr, "protan", 1.0))
    de_cvd_mat = np.minimum(de_deut_mat, de_prot_mat)

    hex_to_pidx = {h: idx for idx, h in enumerate(pool_unique)}
    cur_idx = [hex_to_pidx[var_hex[v.var_id]] for v in all_vars]
    ii, jj = np.where(np.triu(constrained, k=1))

    def _Objective(idxs: list[int]) -> tuple[int, int, float]:
        if len(ii) == 0:
            return (0, 0, -99.0)
        pi = [idxs[a] for a in ii]
        pj = [idxs[b] for b in jj]
        dn = de_norm_mat[pi, pj]
        dc = de_cvd_mat[pi, pj]
        v_norm = int((dn < 12.0).sum())
        v_cvd = int((dc < 8.0).sum())
        min_dn = float(dn.min())
        min_dc = float(dc.min())
        return (v_norm, v_cvd, -(min_dn + 0.55 * min_dc))

    cur_obj = _Objective(cur_idx)
    if cur_obj[0] == 0 and cur_obj[1] == 0:
        return

    allow_cross_panel_dup = collision_scope == "panel_scoped" and len(pool_unique) < n_all

    for _ in range(max_iters):
        if cur_obj[0] == 0 and cur_obj[1] == 0:
            break
        improved = False

        # 1. Try swapping colors between two Normal variables
        for a in range(n_fixed, n_all):
            for b in range(a + 1, n_all):
                if cur_idx[a] == cur_idx[b]:
                    continue
                cur_idx[a], cur_idx[b] = cur_idx[b], cur_idx[a]
                cand_obj = _Objective(cur_idx)
                if cand_obj < cur_obj:
                    cur_obj = cand_obj
                    improved = True
                    break
                cur_idx[a], cur_idx[b] = cur_idx[b], cur_idx[a]
            if improved:
                break

        if improved:
            continue

        # 2. Try replacing a Normal variable's color with an unused color from pool_unique
        used_set = set(cur_idx)
        for a in range(n_fixed, n_all):
            orig_p = cur_idx[a]
            for p_cand in range(len(pool_unique)):
                if p_cand == orig_p:
                    continue
                if p_cand in used_set and not allow_cross_panel_dup:
                    continue
                cur_idx[a] = p_cand
                cand_obj = _Objective(cur_idx)
                if cand_obj < cur_obj:
                    cur_obj = cand_obj
                    improved = True
                    break
                cur_idx[a] = orig_p
            if improved:
                break

        if not improved:
            break

    for k_i in range(n_norm):
        v = normal_vars[k_i]
        var_hex[v.var_id] = pool_unique[cur_idx[n_fixed + k_i]]


def solve_scene_colors(
    entities: dict[str, SemanticEntity],
    continuous_scales: dict[str, ContinuousScale],
    evidence_regions: list[EvidenceRegion],
    style_id: str = DEFAULT_PALETTE_ID,
    collision_scope: CollisionScope = "panel_scoped",
    chroma_bias: float = 0.0,
    contrast_bias: float = 0.0,
    pinned_registry: dict[str, str] | None = None,
    vibrancy: VibrancyMode | None = None,
) -> SolveResult:
    """Assign optimal colors to all categorical elements and continuous scales in < 20 ms."""
    pal: PaletteDefinition = get_palette(style_id)
    registry = pinned_registry or {}
    if collision_scope in ("unique", "global_strict"):
        collision_scope = "global_strict"
    else:
        collision_scope = "panel_scoped"

    if vibrancy is None:
        if chroma_bias <= -0.25:
            vib: VibrancyMode = "muted"
        elif chroma_bias >= 0.25:
            vib = "vivid"
        else:
            vib = "standard"
    else:
        vib = vibrancy

    ent_list = list(entities.values())

    # 1. Merge same-name entities across panels into unified color variables (unless `unlinked`)
    vars_by_key: dict[str, _ColorVar] = {}
    ordered_vars: list[_ColorVar] = []
    for ent in ent_list:
        norm_lbl = ent.label.strip().lower()
        vkey = f"__id__{ent.entity_id}" if (ent.unlinked or not norm_lbl) else f"__lbl__{norm_lbl}"
        role = normalize_role(ent.tier)
        locked_h: str | None = None
        if ent.locked:
            locked_h = ent.current_hex.upper()
        elif ent.pinned_manuscript and norm_lbl in registry:
            locked_h = registry[norm_lbl].upper()

        if vkey not in vars_by_key:
            cv = _ColorVar(
                var_id=vkey,
                norm_key=norm_lbl,
                label=ent.label,
                category_group=ent.category_group or "",
                role=role,
                panels=set(ent.panels),
                entity_ids=[ent.entity_id],
                locked_hex=locked_h,
            )
            vars_by_key[vkey] = cv
            ordered_vars.append(cv)
        else:
            cv = vars_by_key[vkey]
            cv.panels.update(ent.panels)
            cv.entity_ids.append(ent.entity_id)
            if locked_h and not cv.locked_hex:
                cv.locked_hex = locked_h
            # Upgrade role priority if one member was promoted to focus
            if role == "focus":
                cv.role = "focus"
            elif role == "background" and cv.role == "normal":
                cv.role = "background"

    raw_palette_colors = apply_vibrancy(list(pal.colors), vib)
    neutral_base = (pal.neutral or "#BDBDBD").upper()
    var_hex: dict[str, str] = {}
    generated_count = 0

    # 2. Pre-assign locked variables & domain conventions (`convention_keys`)
    if pal.convention_keys:
        conv_map = dict(zip((k.strip().lower() for k in pal.convention_keys), raw_palette_colors))
        for cv in ordered_vars:
            if not cv.locked_hex and cv.norm_key in conv_map:
                cv.locked_hex = conv_map[cv.norm_key]

    for cv in ordered_vars:
        if cv.locked_hex:
            var_hex[cv.var_id] = cv.locked_hex

    locked_hex_set = {h.upper() for h in var_hex.values()}

    # 3. Assign Background role variables
    bg_vars = [cv for cv in ordered_vars if cv.var_id not in var_hex and cv.role == "background"]
    bg_rungs = [
        neutral_base,
        oklch_to_hex(0.84, 0.008, 250.0),
        oklch_to_hex(0.68, 0.010, 250.0),
        oklch_to_hex(0.76, 0.012, 80.0),
    ]
    for idx_b, cv in enumerate(bg_vars):
        # If single background in its panels, use exact palette neutral; if multiple share a panel, step lightness
        co_bg = sum(1 for other in bg_vars[:idx_b] if other.panels & cv.panels)
        var_hex[cv.var_id] = bg_rungs[co_bg % len(bg_rungs)]

    # Build available chromatic pool excluding locked & neutral colors
    avail_pool = [c for c in raw_palette_colors if c.upper() not in locked_hex_set and c.upper() != neutral_base]
    if not avail_pool:
        avail_pool = list(raw_palette_colors)

    # 4. Assign Focus role variables (max contrast against already-selected + white paper + highest OKLCH chroma)
    focus_vars = [cv for cv in ordered_vars if cv.var_id not in var_hex and cv.role == "focus"]
    white_arr = np.array([[1.0, 1.0, 1.0]], dtype=np.float64)
    for cv in focus_vars:
        if not avail_pool:
            avail_pool = expand_glasbey_in_hull(raw_palette_colors, len(raw_palette_colors) + len(focus_vars) + 2)
        cand_arr = np.stack([hex_to_srgb01(c) for c in avail_pool], axis=0)
        d_white = ciede2000_matrix(cand_arr, white_arr)[:, 0]
        existing_hexes = list(var_hex.values())
        if existing_hexes:
            ex_arr = np.stack([hex_to_srgb01(c) for c in existing_hexes], axis=0)
            d_ex = ciede2000_matrix(cand_arr, ex_arr).min(axis=1)
        else:
            d_ex = np.full(len(avail_pool), 35.0)
        chromas = np.array([hex_to_oklch(c)[1] for c in avail_pool], dtype=np.float64)
        scores = 0.45 * d_ex + 0.30 * d_white + 120.0 * chromas
        best_i = int(np.argmax(scores))
        chosen_f = avail_pool.pop(best_i)
        var_hex[cv.var_id] = chosen_f

    # 5. Assign Normal role variables
    normal_vars = [cv for cv in ordered_vars if cv.var_id not in var_hex]
    k_norm = len(normal_vars)
    n_avail = len(avail_pool)

    if pal.dynamic_generator == "chrom_alternating" and k_norm > 0:
        two_tone = raw_palette_colors[:2] if len(raw_palette_colors) >= 2 else ["#1E3A5F", "#64748B"]
        for i, cv in enumerate(normal_vars):
            var_hex[cv.var_id] = two_tone[i % 2]
    elif k_norm > 0:
        if k_norm <= n_avail:
            # K_total <= N: zero cross-panel duplicate colors in BOTH rules!
            if pal.order == "gradient" or pal.kind in ("sequential", "diverging"):
                cand_arr = np.stack([hex_to_srgb01(c) for c in avail_pool], axis=0)
                avoid_list = [hex_to_srgb01(h) for h in var_hex.values()]
                avoid_arr = np.stack(avoid_list, axis=0) if avoid_list else None
                sub_idxs = _select_maxmin_subset_indices(cand_arr, k_norm, avoid_arr=avoid_arr)
                picked = [avail_pool[i] for i in sub_idxs]
            else:
                # Respect palette designer's perceptual ordering first
                picked = avail_pool[:k_norm]
            for cv, hx in zip(normal_vars, picked):
                var_hex[cv.var_id] = hx
        else:
            # K_norm > n_avail
            # Check max variables appearing inside any single panel
            panel_counts: dict[str, int] = {}
            for cv in ordered_vars:
                if cv.role != "background":
                    for p in cv.panels:
                        panel_counts[p] = panel_counts.get(p, 0) + 1
            max_in_single_panel = max(panel_counts.values(), default=0)

            if collision_scope == "global_strict" or max_in_single_panel > len(raw_palette_colors):
                # Need genuinely more colors than palette size -> hierarchical rungs or Glasbey hull expansion
                base_for_exp = avail_pool if avail_pool else raw_palette_colors
                exp_map, gen_n = _expand_hierarchical_or_glasbey(base_for_exp, normal_vars)
                var_hex.update(exp_map)
                generated_count = gen_n
            else:
                # `panel_scoped` ("Same name, same color") where K_total > N, yet every single panel has <= N elements:
                # First exhaust ALL n_avail distinct colors before any cross-panel reuse!
                first_batch = normal_vars[:n_avail]
                if pal.order == "gradient" or pal.kind in ("sequential", "diverging"):
                    cand_arr = np.stack([hex_to_srgb01(c) for c in avail_pool], axis=0)
                    sub_idxs = _select_maxmin_subset_indices(cand_arr, n_avail)
                    ordered_avail = [avail_pool[i] for i in sub_idxs]
                else:
                    ordered_avail = list(avail_pool)

                color_owners: dict[str, list[_ColorVar]] = {}
                for cv, hx in zip(first_batch, ordered_avail):
                    var_hex[cv.var_id] = hx
                    color_owners.setdefault(hx, []).append(cv)

                reuse_pool = ordered_avail if ordered_avail else list(raw_palette_colors)
                for cv in normal_vars[n_avail:]:
                    # Forbidden: any color already used in `cv.panels`
                    co_panel_hexes = {
                        var_hex[other.var_id]
                        for other in ordered_vars
                        if other.var_id in var_hex and bool(other.panels & cv.panels)
                    }
                    co_arr = (
                        np.stack([hex_to_srgb01(c) for c in co_panel_hexes], axis=0)
                        if co_panel_hexes
                        else None
                    )
                    best_hx: str | None = None
                    best_score = -1e9
                    for cand_hx in reuse_pool:
                        if cand_hx in co_panel_hexes:
                            continue
                        owners = color_owners.get(cand_hx, [])
                        # Prefer reusing from semantically distant legend group (`category_group`) and least-reused color
                        diff_group = all(
                            (ow.category_group or "") != (cv.category_group or "") or not cv.category_group
                            for ow in owners
                        )
                        sem_bonus = 18.0 if diff_group else 0.0
                        reuse_pen = -6.0 * len(owners)
                        d_co = (
                            float(ciede2000_matrix(hex_to_srgb01(cand_hx)[None, :], co_arr).min())
                            if co_arr is not None
                            else 35.0
                        )
                        if d_co < 12.0:
                            d_co -= 30.0
                        sc = sem_bonus + reuse_pen + 0.8 * d_co
                        if sc > best_score:
                            best_score = sc
                            best_hx = cand_hx
                    if best_hx is None:
                        # Fallback: generate a new hull color so same-panel collision never occurs
                        extra = expand_glasbey_in_hull(list(var_hex.values()), len(var_hex) + 1)[-1]
                        best_hx = extra
                        generated_count += 1
                    var_hex[cv.var_id] = best_hx
                    color_owners.setdefault(best_hx, []).append(cv)

        # Local swap optimization (<= 200 iterations) across Normal variables
        fixed_vars = [cv for cv in ordered_vars if cv not in normal_vars and cv.var_id in var_hex]
        swap_candidates = list(dict.fromkeys(avail_pool + [var_hex[v.var_id] for v in normal_vars]))
        _optimize_local_swaps(
            normal_vars=normal_vars,
            var_hex=var_hex,
            candidate_pool=swap_candidates,
            fixed_vars=fixed_vars,
            collision_scope=collision_scope,
            max_iters=200,
        )

    # Propagate variable colors to `entity_hex` and `group_hex`
    entity_hex: dict[str, str] = {}
    group_hex: dict[str, str] = {}
    for cv in ordered_vars:
        hx = var_hex[cv.var_id]
        for eid in cv.entity_ids:
            entity_hex[eid] = hx
            for gid in entities[eid].member_group_ids:
                group_hex[gid] = hx

    # 6. Continuous scales (Section 8.2.7: homologous paired ramp first, then named partner, ΔE >= 15 vs Focus)
    focus_srgbs = [
        hex_to_srgb01(var_hex[cv.var_id])
        for cv in ordered_vars
        if cv.role == "focus" and cv.var_id in var_hex
    ]
    focus_arr = np.stack(focus_srgbs, axis=0) if focus_srgbs else None
    seq_fallbacks = [pal.partner_sequential, "cividis", "batlow", "oslo", "YlGnBu", "viridis", "lajolla"]
    div_fallbacks = [pal.partner_diverging, "vik", "PuOr", "BrBG", "RdBu", "roma", "bam"]

    scale_stops: dict[str, list[str]] = {}
    used_seq_partners: set[str] = set()
    for sid, cs in continuous_scales.items():
        if cs.locked:
            scale_stops[sid] = list(cs.current_stops_hex)
            continue
        is_div = cs.kind == "continuous_diverging"
        cand_specs: list[tuple[str, list[str]]] = []
        if is_div:
            if pal.kind == "diverging":
                cand_specs.append((pal.id, list(pal.colors)))
            elif pal.paired_diverging_stops:
                cand_specs.append((f"{pal.id}__paired_div", list(pal.paired_diverging_stops)))
            for cid in dict.fromkeys(div_fallbacks):
                cand_specs.append((cid, list(get_palette(cid).colors)))
        else:
            if pal.kind == "sequential":
                cand_specs.append((pal.id, list(pal.colors)))
            elif pal.paired_sequential_stops:
                cand_specs.append((f"{pal.id}__paired_seq", list(pal.paired_sequential_stops)))
            for cid in dict.fromkeys(seq_fallbacks):
                cand_specs.append((cid, list(get_palette(cid).colors)))

        chosen_stops: list[str] | None = None
        for tag, raw_stops in cand_specs:
            if not is_div and tag in used_seq_partners and len(continuous_scales) > 1:
                continue
            stops = apply_vibrancy(raw_stops, vib)
            if focus_arr is not None and len(stops) >= 2:
                # High-end stops (both dark and intense poles) should stay >= 15 ΔE away from Focus marks
                hi_poles = np.stack([hex_to_srgb01(stops[0]), hex_to_srgb01(stops[-1])], axis=0)
                min_d_focus = float(ciede2000_matrix(hi_poles, focus_arr).min())
                if min_d_focus < 15.0:
                    continue
            chosen_stops = stops
            if not is_div:
                used_seq_partners.add(tag)
            break

        if chosen_stops is None:
            if is_div and pal.paired_diverging_stops:
                chosen_stops = apply_vibrancy(list(pal.paired_diverging_stops), vib)
            elif not is_div and pal.paired_sequential_stops:
                chosen_stops = apply_vibrancy(list(pal.paired_sequential_stops), vib)
            else:
                fallback_pal = get_palette(pal.partner_diverging if is_div else pal.partner_sequential)
                chosen_stops = apply_vibrancy(list(fallback_pal.colors), vib)
        scale_stops[sid] = chosen_stops

    # 7. Inspector swatches: ALL palette colors (+ neutral + generated), sorted by min ΔE2000 vs co-panel elements
    full_swatch_pool = list(
        dict.fromkeys(raw_palette_colors + [neutral_base] + [entity_hex[eid] for eid in entity_hex])
    )
    entity_swatches: dict[str, list[str]] = {}
    inspector_swatches: dict[str, list[dict[str, Any]]] = {}

    for ent in ent_list:
        others = [
            (other.label, hex_to_srgb01(entity_hex[oid]))
            for oid, other in entities.items()
            if oid != ent.entity_id
            and other.label.strip().lower() != ent.label.strip().lower()
            and (collision_scope == "global_strict" or bool(set(ent.panels) & set(other.panels)))
        ]
        if not others:
            items = [{"hex": sw, "min_de": 99.0, "too_close_to": None} for sw in full_swatch_pool]
        else:
            o_labels = [x[0] for x in others]
            o_arr = np.stack([x[1] for x in others], axis=0)
            sw_arr = np.stack([hex_to_srgb01(sw) for sw in full_swatch_pool], axis=0)
            d_mat = ciede2000_matrix(sw_arr, o_arr)
            items = []
            for s_i, sw in enumerate(full_swatch_pool):
                min_idx = int(np.argmin(d_mat[s_i]))
                min_d = float(d_mat[s_i, min_idx])
                items.append(
                    {
                        "hex": sw,
                        "min_de": round(min_d, 1),
                        "too_close_to": o_labels[min_idx] if min_d < 10.5 else None,
                    }
                )
            items.sort(key=lambda it: float(it["min_de"]), reverse=True)
        inspector_swatches[ent.entity_id] = items
        entity_swatches[ent.entity_id] = [it["hex"] for it in items]

    diagnostics = evaluate_gates(
        entities=entities,
        entity_hex=entity_hex,
        collision_scope=collision_scope,
        palette_color_count=len(raw_palette_colors),
        required_color_count=sum(1 for cv in ordered_vars if cv.role != "background"),
        generated_count=generated_count,
    )
    return SolveResult(
        palette_id=pal.id,
        collision_scope=collision_scope,
        vibrancy=vib,
        entity_hex=entity_hex,
        group_hex=group_hex,
        scale_stops=scale_stops,
        entity_swatches=entity_swatches,
        inspector_swatches=inspector_swatches,
        diagnostics=diagnostics,
    )


def evaluate_gates(
    entities: dict[str, SemanticEntity],
    entity_hex: dict[str, str],
    collision_scope: CollisionScope,
    palette_color_count: int = 8,
    required_color_count: int = 0,
    generated_count: int = 0,
) -> dict[str, Any]:
    """Compute assignment diagnostics (Section 8.1 & 8.3)."""
    ent_list = list(entities.values())
    min_de_normal = 99.0
    min_de_protan = 99.0
    min_de_deutan = 99.0
    min_de_tritan = 99.0
    intra_panel_violations = 0
    cross_panel_shared_pairs: list[dict[str, str]] = []
    cb_problem_panels: list[str] = []

    if len(ent_list) >= 2:
        srgbs = np.stack([hex_to_srgb01(entity_hex[e.entity_id]) for e in ent_list], axis=0)
        m_norm = ciede2000_matrix(srgbs)
        m_prot = ciede2000_matrix(simulate_cvd(srgbs, "protan", 1.0))
        m_deut = ciede2000_matrix(simulate_cvd(srgbs, "deutan", 1.0))
        m_trit = ciede2000_matrix(simulate_cvd(srgbs, "tritan", 1.0))

        for i in range(len(ent_list)):
            for j in range(i + 1, len(ent_list)):
                ea, eb = ent_list[i], ent_list[j]
                if not ea.unlinked and not eb.unlinked and ea.label.strip().lower() == eb.label.strip().lower():
                    continue
                ra, rb = normalize_role(ea.tier), normalize_role(eb.tier)
                if ra == "background" and rb == "background":
                    continue
                shared_panels = sorted(set(ea.panels) & set(eb.panels))
                same_panel = bool(shared_panels)
                dn = float(m_norm[i, j])
                dp = float(m_prot[i, j])
                dd = float(m_deut[i, j])
                dt = float(m_trit[i, j])

                if same_panel or collision_scope == "global_strict":
                    min_de_normal = min(min_de_normal, dn)
                    min_de_protan = min(min_de_protan, dp)
                    min_de_deutan = min(min_de_deutan, dd)
                    min_de_tritan = min(min_de_tritan, dt)
                    if same_panel and dn < 12.0:
                        intra_panel_violations += 1
                    if same_panel and min(dp, dd) < 8.0:
                        for pid in shared_panels:
                            if pid not in cb_problem_panels:
                                cb_problem_panels.append(pid)
                elif not same_panel and dn < 4.0:
                    cross_panel_shared_pairs.append(
                        {
                            "hex_a": entity_hex[ea.entity_id],
                            "hex_b": entity_hex[eb.entity_id],
                            "label_a": ea.label,
                            "label_b": eb.label,
                            "panels_a": ",".join(ea.panels),
                            "panels_b": ",".join(eb.panels),
                        }
                    )

    white = np.ones(3, dtype=np.float64)
    min_apca_vs_white = 106.0
    for e in ent_list:
        if normalize_role(e.tier) != "background":
            lc = abs(apca_contrast(hex_to_srgb01(entity_hex[e.entity_id]), white))
            min_apca_vs_white = min(min_apca_vs_white, lc)

    de_norm_out = round(min_de_normal if min_de_normal < 98 else 32.0, 1)
    de_deut_out = round(min_de_deutan if min_de_deutan < 98 else 26.0, 1)
    de_prot_out = round(min_de_protan if min_de_protan < 98 else 26.0, 1)
    de_trit_out = round(min_de_tritan if min_de_tritan < 98 else 28.0, 1)

    return {
        "g1_separability_pass": bool(intra_panel_violations == 0 and de_norm_out >= 12.0),
        "colorblind_deutan_safe": bool(de_deut_out >= 8.0),
        "colorblind_protan_safe": bool(de_prot_out >= 8.0),
        "colorblind_problem_panels": cb_problem_panels,
        "min_de2000_normal": de_norm_out,
        "min_de2000_protan": de_prot_out,
        "min_de2000_deutan": de_deut_out,
        "min_de2000_tritan": de_trit_out,
        "g3_apca_min_lc": round(min_apca_vs_white if min_apca_vs_white < 105 else 62.0, 1),
        "g4_intra_panel_collisions": intra_panel_violations,
        "cross_panel_reused_count": len(cross_panel_shared_pairs),
        "cross_panel_reused_pairs": cross_panel_shared_pairs[:8],
        "palette_color_count": palette_color_count,
        "required_color_count": required_color_count,
        "generated_count": generated_count,
        "unique_hues_used": len({h.upper() for h in entity_hex.values()}),
    }
