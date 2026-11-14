"""Tests for per-panel selective recoloring and thread-safe PDFium preview rendering."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from web.backend.app import app


def test_per_panel_selective_recoloring_mix_and_match_and_reset() -> None:
    client = TestClient(app)
    res = client.post("/api/v2/figures?sync=true", data={"preset_id": "penguins_multimodal"})
    assert res.status_code == 200
    fig_id = res.json()["figure_id"]

    fig0 = client.get(f"/api/v2/figures/{fig_id}").json()
    assert len(fig0["panels"]) >= 2
    panel_a = fig0["panels"][0]["panel_id"]
    panel_b = fig0["panels"][1]["panel_id"]

    orig_lut = {it["group_id"]: (it["panel_id"], it["current_hex"]) for it in fig0["categorical_lut"]}

    # 1. Recolor ONLY panel_b -> panel_a and all other panels must remain 100% at original_hex!
    r1 = client.patch(
        f"/api/v2/figures/{fig_id}/state",
        json={"action": "set_palette", "palette_id": "petroff10", "target_panels": [panel_b]},
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["panel_palettes"][panel_b] == "petroff10"
    assert d1["panel_palettes"][panel_a] == "__original__"

    fig1 = client.get(f"/api/v2/figures/{fig_id}").json()
    for it in fig1["categorical_lut"]:
        gid = it["group_id"]
        if it["panel_id"] != panel_b:
            assert it["current_hex"].upper() == orig_lut[gid][1].upper(), f"Non-target panel {it['panel_id']} leaked!"

    panel_b_after_p1 = {
        it["group_id"]: it["current_hex"] for it in fig1["categorical_lut"] if it["panel_id"] == panel_b
    }

    # 2. Mix & Match: now recolor ONLY panel_a with a second palette -> panel_b keeps petroff10, others stay original!
    r2 = client.patch(
        f"/api/v2/figures/{fig_id}/state",
        json={"action": "set_palette", "palette_id": "east_ming_blue_white", "target_panels": [panel_a]},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["panel_palettes"][panel_a] == "east_ming_blue_white"
    assert d2["panel_palettes"][panel_b] == "petroff10"

    fig2 = client.get(f"/api/v2/figures/{fig_id}").json()
    for it in fig2["categorical_lut"]:
        gid = it["group_id"]
        if it["panel_id"] == panel_b:
            assert it["current_hex"].upper() == panel_b_after_p1[gid].upper()
        elif it["panel_id"] != panel_a:
            assert it["current_hex"].upper() == orig_lut[gid][1].upper()

    # 3. Hover preview scoped to panel_a returns valid PNG without mutating stored state
    prev_res = client.get(f"/api/v2/figures/{fig_id}/render?rev={d2['revision']}&palette=okabe_ito&panels={panel_a}")
    assert prev_res.status_code == 200
    assert prev_res.headers["content-type"] == "image/png"

    # 4. Reset ONLY panel_b -> panel_b returns to original, while panel_a keeps east_ming_blue_white!
    r3 = client.patch(
        f"/api/v2/figures/{fig_id}/state",
        json={"action": "reset_panel", "target_panels": [panel_b]},
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["panel_palettes"][panel_b] == "__original__"
    assert d3["panel_palettes"][panel_a] == "east_ming_blue_white"

    fig3 = client.get(f"/api/v2/figures/{fig_id}").json()
    for it in fig3["categorical_lut"]:
        if it["panel_id"] == panel_b:
            assert it["current_hex"].upper() == orig_lut[it["group_id"]][1].upper()

    # 5. Undo restores panel_b's petroff10 assignment cleanly
    r_undo = client.patch(f"/api/v2/figures/{fig_id}/state", json={"action": "undo"})
    assert r_undo.status_code == 200
    assert r_undo.json()["panel_palettes"][panel_b] == "petroff10"


def test_concurrent_multithread_pdfium_renders_are_thread_safe() -> None:
    client = TestClient(app)
    client.post("/api/v2/figures?sync=true", data={"preset_id": "penguins_multimodal"})
    client.post("/api/v2/figures?sync=true", data={"preset_id": "histology_wb_shield"})

    urls = [
        "/api/v2/figures/penguins_multimodal/render?rev=1&palette=okabe_ito",
        "/api/v2/figures/histology_wb_shield/render?rev=1&palette=petroff10",
        "/api/v2/figures/penguins_multimodal/render?rev=1&palette=east_ming_fahua&panels=Panel%20A",
        "/api/v2/figures/histology_wb_shield/render?rev=1&palette=carto_safe",
        "/api/v2/figures/penguins_multimodal/pick",
        "/api/v2/figures/histology_wb_shield/pick",
    ]

    def _hit(u: str) -> int:
        r = client.get(u)
        return r.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(_hit, urls * 2))

    assert all(c in (200, 204) for c in codes)


def test_multi_visitor_privacy_and_preset_isolation() -> None:
    client_a = TestClient(app)
    client_b = TestClient(app)

    svg_payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">'
        '<rect x="10" y="10" width="60" height="80" fill="#E64B35"/>'
        '<rect x="90" y="25" width="60" height="65" fill="#4DBBD5"/>'
        "</svg>"
    )
    up_a = client_a.post("/api/v2/figures?sync=true", data={"svg_text": svg_payload})
    assert up_a.status_code == 200
    fig_a_id = up_a.json()["figure_id"]

    # Visitor A sees their figure; Visitor B sees zero uploaded figures and gets 404 on Visitor A's ID
    list_a = client_a.get("/api/v2/figures").json()["figures"]
    assert any(f["figure_id"] == fig_a_id for f in list_a)

    list_b = client_b.get("/api/v2/figures").json()["figures"]
    assert all(f["figure_id"] != fig_a_id for f in list_b)
    assert client_b.get(f"/api/v2/figures/{fig_a_id}").status_code == 404
    assert client_b.get(f"/api/v2/figures/{fig_a_id}/render").status_code == 404

    # Preset edits by Visitor A do not leak to Visitor B
    client_a.post("/api/v2/figures?sync=true", data={"preset_id": "penguins_multimodal"})
    client_a.patch(
        "/api/v2/figures/penguins_multimodal/state",
        json={"action": "set_palette", "palette_id": "petroff10"},
    )
    state_a = client_a.get("/api/v2/figures/penguins_multimodal").json()
    assert state_a["is_original_mode"] is False
    assert state_a["palette_id"] == "petroff10"

    client_b.post("/api/v2/figures?sync=true", data={"preset_id": "penguins_multimodal"})
    state_b = client_b.get("/api/v2/figures/penguins_multimodal").json()
    assert state_b["is_original_mode"] is True
    assert state_b["palette_id"] is None

    # Forged / unsigned cookie cannot hijack Visitor B or predict any session
    attacker = TestClient(app)
    attacker.cookies.set("dq_sid", "00000000000000000000000000000001.ffffffffffffffffffffffffffffffff")
    assert attacker.get(f"/api/v2/figures/{fig_a_id}").status_code == 404
    assert attacker.get("/api/v2/figures").json()["figures"] == []

    # Instant session wipe clears Visitor A's RAM state without touching Visitor B
    clr = client_a.post("/api/v2/session/clear")
    assert clr.status_code == 200
    assert client_a.get(f"/api/v2/figures/{fig_a_id}").status_code == 404
    assert client_b.get("/api/v2/figures/penguins_multimodal").status_code == 200

