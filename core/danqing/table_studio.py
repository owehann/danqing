"""Danqing Table Studio v2 — Deterministic Tabular Parser, Numeric Spec & Native Exporters.

Implements:
1. RawSnapshot ingestion (CSV / TSV / Semicolon / European decimal-comma / Multi-sheet XLSX
   with merged 2-row spanning headers, title-row & footer-row detection, uncached formula
   audit, HTML <table> colspan/rowspan paste, and Danqing rule-JSON round-trip).
2. Shared deterministic number parser (`parse_number`) verified against
   `core/danqing/table_numeric_spec.json`.
3. Submission-grade native `.xlsx` (`openpyxl` with `CellRichText` superscripts, spanner
   merges, true float/int cells + `numFmt`, `Original: <from>` cell comments, frozen headers,
   auto column widths, `fitToWidth=1`, and raw unmerged `data` worksheet), `.docx`
   (`python-docx` three-line borders, `gridSpan` spanners, `<w:tblHeader/>`, `<w:cantSplit/>`,
   superscripts), and `.zip` (`table.json` + `data.csv` + runnable `great_tables` `make_table.py`).
"""

from __future__ import annotations

import csv
import hashlib
import html as html_std
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import openpyxl
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import html as lxml_html
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from danqing.table_compute import (
    classify_narrative_roles,
    detect_smart_compute,
    infer_enhanced_merges,
    infer_flat_header_spanners,
    infer_sig_bindings,
)

ColumnRole = Literal["normal", "count", "part", "heat", "sig", "bar"]

_MISSING_TOKENS = {
    "",
    "-",
    "—",
    "–",
    "NA",
    "N/A",
    "na",
    "n/a",
    "nan",
    "NaN",
    "null",
    "NULL",
}

_PART_HEADER_HINTS = {
    "part",
    "section",
    "group",
    "species",
    "arm",
    "cohort",
    "type",
    "category",
    "block",
    "module",
    "domain",
    "stratum",
    "分组",
    "组别",
    "类别",
    "分块",
    "模块",
    "板块",
}

_PIVOT_COL_HINTS = {
    "species",
    "group",
    "arm",
    "cohort",
    "treatment",
    "condition",
    "分组",
    "组别",
}

_SIG_EXACT_HINTS = {"p", "q", "fdr", "pval", "padj"}
_SIG_SUBSTR_HINTS = (
    "p-value",
    "p_value",
    "p value",
    "pvalue",
    "p_val",
    "p-val",
    "pval",
    "p_adj",
    "padj",
    "fdr",
    "q-value",
    "q_value",
    "qval",
    "adj.p",
    "显著性",
    "p值",
)

_COUNT_EXACT_HINTS = {
    "count",
    "counts",
    "n",
    "sample_size",
    "samples",
    "样本量",
    "例数",
    "人数",
}

_NON_HEAT_HINTS = (
    "id",
    "index",
    "rank",
    "age",
    "编号",
    "序号",
)

_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_EURO_DECIMAL_LIKE_RE = re.compile(
    r"^[<>≤≥\s]*\(?[-+−]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d+(?:[eE][-+]?\d+)?\)?\s*%?$"
)
_ANY_NUM_LIKE_RE = re.compile(
    r"^[<>≤≥\s]*\(?[-+−]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?(?:[eE][-+]?\d+)?\)?\s*%?$"
)
_STD_THOUSANDS_RE = re.compile(r"^[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
_EURO_THOUSANDS_RE = re.compile(r"^[-+]?\d{1,3}(?:\.\d{3})+,\d+(?:[eE][-+]?\d+)?$")
_PLAIN_FLOAT_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_SEMI_PIPE_SEQ_RE = re.compile(
    r"^\s*[-+]?\d*\.?\d+(?:\s*[;|/]\s*[-+]?\d*\.?\d+){2,}\s*$"
)
_TRAILING_STARS_RE = re.compile(r"^([<>≤≥\s]*[-+−]?\d[\d.,eE+-]*%?)\*{1,4}$")
_FOOTER_START_RE = re.compile(r"^(?:[a-zA-Z*†‡§#]|Note\b|Notes\b|注[:：\s]|说明[:：\s])")


class TableParseError(ValueError):
    """Structured parse error carrying an i18n error_key for the frontend."""

    def __init__(self, error_key: str, detail: str = "") -> None:
        super().__init__(detail or error_key)
        self.error_key = error_key
        self.detail = detail


@dataclass(frozen=True)
class ParsedNumber:
    value: float | None
    prefix: str = ""
    unit: str = ""
    p_text: str | None = None
    is_sequence: bool = False


def parse_number(raw: str, decimal_comma: bool = False) -> ParsedNumber:
    """Deterministically parse a tabular string into numeric components (WP T2/T4).

    Verified against `core/danqing/table_numeric_spec.json`.
    """
    s = raw.strip()
    if s in _MISSING_TOKENS:
        return ParsedNumber(None, "", "", None, False)

    if s.lower() in ("n.s.", "ns"):
        return ParsedNumber(None, "", "", "n.s.", False)

    # Normalize Unicode minus
    s_norm = s.replace("\u2212", "-")

    # Sequence check 1: semicolon / pipe / slash separated >= 3 numbers
    if _SEMI_PIPE_SEQ_RE.match(s_norm):
        return ParsedNumber(None, "", "", None, True)

    # Sequence check 2: comma-separated sequence (only when comma is NOT decimal separator)
    if not decimal_comma and "," in s_norm:
        if not _STD_THOUSANDS_RE.match(s_norm.rstrip("% ").lstrip("<>≤≥+ ")):
            parts = [p.strip() for p in s_norm.split(",")]
            if len(parts) >= 2 and all(_PLAIN_FLOAT_RE.match(p) for p in parts):
                return ParsedNumber(None, "", "", None, True)

    work = s_norm
    prefix = ""
    for pfx in ("<=", ">=", "≤", "≥", "<", ">"):
        if work.startswith(pfx):
            prefix = pfx
            work = work[len(pfx) :].strip()
            break

    neg_paren = False
    if work.startswith("(") and work.endswith(")") and len(work) > 2:
        neg_paren = True
        work = work[1:-1].strip()

    unit = ""
    if work.endswith("%"):
        unit = "%"
        work = work[:-1].strip()

    if not work:
        return ParsedNumber(None, "", "", None, False)

    cleaned: str | None = None
    if decimal_comma:
        if _EURO_THOUSANDS_RE.match(work):
            cleaned = work.replace(".", "").replace(",", ".")
        elif "," in work and "." not in work:
            cand = work.replace(",", ".")
            if _PLAIN_FLOAT_RE.match(cand):
                cleaned = cand
        elif _PLAIN_FLOAT_RE.match(work):
            cleaned = work
    else:
        if _STD_THOUSANDS_RE.match(work):
            cleaned = work.replace(",", "")
        elif "," not in work and _PLAIN_FLOAT_RE.match(work):
            cleaned = work

    if cleaned is None:
        return ParsedNumber(None, "", "", None, False)

    try:
        num = float(cleaned)
    except ValueError:
        return ParsedNumber(None, "", "", None, False)

    if math.isnan(num) or math.isinf(num):
        return ParsedNumber(None, "", "", None, False)

    if neg_paren:
        num = -abs(num)

    return ParsedNumber(num, prefix, unit, None, False)


@dataclass
class RawSnapshotData:
    snapshot_id: str
    source: dict[str, Any]
    grid: list[list[str]]
    cell_merges: list[dict[str, int]]
    warnings: list[dict[str, Any]]
    suggestions: dict[str, Any]
    sheets_meta: list[dict[str, Any]] = field(default_factory=list)
    column_stats: list[dict[str, Any]] = field(default_factory=list)
    restored_rules: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "grid": self.grid,
            "cell_merges": self.cell_merges,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "sheets_meta": self.sheets_meta,
            "column_stats": self.column_stats,
        }
        if self.restored_rules is not None:
            out["restored_rules"] = self.restored_rules
        return out


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _non_empty_indices(row: list[str]) -> list[int]:
    return [i for i, c in enumerate(row) if c.strip() != ""]


def _decode_text_bytes(raw: bytes) -> str:
    if not raw:
        raise TableParseError("tableStudio.errors.emptyFile")
    # UTF-16 BOM support
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise TableParseError("tableStudio.errors.decodeFailed", str(exc)) from exc
    # Reject binary payloads masquerading as CSV/TSV (e.g. PNG/PDF/ZIP renamed .csv)
    if b"\x00" in raw[:4096]:
        raise TableParseError("tableStudio.errors.decodeFailed", "Binary null bytes in text input")
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise TableParseError("tableStudio.errors.decodeFailed")


def _detect_delimiter(text: str) -> str:
    first_non_empty = ""
    for line in text.splitlines():
        if line.strip():
            first_non_empty = line
            break
    if not first_non_empty:
        return ","
    tab_cnt = first_non_empty.count("\t")
    semi_cnt = first_non_empty.count(";")
    comma_cnt = first_non_empty.count(",")
    if tab_cnt >= 1 and tab_cnt >= max(semi_cnt, comma_cnt):
        return "\t"
    if semi_cnt > comma_cnt and semi_cnt >= 1:
        return ";"
    sample = "\n".join(text.splitlines()[:25])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _detect_decimal_comma(
    grid: list[list[str]],
    body_start: int,
    body_end: int,
    delimiter: str,
) -> tuple[bool, float]:
    if delimiter == ",":
        return False, 0.0
    euro_hits = 0
    num_like = 0
    for r in range(body_start, body_end + 1):
        if r < 0 or r >= len(grid):
            continue
        for cell in grid[r]:
            s = cell.strip()
            if not s or s in _MISSING_TOKENS:
                continue
            if _ANY_NUM_LIKE_RE.match(s):
                num_like += 1
                if _EURO_DECIMAL_LIKE_RE.match(s):
                    euro_hits += 1
    if num_like >= 2 and (euro_hits / num_like) >= 0.60:
        return True, euro_hits / num_like
    return False, 0.0


def _locate_regions_and_headers(
    grid: list[list[str]],
    cell_merges: list[dict[str, int]],
    warnings: list[dict[str, Any]],
) -> tuple[tuple[int, int], tuple[int, int], str | None, list[str], list[dict[str, Any]], list[str]]:
    n_rows = len(grid)
    n_cols = len(grid[0]) if n_rows else 0
    if n_rows == 0 or n_cols == 0:
        raise TableParseError("tableStudio.errors.emptyFile")

    # Check if there are rows with >= 2 non-empty cells
    multi_cell_rows = [r for r in range(n_rows) if len(_non_empty_indices(grid[r])) >= 2]
    non_empty_rows = [r for r in range(n_rows) if len(_non_empty_indices(grid[r])) >= 1]
    if not non_empty_rows:
        raise TableParseError("tableStudio.errors.emptyFile")

    title_candidate: str | None = None
    if multi_cell_rows:
        h0 = multi_cell_rows[0]
        skipped_titles = 0
        for r in range(0, h0):
            idxs = _non_empty_indices(grid[r])
            if len(idxs) == 1:
                skipped_titles += 1
                if title_candidate is None:
                    title_candidate = grid[r][idxs[0]].strip()
        if skipped_titles > 0:
            warnings.append({"code": "TITLE_ROWS_SKIPPED", "detail": {"rows": h0}})
    else:
        # 1-column table fallback: require at least 2 non-empty rows (1 header + >=1 data)
        if len(non_empty_rows) < 2:
            raise TableParseError("tableStudio.errors.noDataRows")
        h0 = non_empty_rows[0]

    # Detect 2-level spanning header at h0..h0+1
    header_rows: tuple[int, int] = (h0, h0)
    spanners: list[dict[str, Any]] = []

    if h0 + 1 < n_rows and len(_non_empty_indices(grid[h0 + 1])) >= 2:
        # Must still leave at least 1 non-empty data row after h0 + 1
        has_data_below = any(len(_non_empty_indices(grid[r])) >= 1 for r in range(h0 + 2, n_rows))
        if has_data_below:
            horiz_merges_h0 = [
                m
                for m in cell_merges
                if m["r0"] <= h0 <= m["r1"] and m["c1"] > m["c0"]
            ]
            empty_h0 = sum(1 for c in grid[h0] if c.strip() == "")
            non_empty_h1 = sum(1 for c in grid[h0 + 1] if c.strip() != "")
            cond_merged = len(horiz_merges_h0) > 0
            cond_sparse_top = empty_h0 > (n_cols / 2.0) and non_empty_h1 == n_cols
            if cond_merged or cond_sparse_top:
                header_rows = (h0, h0 + 1)

    if header_rows[0] == header_rows[1]:
        raw_headers = [
            grid[h0][c].strip() or f"Col {c + 1}" for c in range(n_cols)
        ]
    else:
        top_row = [c.strip() for c in grid[h0]]
        bot_row = [c.strip() for c in grid[h0 + 1]]
        top_expanded = list(top_row)
        # Expand horizontal merges on h0
        used_span_cols: set[int] = set()
        for m in sorted(cell_merges, key=lambda x: x["c0"]):
            if m["r0"] <= h0 <= m["r1"] and m["c1"] > m["c0"]:
                lbl = top_row[m["c0"]]
                if lbl:
                    cols_span = list(range(m["c0"], min(m["c1"] + 1, n_cols)))
                    for c in cols_span:
                        top_expanded[c] = lbl
                        used_span_cols.add(c)
                    if len(cols_span) >= 2:
                        spanners.append({"label": lbl, "source_cols": cols_span})

        # Also group identical consecutive top labels (>=2 cols) if not from xlsx merge
        c = 0
        while c < n_cols:
            if c in used_span_cols or not top_expanded[c]:
                c += 1
                continue
            j = c + 1
            while j < n_cols and j not in used_span_cols and top_expanded[j] == top_expanded[c]:
                j += 1
            if j - c >= 2:
                spanners.append(
                    {"label": top_expanded[c], "source_cols": list(range(c, j))}
                )
            c = j

        raw_headers = []
        for c in range(n_cols):
            t_lbl = top_expanded[c]
            b_lbl = bot_row[c]
            if t_lbl and b_lbl and t_lbl != b_lbl:
                raw_headers.append(f"{t_lbl} · {b_lbl}")
            elif b_lbl:
                raw_headers.append(b_lbl)
            elif t_lbl:
                raw_headers.append(t_lbl)
            else:
                raw_headers.append(f"Col {c + 1}")

    # Deduplicate headers (D7)
    seen_counts: dict[str, int] = {}
    dedup_headers: list[str] = []
    dup_total = 0
    for h in raw_headers:
        cnt = seen_counts.get(h, 0) + 1
        seen_counts[h] = cnt
        if cnt == 1:
            dedup_headers.append(h)
        else:
            dup_total += 1
            dedup_headers.append(f"{h} ({cnt})")
    if dup_total > 0:
        warnings.append({"code": "DUPLICATE_HEADERS", "detail": {"count": dup_total}})

    # Scan footer rows upward from bottom (D2)
    footnotes: list[str] = []
    scan_end = n_rows - 1
    while scan_end > header_rows[1] and len(_non_empty_indices(grid[scan_end])) == 0:
        scan_end -= 1

    if n_cols >= 2:
        while scan_end > header_rows[1]:
            idxs = _non_empty_indices(grid[scan_end])
            if len(idxs) == 0:
                scan_end -= 1
                continue
            if idxs == [0]:
                candidate = grid[scan_end][0].strip()
                has_real_row_above = any(
                    len(_non_empty_indices(grid[r])) >= 2
                    for r in range(header_rows[1] + 1, scan_end)
                )
                if has_real_row_above and _FOOTER_START_RE.match(candidate):
                    footnotes.insert(0, candidate)
                    scan_end -= 1
                    continue
            break

    if footnotes:
        warnings.append({"code": "FOOTER_ROWS_DETECTED", "detail": {"count": len(footnotes)}})

    # Trim leading/trailing completely-blank rows from bodyRange
    body_start = header_rows[1] + 1
    while body_start <= scan_end and len(_non_empty_indices(grid[body_start])) == 0:
        body_start += 1
    body_end = scan_end
    while body_end >= body_start and len(_non_empty_indices(grid[body_end])) == 0:
        body_end -= 1

    if body_start > body_end:
        raise TableParseError("tableStudio.errors.noDataRows")

    return header_rows, (body_start, body_end), title_candidate, footnotes, spanners, dedup_headers


def _leaf_header(label: str) -> str:
    return label.split(" · ")[-1].strip()


def _span_prefix(label: str) -> str:
    parts = label.split(" · ")
    return " · ".join(parts[:-1]).strip() if len(parts) > 1 else ""


def _infer_suggestions_and_stats(
    grid: list[list[str]],
    header_rows: tuple[int, int],
    body_range: tuple[int, int],
    title_candidate: str | None,
    footnote_candidates: list[str],
    spanners: list[dict[str, Any]],
    headers: list[str],
    decimal_comma: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    n_cols = len(headers)
    body_rows = [
        grid[r]
        for r in range(body_range[0], body_range[1] + 1)
        if len(_non_empty_indices(grid[r])) > 0
    ]

    # 1. Per-column numeric statistics & unit detection
    col_stats: list[dict[str, Any]] = []
    parsed_matrix: list[list[ParsedNumber]] = [
        [parse_number(row[c], decimal_comma=decimal_comma) for row in body_rows]
        for c in range(n_cols)
    ]

    for c in range(n_cols):
        col_cells = [row[c].strip() for row in body_rows]
        non_empty = [v for v in col_cells if v not in _MISSING_TOKENS]
        pnums = parsed_matrix[c]
        num_vals = [p.value for p in pnums if p.value is not None]
        seq_hits = sum(1 for p in pnums if p.is_sequence)
        ns_hits = sum(1 for p in pnums if p.p_text is not None)
        denom = len(non_empty)
        numeric_ratio = ((len(num_vals) + ns_hits) / denom) if denom > 0 else 0.0

        pct_hits = sum(1 for p in pnums if p.value is not None and p.unit == "%")
        detected_unit = "%" if (len(num_vals) >= 2 and pct_hits / len(num_vals) >= 0.75) else ""
        is_all_int = len(num_vals) > 0 and all(abs(v - round(v)) < 1e-9 for v in num_vals)

        col_stats.append(
            {
                "col": c,
                "name": headers[c],
                "numeric_ratio": round(numeric_ratio, 4),
                "min_val": min(num_vals) if num_vals else None,
                "max_val": max(num_vals) if num_vals else None,
                "detected_unit": detected_unit,
                "seq_ratio": (seq_hits / denom) if denom > 0 else 0.0,
                "is_all_int": is_all_int,
            }
        )

    # 2. Layer 1A & 1B: Token-Tree flat-header spanners + mathematical-invariant merges
    spanners, leaf_headers = infer_flat_header_spanners(headers, spanners, header_rows)
    merges, merged_member_cols, pct_promoted_cols = infer_enhanced_merges(
        headers, leaf_headers, spanners, parsed_matrix, col_stats
    )
    for pc in pct_promoted_cols:
        col_stats[pc]["detected_unit"] = "%"

    # 3. Sparkline runs across >= 4 adjacent year columns
    sparkline_runs: list[dict[str, Any]] = []
    c = 0
    while c < n_cols:
        leaf = _leaf_header(headers[c])
        if _YEAR_RE.match(leaf) and col_stats[c]["numeric_ratio"] >= 0.6:
            j = c + 1
            while (
                j < n_cols
                and _YEAR_RE.match(_leaf_header(headers[j]))
                and col_stats[j]["numeric_ratio"] >= 0.6
            ):
                j += 1
            if j - c >= 4:
                first_yr = _leaf_header(headers[c])
                last_yr = _leaf_header(headers[j - 1])
                sparkline_runs.append(
                    {
                        "source_cols": list(range(c, j)),
                        "label": f"{first_yr}–{last_yr}",
                    }
                )
            c = j
        else:
            c += 1

    # 4. Part / Block column suggestion (D6: text col in first 3 cols, cardinality 2..12 with repeats)
    part_by: int | None = None
    best_part_score = -1
    n_body = len(body_rows)
    for c in range(min(3, n_cols)):
        if col_stats[c]["numeric_ratio"] >= 0.2:
            continue
        vals = [row[c].strip() for row in body_rows if row[c].strip() not in _MISSING_TOKENS]
        if len(vals) < 2:
            continue
        uniq = set(vals)
        k = len(uniq)
        has_repeat = len(vals) > k
        leaf_low = _leaf_header(headers[c]).lower()
        name_hit = leaf_low in _PART_HEADER_HINTS or any(h in leaf_low for h in ("分组", "组别", "分块", "板块"))
        if 2 <= k <= 12 and has_repeat:
            score = (10 if name_hit else 1) + (5 if c == 0 else 0)
            if score > best_part_score:
                best_part_score = score
                part_by = c

    # 5. Long-format Pivot suggestion (D6b + retain_row_cols + col_counts)
    pivot_suggestion: dict[str, Any] | None = None
    text_candidates = [
        c
        for c in range(min(3, n_cols))
        if col_stats[c]["numeric_ratio"] < 0.2
    ]
    if len(text_candidates) >= 2 and n_body >= 4:
        c0, c1 = text_candidates[0], text_candidates[1]
        valid_pairs = [
            (r[c0].strip(), r[c1].strip(), r_idx)
            for r_idx, r in enumerate(body_rows)
            if r[c0].strip() not in _MISSING_TOKENS and r[c1].strip() not in _MISSING_TOKENS
        ]
        pair_set = {(a, b) for a, b, _ in valid_pairs}
        uniq0 = {a for a, _, _ in valid_pairs}
        uniq1 = {b for _, b, _ in valid_pairs}
        # True long-format requires BOTH dimensions to repeat (each < len(valid_pairs))
        if (
            len(valid_pairs) >= int(math.ceil(0.9 * n_body))
            and len(pair_set) == len(valid_pairs)
            and 2 <= len(uniq0) <= 12
            and 2 <= len(uniq1) < len(valid_pairs)
            and len(uniq0) < len(valid_pairs)
        ):
            l0 = _leaf_header(headers[c0]).lower()
            l1 = _leaf_header(headers[c1]).lower()
            if l1 in _PIVOT_COL_HINTS and l0 not in _PIVOT_COL_HINTS:
                col_key, row_key = c1, c0
            elif l0 in _PIVOT_COL_HINTS or len(uniq0) <= len(uniq1):
                col_key, row_key = c0, c1
            else:
                col_key, row_key = c1, c0

            if len({r[col_key].strip() for r in body_rows if r[col_key].strip()}) <= 12:
                other_cols = [
                    c for c in range(n_cols) if c not in (col_key, row_key)
                ]
                retain_row_cols: list[int] = []
                col_count_col: int | None = None
                col_counts: dict[str, str] = {}
                value_cols: list[int] = []

                for oc in other_cols:
                    oc_leaf = _leaf_header(headers[oc]).lower()
                    # Check if constant within each rowKey (e.g. omnibus p_value, ignoring missing tokens)
                    by_rk: dict[str, set[str]] = {}
                    for r in body_rows:
                        rk_val = r[row_key].strip()
                        oc_val = r[oc].strip()
                        by_rk.setdefault(rk_val, set())
                        if oc_val not in _MISSING_TOKENS:
                            by_rk[rk_val].add(oc_val)
                    is_row_const = all(len(vs) <= 1 for vs in by_rk.values()) and len(by_rk) >= 2

                    # Check if count column constant within each colKey (e.g. species sample size)
                    by_ck: dict[str, set[str]] = {}
                    for r in body_rows:
                        ck_val = r[col_key].strip()
                        oc_val = r[oc].strip()
                        if oc_val not in _MISSING_TOKENS:
                            by_ck.setdefault(ck_val, set()).add(oc_val)
                    is_col_const_count = (
                        oc_leaf in _COUNT_EXACT_HINTS
                        and col_stats[oc]["is_all_int"]
                        and len(by_ck) >= 2
                        and all(len(vs) == 1 for vs in by_ck.values())
                    )

                    if is_col_const_count and col_count_col is None:
                        col_count_col = oc
                        col_counts = {k: next(iter(vs)) for k, vs in by_ck.items()}
                    elif is_row_const:
                        retain_row_cols.append(oc)
                    elif col_stats[oc]["numeric_ratio"] >= 0.5:
                        value_cols.append(oc)

                if value_cols:
                    pivot_suggestion = {
                        "row_key": row_key,
                        "col_key": col_key,
                        "value_cols": value_cols,
                        "retain_row_cols": retain_row_cols,
                        "col_counts": col_counts,
                    }

    # 6. Layer 2 & 3: Five-tier narrative column roles, multi-scope sig bindings & raw-column smart compute
    roles_raw = classify_narrative_roles(
        headers=headers,
        leaf_headers=leaf_headers,
        col_stats=col_stats,
        part_by=part_by,
        merged_member_cols=merged_member_cols,
        sig_Substr_hints=_SIG_SUBSTR_HINTS,
        sig_exact_hints=_SIG_EXACT_HINTS,
        count_exact_hints=_COUNT_EXACT_HINTS,
    )
    roles: dict[str, ColumnRole] = {k: v for k, v in roles_raw.items()}  # type: ignore[misc]
    sig_bindings = infer_sig_bindings(
        headers=headers,
        leaf_headers=leaf_headers,
        roles=roles_raw,
        merges=merges,
        spanners=spanners,
        parsed_matrix=parsed_matrix,
    )
    smart_compute = detect_smart_compute(
        headers=headers,
        body_rows=body_rows,
        col_stats=col_stats,
        roles=roles_raw,
        pivot_suggestion=pivot_suggestion,
        sparkline_runs=sparkline_runs,
        merges=merges,
    )
    # Do not auto-propose `part_by` on wide raw patient cohorts (where `Group` is for Table 1 aggregation)
    if smart_compute is not None and smart_compute.get("kind") == "subject_table1":
        if part_by is not None and roles.get(str(part_by)) == "part":
            roles[str(part_by)] = "normal"
            col_stats[part_by]["role"] = "normal"
        part_by = None
        # Also suppress replicate/flat spanners when raw records are unaggregated subject rows
        spanners = []
        leaf_headers = [h.split(" · ")[-1].strip() for h in headers]

    suggestions = {
        "header_rows": [header_rows[0], header_rows[1]],
        "body_range": [body_range[0], body_range[1]],
        "title_candidate": title_candidate,
        "footnote_candidates": footnote_candidates,
        "spanners": spanners,
        "roles": roles,
        "merges": merges,
        "part_by": part_by,
        "sparkline_runs": sparkline_runs,
        "pivot": pivot_suggestion,
        "decimal_comma": decimal_comma,
        "resolved_headers": headers,
        "leaf_headers": leaf_headers,
        "sig_bindings": sig_bindings,
        "smart_compute": smart_compute,
    }
    return suggestions, col_stats


def _finalize_grid_and_build_snapshot(
    raw_rows: list[list[str]],
    *,
    filename: str,
    sheet: str,
    sheets: list[str],
    sheets_meta: list[dict[str, Any]],
    kind: Literal["csv", "tsv", "xlsx", "paste", "sample"],
    sha256_hex: str,
    delimiter: str,
    cell_merges: list[dict[str, int]] | None = None,
    pre_warnings: list[dict[str, Any]] | None = None,
    formula_matrix: list[list[str | None]] | None = None,
    restored_rules: dict[str, Any] | None = None,
) -> RawSnapshotData:
    warnings = list(pre_warnings or [])
    merges_list = list(cell_merges or [])

    non_empty_lengths = [len(r) for r in raw_rows if any(c.strip() != "" for c in r)]
    if not non_empty_lengths:
        raise TableParseError("tableStudio.errors.emptyFile")

    max_cols = max(non_empty_lengths)
    if max_cols == 0:
        raise TableParseError("tableStudio.errors.emptyFile")

    ragged_rows = sum(
        1 for r in raw_rows if any(c.strip() != "" for c in r) and len(r) != max_cols
    )
    if ragged_rows > 0:
        warnings.append({"code": "RAGGED_ROWS", "detail": {"rows": ragged_rows}})

    grid: list[list[str]] = []
    for r in raw_rows:
        padded = [c.strip() for c in r] + [""] * max(0, max_cols - len(r))
        grid.append(padded[:max_cols])

    header_rows, body_range, title_cand, footnotes, spanners, headers = _locate_regions_and_headers(
        grid, merges_list, warnings
    )

    # Check uncached Excel formulas in bodyRange (D3)
    if formula_matrix is not None:
        for c in range(max_cols):
            body_vals = [grid[r][c] for r in range(body_range[0], body_range[1] + 1)]
            body_fmls = [
                formula_matrix[r][c]
                if r < len(formula_matrix) and c < len(formula_matrix[r])
                else None
                for r in range(body_range[0], body_range[1] + 1)
            ]
            if all(v == "" for v in body_vals) and any(
                isinstance(f, str) and f.startswith("=") for f in body_fmls
            ):
                for r in range(body_range[0], body_range[1] + 1):
                    f_str = (
                        formula_matrix[r][c]
                        if r < len(formula_matrix) and c < len(formula_matrix[r])
                        else None
                    )
                    if isinstance(f_str, str) and f_str.startswith("="):
                        grid[r][c] = f_str
                warnings.append(
                    {
                        "code": "FORMULA_NO_CACHE",
                        "detail": {"column": headers[c], "col": c},
                    }
                )

    decimal_comma, dec_ratio = _detect_decimal_comma(
        grid, body_range[0], body_range[1], delimiter
    )
    if decimal_comma:
        warnings.append(
            {"code": "LOCALE_DECIMAL_COMMA", "detail": {"ratio": round(dec_ratio, 3)}}
        )

    suggestions, col_stats = _infer_suggestions_and_stats(
        grid=grid,
        header_rows=header_rows,
        body_range=body_range,
        title_candidate=title_cand,
        footnote_candidates=footnotes,
        spanners=spanners,
        headers=headers,
        decimal_comma=decimal_comma,
    )

    snap_id = f"tbl_{sha256_hex[:12]}_{sheet or 'main'}"
    return RawSnapshotData(
        snapshot_id=snap_id,
        source={
            "filename": filename,
            "sheet": sheet,
            "sheets": sheets,
            "kind": kind,
            "sha256": sha256_hex,
        },
        grid=grid,
        cell_merges=merges_list,
        warnings=warnings,
        suggestions=suggestions,
        sheets_meta=sheets_meta,
        column_stats=col_stats,
        restored_rules=restored_rules,
    )


def _format_excel_scalar(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return ""
        if val.is_integer() and abs(val) < 1e15:
            return str(int(val))
        return f"{val:.10g}"
    return str(val).strip()


def _sheet_has_data(ws_val: Any, ws_fml: Any) -> bool:
    non_empty_rows = 0
    max_non_empty_in_row = 0
    for r in range(1, (ws_val.max_row or 0) + 1):
        cnt = 0
        for c in range(1, (ws_val.max_column or 0) + 1):
            v = ws_val.cell(r, c).value
            f = ws_fml.cell(r, c).value
            if (v is not None and str(v).strip() != "") or (f is not None and str(f).strip() != ""):
                cnt += 1
        if cnt > 0:
            non_empty_rows += 1
            max_non_empty_in_row = max(max_non_empty_in_row, cnt)
    return non_empty_rows >= 2 or max_non_empty_in_row >= 2


def parse_tabular_bytes(
    raw_bytes: bytes,
    filename: str = "table.csv",
    sheet_name: str | None = None,
    kind_override: Literal["csv", "tsv", "xlsx", "paste", "sample"] | None = None,
) -> RawSnapshotData:
    if not raw_bytes:
        raise TableParseError("tableStudio.errors.emptyFile")

    sha256_hex = _sha256_bytes(raw_bytes)
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "csv"
    if ext not in ("csv", "tsv", "txt", "xlsx"):
        raise TableParseError("tableStudio.errors.unsupported", f"Unsupported extension .{ext}")

    if ext == "xlsx":
        try:
            wb_val = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
            wb_fml = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=False)
        except Exception as exc:
            raise TableParseError("tableStudio.errors.decodeFailed", str(exc)) from exc

        sheets = list(wb_val.sheetnames)
        if not sheets:
            raise TableParseError("tableStudio.errors.emptyFile")

        sheets_meta = [
            {"name": s, "empty": not _sheet_has_data(wb_val[s], wb_fml[s])}
            for s in sheets
        ]
        non_empty_sheets = [m["name"] for m in sheets_meta if not m["empty"]]

        if sheet_name and sheet_name in sheets:
            chosen = sheet_name
        elif non_empty_sheets:
            chosen = non_empty_sheets[0]
        else:
            raise TableParseError("tableStudio.errors.noDataRows")

        ws_v = wb_val[chosen]
        ws_f = wb_fml[chosen]
        pre_warnings: list[dict[str, Any]] = []
        if not _sheet_has_data(ws_v, ws_f):
            pre_warnings.append({"code": "EMPTY_SHEET", "detail": {"sheet": chosen}})
            raise TableParseError("tableStudio.errors.noDataRows")

        max_r = max(ws_v.max_row or 0, ws_f.max_row or 0)
        max_c = max(ws_v.max_column or 0, ws_f.max_column or 0)
        raw_rows: list[list[str]] = []
        fml_matrix: list[list[str | None]] = []
        for r in range(1, max_r + 1):
            row_v: list[str] = []
            row_f: list[str | None] = []
            for c in range(1, max_c + 1):
                val = ws_v.cell(r, c).value
                fml = ws_f.cell(r, c).value
                row_v.append(_format_excel_scalar(val))
                row_f.append(fml if isinstance(fml, str) and fml.startswith("=") else None)
            raw_rows.append(row_v)
            fml_matrix.append(row_f)

        cell_merges = [
            {
                "r0": rng.min_row - 1,
                "c0": rng.min_col - 1,
                "r1": rng.max_row - 1,
                "c1": rng.max_col - 1,
            }
            for rng in ws_v.merged_cells.ranges
        ]
        wb_val.close()
        wb_fml.close()

        return _finalize_grid_and_build_snapshot(
            raw_rows,
            filename=filename,
            sheet=chosen,
            sheets=sheets,
            sheets_meta=sheets_meta,
            kind=kind_override or "xlsx",
            sha256_hex=sha256_hex,
            delimiter="\t",
            cell_merges=cell_merges,
            pre_warnings=pre_warnings,
            formula_matrix=fml_matrix,
        )

    text = _decode_text_bytes(raw_bytes)
    delim = "\t" if ext == "tsv" else _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    raw_rows = list(reader)
    inferred_kind: Literal["csv", "tsv", "xlsx", "paste", "sample"] = (
        kind_override or ("tsv" if delim == "\t" else "csv")
    )
    return _finalize_grid_and_build_snapshot(
        raw_rows,
        filename=filename,
        sheet="Sheet1",
        sheets=["Sheet1"],
        sheets_meta=[{"name": "Sheet1", "empty": False}],
        kind=inferred_kind,
        sha256_hex=sha256_hex,
        delimiter=delim,
    )


def _extract_html_table(html_str: str) -> tuple[list[list[str]], list[dict[str, int]], dict[str, Any] | None]:
    doc = lxml_html.fromstring(html_str)
    tables = doc.xpath("//table")
    if not tables:
        raise TableParseError("tableStudio.errors.noDataRows")
    tbl = tables[0]
    restored_rules: dict[str, Any] | None = None
    rules_attr = tbl.get("data-danqing-rules")
    if rules_attr:
        try:
            restored_rules = json.loads(html_std.unescape(rules_attr))
        except Exception:
            restored_rules = None

    tr_nodes = tbl.xpath(".//tr")
    if not tr_nodes:
        raise TableParseError("tableStudio.errors.noDataRows")

    occupied: dict[tuple[int, int], bool] = {}
    grid_map: dict[tuple[int, int], str] = {}
    merges: list[dict[str, int]] = []
    max_col = 0

    for r_idx, tr in enumerate(tr_nodes):
        cells = tr.xpath("./th|./td")
        c_cursor = 0
        for cell in cells:
            while occupied.get((r_idx, c_cursor), False):
                c_cursor += 1
            try:
                colspan = max(1, int(cell.get("colspan") or "1"))
            except ValueError:
                colspan = 1
            try:
                rowspan = max(1, int(cell.get("rowspan") or "1"))
            except ValueError:
                rowspan = 1

            txt = " ".join(cell.text_content().split()).strip()
            m_star = _TRAILING_STARS_RE.match(txt)
            if m_star:
                txt = m_star.group(1).strip()

            grid_map[(r_idx, c_cursor)] = txt
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied[(r_idx + dr, c_cursor + dc)] = True
            if rowspan > 1 or colspan > 1:
                merges.append(
                    {
                        "r0": r_idx,
                        "c0": c_cursor,
                        "r1": r_idx + rowspan - 1,
                        "c1": c_cursor + colspan - 1,
                    }
                )
            c_cursor += colspan
            max_col = max(max_col, c_cursor)

    total_rows = max((r for r, _ in occupied.keys()), default=-1) + 1
    rows: list[list[str]] = []
    for r in range(total_rows):
        rows.append([grid_map.get((r, c), "") for c in range(max_col)])
    return rows, merges, restored_rules


def parse_tabular_paste(
    pasted_text: str | None = None,
    pasted_html: str | None = None,
    filename: str = "pasted_table.tsv",
) -> RawSnapshotData:
    if pasted_html and "<table" in pasted_html.lower():
        raw_bytes = pasted_html.encode("utf-8")
        rows, merges, restored = _extract_html_table(pasted_html)
        if restored and isinstance(restored.get("rawGrid"), list):
            rows = [[str(c) for c in r] for r in restored["rawGrid"]]
            merges = restored.get("cellMerges") or merges
        return _finalize_grid_and_build_snapshot(
            rows,
            filename=filename,
            sheet="Clipboard",
            sheets=["Clipboard"],
            sheets_meta=[{"name": "Clipboard", "empty": False}],
            kind="paste",
            sha256_hex=_sha256_bytes(raw_bytes),
            delimiter="\t",
            cell_merges=merges,
            restored_rules=restored,
        )

    if not pasted_text or not pasted_text.strip():
        raise TableParseError("tableStudio.errors.emptyFile")

    raw_bytes = pasted_text.encode("utf-8")
    lines = pasted_text.splitlines()
    has_hash_blocks = any(ln.strip().startswith("# ") for ln in lines[1:])
    non_hash_text = "\n".join(ln for ln in lines if not ln.strip().startswith("# "))
    delim = _detect_delimiter(non_hash_text or pasted_text)

    if has_hash_blocks:
        parsed_rows: list[list[str]] = []
        current_block = ""
        header_done = False
        for ln in lines:
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                current_block = stripped[2:].strip()
                continue
            row = next(csv.reader([ln], delimiter=delim))
            cleaned_row = []
            for cell in row:
                c_str = cell.strip()
                m_star = _TRAILING_STARS_RE.match(c_str)
                cleaned_row.append(m_star.group(1).strip() if m_star else c_str)
            if not header_done:
                parsed_rows.append(["Block", *cleaned_row])
                header_done = True
            else:
                parsed_rows.append([current_block, *cleaned_row])
    else:
        parsed_rows = []
        for row in csv.reader(io.StringIO(pasted_text), delimiter=delim):
            cleaned_row = []
            for cell in row:
                c_str = cell.strip()
                m_star = _TRAILING_STARS_RE.match(c_str)
                cleaned_row.append(m_star.group(1).strip() if m_star else c_str)
            parsed_rows.append(cleaned_row)

    return _finalize_grid_and_build_snapshot(
        parsed_rows,
        filename=filename,
        sheet="Clipboard",
        sheets=["Clipboard"],
        sheets_meta=[{"name": "Clipboard", "empty": False}],
        kind="paste",
        sha256_hex=_sha256_bytes(raw_bytes),
        delimiter=delim,
    )


def parse_tabular_text(text: str, filename: str = "pasted_table.tsv") -> RawSnapshotData:
    return parse_tabular_paste(pasted_text=text, pasted_html=None, filename=filename)


# ==============================================================================
# Native Styled Exporters (.xlsx, .docx, .zip with great_tables Python script)
# ==============================================================================


def _clean_hex6(hex_str: str | None, fallback: str = "FFFFFF") -> str:
    if not hex_str:
        return fallback
    h = hex_str.strip().lstrip("#").upper()
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return h[:6] if len(h) >= 6 else fallback


def _unicode_sparkbars(vals: list[float]) -> str:
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span <= 1e-12:
        return _SPARK_BLOCKS[3] * len(vals)
    out = []
    for v in vals:
        idx = int(round(((v - lo) / span) * (len(_SPARK_BLOCKS) - 1)))
        idx = max(0, min(len(_SPARK_BLOCKS) - 1, idx))
        out.append(_SPARK_BLOCKS[idx])
    return "".join(out)


_HBAR_EIGHTHS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")


def _unicode_hbar(ratio: float, max_chars: int = 6) -> str:
    clamped = max(0.0, min(1.0, float(ratio)))
    total_eighths = int(round(clamped * max_chars * 8))
    if total_eighths <= 0 and clamped > 0.0:
        total_eighths = 1
    full_blocks, rem = divmod(total_eighths, 8)
    return ("█" * full_blocks) + (_HBAR_EIGHTHS[rem] if rem > 0 else "")


def _excel_rich_text_with_sup(
    base_text: str,
    superscript: str,
    *,
    bold: bool = False,
    color_hex: str = "111827",
    base_sz: float = 10.0,
    bar_text: str = "",
    bar_color_hex: str = "2E6F95",
) -> CellRichText | str:
    sup = superscript.strip()
    if not sup and not bar_text:
        return base_text
    blocks: list[TextBlock | str] = [
        TextBlock(InlineFont(rFont="Arial", sz=base_sz, b=bold, color=color_hex), base_text)
    ]
    if sup:
        blocks.append(
            TextBlock(
                InlineFont(
                    rFont="Arial",
                    sz=max(7.5, base_sz - 2.0),
                    b=bold,
                    color=color_hex,
                    vertAlign="superscript",
                ),
                sup,
            )
        )
    if bar_text:
        blocks.append(
            TextBlock(
                InlineFont(rFont="Arial", sz=max(8.0, base_sz - 0.5), b=False, color=bar_color_hex),
                f"  {bar_text}",
            )
        )
    return CellRichText(*blocks)


def export_styled_xlsx(payload: dict[str, Any]) -> bytes:
    """Generate a native publication `.xlsx` workbook + raw `data` sheet via `openpyxl`."""
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Table"
    ws.views.sheetView[0].showGridLines = False

    # Print / PDF single-page-wide setup
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    headers: list[dict[str, Any]] = payload.get("headers") or []
    spanners: list[dict[str, Any]] = payload.get("spanners") or []
    blocks: list[dict[str, Any]] = payload.get("blocks") or []
    footnotes: list[dict[str, Any]] = payload.get("footnotes") or []
    raw_data_sheet: dict[str, Any] | None = payload.get("raw_data_sheet")
    preset: str = str(payload.get("preset") or "cns_three_line")
    title_str: str = str(payload.get("title") or "").strip()
    subtitle_str: str = str(payload.get("subtitle") or "").strip()

    n_cols = max(len(headers), 1)
    max_col_chars: list[int] = [max(8, len(str(h.get("label") or ""))) for h in headers] or [12]

    rule_heavy = Side(style="medium", color="111827")
    rule_mid = Side(style="thin", color="111827")
    rule_hair = Side(style="hair", color="CBD5E1")
    rule_box = Side(style="thin", color="1E293B")

    row_cursor = 1

    if title_str:
        c_title = ws.cell(row=row_cursor, column=1, value=title_str)
        c_title.font = Font(
            name="Georgia" if preset == "ft_editorial" else "Arial",
            size=12,
            bold=True,
            color="111827",
        )
        c_title.alignment = Alignment(horizontal="left", vertical="center")
        if n_cols > 1:
            ws.merge_cells(
                start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=n_cols
            )
        ws.row_dimensions[row_cursor].height = 24
        row_cursor += 1

    if subtitle_str:
        c_sub = ws.cell(row=row_cursor, column=1, value=subtitle_str)
        c_sub.font = Font(name="Arial", size=9.5, italic=True, color="475569")
        c_sub.alignment = Alignment(horizontal="left", vertical="center")
        if n_cols > 1:
            ws.merge_cells(
                start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=n_cols
            )
        ws.row_dimensions[row_cursor].height = 18
        row_cursor += 1

    top_header_row = row_cursor

    # Optional spanner row above leaf column headers
    if spanners:
        ws.row_dimensions[row_cursor].height = 22
        for c_idx in range(1, n_cols + 1):
            sc = ws.cell(row=row_cursor, column=c_idx, value="")
            sc.fill = PatternFill("solid", fgColor="FFFFFF")
            sc.border = Border(top=rule_heavy)

        for sp in spanners:
            c0 = int(sp.get("start_col", 0)) + 1
            c1 = int(sp.get("end_col", 0)) + 1
            if 1 <= c0 <= c1 <= n_cols:
                sp_lbl = str(sp.get("label") or "")
                sp_sup = str(sp.get("superscript") or "")
                top_cell = ws.cell(
                    row=row_cursor,
                    column=c0,
                    value=_excel_rich_text_with_sup(
                        sp_lbl, sp_sup, bold=True, color_hex="111827", base_sz=10.0
                    ),
                )
                top_cell.font = Font(name="Arial", size=10, bold=True, color="111827")
                top_cell.alignment = Alignment(horizontal="center", vertical="center")
                if c1 > c0:
                    ws.merge_cells(
                        start_row=row_cursor,
                        start_column=c0,
                        end_row=row_cursor,
                        end_column=c1,
                    )
                for k in range(c0, c1 + 1):
                    ws.cell(row=row_cursor, column=k).border = Border(
                        top=rule_heavy, bottom=rule_mid
                    )
        row_cursor += 1

    # Leaf header row
    header_row_idx = row_cursor
    ws.row_dimensions[header_row_idx].height = 24
    for c_idx, h in enumerate(headers, start=1):
        lbl = str(h.get("label") or "")
        sup = str(h.get("superscript") or "").strip()
        cell = ws.cell(
            row=header_row_idx,
            column=c_idx,
            value=_excel_rich_text_with_sup(
                lbl, sup, bold=True, color_hex="111827", base_sz=10.0
            ),
        )
        cell.font = Font(name="Arial", size=10, bold=True, color="111827")
        h_align = "left" if h.get("align") == "left" else "right"
        cell.alignment = Alignment(horizontal=h_align, vertical="center", wrap_text=True)
        cell.fill = PatternFill(
            "solid", fgColor="F8FAFC" if preset == "matrix_heatmap" else "FFFFFF"
        )
        existing_top = ws.cell(row=header_row_idx - 1, column=c_idx).border.bottom if spanners else None
        top_side = None if (spanners and existing_top and existing_top.style) else (None if spanners else rule_heavy)
        cell.border = Border(top=top_side, bottom=rule_mid)
    row_cursor += 1

    # Freeze panes below leaf header row and to the right of column A
    freeze_col = 2 if n_cols >= 2 else 1
    ws.freeze_panes = f"{get_column_letter(freeze_col)}{row_cursor}"
    _ = top_header_row

    total_data_rows = sum(len(b.get("rows") or []) for b in blocks)
    emitted_data_rows = 0
    numeric_bar_cells_by_col: dict[int, list[tuple[int, float, float, str]]] = {}

    for block in blocks:
        part_name = str(block.get("part_name") or "").strip()
        part_accent = _clean_hex6(block.get("part_accent"), "334155")
        b_rows: list[list[dict[str, Any]]] = block.get("rows") or []

        if part_name:
            p_cell = ws.cell(row=row_cursor, column=1, value=part_name)
            p_cell.font = Font(name="Arial", size=9.5, bold=True, color="1E293B")
            p_cell.alignment = Alignment(horizontal="left", vertical="center")
            if n_cols > 1:
                ws.merge_cells(
                    start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=n_cols
                )
            for c_i in range(1, n_cols + 1):
                mc = ws.cell(row=row_cursor, column=c_i)
                mc.fill = PatternFill("solid", fgColor="F1F5F9")
                mc.border = Border(
                    left=Side(style="thick", color=part_accent) if c_i == 1 else None,
                    top=rule_hair,
                    bottom=rule_hair,
                )
            ws.row_dimensions[row_cursor].height = 21
            row_cursor += 1

        for r_cells in b_rows:
            emitted_data_rows += 1
            is_last_row = emitted_data_rows == total_data_rows
            ws.row_dimensions[row_cursor].height = 20

            for c_idx in range(1, n_cols + 1):
                c_meta = r_cells[c_idx - 1] if c_idx - 1 < len(r_cells) else {}
                raw_num = c_meta.get("raw_number")
                num_fmt = str(c_meta.get("number_format") or "")
                txt = str(c_meta.get("text") or "")
                sup = str(c_meta.get("superscript") or "").strip()
                spark_vals = c_meta.get("sparkline_values")
                bar_spec = c_meta.get("bar_spec")
                edited_from = c_meta.get("edited_from")
                indent_lvl = int(c_meta.get("indent") or 0)
                col_hdr = headers[c_idx - 1] if c_idx - 1 < len(headers) else {}
                is_col_heat = col_hdr.get("effective_visual") == "heat"

                if isinstance(spark_vals, list) and len(spark_vals) >= 2:
                    bars = _unicode_sparkbars([float(v) for v in spark_vals])
                    txt = f"{bars}  {txt}".strip() if txt else bars

                bg_hex = _clean_hex6(c_meta.get("bg_hex"), "FFFFFF")
                fg_hex = _clean_hex6(c_meta.get("fg_hex"), "111827")
                is_bold = bool(c_meta.get("bold", False))
                box_border = bool(c_meta.get("box_border", False))
                align_h = "left" if c_meta.get("align") == "left" else "right"

                bar_ratio = 0.0
                bar_color_hex = "2E6F95"
                bar_is_neg = False
                bar_dom_min = 0.0
                bar_dom_max = 1.0
                has_bar_spec = isinstance(bar_spec, dict)
                if has_bar_spec:
                    bar_ratio = float(bar_spec.get("ratio") or 0.0)
                    bar_color_hex = _clean_hex6(bar_spec.get("fill_hex"), "2E6F95")
                    bar_is_neg = bool(bar_spec.get("is_negative", False))
                    bar_dom_min = float(bar_spec.get("domain_min") or 0.0)
                    bar_dom_max = float(bar_spec.get("domain_max") or 1.0)

                cell = ws.cell(row=row_cursor, column=c_idx)
                has_stars = "*" in txt or txt.startswith(("<", ">", "≤", "≥"))
                is_pure_numeric_cell = (
                    isinstance(raw_num, (int, float))
                    and not isinstance(raw_num, bool)
                    and not sup
                    and not spark_vals
                    and not has_stars
                )
                if is_pure_numeric_cell:
                    cell.value = int(raw_num) if (isinstance(raw_num, int) or (num_fmt == "0" and float(raw_num).is_integer())) else float(raw_num)
                    if num_fmt:
                        cell.number_format = num_fmt
                    if has_bar_spec:
                        numeric_bar_cells_by_col.setdefault(c_idx, []).append(
                            (row_cursor, bar_dom_min, bar_dom_max, bar_color_hex)
                        )
                else:
                    bar_glyph = ""
                    if has_bar_spec:
                        hbar = _unicode_hbar(bar_ratio, max_chars=6)
                        bar_glyph = f"◀{hbar}" if (bar_is_neg and hbar) else hbar
                    if sup or bar_glyph:
                        cell.value = _excel_rich_text_with_sup(
                            txt,
                            sup,
                            bold=is_bold,
                            color_hex=fg_hex,
                            base_sz=9.5,
                            bar_text=bar_glyph,
                            bar_color_hex=bar_color_hex,
                        )
                    else:
                        cell.value = txt

                cell.font = Font(name="Arial", size=9.5, bold=is_bold, color=fg_hex)
                cell.alignment = Alignment(
                    horizontal=align_h,
                    vertical="center",
                    indent=indent_lvl * 2 if align_h == "left" and indent_lvl > 0 else 0,
                )
                if bg_hex != "FFFFFF":
                    cell.fill = PatternFill("solid", fgColor=bg_hex)

                if edited_from is not None:
                    cell.comment = Comment(f"Original: {edited_from}", "Danqing Table Studio")

                white_gap = Side(style="thin", color="FFFFFF")
                if box_border:
                    cell.border = Border(
                        left=rule_box,
                        right=rule_box,
                        top=rule_box,
                        bottom=rule_heavy if is_last_row else rule_box,
                    )
                elif is_last_row:
                    if is_col_heat and bg_hex != "FFFFFF" and preset != "matrix_heatmap":
                        cell.border = Border(
                            left=white_gap, right=white_gap, top=white_gap, bottom=rule_heavy
                        )
                    else:
                        cell.border = Border(bottom=rule_heavy)
                elif preset == "matrix_heatmap" or (is_col_heat and bg_hex != "FFFFFF"):
                    cell.border = Border(
                        left=white_gap, right=white_gap, top=white_gap, bottom=white_gap
                    )

                extra_bar_chars = 8 if has_bar_spec else 0
                disp_len = len(txt) + len(sup) + indent_lvl * 2 + extra_bar_chars
                if c_idx - 1 < len(max_col_chars):
                    max_col_chars[c_idx - 1] = max(max_col_chars[c_idx - 1], disp_len)

            row_cursor += 1

    # Attach native Excel DataBar conditional formatting rules onto numeric bar columns
    for col_idx, entries in numeric_bar_cells_by_col.items():
        if not entries:
            continue
        col_letter = get_column_letter(col_idx)
        # Split into contiguous row spans (e.g. across Part banner rows)
        spans: list[list[tuple[int, float, float, str]]] = []
        for ent in entries:
            if not spans or ent[0] != spans[-1][-1][0] + 1:
                spans.append([ent])
            else:
                spans[-1].append(ent)
        for sp_entries in spans:
            r0 = sp_entries[0][0]
            r1 = sp_entries[-1][0]
            dom_lo = sp_entries[0][1]
            dom_hi = sp_entries[0][2]
            if dom_hi - dom_lo <= 1e-12:
                dom_hi = dom_lo + 1.0
            bar_hex = sp_entries[0][3]
            rule = DataBarRule(
                start_type="num",
                start_value=dom_lo,
                end_type="num",
                end_value=dom_hi,
                color=bar_hex,
                showValue=True,
            )
            ws.conditional_formatting.add(f"{col_letter}{r0}:{col_letter}{r1}", rule)

    # Footnotes below closing rule
    for fn in footnotes:
        sym = str(fn.get("symbol") or "").strip()
        ftxt = str(fn.get("text") or "").strip()
        if not ftxt:
            continue
        f_cell = ws.cell(row=row_cursor, column=1)
        if sym and sym not in ("*", "**", "***"):
            f_cell.value = _excel_rich_text_with_sup(
                "", sym, bold=False, color_hex="475569", base_sz=8.5
            )
            f_cell.value = CellRichText(
                TextBlock(
                    InlineFont(rFont="Arial", sz=7.5, color="475569", vertAlign="superscript"),
                    sym,
                ),
                TextBlock(InlineFont(rFont="Arial", sz=8.5, color="475569"), f" {ftxt}"),
            )
        else:
            line = f"{sym} {ftxt}".strip() if sym and not ftxt.startswith(sym) else ftxt
            f_cell.value = line
        f_cell.font = Font(name="Arial", size=8.5, color="475569")
        f_cell.alignment = Alignment(horizontal="left", vertical="center")
        if n_cols > 1:
            ws.merge_cells(
                start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=n_cols
            )
        ws.row_dimensions[row_cursor].height = 16
        row_cursor += 1

    # Auto-fit column widths based on max visible text length
    for c_idx in range(1, n_cols + 1):
        col_letter = get_column_letter(c_idx)
        char_w = max_col_chars[c_idx - 1] if c_idx - 1 < len(max_col_chars) else 12
        ws.column_dimensions[col_letter].width = min(max(char_w + 4, 10), 44)

    # Always write unmerged raw numeric `data` worksheet for downstream recalculation (§3.2)
    ws_data = wb.create_sheet(title="data")
    if raw_data_sheet and isinstance(raw_data_sheet.get("headers"), list):
        d_headers = [str(h) for h in raw_data_sheet["headers"]]
        ws_data.append(d_headers)
        for d_row in raw_data_sheet.get("rows") or []:
            parsed_d_row: list[Any] = []
            for item in d_row:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    parsed_d_row.append(item)
                elif item is None:
                    parsed_d_row.append("")
                else:
                    pn = parse_number(str(item), decimal_comma=False)
                    if pn.value is not None and pn.prefix == "" and not pn.is_sequence:
                        parsed_d_row.append(pn.value)
                    else:
                        parsed_d_row.append(str(item))
            ws_data.append(parsed_d_row)
    else:
        # Derive `data` sheet from blocks if raw_data_sheet not explicitly passed
        ws_data.append([str(h.get("label") or "") for h in headers])
        for block in blocks:
            for r_cells in block.get("rows") or []:
                d_row = []
                for c_meta in r_cells:
                    rn = c_meta.get("raw_number")
                    d_row.append(rn if isinstance(rn, (int, float)) else str(c_meta.get("text") or ""))
                ws_data.append(d_row)

    # Optional 3rd worksheet (`source_data`) preserving unaggregated raw subject/replicate observations
    source_data_sheet = payload.get("source_data_sheet")
    if isinstance(source_data_sheet, dict) and isinstance(source_data_sheet.get("headers"), list):
        ws_src = wb.create_sheet(title="source_data")
        ws_src.append([str(h) for h in source_data_sheet["headers"]])
        for s_row in source_data_sheet.get("rows") or []:
            parsed_s_row: list[Any] = []
            for item in s_row:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    parsed_s_row.append(item)
                elif item is None:
                    parsed_s_row.append("")
                else:
                    pn = parse_number(str(item), decimal_comma=False)
                    if pn.value is not None and pn.prefix == "" and pn.unit == "" and not pn.is_sequence:
                        parsed_s_row.append(pn.value)
                    else:
                        parsed_s_row.append(str(item))
            ws_src.append(parsed_s_row)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _set_docx_cell_shading(cell: Any, hex6: str) -> None:
    if hex6 == "FFFFFF":
        return
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex6)
    tc_pr.append(shd)


def _set_docx_cell_margins(
    cell: Any, top: int = 75, bottom: int = 75, left: int = 100, right: int = 100
) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for side_name, dxa in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side_name}")
        node.set(qn("w:w"), str(dxa))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tc_pr.append(tc_mar)


def _set_docx_cell_nowrap(cell: Any) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(OxmlElement("w:noWrap"))


def _set_docx_row_repeat_header(row: Any) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:tblHeader"))
    tr_pr.append(OxmlElement("w:cantSplit"))


def _set_docx_row_cant_split(row: Any) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def _set_docx_cell_borders(
    cell: Any,
    *,
    top: tuple[str, int, str] | None = None,
    bottom: tuple[str, int, str] | None = None,
    left: tuple[str, int, str] | None = None,
    right: tuple[str, int, str] | None = None,
) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge_name, spec in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        edge = OxmlElement(f"w:{edge_name}")
        if spec is None:
            edge.set(qn("w:val"), "nil")
        else:
            val, sz, color = spec
            edge.set(qn("w:val"), val)
            edge.set(qn("w:sz"), str(sz))
            edge.set(qn("w:space"), "0")
            edge.set(qn("w:color"), color)
        tc_borders.append(edge)
    tc_pr.append(tc_borders)


def _append_docx_run(
    paragraph: Any,
    text: str,
    *,
    font_size_pt: float,
    bold: bool = False,
    color_hex: str = "111827",
    superscript: str = "",
) -> None:
    rgb = RGBColor.from_string(color_hex)
    r_main = paragraph.add_run(text)
    r_main.bold = bold
    r_main.font.name = "Arial"
    r_main.font.size = Pt(font_size_pt)
    r_main.font.color.rgb = rgb
    if superscript:
        r_sup = paragraph.add_run(superscript)
        r_sup.bold = bold
        r_sup.font.superscript = True
        r_sup.font.name = "Arial"
        r_sup.font.size = Pt(max(7.0, font_size_pt - 1.0))
        r_sup.font.color.rgb = rgb


def export_styled_docx(payload: dict[str, Any]) -> bytes:
    """Generate a submission-grade Word `.docx` three-line table via `python-docx`."""
    doc = Document()
    headers: list[dict[str, Any]] = payload.get("headers") or []
    spanners: list[dict[str, Any]] = payload.get("spanners") or []
    blocks: list[dict[str, Any]] = payload.get("blocks") or []
    footnotes: list[dict[str, Any]] = payload.get("footnotes") or []
    title_str: str = str(payload.get("title") or "").strip()
    subtitle_str: str = str(payload.get("subtitle") or "").strip()

    n_cols = max(len(headers), 1)
    section = doc.sections[0]
    if n_cols > 6:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)

    body_pt = 9.0 if n_cols <= 6 else (8.2 if n_cols <= 10 else 7.5)

    if title_str:
        p_title = doc.add_paragraph()
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after = Pt(2 if subtitle_str else 6)
        _append_docx_run(p_title, title_str, font_size_pt=11.0, bold=True, color_hex="111827")

    if subtitle_str:
        p_sub = doc.add_paragraph()
        p_sub.paragraph_format.space_before = Pt(0)
        p_sub.paragraph_format.space_after = Pt(6)
        r_sub = p_sub.add_run(subtitle_str)
        r_sub.italic = True
        r_sub.font.name = "Arial"
        r_sub.font.size = Pt(9.0)
        r_sub.font.color.rgb = RGBColor.from_string("475569")

    spanner_rows_cnt = 1 if spanners else 0
    total_body_rows = sum(len(b.get("rows") or []) for b in blocks)
    part_banner_rows = sum(1 for b in blocks if str(b.get("part_name") or "").strip())
    total_tbl_rows = spanner_rows_cnt + 1 + part_banner_rows + total_body_rows

    table = doc.add_table(rows=total_tbl_rows, cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    # Strip default Word grid lines; apply explicit three-line rules per cell
    tbl_pr = table._tbl.tblPr
    tbl_borders = OxmlElement("w:tblBorders")
    for b_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{b_name}")
        el.set(qn("w:val"), "nil")
        tbl_borders.append(el)
    tbl_pr.append(tbl_borders)

    # sz is in eighths of a point: 12 = 1.5pt, 6 = 0.75pt, 4 = 0.5pt
    b_heavy = ("single", 12, "111827")
    b_mid = ("single", 6, "111827")
    b_span = ("single", 4, "111827")
    b_hair = ("single", 4, "CBD5E1")
    b_box = ("single", 6, "1E293B")

    r_ptr = 0

    if spanners:
        sp_row = table.rows[r_ptr]
        _set_docx_row_repeat_header(sp_row)
        spanned_cols: set[int] = set()
        for sp in spanners:
            c0 = int(sp.get("start_col", 0))
            c1 = int(sp.get("end_col", 0))
            if 0 <= c0 <= c1 < n_cols:
                for k in range(c0, c1 + 1):
                    spanned_cols.add(k)
                    _set_docx_cell_borders(sp_row.cells[k], top=b_heavy, bottom=b_span)
                    _set_docx_cell_margins(sp_row.cells[k], top=70, bottom=50)
                merged_sp = sp_row.cells[c0].merge(sp_row.cells[c1]) if c1 > c0 else sp_row.cells[c0]
                merged_sp.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                p = merged_sp.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                _append_docx_run(
                    p,
                    str(sp.get("label") or ""),
                    font_size_pt=body_pt,
                    bold=True,
                    color_hex="111827",
                    superscript=str(sp.get("superscript") or "").strip(),
                )
        for k in range(n_cols):
            if k not in spanned_cols:
                _set_docx_cell_borders(sp_row.cells[k], top=b_heavy, bottom=None)
                _set_docx_cell_margins(sp_row.cells[k], top=70, bottom=50)
        r_ptr += 1

    # Leaf header row
    hdr_row = table.rows[r_ptr]
    _set_docx_row_repeat_header(hdr_row)
    for c_idx, h in enumerate(headers):
        cell = hdr_row.cells[c_idx]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _set_docx_cell_margins(cell, top=80, bottom=80)
        _set_docx_cell_borders(
            cell,
            top=None if spanners else b_heavy,
            bottom=b_mid,
        )
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.alignment = (
            WD_ALIGN_PARAGRAPH.LEFT if h.get("align") == "left" else WD_ALIGN_PARAGRAPH.RIGHT
        )
        _append_docx_run(
            p,
            str(h.get("label") or ""),
            font_size_pt=body_pt,
            bold=True,
            color_hex="111827",
            superscript=str(h.get("superscript") or "").strip(),
        )
    r_ptr += 1

    emitted_body = 0
    for block in blocks:
        part_name = str(block.get("part_name") or "").strip()
        part_accent = _clean_hex6(block.get("part_accent"), "334155")
        b_rows: list[list[dict[str, Any]]] = block.get("rows") or []

        if part_name:
            p_row = table.rows[r_ptr]
            _set_docx_row_cant_split(p_row)
            first_c = p_row.cells[0]
            if n_cols > 1:
                first_c.merge(p_row.cells[n_cols - 1])
            _set_docx_cell_shading(first_c, "F1F5F9")
            _set_docx_cell_margins(first_c, top=65, bottom=65)
            _set_docx_cell_borders(
                first_c,
                top=b_hair,
                bottom=b_hair,
                left=("single", 18, part_accent),
            )
            p = first_c.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _append_docx_run(p, part_name, font_size_pt=body_pt, bold=True, color_hex="1E293B")
            r_ptr += 1

        for r_cells in b_rows:
            emitted_body += 1
            is_last = emitted_body == total_body_rows
            d_row = table.rows[r_ptr]
            _set_docx_row_cant_split(d_row)

            for c_idx in range(n_cols):
                c_meta = r_cells[c_idx] if c_idx < len(r_cells) else {}
                cell = d_row.cells[c_idx]
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                indent_lvl = int(c_meta.get("indent") or 0)
                _set_docx_cell_margins(
                    cell,
                    top=60,
                    bottom=60,
                    left=100 + indent_lvl * 180,
                    right=100,
                )

                bg_hex = _clean_hex6(c_meta.get("bg_hex"), "FFFFFF")
                fg_hex = _clean_hex6(c_meta.get("fg_hex"), "111827")
                is_bold = bool(c_meta.get("bold", False))
                box_border = bool(c_meta.get("box_border", False))
                no_wrap = bool(c_meta.get("no_wrap", False))

                _set_docx_cell_shading(cell, bg_hex)
                if no_wrap:
                    _set_docx_cell_nowrap(cell)

                if box_border:
                    _set_docx_cell_borders(
                        cell,
                        top=b_box,
                        bottom=b_heavy if is_last else b_box,
                        left=b_box,
                        right=b_box,
                    )
                elif is_last:
                    _set_docx_cell_borders(cell, bottom=b_heavy)
                else:
                    _set_docx_cell_borders(cell)

                txt = str(c_meta.get("text") or "")
                spark_vals = c_meta.get("sparkline_values")
                if isinstance(spark_vals, list) and len(spark_vals) >= 2:
                    bars = _unicode_sparkbars([float(v) for v in spark_vals])
                    txt = f"{bars}  {txt}".strip() if txt else bars

                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.alignment = (
                    WD_ALIGN_PARAGRAPH.LEFT
                    if c_meta.get("align") == "left"
                    else WD_ALIGN_PARAGRAPH.RIGHT
                )
                _append_docx_run(
                    p,
                    txt,
                    font_size_pt=body_pt,
                    bold=is_bold,
                    color_hex=fg_hex,
                    superscript=str(c_meta.get("superscript") or "").strip(),
                )
                bar_spec = c_meta.get("bar_spec")
                if isinstance(bar_spec, dict):
                    b_ratio = float(bar_spec.get("ratio") or 0.0)
                    b_hex = _clean_hex6(bar_spec.get("fill_hex"), "2E6F95")
                    b_neg = bool(bar_spec.get("is_negative", False))
                    hbar = _unicode_hbar(b_ratio, max_chars=5)
                    if hbar:
                        glyph = f"  ◀{hbar}" if b_neg else f"  {hbar}"
                        r_bar = p.add_run(glyph)
                        r_bar.font.name = "Arial"
                        r_bar.font.size = Pt(max(7.0, body_pt - 0.5))
                        r_bar.font.color.rgb = RGBColor.from_string(b_hex)
            r_ptr += 1

    for fn in footnotes:
        sym = str(fn.get("symbol") or "").strip()
        ftxt = str(fn.get("text") or "").strip()
        if not ftxt:
            continue
        p_fn = doc.add_paragraph()
        p_fn.paragraph_format.space_before = Pt(3)
        p_fn.paragraph_format.space_after = Pt(0)
        if sym and sym not in ("*", "**", "***"):
            r_s = p_fn.add_run(sym)
            r_s.font.superscript = True
            r_s.font.name = "Arial"
            r_s.font.size = Pt(7.5)
            r_s.font.color.rgb = RGBColor.from_string("475569")
            r_t = p_fn.add_run(f" {ftxt}")
        else:
            line = f"{sym} {ftxt}".strip() if sym and not ftxt.startswith(sym) else ftxt
            r_t = p_fn.add_run(line)
        r_t.font.name = "Arial"
        r_t.font.size = Pt(8.0)
        r_t.font.color.rgb = RGBColor.from_string("475569")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def build_great_tables_script(bundle_meta: dict[str, Any]) -> str:
    """Generate a self-contained runnable `great_tables` Python script (`make_table.py`)."""
    title_str = bundle_meta.get("title") or "Table 1"
    subtitle_str = bundle_meta.get("subtitle") or ""
    rowname_col = bundle_meta.get("rowname_col") or ""
    groupname_col = bundle_meta.get("groupname_col") or ""
    spanners = bundle_meta.get("spanners") or []
    merges = bundle_meta.get("merges") or []
    heat_cols = bundle_meta.get("heat_cols") or []
    p_cols = bundle_meta.get("p_cols") or []
    decimals_map = bundle_meta.get("decimals_map") or {}
    footnotes = bundle_meta.get("footnotes") or []

    lines = [
        '#!/usr/bin/env python3',
        '"""Reproducible publication table script generated by Danqing Table Studio v2."""',
        "",
        "from pathlib import Path",
        "import pandas as pd",
        "from great_tables import GT",
        "",
        "HERE = Path(__file__).resolve().parent",
        'df = pd.read_csv(HERE / "data.csv")',
        "",
    ]
    for pc in p_cols:
        lines.append(f"if {pc!r} in df.columns:")
        lines.append(f"    df[{pc!r}] = pd.to_numeric(df[{pc!r}], errors='coerce')")

    gt_kwargs: list[str] = []
    if rowname_col:
        gt_kwargs.append(f"rowname_col={rowname_col!r}")
    if groupname_col:
        gt_kwargs.append(f"groupname_col={groupname_col!r}")
    kw_str = (", " + ", ".join(gt_kwargs)) if gt_kwargs else ""
    lines.append(f"gt = GT(df{kw_str})")

    if title_str or subtitle_str:
        if subtitle_str:
            lines.append(f"gt = gt.tab_header(title={title_str!r}, subtitle={subtitle_str!r})")
        else:
            lines.append(f"gt = gt.tab_header(title={title_str!r})")

    for col_name, dec in decimals_map.items():
        lines.append(f"if {col_name!r} in df.columns:")
        lines.append(f"    gt = gt.fmt_number(columns=[{col_name!r}], decimals={int(dec)})")

    for sp in spanners:
        sp_label = sp.get("label") or ""
        sp_cols = sp.get("columns") or []
        if sp_label and sp_cols:
            lines.append(f"gt = gt.tab_spanner(label={sp_label!r}, columns={sp_cols!r})")

    for hc in heat_cols:
        h_cols = hc.get("columns") or []
        h_pal = hc.get("palette") or []
        if h_cols and h_pal:
            lines.append(
                f"gt = gt.data_color(columns=[c for c in {h_cols!r} if c in df.columns], palette={h_pal!r})"
            )

    for mg in merges:
        cols = mg.get("columns") or []
        pattern = mg.get("pattern") or "{0} ({1})"
        if len(cols) >= 2:
            lines.append(f"gt = gt.cols_merge(columns={cols!r}, pattern={pattern!r})")

    for fn in footnotes:
        note_txt = f"{fn.get('symbol', '')} {fn.get('text', '')}".strip()
        if note_txt:
            lines.append(f"gt = gt.tab_source_note(source_note={note_txt!r})")

    lines.extend(
        [
            "",
            'html_out = gt.as_raw_html()',
            '(HERE / "table_rendered.html").write_text(html_out, encoding="utf-8")',
            'print(f"Rendered {len(df)} rows -> table_rendered.html ({len(html_out)} chars)")',
            "",
        ]
    )
    return "\n".join(lines)


def export_rule_bundle_zip(payload: dict[str, Any]) -> bytes:
    """Export reproducible `.zip` containing `table.json`, `data.csv`, and `make_table.py`."""
    rule_json = payload.get("table_json") or {"schema": "danqing.table_studio.v2"}
    csv_headers = payload.get("csv_headers") or []
    csv_rows = payload.get("csv_rows") or []
    gt_meta = payload.get("gt_meta") or {}

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, lineterminator="\n")
    if csv_headers:
        writer.writerow(csv_headers)
    for r in csv_rows:
        writer.writerow(["" if v is None else v for v in r])

    py_code = build_great_tables_script(gt_meta)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "table.json",
            json.dumps(rule_json, indent=2, ensure_ascii=False) + "\n",
        )
        zf.writestr("data.csv", csv_buf.getvalue())
        zf.writestr("make_table.py", py_code)
        src_sheet = payload.get("source_data_sheet")
        if isinstance(src_sheet, dict) and isinstance(src_sheet.get("headers"), list):
            src_buf = io.StringIO()
            src_writer = csv.writer(src_buf, lineterminator="\n")
            src_writer.writerow([str(h) for h in src_sheet["headers"]])
            for sr in src_sheet.get("rows") or []:
                src_writer.writerow(["" if v is None else v for v in sr])
            zf.writestr("source_data.csv", src_buf.getvalue())
    return zbuf.getvalue()
