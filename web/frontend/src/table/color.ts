import type { PaletteItem } from "../types";

export interface BuiltinTableRamp {
  id: string;
  kind: "sequential" | "diverging";
  stops: string[];
  secondaryStops?: string[];
  partAccents: string[];
  labelKey: string;
}

export const BUILTIN_TABLE_RAMPS: BuiltinTableRamp[] = [
  {
    id: "danqing_umi_teal",
    kind: "sequential",
    stops: ["#E6F3F1", "#BFE2DC", "#7BBDB7", "#387D98", "#183B59"],
    partAccents: ["#2E6F95", "#5FA292", "#4E79A7", "#6AA6A2"],
    labelKey: "tableStudio.palettes.umiTeal",
  },
  {
    id: "danqing_sdi_terracotta",
    kind: "sequential",
    stops: ["#F7ECDC", "#EED3A3", "#E29D56", "#C45B3E", "#7A2022"],
    partAccents: ["#C6593F", "#E09F5A", "#A87559", "#781E20"],
    labelKey: "tableStudio.palettes.sdiTerracotta",
  },
  {
    id: "danqing_dual_part",
    kind: "sequential",
    stops: ["#E6F3F1", "#BFE2DC", "#7BBDB7", "#387D98", "#183B59"],
    secondaryStops: ["#F7ECDC", "#EED3A3", "#E29D56", "#C45B3E", "#7A2022"],
    partAccents: ["#2E6F95", "#C6593F", "#4F7E7F", "#597D52"],
    labelKey: "tableStudio.palettes.dualPart",
  },
  {
    id: "danqing_qingbai_jade",
    kind: "sequential",
    stops: ["#E6F0EE", "#C4DDD8", "#8EB5AE", "#4E7D7E", "#234649"],
    partAccents: ["#4F7E7F", "#728E86", "#6AA6A2", "#24474A"],
    labelKey: "tableStudio.palettes.qingbaiJade",
  },
  {
    id: "danqing_diverging_bu_rd",
    kind: "diverging",
    stops: ["#2166AC", "#5AA0C8", "#C8E0EE", "#F4F6F8", "#F7D6C4", "#DC7C50", "#9E2A2B"],
    partAccents: ["#2166AC", "#9E2A2B", "#4E79A7", "#C85A53"],
    labelKey: "tableStudio.palettes.divergingBuRd",
  },
  {
    id: "danqing_kyoto_moss",
    kind: "sequential",
    stops: ["#E9F0E4", "#C9DCBA", "#96B583", "#5A7F53", "#2C462A"],
    partAccents: ["#597D52", "#86A873", "#6AA6A2", "#2D472B"],
    labelKey: "tableStudio.palettes.kyotoMoss",
  },
  {
    id: "danqing_slate_ink",
    kind: "sequential",
    stops: ["#EBF0F5", "#CBD5E1", "#8FA0B5", "#475569", "#1E293B"],
    partAccents: ["#334155", "#64748B", "#475569", "#1E293B"],
    labelKey: "tableStudio.palettes.slateInk",
  },
];

export function filterContinuousCatalogPalettes(palettes: PaletteItem[]): PaletteItem[] {
  return palettes.filter((p) => {
    if (p.kind === "sequential" || p.kind === "diverging") {
      return p.colors.length >= 3;
    }
    const hasSeqPartner =
      Array.isArray(p.partners?.paired_sequential_stops) &&
      p.partners.paired_sequential_stops.length >= 3;
    const hasDivPartner =
      Array.isArray(p.partners?.paired_diverging_stops) &&
      p.partners.paired_diverging_stops.length >= 3;
    return hasSeqPartner || hasDivPartner;
  });
}

export interface ResolvedRamp {
  stops: string[];
  secondaryStops?: string[];
  partAccents: string[];
  diverging: boolean;
}

export function resolveTableRamp(
  paletteId: string,
  catalogPalettes: PaletteItem[],
  wantDiverging: boolean,
): ResolvedRamp {
  const builtin = BUILTIN_TABLE_RAMPS.find((b) => b.id === paletteId);
  if (builtin) {
    if (wantDiverging && builtin.kind !== "diverging") {
      const divBuiltin = BUILTIN_TABLE_RAMPS.find((b) => b.id === "danqing_diverging_bu_rd")!;
      return {
        stops: divBuiltin.stops,
        partAccents: builtin.partAccents,
        diverging: true,
      };
    }
    return {
      stops: builtin.stops,
      secondaryStops: builtin.secondaryStops,
      partAccents: builtin.partAccents,
      diverging: builtin.kind === "diverging",
    };
  }

  const cat = catalogPalettes.find((p) => p.id === paletteId);
  if (cat) {
    if (wantDiverging) {
      if (cat.kind === "diverging" && cat.colors.length >= 3) {
        return { stops: cat.colors, partAccents: cat.colors.slice(0, 4), diverging: true };
      }
      if (cat.partners?.paired_diverging_stops && cat.partners.paired_diverging_stops.length >= 3) {
        return {
          stops: cat.partners.paired_diverging_stops,
          partAccents: cat.colors.slice(0, 4),
          diverging: true,
        };
      }
    }
    if (cat.kind === "sequential" && cat.colors.length >= 3) {
      return { stops: cat.colors, partAccents: cat.colors.slice(0, 4), diverging: false };
    }
    if (cat.kind === "diverging" && cat.colors.length >= 3) {
      return { stops: cat.colors, partAccents: cat.colors.slice(0, 4), diverging: true };
    }
    if (cat.partners?.paired_sequential_stops && cat.partners.paired_sequential_stops.length >= 3) {
      return {
        stops: cat.partners.paired_sequential_stops,
        partAccents: cat.colors.slice(0, 4),
        diverging: false,
      };
    }
    if (cat.partners?.paired_diverging_stops && cat.partners.paired_diverging_stops.length >= 3) {
      return {
        stops: cat.partners.paired_diverging_stops,
        partAccents: cat.colors.slice(0, 4),
        diverging: true,
      };
    }
  }

  const fallback = BUILTIN_TABLE_RAMPS[0];
  return {
    stops: fallback.stops,
    partAccents: fallback.partAccents,
    diverging: false,
  };
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "").trim();
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  const r = parseInt(full.slice(0, 2), 16) || 0;
  const g = parseInt(full.slice(2, 4), 16) || 0;
  const b = parseInt(full.slice(4, 6), 16) || 0;
  return [r, g, b];
}

function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  return (
    "#" +
    [clamp(r), clamp(g), clamp(b)]
      .map((v) => v.toString(16).padStart(2, "0").toUpperCase())
      .join("")
  );
}

export function cushionSmallSampleT(t: number, count: number, diverging: boolean): number {
  const clamped = Math.max(0, Math.min(1, t));
  if (diverging || count >= 4) return clamped;
  return 0.08 + 0.74 * clamped;
}

export function interpolateRampHex(stops: string[], t: number): string {
  if (stops.length === 0) return "#FFFFFF";
  if (stops.length === 1) return stops[0];
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const idx = Math.min(Math.floor(scaled), stops.length - 2);
  const frac = scaled - idx;
  const [r1, g1, b1] = hexToRgb(stops[idx]);
  const [r2, g2, b2] = hexToRgb(stops[idx + 1]);
  return rgbToHex(r1 + (r2 - r1) * frac, g1 + (g2 - g1) * frac, b1 + (b2 - b1) * frac);
}

function srgbToLinear(c255: number): number {
  const c = c255 / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

export function contrastRatio(hexA: string, hexB: string): number {
  const l1 = relativeLuminance(hexA);
  const l2 = relativeLuminance(hexB);
  const hi = Math.max(l1, l2);
  const lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}

export function pickWcagForeground(bgHex: string | null): string {
  if (!bgHex) return "#111827";
  const darkInk = "#111827";
  const pureWhite = "#FFFFFF";
  const cDark = contrastRatio(bgHex, darkInk);
  const cWhite = contrastRatio(bgHex, pureWhite);
  return cDark >= 4.5 || cDark >= cWhite ? darkInk : pureWhite;
}
