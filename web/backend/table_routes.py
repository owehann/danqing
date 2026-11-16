"""FastAPI router for Danqing Table Studio v2 (samples, RawSnapshot parsing, .xlsx/.docx/.zip exports)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from danqing.table_compute import compute_statistical_table
from danqing.table_studio import (
    TableParseError,
    export_rule_bundle_zip,
    export_styled_docx,
    export_styled_xlsx,
    parse_tabular_bytes,
    parse_tabular_paste,
)

table_router = APIRouter(prefix="/api/v2/tables", tags=["tables"])

MAX_TABLE_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB stateless memory guard
REPO_ROOT = Path(__file__).resolve().parents[2]
TABLES_BENCH_DIR = REPO_ROOT / "bench" / "tables"
MANIFEST_PATH = TABLES_BENCH_DIR / "MANIFEST.json"
OUT_DIR = TABLES_BENCH_DIR / "out"

# Cached sample preview thumbnails (first 6 rows x 5 cols of raw grid)
_SAMPLES_CACHE: list[dict[str, Any]] | None = None


class TableExportPayload(BaseModel):
    filename_stem: str = "danqing_table"
    title: str = "Table 1"
    subtitle: str = ""
    preset: str = "cns_three_line"
    spanners: list[dict[str, Any]] = Field(default_factory=list)
    headers: list[dict[str, Any]] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    footnotes: list[dict[str, Any]] = Field(default_factory=list)
    raw_data_sheet: dict[str, Any] | None = None
    source_data_sheet: dict[str, Any] | None = None


class TableZipExportPayload(BaseModel):
    filename_stem: str = "danqing_table_bundle"
    table_json: dict[str, Any] = Field(default_factory=dict)
    csv_headers: list[str] = Field(default_factory=list)
    csv_rows: list[list[Any]] = Field(default_factory=list)
    gt_meta: dict[str, Any] = Field(default_factory=dict)
    source_data_sheet: dict[str, Any] | None = None


class TableComputePayload(BaseModel):
    grid: list[list[str]] = Field(default_factory=list)
    header_rows: tuple[int, int] = (0, 0)
    body_range: tuple[int, int] = (1, 1)
    decimal_comma: bool = False
    source: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["subject_table1", "replicate_collapse"] = "subject_table1"
    options: dict[str, Any] = Field(default_factory=dict)
    lang: Literal["en", "zh"] = "zh"


def _safe_disposition_filename(stem: str, ext: str) -> str:
    cleaned = re.sub(r"[^\w\-. \u4e00-\u9fff]+", "_", stem.strip()).strip(" ._") or "danqing_table"
    full = f"{cleaned}.{ext.lstrip('.')}"
    ascii_fallback = re.sub(r"[^\x20-\x7E]+", "_", full) or f"danqing_table.{ext.lstrip('.')}"
    encoded = quote(full)
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def _load_samples_catalog() -> list[dict[str, Any]]:
    global _SAMPLES_CACHE
    if _SAMPLES_CACHE is not None:
        return _SAMPLES_CACHE
    if not MANIFEST_PATH.exists():
        return []
    manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
    catalog: list[dict[str, Any]] = []
    for item in manifest.get("samples", []):
        out_path = OUT_DIR / item["filename"]
        preview_grid: list[list[str]] = []
        if out_path.exists():
            snap = parse_tabular_bytes(
                out_path.read_bytes(), filename=item["filename"], kind_override="sample"
            )
            preview_grid = [row[:5] for row in snap.grid[:6]]
        catalog.append({**item, "preview_grid": preview_grid})
    _SAMPLES_CACHE = catalog
    return catalog


@table_router.get("/samples")
def list_v2_table_samples() -> dict[str, Any]:
    return {"samples": _load_samples_catalog()}


@table_router.get("/samples/{sample_id}")
def get_v2_table_sample(sample_id: str) -> Response:
    catalog = _load_samples_catalog()
    match = next((s for s in catalog if s["id"] == sample_id), None)
    if match is None:
        return JSONResponse(
            status_code=404,
            content={"error_key": "tableStudio.errors.unsupported"},
        )
    out_path = OUT_DIR / match["filename"]
    if not out_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error_key": "tableStudio.errors.noDataRows"},
        )
    snap = parse_tabular_bytes(
        out_path.read_bytes(), filename=match["filename"], kind_override="sample"
    )
    body = snap.to_dict()
    body["sample_id"] = sample_id
    return JSONResponse(content=body)


@table_router.post("/parse")
async def parse_v2_table(
    file: UploadFile | None = File(default=None),
    pasted_text: str | None = Form(default=None),
    pasted_html: str | None = Form(default=None),
    sheet_name: str | None = Form(default=None),
) -> Response:
    try:
        if file is not None:
            fname = file.filename or "uploaded_table.csv"
            raw = await file.read(MAX_TABLE_UPLOAD_BYTES + 1)
            if len(raw) > MAX_TABLE_UPLOAD_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"error_key": "tableStudio.errors.tooLarge"},
                )
            parsed = parse_tabular_bytes(raw, filename=fname, sheet_name=sheet_name)
            return JSONResponse(content=parsed.to_dict())

        if (pasted_html and pasted_html.strip()) or (pasted_text and pasted_text.strip()):
            parsed = parse_tabular_paste(
                pasted_text=pasted_text,
                pasted_html=pasted_html,
                filename="pasted_table.tsv",
            )
            return JSONResponse(content=parsed.to_dict())

        return JSONResponse(
            status_code=400,
            content={"error_key": "tableStudio.errors.emptyFile"},
        )
    except TableParseError as exc:
        return JSONResponse(
            status_code=422,
            content={"error_key": exc.error_key, "detail": exc.detail},
        )
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"error_key": "tableStudio.errors.decodeFailed"},
        )


@table_router.post("/compute")
def compute_v2_statistical_table(payload: TableComputePayload) -> Response:
    if len(payload.grid) < 2 or not payload.grid[0]:
        return JSONResponse(
            status_code=422,
            content={"error_key": "tableStudio.errors.noDataRows"},
        )
    try:
        result = compute_statistical_table(
            raw_grid=payload.grid,
            header_rows=payload.header_rows,
            body_range=payload.body_range,
            decimal_comma=payload.decimal_comma,
            source_meta=payload.source,
            mode=payload.mode,
            options=payload.options,
            lang=payload.lang,
        )
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(
            status_code=422,
            content={"error_key": "tableStudio.errors.decodeFailed", "detail": str(exc)},
        )


@table_router.post("/export/xlsx")
def export_v2_table_xlsx(payload: TableExportPayload) -> Response:
    try:
        xlsx_bytes = export_styled_xlsx(payload.model_dump())
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error_key": "tableStudio.errors.exportFailed"},
        )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": _safe_disposition_filename(payload.filename_stem, "xlsx"),
            "Cache-Control": "no-store",
        },
    )


@table_router.post("/export/docx")
def export_v2_table_docx(payload: TableExportPayload) -> Response:
    try:
        docx_bytes = export_styled_docx(payload.model_dump())
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error_key": "tableStudio.errors.exportFailed"},
        )
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": _safe_disposition_filename(payload.filename_stem, "docx"),
            "Cache-Control": "no-store",
        },
    )


@table_router.post("/export/zip")
def export_v2_table_zip(payload: TableZipExportPayload) -> Response:
    try:
        zip_bytes = export_rule_bundle_zip(payload.model_dump())
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error_key": "tableStudio.errors.exportFailed"},
        )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": _safe_disposition_filename(payload.filename_stem, "zip"),
            "Cache-Control": "no-store",
        },
    )
