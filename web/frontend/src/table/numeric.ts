import type { ColumnRole, PStyle, Precision } from "./model";

export interface ParsedNumberResult {
  value: number | null;
  prefix: string;
  unit: string;
  pText: string | null;
  isSequence: boolean;
}

const MISSING_TOKENS = new Set([
  "",
  "-",
  "—",
  "–",
  "NA",
  "N/A",
  "na",
  "n/a",
  "nan",
  "NaN",
  "null",
  "NULL",
]);

const STD_THOUSANDS_RE = /^[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:[eE][-+]?\d+)?$/;
const EURO_THOUSANDS_RE = /^[-+]?\d{1,3}(?:\.\d{3})+,\d+(?:[eE][-+]?\d+)?$/;
const PLAIN_FLOAT_RE = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/;
const SEMI_PIPE_SEQ_RE = /^\s*[-+]?\d*\.?\d+(?:\s*[;|/]\s*[-+]?\d*\.?\d+){2,}\s*$/;

const SUPERSCRIPT_DIGITS: Record<string, string> = {
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
  "-": "⁻",
  "+": "⁺",
};

export function parseNumber(raw: string, decimalComma = false): ParsedNumberResult {
  const s = raw.trim();
  if (MISSING_TOKENS.has(s)) {
    return { value: null, prefix: "", unit: "", pText: null, isSequence: false };
  }

  const lower = s.toLowerCase();
  if (lower === "n.s." || lower === "ns") {
    return { value: null, prefix: "", unit: "", pText: "n.s.", isSequence: false };
  }

  const sNorm = s.replace(/\u2212/g, "-");

  if (SEMI_PIPE_SEQ_RE.test(sNorm)) {
    return { value: null, prefix: "", unit: "", pText: null, isSequence: true };
  }

  if (!decimalComma && sNorm.includes(",")) {
    const strippedForCheck = sNorm.replace(/^[<>≤≥+\s]+/, "").replace(/[\s%]+$/, "");
    if (!STD_THOUSANDS_RE.test(strippedForCheck)) {
      const parts = sNorm.split(",").map((p) => p.trim());
      if (parts.length >= 2 && parts.every((p) => PLAIN_FLOAT_RE.test(p))) {
        return { value: null, prefix: "", unit: "", pText: null, isSequence: true };
      }
    }
  }

  let work = sNorm;
  let prefix = "";
  for (const pfx of ["<=", ">=", "≤", "≥", "<", ">"]) {
    if (work.startsWith(pfx)) {
      prefix = pfx;
      work = work.slice(pfx.length).trim();
      break;
    }
  }

  let negParen = false;
  if (work.startsWith("(") && work.endsWith(")") && work.length > 2) {
    negParen = true;
    work = work.slice(1, -1).trim();
  }

  let unit = "";
  if (work.endsWith("%")) {
    unit = "%";
    work = work.slice(0, -1).trim();
  }

  if (!work) {
    return { value: null, prefix: "", unit: "", pText: null, isSequence: false };
  }

  let cleaned: string | null = null;
  if (decimalComma) {
    if (EURO_THOUSANDS_RE.test(work)) {
      cleaned = work.replace(/\./g, "").replace(",", ".");
    } else if (work.includes(",") && !work.includes(".")) {
      const cand = work.replace(",", ".");
      if (PLAIN_FLOAT_RE.test(cand)) cleaned = cand;
    } else if (PLAIN_FLOAT_RE.test(work)) {
      cleaned = work;
    }
  } else {
    if (STD_THOUSANDS_RE.test(work)) {
      cleaned = work.replace(/,/g, "");
    } else if (!work.includes(",") && PLAIN_FLOAT_RE.test(work)) {
      cleaned = work;
    }
  }

  if (cleaned === null) {
    return { value: null, prefix: "", unit: "", pText: null, isSequence: false };
  }

  const num = Number(cleaned);
  if (!Number.isFinite(num)) {
    return { value: null, prefix: "", unit: "", pText: null, isSequence: false };
  }

  const finalVal = negParen ? -Math.abs(num) : num;
  return { value: finalVal, prefix, unit, pText: null, isSequence: false };
}

export function parseSequence(raw: string): number[] | null {
  const s = raw.trim().replace(/\u2212/g, "-");
  if (!s) return null;
  const parts = s.split(/[,;|/]/).map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return null;
  const nums = parts.map((p) => Number(p));
  if (nums.some((n) => !Number.isFinite(n))) return null;
  return nums;
}

export function stripStarsInput(raw: string): string {
  return raw.replace(/\*+$/g, "").trim();
}

export function inferAutoPrecision(
  values: number[],
  role: ColumnRole,
  unit: string,
): 0 | 1 | 2 | 3 {
  if (role === "count") return 0;
  if (unit === "%") return 1;
  const absVals = values.map((v) => Math.abs(v)).filter((v) => Number.isFinite(v));
  if (absVals.length === 0) return 2;
  absVals.sort((a, b) => a - b);
  const mid = Math.floor(absVals.length / 2);
  const median =
    absVals.length % 2 === 1
      ? absVals[mid]
      : 0.5 * (absVals[mid - 1] + absVals[mid]);

  if (median >= 100) return 0;
  if (median >= 10) return 1;
  if (median >= 1) return 2;
  return 3;
}

export function resolvePrecision(
  precision: Precision,
  values: number[],
  role: ColumnRole,
  unit: string,
): 0 | 1 | 2 | 3 {
  if (role === "count") return 0;
  if (precision !== "auto") return precision;
  return inferAutoPrecision(values, role, unit);
}

export function formatNumberFixed(value: number, decimals: 0 | 1 | 2 | 3, prefix = ""): string {
  const safeVal = Object.is(value, -0) ? 0 : value;
  const fixed = safeVal.toFixed(decimals);
  const normalized = /^-(0(?:\.0+)?)$/.test(fixed) ? fixed.slice(1) : fixed;
  return `${prefix}${normalized}`;
}

export function buildExcelNumFmt(decimals: 0 | 1 | 2 | 3): string {
  return decimals === 0 ? "0" : `0.${"0".repeat(decimals)}`;
}

export function computeSigStars(value: number | null, prefix: string): "" | "*" | "**" | "***" {
  if (value === null || !Number.isFinite(value) || value < 0) return "";
  if (prefix === "<") {
    if (value <= 0.001) return "***";
    if (value <= 0.01) return "**";
    if (value <= 0.05) return "*";
    return "";
  }
  if (prefix === ">" || prefix === ">=" || prefix === "≥") {
    return "";
  }
  if (value < 0.001) return "***";
  if (value < 0.01) return "**";
  if (value < 0.05) return "*";
  return "";
}

function dropLeadingZero(numStr: string): string {
  if (numStr.startsWith("0.")) return numStr.slice(1);
  if (numStr.startsWith("<0.")) return `<.${numStr.slice(3)}`;
  if (numStr.startsWith(">0.")) return `>.${numStr.slice(3)}`;
  return numStr;
}

function toUnicodeSuperscript(expStr: string): string {
  return Array.from(expStr)
    .map((ch) => SUPERSCRIPT_DIGITS[ch] ?? ch)
    .join("");
}

const P_THRESHOLDS = [0.001, 0.01, 0.05] as const;

export function formatP(
  value: number | null,
  prefix: string,
  style: PStyle,
  pText: string | null = null,
): string {
  if (pText) return pText;
  if (value === null || !Number.isFinite(value)) return "";

  if (prefix === "<" || prefix === ">" || prefix === "≤" || prefix === "≥") {
    const rawStr = `${prefix}${value.toString()}`;
    return style === "apa" ? dropLeadingZero(rawStr) : rawStr;
  }

  if (style === "exact") {
    if (value <= 0) return "<1.0×10⁻³⁰⁰";
    if (value < 0.001) {
      const expParts = value.toExponential(1).split("e");
      const mantissa = expParts[0];
      const expInt = parseInt(expParts[1], 10);
      return `${mantissa}×10${toUnicodeSuperscript(String(expInt))}`;
    }
    let sigDigits = 2;
    let candidateStr = Number(value.toPrecision(sigDigits)).toString();
    // Ensure trailing zero for 2 sig figs like 0.030 -> "0.030" or keep clean 2 sig figs
    const expForm = value.toExponential(1);
    const expVal = parseInt(expForm.split("e")[1], 10);
    const decPlaces = Math.max(0, 1 - expVal);
    candidateStr = value.toFixed(decPlaces);

    for (const thr of P_THRESHOLDS) {
      if (value < thr && Number(candidateStr) >= thr) {
        const extraStr = value.toFixed(decPlaces + 1);
        if (Number(extraStr) < thr) {
          return extraStr;
        }
        return `<${thr}`;
      }
    }
    return candidateStr;
  }

  if (value < 0.001) {
    return style === "apa" ? "<.001" : "<0.001";
  }

  const baseDecimals = style === "apa" ? 3 : value >= 0.01 ? 2 : 3;
  let formatted = value.toFixed(baseDecimals);

  for (const thr of P_THRESHOLDS) {
    if (value < thr && Number(formatted) >= thr) {
      const more = value.toFixed(baseDecimals + 1);
      if (Number(more) < thr) {
        formatted = more;
      } else {
        formatted = `<${thr}`;
      }
      break;
    }
  }

  return style === "apa" ? dropLeadingZero(formatted) : formatted;
}
