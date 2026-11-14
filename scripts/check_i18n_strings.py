#!/usr/bin/env python3
"""WP7 i18n & copy hygiene verifier for Danqing Studio frontend (TypeScript JSX AST + Locale Audit)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO / "web" / "frontend"
SRC_DIR = FRONTEND_DIR / "src"
EN_PATH = SRC_DIR / "locales" / "en.json"
ZH_PATH = SRC_DIR / "locales" / "zh.json"

BANNED_PATTERNS = [
    r"\bG[0-6]\b",
    r"ΔE",
    r"\bOKLCH\b",
    r"\bAPCA\b",
    r"\bSHA-256\b",
    r"墨分三境",
    r"一指点睛",
    r"素绢退墨",
    r"60\s*FPS",
    r"无损流形",
    r"[!！]",
]

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]"
)

TS_AST_CHECK_JS = r"""
const fs = require("fs");
const path = require("path");
const ts = require(path.join(process.cwd(), "node_modules", "typescript"));

const srcDir = path.join(process.cwd(), "src");
const userAttrs = new Set(["aria-label", "title", "placeholder", "alt"]);
const allowedPunct = /^[·%×+\-–—/|,:()0-9\s]*$/;
const violations = [];

function walkDir(dir) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) walkDir(full);
    else if (ent.name.endsWith(".tsx")) inspectFile(full);
  }
}

function inspectFile(filePath) {
  const code = fs.readFileSync(filePath, "utf8");
  const sf = ts.createSourceFile(filePath, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const rel = path.relative(process.cwd(), filePath);

  function visit(node) {
    if (ts.isJsxText(node)) {
      const txt = node.getText(sf).trim();
      if (txt && !allowedPunct.test(txt)) {
        const lc = sf.getLineAndCharacterOfPosition(node.getStart(sf));
        violations.push(`${rel}:${lc.line + 1}: literal JsxText ${JSON.stringify(txt)}`);
      }
    } else if (ts.isJsxAttribute(node)) {
      const attrName = node.name.getText(sf);
      if (userAttrs.has(attrName) && node.initializer && ts.isStringLiteral(node.initializer)) {
        const val = node.initializer.text.trim();
        if (val) {
          const lc = sf.getLineAndCharacterOfPosition(node.getStart(sf));
          violations.push(`${rel}:${lc.line + 1}: literal ${attrName}=${JSON.stringify(val)}`);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
}

walkDir(srcDir);
console.log(JSON.stringify(violations));
"""


def flatten_keys(obj: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_keys(v, full))
        else:
            out[full] = str(v)
    return out


def main() -> int:
    errors: list[str] = []

    en_flat = flatten_keys(json.loads(EN_PATH.read_text("utf-8")))
    zh_flat = flatten_keys(json.loads(ZH_PATH.read_text("utf-8")))

    missing_in_zh = sorted(set(en_flat) - set(zh_flat))
    missing_in_en = sorted(set(zh_flat) - set(en_flat))
    if missing_in_zh:
        errors.append(f"Keys missing in zh.json: {missing_in_zh}")
    if missing_in_en:
        errors.append(f"Keys missing in en.json: {missing_in_en}")

    for lang_name, flat in (("en.json", en_flat), ("zh.json", zh_flat)):
        for k, val in flat.items():
            if not val.strip():
                errors.append(f"{lang_name}:{k} is empty")
            for pat in BANNED_PATTERNS:
                if re.search(pat, val):
                    errors.append(f"{lang_name}:{k} matches banned pattern {pat!r}: {val!r}")
            if EMOJI_RE.search(val):
                errors.append(f"{lang_name}:{k} contains emoji: {val!r}")

    for tsx in sorted(SRC_DIR.rglob("*.tsx")):
        text = tsx.read_text("utf-8")
        if EMOJI_RE.search(text):
            errors.append(f"{tsx.relative_to(REPO)}: contains emoji character")

    proc = subprocess.run(
        ["node", "-e", TS_AST_CHECK_JS],
        cwd=str(FRONTEND_DIR),
        capture_output=True,
        text=True,
        check=True,
    )
    ast_violations: list[str] = json.loads(proc.stdout.strip() or "[]")
    errors.extend(ast_violations)

    if errors:
        print("FAILED check_i18n_strings.py:")
        for err in errors:
            print("  -", err)
        return 1

    print(
        f"PASS check_i18n_strings.py: {len(en_flat)} EN/ZH keys matched, "
        f"0 TypeScript JSX/attribute literal strings, 0 banned terms or emojis."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
