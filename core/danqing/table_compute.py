"""Danqing Table Studio v3 — Deep Relational Column Graph & Raw-Column Statistical Compiler.

Implements:
1. Three-Layer Relational Column Inference:
   - Layer 1A: Token-Tree Flat-Header Spanner Factorization (`Donor_Median/Q1/Q3`, `Ctrl_1..6`, `Arm_log2FC/padj`).
   - Layer 1B: Expanded Statistical Pair/Triple Merges (`Mean+SD`, `Median+Q1+Q3` / `Median+IQR`, `OR+CI`,
     `Effect+SE`, `Count+Percent`) backed by mathematical order & ratio-conservation invariants.
   - Layer 2: Multi-Scope Significance Binding Graph (`sig_bindings`) with Spearman monotonicity tie-breaking.
   - Layer 3: Five-Tier Narrative Column Classification (`stub`, `context`, `summary`, `effect`, `evidence`).
2. "Laziest User" Raw-Column Statistical Compiler (`detect_smart_compute` + `compute_statistical_table`):
   - Mode `subject_table1`: Individual subject/patient records -> Publication Table 1 (normality-routed
     `Mean ± SD` [Welch's t / ANOVA] vs `Median [Q1–Q3]` [Mann–Whitney U / Kruskal–Wallis], multi-level
     indented `n (%)` [Fisher's exact / Pearson's chi-square], missing denominator audit, exact footnotes).
   - Mode `replicate_collapse`: Wide biological/experimental replicate columns -> Group `Mean ± SD` / `Median [IQR]`,
     `log2FC` / `Fold Change` / `Δ` with bidirectional inline micro-bar, `P value`, and Benjamini–Hochberg `FDR`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal

import numpy as np
from scipy import stats

_MISSING_SET = {
    "",
    "-",
    "—",
    "–",
    "?",
    "NA",
    "N/A",
    "na",
    "n/a",
    "nan",
    "NaN",
    "null",
    "NULL",
}

# Recognized statistical / comparison suffix tokens for flat-header prefix factorization (0% false positives)
_STAT_SUFFIX_EXACT = {
    "mean",
    "avg",
    "average",
    "sd",
    "std",
    "stdev",
    "se",
    "sem",
    "stderr",
    "lfcse",
    "median",
    "med",
    "iqr",
    "q1",
    "q3",
    "p25",
    "p75",
    "q25",
    "q75",
    "lower",
    "upper",
    "low",
    "high",
    "lcl",
    "ucl",
    "ci",
    "ci_low",
    "ci_high",
    "ci_lower",
    "ci_upper",
    "n",
    "count",
    "counts",
    "pct",
    "percent",
    "percentage",
    "prop",
    "proportion",
    "rate",
    "or",
    "hr",
    "rr",
    "fc",
    "log2fc",
    "logfc",
    "lfc",
    "diff",
    "delta",
    "change",
    "beta",
    "coef",
    "est",
    "estimate",
    "stat",
    "t",
    "z",
    "p",
    "q",
    "pval",
    "p_val",
    "pvalue",
    "p_value",
    "padj",
    "p_adj",
    "fdr",
    "qval",
    "q_value",
    "均值",
    "平均",
    "平均值",
    "标准差",
    "标准误",
    "中位数",
    "四分位距",
    "下限",
    "上限",
    "置信区间",
    "例数",
    "样本量",
    "人数",
    "占比",
    "百分比",
    "比值",
    "风险比",
    "效应",
    "变化",
    "倍数",
    "p值",
    "显著性",
}

# Prefixes that are themselves bare stat words (e.g. `CI_Lower`, `CI_Upper`) — NEVER create a cohort spanner for them
_BARE_STAT_PREFIXES = {
    "ci",
    "95%ci",
    "95ci",
    "iqr",
    "p",
    "q",
    "sd",
    "se",
    "std",
    "mean",
    "median",
    "or",
    "hr",
    "rr",
    "fc",
    "log2fc",
    "est",
    "adj",
    "adjusted",
    "raw",
}

_REPLICATE_SUFFIX_RE = re.compile(
    r"^(?:rep|r|s|sample|bio|tech)?0*([1-9]\d?)$", re.IGNORECASE
)
_PAREN_SUFFIX_RE = re.compile(r"^(.+?)\s*[(\[（【]\s*([^)\]）】]+)\s*[)\]）】]$")
_REP_HEADER_FULL_RE = re.compile(
    r"^([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff\s\-]*?)[_.\-\s]+(?:rep|r|sample)?0*([1-9]\d?)$",
    re.IGNORECASE,
)

_EFFECT_LEAF_RE = re.compile(
    r"(?:(?:^|[\s_\-·/(])(?:log2?fc|lfc|fold[\s_]?change|fc|or|hr|rr|odds|hazard|"
    r"beta|coef|diff(?:erence)?|delta|change|auc)(?:$|[\s_\-·/)])|^Δ|效应|倍数|变化|差值|比值|风险比)",
    re.IGNORECASE,
)
_RATIO_EFFECT_RE = re.compile(
    r"(?:(?:^|[\s_\-·/(])(?:or|hr|rr|odds|hazard|fold[\s_]?change|fc)(?:$|[\s_\-·/)])|比值|风险比)",
    re.IGNORECASE,
)
_CONTEXT_NON_HEAT_RE = re.compile(
    r"(?:^id$|_id$|^index$|^rank$|^age$|^age[_\s]|^basemean$|^aveexpr$|^n$|^total$|编号|序号|年龄|样本量)",
    re.IGNORECASE,
)

_GROUP_PRIMARY_HINTS = {
    "group",
    "groups",
    "arm",
    "cohort",
    "diagnosis",
    "diag",
    "treatment",
    "trt",
    "therapy",
    "status",
    "outcome",
    "condition",
    "disease",
    "class",
    "category",
    "subtype",
    "stage",
    "分组",
    "组别",
    "诊断",
    "治疗",
    "队列",
    "结局",
    "分期",
}
_GROUP_SECONDARY_HINTS = {
    "sex",
    "gender",
    "type",
    "grade",
    "性别",
    "类型",
    "分级",
}
_ID_COL_HINTS = {
    "id",
    "patient_id",
    "patientid",
    "sample_id",
    "sampleid",
    "subject_id",
    "subject",
    "patient",
    "record_id",
    "code",
    "rownames",
    "index",
    "编号",
    "患者编号",
    "样本编号",
    "序号",
}

_PRETTY_LEAF_MAP = {
    "mean": "Mean",
    "avg": "Mean",
    "sd": "SD",
    "std": "SD",
    "se": "SE",
    "sem": "SEM",
    "median": "Median",
    "med": "Median",
    "iqr": "IQR",
    "q1": "Q1",
    "q3": "Q3",
    "p25": "Q1",
    "p75": "Q3",
    "log2fc": "log2FC",
    "logfc": "logFC",
    "fc": "FC",
    "padj": "FDR",
    "p_adj": "FDR",
    "fdr": "FDR",
    "pval": "P value",
    "p_val": "P value",
    "pvalue": "P value",
    "p_value": "P value",
    "n": "n",
    "pct": "%",
    "percent": "%",
}

_UNIT_SUFFIX_MAP = [
    ("_mmhg", " (mmHg)"),
    ("_mg_dl", " (mg/dL)"),
    ("_mmol_l", " (mmol/L)"),
    ("_umol_l", " (umol/L)"),
    ("_g_l", " (g/L)"),
    ("_u_l", " (U/L)"),
    ("_ku_l", " (kU/L)"),
    ("_bpm", " (bpm)"),
    ("_mv", " (mV)"),
    ("_yr", " (yr)"),
    ("_years", " (yr)"),
    ("_mm", " (mm)"),
    ("_cm", " (cm)"),
    ("_kg", " (kg)"),
    ("_um2", " (um2)"),
    ("_um", " (um)"),
]


def _prettify_prefix(raw_prefix: str) -> str:
    cleaned = re.sub(r"[_]+", " ", raw_prefix).strip(" -·/")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _prettify_leaf(raw_leaf: str) -> str:
    low = raw_leaf.strip().lower()
    if low in _PRETTY_LEAF_MAP:
        return _PRETTY_LEAF_MAP[low]
    return raw_leaf.strip()


def prettify_variable_label(raw_name: str) -> str:
    """Convert snake_case clinical headers like `Resting_BP_mmHg` into `Resting BP (mmHg)`."""
    s = raw_name.strip()
    low = s.lower()
    unit_tail = ""
    for sfx, pretty_u in _UNIT_SUFFIX_MAP:
        if low.endswith(sfx) and len(s) > len(sfx):
            s = s[: -len(sfx)]
            unit_tail = pretty_u
            break
    s = s.replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return f"{s}{unit_tail}"


def split_flat_header_prefix_leaf(header: str) -> tuple[str, str] | None:
    """Factor a flat single-row header into `(cohort_prefix, stat_or_rep_leaf)` if valid."""
    h = header.strip()
    if not h or " · " in h:
        return None

    # Dedup suffix strip like `mean (2)` -> keep only real stat parens
    m_paren = _PAREN_SUFFIX_RE.match(h)
    if m_paren:
        cand_p, cand_s = m_paren.group(1).strip(), m_paren.group(2).strip()
        s_low = cand_s.lower()
        if s_low in _STAT_SUFFIX_EXACT and cand_p.lower() not in _BARE_STAT_PREFIXES:
            return _prettify_prefix(cand_p), _prettify_leaf(cand_s)

    # Try splitting from rightmost separator (`_`, ` `, `-`) checking 2-token stat suffixes like `ci_low`, `p_value`
    tokens = [t for t in re.split(r"[_\s\-]+", h) if t]
    if len(tokens) < 2:
        return None

    if len(tokens) >= 3:
        last2 = f"{tokens[-2]}_{tokens[-1]}".lower()
        prefix2 = "_".join(tokens[:-2])
        if last2 in _STAT_SUFFIX_EXACT and prefix2.lower() not in _BARE_STAT_PREFIXES:
            return _prettify_prefix(prefix2), _prettify_leaf(last2)

    last1 = tokens[-1]
    last1_low = last1.lower()
    prefix1 = "_".join(tokens[:-1])
    if prefix1.lower() in _BARE_STAT_PREFIXES:
        return None

    if last1_low in _STAT_SUFFIX_EXACT:
        return _prettify_prefix(prefix1), _prettify_leaf(last1)

    m_rep = _REPLICATE_SUFFIX_RE.match(last1)
    if m_rep and len(prefix1) >= 2:
        return _prettify_prefix(prefix1), last1

    return None


def infer_flat_header_spanners(
    headers: list[str],
    existing_spanners: list[dict[str, Any]],
    header_rows: tuple[int, int],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Infer cross-column spanners and clean leaf headers from single-row flat headers."""
    n_cols = len(headers)
    if header_rows[0] != header_rows[1] or existing_spanners:
        leaves = [h.split(" · ")[-1].strip() for h in headers]
        return list(existing_spanners), leaves

    parsed = [split_flat_header_prefix_leaf(h) if c >= 1 else None for c, h in enumerate(headers)]
    spanners: list[dict[str, Any]] = []
    leaves = list(headers)

    c = 1
    while c < n_cols:
        item = parsed[c]
        if item is None:
            c += 1
            continue
        pfx, _ = item
        j = c + 1
        while j < n_cols and parsed[j] is not None and parsed[j][0].lower() == pfx.lower():
            j += 1
        if j - c >= 2:
            # Verify distinct leaves inside the run
            run_leaves = [parsed[k][1] for k in range(c, j) if parsed[k] is not None]
            if len(set(x.lower() for x in run_leaves)) >= 2:
                spanners.append({"label": pfx, "source_cols": list(range(c, j))})
                for k in range(c, j):
                    assert parsed[k] is not None
                    leaves[k] = parsed[k][1]
        c = j

    return spanners, leaves


def infer_enhanced_merges(
    headers: list[str],
    leaf_headers: list[str],
    spanners: list[dict[str, Any]],
    parsed_matrix: list[list[Any]],
    col_stats: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int], set[int]]:
    """Detect 2-col and 3-col statistical merges using lexical rules + mathematical invariants.

    Returns `(merges, merged_member_cols, pct_promoted_cols)`.
    """
    n_cols = len(headers)
    col_to_span: dict[int, str] = {}
    for sp_idx, sp in enumerate(spanners):
        lbl = f"{sp_idx}:{sp['label']}"
        for sc in sp["source_cols"]:
            col_to_span[sc] = lbl

    merges: list[dict[str, Any]] = []
    merged_members: set[int] = set()
    pct_promoted_cols: set[int] = set()

    def _same_scope(cols: list[int]) -> bool:
        scopes = [col_to_span.get(k, "") for k in cols]
        if len(set(scopes)) == 1:
            return True
        # Allow `[est, ci_low, ci_high]` when none are inside conflicting named spanners
        if all(s == "" for s in scopes):
            return True
        return False

    idx = 0
    while idx < n_cols - 1:
        # 1. Three-column merges: Estimate+Lower+Upper (`ci`) or Median+Q1+Q3 (`iqr`)
        if idx + 2 < n_cols and _same_scope([idx, idx + 1, idx + 2]):
            l1 = leaf_headers[idx].lower()
            l2 = leaf_headers[idx + 1].lower()
            l3 = leaf_headers[idx + 2].lower()

            is_q1 = any(k in l2 for k in ("q1", "p25", "q25", "25%", "iqr_low"))
            is_q3 = any(k in l3 for k in ("q3", "p75", "q75", "75%", "iqr_high"))
            is_med = any(k in l1 for k in ("median", "med", "中位数"))

            if is_med and is_q1 and is_q3:
                merges.append({"source_cols": [idx, idx + 1, idx + 2], "pattern": "iqr"})
                merged_members.update((idx, idx + 1, idx + 2))
                idx += 3
                continue

            is_low = any(k in l2 for k in ("lower", "lcl", "ci_low", "2.5%", "下限")) or l2 in ("lo", "l")
            is_high = any(k in l3 for k in ("upper", "ucl", "ci_high", "97.5%", "上限")) or l3 in ("hi", "u")
            is_est = any(
                k in l1
                for k in ("or", "hr", "rr", "est", "beta", "coef", "diff", "mean", "fc", "log2fc", "比值", "效应", "均值")
            )
            if is_est and is_low and is_high:
                merges.append({"source_cols": [idx, idx + 1, idx + 2], "pattern": "ci"})
                merged_members.update((idx, idx + 1, idx + 2))
                idx += 3
                continue

            # Mathematical order-invariant check inside an explicit spanner: v[idx+1] <= v[idx] <= v[idx+2]
            if col_to_span.get(idx, "") != "":
                n_rows = len(parsed_matrix[idx]) if idx < len(parsed_matrix) else 0
                triples = []
                for r in range(n_rows):
                    v0 = parsed_matrix[idx][r].value
                    v1 = parsed_matrix[idx + 1][r].value
                    v2 = parsed_matrix[idx + 2][r].value
                    if v0 is not None and v1 is not None and v2 is not None:
                        triples.append((v0, v1, v2))
                if len(triples) >= 3:
                    in_order = sum(
                        1 for v0, v1, v2 in triples if (v1 - 1e-9) <= v0 <= (v2 + 1e-9)
                    )
                    strict_span = sum(1 for _, v1, v2 in triples if v2 > v1 + 1e-9)
                    has_bound_hint = any(
                        k in f"{l1} {l2} {l3}"
                        for k in ("q1", "q3", "25", "75", "iqr", "med", "ci", "low", "high", "lcl", "ucl")
                    )
                    if (
                        has_bound_hint
                        and in_order / len(triples) >= 0.95
                        and strict_span / len(triples) >= 0.5
                    ):
                        pat: Literal["iqr", "ci"] = (
                            "iqr"
                            if any(k in f"{l1} {l2} {l3}" for k in ("q1", "q3", "25", "75", "iqr", "med"))
                            else "ci"
                        )
                        merges.append({"source_cols": [idx, idx + 1, idx + 2], "pattern": pat})
                        merged_members.update((idx, idx + 1, idx + 2))
                        idx += 3
                        continue

        # 2. Two-column merges
        if _same_scope([idx, idx + 1]):
            l1 = leaf_headers[idx].lower()
            l2 = leaf_headers[idx + 1].lower()

            is_mean_sd = any(k in l1 for k in ("mean", "avg", "均值", "平均")) and (
                any(k in l2 for k in ("sd", "std", "stdev", "标准差")) or l2 in ("se", "sem", "标准误")
            )
            is_est_ci = any(
                k in l1
                for k in ("or", "hr", "rr", "beta", "coef", "hazard", "odds", "diff", "fc", "log2fc", "比值", "风险比")
            ) and ("ci" in l2 or "置信区间" in l2)
            is_med_iqr = any(k in l1 for k in ("median", "med", "中位数")) and (
                "iqr" in l2 or "四分位距" in l2
            )
            is_eff_se = _EFFECT_LEAF_RE.search(l1) is not None and (
                l2 in ("se", "sem", "lfcse", "stderr", "标准误") or "std.err" in l2
            )

            if is_mean_sd or is_est_ci:
                merges.append({"source_cols": [idx, idx + 1], "pattern": "paren"})
                merged_members.update((idx, idx + 1))
                idx += 2
                continue

            if is_med_iqr:
                merges.append({"source_cols": [idx, idx + 1], "pattern": "iqr"})
                merged_members.update((idx, idx + 1))
                idx += 2
                continue

            if is_eff_se:
                merges.append({"source_cols": [idx, idx + 1], "pattern": "plusminus"})
                merged_members.update((idx, idx + 1))
                idx += 2
                continue

            # Count (n) + Percentage (%) pair (lexical OR mathematical ratio-conservation invariant)
            st0 = col_stats[idx]
            st1 = col_stats[idx + 1]
            if (
                st0["is_all_int"]
                and st0["min_val"] is not None
                and st0["min_val"] >= 0
                and st1["numeric_ratio"] >= 0.75
                and st1["min_val"] is not None
                and st1["max_val"] is not None
                and 0.0 <= st1["min_val"]
                and st1["max_val"] <= 100.0 + 1e-6
            ):
                lex_n = l1 in ("n", "count", "counts", "events", "cases", "例数", "人数", "样本量")
                lex_pct = (
                    l2 in ("%", "pct", "percent", "percentage", "prop", "rate", "占比", "百分比")
                    or "%" in l2
                    or st1["detected_unit"] == "%"
                )
                # Ratio conservation check: n_i / pct_i ~ constant N/100
                ratios: list[float] = []
                for r in range(len(parsed_matrix[idx])):
                    v_n = parsed_matrix[idx][r].value
                    v_p = parsed_matrix[idx + 1][r].value
                    if v_n is not None and v_p is not None and v_n > 0 and v_p > 0.5:
                        ratios.append(v_n / v_p)
                ratio_conserved = False
                if len(ratios) >= 3:
                    arr_r = np.array(ratios, dtype=float)
                    mean_r = float(np.mean(arr_r))
                    if mean_r > 0 and float(np.std(arr_r) / mean_r) < 0.06:
                        ratio_conserved = True

                if (lex_n and lex_pct) or (ratio_conserved and (lex_n or lex_pct)):
                    merges.append({"source_cols": [idx, idx + 1], "pattern": "paren"})
                    merged_members.update((idx, idx + 1))
                    pct_promoted_cols.add(idx + 1)
                    idx += 2
                    continue

        idx += 1

    return merges, merged_members, pct_promoted_cols


def infer_sig_bindings(
    headers: list[str],
    leaf_headers: list[str],
    roles: dict[str, str],
    merges: list[dict[str, Any]],
    spanners: list[dict[str, Any]],
    parsed_matrix: list[list[Any]],
) -> list[dict[str, Any]]:
    """Bind each significance (`P`/`FDR`) column to its true target protagonist column(s)."""
    n_cols = len(headers)
    sig_cols = [c for c in range(n_cols) if roles.get(str(c)) == "sig"]
    if not sig_cols:
        return []

    col_to_span_idx: dict[int, int] = {}
    for s_idx, sp in enumerate(spanners):
        for sc in sp["source_cols"]:
            col_to_span_idx[sc] = s_idx

    # Map secondary merge members to their lead column
    lead_of_col: dict[int, int] = {c: c for c in range(n_cols)}
    secondary_cols: set[int] = set()
    for mg in merges:
        lead = mg["source_cols"][0]
        for sec in mg["source_cols"][1:]:
            lead_of_col[sec] = lead
            secondary_cols.add(sec)

    bindings: list[dict[str, Any]] = []
    prev_sig_col = 0

    for s_col in sig_cols:
        span_idx = col_to_span_idx.get(s_col)
        scope_label = ""
        if span_idx is not None:
            sp = spanners[span_idx]
            scope_label = str(sp["label"])
            cand_cols = [
                c
                for c in sp["source_cols"]
                if c != s_col
                and c not in secondary_cols
                and roles.get(str(c)) not in ("sig", "part")
            ]
        else:
            # Check if candidate columns share a common leading cohort token with `headers[s_col]`
            s_tok0 = re.split(r"[_\s\-]+", headers[s_col].strip())[0]
            cand_cols = [
                c
                for c in range(max(1, prev_sig_col + 1), s_col)
                if c not in secondary_cols and roles.get(str(c)) not in ("sig", "part")
            ]
            shared_lead = [
                c
                for c in cand_cols
                if re.split(r"[_\s\-]+", headers[c].strip())[0].lower() == s_tok0.lower()
                and s_tok0.lower() not in _BARE_STAT_PREFIXES
            ]
            if shared_lead:
                cand_cols = shared_lead
                scope_label = _prettify_prefix(s_tok0)
            else:
                scope_label = leaf_headers[s_col]

        # Identify explicit effect protagonist columns inside candidate scope
        effect_cands: list[int] = []
        for c in cand_cols:
            lbl_combo = f"{headers[c]} {leaf_headers[c]}"
            mg_for_c = next((m for m in merges if m["source_cols"][0] == c), None)
            if _EFFECT_LEAF_RE.search(lbl_combo) is not None or (
                mg_for_c is not None and mg_for_c["pattern"] == "ci"
            ):
                effect_cands.append(c)

        target_cols: list[int]
        if len(effect_cands) == 1:
            target_cols = [effect_cands[0]]
        elif len(effect_cands) >= 2:
            # Break ties via Spearman rank monotonicity between |effect - null| and -log10(P)
            best_c = effect_cands[-1]
            best_rho = -2.0
            for ec in effect_cands:
                null_v = 1.0 if _RATIO_EFFECT_RE.search(f"{headers[ec]} {leaf_headers[ec]}") else 0.0
                xs: list[float] = []
                ys: list[float] = []
                for r in range(len(parsed_matrix[s_col])):
                    ev = parsed_matrix[ec][r].value
                    pv = parsed_matrix[s_col][r].value
                    if ev is not None and pv is not None and pv >= 0:
                        xs.append(abs(ev - null_v))
                        ys.append(-math.log10(max(pv, 1e-300)))
                if len(xs) >= 4 and len(set(xs)) >= 2 and len(set(ys)) >= 2:
                    rho_res = stats.spearmanr(xs, ys)
                    rho = float(rho_res.statistic) if not math.isnan(float(rho_res.statistic)) else 0.0
                    if rho > best_rho:
                        best_rho = rho
                        best_c = ec
            target_cols = [best_c]
        else:
            # Descriptive baseline comparison (e.g. Table 1 without separate effect column): keep sig col itself
            target_cols = [s_col]

        bindings.append(
            {
                "source_col": s_col,
                "target_cols": target_cols,
                "label": scope_label,
            }
        )
        prev_sig_col = s_col

    return bindings


def classify_narrative_roles(
    headers: list[str],
    leaf_headers: list[str],
    col_stats: list[dict[str, Any]],
    part_by: int | None,
    merged_member_cols: set[int],
    sig_Substr_hints: tuple[str, ...],
    sig_exact_hints: set[str],
    count_exact_hints: set[str],
) -> dict[str, str]:
    """Assign 5-tier narrative roles (`part`, `sig`, `count`, `bar`, `heat`, `normal`)."""
    n_cols = len(headers)
    roles: dict[str, str] = {}
    has_merges_or_sig = len(merged_member_cols) > 0

    raw_sig_flags: list[bool] = []
    for c in range(n_cols):
        st = col_stats[c]
        leaf_low = leaf_headers[c].lower()
        min_v = st["min_val"]
        max_v = st["max_val"]
        in_unit = min_v is not None and max_v is not None and -1e-9 <= min_v and max_v <= 1.0 + 1e-9
        is_sig = (
            any(h in leaf_low for h in sig_Substr_hints)
            or (leaf_low in sig_exact_hints and st["numeric_ratio"] >= 0.6 and in_unit)
        ) and st["numeric_ratio"] >= 0.5
        raw_sig_flags.append(is_sig)
        if is_sig:
            has_merges_or_sig = True

    for c in range(n_cols):
        st = col_stats[c]
        leaf = leaf_headers[c]
        leaf_low = leaf.lower()
        full_low = headers[c].lower()

        if part_by == c:
            role = "part"
        elif raw_sig_flags[c]:
            role = "sig"
        elif leaf_low in count_exact_hints and st["is_all_int"]:
            role = "count"
        elif st["seq_ratio"] >= 0.5:
            role = "bar"
        elif c in merged_member_cols:
            role = "normal"
        elif (
            has_merges_or_sig
            and st["numeric_ratio"] >= 0.65
            and _EFFECT_LEAF_RE.search(f"{headers[c]} {leaf}") is not None
            and not _RATIO_EFFECT_RE.search(leaf)  # log2FC/Delta/Beta get 0-centered inline bar automatically!
        ):
            role = "bar"
        elif st["numeric_ratio"] >= 0.65 and not _CONTEXT_NON_HEAT_RE.search(full_low) and not _CONTEXT_NON_HEAT_RE.search(leaf_low):
            # In mixed clinical/contrast tables (has_merges_or_sig), keep non-effect numeric columns calm `normal`
            # unless it's a pure unmerged numeric matrix!
            if len(merged_member_cols) > 0:
                role = "normal"
            else:
                role = "heat"
        else:
            role = "normal"

        roles[str(c)] = role
        st["role"] = role

    return roles


def detect_smart_compute(
    headers: list[str],
    body_rows: list[list[str]],
    col_stats: list[dict[str, Any]],
    roles: dict[str, str],
    pivot_suggestion: dict[str, Any] | None,
    sparkline_runs: list[dict[str, Any]],
    merges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Detect whether the input grid is unaggregated raw columns suitable for auto-computation."""
    n_cols = len(headers)
    n_rows = len(body_rows)
    if n_cols < 3 or n_rows < 3:
        return None
    if pivot_suggestion is not None or sparkline_runs or merges:
        return None
    # If the table already contains a P-value / FDR column, it is already a statistical summary table!
    if any(r == "sig" for r in roles.values()):
        return None

    # 1. Check Mode B: Wide Biological/Experimental Replicate Matrix (`Benign_1..6`, `Malignant_1..6`)
    if col_stats[0]["numeric_ratio"] < 0.25 and n_cols >= 5:
        rep_groups: dict[str, list[int]] = {}
        group_order: list[str] = []
        numeric_non_stub = [c for c in range(1, n_cols) if col_stats[c]["numeric_ratio"] >= 0.7]
        matched_rep_cols = 0
        for c in range(1, n_cols):
            if col_stats[c]["numeric_ratio"] < 0.7:
                continue
            m = _REP_HEADER_FULL_RE.match(headers[c].strip())
            if m:
                g_name = _prettify_prefix(m.group(1))
                if g_name.lower() not in _BARE_STAT_PREFIXES:
                    if g_name not in rep_groups:
                        rep_groups[g_name] = []
                        group_order.append(g_name)
                    rep_groups[g_name].append(c)
                    matched_rep_cols += 1

        valid_groups = [
            {"name": g, "cols": rep_groups[g], "n": len(rep_groups[g])}
            for g in group_order
            if len(rep_groups[g]) >= 2
        ]
        total_grouped_cols = sum(g["n"] for g in valid_groups)
        if (
            2 <= len(valid_groups) <= 6
            and len(numeric_non_stub) >= 4
            and total_grouped_cols >= max(4, int(math.ceil(0.8 * len(numeric_non_stub))))
        ):
            equal_reps = len({g["n"] for g in valid_groups}) == 1 and len(valid_groups) == 2
            all_pos = all(
                (col_stats[c]["min_val"] is not None and col_stats[c]["min_val"] > 0)
                for g in valid_groups
                for c in g["cols"]
            )
            return {
                "kind": "replicate_collapse",
                "n_features": n_rows,
                "feature_col": 0,
                "groups": valid_groups,
                "can_pair": equal_reps,
                "default_effect": "log2fc" if (len(valid_groups) == 2 and all_pos) else "diff",
            }

    # 2. Check Mode A: Individual Subject / Patient Raw Records -> Auto Table 1
    if n_rows < 12:
        return None

    # Identify unique ID columns to exclude
    excluded_id_cols: list[int] = []
    for c in range(n_cols):
        vals = [r[c].strip() for r in body_rows if r[c].strip() not in _MISSING_SET]
        if not vals:
            continue
        uniq_ratio = len(set(vals)) / len(vals)
        h_low = headers[c].strip().lower()
        is_id_name = h_low in _ID_COL_HINTS or h_low.endswith("_id")
        is_seq_int = (
            c == 0
            and col_stats[c]["is_all_int"]
            and uniq_ratio >= 0.98
            and h_low in ("", "col 1", "id", "index", "row")
        )
        is_unique_code = c == 0 and col_stats[c]["numeric_ratio"] < 0.2 and uniq_ratio >= 0.95
        if (uniq_ratio >= 0.95 and is_id_name) or is_seq_int or is_unique_code:
            excluded_id_cols.append(c)

    # Identify candidate group columns (2..6 levels, each >= 2 observations)
    candidate_group_cols: list[dict[str, Any]] = []
    for c in range(n_cols):
        if c in excluded_id_cols:
            continue
        vals = [r[c].strip() for r in body_rows if r[c].strip() not in _MISSING_SET]
        if len(vals) < int(0.85 * n_rows):
            continue
        counts: dict[str, int] = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        k = len(counts)
        if not (2 <= k <= 6):
            continue
        if min(counts.values()) < 2:
            continue
        h_low = headers[c].strip().lower()
        is_text = col_stats[c]["numeric_ratio"] < 0.2
        is_coded_group = col_stats[c]["is_all_int"] and (
            h_low in _GROUP_PRIMARY_HINTS or h_low in _GROUP_SECONDARY_HINTS
        )
        if not (is_text or is_coded_group):
            continue

        score = 0
        if h_low in _GROUP_PRIMARY_HINTS or any(p in h_low for p in ("group", "diag", "arm", "cohort", "treat", "分组", "诊断")):
            score += 30
        elif h_low in _GROUP_SECONDARY_HINTS:
            score += 12
        if is_text:
            score += 5
        if c <= 2:
            score += 4
        if k == 2:
            score += 3

        candidate_group_cols.append(
            {
                "col": c,
                "name": headers[c],
                "groups": counts,
                "_score": score,
            }
        )

    if not candidate_group_cols:
        return None

    candidate_group_cols.sort(key=lambda x: (-int(x["_score"]), int(x["col"])))
    best_group_col = int(candidate_group_cols[0]["col"])
    for item in candidate_group_cols:
        item.pop("_score", None)

    # Count remaining continuous vs categorical covariates
    n_cont = 0
    n_cat = 0
    for c in range(n_cols):
        if c in excluded_id_cols or c == best_group_col:
            continue
        vals = [r[c].strip() for r in body_rows if r[c].strip() not in _MISSING_SET]
        if len(vals) < 3:
            continue
        uniq_k = len(set(vals))
        st = col_stats[c]
        if st["numeric_ratio"] >= 0.75 and not (st["is_all_int"] and uniq_k <= 5):
            n_cont += 1
        elif 2 <= uniq_k <= 10:
            n_cat += 1

    if n_cont + n_cat < 2:
        return None

    return {
        "kind": "subject_table1",
        "n_subjects": n_rows,
        "default_group_col": best_group_col,
        "candidate_group_cols": candidate_group_cols,
        "excluded_id_cols": excluded_id_cols,
        "n_continuous": n_cont,
        "n_categorical": n_cat,
    }


def _safe_float(raw: str, decimal_comma: bool = False) -> float | None:
    s = raw.strip()
    if s in _MISSING_SET:
        return None
    s = s.replace("\u2212", "-").rstrip("%").strip()
    if decimal_comma and "," in s and "." not in s:
        s = s.replace(",", ".")
    elif not decimal_comma and "," in s:
        s = s.replace(",", "")
    try:
        v = float(s)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except ValueError:
        return None


def _is_skewed_distribution(arr: np.ndarray) -> bool:
    if arr.size < 8:
        return False
    std_v = float(np.std(arr, ddof=1))
    if std_v <= 1e-12:
        return False
    skew_v = abs(float(stats.skew(arr, bias=False)))
    if skew_v > 1.0:
        return True
    if skew_v > 0.75 and arr.size <= 500:
        try:
            _, p_shap = stats.shapiro(arr)
            if float(p_shap) < 0.005:
                return True
        except Exception:
            pass
    return False


def _choose_auto_decimals(arr: np.ndarray) -> int:
    if arr.size == 0:
        return 1
    if np.all(np.abs(arr - np.round(arr)) < 1e-9):
        span = float(np.max(arr) - np.min(arr))
        return 1 if span >= 10 else 2
    med_abs = float(np.median(np.abs(arr[arr != 0]))) if np.any(arr != 0) else 1.0
    if med_abs >= 100:
        return 1
    if med_abs >= 1:
        return 1
    if med_abs >= 0.1:
        return 2
    return 3


def compute_statistical_table(
    raw_grid: list[list[str]],
    *,
    header_rows: tuple[int, int],
    body_range: tuple[int, int],
    decimal_comma: bool,
    source_meta: dict[str, Any],
    mode: Literal["subject_table1", "replicate_collapse"],
    options: dict[str, Any] | None = None,
    lang: Literal["en", "zh"] = "zh",
) -> dict[str, Any]:
    """Deterministically compute a publication-ready statistical table + StructureLayer + StyleLayer."""
    opts = options or {}
    h_idx = header_rows[1]
    headers = [c.strip() or f"Col {i + 1}" for i, c in enumerate(raw_grid[h_idx])]
    body_rows = [
        raw_grid[r]
        for r in range(body_range[0], min(body_range[1] + 1, len(raw_grid)))
        if any(c.strip() != "" for c in raw_grid[r])
    ]
    n_cols = len(headers)
    is_zh = lang == "zh"

    if mode == "subject_table1":
        return _compute_subject_table1(
            headers=headers,
            body_rows=body_rows,
            n_cols=n_cols,
            decimal_comma=decimal_comma,
            source_meta=source_meta,
            opts=opts,
            is_zh=is_zh,
        )
    return _compute_replicate_collapse(
        headers=headers,
        body_rows=body_rows,
        n_cols=n_cols,
        decimal_comma=decimal_comma,
        source_meta=source_meta,
        opts=opts,
        is_zh=is_zh,
    )


def _compute_subject_table1(
    *,
    headers: list[str],
    body_rows: list[list[str]],
    n_cols: int,
    decimal_comma: bool,
    source_meta: dict[str, Any],
    opts: dict[str, Any],
    is_zh: bool,
) -> dict[str, Any]:
    if "group_col" in opts:
        raw_group_col = opts.get("group_col")
        group_col: int | None = (
            int(raw_group_col)
            if raw_group_col is not None and str(raw_group_col) != "none" and int(raw_group_col) >= 0
            else None
        )
    else:
        # Auto-select top candidate grouping column when unspecified
        best_col: int | None = None
        best_sc = -1
        for c in range(n_cols):
            vals = [r[c].strip() for r in body_rows if r[c].strip() not in _MISSING_SET]
            if len(vals) < int(0.85 * len(body_rows)):
                continue
            uniq = set(vals)
            if not (2 <= len(uniq) <= 6):
                continue
            h_low = headers[c].strip().lower()
            num_hits = sum(1 for v in vals if _safe_float(v, decimal_comma) is not None)
            is_text = (num_hits / len(vals)) < 0.2
            if not is_text and h_low not in _GROUP_PRIMARY_HINTS:
                continue
            sc = (30 if (h_low in _GROUP_PRIMARY_HINTS or any(p in h_low for p in ("group", "diag", "arm", "cohort", "treat", "分组", "诊断"))) else 5) + (4 if c <= 2 else 0)
            if sc > best_sc:
                best_sc = sc
                best_col = c
        group_col = best_col
    continuous_mode: str = str(opts.get("continuous_mode") or "auto")
    include_overall: bool = bool(opts.get("include_overall", True))
    adjust_p: bool = bool(opts.get("adjust_p", False))

    # Filter rows with non-missing group if grouped
    valid_subject_rows: list[list[str]] = []
    group_order: list[str] = []
    rows_by_group: dict[str, list[list[str]]] = {}

    if group_col is not None and 0 <= group_col < n_cols:
        for r in body_rows:
            gv = r[group_col].strip()
            if gv in _MISSING_SET:
                continue
            valid_subject_rows.append(r)
            if gv not in rows_by_group:
                rows_by_group[gv] = []
                group_order.append(gv)
            rows_by_group[gv].append(r)
    else:
        group_col = None
        valid_subject_rows = list(body_rows)

    n_total = len(valid_subject_rows)
    has_groups = group_col is not None and len(group_order) >= 2

    # Detect ID columns to skip
    excluded_ids: set[int] = set()
    for c in range(n_cols):
        if c == group_col:
            continue
        vals = [r[c].strip() for r in valid_subject_rows if r[c].strip() not in _MISSING_SET]
        if not vals:
            excluded_ids.add(c)
            continue
        uniq_ratio = len(set(vals)) / len(vals)
        h_low = headers[c].strip().lower()
        is_id_name = h_low in _ID_COL_HINTS or h_low.endswith("_id")
        parsed_c = [_safe_float(v, decimal_comma) for v in vals]
        num_ratio = sum(1 for x in parsed_c if x is not None) / len(vals)
        if (uniq_ratio >= 0.95 and is_id_name) or (c == 0 and num_ratio < 0.2 and uniq_ratio >= 0.95):
            excluded_ids.add(c)

    # Build output columns:
    # Col 0: Characteristic
    # If include_overall or not has_groups: Overall_Center, Overall_Spread
    # For each group g: Group_g_Center, Group_g_Spread
    # If has_groups: P value (+ optional FDR)
    arm_defs: list[tuple[str, list[list[str]]]] = []
    if include_overall or not has_groups:
        ov_lbl = f"Overall (N={n_total})" if not is_zh else f"总计 (N={n_total})"
        arm_defs.append((ov_lbl, valid_subject_rows))
    if has_groups:
        for g in group_order:
            g_rows = rows_by_group[g]
            arm_defs.append((f"{g} (n={len(g_rows)})", g_rows))

    out_headers: list[str] = ["Characteristic" if not is_zh else "特征变量"]
    spanners_spec: list[dict[str, Any]] = []
    merges_spec: list[dict[str, Any]] = []

    for a_idx, (arm_label, _) in enumerate(arm_defs):
        c_lead = len(out_headers)
        aux_lbl = f"{arm_label} · 离散/占比" if is_zh else f"{arm_label} · SD/IQR/%"
        out_headers.append(arm_label)
        out_headers.append(aux_lbl)
        merges_spec.append(
            {
                "id": f"mg_t1_{a_idx}",
                "columnIds": [f"c{c_lead}", f"c{c_lead + 1}"],
                "pattern": "plusminus",
                "mergedLabel": arm_label,
            }
        )

    p_col_idx: int | None = None
    fdr_col_idx: int | None = None
    if has_groups:
        p_col_idx = len(out_headers)
        out_headers.append("P value")
        if adjust_p:
            fdr_col_idx = len(out_headers)
            out_headers.append("FDR")

    # Track used statistical tests for exact footnote generation
    used_tests: list[str] = []  # ordered subset of ["parametric", "nonparametric", "chi2", "fisher"]

    def _mark_test(kind: str) -> str:
        if kind not in used_tests:
            used_tests.append(kind)
        idx_sym = used_tests.index(kind)
        return chr(ord("a") + idx_sym)

    out_body: list[list[str]] = []
    row_indents: dict[int, int] = {}
    p_row_records: list[tuple[int, float]] = []  # (body_row_idx, raw_p)

    for c in range(n_cols):
        if c == group_col or c in excluded_ids:
            continue
        non_miss_vals = [r[c].strip() for r in valid_subject_rows if r[c].strip() not in _MISSING_SET]
        if len(non_miss_vals) < 3:
            continue

        parsed_all = [_safe_float(v, decimal_comma) for v in non_miss_vals]
        num_hits = [x for x in parsed_all if x is not None]
        num_ratio = len(num_hits) / len(non_miss_vals)
        is_all_int = len(num_hits) > 0 and all(abs(x - round(x)) < 1e-9 for x in num_hits)
        uniq_levels = len(set(non_miss_vals))

        is_continuous = num_ratio >= 0.75 and not (is_all_int and uniq_levels <= 5 and n_total >= 15)
        pretty_name = prettify_variable_label(headers[c])
        n_valid_var = len(non_miss_vals)
        miss_note = f" (n={n_valid_var})" if n_valid_var < n_total else ""

        if is_continuous:
            arr_all = np.array(num_hits, dtype=float)
            dec = _choose_auto_decimals(arr_all)
            use_nonparam = (
                True
                if continuous_mode == "nonparametric"
                else False
                if continuous_mode == "parametric"
                else _is_skewed_distribution(arr_all)
            )

            p_val: float | None = None
            if has_groups:
                grp_arrays = []
                for g in group_order:
                    g_nums = [
                        x
                        for x in (_safe_float(r[c], decimal_comma) for r in rows_by_group[g])
                        if x is not None
                    ]
                    if len(g_nums) >= 1:
                        grp_arrays.append(np.array(g_nums, dtype=float))
                if len(grp_arrays) >= 2 and all(a.size >= 2 for a in grp_arrays):
                    try:
                        if use_nonparam:
                            if len(grp_arrays) == 2:
                                _, pv = stats.mannwhitneyu(grp_arrays[0], grp_arrays[1], alternative="two-sided")
                            else:
                                _, pv = stats.kruskal(*grp_arrays)
                        else:
                            if len(grp_arrays) == 2:
                                _, pv = stats.ttest_ind(grp_arrays[0], grp_arrays[1], equal_var=False)
                            else:
                                _, pv = stats.f_oneway(*grp_arrays)
                        if not math.isnan(float(pv)):
                            p_val = float(pv)
                    except Exception:
                        p_val = None

            sup_sym = _mark_test("nonparametric" if use_nonparam else "parametric")
            row_cells = [f"{pretty_name}{miss_note}^{sup_sym}"]
            for _, arm_rows in arm_defs:
                a_nums = np.array(
                    [
                        x
                        for x in (_safe_float(r[c], decimal_comma) for r in arm_rows)
                        if x is not None
                    ],
                    dtype=float,
                )
                if a_nums.size == 0:
                    row_cells.extend(["", ""])
                elif use_nonparam:
                    q25, med, q75 = [float(x) for x in np.percentile(a_nums, [25, 50, 75])]
                    row_cells.extend([f"{med:.{dec}f}", f"[{q25:.{dec}f}–{q75:.{dec}f}]"])
                else:
                    mean_v = float(np.mean(a_nums))
                    sd_v = float(np.std(a_nums, ddof=1)) if a_nums.size >= 2 else 0.0
                    row_cells.extend([f"{mean_v:.{dec}f}", f"{sd_v:.{dec}f}"])

            if p_col_idx is not None:
                row_cells.append(f"{p_val:.6e}" if p_val is not None else "")
            if fdr_col_idx is not None:
                row_cells.append("")

            r_idx = len(out_body)
            out_body.append(row_cells)
            if p_val is not None:
                p_row_records.append((r_idx, p_val))

        elif 2 <= uniq_levels <= 10:
            # Categorical variable: parent header row + indented level sub-rows
            # Order levels by overall descending frequency (standard clinical Table 1)
            overall_counts: dict[str, int] = {}
            for v in non_miss_vals:
                overall_counts[v] = overall_counts.get(v, 0) + 1
            ordered_levels = sorted(overall_counts.keys(), key=lambda lv: (-overall_counts[lv], lv))

            p_val = None
            test_kind = "chi2"
            if has_groups:
                ct = np.array(
                    [
                        [
                            sum(1 for r in rows_by_group[g] if r[c].strip() == lv)
                            for g in group_order
                        ]
                        for lv in ordered_levels
                    ],
                    dtype=float,
                )
                # Keep rows/cols with positive totals
                ct = ct[ct.sum(axis=1) > 0]
                if ct.shape[0] >= 2 and ct.shape[1] >= 2 and ct.sum() > 0:
                    row_sums = ct.sum(axis=1, keepdims=True)
                    col_sums = ct.sum(axis=0, keepdims=True)
                    expected = (row_sums @ col_sums) / float(ct.sum())
                    try:
                        if ct.shape == (2, 2) and float(np.min(expected)) < 5.0:
                            test_kind = "fisher"
                            _, pv = stats.fisher_exact(ct.astype(int), alternative="two-sided")
                        else:
                            test_kind = "chi2"
                            _, pv, _, _ = stats.chi2_contingency(ct, correction=False)
                        if not math.isnan(float(pv)):
                            p_val = float(pv)
                    except Exception:
                        p_val = None

            sup_sym = _mark_test(test_kind)
            parent_row = [f"{pretty_name}{miss_note}, n (%)^{sup_sym}"]
            for _ in arm_defs:
                parent_row.extend(["", ""])
            if p_col_idx is not None:
                parent_row.append(f"{p_val:.6e}" if p_val is not None else "")
            if fdr_col_idx is not None:
                parent_row.append("")

            p_row_idx = len(out_body)
            out_body.append(parent_row)
            if p_val is not None:
                p_row_records.append((p_row_idx, p_val))

            for lv in ordered_levels:
                sub_row = [lv]
                for _, arm_rows in arm_defs:
                    denom = sum(1 for r in arm_rows if r[c].strip() not in _MISSING_SET)
                    cnt = sum(1 for r in arm_rows if r[c].strip() == lv)
                    pct = (100.0 * cnt / denom) if denom > 0 else 0.0
                    sub_row.extend([str(cnt), f"{pct:.1f}%"])
                if p_col_idx is not None:
                    sub_row.append("")
                if fdr_col_idx is not None:
                    sub_row.append("")
                sub_idx = len(out_body)
                row_indents[sub_idx] = 1
                out_body.append(sub_row)

    # Populate BH-FDR if requested
    if fdr_col_idx is not None and p_row_records:
        raw_ps = np.array([pv for _, pv in p_row_records], dtype=float)
        fdrs = stats.false_discovery_control(raw_ps, method="bh")
        for (r_idx, _), qv in zip(p_row_records, fdrs):
            out_body[r_idx][fdr_col_idx] = f"{float(qv):.6e}"

    # Build bilingual methodological footnotes
    k_arms = len(group_order)
    footnotes_spec: list[dict[str, Any]] = []
    for idx_sym, kind in enumerate(used_tests):
        sym = chr(ord("a") + idx_sym)
        if not has_groups:
            if kind == "parametric":
                txt = "均值 ± 标准差。" if is_zh else "Mean ± SD."
            elif kind == "nonparametric":
                txt = "中位数 [Q1–Q3]。" if is_zh else "Median [Q1–Q3]."
            else:
                txt = "例数（百分比）。" if is_zh else "n (%)."
        elif kind == "parametric":
            txt = (
                (
                    "均值 ± 标准差；组间比较采用双侧 Welch t 检验。"
                    if k_arms <= 2
                    else "均值 ± 标准差；多组比较采用单因素方差分析（ANOVA）。"
                )
                if is_zh
                else (
                    "Mean ± SD; two-sided Welch's t-test."
                    if k_arms <= 2
                    else "Mean ± SD; one-way ANOVA across groups."
                )
            )
        elif kind == "nonparametric":
            txt = (
                (
                    "中位数 [Q1–Q3]；偏态连续变量采用双侧 Mann–Whitney U 检验。"
                    if k_arms <= 2
                    else "中位数 [Q1–Q3]；偏态连续变量采用 Kruskal–Wallis 检验。"
                )
                if is_zh
                else (
                    "Median [Q1–Q3]; two-sided Mann–Whitney U test for skewed distributions."
                    if k_arms <= 2
                    else "Median [Q1–Q3]; Kruskal–Wallis test across groups."
                )
            )
        elif kind == "fisher":
            txt = (
                "例数（百分比）；理论频数 < 5 采用双侧 Fisher 精确检验。"
                if is_zh
                else "n (%); two-sided Fisher's exact test (expected cell count < 5)."
            )
        else:
            txt = (
                "例数（百分比）；采用 Pearson 卡方检验。"
                if is_zh
                else "n (%); Pearson's chi-square test."
            )
        footnotes_spec.append(
            {
                "id": f"fn_auto_{sym}",
                "symbol": sym,
                "text": txt,
                "anchorColumnIds": [],
            }
        )

    grp_title_part = (
        (f" stratified by {headers[group_col]}" if not is_zh else f"（按 {headers[group_col]} 分组）")
        if group_col is not None
        else ""
    )
    title_str = (
        f"Baseline characteristics{grp_title_part}"
        if not is_zh
        else f"研究队列基线特征统计表{grp_title_part}"
    )

    sig_src_id = (
        f"c{fdr_col_idx}"
        if fdr_col_idx is not None
        else (f"c{p_col_idx}" if p_col_idx is not None else None)
    )
    sig_bindings_spec = (
        [{"id": "sb_0", "sourceId": sig_src_id, "targetIds": [sig_src_id], "label": "P value"}]
        if sig_src_id
        else []
    )

    return _package_computed_table(
        out_headers=out_headers,
        out_body=out_body,
        source_meta=source_meta,
        table_number="Table 1",
        title=title_str,
        spanners_spec=spanners_spec,
        merges_spec=merges_spec,
        row_indents=row_indents,
        footnotes_spec=footnotes_spec,
        sig_source_id=sig_src_id,
        sig_target_ids=[sig_src_id] if sig_src_id else [],
        sig_bindings_spec=sig_bindings_spec,
        bar_col_ids=set(),
        sig_col_indices={c for c in (p_col_idx, fdr_col_idx) if c is not None},
        active_compute={
            "mode": "subject_table1",
            "groupCol": group_col,
            "continuousMode": continuous_mode,
            "includeOverall": include_overall,
            "adjustP": adjust_p,
        },
    )


def _compute_replicate_collapse(
    *,
    headers: list[str],
    body_rows: list[list[str]],
    n_cols: int,
    decimal_comma: bool,
    source_meta: dict[str, Any],
    opts: dict[str, Any],
    is_zh: bool,
) -> dict[str, Any]:
    summary_mode: str = str(opts.get("summary_mode") or "parametric")
    effect_metric: str = str(opts.get("effect_metric") or "auto")
    paired: bool = bool(opts.get("paired", False))
    use_nonparam = summary_mode == "nonparametric"

    # Re-detect replicate groups from headers
    rep_groups: dict[str, list[int]] = {}
    group_order: list[str] = []
    for c in range(1, n_cols):
        m = _REP_HEADER_FULL_RE.match(headers[c].strip())
        if m:
            g_name = _prettify_prefix(m.group(1))
            if g_name.lower() not in _BARE_STAT_PREFIXES:
                if g_name not in rep_groups:
                    rep_groups[g_name] = []
                    group_order.append(g_name)
                rep_groups[g_name].append(c)

    groups = [(g, rep_groups[g]) for g in group_order if len(rep_groups[g]) >= 2]
    k_groups = len(groups)
    can_pair = k_groups == 2 and len(groups[0][1]) == len(groups[1][1])
    use_paired = paired and can_pair

    # Check if all values are strictly positive for log2FC / FC
    all_positive = True
    for r in body_rows:
        for _, cols in groups:
            for c in cols:
                v = _safe_float(r[c], decimal_comma)
                if v is not None and v <= 0:
                    all_positive = False
                    break

    if effect_metric == "auto":
        resolved_effect = "log2fc" if (k_groups == 2 and all_positive) else "diff"
    elif effect_metric in ("log2fc", "fc") and not all_positive:
        resolved_effect = "diff"
    else:
        resolved_effect = effect_metric

    feat_header = prettify_variable_label(headers[0]) or ("Feature" if not is_zh else "指标")
    out_headers: list[str] = [feat_header]
    merges_spec: list[dict[str, Any]] = []
    spanners_spec: list[dict[str, Any]] = []

    for g_idx, (g_name, g_cols) in enumerate(groups):
        c_lead = len(out_headers)
        arm_lbl = f"{g_name} (n={len(g_cols)})"
        c_lbl = (
            f"{arm_lbl} · {'中位数' if use_nonparam else '均值'}"
            if is_zh
            else f"{arm_lbl} · {'Median' if use_nonparam else 'Mean'}"
        )
        s_lbl = f"{arm_lbl} · {'IQR' if use_nonparam else 'SD'}"
        out_headers.append(c_lbl)
        out_headers.append(s_lbl)
        merges_spec.append(
            {
                "id": f"mg_rep_{g_idx}",
                "columnIds": [f"c{c_lead}", f"c{c_lead + 1}"],
                "pattern": "plusminus",
                "mergedLabel": arm_lbl,
            }
        )

    eff_col_idx = len(out_headers)
    if k_groups == 2:
        g0_name, g1_name = groups[0][0], groups[1][0]
        if resolved_effect == "log2fc":
            eff_header = "log2FC"
        elif resolved_effect == "fc":
            eff_header = "Fold Change"
        else:
            eff_header = f"Δ ({g1_name} − {g0_name})"
        contrast_span_label = f"{g1_name} vs {g0_name}"
    else:
        eff_header = "Δ Range"
        contrast_span_label = "Group Comparison" if not is_zh else "多组差异检验"

    p_col_idx = eff_col_idx + 1
    fdr_col_idx = eff_col_idx + 2
    out_headers.extend([eff_header, "P value", "FDR"])

    spanners_spec.append(
        {
            "id": "sp_rep_contrast",
            "label": contrast_span_label,
            "columnIds": [f"c{eff_col_idx}", f"c{p_col_idx}", f"c{fdr_col_idx}"],
        }
    )

    out_body: list[list[str]] = []
    p_records: list[tuple[int, float]] = []

    for r in body_rows:
        feat_name = r[0].strip()
        if not feat_name:
            continue
        grp_arrays: list[np.ndarray] = []
        all_row_nums: list[float] = []
        for _, g_cols in groups:
            vals = [
                x for x in (_safe_float(r[c], decimal_comma) for c in g_cols) if x is not None
            ]
            arr = np.array(vals, dtype=float)
            grp_arrays.append(arr)
            all_row_nums.extend(vals)

        dec = _choose_auto_decimals(np.array(all_row_nums, dtype=float))
        row_cells: list[str] = [feat_name]
        centers: list[float | None] = []

        for arr in grp_arrays:
            if arr.size == 0:
                row_cells.extend(["", ""])
                centers.append(None)
            elif use_nonparam:
                q25, med, q75 = [float(x) for x in np.percentile(arr, [25, 50, 75])]
                row_cells.extend([f"{med:.{dec}f}", f"[{q25:.{dec}f}–{q75:.{dec}f}]"])
                centers.append(med)
            else:
                mean_v = float(np.mean(arr))
                sd_v = float(np.std(arr, ddof=1)) if arr.size >= 2 else 0.0
                row_cells.extend([f"{mean_v:.{dec}f}", f"{sd_v:.{dec}f}"])
                centers.append(mean_v)

        # Effect value
        eff_val: float | None = None
        if k_groups == 2 and centers[0] is not None and centers[1] is not None:
            c0_v, c1_v = centers[0], centers[1]
            if resolved_effect == "log2fc" and c0_v > 0 and c1_v > 0:
                eff_val = math.log2(c1_v / c0_v)
            elif resolved_effect == "fc" and c0_v != 0:
                eff_val = c1_v / c0_v
            else:
                eff_val = c1_v - c0_v
        elif k_groups >= 3:
            valid_c = [x for x in centers if x is not None]
            if len(valid_c) >= 2:
                eff_val = max(valid_c) - min(valid_c)

        eff_str = (
            f"{eff_val:.3f}"
            if (eff_val is not None and resolved_effect in ("log2fc", "fc"))
            else (f"{eff_val:.{dec}f}" if eff_val is not None else "")
        )

        # Hypothesis test
        p_val: float | None = None
        if len(grp_arrays) >= 2 and all(a.size >= 2 for a in grp_arrays):
            try:
                if k_groups == 2:
                    a0, a1 = grp_arrays[0], grp_arrays[1]
                    if use_paired:
                        if use_nonparam:
                            _, pv = stats.wilcoxon(a1, a0)
                        else:
                            _, pv = stats.ttest_rel(a1, a0)
                    else:
                        if use_nonparam:
                            _, pv = stats.mannwhitneyu(a1, a0, alternative="two-sided")
                        else:
                            _, pv = stats.ttest_ind(a1, a0, equal_var=False)
                else:
                    if use_nonparam:
                        _, pv = stats.kruskal(*grp_arrays)
                    else:
                        _, pv = stats.f_oneway(*grp_arrays)
                if not math.isnan(float(pv)):
                    p_val = float(pv)
            except Exception:
                p_val = None

        row_cells.extend(
            [
                eff_str,
                f"{p_val:.6e}" if p_val is not None else "",
                "",
            ]
        )
        r_idx = len(out_body)
        out_body.append(row_cells)
        if p_val is not None:
            p_records.append((r_idx, p_val))

    if p_records:
        raw_ps = np.array([pv for _, pv in p_records], dtype=float)
        fdrs = stats.false_discovery_control(raw_ps, method="bh")
        for (r_idx, _), qv in zip(p_records, fdrs):
            out_body[r_idx][fdr_col_idx] = f"{float(qv):.6e}"

    # Footnotes
    if is_zh:
        sum_desc = "中位数 [Q1–Q3]" if use_nonparam else "均值 ± 标准差"
        if k_groups == 2:
            test_desc = (
                ("配对 Wilcoxon 符号秩检验" if use_nonparam else "双侧配对 t 检验")
                if use_paired
                else ("双侧 Mann–Whitney U 检验" if use_nonparam else "双侧 Welch t 检验")
            )
        else:
            test_desc = "Kruskal–Wallis 检验" if use_nonparam else "单因素方差分析（ANOVA）"
        fn_text = f"各组数据表示为{sum_desc}；组间比较采用{test_desc}，并经 Benjamini–Hochberg 方法校正多重假设检验（FDR）。"
    else:
        sum_desc = "median [Q1–Q3]" if use_nonparam else "mean ± SD"
        if k_groups == 2:
            test_desc = (
                ("paired Wilcoxon signed-rank test" if use_nonparam else "two-sided paired t-test")
                if use_paired
                else ("two-sided Mann–Whitney U test" if use_nonparam else "two-sided Welch's t-test")
            )
        else:
            test_desc = "Kruskal–Wallis test" if use_nonparam else "one-way ANOVA"
        fn_text = f"Values are {sum_desc} across replicates; {test_desc} with Benjamini–Hochberg FDR adjustment."

    footnotes_spec = [
        {
            "id": "fn_auto_rep",
            "symbol": "a",
            "text": fn_text,
            "anchorColumnIds": [f"c{fdr_col_idx}"],
        }
    ]

    title_str = (
        f"Differential replicate analysis ({contrast_span_label})"
        if not is_zh
        else f"重复样本组间差异统计表（{contrast_span_label}）"
    )

    eff_cid = f"c{eff_col_idx}"
    fdr_cid = f"c{fdr_col_idx}"
    bar_cols = {eff_cid} if resolved_effect != "fc" else set()

    return _package_computed_table(
        out_headers=out_headers,
        out_body=out_body,
        source_meta=source_meta,
        table_number="Table 1",
        title=title_str,
        spanners_spec=spanners_spec,
        merges_spec=merges_spec,
        row_indents={},
        footnotes_spec=footnotes_spec,
        sig_source_id=fdr_cid,
        sig_target_ids=[eff_cid],
        sig_bindings_spec=[
            {
                "id": "sb_rep_0",
                "sourceId": fdr_cid,
                "targetIds": [eff_cid],
                "label": contrast_span_label,
            }
        ],
        bar_col_ids=bar_cols,
        sig_col_indices={p_col_idx, fdr_col_idx},
        active_compute={
            "mode": "replicate_collapse",
            "summaryMode": summary_mode,
            "effectMetric": resolved_effect,
            "paired": use_paired,
        },
    )


def _package_computed_table(
    *,
    out_headers: list[str],
    out_body: list[list[str]],
    source_meta: dict[str, Any],
    table_number: str,
    title: str,
    spanners_spec: list[dict[str, Any]],
    merges_spec: list[dict[str, Any]],
    row_indents: dict[int, int],
    footnotes_spec: list[dict[str, Any]],
    sig_source_id: str | None,
    sig_target_ids: list[str],
    sig_bindings_spec: list[dict[str, Any]],
    bar_col_ids: set[str],
    sig_col_indices: set[int],
    active_compute: dict[str, Any],
) -> dict[str, Any]:
    grid = [out_headers, *out_body]
    sha_hex = hashlib.sha256(json.dumps(grid, ensure_ascii=False).encode("utf-8")).hexdigest()
    n_cols = len(out_headers)
    n_body = max(1, len(out_body))

    roles: dict[str, str] = {}
    col_stats: list[dict[str, Any]] = []
    columns_spec: list[dict[str, Any]] = []

    for c in range(n_cols):
        cid = f"c{c}"
        vals = [_safe_float(r[c], False) for r in out_body]
        nums = [x for x in vals if x is not None]
        pct_hits = sum(1 for r in out_body if r[c].strip().endswith("%"))
        det_unit = "%" if (len(nums) >= 1 and pct_hits / max(1, len(nums)) >= 0.5) else ""
        is_int = len(nums) > 0 and all(abs(x - round(x)) < 1e-9 for x in nums)
        role = "sig" if c in sig_col_indices else ("bar" if cid in bar_col_ids else "normal")
        roles[str(c)] = role

        col_stats.append(
            {
                "col": c,
                "name": out_headers[c],
                "numeric_ratio": round(len(nums) / n_body, 4),
                "min_val": min(nums) if nums else None,
                "max_val": max(nums) if nums else None,
                "detected_unit": det_unit,
                "seq_ratio": 0.0,
                "is_all_int": is_int,
                "role": role,
            }
        )
        columns_spec.append(
            {
                "id": cid,
                "source": {"kind": "grid", "col": c},
                "label": out_headers[c],
                "hidden": False,
                "role": role,
                "visual": "bar" if cid in bar_col_ids else "auto",
                "precision": "auto",
                "unit": det_unit,
            }
        )

    snapshot = {
        "snapshot_id": f"tbl_comp_{sha_hex[:12]}",
        "source": {
            "filename": str(source_meta.get("filename") or "computed_table.csv"),
            "sheet": str(source_meta.get("sheet") or "Computed"),
            "sheets": [str(source_meta.get("sheet") or "Computed")],
            "kind": source_meta.get("kind") or "csv",
            "sha256": sha_hex,
        },
        "grid": grid,
        "cell_merges": [],
        "warnings": [],
        "sheets_meta": [{"name": str(source_meta.get("sheet") or "Computed"), "empty": False}],
        "column_stats": col_stats,
        "suggestions": {
            "header_rows": [0, 0],
            "body_range": [1, len(grid) - 1],
            "title_candidate": title,
            "footnote_candidates": [],
            "spanners": [
                {
                    "label": sp["label"],
                    "source_cols": [int(cid[1:]) for cid in sp["columnIds"]],
                }
                for sp in spanners_spec
            ],
            "roles": roles,
            "merges": [
                {
                    "source_cols": [int(cid[1:]) for cid in mg["columnIds"]],
                    "pattern": mg["pattern"],
                }
                for mg in merges_spec
            ],
            "part_by": None,
            "sparkline_runs": [],
            "pivot": None,
            "decimal_comma": False,
            "resolved_headers": out_headers,
            "leaf_headers": out_headers,
            "sig_bindings": [],
            "smart_compute": None,
        },
    }

    structure = {
        "stage": "tidied",
        "headerRows": [0, 0],
        "bodyRange": [1, len(grid) - 1],
        "pivot": None,
        "columns": columns_spec,
        "spanners": spanners_spec,
        "merges": merges_spec,
        "derived": [],
        "partBy": None,
        "partOrder": "appearance",
        "sort": [],
        "cellOverrides": {},
        "rowIndents": {str(k): v for k, v in row_indents.items()},
        "missingToken": "—",
        "tableNumber": table_number,
        "title": title,
        "subtitle": "",
        "footnotes": footnotes_spec,
        "sig": {
            "sourceId": sig_source_id,
            "targetIds": sig_target_ids,
            "bindings": sig_bindings_spec,
            "pStyle": "nejm",
            "stars": True,
        },
        "dismissedSuggestions": [],
        "excludeSummaryRows": True,
        "activeCompute": active_compute,
    }

    style = {
        "preset": "cns_three_line",
        "paletteId": "cns_slate",
        "heatScope": "per_column",
        "heatCenter": "auto",
        "heatLog": False,
        "heatDomainClip": "minmax",
        "emphasis": "bold_star_mono",
        "rowRhythm": "none" if row_indents else "zebra",
        "tabularNums": True,
    }

    return {
        "snapshot": snapshot,
        "structure": structure,
        "style": style,
    }
