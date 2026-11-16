"""Golden tests: preview == export, pick region == recolored region, and API v2 guardrails across presets & corpus."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from scipy import ndimage

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(REPO))

from web.backend.app import PRESET_MANIFEST, _load_preset_item, app  # noqa: E402

PDF_PRESETS = ["penguins_multimodal", "histology_wb_shield", "visium_brain_complex"]
ALL_PRESETS = PDF_PRESETS + ["egfr_pathway_svg"]
PALETTES = ["okabe_ito", "east_qinghua_porcelain", "met_hiroshige"]
CORPUS_DIR = REPO / "bench" / "corpus"


@pytest.fixture(scope="module")
def client() -> TestClient:
    for item in PRESET_MANIFEST:
        _load_preset_item(item, keep_original=False)
    return TestClient(app)


def _png(b: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(b)).convert("RGB"), dtype=np.int16)


def _render_pdf_bytes(pdf_bytes: bytes, scale: float, page_index: int = 0) -> np.ndarray:
    pil = pdfium.PdfDocument(pdf_bytes)[page_index].render(scale=scale, fill_color=(255, 255, 255, 255)).to_pil().convert("RGB")
    return np.asarray(pil, dtype=np.int16)


def _v2_mutation_sequence(client: TestClient, fid: str, palette_id: str) -> list[dict]:
    states = []
    st = client.patch(f"/api/v2/figures/{fid}/state", json={"action": "set_palette", "palette_id": palette_id}).json()
    states.append(st)
    st = client.patch(f"/api/v2/figures/{fid}/state", json={"action": "set_rule", "rule": "unique"}).json()
    states.append(st)
    first_eid = next(iter(st["entity_colors"].keys()))
    swatches = st["inspector_swatches"][first_eid]
    bead = swatches[min(2, len(swatches) - 1)]["hex"]
    st = client.patch(
        f"/api/v2/figures/{fid}/state",
        json={"action": "pick_color", "entity_id": first_eid, "hex_color": bead},
    ).json()
    assert st["entity_meta"][first_eid]["locked"] is True  # Spec 4.6 auto-lock!
    states.append(st)
    if st["continuous_scales"]:
        sid0 = st["continuous_scales"][0]["scale_id"]
        st = client.patch(f"/api/v2/figures/{fid}/state", json={"action": "invert_scale", "scale_id": sid0}).json()
        states.append(st)
    st = client.patch(f"/api/v2/figures/{fid}/state", json={"action": "set_rule", "rule": "same_name"}).json()
    states.append(st)
    return states


@pytest.mark.parametrize("fid", ALL_PRESETS)
@pytest.mark.parametrize("palette_id", PALETTES)
def test_v2_preview_equals_export(client: TestClient, fid: str, palette_id: str) -> None:
    if fid == "visium_brain_complex" and palette_id != PALETTES[0]:
        pytest.skip("heavy figure: one palette is enough for golden equality check")
    meta = client.get(f"/api/v2/figures/{fid}").json()
    for st in _v2_mutation_sequence(client, fid, palette_id):
        preview = client.get(st["render_url"])
        assert preview.status_code == 200
        exp_fmt = "svg" if meta["kind"] == "svg" else "pdf"
        exp = client.post(
            f"/api/v2/figures/{fid}/export",
            json={
                "format": exp_fmt,
                "include_r": False,
                "include_python": False,
                "include_json": False,
                "include_change_report": False,
                "force": True,
            },
        )
        assert exp.status_code == 200
        if meta["kind"] == "svg":
            assert preview.content == exp.content
            continue
        pv = _png(preview.content)
        ex = _render_pdf_bytes(exp.content, meta["preview_scale"], meta["page_index"])
        assert pv.shape == ex.shape
        bad = (np.abs(pv - ex).max(axis=2) > 20).mean()
        assert bad < 0.005, f"{fid}/{palette_id} rev {st['revision']}: {bad * 100:.2f}% preview pixels differ from export"


@pytest.mark.parametrize("fid", PDF_PRESETS)
def test_pick_region_is_exactly_what_recolors(client: TestClient, fid: str) -> None:
    client.patch(f"/api/v2/figures/{fid}/state", json={"action": "set_palette", "palette_id": "east_cloisonne_enamel"})
    st = client.get(f"/api/v2/figures/{fid}").json()
    idm = _png(client.get(st["pick_url"]).content).astype(np.int32)
    base = _png(client.get(st["render_url"]).content)
    assert idm.shape == base.shape
    R, G = idm[..., 0], idm[..., 1]
    assert (R == 255).mean() < 0.001, "pick buffer contains white leakage (R=255)"
    cat_idx = (R - 1) + G * 240

    elements = st["elements"][: (4 if fid == "visium_brain_complex" else len(st["elements"]))]
    checked = 0
    for ent in elements:
        idxs = [e["cat_index"] for e in st["categorical_lut"] if e["entity_id"] == ent["entity_id"]]
        mask = (R >= 1) & (R <= 240) & np.isin(cat_idx, idxs)
        if mask.sum() < 30:
            continue
        probe = "00FF00" if ent["current_hex"].upper() != "#00FF00" else "FF00FF"
        url = f"{st['render_url']}&pe={ent['entity_id']}&ph={probe}"
        probed = _png(client.get(url).content)
        changed = np.abs(probed - base).max(axis=2) > 30
        near = ndimage.binary_dilation(mask, iterations=3)
        core = ndimage.binary_erosion(mask, iterations=1)
        outside_leak = (changed & ~near).sum() / max(1, changed.sum())
        inside_hit = changed[core].mean() if core.sum() else changed[mask].mean()
        assert outside_leak < 0.02, f"{fid} {ent['label']}: {outside_leak * 100:.1f}% outside pick region"
        assert inside_hit > 0.6, f"{fid} {ent['label']}: only {inside_hit * 100:.1f}% inside pick region recolors"
        checked += 1
    assert checked >= 3


def test_api_v2_upload_guardrails_and_zip_export(client: TestClient) -> None:
    # 1. Palettes endpoint
    p_res = client.get("/api/v2/palettes")
    assert p_res.status_code == 200
    assert len(p_res.json()["palettes"]) >= 55

    # 2. Raster rejection (Spec 4.1)
    png_buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 0, 0)).save(png_buf, format="PNG")
    r_ras = client.post("/api/v2/figures?sync=true", files={"file": ("blot.png", png_buf.getvalue(), "image/png")})
    assert r_ras.status_code == 422
    assert r_ras.json()["code"] == "RASTER_NOT_SUPPORTED"

    # 3. Empty file rejection
    r_emp = client.post("/api/v2/figures?sync=true", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r_emp.status_code == 400
    assert r_emp.json()["code"] == "EMPTY_FILE"

    # 4. Scanned PDF rejection (`c33_scanned_page_only.pdf`)
    c33 = (CORPUS_DIR / "c33_scanned_page_only.pdf").read_bytes()
    r_scan = client.post("/api/v2/figures?sync=true", files={"file": ("scanned.pdf", c33, "application/pdf")})
    assert r_scan.status_code == 422
    assert r_scan.json()["code"] == "SCANNED_PDF_NO_VECTORS"

    # 5. Multi-page PDF page picker (`c32_multipage_manuscript_3p.pdf`)
    c32 = (CORPUS_DIR / "c32_multipage_manuscript_3p.pdf").read_bytes()
    r_mp = client.post("/api/v2/figures?sync=true", files={"file": ("3page.pdf", c32, "application/pdf")})
    assert r_mp.status_code == 200
    mp_data = r_mp.json()
    assert mp_data["code"] == "MULTI_PAGE_SELECT_REQUIRED"
    assert mp_data["page_count"] == 3
    r_mp2 = client.post(
        "/api/v2/figures?sync=true",
        data={"pending_upload_id": mp_data["pending_upload_id"], "page_index": "1"},
    )
    assert r_mp2.status_code == 200
    fid_mp = r_mp2.json()["figure_id"]
    fig_mp = client.get(f"/api/v2/figures/{fid_mp}").json()
    assert fig_mp["is_original_mode"] is True  # Spec 4.2 default original mode!
    assert fig_mp["page_index"] == 1

    # 6. Export verify + ZIP bundle with R, Python, JSON, and CSV change report
    client.patch(f"/api/v2/figures/{fid_mp}/state", json={"action": "set_palette", "palette_id": "okabe_ito"})
    ver = client.post(f"/api/v2/figures/{fid_mp}/export/verify", json={"format": "pdf"}).json()
    assert ver["checks"]["shapes_and_text_unchanged"] is True
    assert ver["checks"]["all_passed"] is True

    exp_zip = client.post(
        f"/api/v2/figures/{fid_mp}/export",
        json={
            "format": "pdf",
            "include_r": True,
            "include_python": True,
            "include_json": True,
            "include_change_report": True,
        },
    )
    assert exp_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exp_zip.content)) as zf:
        names = zf.namelist()
        assert any(n.endswith(".pdf") for n in names)
        assert any(n.endswith("_ggplot2.R") for n in names)
        assert any(n.endswith("_matplotlib.py") for n in names)
        assert any(n.endswith("_palette.json") for n in names)
        assert any(n.endswith("_changes.csv") for n in names)

    # 7. Delete session (Spec 4.1 privacy cleanup)
    client.delete(f"/api/v2/figures/{fid_mp}")
    assert client.get(f"/api/v2/figures/{fid_mp}").status_code == 404


def test_corpus_preview_equals_export_sample(client: TestClient) -> None:
    manifest = json.loads((CORPUS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    sample_ids = [
        "c05_mpl_grouped_bar",
        "c06_mpl_grouped_bar",
        "c10_mpl_umap_24clusters",
        "c21_svglite_css_dodged_bar",
        "c26_prism_icc_grouped_bar",
        "c27_illustrator_form_separation",
        "c30_biorender_signaling_pathway",
        "c31_excel_indexed_chart",
    ]
    for it in manifest["figures"]:
        if it["id"] not in sample_ids:
            continue
        fp = CORPUS_DIR / it["filename"]
        res = client.post("/api/v2/figures?sync=true", files={"file": (fp.name, fp.read_bytes())}).json()
        fid = res["figure_id"]
        st = client.patch(f"/api/v2/figures/{fid}/state", json={"action": "set_palette", "palette_id": "okabe_ito"}).json()
        pv_resp = client.get(st["render_url"])
        meta = client.get(f"/api/v2/figures/{fid}").json()
        exp_fmt = "svg" if meta["kind"] == "svg" else "pdf"
        ex_resp = client.post(
            f"/api/v2/figures/{fid}/export",
            json={"format": exp_fmt, "include_r": False, "include_python": False, "force": True},
        )
        if meta["kind"] == "svg":
            assert pv_resp.content == ex_resp.content
        else:
            pv = _png(pv_resp.content)
            ex = _render_pdf_bytes(ex_resp.content, meta["preview_scale"], 0)
            assert (np.abs(pv - ex).max(axis=2) > 20).mean() < 0.005
        client.delete(f"/api/v2/figures/{fid}")


def test_api_v2_overlay_split_layers_and_corpus_form_scatter_pick(client: TestClient) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 1. Corpus Matplotlib PDF scatter plots (`c09` UMAP `/P* Do` & `c12` Volcano `/M* Do`) must pick & recolor all points
    for fname in ("c09_mpl_umap_22clusters.pdf", "c12_mpl_volcano_deg.pdf"):
        fp = CORPUS_DIR / fname
        res = client.post("/api/v2/figures?sync=true", files={"file": (fp.name, fp.read_bytes())}).json()
        fid = res["figure_id"]
        meta = client.get(f"/api/v2/figures/{fid}").json()
        total_prims = sum(el["primitive_count"] for el in meta["elements"])
        assert total_prims >= 100, f"{fname}: expected >= 100 scatter marks, got {total_prims}"
        idm = _png(client.get(meta["pick_url"]).content).astype(np.int32)
        base = _png(client.get(meta["render_url"]).content)
        R, G = idm[..., 0], idm[..., 1]
        cat_idx = (R - 1) + G * 240
        ent0 = meta["elements"][0]
        idxs = [e["cat_index"] for e in meta["categorical_lut"] if e["entity_id"] == ent0["entity_id"]]
        mask = (R >= 1) & (R <= 240) & np.isin(cat_idx, idxs)
        assert int(mask.sum()) >= 80
        probed = _png(client.get(f"{meta['render_url']}&pe={ent0['entity_id']}&ph=00FF00").content)
        changed = np.abs(probed - base).max(axis=2) > 30
        assert changed[mask].mean() > 0.5
        client.delete(f"/api/v2/figures/{fid}")

    # 2. Single-panel Boxplot + Overlaid Scatter PDF: `split_same_name` unlinks shapes vs individual points
    fig, ax = plt.subplots(figsize=(4.5, 4.0))
    vals = [10.0 + (i % 7) * 1.1 for i in range(14)]
    xs = [1.0 + ((i % 5) - 2) * 0.04 for i in range(14)]
    bp = ax.boxplot([vals], patch_artist=True, widths=0.45)
    bp["boxes"][0].set(facecolor="#1f77b4", alpha=0.35, edgecolor="#444444")
    bp["medians"][0].set_color("#444444")
    ax.scatter(xs, vals, s=32, c="#1f77b4", alpha=0.80, edgecolors="#222222", linewidths=0.5, zorder=3)
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)

    up = client.post("/api/v2/figures?sync=true", files={"file": ("single_overlay.pdf", buf.getvalue())}).json()
    fid_ov = up["figure_id"]
    m0 = client.get(f"/api/v2/figures/{fid_ov}").json()
    assert len(m0["elements"]) == 1
    eid0 = m0["elements"][0]["entity_id"]
    assert len(m0["elements"][0]["member_group_ids"]) == 2
    assert {e["mark_kind"] for e in m0["categorical_lut"]} == {"area", "point"}

    sp_res = client.patch(
        f"/api/v2/figures/{fid_ov}/state",
        json={"action": "split_same_name", "entity_id": eid0},
    ).json()
    assert sp_res["structure_changed"] is True
    assert len(sp_res["elements"]) == 2
    pts_el = next(el for el in sp_res["elements"] if "(points)" in el["label"])
    shp_el = next(el for el in sp_res["elements"] if "(shapes)" in el["label"])

    # Recolor ONLY the overlaid points to crimson while keeping the underlying boxplot blue
    st_pts = client.patch(
        f"/api/v2/figures/{fid_ov}/state",
        json={"action": "pick_color", "entity_id": pts_el["entity_id"], "hex_color": "#D55E00"},
    ).json()
    assert st_pts["entity_colors"][pts_el["entity_id"]] == "#D55E00"
    assert st_pts["entity_colors"][shp_el["entity_id"]].upper() == "#1F77B4"
    client.delete(f"/api/v2/figures/{fid_ov}")
