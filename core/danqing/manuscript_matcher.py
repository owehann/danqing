"""Manuscript-level comfort & journal-tone palette recommender (Gemini + Deterministic Perceptual Ranker).

Helps researchers stop wasting hours tweaking hex codes by matching finished figures or whole
manuscript figure sets to comfortable, harmonious, reviewer-safe palettes in one step.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .color_science import hex_to_oklch
from .palettes import PaletteDefinition, get_palette, list_palettes

PRESET_BRIEFS: dict[str, str] = {
    "cns_clean": "Nature / Cell / Science multidisciplinary manuscript, crisp white background, low visual fatigue, balanced medium chroma",
    "clinical": "NEJM / Lancet / JAMA clinical cohort & translational medicine manuscript, calm authoritative contrast, grayscale & colorblind safe",
    "omics": "Single-cell / spatial transcriptomics / multi-omics atlas with clear cluster separation and harmonious continuous partner ramps",
    "museum": "Warm museum & Song-porcelain mineral aesthetic, gentle eye-soothing scholarly palette with high perceptual distinction",
}

CURATED_ANCHORS: dict[str, tuple[str, ...]] = {
    "cns_clean": (
        "cns_harmony_lineage",
        "npg",
        "petroff8",
        "okabe_ito",
        "tol_muted",
        "aaas",
    ),
    "clinical": (
        "lancet",
        "nejm",
        "jama",
        "jco",
        "bmj",
        "ibm_cbs",
    ),
    "omics": (
        "cns_harmony_lineage",
        "scanpy_vega10",
        "petroff10",
        "polychrome_36",
        "scanpy_zeileis28",
        "kelly22",
    ),
    "museum": (
        "east_ru_celadon",
        "met_hiroshige",
        "east_blue_green_landscape",
        "met_hokusai2",
        "sanzo_wada_121",
        "pnw_bay",
    ),
}

KEYWORD_BOOSTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"nature|npg|顶刊|自然", re.I), ("npg", "cns_harmony_lineage", "petroff8")),
    (re.compile(r"science|aaas|科学", re.I), ("aaas", "petroff6", "okabe_ito")),
    (re.compile(r"cell|cancer\s*discovery|肿瘤|免疫|immun", re.I), ("cns_harmony_lineage", "npg", "lancet")),
    (re.compile(r"nejm|新英格兰|临床|clinical|trial|cohort|队列|生存|kaplan", re.I), ("nejm", "lancet", "jama", "jco")),
    (re.compile(r"lancet|柳叶刀", re.I), ("lancet", "bmj", "nejm")),
    (re.compile(r"jama", re.I), ("jama", "jco", "uchicago")),
    (re.compile(r"gwas|manhattan|genetics|遗传|基因组", re.I), ("locuszoom", "chrom_alternating", "okabe_ito")),
    (re.compile(r"single[-\s]?cell|scrna|umap|tsne|visium|spatial|单细胞|空间|多簇|组学|omics", re.I), ("cns_harmony_lineage", "scanpy_vega10", "polychrome_36", "scanpy_zeileis28")),
    (re.compile(r"volcano|deg|火山|差异表达", re.I), ("volcano_deg3", "npg", "tol_vibrant")),
    (re.compile(r"宋|汝|青瓷|东方|古风|国风|和田三造|sanzo|wada|mineral|celadon|porcelain|eastern|dunhuang|唐卡", re.I), ("east_ru_celadon", "east_blue_green_landscape", "east_ming_blue_white", "sanzo_wada_121")),
    (re.compile(r"museum|art|馆藏|名画|莫奈|浮世绘|hiroshige|hokusai", re.I), ("met_hiroshige", "met_hokusai2", "east_hokusai_red_fuji", "moma_picasso")),
    (re.compile(r"柔和|护眼|舒适|清淡|低饱和|muted|soft|calm|gentle|pastel", re.I), ("tol_muted", "east_ru_celadon", "cns_harmony_lineage", "seaborn_muted", "carto_pastel")),
    (re.compile(r"色盲|无障碍|accessible|colorblind|cvd|deutan", re.I), ("okabe_ito", "petroff8", "tol_bright", "ibm_cbs", "carto_safe")),
    (re.compile(r"热图|连续|发散|heatmap|continuous|gradient", re.I), ("batlow", "vik", "roma", "lipari", "cns_sdi_amber")),
)


def _visual_comfort_score(pal: PaletteDefinition) -> float:
    """Measure eye-comfort on white paper: penalize harsh neon chroma or ultra-dark muddy fills."""
    if not pal.colors:
        return 0.0
    sample = pal.colors[: min(8, len(pal.colors))]
    l_vals: list[float] = []
    c_vals: list[float] = []
    for hx in sample:
        l_ch, c_ch, _ = hex_to_oklch(hx)
        l_vals.append(l_ch)
        c_vals.append(c_ch)
    mean_c = sum(c_vals) / len(c_vals)
    mean_l = sum(l_vals) / len(l_vals)
    # Ideal scholarly comfort band: OKLCH L in [0.48, 0.72], C in [0.075, 0.155]
    c_penalty = max(0.0, mean_c - 0.165) * 45.0 + max(0.0, 0.055 - mean_c) * 20.0
    l_penalty = max(0.0, 0.42 - mean_l) * 35.0 + max(0.0, mean_l - 0.80) * 35.0
    return max(0.0, 18.0 - c_penalty - l_penalty)


def _default_reason(pal: PaletteDefinition, required_k: int, has_continuous: bool) -> dict[str, str]:
    cb_zh = "通过色盲区分检验，" if pal.qc.get("colorblind_safe") else ""
    cb_en = "Color-blind safe; " if pal.qc.get("colorblind_safe") else ""
    if pal.collection == "eastern":
        return {
            "zh": f"{cb_zh}源自馆藏矿物釉彩，明度温润克制，长时间审阅不刺眼（覆盖 {required_k} 组数据）。",
            "en": f"{cb_en}drawn from museum mineral glazes with calm, low-fatigue contrast across {required_k} groups.",
        }
    if pal.collection == "journal":
        return {
            "zh": f"{cb_zh}契合主流期刊白底排版语境，层次利落，免去反复微调色号。",
            "en": f"{cb_en}tailored for white-page journal layouts with clean hierarchy and zero hex-tweaking.",
        }
    if pal.collection == "accessible":
        return {
            "zh": f"{cb_zh}国际学术无障碍标准色板，审稿人色觉友好且黑白打印清晰。",
            "en": f"{cb_en}benchmark accessible palette built for universal reviewer legibility and print clarity.",
        }
    if pal.collection == "many":
        return {
            "zh": f"专为 {required_k} 组以上高维多簇图表设计，相邻类别易于分辨。",
            "en": f"Engineered for high-cardinality ({required_k}+) clusters with reliable visual separation.",
        }
    if pal.collection == "continuous" or has_continuous:
        return {
            "zh": f"{cb_zh}感知均匀连续色阶，亮暗过渡平滑自然，忠实呈现数值梯度。",
            "en": f"{cb_en}perceptually uniform ramp that preserves smooth data gradients without distortion.",
        }
    return {
        "zh": f"{cb_zh}馆藏级色彩比例均衡耐看，适合整篇论文多图统一设色。",
        "en": f"{cb_en}balanced museum-grade harmony suited for consistent multi-figure manuscripts.",
    }


def _rank_deterministic(
    *,
    required_k: int,
    has_continuous: bool,
    has_diverging: bool,
    element_labels: list[str],
    preset: str | None,
    brief: str,
) -> list[tuple[PaletteDefinition, float]]:
    all_pals = list_palettes()
    combined_text = f"{brief} {' '.join(element_labels[:24])}".strip()

    anchor_ids: list[str] = []
    if preset and preset in CURATED_ANCHORS:
        anchor_ids.extend(CURATED_ANCHORS[preset])
    for rx, pids in KEYWORD_BOOSTS:
        if rx.search(combined_text):
            for pid in pids:
                if pid not in anchor_ids:
                    anchor_ids.append(pid)

    only_continuous = required_k <= 1 and has_continuous
    scored: list[tuple[PaletteDefinition, float]] = []

    for pal in all_pals:
        if only_continuous:
            if pal.kind == "qualitative":
                continue
            if has_diverging and pal.kind != "diverging":
                continue
        else:
            if pal.kind != "qualitative":
                continue
            max_c = int(pal.qc.get("max_colors", len(pal.colors)))
            if not pal.dynamic_generator and max_c < required_k:
                continue

        score = _visual_comfort_score(pal)
        if pal.qc.get("colorblind_safe"):
            score += 14.0
        if pal.qc.get("print_friendly"):
            score += 6.0
        min_de = float(pal.qc.get("min_de2000_first6") or 18.0)
        score += min(12.0, min_de * 0.35)

        if required_k >= 11 and (pal.collection == "many" or len(pal.colors) >= required_k):
            score += 12.0
        elif required_k <= 8 and pal.collection in ("journal", "accessible", "eastern", "museum"):
            score += 6.0

        if pal.id in anchor_ids:
            rank_pos = anchor_ids.index(pal.id)
            score += max(16.0, 38.0 - rank_pos * 3.5)

        scored.append((pal, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _try_gemini_selection(
    *,
    api_key: str,
    candidates: list[PaletteDefinition],
    required_k: int,
    has_continuous: bool,
    element_labels: list[str],
    brief: str,
) -> list[dict[str, Any]] | None:
    """Ask Gemini 2.5 Flash to pick the 3 most comfortable, fitting palettes from verified candidates."""
    if not api_key or not candidates:
        return None

    shortlist = [
        {
            "id": p.id,
            "name_en": p.name_en,
            "name_zh": p.name_zh,
            "collection": p.collection,
            "colors": list(p.colors[:8]),
            "colorblind_safe": bool(p.qc.get("colorblind_safe")),
        }
        for p in candidates[:24]
    ]

    prompt = (
        "You are an expert scientific visualization art director for Nature, Science, Cell, NEJM, and Lancet.\n"
        "Select the 3 most visually comfortable, harmonious, publication-appropriate palettes from CANDIDATES "
        "for the researcher's manuscript so they do not waste time tweaking hex codes.\n"
        f"- Manuscript / style brief: {brief or 'General peer-reviewed scientific manuscript, clean and comfortable'}\n"
        f"- Discrete groups required: {required_k}\n"
        f"- Has continuous heatmap/scale: {has_continuous}\n"
        f"- Figure group labels (context only): {element_labels[:16]}\n"
        f"- CANDIDATES (JSON): {json.dumps(shortlist, ensure_ascii=False)}\n\n"
        "Return ONLY valid JSON matching this exact schema (no exclamation marks, no emojis, concise 1-sentence reasons):\n"
        '{"recommendations":[{"palette_id":"string","reason_en":"string","reason_zh":"string"}]}'
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 600,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = (
            payload.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        parsed = json.loads(text)
        recs = parsed.get("recommendations", [])
        valid_ids = {p.id for p in candidates}
        cleaned: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in recs:
            pid = str(item.get("palette_id", "")).strip()
            if pid in valid_ids and pid not in seen:
                seen.add(pid)
                pal = get_palette(pid)
                r_en = str(item.get("reason_en", "")).replace("!", ".").replace("！", "。").strip()
                r_zh = str(item.get("reason_zh", "")).replace("!", "。").replace("！", "。").strip()
                fallback = _default_reason(pal, required_k, has_continuous)
                cleaned.append(
                    {
                        "palette_id": pid,
                        "reason": {
                            "en": r_en or fallback["en"],
                            "zh": r_zh or fallback["zh"],
                        },
                    }
                )
            if len(cleaned) >= 3:
                break
        return cleaned if len(cleaned) >= 2 else None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError):
        return None


def match_manuscript_palettes(
    *,
    required_k: int = 4,
    has_continuous: bool = False,
    has_diverging: bool = False,
    element_labels: list[str] | None = None,
    preset: str | None = None,
    brief: str = "",
    gemini_api_key: str | None = None,
) -> dict[str, Any]:
    """Return top 3 comfortable manuscript palette matches using Gemini (if configured) or deterministic ranker."""
    labels = element_labels or []
    preset_key = (preset or "").strip().lower() or None
    effective_brief = brief.strip()
    if preset_key in PRESET_BRIEFS:
        effective_brief = (
            f"{PRESET_BRIEFS[preset_key]}. {effective_brief}".strip()
            if effective_brief
            else PRESET_BRIEFS[preset_key]
        )

    ranked = _rank_deterministic(
        required_k=max(1, int(required_k)),
        has_continuous=has_continuous,
        has_diverging=has_diverging,
        element_labels=labels,
        preset=preset_key,
        brief=effective_brief,
    )
    candidates = [p for p, _ in ranked]

    resolved_key = (gemini_api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
    gemini_picks = _try_gemini_selection(
        api_key=resolved_key,
        candidates=candidates,
        required_k=max(1, int(required_k)),
        has_continuous=has_continuous,
        element_labels=labels,
        brief=effective_brief,
    )

    if gemini_picks:
        return {
            "engine": "gemini",
            "recommendations": gemini_picks,
        }

    # Ensure diversity across top 3 deterministic picks while preserving top match quality
    chosen: list[PaletteDefinition] = []
    used_collections: set[str] = set()
    for pal in candidates:
        if len(chosen) == 0 or pal.collection not in used_collections or len(candidates) <= 4:
            chosen.append(pal)
            used_collections.add(pal.collection)
        if len(chosen) >= 3:
            break
    for pal in candidates:
        if len(chosen) >= 3:
            break
        if pal not in chosen:
            chosen.append(pal)

    return {
        "engine": "perceptual",
        "recommendations": [
            {
                "palette_id": p.id,
                "reason": _default_reason(p, max(1, int(required_k)), has_continuous),
            }
            for p in chosen[:3]
        ],
    }
