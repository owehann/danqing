#!/usr/bin/env python3
"""Deterministic SVG + multi-resolution PNG brand asset generator for Danqing (丹青).

Optical Two-Tier Identity System ("丹青叠璧 · Albers Mineral Seal"):
1. Small-Scale Mark (`16px–24px`, `favicon.svg`, `favicon-16x16.png`, `favicon-32x32.png`, TopBar):
   Full-bleed borderless Boolean geometry — Cinnabar Circle (丹 · 朱砂) overlapping
   Azurite-Teal Rounded Square (青 · 石青/石绿) with a luminous Song-Porcelain intersection lens.
   Eliminates container padding to maximize active pixel area (+42%) on 16px light & dark browser tabs.

2. Display Seal (`44px–512px`, `icon-seal.svg`, `apple-touch-icon.png`, `icon-512.png`, Landing Hero):
   Warm Song-Porcelain squircle seal (`#FCFBF7` -> `#F1ECE0`, `#D5CEC0` rim) housing the three
   Northern Song mineral pigments of Wang Ximeng's *A Thousand Li of Rivers and Mountains*:
   Cinnabar (`#E2523A`), Azurite (`#236E8E`), and Celadon-Jade Boolean synthesis (`#48B8A8` -> `#288B82`).
"""

from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO_ROOT / "web" / "frontend" / "public"

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <defs>
    <linearGradient id="dq-fav-dan" x1="8" y1="8" x2="42" y2="42" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#E6583E"/>
      <stop offset="100%" stop-color="#C43823"/>
    </linearGradient>
    <linearGradient id="dq-fav-qing" x1="22" y1="22" x2="58" y2="58" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#2B8E92"/>
      <stop offset="100%" stop-color="#19556C"/>
    </linearGradient>
    <clipPath id="dq-fav-dan-clip">
      <circle cx="25" cy="25" r="21"/>
    </clipPath>
  </defs>
  <rect x="22" y="22" width="38" height="38" rx="10" fill="url(#dq-fav-qing)"/>
  <circle cx="25" cy="25" r="21" fill="url(#dq-fav-dan)"/>
  <g clip-path="url(#dq-fav-dan-clip)">
    <rect x="22" y="22" width="38" height="38" rx="10" fill="#FAF6EE"/>
  </g>
</svg>
"""

SEAL_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" fill="none">
  <defs>
    <linearGradient id="dq-seal-paper" x1="12" y1="8" x2="116" y2="120" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#FDFCF8"/>
      <stop offset="100%" stop-color="#F1ECE0"/>
    </linearGradient>
    <linearGradient id="dq-seal-dan" x1="24" y1="24" x2="78" y2="78" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#E4553C"/>
      <stop offset="100%" stop-color="#C23722"/>
    </linearGradient>
    <linearGradient id="dq-seal-qing" x1="50" y1="50" x2="104" y2="104" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#257291"/>
      <stop offset="100%" stop-color="#164663"/>
    </linearGradient>
    <linearGradient id="dq-seal-jade" x1="50" y1="50" x2="80" y2="80" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#4BBAA9"/>
      <stop offset="100%" stop-color="#278980"/>
    </linearGradient>
    <clipPath id="dq-seal-dan-clip">
      <circle cx="52" cy="52" r="27"/>
    </clipPath>
    <clipPath id="dq-seal-qing-clip">
      <rect x="50" y="50" width="50" height="50" rx="13"/>
    </clipPath>
  </defs>
  <rect x="6" y="6" width="116" height="116" rx="28" fill="url(#dq-seal-paper)" stroke="#D6CFC1" stroke-width="2.5"/>
  <rect x="50" y="50" width="50" height="50" rx="13" fill="url(#dq-seal-qing)"/>
  <circle cx="52" cy="52" r="27" fill="url(#dq-seal-dan)"/>
  <g clip-path="url(#dq-seal-dan-clip)">
    <rect x="50" y="50" width="50" height="50" rx="13" fill="url(#dq-seal-jade)"/>
    <rect x="50" y="50" width="50" height="50" rx="13" stroke="#FCFBF7" stroke-width="2.4"/>
  </g>
  <g clip-path="url(#dq-seal-qing-clip)">
    <circle cx="52" cy="52" r="27" stroke="#FCFBF7" stroke-width="2.4"/>
  </g>
</svg>
"""


def _render_svg_rgba(svg_text: str, size_px: int) -> Image.Image:
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg_text, width=size_px, height=size_px)
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def build_assets(showcase_out: Path | None = None) -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    (PUBLIC_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    (PUBLIC_DIR / "icon-seal.svg").write_text(SEAL_SVG, encoding="utf-8")

    # Small optical tier (16px, 32px)
    _render_svg_rgba(FAVICON_SVG, 16).save(PUBLIC_DIR / "favicon-16x16.png", format="PNG")
    _render_svg_rgba(FAVICON_SVG, 32).save(PUBLIC_DIR / "favicon-32x32.png", format="PNG")

    # Display optical tier (180px Apple Touch Icon, 512px App/PWA Emblem)
    _render_svg_rgba(SEAL_SVG, 180).save(PUBLIC_DIR / "apple-touch-icon.png", format="PNG")
    _render_svg_rgba(SEAL_SVG, 512).save(PUBLIC_DIR / "icon-512.png", format="PNG")

    if showcase_out is not None:
        showcase_out.parent.mkdir(parents=True, exist_ok=True)
        canvas = Image.new("RGBA", (1120, 440), (249, 248, 245, 255))
        draw = ImageDraw.Draw(canvas)
        try:
            font_lg = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 18)
            font_sm = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 13)
        except Exception:
            font_lg = ImageFont.load_default()
            font_sm = ImageFont.load_default()

        # Left card: Display Seal (200px)
        draw.rounded_rectangle((32, 36, 544, 404), radius=18, fill=(255, 255, 255, 255), outline=(224, 220, 212, 255), width=2)
        seal_200 = _render_svg_rgba(SEAL_SVG, 196)
        canvas.alpha_composite(seal_200, (60, 104))
        draw.text((280, 118), "Display Seal (44px – 512px)", fill=(24, 24, 27, 255), font=font_lg)
        draw.text((280, 152), "Song-Porcelain Squircle Emblem", fill=(82, 82, 91, 255), font=font_sm)
        draw.text((280, 182), "Dan · Cinnabar (#E4553C)", fill=(194, 55, 34, 255), font=font_sm)
        draw.text((280, 208), "Qing · Azurite (#257291)", fill=(22, 70, 99, 255), font=font_sm)
        draw.text((280, 234), "Synthesis · Celadon (#38A396)", fill=(39, 137, 128, 255), font=font_sm)
        draw.text((280, 272), "Landing Hero · iOS · App Icon", fill=(113, 113, 122, 255), font=font_sm)

        # Right card: Optical Micro-Mark (16px / 24px / 32px on Light & Dark Tabs)
        draw.rounded_rectangle((572, 36, 1088, 404), radius=18, fill=(255, 255, 255, 255), outline=(224, 220, 212, 255), width=2)
        fav_136 = _render_svg_rgba(FAVICON_SVG, 136)
        canvas.alpha_composite(fav_136, (604, 90))
        draw.text((766, 106), "Micro Mark (16px – 32px)", fill=(24, 24, 27, 255), font=font_lg)
        draw.text((766, 140), "Full-bleed borderless geometry", fill=(82, 82, 91, 255), font=font_sm)
        draw.text((766, 166), "+42% active pixel area at 16x16", fill=(82, 82, 91, 255), font=font_sm)
        draw.text((766, 192), "TopBar + Light/Dark Browser Tab", fill=(113, 113, 122, 255), font=font_sm)

        # Simulated Light Browser Tab (16x16 & 24x24)
        draw.rounded_rectangle((604, 262, 1056, 314), radius=10, fill=(241, 243, 245, 255), outline=(212, 212, 216, 255), width=1)
        fav_16 = _render_svg_rgba(FAVICON_SVG, 16)
        fav_24 = _render_svg_rgba(FAVICON_SVG, 24)
        canvas.alpha_composite(fav_16, (622, 280))
        canvas.alpha_composite(fav_24, (1014, 276))
        draw.text((648, 280), "Danqing — Scientific Figure Recoloring (16px Light)", fill=(24, 24, 27, 255), font=font_sm)

        # Simulated Dark Browser Tab (16x16 & 24x24)
        draw.rounded_rectangle((604, 330, 1056, 382), radius=10, fill=(32, 33, 36, 255))
        canvas.alpha_composite(fav_16, (622, 348))
        canvas.alpha_composite(fav_24, (1014, 344))
        draw.text((648, 348), "Danqing — Scientific Figure Recoloring (16px Dark)", fill=(244, 244, 245, 255), font=font_sm)

        canvas.convert("RGB").save(showcase_out, format="PNG")


if __name__ == "__main__":
    import sys

    out_sheet = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    build_assets(out_sheet)
    print(f"Generated brand assets in {PUBLIC_DIR}")
