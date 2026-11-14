<div align="center">

<img src="./assets/logo.png" alt="丹青叠璧 · Danqing Albers Mineral Seal" width="128" height="128" />

# 丹青 · Danqing

### 赋科研以丹青，守数据之本真
#### New color for discovery, faithful to every datum

<p>
  <a href="./README.md"><strong>English Documentation</strong></a> ·
  <a href="#-为什么做丹青">为什么做丹青</a> ·
  <a href="#-快速使用与零成本部署">快速使用与云部署</a> ·
  <a href="#-论文配色定调与-277-套核验色库">论文配色定调与色库</a> ·
  <a href="#-agent-插件与-mcp-服务">Agent 插件与 MCP</a> ·
  <a href="#-软件署名与引用">软件署名</a>
</p>

[![Live Studio](https://img.shields.io/badge/在线工作台-danqing.onrender.com-C84B31?style=flat-square&logo=googlechrome&logoColor=white)](https://danqing.onrender.com)
[![CI Status](https://github.com/owehann/danqing/actions/workflows/ci.yml/badge.svg)](https://github.com/owehann/danqing/actions/workflows/ci.yml)
[![Deploy to Render](https://img.shields.io/badge/Render_免费云部署-%240_免绑卡蓝图-0D9488?style=flat-square&logo=render)](https://render.com/deploy?repo=https://github.com/owehann/danqing)
[![Palettes: 277 Verified](https://img.shields.io/badge/权威调色板-277_套溯源核验-C84B31?style=flat-square)](#-论文配色定调与-277-套核验色库)
[![Plugin + MCP](https://img.shields.io/badge/Antigravity_%2B_MCP-danqing__mcp-0F766E?style=flat-square)](#-agent-插件与-mcp-服务)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-0284C7?style=flat-square)](./LICENSE)

</div>

<br/>

## ✨ 为什么做丹青

科研人与学生不该把宝贵的时间和心流浪费在反复凑十六进制色号、改完脚本重跑二十遍、盯着刺眼或发灰的配色越看越烦躁的内耗里。

**丹青（Danqing）** 免费开源地服务每一位研究者——不动分毫原始数据坐标、字体排版与实验像素，为 **R (`ggplot2`)**、**Python (`matplotlib` / `seaborn` / `scanpy`)**、**GraphPad Prism** 与 **Adobe Illustrator** 导出的 PDF 或 SVG 矢量图一键换上舒适、和谐、经得起审稿检验的科学配色。

<table width="100%">
  <tr>
    <td width="50%" valign="top">
      <h3>📖 1.「论文配色定调」一键匹配</h3>
      <p>内置<strong>顶刊清朗、临床医学、高维组学、温润博物</strong>四大刊风预设及期刊/课题自由匹配（支持接入免费 Gemini 2.5 Flash 推理与内置视觉舒适度排序引擎），无需在数百套色板里盲目试错，整篇论文多图瞬间统一格调。</p>
    </td>
    <td width="50%" valign="top">
      <h3>🎯 2. 无损矢量引擎与原始证据护盾</h3>
      <p>深度解析 PDF 内容流与 SVG 样式表（严格满足 <code>预览 == 导出</code>），自动识别并物理锁定图表内嵌的 <strong>Western blot 条带、H&amp;E 病理切片、免疫荧光与电镜原图</strong>，导出前后逐字节一致。</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>🎨 3. 7 大馆藏级核验色库（277 套）</h3>
      <p>囊括<strong>色盲无障碍标准</strong>（Okabe–Ito、Petroff、Paul Tol）、<strong>期刊启发风格</strong>（NPG/NEJM/Lancet、CNS 等彩度十二色）、<strong>世界艺术馆藏</strong>（大都会 <code>MetBrewer</code>、MoMA）、<strong>24 套克利夫兰博物馆 CC0 东方器物矿物色</strong>、<strong>单细胞多簇</strong>与 <strong>Crameri v8.0 / cmocean</strong> 连续色阶。</p>
    </td>
    <td width="50%" valign="top">
      <h3>🤖 4. 原生 Agent 插件、MCP 与零留存隐私</h3>
      <p>原生附带 <strong>Google Antigravity 插件清单</strong>与 <strong>MCP 服务（<code>danqing_mcp</code>）</strong>，一句话即可在 AI 助手中自动完成无损换色与 R/Python 代码生成；网页端采用 <strong>100% 纯内存零落盘 + 多访客密码学隔离</strong>。</p>
    </td>
  </tr>
</table>

<br/>

<div align="center">
  <img src="./assets/icon_system.png" alt="丹青叠璧 · Danqing Albers Mineral Seal 视觉识别系统" width="880" />
</div>

<br/>

---

## 🚀 快速使用与零成本部署

### 方式一：打开网页直接使用（永久免费）
在桌面浏览器（宽度 `≥ 600 px`）直接访问：**[https://danqing.onrender.com](https://danqing.onrender.com)**

### 方式二：本地工作台启动（3 条命令）

```bash
pip install -e ".[dev]"
(cd web/frontend && pnpm install && pnpm build)
./scripts/start_studio.sh
```

浏览器打开 `http://127.0.0.1:8765`。

### 方式三：免账号临时分享或自建 \$0 云实例

```bash
./scripts/share_public.sh          # 生成 https://*.trycloudflare.com 公网加密链接 ($0)
./scripts/share_public.sh --lan    # 同一实验室 / 校园 Wi-Fi 局域网高速模式 ($0)
```

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/owehann/danqing)

---

## 🎨 论文配色定调与 277 套核验色库

在右侧调色板栏顶部点击 **「论文配色定调」**，即可按投稿刊风（`顶刊清朗` / `临床医学` / `高维组学` / `温润博物`）或自由输入课题方向，自动根据当前图表的组别数量与连续热图结构筛出最舒适耐看的 3 套推荐方案（悬停即刻预览，点击一键应用）。

| 分类 | 数量 | 代表配色与学术/馆藏溯源 |
| :--- | :---: | :--- |
| **色盲友好（Accessible）** | `16` | Okabe–Ito、Petroff 6/8/10（*IEEE VIS / Matplotlib 3.10*）、IBM Safe、Paul Tol 全系列、CARTO Safe、ColorBrewer Dark2 |
| **期刊与现代数据科学（Journal）** | `29` | NPG、AAAS、NEJM、Lancet、JAMA、JCO、BMJ（`*-inspired`）、LocusZoom GWAS、Observable 10、Tableau 10、Scanpy 10、CNS 等彩度和谐十二色 |
| **世界馆藏与自然博物（Museum）** | `116` | 大都会博物馆 `MetBrewer` 全集 56 套（CC0）、现代艺术博物馆 `MoMAColors` 30 套（MIT）、太平洋海岸 `PNWColors`、国家公园 `NatParksPalettes` |
| **东方馆藏器物（Eastern · CC0）** | `24` | 自克利夫兰艺术博物馆 48 幅 CC0 高清藏品确定性提取：商青铜爵、唐螺钿镜与三彩、宋汝钧天青霞紫、龙泉青瓷、赵孟頫青绿山水、明成化斗彩、北斋赤富士、雪域矿物唐卡绿度母 |
| **单细胞/空间多簇（Many Colors）** | `13` | Polychrome 34、Green-Armytage 25、Scanpy 20、Zeileis 26 / Ultra-Cluster 64、Kelly 22、Glasbey 32 + 动态多簇扩展 |
| **连续与发散色阶（Continuous）** | `73` | Crameri v8.0 科学色阶 25 套（`batlowW`、`lipari`、`navia`、`vik`、`roma`）、`cmocean` 13 套、Viridis/Cividis、ColorBrewer 2.0，发散色阶自动锁定零点 |
| **学科常规约定（Conventions）** | `6` | COSMIC SBS-6 突变谱、曼哈顿图染色体双色、火山图 `Up/Down/NS`、细胞周期 `G1/S/G2M`、拷贝数 `Gain/Loss/Neutral`、四碱基 `A/C/G/T` |

---

## 🤖 Agent 插件与 MCP 服务

本仓库内置标准 **Google Antigravity 插件清单**（[`plugin.json`](./plugin.json) + [`mcp_config.json`](./mcp_config.json) + [`skills/danqing/SKILL.md`](./skills/danqing/SKILL.md)）与零额外依赖的 **MCP 标准服务端**（`danqing-mcp` / `python -m danqing.mcp_server`），提供 4 个确定性工具：

- `danqing_inspect_figure` — 解析 PDF/SVG 分栏、离散组别、连续色阶、受保护实验原图与色盲安全指标；
- `danqing_match_manuscript_palettes` — 根据论文期刊与组数一键推荐 3 套最舒适和谐的科研色板；
- `danqing_recolor_figure` — 字节级无损换色导出，并同步写出 `.palette.R`（`ggplot2`）与 `.palette.py`（`matplotlib`）代码；
- `danqing_list_palettes` — 按分类、颜色数或无障碍属性检索全部 277 套核验色库。

---

## 📝 软件署名与引用

本项目由 **Xinyin Han**（[@owehann](https://github.com/owehann)）设计开发并开源维护。若丹青为你节省了论文改图与配色的时间，欢迎在致谢或软件引用中署名（GitHub 右侧栏 **Cite this repository** 按钮可直接读取 [`CITATION.cff`](./CITATION.cff)）：

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

- **核心代码与视觉资产**：[Apache License 2.0](./LICENSE) — Copyright © 2026 Xinyin Han（零 GPL/AGPL 运行时依赖）。
- **调色板文献与公开数据集溯源**：详见 [`NOTICE`](./NOTICE) 与 [`core/danqing/palettes/VERIFICATION.md`](./core/danqing/palettes/VERIFICATION.md)。
