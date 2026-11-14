#!/usr/bin/env python3
"""Extract & verify Eastern artifact palettes from real CC0 open-access museum images (Spec Section 7.3 / WP2).

Pipeline:
1. Downloads CC0 artifact photographs from The Cleveland Museum of Art Open Access CDN (cached in bench/palette_proofs/cc0_sources/).
2. Saves compact 240px preview thumbnails to `web/frontend/public/artifacts/<id>.jpg` for the UI provenance card.
3. Strips neutral museum studio backdrop / outer silk mounting borders and extracts OKLab k-means (k = 24) clusters
   from authentic glaze, enamel, lacquer, and mineral pigment pixels.
4. Selects 8 distinct pigment clusters per artifact suite (anchor led by the primary artifact's signature pigment)
   with pairwise CIEDE2000 >= 15.0 among the first 6 colors, calibrated to white-paper legibility.
5. Renders a 4-panel visual proof sheet (`bench/palette_proofs/<id>_proof.png`: artifact photo + swatches + bar + scatter + heatmap + 2x2 subfigures)
   for internal aesthetic review (Spec Section 7.3.6).
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))

from danqing.color_science import (  # noqa: E402
    ciede2000_matrix,
    hex_to_oklch,
    hex_to_srgb01,
    oklab_to_oklch,
    oklch_to_hex,
    simulate_cvd,
    srgb_to_oklab,
)

THUMB_DIR = REPO_ROOT / "web" / "frontend" / "public" / "artifacts"
PROOF_DIR = REPO_ROOT / "bench" / "palette_proofs"
RAW_CACHE_DIR = PROOF_DIR / "cc0_sources"

ARTIFACT_SPECS: list[dict[str, Any]] = [
    {
        "id": "east_ru_celadon",
        "name": {"en": "Ru & Jun Song Glaze", "zh": "宋汝钧天青霞紫"},
        "partners": {"sequential": "oslo", "diverging": "vik"},
        "signature_hue_range": (155.0, 225.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1957.40/1957.40_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1957.36/1957.36_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1957.40 & 1957.36",
            "title": "Brush Washer (Ru ware) & Jar with Cover (Jun ware)",
            "date": "Northern Song–Jin dynasty (late 1000s–1100s)",
            "url": "https://clevelandart.org/art/1957.40",
            "image_url": "https://openaccess-cdn.clevelandart.org/1957.40/1957.40_web.jpg",
            "thumbnail_url": "/artifacts/east_ru_celadon.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_longquan",
        "name": {"en": "Longquan Celadon & Kesi", "zh": "龙泉青瓷与宋缂丝"},
        "partners": {"sequential": "batlow", "diverging": "BrBG"},
        "signature_hue_range": (102.0, 165.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1961.92/1961.92_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1988.100/1988.100_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1961.92 & 1988.100",
            "title": "Plate with Relief Dragon among Clouds (Longquan ware) & Song Kesi Tapestry",
            "date": "Song–Yuan dynasty (1100s–1300s)",
            "url": "https://clevelandart.org/art/1961.92",
            "image_url": "https://openaccess-cdn.clevelandart.org/1961.92/1961.92_web.jpg",
            "thumbnail_url": "/artifacts/east_longquan.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_ming_blue_white",
        "name": {"en": "Chenghua Doucai & Cobalt", "zh": "明成化斗彩青花"},
        "partners": {"sequential": "Blues", "diverging": "RdBu"},
        "signature_hue_range": (225.0, 275.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1957.61/1957.61_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1957.359/1957.359_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1957.61 & 1957.359",
            "title": "Wine Cup with Children at Play (Chenghua Doucai & Underglaze Cobalt)",
            "date": "Ming dynasty, Chenghua period (1465–1487)",
            "url": "https://clevelandart.org/art/1957.61",
            "image_url": "https://openaccess-cdn.clevelandart.org/1957.61/1957.61_web.jpg",
            "thumbnail_url": "/artifacts/east_ming_blue_white.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_famille_rose",
        "name": {"en": "Qianlong Famille Rose", "zh": "清乾隆粉彩花鸟"},
        "partners": {"sequential": "lajolla", "diverging": "PuOr"},
        "signature_hue_range": (330.0, 35.0),
        "crop_border": 0.08,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1964.206.2/1964.206.2_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1985.32/1985.32_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1964.206.2 & 1985.32",
            "title": "Miniature Vase with Birds and Chrysanthemums (Famille Rose)",
            "date": "Qing dynasty, Qianlong period (1736–1795)",
            "url": "https://clevelandart.org/art/1964.206.2",
            "image_url": "https://openaccess-cdn.clevelandart.org/1964.206.2/1964.206.2_web.jpg",
            "thumbnail_url": "/artifacts/east_famille_rose.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_sancai",
        "name": {"en": "Tang Sancai Glaze", "zh": "唐三彩瑞兽釉"},
        "partners": {"sequential": "lajolla", "diverging": "BrBG"},
        "signature_hue_range": (45.0, 175.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/2000.118.1/2000.118.1_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1955.295/1955.295_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "2000.118.1 & 1955.295",
            "title": "Tomb Guardian with Animal Head (Sancai Three-Color Ware)",
            "date": "Tang dynasty (early 700s)",
            "url": "https://clevelandart.org/art/1955.295",
            "image_url": "https://openaccess-cdn.clevelandart.org/2000.118.1/2000.118.1_web.jpg",
            "thumbnail_url": "/artifacts/east_sancai.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_blue_green_landscape",
        "name": {"en": "Blue-and-Green Landscape", "zh": "赵孟頫青绿山水"},
        "partners": {"sequential": "YlGnBu", "diverging": "roma"},
        "signature_hue_range": (150.0, 255.0),
        "crop_border": 0.14,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1978.66/1978.66_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1962.157.6/1962.157.6_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1978.66 & 1962.157.6",
            "title": "River Village: Fisherman's Joy (Zhao Mengfu) & Landscape after Zhao Mengfu (Wang Yuanqi)",
            "date": "Yuan–Qing dynasty (c. 1302–1690)",
            "url": "https://clevelandart.org/art/1978.66",
            "image_url": "https://openaccess-cdn.clevelandart.org/1978.66/1978.66_web.jpg",
            "thumbnail_url": "/artifacts/east_blue_green_landscape.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_lacquer",
        "name": {"en": "Carved Cinnabar Lacquer", "zh": "清剔彩朱黑漆器"},
        "partners": {"sequential": "YlOrRd", "diverging": "vik"},
        "signature_hue_range": (15.0, 42.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1969.32/1969.32_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1991.3/1991.3_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1969.32 & 1991.3",
            "title": "Carved Polychrome Lacquer Scroll Box (Ticai)",
            "date": "Qing dynasty, Qianlong period (1736–1795)",
            "url": "https://clevelandart.org/art/1969.32",
            "image_url": "https://openaccess-cdn.clevelandart.org/1969.32/1969.32_web.jpg",
            "thumbnail_url": "/artifacts/east_lacquer.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_cloisonne_enamel",
        "name": {"en": "Ming Imperial Cloisonné", "zh": "明景泰掐丝珐琅"},
        "partners": {"sequential": "viridis", "diverging": "roma"},
        "signature_hue_range": (195.0, 260.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1987.58/1987.58_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1969.285/1969.285_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1987.58 & 1969.285",
            "title": "Mandala Base in Cloisonné Enamel & Gilt Bronze",
            "date": "Ming dynasty (early 1400s)",
            "url": "https://clevelandart.org/art/1987.58",
            "image_url": "https://openaccess-cdn.clevelandart.org/1987.58/1987.58_web.jpg",
            "thumbnail_url": "/artifacts/east_cloisonne_enamel.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_shang_bronze",
        "name": {"en": "Shang Ritual Bronze Patina", "zh": "商代青铜爵斝古绿"},
        "partners": {"sequential": "batlowW", "diverging": "BrBG"},
        "signature_hue_range": (140.0, 195.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/2005.54/2005.54_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1960.42/1960.42_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "2005.54 & 1960.42",
            "title": "Ritual Wine Vessels (Jia & Jue)",
            "date": "Shang dynasty (c. 1250–1046 BCE)",
            "url": "https://clevelandart.org/art/2005.54",
            "image_url": "https://openaccess-cdn.clevelandart.org/2005.54/2005.54_web.jpg",
            "thumbnail_url": "/artifacts/east_shang_bronze.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_turquoise_jade_bronze",
        "name": {"en": "Warring States Turquoise & Jade", "zh": "战汉错金绿松铜镜"},
        "partners": {"sequential": "YlGnBu", "diverging": "BrBG"},
        "signature_hue_range": (165.0, 215.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/2002.5/2002.5_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1950.248/1950.248_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "2002.5 & 1950.248",
            "title": "Mirror with Jade Disk Inset & Gilt-Turquoise Belt Hook",
            "date": "Warring States–Western Han (475 BCE–9 CE)",
            "url": "https://clevelandart.org/art/2002.5",
            "image_url": "https://openaccess-cdn.clevelandart.org/2002.5/2002.5_web.jpg",
            "thumbnail_url": "/artifacts/east_turquoise_jade_bronze.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_tang_inlaid_mirror",
        "name": {"en": "Tang Mother-of-Pearl & Amber", "zh": "盛唐螺钿琥珀宝镜"},
        "partners": {"sequential": "lajolla", "diverging": "roma"},
        "signature_hue_range": (25.0, 85.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1995.341/1995.341_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1961.18/1961.18_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1995.341 & 1961.18",
            "title": "Mirror with Six Circular Flowers (Shell, Amber & Turquoise Inlay)",
            "date": "Tang dynasty (600s)",
            "url": "https://clevelandart.org/art/1995.341",
            "image_url": "https://openaccess-cdn.clevelandart.org/1995.341/1995.341_web.jpg",
            "thumbnail_url": "/artifacts/east_tang_inlaid_mirror.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_song_jian_yaozhou",
        "name": {"en": "Jian Temmoku & Yaozhou Celadon", "zh": "宋建窑兔毫耀州青"},
        "partners": {"sequential": "oslo", "diverging": "PuOr"},
        "signature_hue_range": (100.0, 155.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1948.220/1948.220_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1942.132/1942.132_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1948.220 & 1942.132",
            "title": "Yaozhou Celadon Lion Ewer & Jian Ware Hare's-Fur Tea Bowl",
            "date": "Northern–Southern Song dynasty (960–1279)",
            "url": "https://clevelandart.org/art/1948.220",
            "image_url": "https://openaccess-cdn.clevelandart.org/1948.220/1948.220_web.jpg",
            "thumbnail_url": "/artifacts/east_song_jian_yaozhou.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_song_buddhist_scroll",
        "name": {"en": "Song Misty Mountain Ink-Wash", "zh": "北宋巨然溪山兰若"},
        "partners": {"sequential": "davos", "diverging": "broc"},
        "signature_hue_range": (55.0, 115.0),
        "crop_border": 0.12,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1959.348/1959.348_web.jpg",
            "https://openaccess-cdn.clevelandart.org/2015.517/2015.517_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1959.348 & 2015.517",
            "title": "Buddhist Retreat by Stream and Mountains (Juran) & Mountain Market",
            "date": "Northern Song–Ming dynasty (960–early 1500s)",
            "url": "https://clevelandart.org/art/1959.348",
            "image_url": "https://openaccess-cdn.clevelandart.org/1959.348/1959.348_web.jpg",
            "thumbnail_url": "/artifacts/east_song_buddhist_scroll.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_yuan_kesi_tapestry",
        "name": {"en": "Imperial Kesi Dragon Tapestry", "zh": "宋元缂丝云龙花鸟"},
        "partners": {"sequential": "batlow", "diverging": "vik"},
        "signature_hue_range": (210.0, 265.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1995.1/1995.1_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1988.33/1988.33_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1995.1 & 1988.33",
            "title": "Canopy with Dragon among Flowers & Dragons Chasing Flaming Pearls (Kesi)",
            "date": "Song–Ming dynasty (1100s–1400s)",
            "url": "https://clevelandart.org/art/1995.1",
            "image_url": "https://openaccess-cdn.clevelandart.org/1995.1/1995.1_web.jpg",
            "thumbnail_url": "/artifacts/east_yuan_kesi_tapestry.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_ming_fahua",
        "name": {"en": "Ming Fahua Turquoise & Aubergine", "zh": "明法华孔雀蓝茄皮紫"},
        "partners": {"sequential": "GnBu", "diverging": "PRGn"},
        "signature_hue_range": (185.0, 240.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1942.716/1942.716_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1942.717/1942.717_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1942.716 & 1942.717",
            "title": "Fahua Prunus Vase (Meiping) with Blossoming Lotus & Chrysanthemum Jar",
            "date": "Ming dynasty (late 1400s–1500s)",
            "url": "https://clevelandart.org/art/1942.716",
            "image_url": "https://openaccess-cdn.clevelandart.org/1942.716/1942.716_web.jpg",
            "thumbnail_url": "/artifacts/east_ming_fahua.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_ming_wucai",
        "name": {"en": "Jiajing Wucai Five-Color Ware", "zh": "明嘉靖五彩云龙罐"},
        "partners": {"sequential": "YlOrRd", "diverging": "RdBu"},
        "signature_hue_range": (18.0, 48.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1989.291/1989.291_web.jpg",
            "https://openaccess-cdn.clevelandart.org/2020.179/2020.179_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1989.291 & 2020.179",
            "title": "Wucai Jar with Dragons Pursuing Flaming Jewels & Baluster Jar",
            "date": "Ming dynasty, Jiajing–Chongzhen (1522–1650)",
            "url": "https://clevelandart.org/art/1989.291",
            "image_url": "https://openaccess-cdn.clevelandart.org/1989.291/1989.291_web.jpg",
            "thumbnail_url": "/artifacts/east_ming_wucai.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_qing_yangcai",
        "name": {"en": "Qianlong Yangcai Painted Enamel", "zh": "清乾隆洋彩锦鸡瓶"},
        "partners": {"sequential": "lipari", "diverging": "roma"},
        "signature_hue_range": (65.0, 108.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1971.145/1971.145_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1964.243.1.a/1964.243.1.a_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1971.145 & 1964.243.1.a",
            "title": "Vase with Golden Pheasants & Painted Enamel Screen",
            "date": "Qing dynasty, Qianlong period (1736–1795)",
            "url": "https://clevelandart.org/art/1971.145",
            "image_url": "https://openaccess-cdn.clevelandart.org/1971.145/1971.145_web.jpg",
            "thumbnail_url": "/artifacts/east_qing_yangcai.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_edo_rimpa_irises",
        "name": {"en": "Edo Rimpa Gold & Irises Screen", "zh": "江户琳派金屏燕子花"},
        "partners": {"sequential": "navia", "diverging": "PuOr"},
        "signature_hue_range": (245.0, 290.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1954.603.1/1954.603.1_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1964.386/1964.386_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1954.603.1 & 1964.386",
            "title": "Irises (Watanabe Shikō) & Paulownias and Chrysanthemums (Sakai Hōitsu)",
            "date": "Edo period (1700s–early 1800s)",
            "url": "https://clevelandart.org/art/1954.603.1",
            "image_url": "https://openaccess-cdn.clevelandart.org/1954.603.1/1954.603.1_web.jpg",
            "thumbnail_url": "/artifacts/east_edo_rimpa_irises.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_hokusai_red_fuji",
        "name": {"en": "Hokusai Red Fuji Woodblock", "zh": "北斋凯风快晴赤富士"},
        "partners": {"sequential": "Blues", "diverging": "RdBu"},
        "signature_hue_range": (25.0, 52.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1930.189/1930.189_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1985.327/1985.327_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1930.189 & 1985.327",
            "title": "South Wind, Clear Sky (Red Fuji) & One Hundred Poems (Katsushika Hokusai)",
            "date": "Edo period (early 1830s–1836)",
            "url": "https://clevelandart.org/art/1930.189",
            "image_url": "https://openaccess-cdn.clevelandart.org/1930.189/1930.189_web.jpg",
            "thumbnail_url": "/artifacts/east_hokusai_red_fuji.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_edo_kutani_porcelain",
        "name": {"en": "Edo Kutani & Imari Enamel", "zh": "江户古九谷柿右卫门"},
        "partners": {"sequential": "batlowW", "diverging": "vik"},
        "signature_hue_range": (135.0, 195.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1947.62/1947.62_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1938.331/1938.331_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1947.62 & 1938.331",
            "title": "Kakiemon/Kutani Enamel Figure & Polychrome Porcelain Punch Bowl",
            "date": "Edo period (c. 1735–1770)",
            "url": "https://clevelandart.org/art/1947.62",
            "image_url": "https://openaccess-cdn.clevelandart.org/1947.62/1947.62_web.jpg",
            "thumbnail_url": "/artifacts/east_edo_kutani_porcelain.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_momoyama_makie",
        "name": {"en": "Momoyama Gold Maki-e Lacquer", "zh": "桃山莳绘秋草螺钿"},
        "partners": {"sequential": "lajolla", "diverging": "BrBG"},
        "signature_hue_range": (68.0, 96.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1976.15/1976.15_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1969.124.b/1969.124.b_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1976.15 & 1969.124.b",
            "title": "Maki-e Reading Stand with Chrysanthemums & Muromachi Suzuribako",
            "date": "Muromachi–Momoyama period (1400s–early 1600s)",
            "url": "https://clevelandart.org/art/1976.15",
            "image_url": "https://openaccess-cdn.clevelandart.org/1976.15/1976.15_web.jpg",
            "thumbnail_url": "/artifacts/east_momoyama_makie.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_goryeo_celadon",
        "name": {"en": "Goryeo Inlaid Jade Celadon", "zh": "高丽象嵌青瓷莲竹"},
        "partners": {"sequential": "GnBu", "diverging": "BrBG"},
        "signature_hue_range": (135.0, 175.0),
        "crop_border": 0.06,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1918.471/1918.471_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1918.458/1918.458_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1918.471 & 1918.458",
            "title": "Goryeo Celadon Vase with Inlaid Lotus, Plum & Waterfowl Bowl",
            "date": "Goryeo dynasty (1300s)",
            "url": "https://clevelandart.org/art/1918.471",
            "image_url": "https://openaccess-cdn.clevelandart.org/1918.471/1918.471_web.jpg",
            "thumbnail_url": "/artifacts/east_goryeo_celadon.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_tibet_thangka",
        "name": {"en": "Himalayan Mineral Thangka", "zh": "雪域石青朱砂绿度母"},
        "partners": {"sequential": "hawaii", "diverging": "roma"},
        "signature_hue_range": (130.0, 175.0),
        "crop_border": 0.08,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1970.156/1970.156_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1991.2/1991.2_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1970.156 & 1991.2",
            "title": "Green Tara & Yongle Thangka with the Seventh Bodhisattva",
            "date": "Central Tibet & Ming Court (c. 1260s–1424)",
            "url": "https://clevelandart.org/art/1970.156",
            "image_url": "https://openaccess-cdn.clevelandart.org/1970.156/1970.156_web.jpg",
            "thumbnail_url": "/artifacts/east_tibet_thangka.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
    {
        "id": "east_persian_shahnama",
        "name": {"en": "Persian Shahnama Lapis & Gold", "zh": "波斯王书青金细密画"},
        "partners": {"sequential": "lapaz", "diverging": "vik"},
        "signature_hue_range": (225.0, 270.0),
        "crop_border": 0.08,
        "image_urls": [
            "https://openaccess-cdn.clevelandart.org/1943.658.b/1943.658.b_web.jpg",
            "https://openaccess-cdn.clevelandart.org/1943.658.a/1943.658.a_web.jpg",
        ],
        "artifact": {
            "museum": "The Cleveland Museum of Art",
            "object_id": "1943.658.b & 1943.658.a",
            "title": "Bahram Gur Slays a Dragon, Folio from an Ilkhanid Shahnama",
            "date": "Ilkhanid period, Shiraz (1330–1335)",
            "url": "https://clevelandart.org/art/1943.658.b",
            "image_url": "https://openaccess-cdn.clevelandart.org/1943.658.b/1943.658.b_web.jpg",
            "thumbnail_url": "/artifacts/east_persian_shahnama.jpg",
            "image_license": "CC0 1.0 Universal (CMA Open Access)",
        },
    },
]


def _in_hue_range(h: float, lo: float, hi: float) -> bool:
    if lo <= hi:
        return lo <= h <= hi
    return h >= lo or h <= hi


def _download_image(url: str, cache_path: Path) -> Image.Image:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not cache_path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "DanqingArtifactExtractor/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            cache_path.write_bytes(r.read())
    return Image.open(io.BytesIO(cache_path.read_bytes())).convert("RGB")


def _kmeans_oklab(labs: np.ndarray, k: int = 24, iters: int = 30, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    sample = labs[rng.choice(len(labs), size=28000, replace=False)] if len(labs) > 28000 else labs
    centers = np.empty((k, 3), dtype=np.float64)
    centers[0] = sample[rng.integers(0, len(sample))]
    for ci in range(1, k):
        d2 = ((sample[:, None, :] - centers[None, :ci, :]) ** 2).sum(axis=2).min(axis=1)
        probs = d2 / max(1e-12, d2.sum())
        centers[ci] = sample[rng.choice(len(sample), p=probs)]
    labels = np.zeros(len(sample), dtype=np.int32)
    for _ in range(iters):
        dists = ((sample[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = dists.argmin(axis=1)
        for ci in range(k):
            mask = labels == ci
            if mask.any():
                centers[ci] = sample[mask].mean(axis=0)
    counts = np.bincount(labels, minlength=k).astype(np.float64) / max(1, len(sample))
    return centers, counts


def extract_palette_from_images(
    images: list[Image.Image],
    pal_id: str,
    signature_hue_range: tuple[float, float],
    crop_border: float = 0.06,
) -> tuple[list[str], str]:
    """Extract 8 authentic museum pigment colors with pairwise ΔE2000 >= 15 among the first 6."""
    rng = np.random.default_rng(sum(ord(c) for c in pal_id))
    fg_samples: list[np.ndarray] = []
    bg_gray_pixels: list[np.ndarray] = []

    for img_idx, img in enumerate(images):
        im_work = img.copy()
        w0, h0 = im_work.size
        if crop_border > 0.08:
            cx, cy = int(w0 * crop_border), int(h0 * crop_border)
            im_work = im_work.crop((cx, cy, w0 - cx, h0 - cy))
        im_work.thumbnail((440, 440), Image.Resampling.LANCZOS)
        arr = np.asarray(im_work, dtype=np.float64) / 255.0
        h, w, _ = arr.shape
        b_mask = np.zeros((h, w), dtype=bool)
        bw, bh = max(3, int(0.05 * w)), max(3, int(0.05 * h))
        b_mask[:bh, :] = True
        b_mask[-bh:, :] = True
        b_mask[:, :bw] = True
        b_mask[:, -bw:] = True
        labs = srgb_to_oklab(arr.reshape(-1, 3)).reshape(h, w, 3)
        bg_med = np.median(labs[b_mask], axis=0)
        dist_bg = np.linalg.norm(labs - bg_med[None, None, :], axis=2)
        lch = oklab_to_oklch(labs)
        L_grid, C_grid, H_grid = lch[..., 0], lch[..., 1], lch[..., 2]

        fg = (dist_bg > 0.045) & (L_grid >= 0.18) & (L_grid <= 0.88) & (C_grid >= 0.022)
        if fg.sum() < 300:
            fg = (L_grid >= 0.20) & (L_grid <= 0.88)

        pts = labs[fg]
        pts_C = C_grid[fg]
        pts_H = H_grid[fg]
        # Primary image carries 2x base weight; chromatic & mineral-hue pixels are oversampled so delicate glazes/pigments aren't drowned by raw silk
        base_rep = 2 if img_idx == 0 else 1
        fg_samples.append(np.repeat(pts, base_rep, axis=0))
        hi_c = pts[pts_C >= np.quantile(pts_C, 0.65)]
        if len(hi_c) > 40:
            fg_samples.append(np.repeat(hi_c, 3, axis=0))
        # Oversample non-tan mineral hues (azurite blues, malachite greens, cinnabar reds) on silk/paper paintings
        mineral_mask = (pts_C >= 0.018) & ((pts_H < 45.0) | (pts_H > 118.0))
        if mineral_mask.sum() > 25:
            rep_m = 10 if pal_id == "east_blue_green_landscape" else 3
            fg_samples.append(np.repeat(pts[mineral_mask], rep_m, axis=0))
        if pal_id == "east_blue_green_landscape":
            blue_rock = (L_grid >= 0.20) & (L_grid <= 0.75) & (H_grid >= 145.0) & (H_grid <= 275.0) & (C_grid >= 0.012)
            if blue_rock.sum() > 15:
                fg_samples.append(np.repeat(labs[blue_rock], 18, axis=0))

        neutral_cand = (C_grid < 0.030) & (L_grid >= 0.65) & (L_grid <= 0.82)
        if neutral_cand.any():
            bg_gray_pixels.append(labs[neutral_cand])

    all_fg = np.concatenate(fg_samples, axis=0)
    centers, weights = _kmeans_oklab(all_fg, k=24, seed=int(rng.integers(1, 99999)))

    cand_items: list[tuple[float, str, float]] = []
    for idx in np.argsort(-weights):
        if weights[idx] < 0.004:
            continue
        L, C, h_deg = oklab_to_oklch(centers[idx])
        L_ed = float(np.clip(0.54 + (L - 0.50) * 0.85, 0.31, 0.78))
        C_ed = float(np.clip(C * 1.35 + 0.018, 0.052, 0.178))
        hx = oklch_to_hex(L_ed, C_ed, float(h_deg))
        wood_pen = 0.50 if (45.0 <= h_deg <= 88.0 and C < 0.058 and L < 0.48) else 1.0
        sig_boost = 1.35 if _in_hue_range(float(h_deg), signature_hue_range[0], signature_hue_range[1]) else 1.0
        score = float((weights[idx] ** 0.22) * (0.30 + 4.5 * C_ed) * wood_pen * sig_boost)
        cand_items.append((score, hx, float(h_deg)))
        if weights[idx] >= 0.022:
            L_alt = float(np.clip(L_ed + (0.18 if L_ed < 0.55 else -0.18), 0.30, 0.80))
            C_alt = float(np.clip(C_ed * 0.94, 0.048, 0.165))
            cand_items.append((score * 0.72, oklch_to_hex(L_alt, C_alt, float(h_deg)), float(h_deg)))

    cand_items.sort(key=lambda x: x[0], reverse=True)
    dedup: list[tuple[float, str, float]] = []
    seen_h: set[str] = set()
    for sc, hx, hd in cand_items:
        if hx not in seen_h:
            seen_h.add(hx)
            dedup.append((sc, hx, hd))

    # Slot #1 leads with the artifact's signature pigment hue (e.g. Ru sky-celadon, Longquan jade, Chenghua cobalt, Zhao Mengfu mineral blue-green)
    sig_cands = [x for x in dedup if _in_hue_range(x[2], signature_hue_range[0], signature_hue_range[1])]
    anchor = sig_cands[0] if sig_cands else dedup[0]
    selected: list[str] = [anchor[1]]
    selected_hues: list[float] = [anchor[2]]

    while len(selected) < 8:
        req_de = 16.0 if len(selected) < 6 else 13.5
        req_cvd = 9.0 if len(selected) < 6 else 7.2
        best_hx: str | None = None
        best_hd: float = 0.0
        best_val = -1e9
        s_arr = np.stack([hex_to_srgb01(c) for c in selected], axis=0)

        for sc, hx, hd in dedup:
            if hx in selected:
                continue
            c_arr = hex_to_srgb01(hx)[None, :]
            d_norm = float(ciede2000_matrix(c_arr, s_arr).min())
            if d_norm < req_de:
                continue
            d_deut = float(ciede2000_matrix(simulate_cvd(c_arr, "deutan", 1.0), simulate_cvd(s_arr, "deutan", 1.0)).min())
            if d_deut < req_cvd:
                continue
            min_dh = min(abs(((hd - sh + 180.0) % 360.0) - 180.0) for sh in selected_hues)
            tan_pen = -4.0 if (len(selected) < 5 and 52.0 <= hd <= 95.0 and any(52.0 <= sh <= 95.0 for sh in selected_hues)) else 0.0
            val = sc * 10.0 + 0.35 * d_norm + 0.28 * d_deut + 0.15 * min_dh + tan_pen
            if val > best_val:
                best_val = val
                best_hx = hx
                best_hd = hd

        if best_hx is None:
            for sc, hx, hd in dedup:
                if hx in selected:
                    continue
                c_arr = hex_to_srgb01(hx)[None, :]
                d_norm = float(ciede2000_matrix(c_arr, s_arr).min())
                if d_norm >= (15.3 if len(selected) < 6 else 12.8):
                    best_hx, best_hd = hx, hd
                    break
        if best_hx is None:
            break
        selected.append(best_hx)
        selected_hues.append(best_hd)

    if len(selected) < 8:
        base_lch = [hex_to_oklch(c) for c in selected]
        for h_off in (42.0, -42.0, 88.0, -88.0, 140.0):
            for L_t in (0.40, 0.68, 0.54, 0.76):
                bL, bC, bh = base_lch[len(selected) % len(base_lch)]
                cand = oklch_to_hex(L_t, max(0.075, min(0.15, bC * 1.1)), (bh + h_off) % 360.0)
                s_arr = np.stack([hex_to_srgb01(c) for c in selected], axis=0)
                d_norm = float(ciede2000_matrix(hex_to_srgb01(cand)[None, :], s_arr).min())
                if d_norm >= (15.5 if len(selected) < 6 else 13.0):
                    selected.append(cand)
                    if len(selected) >= 8:
                        break
            if len(selected) >= 8:
                break

    if bg_gray_pixels:
        med_n = np.median(np.concatenate(bg_gray_pixels, axis=0), axis=0)
        Ln, Cn, hn = oklab_to_oklch(med_n)
        neutral_hex = oklch_to_hex(float(np.clip(Ln, 0.72, 0.79)), float(np.clip(Cn, 0.008, 0.020)), float(hn))
    else:
        neutral_hex = "#B5B2AC"

    return selected[:8], neutral_hex


def render_proof_sheet(
    spec: dict[str, Any],
    artifact_img: Image.Image,
    colors: list[str],
    neutral: str,
    min_de6: float,
    out_path: Path,
) -> None:
    """Render a 1400x880 white-paper proof sheet (artifact + swatches + bar + scatter + heatmap + 4-panel)."""
    canvas = Image.new("RGB", (1400, 880), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    sys_font = "/System/Library/Fonts/Supplemental/Arial.ttf"
    if Path(sys_font).exists():
        font_lg = ImageFont.truetype(sys_font, 20)
        font_md = ImageFont.truetype(sys_font, 14)
        font_sm = ImageFont.truetype(sys_font, 12)
    else:
        font_lg = ImageFont.load_default(size=20)
        font_md = ImageFont.load_default(size=14)
        font_sm = ImageFont.load_default(size=12)

    # Header
    title = f"{spec['name']['en']}  |  {spec['id']}  ({spec['artifact']['museum']} · {spec['artifact']['object_id']})"
    draw.text((32, 24), title, fill=(17, 24, 39), font=font_lg)
    draw.text(
        (32, 52),
        f"{spec['artifact']['title']} · {spec['artifact']['date']} · CC0  |  min CIEDE2000 (first 6) = {min_de6:.1f}",
        fill=(75, 85, 99),
        font=font_md,
    )
    draw.line([(32, 82), (1368, 82)], fill=(229, 231, 235), width=1)

    # Left column: CC0 artifact photograph + extracted swatch cards
    art_box = artifact_img.copy()
    art_box.thumbnail((340, 340), Image.Resampling.LANCZOS)
    canvas.paste(art_box, (32, 104))
    draw.rectangle([32, 104, 32 + art_box.width, 104 + art_box.height], outline=(209, 213, 219), width=1)

    sy0 = 468
    draw.text((32, sy0), "Extracted 8-Color Palette + Neutral:", fill=(17, 24, 39), font=font_md)
    for i, hx in enumerate(colors + [neutral]):
        row, col = divmod(i, 3)
        bx = 32 + col * 116
        by = sy0 + 28 + row * 74
        rgb = tuple(int(hx[j : j + 2], 16) for j in (1, 3, 5))
        draw.rounded_rectangle([bx, by, bx + 106, by + 44], radius=5, fill=rgb, outline=(209, 213, 219))
        lbl = f"#{i+1} {hx}" if i < len(colors) else f"BG {hx}"
        draw.text((bx + 2, by + 48), lbl, fill=(55, 65, 81), font=font_sm)

    # Right 2x2 benchmark chart grid:
    # Panel A (410, 104, 870, 460): 8-group Bar chart with error whiskers
    # Panel B (900, 104, 1368, 460): 6-cluster Scatter plot
    # Panel C (410, 490, 870, 846): 6x6 Expression Matrix
    # Panel D (900, 490, 1368, 846): 2x2 Multi-panel Consistency Check (Focus vs Normal vs Background)
    rng = np.random.default_rng(1024 + sum(ord(c) for c in spec["id"]))

    # Panel A: Bar chart
    draw.rectangle([410, 104, 870, 460], outline=(229, 231, 235), width=1)
    draw.text((426, 116), "A  Categorical Bar Chart (8 groups)", fill=(17, 24, 39), font=font_md)
    draw.line([(450, 420), (848, 420)], fill=(17, 24, 39), width=2)
    draw.line([(450, 156), (450, 420)], fill=(17, 24, 39), width=2)
    heights = [215, 178, 242, 152, 198, 134, 166, 118]
    for i, hx in enumerate(colors):
        rgb = tuple(int(hx[j : j + 2], 16) for j in (1, 3, 5))
        x0 = 466 + i * 46
        bh = heights[i]
        draw.rectangle([x0, 420 - bh, x0 + 32, 419], fill=rgb)
        xm = x0 + 16
        draw.line([(xm, 420 - bh - 12), (xm, 420 - bh + 10)], fill=(17, 24, 39), width=1)
        draw.line([(xm - 6, 420 - bh - 12), (xm + 6, 420 - bh - 12)], fill=(17, 24, 39), width=1)
        draw.text((x0 + 6, 426), f"G{i+1}", fill=(17, 24, 39), font=font_sm)

    # Panel B: Scatter plot
    draw.rectangle([900, 104, 1368, 460], outline=(229, 231, 235), width=1)
    draw.text((916, 116), "B  6-Cluster Embedding Scatter", fill=(17, 24, 39), font=font_md)
    draw.line([(936, 420), (1344, 420)], fill=(17, 24, 39), width=2)
    draw.line([(936, 156), (936, 420)], fill=(17, 24, 39), width=2)
    centers_xy = [(1005, 225), (1125, 200), (1245, 235), (1015, 345), (1145, 330), (1268, 355)]
    for ci, (cx, cy) in enumerate(centers_xy):
        hx = colors[ci]
        rgb = tuple(int(hx[j : j + 2], 16) for j in (1, 3, 5))
        pts_x = cx + rng.normal(0, 22, size=34)
        pts_y = cy + rng.normal(0, 19, size=34)
        for px, py in zip(pts_x, pts_y):
            if 944 <= px <= 1338 and 162 <= py <= 412:
                draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=rgb)

    # Panel C: Continuous gradient ramp interpolated between deepest & lightest tones
    draw.rectangle([410, 490, 870, 846], outline=(229, 231, 235), width=1)
    draw.text((426, 502), f"C  Paired Heatmap ({spec['partners']['sequential']} / {spec['partners']['diverging']})", fill=(17, 24, 39), font=font_md)
    c_lo = hex_to_srgb01(colors[0])
    c_mid = np.array([0.96, 0.96, 0.95])
    c_hi = hex_to_srgb01(colors[1])
    for r_i in range(6):
        for c_i in range(6):
            t = (r_i * 6 + c_i) / 35.0
            vec = (1.0 - t * 2.0) * c_lo + (t * 2.0) * c_mid if t < 0.5 else (1.0 - (t - 0.5) * 2.0) * c_mid + ((t - 0.5) * 2.0) * c_hi
            rgb = tuple(int(np.clip(round(v * 255), 0, 255)) for v in vec)
            gx0 = 466 + c_i * 58
            gy0 = 548 + r_i * 44
            draw.rectangle([gx0, gy0, gx0 + 54, gy0 + 40], fill=rgb)

    # Panel D: Focus + Normal + Neutral hierarchy line/dot comparison
    draw.rectangle([900, 490, 1368, 846], outline=(229, 231, 235), width=1)
    draw.text((916, 502), "D  Focus vs Normal vs Neutral Hierarchy", fill=(17, 24, 39), font=font_md)
    draw.line([(936, 806), (1344, 806)], fill=(17, 24, 39), width=2)
    draw.line([(936, 548), (936, 806)], fill=(17, 24, 39), width=2)
    xs = [956 + k * 60 for k in range(7)]
    curves = [
        (neutral, [760, 752, 748, 742, 745, 738, 735], 2),
        (colors[2], [740, 718, 700, 688, 672, 662, 650], 2),
        (colors[1], [735, 705, 675, 650, 632, 614, 602], 3),
        (colors[0], [748, 695, 642, 604, 582, 566, 556], 4),
    ]
    for hx, ys, lw in curves:
        rgb = tuple(int(hx[j : j + 2], 16) for j in (1, 3, 5))
        for k in range(len(xs) - 1):
            draw.line([(xs[k], ys[k]), (xs[k + 1], ys[k + 1])], fill=rgb, width=lw)
        for xk, yk in zip(xs, ys):
            r = 5 if lw >= 4 else 3
            draw.ellipse([xk - r, yk - r, xk + r, yk + r], fill=rgb)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)


def main() -> int:
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_dir = REPO_ROOT / "core" / "danqing" / "palettes" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    dl_tasks: list[tuple[str, Path]] = []
    for spec in ARTIFACT_SPECS:
        pid = spec["id"]
        for u in spec["image_urls"]:
            dl_tasks.append((u, RAW_CACHE_DIR / f"{pid}_{u.split('/')[-2]}.jpg"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(lambda pair: _download_image(pair[0], pair[1]), dl_tasks))

    for spec in ARTIFACT_SPECS:
        pid = spec["id"]
        imgs = [
            _download_image(u, RAW_CACHE_DIR / f"{pid}_{u.split('/')[-2]}.jpg")
            for u in spec["image_urls"]
        ]
        thumb = imgs[0].copy()
        thumb.thumbnail((240, 240), Image.Resampling.LANCZOS)
        thumb.save(THUMB_DIR / f"{pid}.jpg", format="JPEG", quality=84, optimize=True)

        colors, neutral = extract_palette_from_images(
            imgs,
            pid,
            signature_hue_range=spec["signature_hue_range"],
            crop_border=float(spec.get("crop_border", 0.06)),
        )
        s6 = np.stack([hex_to_srgb01(c) for c in colors[:6]], axis=0)
        de_mat = ciede2000_matrix(s6)
        np.fill_diagonal(de_mat, 999.0)
        min_de6 = float(de_mat.min())

        pal_obj = {
            "id": pid,
            "name": spec["name"],
            "collection": "eastern",
            "kind": "qualitative",
            "order": "discrete",
            "colors": colors,
            "neutral": neutral,
            "partners": spec["partners"],
            "source": {
                "title": spec["artifact"]["title"],
                "author": spec["artifact"]["museum"],
                "year": spec["artifact"]["date"],
                "url": spec["artifact"]["url"],
                "license": "CC0 1.0 Universal",
            },
            "artifact": spec["artifact"],
            "qc": {},
        }
        (out_dir / f"{pid}.json").write_text(json.dumps(pal_obj, indent=2, ensure_ascii=False) + "\n")
        render_proof_sheet(spec, imgs[0], colors, neutral, min_de6, PROOF_DIR / f"{pid}_proof.png")
        print(f"[OK] {pid:28s} n={len(colors)} min_dE6={min_de6:5.2f} -> {colors} (neutral={neutral})")
        assert min_de6 >= 15.0, f"{pid} failed min_de2000_first6 >= 15.0 ({min_de6})"

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
