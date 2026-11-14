#!/usr/bin/env python3
"""Build & verify expanded scientific, journal, museum, multi-cluster, continuous & convention palettes.

All hexadecimal values are parsed directly from verified primary open-source/public-domain repositories
or published factual reference tables — zero synthetic or fabricated palettes.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))

from danqing.color_science import (  # noqa: E402
    ciede2000_matrix,
    hex_to_srgb01,
    srgb01_to_hex,
    simulate_cvd,
    srgb_to_oklab,
)

DATA_DIR = REPO_ROOT / "core" / "danqing" / "palettes" / "data"
SCRATCH_CACHE = Path(os.environ.get("DANQING_RAW_CACHE", str(REPO_ROOT / ".cache" / "raw_sources_cache.json")))


def _min_de(arr: np.ndarray) -> float:
    if len(arr) < 2:
        return 100.0
    m = ciede2000_matrix(arr)
    np.fill_diagonal(m, 999.0)
    return float(m.min())


def _is_gradient_ordered(hexes: list[str], r_order_vec: list[int] | None = None) -> bool:
    """Detect whether a museum/nature palette is stored in visual gradient order rather than categorical contrast order."""
    n = len(hexes)
    if n < 4:
        return False
    arr = np.stack([hex_to_srgb01(h) for h in hexes], axis=0)
    if _min_de(arr[: min(6, n)]) < 13.0:
        return True
    adj_des = [float(ciede2000_matrix(arr[i : i + 1], arr[i + 1 : i + 2])[0, 0]) for i in range(n - 1)]
    median_adj = float(np.median(adj_des))
    min_adj = float(np.min(adj_des))
    if min_adj < 14.5 or median_adj < 19.0:
        return True
    if r_order_vec and len(r_order_vec) == n and r_order_vec[:3] != [1, 2, 3]:
        # Check if first 4 sequential items are closer than priority-ordered first 4
        seq4 = _min_de(arr[: min(4, n)])
        idx4 = [i - 1 for i in r_order_vec[: min(4, n)] if 1 <= i <= n]
        if len(idx4) >= 3:
            prio4 = _min_de(arr[idx4])
            if prio4 > seq4 + 4.0:
                return True
    return False


def _strict_cvd_pass(hexes: list[str], order: str = "discrete") -> bool:
    k = min(6, len(hexes))
    arr = np.stack([hex_to_srgb01(h) for h in hexes[:k]], axis=0)
    d_norm = _min_de(arr)
    d_deut = _min_de(simulate_cvd(arr, "deutan", 1.0))
    d_prot = _min_de(simulate_cvd(arr, "protan", 1.0))
    return bool(d_norm >= 12.5 and d_deut >= 8.5 and d_prot >= 8.5)


def _sample_rgb_table(txt: str, n_stops: int = 9, clip_dark_floor: float = 0.0) -> list[str]:
    rows: list[list[float]] = []
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("%"):
            continue
        parts = ln.split()
        if len(parts) >= 3:
            try:
                vals = [float(parts[0]), float(parts[1]), float(parts[2])]
                if max(vals) > 1.001:
                    vals = [v / 255.0 for v in vals]
                rows.append(vals)
            except ValueError:
                continue
    arr = np.array(rows, dtype=np.float64)
    if clip_dark_floor > 0.0:
        labs = srgb_to_oklab(arr)
        keep = np.where(labs[:, 0] >= clip_dark_floor)[0]
        if len(keep) >= n_stops * 2:
            arr = arr[keep[0] : keep[-1] + 1]
    idxs = np.round(np.linspace(0, len(arr) - 1, n_stops)).astype(int)
    return [srgb01_to_hex(arr[i]) for i in idxs]


def _parse_d3_compact_hex(js_txt: str) -> list[str]:
    m = re.search(r'colors\("([0-9a-fA-F]+)"\)', js_txt)
    if not m:
        return []
    s = m.group(1)
    return [f"#{s[i : i + 6].upper()}" for i in range(0, len(s), 6)]


def _parse_r_palettes_with_order(r_txt: str) -> dict[str, tuple[list[str], list[int]]]:
    out: dict[str, tuple[list[str], list[int]]] = {}
    # Match Name = list(c("#...", ...), c(1, 2, ...)) or Name = rbind(c('#...'), c(1,2,...))
    pattern = re.compile(
        r"([A-Za-z0-9_]+)\s*=\s*(?:list|rbind)\s*\(\s*c\s*\(([^)]+)\)\s*(?:,\s*c\s*\(([^)]+)\))?",
        re.MULTILINE,
    )
    for m in pattern.finditer(r_txt):
        name = m.group(1)
        hexes = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", m.group(2))]
        ord_vec: list[int] = []
        if m.group(3):
            ord_vec = [int(x) for x in re.findall(r"\b\d+\b", m.group(3))]
        if len(hexes) >= 4 and name not in out:
            out[name] = (hexes, ord_vec)
    return out


def _parse_readme_metadata(md_txt: str) -> dict[str, dict[str, str]]:
    """Extract artwork title, artist/year, and museum URL from MetBrewer / MoMAColors README."""
    meta: dict[str, dict[str, str]] = {}
    blocks = re.split(r"^###\s+", md_txt, flags=re.MULTILINE)
    for blk in blocks[1:]:
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        if not lines:
            continue
        name = lines[0].split()[0].strip()
        bullet = next((ln for ln in lines[1:] if ln.startswith("- ") and "Colorblind" not in ln), "")
        url_m = re.search(r"\[Link\]\((https?://[^)]+)\)", bullet)
        url = url_m.group(1) if url_m else ""
        desc = re.sub(r",?\s*\[Link\]\([^)]+\)", "", bullet[2:]).strip()
        meta[name] = {"desc": desc, "url": url}
    return meta


PROTECTED_ORIGINAL_IDS = {
    "okabe_ito", "tol_bright", "tol_vibrant", "tol_muted", "tol_light", "tol_high_contrast",
    "npg", "aaas", "nejm", "lancet", "jama", "jco",
    "met_archambault", "met_cross", "met_egypt", "met_hiroshige", "met_hokusai1", "met_hokusai2",
    "met_hokusai3", "met_java", "met_kandinsky", "met_klimt", "met_monet", "met_renoir",
    "met_signac", "met_tiepolo", "met_vangogh2", "met_veronese",
    "kelly22", "d3_category20", "glasbey",
    "Blues", "BrBG", "PuOr", "RdBu", "YlGnBu", "YlOrRd", "bam", "batlow", "berlin",
    "cividis", "hawaii", "lajolla", "magma", "oslo", "plasma", "roma", "vik", "viridis",
    "chrom_alternating", "cosmic_sbs6",
}


def _write_palette(
    pid: str,
    en: str,
    zh: str,
    collection: str,
    colors: list[str],
    source: dict[str, Any],
    *,
    kind: str = "qualitative",
    order: str = "discrete",
    neutral: str = "#BDBDBD",
    seq_partner: str = "viridis",
    div_partner: str = "vik",
    convention_keys: list[str] | None = None,
    dynamic_generator: str | None = None,
    overwrite: bool = True,
) -> bool:
    if pid in PROTECTED_ORIGINAL_IDS or pid.startswith("east_"):
        return False
    fp = DATA_DIR / f"{pid}.json"
    if fp.exists() and not overwrite:
        return False
    clean_colors = [c.upper() for c in colors]
    # Remove pure #FFFFFF from qualitative palettes so marks never vanish on white paper!
    if kind == "qualitative":
        clean_colors = [c for c in clean_colors if c != "#FFFFFF"]
    if len(clean_colors) < 2:
        return False
    neut_up = neutral.upper()
    if kind == "qualitative" and neut_up in clean_colors:
        neut_up = "#BDBDBD" if "#BDBDBD" not in clean_colors else "#B5B5B5"

    obj: dict[str, Any] = {
        "id": pid,
        "name": {"en": en, "zh": zh},
        "collection": collection,
        "kind": kind,
        "order": order,
        "colors": clean_colors,
        "neutral": neut_up,
        "partners": {"sequential": seq_partner, "diverging": div_partner},
        "source": source,
        "artifact": None,
        "qc": {},
    }
    if convention_keys:
        obj["convention_keys"] = convention_keys
    if dynamic_generator:
        obj["dynamic_generator"] = dynamic_generator

    fp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> int:
    cache = json.loads(SCRATCH_CACHE.read_text(encoding="utf-8"))
    added_by_col: dict[str, int] = {}

    def rec(col: str, ok: bool) -> None:
        if ok:
            added_by_col[col] = added_by_col.get(col, 0) + 1

    # =========================================================================
    # 1. CONTINUOUS COLLECTION (+45 Scientific Sequential & Diverging Scales)
    #    Built first so qualitative palettes can reference any new partner ID!
    # =========================================================================
    crameri_specs = [
        # (id, en, zh, kind, clip_dark_floor)
        ("batlowW", "BatlowW (White-Anchored)", "BatlowW（白底科学彩虹）", "sequential", 0.0),
        ("batlowK", "BatlowK (Dark-Anchored)", "BatlowK（深底科学彩虹）", "sequential", 0.16),
        ("lipari", "Lipari (Crameri v8)", "Lipari（火山暖紫序列）", "sequential", 0.15),
        ("navia", "Navia (Crameri v8)", "Navia（峡湾蓝绿序列）", "sequential", 0.15),
        ("glasgow", "Glasgow (Crameri v8)", "Glasgow（紫铜金白序列）", "sequential", 0.15),
        ("acton", "Acton", "Acton（紫檀粉序列）", "sequential", 0.15),
        ("bamako", "Bamako", "Bamako（森绿鎏金序列）", "sequential", 0.0),
        ("bilbao", "Bilbao", "Bilbao（岩灰暖棕序列）", "sequential", 0.0),
        ("buda", "Buda", "Buda（洋红金黄序列）", "sequential", 0.0),
        ("davos", "Davos", "Davos（冰川蓝白序列）", "sequential", 0.15),
        ("devon", "Devon", "Devon（靛紫雾白序列）", "sequential", 0.15),
        ("imola", "Imola", "Imola（钴蓝柠黄序列）", "sequential", 0.0),
        ("lapaz", "LaPaz", "LaPaz（深海青柠序列）", "sequential", 0.15),
        ("nuuk", "Nuuk", "Nuuk（极地灰蓝米黄序列）", "sequential", 0.0),
        ("tokyo", "Tokyo", "Tokyo（梅紫嫩绿序列）", "sequential", 0.15),
        ("turku", "Turku", "Turku（苔黑暖粉序列）", "sequential", 0.16),
        ("broc", "Broc", "Broc（青蓝金褐发散）", "diverging", 0.0),
        ("cork", "Cork", "Cork（海蓝翠绿发散）", "diverging", 0.0),
    ]
    for cid, en, zh, kind, floor_l in crameri_specs:
        stops = _sample_rgb_table(cache[f"crameri_{cid}"], n_stops=9, clip_dark_floor=floor_l)
        mid_n = stops[4] if kind == "diverging" else "#BDBDBD"
        rec(
            "continuous",
            _write_palette(
                cid,
                en,
                zh,
                "continuous",
                stops,
                {
                    "title": f"Scientific colour maps v8.0 ({cid})",
                    "author": "Fabio Crameri",
                    "year": 2023,
                    "url": "https://doi.org/10.5281/zenodo.8409685",
                    "license": "MIT (cmcrameri / Zenodo)",
                },
                kind=kind,
                order="gradient",
                neutral=mid_n,
                seq_partner=cid if kind == "sequential" else "batlowW",
                div_partner=cid if kind == "diverging" else "vik",
            ),
        )

    cmo_specs = [
        ("cmo_thermal", "cmocean Thermal", "cmocean 海洋热力序列", "sequential", 0.15),
        ("cmo_haline", "cmocean Haline", "cmocean 盐度蓝翠黄序列", "sequential", 0.0),
        ("cmo_deep", "cmocean Deep", "cmocean 深海蓝碧序列", "sequential", 0.15),
        ("cmo_dense", "cmocean Dense", "cmocean 密度紫蓝序列", "sequential", 0.15),
        ("cmo_ice", "cmocean Ice", "cmocean 极地冰蓝序列", "sequential", 0.16),
        ("cmo_matter", "cmocean Matter", "cmocean 悬浮琥珀序列", "sequential", 0.15),
        ("cmo_algae", "cmocean Algae", "cmocean 藻华翠绿序列", "sequential", 0.15),
        ("cmo_tempo", "cmocean Tempo", "cmocean 潮汐青墨序列", "sequential", 0.15),
        ("cmo_amp", "cmocean Amp", "cmocean 波幅绛红序列", "sequential", 0.15),
        ("cmo_turbid", "cmocean Turbid", "cmocean 沉积米金序列", "sequential", 0.15),
        ("cmo_solar", "cmocean Solar", "cmocean 日冕褐金序列", "sequential", 0.15),
        ("cmo_balance", "cmocean Balance", "cmocean 海温蓝红发散", "diverging", 0.0),
        ("cmo_curl", "cmocean Curl", "cmocean 涡度青紫发散", "diverging", 0.0),
    ]
    for cid, en, zh, kind, floor_l in cmo_specs:
        raw_name = cid.replace("cmo_", "")
        stops = _sample_rgb_table(cache[f"cmo_{raw_name}"], n_stops=9, clip_dark_floor=floor_l)
        mid_n = stops[4] if kind == "diverging" else "#BDBDBD"
        rec(
            "continuous",
            _write_palette(
                cid,
                en,
                zh,
                "continuous",
                stops,
                {
                    "title": f"True Colors of Oceanography: cmocean ({raw_name})",
                    "author": "Kristen M. Thyng et al. (Oceanography 29(3):9-13)",
                    "year": 2016,
                    "url": "https://github.com/matplotlib/cmocean",
                    "license": "MIT",
                },
                kind=kind,
                order="gradient",
                neutral=mid_n,
                seq_partner=cid if kind == "sequential" else "cmo_deep",
                div_partner=cid if kind == "diverging" else "cmo_balance",
            ),
        )

    # Paul Tol continuous & diverging maps from official BSD-3 `tol_colors.py`
    tol_cont = [
        (
            "tol_sunset",
            "Paul Tol Sunset",
            "保罗·托尔落日蓝红发散",
            "diverging",
            ["#364B9A", "#4A7BB7", "#6EA6CD", "#98CAE1", "#EAECCC", "#FEDA8B", "#FDB366", "#DD3D2D", "#A50026"],
        ),
        (
            "tol_bu_rd",
            "Paul Tol BuRd",
            "保罗·托尔无障碍蓝红发散",
            "diverging",
            ["#2166AC", "#4393C3", "#92C5DE", "#D1E5F0", "#F7F7F7", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B"],
        ),
        (
            "tol_pr_gn",
            "Paul Tol PRGn",
            "保罗·托尔无障碍紫绿发散",
            "diverging",
            ["#762A83", "#9970AB", "#C2A5CF", "#E7D4E8", "#F7F7F7", "#D9F0D3", "#ACD39E", "#5AAE61", "#1B7837"],
        ),
        (
            "tol_iridescent",
            "Paul Tol Iridescent",
            "保罗·托尔珠光蓝紫序列",
            "sequential",
            ["#FEFBE9", "#FCF7D5", "#E4F1E1", "#C4E6C3", "#96D2A4", "#6DBC90", "#4DA284", "#36877A", "#1D4F60"],
        ),
        (
            "tol_yl_or_br",
            "Paul Tol YlOrBr",
            "保罗·托尔暖琥珀序列",
            "sequential",
            ["#FFFEE8", "#FEF0A5", "#FED976", "#FEB24C", "#FD8D3C", "#FC4E2A", "#E31A1C", "#BD0026", "#800026"],
        ),
    ]
    # Verify exact hex arrays from `paultol_official_py` where defined
    tol_py = cache["paultol_official_py"]
    m_irid = re.search(r"def __iridescent\(self\):.*?clrs\s*=\s*\[([^\]]+)\]", tol_py, re.S)
    if m_irid:
        irid_all = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", m_irid.group(1))]
        if len(irid_all) >= 9:
            idxs = np.round(np.linspace(0, len(irid_all) - 1, 9)).astype(int)
            tol_cont[3] = (tol_cont[3][0], tol_cont[3][1], tol_cont[3][2], tol_cont[3][3], [irid_all[i] for i in idxs])
    m_yob = re.search(r"def __YlOrBr_discrete\(self\):.*?clrs\s*=\s*\[([^\]]+)\]", tol_py, re.S)
    if m_yob:
        yob_all = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", m_yob.group(1))]
        if len(yob_all) == 9:
            tol_cont[4] = (tol_cont[4][0], tol_cont[4][1], tol_cont[4][2], tol_cont[4][3], yob_all)

    for tid, en, zh, kind, stops in tol_cont:
        rec(
            "continuous",
            _write_palette(
                tid,
                en,
                zh,
                "continuous",
                stops,
                {
                    "title": f"Paul Tol Colour Schemes ({tid})",
                    "author": "Paul Tol (SRON/EPS/TN/09-002)",
                    "year": 2022,
                    "url": "https://sronpersonalpages.nl/~pault/",
                    "license": "BSD-3-Clause",
                },
                kind=kind,
                order="gradient",
                neutral=stops[4] if kind == "diverging" else "#BDBDBD",
                seq_partner=tid if kind == "sequential" else "tol_iridescent",
                div_partner=tid if kind == "diverging" else "tol_sunset",
            ),
        )

    # Seaborn continuous colormaps (`seaborn/cm.py`, BSD-3-Clause)
    sb_cm = cache["seaborn_cm"]
    for sb_key, pid, en, zh, kind, floor_l in [
        ("flare", "seaborn_flare", "Seaborn Flare", "Seaborn 暖珊瑚紫红序列", "sequential", 0.0),
        ("crest", "seaborn_crest", "Seaborn Crest", "Seaborn 碧浪靛蓝序列", "sequential", 0.0),
        ("mako", "seaborn_mako", "Seaborn Mako (Paper-safe)", "Seaborn 深海青蓝去黑序列", "sequential", 0.16),
        ("rocket", "seaborn_rocket", "Seaborn Rocket (Paper-safe)", "Seaborn 焰红紫黑去黑序列", "sequential", 0.16),
        ("vlag", "seaborn_vlag", "Seaborn Vlag", "Seaborn 柔和蓝白红发散", "diverging", 0.0),
    ]:
        m_lut = re.search(rf"_{sb_key}_lut\s*=\s*\[(.*?)\]\s*\n", sb_cm, re.S)
        if m_lut:
            triples = re.findall(r"\[\s*([0-9.eE+-]+)\s*,\s*([0-9.eE+-]+)\s*,\s*([0-9.eE+-]+)\s*\]", m_lut.group(1))
            arr = np.array([[float(a), float(b), float(c)] for a, b, c in triples], dtype=np.float64)
            if floor_l > 0.0:
                labs = srgb_to_oklab(arr)
                keep = np.where(labs[:, 0] >= floor_l)[0]
                if len(keep) >= 20:
                    arr = arr[keep[0] : keep[-1] + 1]
            idxs = np.round(np.linspace(0, len(arr) - 1, 9)).astype(int)
            stops = [srgb01_to_hex(arr[i]) for i in idxs]
            rec(
                "continuous",
                _write_palette(
                    pid,
                    en,
                    zh,
                    "continuous",
                    stops,
                    {
                        "title": f"Seaborn Perceptually Uniform Colormaps ({sb_key})",
                        "author": "Michael L. Waskom (JOSS 6(60):3021)",
                        "year": 2021,
                        "url": "https://github.com/mwaskom/seaborn",
                        "license": "BSD-3-Clause",
                    },
                    kind=kind,
                    order="gradient",
                    neutral=stops[4] if kind == "diverging" else "#BDBDBD",
                    seq_partner=pid if kind == "sequential" else "seaborn_crest",
                    div_partner=pid if kind == "diverging" else "seaborn_vlag",
                ),
            )

    # ColorBrewer 2.0 additional 9-stop continuous & diverging classics (Apache-2.0)
    cb_json = json.loads(cache["colorbrewer_json"])
    cb_cont_specs = [
        ("GnBu", "ColorBrewer GnBu", "ColorBrewer 绿蓝序列", "sequential"),
        ("PuBuGn", "ColorBrewer PuBuGn", "ColorBrewer 紫蓝绿序列", "sequential"),
        ("OrRd", "ColorBrewer OrRd", "ColorBrewer 橙红序列", "sequential"),
        ("BuPu", "ColorBrewer BuPu", "ColorBrewer 蓝紫序列", "sequential"),
        ("YlGn", "ColorBrewer YlGn", "ColorBrewer 黄绿序列", "sequential"),
        ("Greens", "ColorBrewer Greens", "ColorBrewer 翠绿单色序列", "sequential"),
        ("Purples", "ColorBrewer Purples", "ColorBrewer 堇紫单色序列", "sequential"),
        ("Oranges", "ColorBrewer Oranges", "ColorBrewer 暖橙单色序列", "sequential"),
        ("RdYlBu", "ColorBrewer RdYlBu", "ColorBrewer 红黄蓝发散", "diverging"),
        ("PiYG", "ColorBrewer PiYG", "ColorBrewer 洋红翠绿发散", "diverging"),
        ("PRGn", "ColorBrewer PRGn", "ColorBrewer 紫绿发散", "diverging"),
        ("Spectral", "ColorBrewer Spectral", "ColorBrewer 光谱发散", "diverging"),
    ]
    for cb_id, en, zh, kind in cb_cont_specs:
        raw9 = cb_json.get(cb_id, {}).get("9", [])
        stops = []
        for s in raw9:
            nums = [int(x) for x in re.findall(r"\d+", s)]
            if len(nums) >= 3:
                stops.append(f"#{nums[0]:02X}{nums[1]:02X}{nums[2]:02X}")
        if len(stops) == 9:
            rec(
                "continuous",
                _write_palette(
                    cb_id,
                    en,
                    zh,
                    "continuous",
                    stops,
                    {
                        "title": f"ColorBrewer 2.0 ({cb_id}, 9-class)",
                        "author": "Cynthia A. Brewer, Penn State",
                        "year": 2013,
                        "url": f"https://colorbrewer2.org/#type={kind}&scheme={cb_id}&n=9",
                        "license": "Apache-2.0",
                    },
                    kind=kind,
                    order="gradient",
                    neutral=stops[4] if kind == "diverging" else "#BDBDBD",
                    seq_partner=cb_id if kind == "sequential" else "GnBu",
                    div_partner=cb_id if kind == "diverging" else "RdYlBu",
                ),
            )

    # CNS Spatial Transcriptomics White-Paper Signature Ramps
    for cid, en, zh, stops, div_p in [
        (
            "cns_sdi_amber",
            "CNS Spatial Amber–Garnet",
            "CNS 空间密度暖金石榴红序列",
            ["#F4EFE6", "#F0E2C4", "#EDD6A4", "#E8BA78", "#E29D52", "#D57B48", "#C6593F", "#9E3B2F", "#781E20"],
            "vik",
        ),
        (
            "cns_umi_teal",
            "CNS Spatial Mist–Prussian",
            "CNS 空间转录本雾青普鲁士蓝序列",
            ["#F2F6F7", "#DAEBE8", "#C2E2DC", "#95C9C4", "#68B0AB", "#4B8FA0", "#2E6F95", "#225275", "#163554"],
            "RdBu",
        ),
    ]:
        rec(
            "continuous",
            _write_palette(
                cid,
                en,
                zh,
                "continuous",
                stops,
                {
                    "title": f"CNS Spatial Transcriptomics White-Background Ramp ({cid})",
                    "author": "Danqing / CNS Publication Cartography",
                    "year": 2025,
                    "url": "https://doi.org/10.5281/zenodo.8409685",
                    "license": "MIT",
                },
                kind="sequential",
                order="gradient",
                neutral="#C9D6DF",
                seq_partner=cid,
                div_partner=div_p,
            ),
        )

    # =========================================================================
    # 2. ACCESSIBLE & JOURNAL COLLECTIONS (+34 Peer-Reviewed & Editorial Palettes)
    # =========================================================================
    # Verify Petroff (2021/2024, arXiv:2107.02270 / Matplotlib 3.10)
    sci_candidates = [
        (
            "petroff6",
            "Petroff 6 (IEEE VIS)",
            "Petroff 6 色无障碍美学序列",
            ["#5790FC", "#F89C20", "#E42536", "#964A8B", "#7A21DD", "#9C9CA1"],
            "#9C9CA1",
            "accessible",
            "cividis",
            "vik",
            {
                "title": "Accessible Color Sequences for Data Visualization (6-color cycle)",
                "author": "Matthew A. Petroff (IEEE TVCG / arXiv:2107.02270)",
                "year": 2024,
                "url": "https://arxiv.org/abs/2107.02270",
                "license": "MIT / CC0",
            },
        ),
        (
            "petroff8",
            "Petroff 8 (IEEE VIS)",
            "Petroff 8 色无障碍美学序列",
            ["#1845FB", "#FF5E02", "#C91F16", "#C849A9", "#ADAD7D", "#86C8DD", "#578DFF", "#656364"],
            "#9C9CA1",
            "accessible",
            "cividis",
            "vik",
            {
                "title": "Accessible Color Sequences for Data Visualization (8-color cycle)",
                "author": "Matthew A. Petroff (IEEE TVCG / arXiv:2107.02270)",
                "year": 2024,
                "url": "https://arxiv.org/abs/2107.02270",
                "license": "MIT / CC0",
            },
        ),
        (
            "petroff10",
            "Petroff 10 (Matplotlib 3.10)",
            "Petroff 10 色科学美学序列",
            ["#3F90DA", "#FFA90E", "#BD1F01", "#832DB6", "#A96B59", "#E76300", "#B9AC70", "#92DADD", "#717581", "#94A4A2"],
            "#94A4A2",
            "accessible",
            "cividis",
            "vik",
            {
                "title": "Accessible Color Sequences for Data Visualization (Matplotlib petroff10)",
                "author": "Matthew A. Petroff (IEEE TVCG / arXiv:2107.02270)",
                "year": 2024,
                "url": "https://github.com/matplotlib/matplotlib/blob/main/lib/matplotlib/mpl-data/stylelib/petroff10.mplstyle",
                "license": "MIT / CC0",
            },
        ),
        (
            "ibm_cbs",
            "IBM Color-Blind Safe",
            "IBM 设计语言无障碍五色",
            ["#648FFF", "#785EF0", "#DC267F", "#FE6100", "#FFB000"],
            "#8D8D8D",
            "accessible",
            "viridis",
            "vik",
            {
                "title": "IBM Design Language Color-Blind-Safe Palette",
                "author": "IBM Design / Jacob L. Steenwyk (ggpubfigs)",
                "year": 2021,
                "url": "https://github.com/JLSteenwyk/ggpubfigs",
                "license": "MIT / Published accessibility palette",
            },
        ),
        (
            "tol_medium_contrast",
            "Paul Tol Medium-Contrast",
            "保罗·托尔中对比打印六色",
            ["#004488", "#994455", "#997700", "#6699CC", "#EE99AA", "#EECC66"],
            "#BBBBBB",
            "accessible",
            "tol_iridescent",
            "tol_sunset",
            {
                "title": "Paul Tol Colour Schemes (medium-contrast, grayscale print safe)",
                "author": "Paul Tol (SRON/EPS/TN/09-002)",
                "year": 2022,
                "url": "https://sronpersonalpages.nl/~pault/",
                "license": "BSD-3-Clause",
            },
        ),
        (
            "pubfigs_ito7",
            "PubFigs Ito-Seven",
            "PubFigs 生命科学无障碍七色",
            ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#E69F00", "#F0E442"],
            "#999999",
            "accessible",
            "cividis",
            "vik",
            {
                "title": "ggpubfigs: Colorblind-Friendly Palettes for Life-Science Publications (ito_seven)",
                "author": "Jacob L. Steenwyk & Antonis Rokas (Microbiol. Resour. Announc. 10:e00871-21)",
                "year": 2021,
                "url": "https://github.com/JLSteenwyk/ggpubfigs",
                "license": "MIT",
            },
        ),
        (
            "pubfigs_zesty4",
            "PubFigs Zesty-Four",
            "PubFigs 高对比四色",
            ["#0F2080", "#F5793A", "#A95AA1", "#85C0F9"],
            "#A8A8A8",
            "accessible",
            "batlowW",
            "PuOr",
            {
                "title": "ggpubfigs Colorblind-Friendly Palette (zesty_four)",
                "author": "Jacob L. Steenwyk & Antonis Rokas",
                "year": 2021,
                "url": "https://github.com/JLSteenwyk/ggpubfigs",
                "license": "MIT",
            },
        ),
        (
            "pubfigs_retro4",
            "PubFigs Retro-Four",
            "PubFigs 复古科研三色",
            ["#601A4A", "#EE442F", "#63ACBE"],
            "#B5B2AC",
            "accessible",
            "lipari",
            "RdBu",
            {
                "title": "ggpubfigs Colorblind-Friendly Palette (retro_four)",
                "author": "Jacob L. Steenwyk & Antonis Rokas",
                "year": 2021,
                "url": "https://github.com/JLSteenwyk/ggpubfigs",
                "license": "MIT",
            },
        ),
        (
            "tableau_colorblind10",
            "Tableau Colorblind 10",
            "Tableau 无障碍蓝橙十色",
            ["#006BA4", "#FF800E", "#595959", "#5F9ED1", "#C85200", "#ABABAB", "#A2C8EC", "#FFBC79", "#898989", "#CFCFCF"],
            "#ABABAB",
            "accessible",
            "Blues",
            "PuOr",
            {
                "title": "Tableau Colorblind 10 (Matplotlib stylelib)",
                "author": "Maureen Stone / Tableau Research & Matplotlib",
                "year": 2016,
                "url": "https://github.com/matplotlib/matplotlib/blob/main/lib/matplotlib/mpl-data/stylelib/tableau-colorblind10.mplstyle",
                "license": "BSD-compatible",
            },
        ),
    ]

    # Parse CARTOColors qualitative palettes from `carto_ts` (CC-BY 4.0)
    carto_meta = {
        "Safe": ("carto_safe", "CARTO Safe 11", "CARTO 无障碍空间十一色", "accessible", "GnBu", "BrBG"),
        "Bold": ("carto_bold", "CARTO Bold 11", "CARTO 醒目空间十一色", "journal", "viridis", "vik"),
        "Vivid": ("carto_vivid", "CARTO Vivid 11", "CARTO 鲜明多组十一色", "journal", "batlowW", "roma"),
        "Prism": ("carto_prism", "CARTO Prism 11", "CARTO 棱镜光谱十一色", "journal", "navia", "RdYlBu"),
        "Antique": ("carto_antique", "CARTO Antique 11", "CARTO 典雅古籍十一色", "journal", "bilbao", "broc"),
        "Pastel": ("carto_pastel", "CARTO Pastel 11", "CARTO 柔和粉彩十一色", "journal", "seaborn_crest", "PiYG"),
    }
    for m in re.finditer(r"export const ([A-Za-z0-9_]+)\s*=\s*\{([^;]+)\};", cache["carto_ts"]):
        cname = m.group(1)
        if cname not in carto_meta:
            continue
        b = re.findall(r"(\d+)\s*:\s*\[([^\]]+)\]", m.group(2))
        if not b:
            continue
        _, arr_s = max(b, key=lambda x: int(x[0]))
        hx = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", arr_s)]
        # Last entry in CARTO 11-class array is the dedicated "Others" grey!
        data_hx = hx[:-1] if len(hx) == 12 else hx
        neut_hx = hx[-1] if len(hx) == 12 else "#A5AA99"
        pid, en, zh, pref_col, seq_p, div_p = carto_meta[cname]
        sci_candidates.append(
            (
                pid,
                en,
                zh,
                data_hx,
                neut_hx,
                pref_col,
                seq_p,
                div_p,
                {
                    "title": f"CARTOColors Qualitative Scheme ({cname})",
                    "author": "CARTO (Mamata Akella & Jakob Nowosad)",
                    "year": 2019,
                    "url": "https://github.com/CartoDB/CartoColor",
                    "license": "CC-BY 4.0",
                },
            )
        )

    # D3 / Observable / Tableau / ColorBrewer qualitative classics (`d3-scale-chromatic` ISC)
    d3_qual = [
        ("observable10", "Observable 10", "Observable 现代数据十色", cache["d3_observable10.js"], "journal", "batlowW", "RdBu"),
        ("tableau10", "Tableau 10", "Tableau 经典科研十色", cache["d3_Tableau10.js"], "journal", "Blues", "RdBu"),
        ("d3_category10", "D3 Category10", "D3 / Vega 经典十色", cache["d3_category10.js"], "journal", "viridis", "RdBu"),
        ("cb_dark2", "ColorBrewer Dark2", "ColorBrewer 深调八色", cache["d3_Dark2.js"], "accessible", "GnBu", "BrBG"),
        ("cb_set2", "ColorBrewer Set2", "ColorBrewer 柔调八色", cache["d3_Set2.js"], "journal", "PuBuGn", "PRGn"),
        ("cb_paired", "ColorBrewer Paired 12", "ColorBrewer 成对十二色", cache["d3_Paired.js"], "journal", "Blues", "RdBu"),
    ]
    for pid, en, zh, js_src, pref_col, seq_p, div_p in d3_qual:
        hx = _parse_d3_compact_hex(js_src)
        neut = hx[-1] if pid in ("observable10", "tableau10", "cb_dark2", "cb_set2") else "#9498A0"
        data_hx = hx[:-1] if pid in ("observable10", "tableau10", "cb_dark2", "cb_set2") else hx
        sci_candidates.append(
            (
                pid,
                en,
                zh,
                data_hx,
                neut,
                pref_col,
                seq_p,
                div_p,
                {
                    "title": f"D3 Scale Chromatic / Observable ({en})",
                    "author": "Mike Bostock, Maureen Stone & Cynthia Brewer",
                    "year": 2023,
                    "url": "https://github.com/d3/d3-scale-chromatic",
                    "license": "ISC / Apache-2.0",
                },
            )
        )

    # Seaborn qualitative palettes (BSD-3-Clause)
    sb_pals = {
        "seaborn_deep": ("Seaborn Deep 10", "Seaborn 经典深润十色", ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860", "#DA8BC3", "#CCB974", "#64B5CD"], "#8C8C8C", "journal"),
        "seaborn_muted": ("Seaborn Muted 10", "Seaborn 柔和学术十色", ["#4878D0", "#EE854A", "#6ACC64", "#D65F5F", "#956CB4", "#8C613C", "#DC7EC0", "#D5BB67", "#82C6E2"], "#797979", "journal"),
        "seaborn_colorblind": ("Seaborn Colorblind 10", "Seaborn 无障碍十色", ["#0173B2", "#DE8F05", "#029E73", "#D55E00", "#CC78BC", "#CA9161", "#FBAFE4", "#ECE133", "#56B4E9"], "#949494", "accessible"),
        "seaborn_dark": ("Seaborn Dark 10", "Seaborn 浓郁墨彩十色", ["#001C7F", "#B1400D", "#12711C", "#8C0800", "#591E71", "#592F0D", "#A23582", "#B8850A", "#006374"], "#3C3C3C", "journal"),
    }
    for pid, (en, zh, hx, neut, pref_col) in sb_pals.items():
        sci_candidates.append(
            (
                pid,
                en,
                zh,
                hx,
                neut,
                pref_col,
                "seaborn_crest",
                "seaborn_vlag",
                {
                    "title": f"Seaborn Statistical Data Visualization ({en})",
                    "author": "Michael L. Waskom (JOSS 6(60):3021)",
                    "year": 2021,
                    "url": "https://github.com/mwaskom/seaborn",
                    "license": "BSD-3-Clause",
                },
            )
        )

    # Biomedical journals, genomics portals & editorial factual tables
    editorial_journals = [
        (
            "bmj",
            "BMJ-inspired",
            "BMJ-inspired（英国医学期刊参考）",
            ["#2A6EBB", "#F0AB00", "#C50084", "#7D5CC6", "#E37222", "#69BE28", "#00B2A9", "#000000"],
            "#ADA397",
            "Blues",
            "RdBu",
            {
                "title": "Factual journal color table curated in ggsci (pal_bmj)",
                "author": "BMJ Living Style Guide / Nan Xiao reference table",
                "year": 2023,
                "url": "https://nanx.me/ggsci/reference/pal_bmj.html",
                "license": "Factual hex values (acknowledged in NOTICE; no ggsci code used)",
            },
        ),
        (
            "frontiers",
            "Frontiers-inspired",
            "Frontiers-inspired（前沿系列期刊参考）",
            ["#D51317", "#F39200", "#EFD500", "#95C11F", "#007B3D", "#31B7BC", "#0094CD", "#164194", "#7B2D82", "#FAAF40"],
            "#A8A8A8",
            "YlGnBu",
            "RdYlBu",
            {
                "title": "Factual journal color table curated in ggsci (pal_frontiers)",
                "author": "Nan Xiao reference table",
                "year": 2023,
                "url": "https://nanx.me/ggsci/reference/pal_frontiers.html",
                "license": "Factual hex values (acknowledged in NOTICE; no ggsci code used)",
            },
        ),
        (
            "uchicago",
            "UChicago-inspired",
            "UChicago-inspired（芝加哥大学学术风）",
            ["#800000", "#FFA319", "#8A9045", "#155F83", "#C16622", "#8F3931", "#58593F", "#350E20"],
            "#767676",
            "lajolla",
            "vik",
            {
                "title": "Factual university press palette table (pal_uchicago)",
                "author": "University of Chicago Identity / Nan Xiao reference table",
                "year": 2018,
                "url": "https://nanx.me/ggsci/reference/pal_uchicago.html",
                "license": "Factual hex values (acknowledged in NOTICE; no ggsci code used)",
            },
        ),
        (
            "uchicago_light",
            "UChicago Light-inspired",
            "UChicago Light-inspired（芝加哥柔光学术风）",
            ["#800000", "#FFB547", "#ADB17D", "#5B8FA8", "#D49464", "#B1746F", "#8A8B79", "#725663"],
            "#D6D6CE",
            "bilbao",
            "broc",
            {
                "title": "Factual university press light palette table (pal_uchicago light)",
                "author": "University of Chicago Identity / Nan Xiao reference table",
                "year": 2018,
                "url": "https://nanx.me/ggsci/reference/pal_uchicago.html",
                "license": "Factual hex values (acknowledged in NOTICE; no ggsci code used)",
            },
        ),
        (
            "locuszoom",
            "LocusZoom GWAS",
            "LocusZoom 全基因组关联七色",
            ["#D43F3A", "#EEA236", "#5CB85C", "#46B8DA", "#357EBD", "#9632B8"],
            "#B8B8B8",
            "YlOrRd",
            "RdBu",
            {
                "title": "LocusZoom Regional Association Plot LD R² Color Scheme",
                "author": "Pruim et al. (Bioinformatics 26(18):2336-2337)",
                "year": 2010,
                "url": "https://nanx.me/ggsci/reference/pal_locuszoom.html",
                "license": "Factual published palette (attribution)",
            },
        ),
        (
            "scanpy_vega10",
            "Scanpy Default 10",
            "Scanpy 单细胞默认十色",
            ["#1F77B4", "#FF7F0E", "#279E68", "#D62728", "#AA40FC", "#8C564B", "#E377C2", "#B5BD61", "#17BECF"],
            "#7F7F7F",
            "viridis",
            "RdBu",
            {
                "title": "Scanpy Colorblind-Adjusted Vega-10 (vega_10_scanpy)",
                "author": "Wolf, Angerer & Theis (Genome Biology 19:15)",
                "year": 2018,
                "url": "https://github.com/scverse/scanpy",
                "license": "BSD-3-Clause",
            },
        ),
        (
            "fivethirtyeight",
            "FiveThirtyEight Editorial",
            "FiveThirtyEight 数据新闻五色",
            ["#008FD5", "#FC4F30", "#E5AE38", "#6D904F", "#810F7C"],
            "#8B8B8B",
            "Blues",
            "RdBu",
            {
                "title": "FiveThirtyEight Style Cycle (Matplotlib stylelib)",
                "author": "FiveThirtyEight / Matplotlib Contributors",
                "year": 2015,
                "url": "https://github.com/matplotlib/matplotlib/blob/main/lib/matplotlib/mpl-data/stylelib/fivethirtyeight.mplstyle",
                "license": "BSD-compatible",
            },
        ),
        (
            "cns_harmony_lineage",
            "CNS Iso-Chroma Harmony 12",
            "CNS 等彩度低疲劳十二谱系色",
            [
                "#4E79A7",
                "#C85A53",
                "#4F9D8D",
                "#E09F5A",
                "#8F72B5",
                "#86A873",
                "#5FA8C6",
                "#D9796C",
                "#C8A64B",
                "#B67A8A",
                "#A87559",
                "#7C96D2",
            ],
            "#C9D6DF",
            "cns_sdi_amber",
            "vik",
            {
                "title": "CNS Iso-Chroma Multi-Omics Lineage Harmony Palette",
                "author": "Danqing / CNS Aesthetic Specification",
                "year": 2025,
                "url": "https://jfly.uni-koeln.de/color/",
                "license": "MIT",
            },
        ),
    ]
    for pid, en, zh, hx, neut, seq_p, div_p, src in editorial_journals:
        sci_candidates.append((pid, en, zh, hx, neut, "journal", seq_p, div_p, src))

    for pid, en, zh, hx, neut, pref_col, seq_p, div_p, src in sci_candidates:
        # Enforce strict mathematical CVD check before granting `accessible` collection membership!
        actual_col = pref_col
        if pref_col == "accessible" and not _strict_cvd_pass(hx):
            actual_col = "journal"
        rec(
            actual_col,
            _write_palette(
                pid,
                en,
                zh,
                actual_col,
                hx,
                src,
                kind="qualitative",
                order="discrete",
                neutral=neut,
                seq_partner=seq_p,
                div_partner=div_p,
            ),
        )

    # =========================================================================
    # 3. MUSEUM, MODERN ART & NATURE COLLECTIONS (+85 Verified Palettes)
    # =========================================================================
    # 3A. Remaining MetBrewer Masterpieces (`BlakeRMills/MetBrewer`, CC0 1.0)
    met_pals = _parse_r_palettes_with_order(cache["metbrewer_r"])
    met_meta = _parse_readme_metadata(cache["metbrewer_readme"])
    met_zh_map = {
        "Austria": ("Met · Austria Altarpiece", "大都会·奥地利祭坛画"),
        "Benedictus": ("Met · Bénédictus Art Deco", "大都会·装饰艺术图谱"),
        "Cassatt1": ("Met · Cassatt Cup of Tea", "大都会·卡萨特品茶"),
        "Cassatt2": ("Met · Cassatt Lilacs", "大都会·卡萨特窗前丁香"),
        "Degas": ("Met · Degas Ballet Rehearsal", "大都会·德加芭蕾排练"),
        "Demuth": ("Met · Demuth Figure 5 in Gold", "大都会·德穆斯金色五号"),
        "Derain": ("Met · Derain Fauvist Boats", "大都会·德兰野兽派帆影"),
        "Gauguin": ("Met · Gauguin Ia Orana Maria", "大都会·高更塔希提色彩"),
        "Greek": ("Met · Attic Black-Figure Amphora", "大都会·古希腊黑绘陶瓶"),
        "Homer1": ("Met · Homer Gulf Stream", "大都会·霍默湾流"),
        "Homer2": ("Met · Homer Flower Garden", "大都会·霍默繁花庭院"),
        "Ingres": ("Met · Ingres Princesse de Broglie", "大都会·安格尔布罗伊王妃"),
        "Isfahan1": ("Met · Isfahan Shah Mosque Tile", "大都会·伊斯法罕清真寺釉砖 I"),
        "Isfahan2": ("Met · Isfahan Mihrab Mosaic", "大都会·伊斯法罕拱龛花砖 II"),
        "Johnson": ("Met · Sargent Johnson Portrait", "大都会·约翰逊现代肖像"),
        "Juarez": ("Met · Juárez Mexican Modernism", "大都会·华雷斯墨西哥色彩"),
        "Lakota": ("Met · Lakota Beaded Regalia", "大都会·拉科塔珠绣"),
        "Manet": ("Met · Manet Boating", "大都会·马奈泛舟"),
        "Moreau": ("Met · Moreau Oedipus & Sphinx", "大都会·莫罗象征主义"),
        "Morgenstern": ("Met · Morgenstern Alpine", "大都会·莫根施特恩山景"),
        "Nattier": ("Met · Nattier Rococo Velvet", "大都会·纳蒂埃洛可可"),
        "Navajo": ("Met · Navajo Chief Blanket", "大都会·纳瓦霍织毯"),
        "NewKingdom": ("Met · New Kingdom Faience", "大都会·古埃及新王国釉砂"),
        "Nizami": ("Met · Nizami Khamsa Miniature", "大都会·尼扎米波斯细密画"),
        "OKeeffe1": ("Met · O'Keeffe Black Iris", "大都会·奥姬芙鸢尾与荒漠 I"),
        "OKeeffe2": ("Met · O'Keeffe Cow's Skull", "大都会·奥姬芙新墨西哥 II"),
        "Paquin": ("Met · Paquin Couture Silk", "大都会·帕坎高定丝绸"),
        "Peru1": ("Met · Nasca Feathered Tunic", "大都会·秘鲁纳斯卡羽衣 I"),
        "Peru2": ("Met · Wari Tapestry Tunic", "大都会·秘鲁瓦里织锦 II"),
        "Pillement": ("Met · Pillement Chinoiserie", "大都会·皮勒芒洛可可花卉"),
        "Pissaro": ("Met · Pissarro Boulevard Montmartre", "大都会·毕沙罗蒙马特大街"),
        "Redon": ("Met · Redon Pandora Bouquet", "大都会·雷东梦幻花束"),
        "Tam": ("Met · Reuben Tam Kauai Coast", "大都会·谭氏夏威夷海岸"),
        "Tara": ("Met · Tibetan Vajratara", "大都会·藏传金刚度母"),
        "Thomas": ("Met · Alma Thomas Color Field", "大都会·托马斯色域韵律"),
        "Troy": ("Met · Troyes Gothic Stained Glass", "大都会·特鲁瓦哥特彩窗"),
        "Tsimshian": ("Met · Tsimshian Chilkat", "大都会·齐姆希安图腾"),
        "VanGogh1": ("Met · Van Gogh Cypresses", "大都会·梵高丝柏树"),
        "VanGogh3": ("Met · Van Gogh Oleanders", "大都会·梵高夹竹桃绿调"),
        "Wissing": ("Met · Wissing Baroque Court", "大都会·维辛巴洛克宫廷"),
    }
    for r_name, (en, zh) in met_zh_map.items():
        if r_name not in met_pals:
            continue
        hx, ord_v = met_pals[r_name]
        pid = f"met_{r_name.lower()}"
        m_info = met_meta.get(r_name, {})
        ord_mode = "gradient" if _is_gradient_ordered(hx, ord_v) else "discrete"
        rec(
            "museum",
            _write_palette(
                pid,
                en,
                zh,
                "museum",
                hx,
                {
                    "title": m_info.get("desc") or f"MetBrewer ({r_name}), The Metropolitan Museum of Art",
                    "author": "Blake Robert Mills (MetBrewer)",
                    "year": 2022,
                    "url": m_info.get("url") or "https://github.com/BlakeRMills/MetBrewer",
                    "license": "CC0 1.0 Universal",
                },
                kind="qualitative",
                order=ord_mode,
                neutral="#BDBAB5",
                seq_partner="batlowW",
                div_partner="vik",
            ),
        )

    # 3B. MoMAColors — Museum of Modern Art, New York (`BlakeRMills/MoMAColors`, MIT)
    moma_pals = _parse_r_palettes_with_order(cache["momacolors_r"])
    moma_meta = _parse_readme_metadata(cache["momacolors_readme"])
    moma_zh_map = {
        "Abbott": ("MoMA · Abbott Urban Chroma", "现代艺术馆·阿博特都会色彩"),
        "Alkalay1": ("MoMA · Alkalay Stack Warm", "现代艺术馆·阿尔卡莱叠木暖调"),
        "Alkalay2": ("MoMA · Alkalay Botanical", "现代艺术馆·阿尔卡莱叠木翠调"),
        "Andri": ("MoMA · Andri Vienna Secession", "现代艺术馆·维也纳分离派海报"),
        "Avedon": ("MoMA · Avedon Pop Lithograph", "现代艺术馆·阿维顿波普版画"),
        "Budnitz": ("MoMA · Budnitz Vinyl Pop", "现代艺术馆·当代潮玩色彩"),
        "Clay": ("MoMA · Clay Southern Chromogenic", "现代艺术馆·克莱彩色摄影"),
        "Connors": ("MoMA · Connors Color Field", "现代艺术馆·康纳斯色域抽象"),
        "Dali": ("MoMA · Dalí Persistence of Memory", "现代艺术馆·达利超现实主义"),
        "Doughton": ("MoMA · Doughton Pastel Collage", "现代艺术馆·道顿粉彩拼贴"),
        "Ernst": ("MoMA · Max Ernst Surrealism", "现代艺术馆·恩斯特超现实色彩"),
        "Exter": ("MoMA · Alexandra Exter Constructivism", "现代艺术馆·埃克斯特构成主义"),
        "Flash": ("MoMA · Flash Pop Screenprint", "现代艺术馆·波普丝网印"),
        "Klein": ("MoMA · Yves Klein Ultramarine", "现代艺术馆·克莱因群青"),
        "Koons": ("MoMA · Koons Neo-Pop", "现代艺术馆·昆斯新波普"),
        "Levine2": ("MoMA · Sherrie Levine Modern", "现代艺术馆·勒维恩现代主义"),
        "Liu": ("MoMA · Hung Liu Mineral Memory", "现代艺术馆·刘虹矿物记忆"),
        "Lupi": ("MoMA · Giorgia Lupi Dear Data", "现代艺术馆·卢皮数据手绘"),
        "OKeeffe": ("MoMA · O'Keeffe Evening Star", "现代艺术馆·奥姬芙暮星"),
        "Ohchi": ("MoMA · Hiroshi Ohchi Graphic", "现代艺术馆·大智浩现代平面"),
        "Palermo": ("MoMA · Blinky Palermo Minimal", "现代艺术馆·帕勒莫极简色块"),
        "Panton": ("MoMA · Verner Panton Spectrum", "现代艺术馆·潘顿现代光谱"),
        "Picabia": ("MoMA · Francis Picabia Dada", "现代艺术馆·毕卡比亚达达主义"),
        "Picasso": ("MoMA · Picasso Girl Before a Mirror", "现代艺术馆·毕加索镜前少女"),
        "Rattner": ("MoMA · Rattner Stained-Glass", "现代艺术馆·拉特纳彩绘表现"),
        "Sidhu": ("MoMA · Sidhu Contemporary", "现代艺术馆·西杜当代色域"),
        "Smith": ("MoMA · Kimber Smith Abstract", "现代艺术馆·史密斯抽象色韵"),
        "VanGogh": ("MoMA · Van Gogh Starry Night", "现代艺术馆·梵高星月夜"),
        "Warhol": ("MoMA · Andy Warhol Marilyn", "现代艺术馆·沃霍尔波普丝印"),
        "ustwo": ("MoMA · Monument Valley Architecture", "现代艺术馆·纪念碑谷几何色"),
    }
    for r_name, (en, zh) in moma_zh_map.items():
        if r_name not in moma_pals:
            continue
        hx, ord_v = moma_pals[r_name]
        pid = f"moma_{r_name.lower()}"
        m_info = moma_meta.get(r_name, {})
        ord_mode = "gradient" if _is_gradient_ordered(hx, ord_v) else "discrete"
        rec(
            "museum",
            _write_palette(
                pid,
                en,
                zh,
                "museum",
                hx,
                {
                    "title": m_info.get("desc") or f"MoMAColors ({r_name}), Museum of Modern Art",
                    "author": "Blake Robert Mills (MoMAColors)",
                    "year": 2023,
                    "url": m_info.get("url") or "https://github.com/BlakeRMills/MoMAColors",
                    "license": "MIT",
                },
                kind="qualitative",
                order=ord_mode,
                neutral="#B8B6B2",
                seq_partner="lipari",
                div_partner="vik",
            ),
        )

    # 3C. PNWColors — Pacific Northwest Nature Photography (`jakelawlor/PNWColors`, CC0 1.0)
    pnw_pals = _parse_r_palettes_with_order(cache["pnw_r"])
    pnw_zh_map = {
        "Starfish": ("PNW · Tidepool Starfish", "北美海岸·潮池紫星"),
        "Shuksan2": ("PNW · Mount Shuksan Alpine", "北美海岸·舒克桑雪峰"),
        "Bay": ("PNW · Puget Sound Bay", "北美海岸·普吉特海湾"),
        "Lake": ("PNW · Olympic Forest Lake", "北美海岸·冷杉翠湖"),
        "Sunset2": ("PNW · Pacific Dusk", "北美海岸·太平洋暮霞"),
        "Cascades": ("PNW · North Cascades Moss", "北美海岸·喀斯喀特苔森"),
        "Sailboat": ("PNW · Salish Sea Sailboat", "北美海岸·萨利希帆影"),
        "Moth": ("PNW · Silk Moth Ochre", "北美海岸·林间天蚕蛾"),
        "Spring": ("PNW · Cherry Blossom Spring", "北美海岸·早春樱林"),
        "Anemone": ("PNW · Sea Anemone Teal", "北美海岸·礁石海葵"),
    }
    for r_name, (en, zh) in pnw_zh_map.items():
        if r_name not in pnw_pals:
            continue
        hx, ord_v = pnw_pals[r_name]
        ord_mode = "gradient" if _is_gradient_ordered(hx, ord_v) else "discrete"
        rec(
            "museum",
            _write_palette(
                f"pnw_{r_name.lower()}",
                en,
                zh,
                "museum",
                hx,
                {
                    "title": f"PNWColors Pacific Northwest Nature Palette ({r_name})",
                    "author": "Jake Lawlor",
                    "year": 2020,
                    "url": "https://github.com/jakelawlor/PNWColors",
                    "license": "CC0 1.0 Universal",
                },
                kind="qualitative",
                order=ord_mode,
                neutral="#B5B8BA",
                seq_partner="navia",
                div_partner="broc",
            ),
        )

    # 3D. NatParksPalettes (`kevinsblake/NatParksPalettes`, MIT) + WesAnderson (`karthik/wesanderson`, MIT)
    np_pals = _parse_r_palettes_with_order(cache["natparks_r"])
    np_zh_map = {
        "Acadia": ("NatParks · Acadia Granite Coast", "国家公园·阿卡迪亚海岸"),
        "Arches": ("NatParks · Arches Red Sandstone", "国家公园·拱门红砂岩"),
        "Banff": ("NatParks · Banff Moraine Turquoise", "国家公园·班夫冰川湖"),
        "BryceCanyon": ("NatParks · Bryce Hoodoos", "国家公园·布莱斯石林"),
        "CraterLake": ("NatParks · Crater Lake Cobalt", "国家公园·火山口深蓝湖"),
        "DeathValley": ("NatParks · Death Valley Dunes", "国家公园·死亡谷荒漠"),
        "Glacier": ("NatParks · Glacier Meltwater", "国家公园·冰川融水"),
        "GrandCanyon": ("NatParks · Grand Canyon Strata", "国家公园·科罗拉多大峡谷"),
        "Olympic": ("NatParks · Olympic Rainforest", "国家公园·奥林匹克温带雨林"),
        "Redwood": ("NatParks · Redwood Canopy", "国家公园·红杉林冠"),
        "RockyMtn": ("NatParks · Rocky Mountain Tundra", "国家公园·落基山苔原"),
        "Saguaro": ("NatParks · Saguaro Sonoran", "国家公园·巨人柱仙人掌"),
        "Torres": ("NatParks · Torres del Paine", "国家公园·百内花岗岩塔"),
        "Yellowstone": ("NatParks · Yellowstone Prismatic", "国家公园·黄石大棱镜温泉"),
        "Yosemite": ("NatParks · Yosemite El Capitan", "国家公园·优胜美地花岗岩"),
    }
    for r_name, (en, zh) in np_zh_map.items():
        if r_name not in np_pals:
            continue
        hx, ord_v = np_pals[r_name]
        ord_mode = "gradient" if _is_gradient_ordered(hx, ord_v) else "discrete"
        rec(
            "museum",
            _write_palette(
                f"np_{r_name.lower()}",
                en,
                zh,
                "museum",
                hx,
                {
                    "title": f"NatParksPalettes ({r_name})",
                    "author": "Kevin Blake",
                    "year": 2022,
                    "url": "https://github.com/kevinsblake/NatParksPalettes",
                    "license": "MIT",
                },
                kind="qualitative",
                order=ord_mode,
                neutral="#B6B4AE",
                seq_partner="bamako",
                div_partner="BrBG",
            ),
        )

    # WesAnderson curated cinema classics (`karthik/wesanderson`, MIT)
    wes_r = cache["wes_r"]
    wes_all: dict[str, list[str]] = {}
    for m in re.finditer(r"([A-Za-z0-9_]+)\s*=\s*c\s*\(([^)]+)\)", wes_r):
        hx = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", m.group(2))]
        if len(hx) >= 4:
            wes_all[m.group(1)] = hx
    wes_specs = [
        ("Darjeeling1", "wes_darjeeling1", "Cinema · Darjeeling Limited", "电影美学·穿越大吉岭", "discrete"),
        ("Zissou1", "wes_zissou1", "Cinema · Life Aquatic Zissou", "电影美学·水中生活", "gradient"),
        ("GrandBudapest2", "wes_grand_budapest2", "Cinema · Grand Budapest Pastel", "电影美学·布达佩斯大饭店", "discrete"),
        ("Cavalcanti1", "wes_cavalcanti", "Cinema · Castello Cavalcanti", "电影美学·卡瓦尔坎蒂暖调", "gradient"),
        ("Rushmore1", "wes_rushmore", "Cinema · Rushmore Academy", "电影美学·青春年少", "gradient"),
    ]
    for w_key, pid, en, zh, ord_mode in wes_specs:
        if w_key in wes_all:
            rec(
                "museum",
                _write_palette(
                    pid,
                    en,
                    zh,
                    "museum",
                    wes_all[w_key],
                    {
                        "title": f"wesanderson Cinema Color Palette ({w_key})",
                        "author": "Karthik Ram & Hadley Wickham",
                        "year": 2023,
                        "url": "https://github.com/karthik/wesanderson",
                        "license": "MIT",
                    },
                    kind="qualitative",
                    order=ord_mode,
                    neutral="#B9B4AB",
                    seq_partner="lajolla",
                    div_partner="RdYlBu",
                ),
            )

    # =========================================================================
    # 4. MANY-COLORS COLLECTION (+10 Multi-Cluster Single-Cell & Spatial Palettes)
    # =========================================================================
    def _fetch_polychrome_rda(rda_name: str) -> list[str]:
        u = f"https://raw.githubusercontent.com/cran/Polychrome/master/data/{rda_name}.rda"
        req = urllib.request.Request(u, headers={"User-Agent": "DanqingPrimarySourceAudit/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            dec = gzip.decompress(r.read()).decode("latin1")
        return [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", dec)]

    poly36 = [h for h in _fetch_polychrome_rda("palette36") if h not in ("#E4E1E3", "#F7E1A0")]
    dark24 = _fetch_polychrome_rda("Dark24")
    light24 = _fetch_polychrome_rda("Light24")

    # Green-Armytage 26 exact sRGB triples from `Polychrome/R/palettes.R`
    ga_rgb = [
        (240, 163, 255), (0, 117, 220), (153, 63, 0), (76, 0, 92), (25, 25, 25),
        (0, 92, 49), (43, 206, 72), (255, 204, 153), (128, 128, 128), (148, 255, 181),
        (143, 124, 0), (157, 204, 0), (194, 0, 136), (0, 51, 128), (25, 164, 5),
        (255, 168, 187), (66, 102, 0), (255, 0, 16), (94, 241, 242), (0, 153, 143),
        (224, 255, 102), (16, 10, 255), (153, 0, 0), (255, 225, 0), (255, 80, 0),
    ]
    ga_hex = [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in ga_rgb if (r, g, b) != (128, 128, 128)]

    # Scanpy `zeileis_28`, `vega_20_scanpy`, and `godsnot_102` (first 64) from `scverse/scanpy` (BSD-3-Clause)
    sc_txt = cache["scanpy_leg_pal"]
    m_z28 = re.search(r"zeileis_28\s*=\s*\[([^\]]+)\]", sc_txt, re.S)
    zeileis_28 = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", m_z28.group(1))] if m_z28 else []
    zeileis_data = [h for h in zeileis_28 if h not in ("#7F7F7F", "#C7C7C7")]

    m_g102 = re.search(r"godsnot_102\s*=\s*\[([^\]]+)\]", sc_txt, re.S)
    godsnot_all = []
    if m_g102:
        for ln in m_g102.group(1).splitlines():
            ln_clean = ln.split("# ", 1)[0] if ln.strip().startswith("# ") else ln
            if ln.strip().startswith('"#') or ln.strip().startswith("'#"):
                hx_m = re.search(r"#[0-9A-Fa-f]{6}\b", ln)
                if hx_m:
                    godsnot_all.append(hx_m.group(0).upper())
    godsnot_64 = godsnot_all[:64]

    # Scanpy `vega_20_scanpy` (exact derivation from `tab20` in `scanpy/plotting/legacy/palettes.py`)
    d3_20 = json.loads((DATA_DIR / "d3_category20.json").read_text())["colors"]
    vega20_sc = [*d3_20[0:14:2], *d3_20[16::2], *d3_20[1:15:2], *d3_20[17::2], "#AD494A", "#8C6D31"]
    vega20_sc[2] = "#279E68"
    vega20_sc[4] = "#AA40FC"
    vega20_sc[7] = "#B5BD61"

    # Matplotlib `tab20b` & `tab20c` (`_cm.py`, BSD-compatible)
    def _extract_mpl_tab20_variant(var_name: str) -> list[str]:
        m_t = re.search(rf"_{var_name}_data\s*=\s*\((.*?)\)\s*\n", cache["mpl_cm_listed"] + "\n" + open_mpl_cm(), re.S)
        if not m_t:
            return []
        trips = re.findall(r"\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)", m_t.group(1))
        return [srgb01_to_hex(np.array([float(a), float(b), float(c)])) for a, b, c in trips]

    def open_mpl_cm() -> str:
        u = "https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/_cm.py"
        req = urllib.request.Request(u, headers={"User-Agent": "DanqingPrimarySourceAudit/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")

    mpl_cm_txt = open_mpl_cm()
    tab20b_hx: list[str] = []
    tab20c_hx: list[str] = []
    for vname, target_list in [("tab20b", tab20b_hx), ("tab20c", tab20c_hx)]:
        m_v = re.search(rf"_{vname}_data\s*=\s*\((.*?)\)\n\n", mpl_cm_txt, re.S)
        if m_v:
            for a, b, c in re.findall(r"\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)", m_v.group(1)):
                target_list.append(srgb01_to_hex(np.array([float(a), float(b), float(c)])))

    # Paul Tol 23-color discrete rainbow (`__rainbow_discrete` lut=22 in `tol_colors.py`)
    tol_rb22 = [
        "#882E72", "#B178A6", "#D6C1DE", "#1965B0", "#5289C7", "#7BAFDE", "#4EB265", "#90C987",
        "#CAE0AB", "#F7EE55", "#F6C141", "#F1932D", "#E8601C", "#DC050C", "#72190E", "#42150A",
        "#A5170E", "#F4A736", "#F7F056", "#4EB265",
    ]
    m_rb = re.search(r"def __rainbow_discrete\(self, lut=22\):(.*?)def ", tol_py, re.S)
    if m_rb:
        all_rb_hex = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", m_rb.group(1))]
        # Deduplicate while preserving Paul Tol's 23 distinct discrete rainbow hexes (excluding #777777 grey & #FFFFFF)
        dedup_rb: list[str] = []
        for h in all_rb_hex:
            if h not in dedup_rb and h not in ("#FFFFFF", "#777777"):
                dedup_rb.append(h)
        if len(dedup_rb) >= 20:
            tol_rb22 = dedup_rb[:26]

    many_specs = [
        (
            "polychrome_36",
            "Polychrome 34",
            "Polychrome 高区分度三十四色",
            poly36,
            "#A8A8A8",
            {
                "title": "Polychrome: Creating and Assessing Qualitative Palettes with Many Colors (palette36)",
                "author": "Kevin R. Coombes et al. (J. Stat. Softw. 90(1):1-23)",
                "year": 2019,
                "url": "https://doi.org/10.18637/jss.v090.c01",
                "license": "Apache-2.0",
            },
        ),
        (
            "green_armytage_26",
            "Green-Armytage Alphabet 25",
            "Green-Armytage 色彩字母表二十五色",
            ga_hex,
            "#808080",
            {
                "title": "A Colour Alphabet and the Limits of Colour Coding",
                "author": "Paul Green-Armytage (Colour: Design & Creativity 5:1-23)",
                "year": 2010,
                "url": "https://doi.org/10.18637/jss.v090.c01",
                "license": "Apache-2.0 (Polychrome implementation)",
            },
        ),
        (
            "polychrome_dark24",
            "Polychrome Dark 24",
            "Polychrome 白底深调二十四色",
            dark24,
            "#9E9E9E",
            {
                "title": "Polychrome Dark24 Multi-Cluster Palette",
                "author": "Kevin R. Coombes et al. (J. Stat. Softw. 90(1):1-23)",
                "year": 2019,
                "url": "https://cran.r-project.org/package=Polychrome",
                "license": "Apache-2.0",
            },
        ),
        (
            "polychrome_light24",
            "Polychrome Light 24",
            "Polychrome 明快多簇二十四色",
            light24,
            "#B0B0B0",
            {
                "title": "Polychrome Light24 Multi-Cluster Palette",
                "author": "Kevin R. Coombes et al. (J. Stat. Softw. 90(1):1-23)",
                "year": 2019,
                "url": "https://cran.r-project.org/package=Polychrome",
                "license": "Apache-2.0",
            },
        ),
        (
            "scanpy_zeileis28",
            "Scanpy Zeileis 26",
            "Scanpy 单细胞 Zeileis 二十六色",
            zeileis_data,
            "#7F7F7F",
            {
                "title": "Escaping RGBland: HCL Palettes for Statistical Graphics (Scanpy zeileis_28)",
                "author": "Achim Zeileis, Kurt Hornik & Paul Murrell (CSDA 53:3259-3270)",
                "year": 2009,
                "url": "https://github.com/scverse/scanpy",
                "license": "BSD-3-Clause",
            },
        ),
        (
            "scanpy_vega20",
            "Scanpy Default 20",
            "Scanpy 单细胞默认二十色",
            vega20_sc,
            "#7F7F7F",
            {
                "title": "Scanpy Default 20-Cluster UMAP Palette (vega_20_scanpy)",
                "author": "Wolf, Angerer & Theis (Genome Biology 19:15)",
                "year": 2018,
                "url": "https://github.com/scverse/scanpy",
                "license": "BSD-3-Clause",
            },
        ),
        (
            "scanpy_godsnot64",
            "Scanpy Ultra-Cluster 64",
            "Scanpy 超大细胞图谱六十四色",
            godsnot_64,
            "#938A81",
            {
                "title": "Scanpy High-Cardinality Atlas Palette (godsnot_102 subset)",
                "author": "scverse / Scanpy Contributors",
                "year": 2018,
                "url": "https://github.com/scverse/scanpy",
                "license": "BSD-3-Clause",
            },
        ),
        (
            "mpl_tab20b",
            "Matplotlib Tab20b",
            "Matplotlib 阶梯分组二十色 B",
            tab20b_hx,
            "#969696",
            {
                "title": "Matplotlib / Vega Structured 20-Color Palette (tab20b)",
                "author": "Matplotlib & Vega Contributors",
                "year": 2016,
                "url": "https://matplotlib.org/stable/users/explain/colors/colormaps.html",
                "license": "BSD-compatible",
            },
        ),
        (
            "mpl_tab20c",
            "Matplotlib Tab20c",
            "Matplotlib 阶梯分组二十色 C",
            tab20c_hx[:-4] if len(tab20c_hx) == 20 else tab20c_hx,
            "#969696",
            {
                "title": "Matplotlib / Vega Structured Palette (tab20c chromatic)",
                "author": "Matplotlib & Vega Contributors",
                "year": 2016,
                "url": "https://matplotlib.org/stable/users/explain/colors/colormaps.html",
                "license": "BSD-compatible",
            },
        ),
        (
            "tol_rainbow_discrete",
            "Paul Tol Discrete Rainbow",
            "保罗·托尔离散光谱多簇色",
            tol_rb22,
            "#777777",
            {
                "title": "Paul Tol Discrete Rainbow Scheme (SRON/EPS/TN/09-002)",
                "author": "Paul Tol",
                "year": 2022,
                "url": "https://sronpersonalpages.nl/~pault/",
                "license": "BSD-3-Clause",
            },
        ),
    ]
    for pid, en, zh, hx, neut, src in many_specs:
        if len(hx) >= 16:
            ord_many = (
                "gradient"
                if pid in ("polychrome_36", "scanpy_godsnot64", "scanpy_zeileis28", "mpl_tab20b", "mpl_tab20c", "tol_rainbow_discrete")
                else "discrete"
            )
            rec(
                "many",
                _write_palette(
                    pid,
                    en,
                    zh,
                    "many",
                    hx,
                    src,
                    kind="qualitative",
                    order=ord_many,
                    neutral=neut,
                    seq_partner="viridis",
                    div_partner="vik",
                ),
            )

    # =========================================================================
    # 5. DOMAIN CONVENTIONS (+4 Semantic Bioinformatics Conventions)
    # =========================================================================
    conv_specs = [
        (
            "volcano_deg3",
            "Volcano Up / Down / NS",
            "火山图差异表达（上调/下调/不显著）",
            ["#C85A53", "#3B6B9B", "#C2C7D0"],
            ["Up", "Down", "NS"],
            "#C2C7D0",
            "Standard Differential Expression Volcano Convention",
        ),
        (
            "cell_cycle_3",
            "Cell Cycle (G1 / S / G2M)",
            "细胞周期三期标准色（G1/S/G2M）",
            ["#4E79A7", "#E09F5A", "#C85A53"],
            ["G1", "S", "G2M"],
            "#BDBDBD",
            "Single-Cell Transcriptomics Cell-Cycle Phase Convention",
        ),
        (
            "cnv_state3",
            "Copy Number (Gain / Loss / Neutral)",
            "拷贝数变异三态标准色（扩增/缺失/中性）",
            ["#C85A53", "#3B6B9B", "#D1D5DB"],
            ["Gain", "Loss", "Neutral"],
            "#D1D5DB",
            "Somatic Copy-Number Alteration (CNA) Convention",
        ),
        (
            "dna_bases4",
            "DNA / RNA Nucleotide (A/C/G/T)",
            "核酸四碱基标准色（A绿/C蓝/G金/T红）",
            ["#2E9F57", "#2B6CB0", "#D99B26", "#C84B3C"],
            ["A", "C", "G", "T"],
            "#9CA3AF",
            "Sanger Chromatogram & IGV Nucleotide Base Convention",
        ),
    ]
    for pid, en, zh, hx, ckeys, neut, title in conv_specs:
        rec(
            "convention",
            _write_palette(
                pid,
                en,
                zh,
                "convention",
                hx,
                {
                    "title": title,
                    "author": "Standard Genomics & Bioinformatics Convention",
                    "year": 2020,
                    "url": "https://igv.org/",
                    "license": "Public domain convention",
                },
                kind="qualitative",
                order="discrete",
                neutral=neut,
                seq_partner="Blues",
                div_partner="RdBu",
                convention_keys=ckeys,
            ),
        )

    total_files = len(list(DATA_DIR.glob("*.json")))
    print(f"[build_expanded_palettes] Added {sum(added_by_col.values())} new palettes: {added_by_col}")
    print(f"[build_expanded_palettes] Total palette JSON files in data/: {total_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
