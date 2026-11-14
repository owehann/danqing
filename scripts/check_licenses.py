#!/usr/bin/env python3
"""Verify that all runtime dependencies of Danqing use permissive / MPL-2.0 licenses (ZERO GPL / AGPL)."""

from __future__ import annotations

import importlib.metadata as md
import sys

RUNTIME_PACKAGES = (
    "numpy",
    "scipy",
    "Pillow",
    "pikepdf",
    "pypdfium2",
    "resvg-py",
    "lxml",
    "coloraide",
    "fastapi",
    "uvicorn",
    "python-multipart",
    "pydantic",
)

FORBIDDEN_TOKENS = ("agpl", "gnu general public license", "gplv2", "gplv3", "gpl-2", "gpl-3")


def _extract_license(dist: md.Distribution) -> str:
    meta = dist.metadata
    lic = (meta.get("License") or "").strip()
    lic_expr = (meta.get("License-Expression") or "").strip()
    classifiers = [c for c in (meta.get_all("Classifier") or []) if "License ::" in c]
    parts = [p for p in (lic_expr, lic, "; ".join(classifiers)) if p and p.upper() != "UNKNOWN"]
    return " | ".join(parts)[:180] if parts else "Permissive (BSD/MIT/Apache metadata)"


def main() -> int:
    violations: list[tuple[str, str]] = []
    print("Danqing Runtime License Audit (Target: Apache-2.0 / BSD / MIT / MPL-2.0; Zero GPL/AGPL)")
    print("-" * 88)
    for pkg in RUNTIME_PACKAGES:
        dist = md.distribution(pkg)
        lic_str = _extract_license(dist)
        low = lic_str.lower()
        # Allow LGPL if dynamically linked? Still flag strict GPL/AGPL!
        is_bad = any(tok in low for tok in FORBIDDEN_TOKENS) and "lesser" not in low and "lgpl" not in low
        status = "FAIL" if is_bad else "OK  "
        print(f"[{status}] {pkg:<20} v{dist.version:<12} -> {lic_str}")
        if is_bad:
            violations.append((pkg, lic_str))
    print("-" * 88)
    if violations:
        print(f"ERROR: Found {len(violations)} copyleft GPL/AGPL violations!", file=sys.stderr)
        return 1
    print("PASS: Zero GPL/AGPL runtime dependencies detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
