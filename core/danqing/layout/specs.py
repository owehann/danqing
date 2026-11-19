"""Physical journal specifications (1-col / 1.5-col / 2-col / 3-col across CNS & major journals) and font metrics."""

from __future__ import annotations

from dataclasses import dataclass

MM_TO_PT: float = 72.0 / 25.4
PT_TO_MM: float = 25.4 / 72.0
PX_PER_MM_WEB: float = 96.0 / 25.4


def mm_to_pt(mm: float) -> float:
    return mm * MM_TO_PT


def pt_to_mm(pt: float) -> float:
    return pt * PT_TO_MM


@dataclass(frozen=True)
class JournalSpec:
    id: str
    family_id: str
    tier_id: str  # "1col" | "mid" | "full" | "custom"
    name: str
    name_zh: str
    width_mm: float
    max_height_mm: float
    tag_case: str  # "lower" (a, b, c) or "upper" (A, B, C)
    tag_pt: float
    title_pt: float
    axis_title_pt: float
    tick_pt: float
    annotation_pt: float
    min_allowed_pt: float
    max_allowed_pt: float
    axis_stroke_pt: float
    data_stroke_pt: float
    grid_stroke_pt: float
    min_stroke_pt: float
    default_font: str
    min_raster_dpi: int

    @property
    def double_col_mm(self) -> float:
        """Backward-compatible alias returning active canvas width in mm."""
        return self.width_mm


def _mk_family_tiers(
    family_id: str,
    family_en: str,
    family_zh: str,
    tiers: list[tuple[str, str, str, float, float]],
    tag_case: str,
    tag_pt: float,
    title_pt: float,
    axis_pt: float,
    tick_pt: float,
    ann_pt: float,
    axis_sw: float,
    data_sw: float,
    font: str = "Arial",
) -> list[JournalSpec]:
    out: list[JournalSpec] = []
    for spec_id, tier_id, tier_label_en, w_mm, h_mm in tiers:
        out.append(
            JournalSpec(
                id=spec_id,
                family_id=family_id,
                tier_id=tier_id,
                name=f"{family_en} · {tier_label_en} ({w_mm:.0f} mm)",
                name_zh=f"{family_zh} · {tier_label_en} ({w_mm:.0f} mm)",
                width_mm=w_mm,
                max_height_mm=h_mm,
                tag_case=tag_case,
                tag_pt=tag_pt,
                title_pt=title_pt,
                axis_title_pt=axis_pt,
                tick_pt=tick_pt,
                annotation_pt=ann_pt,
                min_allowed_pt=5.0,
                max_allowed_pt=9.5,
                axis_stroke_pt=axis_sw,
                data_stroke_pt=data_sw,
                grid_stroke_pt=0.30,
                min_stroke_pt=0.25,
                default_font=font,
                min_raster_dpi=300,
            )
        )
    return out


_ALL_SPECS_LIST: list[JournalSpec] = [
    # 1. Nature Portfolio (89 / 136 / 183 mm, lowercase bold a-l)
    *_mk_family_tiers(
        "nature",
        "Nature Portfolio",
        "Nature 系列",
        [
            ("nature_1col", "1col", "1-Col", 89.0, 185.0),
            ("nature_mid", "mid", "1.5-Col", 136.0, 215.0),
            ("nature_double", "full", "2-Col Full", 183.0, 225.0),
        ],
        tag_case="lower",
        tag_pt=8.0,
        title_pt=6.8,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.65,
        font="Arial",
    ),
    # 2. Science / AAAS (3-column system: 55 / 120 / 183 mm, uppercase bold A-L)
    *_mk_family_tiers(
        "science",
        "Science / AAAS",
        "Science 系列",
        [
            ("science_1col", "1col", "1-Col", 55.0, 180.0),
            ("science_2col", "mid", "2-Col", 120.0, 210.0),
            ("science_3col", "full", "3-Col Full", 183.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.5,
        title_pt=7.0,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.65,
        font="Helvetica",
    ),
    # 3. Cell Press (85 / 114 / 174 mm, uppercase bold A-L)
    *_mk_family_tiers(
        "cell",
        "Cell Press",
        "Cell 系列",
        [
            ("cell_1col", "1col", "1-Col", 85.0, 185.0),
            ("cell_mid", "mid", "1.5-Col", 114.0, 210.0),
            ("cell_double", "full", "2-Col Full", 174.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.5,
        title_pt=7.0,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.8,
        axis_sw=0.55,
        data_sw=0.70,
        font="Arial",
    ),
    # 4. NEJM / JAMA Clinical (84 / 130 / 178 mm)
    *_mk_family_tiers(
        "nejm",
        "NEJM / JAMA",
        "NEJM · JAMA 临床",
        [
            ("nejm_1col", "1col", "1-Col", 84.0, 185.0),
            ("nejm_mid", "mid", "1.5-Col", 130.0, 210.0),
            ("nejm_clinical", "full", "2-Col Full", 178.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.5,
        title_pt=7.0,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.70,
        font="Arial",
    ),
    # 5. The Lancet (75 / 154 / 180 mm)
    *_mk_family_tiers(
        "lancet",
        "The Lancet",
        "Lancet 柳叶刀系列",
        [
            ("lancet_1col", "1col", "1-Col", 75.0, 185.0),
            ("lancet_mid", "mid", "2-Col Std", 154.0, 215.0),
            ("lancet_full", "full", "Full Page", 180.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.5,
        title_pt=7.0,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.65,
        font="Arial",
    ),
    # 6. Gut / J. Hepatol. / Hepatology (86 / 132 / 176 mm)
    *_mk_family_tiers(
        "hepatology",
        "Gut / J. Hepatol.",
        "Gut · J. Hepatol.",
        [
            ("hep_1col", "1col", "1-Col", 86.0, 185.0),
            ("hep_mid", "mid", "1.5-Col", 132.0, 210.0),
            ("hep_full", "full", "2-Col Full", 176.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.5,
        title_pt=7.0,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.65,
        font="Arial",
    ),
    # 7. Cancer Discovery / JCO / AACR (85 / 115 / 175 mm)
    *_mk_family_tiers(
        "oncology",
        "Cancer Discov. / JCO",
        "Cancer Discov. · JCO",
        [
            ("onco_1col", "1col", "1-Col", 85.0, 185.0),
            ("onco_mid", "mid", "1.5-Col", 115.0, 210.0),
            ("onco_full", "full", "2-Col Full", 175.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.5,
        title_pt=7.0,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.65,
        font="Arial",
    ),
    # 8. PNAS (87 / 114 / 178 mm)
    *_mk_family_tiers(
        "pnas",
        "PNAS",
        "PNAS 院刊",
        [
            ("pnas_1col", "1col", "1-Col", 87.0, 185.0),
            ("pnas_mid", "mid", "1.5-Col", 114.0, 210.0),
            ("pnas_full", "full", "2-Col Full", 178.0, 220.0),
        ],
        tag_case="upper",
        tag_pt=8.0,
        title_pt=6.8,
        axis_pt=6.5,
        tick_pt=6.0,
        ann_pt=5.6,
        axis_sw=0.50,
        data_sw=0.65,
        font="Helvetica",
    ),
    # 9. Custom Physical Canvas
    JournalSpec(
        id="custom_canvas",
        family_id="custom",
        tier_id="custom",
        name="Custom Canvas (mm)",
        name_zh="自定义物理版心 (mm)",
        width_mm=180.0,
        max_height_mm=225.0,
        tag_case="upper",
        tag_pt=8.0,
        title_pt=6.8,
        axis_title_pt=6.5,
        tick_pt=6.0,
        annotation_pt=5.6,
        min_allowed_pt=5.0,
        max_allowed_pt=9.5,
        axis_stroke_pt=0.50,
        data_stroke_pt=0.65,
        grid_stroke_pt=0.30,
        min_stroke_pt=0.25,
        default_font="Arial",
        min_raster_dpi=300,
    ),
]

JOURNAL_SPECS: dict[str, JournalSpec] = {s.id: s for s in _ALL_SPECS_LIST}

JOURNAL_FAMILIES: list[dict[str, object]] = [
    {
        "family_id": fid,
        "specs": [s.id for s in _ALL_SPECS_LIST if s.family_id == fid],
    }
    for fid in ("nature", "science", "cell", "nejm", "lancet", "hepatology", "oncology", "pnas", "custom")
]

FONT_FAMILIES: dict[str, str] = {
    "Arial": "Arial, Helvetica, sans-serif",
    "Helvetica": "Helvetica, Arial, sans-serif",
    "Helvetica Neue": "'Helvetica Neue', Helvetica, Arial, sans-serif",
    "Calibri": "Calibri, Carlito, Arial, sans-serif",
    "Times New Roman": "'Times New Roman', Times, Georgia, serif",
}

_CHAR_EM_WIDTH: dict[str, float] = {
    " ": 0.28,
    "i": 0.23,
    "l": 0.23,
    "I": 0.28,
    "j": 0.23,
    "t": 0.28,
    "f": 0.28,
    "r": 0.33,
    ".": 0.28,
    ",": 0.28,
    ":": 0.28,
    ";": 0.28,
    "-": 0.33,
    "(": 0.33,
    ")": 0.33,
    "1": 0.52,
    "m": 0.83,
    "w": 0.72,
    "M": 0.83,
    "W": 0.94,
    "%": 0.89,
    "+": 0.58,
    "=": 0.58,
    "<": 0.58,
    ">": 0.58,
}


def measure_text_mm(text: str, font_pt: float, bold: bool = False, font_family: str = "Arial") -> tuple[float, float]:
    """Return physical (width_mm, cap_height_mm) of a string at exact `font_pt`."""
    if not text:
        return (0.0, pt_to_mm(font_pt * 0.72))
    em_sum = 0.0
    for ch in text:
        if ord(ch) > 0x2E80:
            em_sum += 1.0
        elif ch in _CHAR_EM_WIDTH:
            em_sum += _CHAR_EM_WIDTH[ch]
        elif ch.isupper():
            em_sum += 0.68
        elif ch.isdigit():
            em_sum += 0.56
        else:
            em_sum += 0.53
    if bold:
        em_sum *= 1.06
    if "Times" in font_family:
        em_sum *= 0.93
    width_pt = em_sum * font_pt
    cap_height_pt = font_pt * 0.73
    return (pt_to_mm(width_pt), pt_to_mm(cap_height_pt))
