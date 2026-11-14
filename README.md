<div align="center">

<img src="./assets/logo.png" alt="Danqing Albers Mineral Seal Logo" width="128" height="128" />

# Danqing · 丹青

### New color for discovery, faithful to every datum
#### 赋科研以丹青，守数据之本真

<p>
  <a href="./README.zh-CN.md"><strong>简体中文文档</strong></a> ·
  <a href="#-why-danqing">Why Danqing</a> ·
  <a href="#-quickstart--zero-cost-deployment">Quickstart &amp; Cloud</a> ·
  <a href="#-manuscript-match--the-277-palettes">Manuscript Match &amp; 277 Palettes</a> ·
  <a href="#-agent-plugin--mcp-server">Plugin &amp; MCP</a> ·
  <a href="#-citation--attribution">Citation</a>
</p>

[![Live Studio](https://img.shields.io/badge/Live_Studio-danqing.onrender.com-C84B31?style=flat-square&logo=googlechrome&logoColor=white)](https://danqing.onrender.com)
[![CI Status](https://github.com/owehann/danqing/actions/workflows/ci.yml/badge.svg)](https://github.com/owehann/danqing/actions/workflows/ci.yml)
[![Deploy to Render](https://img.shields.io/badge/Deploy_to_Render-Free_%240_Blueprint-0D9488?style=flat-square&logo=render)](https://render.com/deploy?repo=https://github.com/owehann/danqing)
[![Palettes: 277 Verified](https://img.shields.io/badge/Palettes-277_Primary--Source_Verified-C84B31?style=flat-square)](#-manuscript-match--the-277-palettes)
[![Plugin + MCP](https://img.shields.io/badge/Antigravity_%2B_MCP-danqing__mcp-0F766E?style=flat-square)](#-agent-plugin--mcp-server)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-0284C7?style=flat-square)](./LICENSE)

</div>

<br/>

## ✨ Why Danqing

Scientists and students shouldn't lose hours tweaking hex codes, re-running plotting scripts twenty times, and staring at harsh or muddy colors just to make manuscript figures comfortable to read.

**Danqing (丹青)** lets every scholar recolor finished vector figures — PDFs and SVGs exported from **R (`ggplot2`)**, **Python (`matplotlib` / `seaborn` / `scanpy`)**, **GraphPad Prism**, or **Adobe Illustrator** — in seconds, free and open-source, without altering a single coordinate, text glyph, or raw experimental image pixel.

<table width="100%">
  <tr>
    <td width="50%" valign="top">
      <h3>📖 1. One-Click Manuscript Match</h3>
      <p>Pick a scholarly tone (<em>CNS Clean</em>, <em>Clinical</em>, <em>Omics Atlas</em>, <em>Mineral &amp; Museum</em>) or type your target journal and field (optional Gemini 2.5 Flash + built-in perceptual comfort ranker) to match the whole paper's figure set without trial-and-error.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🎯 2. Lossless Vector Engine &amp; Gate G0 Shield</h3>
      <p>Parses PDF content streams and SVG stylesheets under strict <code>preview == export</code> parity while physically locking <strong>Western blot lanes, H&amp;E sections, immunofluorescence, and EM micrographs</strong> (verified bit-identical on export).</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>🎨 3. 277 Primary-Source Palettes</h3>
      <p>Spans <strong>Accessible</strong> (Okabe–Ito, Petroff IEEE VIS, Paul Tol), <strong>Journal-Inspired</strong> (NPG/NEJM/Lancet, CNS Iso-Chroma), <strong>World Museums</strong> (<code>MetBrewer</code>, <code>MoMAColors</code>), <strong>24 CC0 Eastern Mineral Artifacts</strong>, <strong>Single-Cell 64+</strong>, and <strong>Crameri v8.0 / cmocean</strong> continuous maps.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🤖 4. Antigravity Plugin, MCP &amp; Zero-Retention Privacy</h3>
      <p>Ships with a native <strong>MCP server (<code>danqing_mcp</code>)</strong> and <code>plugin.json</code> for Google Antigravity, Claude Code, and Cursor, plus <strong>100% RAM-only multi-visitor isolation</strong> and ready-to-paste <code>ggplot2</code> &amp; <code>matplotlib</code> export snippets.</p>
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

### Option A · Use Online Immediately (Free Forever)
Open **[https://danqing.onrender.com](https://danqing.onrender.com)** in any desktop browser (`≥ 600 px`).

### Option B · Local Studio (3 Commands)

```bash
pip install -e ".[dev]"
(cd web/frontend && pnpm install && pnpm build)
./scripts/start_studio.sh
```

Open `http://127.0.0.1:8765`.

### Option C · Instant Share Link or Self-Hosted \$0 Cloud

```bash
./scripts/share_public.sh          # Public HTTPS link via Cloudflare Quick Tunnel ($0)
./scripts/share_public.sh --lan    # Lab / campus Wi-Fi LAN mode ($0)
```

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/owehann/danqing)

---

## 🎨 Manuscript Match & The 277 Palettes

Click **Manuscript Match (`论文配色定调`)** in the studio sidebar to select a journal aesthetic (`CNS Clean`, `Clinical`, `Omics Atlas`, `Mineral & Museum`) or describe your manuscript (with optional session-only Google AI Studio Gemini key support and zero-cost perceptual fallback).

| Collection | Count | Representative Palettes & Provenance |
| :--- | :---: | :--- |
| **Accessible** | `16` | Okabe–Ito, Petroff 6/8/10 (*Matplotlib 3.10 / IEEE VIS*), IBM Safe, Paul Tol (*Bright, Vibrant, Muted, High-Contrast*), CARTO Safe, ColorBrewer Dark2 |
| **Journal & Data-Vis** | `29` | NPG, AAAS, NEJM, Lancet, JAMA, JCO, BMJ (`*-inspired`), LocusZoom GWAS, Observable 10, Tableau 10, Seaborn, Scanpy 10, CNS Iso-Chroma Harmony 12 |
| **Museum, Art & Nature** | `116` | 56 Metropolitan Museum of Art (`MetBrewer`, CC0), 30 MoMA (`MoMAColors`, MIT), 10 `PNWColors` (CC0), 15 `NatParksPalettes` (MIT), 5 cinema classics |
| **Eastern Artifacts (CC0)** | `24` | Deterministic extraction from 48 CC0 Cleveland Museum of Art photographs: Shang bronzes, Tang Sancai, Song Ru/Jun/Longquan celadons, Zhao Mengfu blue-green landscape, Chenghua Doucai, Hokusai Red Fuji, Himalayan mineral thangkas |
| **Many Colors (Single-Cell)** | `13` | Polychrome 34, Green-Armytage 25, Scanpy 20, Zeileis 26 & Ultra-Cluster 64, Kelly 22, Glasbey 32 + dynamic hull expansion (`K > N`) |
| **Continuous & Diverging** | `73` | Crameri *Scientific colour maps* v8.0 (`batlowW`, `lipari`, `navia`, `vik`, `roma`, `bam`), `cmocean` (`thermal`, `haline`, `balance`), Viridis/Cividis, ColorBrewer 2.0, zero-midpoint lock |
| **Domain Conventions** | `6` | COSMIC SBS-6 mutational signatures, Manhattan alternating chromosomes, Volcano `Up/Down/NS`, Cell Cycle `G1/S/G2M`, CNV `Gain/Loss/Neutral`, `A/C/G/T` bases |

---

## 🤖 Agent Plugin & MCP Server

Danqing is packaged as a ready-to-use **Google Antigravity Plugin** ([`plugin.json`](./plugin.json) + [`mcp_config.json`](./mcp_config.json) + [`skills/danqing/SKILL.md`](./skills/danqing/SKILL.md)) and standard **MCP stdio server** (`danqing-mcp` / `python -m danqing.mcp_server`) exposing four tools:

- `danqing_inspect_figure` — Inspect discrete groups, panels, continuous scales, protected raw images, and deuteranopia diagnostics.
- `danqing_match_manuscript_palettes` — Recommend the 3 most comfortable palettes for a figure or manuscript brief.
- `danqing_recolor_figure` — Losslessly recolor a `.pdf` or `.svg` with byte-level geometry/image verification plus `.palette.R` & `.palette.py` code output.
- `danqing_list_palettes` — Search and filter the 277 verified palettes.

---

## 📝 Citation & Attribution

Created and maintained by **Xinyin Han** ([@owehann](https://github.com/owehann)). If Danqing saves you time preparing figures or manuscripts, please cite the software (GitHub's **Cite this repository** button reads [`CITATION.cff`](./CITATION.cff) automatically):

```bibtex
@software{han2026danqing,
  author       = {Han, Xinyin},
  title        = {{Danqing: Lossless Scientific Figure \& Manuscript Recoloring Studio}},
  year         = {2026},
  version      = {0.3.0},
  url          = {https://github.com/owehann/danqing},
  license      = {Apache-2.0}
}
```

- **Code & Brand Assets**: [Apache License 2.0](./LICENSE) — Copyright © 2026 Xinyin Han (`0` GPL/AGPL runtime dependencies).
- **Palette Provenance & Public Benchmark Datasets**: Documented in [`NOTICE`](./NOTICE) and [`core/danqing/palettes/VERIFICATION.md`](./core/danqing/palettes/VERIFICATION.md).
