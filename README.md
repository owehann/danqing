<div align="center">

<img src="./assets/logo.png" alt="Danqing Albers Mineral Seal Logo" width="128" height="128" />

# Danqing · 丹青

### New color for discovery, faithful to every datum
#### 赋科研以丹青，守数据之本真

<p>
  <a href="./README.zh-CN.md"><strong>简体中文文档</strong></a> ·
  <a href="#-at-a-glance">At a Glance</a> ·
  <a href="#-quickstart--zero-cost-deployment">Quickstart &amp; Cloud</a> ·
  <a href="#-the-277-verified-palettes">277 Palettes</a> ·
  <a href="#-multi-user-privacy--evidence-shield">Privacy &amp; Gate G0</a> ·
  <a href="#-ai-agent-skill--python-api">Agent Skill</a>
</p>

[![CI Status](https://github.com/owehann/danqing/actions/workflows/ci.yml/badge.svg)](https://github.com/owehann/danqing/actions/workflows/ci.yml)
[![Deploy to Render](https://img.shields.io/badge/Deploy_to_Render-Free_%240_Blueprint-0D9488?style=flat-square&logo=render)](https://render.com/deploy?repo=https://github.com/owehann/danqing)
[![Palettes: 277 Verified](https://img.shields.io/badge/Palettes-277_Primary--Source_Verified-C84B31?style=flat-square)](#-the-277-verified-palettes)
[![Privacy: Zero-Retention RAM](https://img.shields.io/badge/Privacy-Zero--Retention_RAM-264E86?style=flat-square)](#-multi-user-privacy--evidence-shield)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-SKILL.md-0F766E?style=flat-square)](./SKILL.md)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-0284C7?style=flat-square)](./LICENSE)

</div>

<br/>

## ✨ At a Glance

**Danqing (丹青)** reimagines finished vector scientific figures — PDFs and SVGs exported from **R (`ggplot2`)**, **Python (`matplotlib` / `seaborn` / `scanpy`)**, **GraphPad Prism**, or **Adobe Illustrator** — using **277 primary-source-verified accessible, journal, museum, and CC0 Eastern mineral-pigment palettes**, without altering a single coordinate, text glyph, or raw experimental image pixel.

<table width="100%">
  <tr>
    <td width="50%" valign="top">
      <h3>🎯 1. Byte-Verified Lossless Vector Engine</h3>
      <p>Parses PDF content streams (<code>rg/RG/g/G/k/K</code>, <code>ICCBased</code>, <code>DeviceCMYK</code>, <code>Indexed</code>, <code>Separation</code>, nested <code>/Form</code> XObjects, multi-page selection) and SVG stylesheets (<code>&lt;style&gt;</code>, inline <code>style=</code>, inherited <code>&lt;g&gt;</code>, <code>currentColor</code>, <code>&lt;use&gt;</code>, coupled gradients) under strict <code>preview == export</code> parity.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🛡️ 2. Gate G0 Raw-Evidence Shield</h3>
      <p>Automatically detects and locks embedded raster evidence — <strong>Western blot lanes, H&amp;E pathology sections, immunofluorescence crops, and electron micrographs</strong> — guaranteeing bit-for-bit SHA-256 identity before and after export.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>🎨 3. 277 Primary-Source Palettes</h3>
      <p>Spans <strong>Accessible</strong> (Okabe–Ito, Petroff IEEE VIS, Paul Tol), <strong>Journal &amp; Data-Vis</strong> (NPG/NEJM/Lancet-inspired, CNS Iso-Chroma), <strong>World Museums</strong> (<code>MetBrewer</code>, <code>MoMAColors</code>), <strong>24 CC0 Eastern Artifacts</strong> (Song Ru/Jun celadon, Dunhuang/mineral thangkas, Ming Doucai), <strong>Single-Cell 64+</strong>, and <strong>Crameri v8.0 / cmocean</strong> continuous maps.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🔒 4. Cryptographic Multi-Visitor Isolation</h3>
      <p>Built for lab-wide and public web hosting: <strong>100% RAM-only zero disk retention</strong>, per-boot 256-bit HMAC-SHA256 visitor isolation (<code>dq_sid</code>), 128-bit unguessable figure handles, physiological CVD simulation, and <code>.zip</code> export with ready-to-paste <code>ggplot2</code> &amp; <code>matplotlib</code> snippets.</p>
    </td>
  </tr>
</table>

<br/>

<div align="center">
  <img src="./assets/icon_system.png" alt="Danqing Optical Brand System — Albers Mineral Seal" width="880" />
</div>

<br/>

---

## 🚀 Quickstart & Zero-Cost Deployment

### Option A · Local Studio (3 Commands)

```bash
pip install -e ".[dev]"
(cd web/frontend && pnpm install && pnpm build)
./scripts/start_studio.sh
```

Open `http://127.0.0.1:8765` in any modern browser.

### Option B · 1-Click 24/7 Free Cloud Hosting (\$0.00 · No Credit Card)

Click below to deploy your own 24/7 HTTPS instance on **Render Free Tier** via [`render.yaml`](./render.yaml) (`plan: free`, `DANQING_LOW_MEMORY=1`, zero billing risk):

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/owehann/danqing)

### Option C · Instant Public Share Link (No Account Needed)

```bash
./scripts/share_public.sh          # Public HTTPS link via Cloudflare Quick Tunnel ($0)
./scripts/share_public.sh --lan    # Same-Wi-Fi / lab LAN mode ($0)
```

See [`docs/FREE_DEPLOYMENT.md`](./docs/FREE_DEPLOYMENT.md) for full details.

---

## 🎨 The 277 Verified Palettes

| Collection | Count | Representative Palettes & Provenance |
| :--- | :---: | :--- |
| **Accessible** | `16` | Okabe–Ito, Petroff 6/8/10 (*Matplotlib 3.10 / IEEE VIS*), IBM Safe, Paul Tol (*Bright, Vibrant, Muted, High-Contrast*), CARTO Safe, ColorBrewer Dark2 |
| **Journal & Data-Vis** | `29` | NPG, AAAS, NEJM, Lancet, JAMA, JCO, BMJ (`*-inspired`), LocusZoom GWAS, Observable 10, Tableau 10, Seaborn, Scanpy 10, CNS Iso-Chroma Harmony 12 |
| **Museum, Art & Nature** | `116` | 56 Metropolitan Museum of Art (`MetBrewer`, CC0), 30 MoMA (`MoMAColors`, MIT), 10 `PNWColors` (CC0), 15 `NatParksPalettes` (MIT), 5 cinema classics |
| **Eastern Artifacts (CC0)** | `24` | Deterministic extraction from 48 CC0 Cleveland Museum of Art photographs: Shang bronzes, Tang Sancai, Song Ru/Jun/Longquan celadons, Zhao Mengfu blue-green landscape, Chenghua Doucai, Hokusai Red Fuji, Himalayan mineral thangkas |
| **Many Colors (Single-Cell)** | `13` | Polychrome 34, Green-Armytage 25, Scanpy 20, Zeileis 26 & Ultra-Cluster 64, Kelly 22, Glasbey 32 + dynamic OKLCH hull expansion (`K > N`) |
| **Continuous & Diverging** | `73` | Crameri *Scientific colour maps* v8.0 (`batlowW`, `lipari`, `navia`, `vik`, `roma`, `bam`), `cmocean` (`thermal`, `haline`, `balance`), Viridis/Cividis, ColorBrewer 2.0, zero-midpoint lock |
| **Domain Conventions** | `6` | COSMIC SBS-6 mutational signatures, Manhattan alternating chromosomes, Volcano `Up/Down/NS`, Cell Cycle `G1/S/G2M`, CNV `Gain/Loss/Neutral`, `A/C/G/T` bases |

Every palette's primary source, license, CIEDE2000 minimum distance, CVD safety under Machado et al. (2009) deuteranopia/protanopia matrices, and grayscale print legibility are audited in [`core/danqing/palettes/VERIFICATION.md`](./core/danqing/palettes/VERIFICATION.md).

---

## 🔒 Multi-User Privacy & Evidence Shield

- **Zero Disk Retention**: Uploaded manuscripts and figures exist strictly in Python process RAM, never touch disk, and are purged via `gc.collect()` on delete or 10-minute idle TTL (`--no-access-log` enabled by default).
- **HMAC-SHA256 Visitor Isolation**: Visitors A and B cannot view, list, or mutate each other's figures or preset states (`404` across sessions; forged cookies rejected in constant time).
- **Gate G6 & Gate G0 Export Audit**: Every exported `.zip` verifies vector path geometry (`g6_geometry_identical == True`) and embedded raster image hashes (`g0_evidence_bit_identical == True`), alongside `palette_snippet.R`, `palette_snippet.py`, and `color_mapping.csv`.

---

## 🤖 AI Agent Skill & Python API

Install or reference [`SKILL.md`](./SKILL.md) in **Claude Code**, **Antigravity**, **Cursor**, or **Codex**, or call the Python engine directly:

```python
from pathlib import Path
from danqing.pdf_engine import parse_pdf_scene, export_recolored_pdf
from danqing.solver import solve_scene_colors

scene = parse_pdf_scene(Path("figure.pdf").read_bytes(), "figure.pdf", "fig1", page_index=0)
result = solve_scene_colors(
    scene.entities,
    scene.continuous_scales,
    scene.evidence_regions,
    style_id="east_ru_celadon",      # or "okabe_ito", "npg_inspired", "met_hiroshige"
    collision_scope="panel_scoped",  # Same label -> same color across panels
)

out_pdf, audit = export_recolored_pdf(scene, result.group_hex, result.scale_stops, verify=True)
assert audit["g6_geometry_identical"] and audit["g0_evidence_bit_identical"]
Path("figure_danqing.pdf").write_bytes(out_pdf)
```

---

## 🧪 Verification Suite

```bash
pytest -q
python scripts/palette_qc.py
python scripts/palette_assignment_eval.py
python scripts/check_i18n_strings.py
python scripts/check_licenses.py
```

---

## 📜 License & Attribution

- **Engine, Studio & Brand Assets**: [Apache License 2.0](./LICENSE) (`0` GPL/AGPL runtime dependencies).
- **Palette Provenance & Public Benchmark Datasets**: Documented in [`NOTICE`](./NOTICE) and [`core/danqing/palettes/VERIFICATION.md`](./core/danqing/palettes/VERIFICATION.md).
