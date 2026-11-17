import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import sharedNumericSpec from "../../../../core/danqing/table_numeric_spec.json";
import type { PaletteItem } from "../types";
import { filterContinuousCatalogPalettes, pickWcagForeground } from "./color";
import {
  buildStandaloneStyledHtml,
  serializeToBackendExportPayload,
  serializeToBackendZipPayload,
} from "./exporters";
import type { RawSnapshot } from "./model";
import {
  computeSigStars,
  formatP,
  inferAutoPrecision,
  parseNumber,
  stripStarsInput,
} from "./numeric";
import {
  applySuggestionsToDoc,
  buildModel,
  createInitialTableDoc,
  listAvailableSuggestions,
  listUnappliedSuggestions,
} from "./pipeline";
import { normalizeRawSnapshotPayload, useTableStudioStore } from "./tableStore";

describe("numeric.ts shared specification vectors (27 cases)", () => {
  for (const vec of sharedNumericSpec.vectors) {
    it(`matches shared vector: ${vec.id}`, () => {
      const res = parseNumber(vec.input, vec.decimal_comma);
      if (vec.value === null) {
        expect(res.value).toBeNull();
      } else {
        expect(res.value).not.toBeNull();
        expect(Math.abs((res.value as number) - vec.value)).toBeLessThanOrEqual(
          Math.max(1e-12, Math.abs(vec.value) * 1e-12),
        );
      }
      expect(res.prefix).toBe(vec.prefix);
      expect(res.unit).toBe(vec.unit);
      expect(res.pText).toBe(vec.p_text);
      expect(res.isSequence).toBe(vec.is_sequence);
    });
  }
});

describe("T4 P-value boundary & anti-rounding rules (12 cases)", () => {
  const renderPWithStars = (rawInput: string, style: "nejm" | "apa" | "exact") => {
    const parsed = parseNumber(rawInput, false);
    const formatted = formatP(parsed.value, parsed.prefix, style, parsed.pText);
    const stars = computeSigStars(parsed.value, parsed.prefix);
    return stars && formatted !== "n.s." ? `${formatted}${stars}` : formatted;
  };

  it("nejm: 0.0491 -> 0.049* (prevents rounding up to 0.05)", () => {
    expect(renderPWithStars("0.0491", "nejm")).toBe("0.049*");
  });

  it("nejm: 0.0499 -> <0.05* (prevents rounding up to 0.050)", () => {
    expect(renderPWithStars("0.0499", "nejm")).toBe("<0.05*");
  });

  it("nejm: 0.05 -> 0.05 (exact threshold has zero stars)", () => {
    expect(renderPWithStars("0.05", "nejm")).toBe("0.05");
  });

  it("nejm: 0.032 -> 0.03*", () => {
    expect(renderPWithStars("0.032", "nejm")).toBe("0.03*");
  });

  it("nejm: 0.00999 -> <0.01**", () => {
    expect(renderPWithStars("0.00999", "nejm")).toBe("<0.01**");
  });

  it("nejm: 0.0042 -> 0.004**", () => {
    expect(renderPWithStars("0.0042", "nejm")).toBe("0.004**");
  });

  it("nejm: 0.00049 -> <0.001***", () => {
    expect(renderPWithStars("0.00049", "nejm")).toBe("<0.001***");
  });

  it("nejm: 1e-300 -> <0.001***", () => {
    expect(renderPWithStars("1e-300", "nejm")).toBe("<0.001***");
  });

  it("nejm: '<0.001' -> <0.001***", () => {
    expect(renderPWithStars("<0.001", "nejm")).toBe("<0.001***");
  });

  it("nejm: 'n.s.' -> n.s.", () => {
    expect(renderPWithStars("n.s.", "nejm")).toBe("n.s.");
  });

  it("apa: 0.032 -> .032*", () => {
    expect(renderPWithStars("0.032", "apa")).toBe(".032*");
  });

  it("exact: 2.69e-91 -> 2.7×10⁻⁹¹***", () => {
    expect(renderPWithStars("2.69e-91", "exact")).toBe("2.7×10⁻⁹¹***");
  });
});

describe("Auto precision, star stripping & continuous palette filtering", () => {
  it("computes auto precision by column median magnitude, count, and % unit", () => {
    expect(inferAutoPrecision([120, 450, 890], "normal", "")).toBe(0);
    expect(inferAutoPrecision([12.4, 45.2, 18.9], "normal", "")).toBe(1);
    expect(inferAutoPrecision([1.24, 3.55, 8.1], "normal", "")).toBe(2);
    expect(inferAutoPrecision([0.124, 0.355, 0.81], "normal", "")).toBe(3);
    expect(inferAutoPrecision([12.4, 45.2], "count", "")).toBe(0);
    expect(inferAutoPrecision([0.4, 0.8], "normal", "%")).toBe(1);
  });

  it("strips trailing asterisks on manual cell edit input", () => {
    expect(stripStarsInput("0.012**")).toBe("0.012");
    expect(stripStarsInput("42.5 (3.1)***")).toBe("42.5 (3.1)");
  });

  it("excludes discrete Okabe-Ito without continuous partner stops from ramp selector", () => {
    const baseSource = {
      title: "Test",
      author: "Author",
      year: 2024,
      url: "https://example.org",
      license: "CC0",
    };
    const baseQc = {
      color_count: 5,
      max_colors: 8,
      colorblind_safe: true,
      print_friendly: true,
    };
    const mockCatalog: PaletteItem[] = [
      {
        id: "okabe_ito",
        name: { en: "Okabe-Ito", zh: "Okabe-Ito" },
        collection: "accessible",
        kind: "qualitative",
        order: "discrete",
        colors: ["#E69F00", "#56B4E9", "#009E73", "#F0E442"],
        neutral: "#999999",
        partners: { sequential: "", diverging: "" },
        source: baseSource,
        artifact: null,
        qc: baseQc,
        dynamic_generator: null,
        convention_keys: [],
      },
      {
        id: "viridis_seq",
        name: { en: "Viridis", zh: "Viridis" },
        collection: "continuous",
        kind: "sequential",
        order: "gradient",
        colors: ["#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725"],
        neutral: "#999999",
        partners: { sequential: "", diverging: "" },
        source: baseSource,
        artifact: null,
        qc: baseQc,
        dynamic_generator: null,
        convention_keys: [],
      },
      {
        id: "npg_paired",
        name: { en: "NPG with Partner", zh: "NPG" },
        collection: "journal",
        kind: "qualitative",
        order: "discrete",
        colors: ["#E64B35", "#4DBBD5", "#00A087", "#3C5488"],
        neutral: "#999999",
        partners: {
          sequential: "",
          diverging: "",
          paired_sequential_stops: ["#F5F9FA", "#9AD1D4", "#007EA7", "#003249"],
        },
        source: baseSource,
        artifact: null,
        qc: baseQc,
        dynamic_generator: null,
        convention_keys: [],
      },
    ];
    const filtered = filterContinuousCatalogPalettes(mockCatalog);
    expect(filtered.map((p) => p.id)).toEqual(["viridis_seq", "npg_paired"]);
    expect(filtered.some((p) => p.name.en.includes("Okabe-Ito"))).toBe(false);
  });

  it("selects accessible WCAG foreground text for dark and light backgrounds", () => {
    expect(pickWcagForeground("#163554")).toBe("#FFFFFF");
    expect(pickWcagForeground("#F7FAFB")).toBe("#111827");
  });
});

describe("pipeline.ts pure functional transformation & store undo/redo", () => {
  const penguinsCsvPath = path.resolve(
    __dirname,
    "../../../../bench/tables/out/penguins_long.csv",
  );

  const loadPenguinsSnapshot = (): RawSnapshot => {
    const csvText = fs.readFileSync(penguinsCsvPath, "utf-8").trim();
    const grid = csvText.split(/\r?\n/).map((line: string) => line.split(","));
    return normalizeRawSnapshotPayload({
      snapshot_id: "tbl_penguins_test",
      sample_id: "penguins_long",
      source: {
        filename: "penguins_long.csv",
        sheet: "Sheet1",
        sheets: ["Sheet1"],
        kind: "sample",
        sha256: "abc123",
      },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "species", numeric_ratio: 0, detected_unit: "", role: "part" },
        { col: 1, name: "variable", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 2, name: "mean", numeric_ratio: 1, detected_unit: "", role: "heat" },
        { col: 3, name: "std", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 4, name: "count", numeric_ratio: 1, detected_unit: "", role: "count" },
        { col: 5, name: "p_value", numeric_ratio: 1, detected_unit: "", role: "sig" },
      ],
      grid,
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, grid.length - 1],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "part", "1": "normal", "2": "heat", "3": "normal", "4": "count", "5": "sig" },
        merges: [{ source_cols: [2, 3], pattern: "paren" }],
        part_by: 0,
        sparkline_runs: [],
        pivot: {
          row_key: 1,
          col_key: 0,
          value_cols: [2, 3],
          retain_row_cols: [5],
          col_counts: { Adelie: "146", Chinstrap: "68", Gentoo: "119" },
        },
        decimal_comma: false,
        resolved_headers: grid[0],
      },
    });
  };

  it("starts in raw stage with unstyled monospace grid and surfaces suggestions", () => {
    const snap = loadPenguinsSnapshot();
    const doc = createInitialTableDoc(snap);
    expect(doc.structure.stage).toBe("raw");
    expect(doc.style.preset).toBe("raw");

    const available = listAvailableSuggestions(doc);
    expect(available).toContain("pivot");
    expect(available).toContain("sig");

    const rawModel = buildModel(doc, "en");
    expect(rawModel.stage).toBe("raw");
    expect(rawModel.rawGrid.length).toBe(13);
    expect(rawModel.headers).toHaveLength(0);
  });

  it("keeps Tidy layout (unstyled grid) visually distinct from Tidy & style (matrix heatmap) on penguins_long", () => {
    const snap = loadPenguinsSnapshot();
    const doc = createInitialTableDoc(snap);

    // 1. Tidy layout only -> unstyled grid: zero heatmap fills, zero bolding
    const tidyOnly = applySuggestionsToDoc(doc, "all", false);
    expect(tidyOnly.structure.stage).toBe("tidied");
    expect(tidyOnly.style.preset).toBe("raw");
    const unstyledModel = buildModel(tidyOnly, "en");
    expect(unstyledModel.stage).toBe("tidied");
    expect(unstyledModel.preset).toBe("raw");
    expect(unstyledModel.recommendedPreset).toBe("matrix_heatmap");
    expect(unstyledModel.heatLegend).toBeNull();
    for (const row of unstyledModel.blocks[0].rows) {
      for (const cell of row) {
        expect(cell.bgHex).toBeNull();
        expect(cell.bold).toBe(false);
      }
    }

    // 2. Tidy & style -> matrix_heatmap + per_row: 12 colored Mean (SD) tiles + bold P-values + legend
    const tidied = applySuggestionsToDoc(doc, "all", true);
    expect(tidied.structure.stage).toBe("tidied");
    expect(tidied.style.preset).toBe("matrix_heatmap");
    expect(tidied.style.heatScope).toBe("per_row");

    const model = buildModel(tidied, "en");
    expect(model.stage).toBe("styled");
    expect(model.heatLegend).not.toBeNull();
    expect(model.heatLegend?.scope).toBe("per_row");
    expect(model.totalRows).toBe(4);
    expect(model.spanners.map((s) => s.label)).toEqual([
      "Adelie (n=146)",
      "Chinstrap (n=68)",
      "Gentoo (n=119)",
    ]);
    expect(model.headers.map((h) => h.label)).toEqual([
      "variable",
      "Mean (SD)",
      "Mean (SD)",
      "Mean (SD)",
      "P value",
    ]);

    // Verify row-scale auto precision preserves 1 decimal for bill_length_mm (~38.8) and 0 decimals for body_mass_g (~3701)
    expect(model.blocks[0].rows[0][1].display).toBe("38.8 (2.7)");
    expect(model.blocks[0].rows[3][1].display).toBe("3701 (459)");

    // Verify every Mean (SD) cell has a non-white heatmap bgHex and no row-peak bolding; only P value column is bold
    for (const row of model.blocks[0].rows) {
      expect(row[1].bgHex).not.toBeNull();
      expect(row[2].bgHex).not.toBeNull();
      expect(row[3].bgHex).not.toBeNull();
      expect(row[1].bgHex).not.toBe(row[3].bgHex);
      expect(row[1].bold).toBe(false);
      expect(row[2].bold).toBe(false);
      expect(row[3].bold).toBe(false);
      expect(row[4].bold).toBe(true);
      expect(row[4].display).toBe("<0.001***");
      expect(row[1].parts).not.toBeNull();
      expect(row[1].parts).toHaveLength(2);
    }

    // Export payload preserves formatted merged strings (raw_number: null) + heatmap bg_hex
    const expPayload = serializeToBackendExportPayload(model, "penguins") as {
      blocks: Array<{ rows: Array<Array<{ text: string; bg_hex: string; raw_number: number | null }>> }>;
    };
    expect(expPayload.blocks[0].rows[0][1].text).toBe("38.8 (2.7)");
    expect(expPayload.blocks[0].rows[0][1].raw_number).toBeNull();
    expect(expPayload.blocks[0].rows[0][1].bg_hex).not.toBe("#FFFFFF");

    // Auto-generated read-only star footnote legend
    expect(model.footnotes.some((f) => f.readOnly && f.text.includes("*** P < 0.001"))).toBe(true);

    // Unmerged rawDataSheet keeps all numeric columns separate for Excel `data` tab & Python export
    expect(model.rawDataSheet.headers.length).toBeGreaterThanOrEqual(8);
    const zipPayload = serializeToBackendZipPayload(tidied, model, "penguins");
    expect(zipPayload.table_json).toBeDefined();
  });

  it("protects clinical binary n (%) rows inside a Mean ± SD merged column", () => {
    const snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_clinical",
      source: { filename: "clinical.csv", sheet: "Sheet1", sheets: ["Sheet1"], kind: "csv", sha256: "def" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Characteristic", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "Control_Mean", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 2, name: "Control_SD", numeric_ratio: 1, detected_unit: "", role: "normal" },
      ],
      grid: [
        ["Characteristic", "Control_Mean", "Control_SD"],
        ["Age, years", "54.36", "9.04"],
        ["Male sex", "92", "56.1%"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 2],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "normal", "2": "normal" },
        merges: [{ source_cols: [1, 2], pattern: "plusminus" }],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Characteristic", "Control_Mean", "Control_SD"],
      },
    });

    const doc = applySuggestionsToDoc(createInitialTableDoc(snap), "all", false);
    expect(doc.style.preset).toBe("raw");
    const model = buildModel(doc, "en");
    expect(model.stage).toBe("tidied");
    // Row 0 is continuous -> uses ± pattern with auto precision 1 (median ~73 >= 10)
    expect(model.blocks[0].rows[0][1].display).toBe("54.4 ± 9.0");
    // Row 1 has integer + % -> protected as n (%)!
    expect(model.blocks[0].rows[1][1].display).toBe("92 (56.1%)");
  });

  it("blocks global heatmap scope when heat columns have incompatible units", () => {
    const snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_units",
      source: { filename: "units.csv", sheet: "Sheet1", sheets: ["Sheet1"], kind: "csv", sha256: "u1" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Item", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "Rate", numeric_ratio: 1, detected_unit: "%", role: "heat" },
        { col: 2, name: "Mass", numeric_ratio: 1, detected_unit: "g", role: "heat" },
      ],
      grid: [
        ["Item", "Rate", "Mass"],
        ["A", "15%", "3200"],
        ["B", "85%", "4500"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 2],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "heat", "2": "heat" },
        merges: [],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Item", "Rate", "Mass"],
      },
    });
    const doc = applySuggestionsToDoc(createInitialTableDoc(snap), "all", true);
    const model = buildModel(doc, "en");
    expect(model.hasHeatColumns).toBe(true);
    expect(model.globalHeatAllowed).toBe(false);
    expect(buildStandaloneStyledHtml(doc, model)).toContain("data-danqing-rules=");
  });

  it("records cellOverrides and supports multi-step undo/redo in tableStore", () => {
    const snap = loadPenguinsSnapshot();
    const initialDoc = createInitialTableDoc(snap);

    useTableStudioStore.setState({
      docs: { [snap.snapshotId]: initialDoc },
      order: [snap.snapshotId],
      activeId: snap.snapshotId,
      historyPast: {},
      historyFuture: {},
      tablePageMode: "editor",
    });

    const store = useTableStudioStore.getState();
    expect(store.canUndo()).toBe(false);

    // Step 1: Apply all suggestions (tidy only)
    store.applySuggestions("all", false);
    expect(useTableStudioStore.getState().docs[snap.snapshotId].structure.stage).toBe("tidied");
    expect(useTableStudioStore.getState().canUndo()).toBe(true);

    // Step 2: Edit a cell value
    useTableStudioStore.getState().commit((draft) => {
      draft.structure.cellOverrides["0:c1"] = {
        from: "bill_length_mm",
        to: "Bill length (mm)",
      };
    });
    const afterEdit = useTableStudioStore.getState().docs[snap.snapshotId];
    const editedModel = buildModel(afterEdit, "en");
    expect(editedModel.editedCount).toBe(1);
    expect(editedModel.blocks[0].rows[0][0].edited).toBe(true);
    expect(editedModel.blocks[0].rows[0][0].editedFrom).toBe("bill_length_mm");
    expect(editedModel.blocks[0].rows[0][0].display).toBe("Bill length (mm)");

    // Undo cell edit
    useTableStudioStore.getState().undo();
    expect(
      Object.keys(useTableStudioStore.getState().docs[snap.snapshotId].structure.cellOverrides),
    ).toHaveLength(0);
    expect(useTableStudioStore.getState().canRedo()).toBe(true);

    // Undo tidy -> back to raw
    useTableStudioStore.getState().undo();
    expect(useTableStudioStore.getState().docs[snap.snapshotId].structure.stage).toBe("raw");

    // Redo -> back to tidied
    useTableStudioStore.getState().redo();
    expect(useTableStudioStore.getState().docs[snap.snapshotId].structure.stage).toBe("tidied");
  });

  it("renders dual-block heatmap tiles on merged Table 1 columns and FT summary + heatmap on wide time-series", () => {
    // 1. Multi-block clinical Table 1 with merged Mean (SD) and binary n (%)
    const t1Snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_t1_heat",
      source: { filename: "t1.xlsx", sheet: "Sheet1", sheets: ["Sheet1"], kind: "sample", sha256: "t1" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Domain", numeric_ratio: 0, detected_unit: "", role: "part" },
        { col: 1, name: "Variable", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 2, name: "ArmA_Mean", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 3, name: "ArmA_SD", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 4, name: "ArmB_Mean", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 5, name: "ArmB_SD", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 6, name: "P value", numeric_ratio: 1, detected_unit: "", role: "sig" },
      ],
      grid: [
        ["Domain", "Variable", "ArmA_Mean", "ArmA_SD", "ArmB_Mean", "ArmB_SD", "P value"],
        ["Demographics", "Age, years", "52.6", "9.5", "56.6", "7.9", "0.0001"],
        ["Demographics", "Male sex", "92", "56.1%", "114", "82.0%", "0.00001"],
        ["Vitals", "Heart rate, bpm", "158.4", "19.2", "139.3", "22.6", "0.00001"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 3],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "part", "1": "normal", "2": "normal", "3": "normal", "4": "normal", "5": "normal", "6": "sig" },
        merges: [
          { source_cols: [2, 3], pattern: "paren" },
          { source_cols: [4, 5], pattern: "paren" },
        ],
        part_by: 0,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Domain", "Variable", "ArmA_Mean", "ArmA_SD", "ArmB_Mean", "ArmB_SD", "P value"],
      },
    });

    const t1Styled = applySuggestionsToDoc(createInitialTableDoc(t1Snap), "all", true);
    expect(t1Styled.style.preset).toBe("cns_three_line");
    expect(t1Styled.style.rowRhythm).toBe("zebra");

    // Switch to Matrix heatmap + Dual-Block Teal & Terracotta
    t1Styled.style.preset = "matrix_heatmap";
    t1Styled.style.paletteId = "danqing_dual_part";
    const t1HeatModel = buildModel(t1Styled, "en");
    expect(t1HeatModel.blocks).toHaveLength(2);
    const blk0Bg = t1HeatModel.blocks[0].rows[0][1].bgHex;
    const blk1Bg = t1HeatModel.blocks[1].rows[0][1].bgHex;
    expect(blk0Bg).not.toBeNull();
    expect(blk1Bg).not.toBeNull();
    expect(blk0Bg).not.toBe(blk1Bg);

    // 2. Wide time-series (4+ years with negative delta): FT editorial summary + Matrix heatmap + sequential ramp switch
    const wideSnap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_wide_spark",
      source: { filename: "wide.csv", sheet: "Sheet1", sheets: ["Sheet1"], kind: "sample", sha256: "w1" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Entity", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "2000", numeric_ratio: 1, detected_unit: "%", role: "normal" },
        { col: 2, name: "2008", numeric_ratio: 1, detected_unit: "%", role: "normal" },
        { col: 3, name: "2016", numeric_ratio: 1, detected_unit: "%", role: "normal" },
        { col: 4, name: "2023", numeric_ratio: 1, detected_unit: "%", role: "normal" },
      ],
      grid: [
        ["Entity", "2000", "2008", "2016", "2023"],
        ["Denmark", "16.4", "28.5", "60.5", "81.9"],
        ["Canada", "60.5", "61.0", "63.2", "59.6"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 2],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "normal", "2": "normal", "3": "normal", "4": "normal" },
        merges: [],
        part_by: null,
        sparkline_runs: [{ source_cols: [1, 2, 3, 4], label: "2000–2023" }],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Entity", "2000", "2008", "2016", "2023"],
      },
    });

    const wideStyled = applySuggestionsToDoc(createInitialTableDoc(wideSnap), "all", true);
    expect(wideStyled.style.preset).toBe("ft_editorial");
    const ftModel = buildModel(wideStyled, "en");
    expect(ftModel.headers.map((h) => h.label)).toEqual([
      "Entity",
      "2000 (%)",
      "2023 (%)",
      "Δ 2000–2023 (%)",
      "2000–2023 (%)",
    ]);
    expect(ftModel.blocks[0].rows[0][2].barRatio).not.toBeNull();
    expect(ftModel.blocks[0].rows[0][3].display).toBe("+65.5");
    expect(ftModel.blocks[0].rows[1][3].display).toBe("-0.9");
    expect(ftModel.blocks[0].rows[0][4].sparklineValues).toHaveLength(4);

    // Switch to Matrix heatmap and verify sequential palettes actually change colors even when negative values (-0.9) exist
    wideStyled.style.preset = "matrix_heatmap";
    wideStyled.style.paletteId = "danqing_umi_teal";
    const tealModel = buildModel(wideStyled, "en");
    wideStyled.style.paletteId = "danqing_sdi_terracotta";
    const terraModel = buildModel(wideStyled, "en");
    expect(tealModel.blocks[0].rows[0][3].bgHex).not.toBeNull();
    expect(terraModel.blocks[0].rows[0][3].bgHex).not.toBeNull();
    expect(tealModel.blocks[0].rows[0][3].bgHex).not.toBe(terraModel.blocks[0].rows[0][3].bgHex);
  });

  it("supports v0.6.1 partial column heatmaps, plain exclusions in matrix_heatmap, missing-cell white isolation, and multi-palette cohorts", () => {
    const snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_v061_partial",
      source: { filename: "bench.csv", sheet: "Sheet1", sheets: ["Sheet1"], kind: "sample", sha256: "v061a" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Model", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "AUROC", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 2, name: "RMSE", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 3, name: "OR", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 4, name: "FDR", numeric_ratio: 1, detected_unit: "", role: "sig" },
      ],
      grid: [
        ["Model", "AUROC", "RMSE", "OR", "FDR"],
        ["Method A", "0.94", "0.12", "2.00", "0.0001"],
        ["Method B", "NA", "0.45", "0.50", "0.040"],
        ["Method C", "0.72", "0.88", "1.00", "0.50"],
        ["Total bilirubin", "0.85", "0.30", "1.25", "0.008"],
        ["Total", "0.84", "99.9", "100.0", "0.000001"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 5],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "normal", "2": "normal", "3": "normal", "4": "sig" },
        merges: [],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Model", "AUROC", "RMSE", "OR", "FDR"],
      },
    });

    const doc = applySuggestionsToDoc(createInitialTableDoc(snap), "all", true);
    doc.style.preset = "cns_three_line";
    doc.style.rowRhythm = "zebra";

    // Turn ON heat ONLY on AUROC (umi_teal) and RMSE (sdi_terracotta, reversed), OR (diverging_bu_rd, ratio_1), FDR (-log10(P))
    const colAuroc = doc.structure.columns[1];
    const colRmse = doc.structure.columns[2];
    const colOr = doc.structure.columns[3];
    const colFdr = doc.structure.columns[4];

    colAuroc.visual = "heat";
    colAuroc.visualConfig = { paletteId: "danqing_umi_teal" };

    colRmse.visual = "heat";
    colRmse.visualConfig = { paletteId: "danqing_sdi_terracotta", direction: "reverse" };

    colOr.visual = "plain";
    colFdr.visual = "plain";

    const m1 = buildModel(doc, "zh");
    expect(m1.hasActiveHeatColumns).toBe(true);
    expect(m1.heatLegends).toHaveLength(2);
    expect(m1.detectedSummaryRowCount).toBe(1);

    // Row 3 ("Total bilirubin", index 3) MUST NOT be flagged as summary row; Row 4 ("Total", index 4) MUST be flagged!
    expect(m1.blocks[0].rows[3][0].isSummaryRow).toBe(false);
    expect(m1.blocks[0].rows[4][0].isSummaryRow).toBe(true);
    // With default excludeSummaryRows !== false, "Total" row has no heat bg and its extreme 99.9 RMSE does not crush Method A/B/C!
    expect(m1.blocks[0].rows[4][1].bgHex).toBeNull();
    expect(m1.blocks[0].rows[4][2].bgHex).toBeNull();
    expect(m1.blocks[0].rows[0][2].bgHex).not.toBe(m1.blocks[0].rows[2][2].bgHex);

    // Missing "NA" cell in Row 1 ("Method B", zebra odd row) of partial heat column AUROC stays null/white, NOT zebra gray (#F3F6FA)!
    expect(m1.blocks[0].rows[1][1].bgHex).toBeNull();
    // Meanwhile plain column OR on the same zebra row still gets zebra tint (#F3F6FA)
    expect(m1.blocks[0].rows[1][3].bgHex).toBe("#F3F6FA");

    // Toggle excludeSummaryRows OFF (User Decision #3): "Total" row now participates in coloring!
    doc.structure.excludeSummaryRows = false;
    const mSummaryIncluded = buildModel(doc, "zh");
    expect(mSummaryIncluded.blocks[0].rows[4][1].bgHex).not.toBeNull();
    expect(mSummaryIncluded.blocks[0].rows[4][2].bgHex).not.toBeNull();
    doc.structure.excludeSummaryRows = true;

    // Neutral slate_ink on FDR does NOT inflate chromatic activeHueCount
    colFdr.visual = "heat";
    colFdr.visualConfig = { paletteId: "danqing_slate_ink" };
    expect(buildModel(doc, "zh").activeHueCount).toBe(2);

    // OR ratio_1 center + FDR -log10(P) heatmap + >3 chromatic hues gentle counter (User Decision #1)
    colOr.visual = "heat";
    colOr.visualConfig = { paletteId: "danqing_diverging_bu_rd", center: "ratio_1" };
    colFdr.visual = "heat";
    colFdr.visualConfig = { paletteId: "danqing_kyoto_moss" };

    const m4Hues = buildModel(doc, "zh");
    expect(m4Hues.activeHueCount).toBe(4);
    // When >3 cohorts exist, caption legends collapse and headers carry inline ramp underlines!
    expect(m4Hues.heatLegends).toHaveLength(0);
    expect(m4Hues.headers[1].headerRampStops).not.toBeNull();
    // FDR preserves "<0.001***" text while receiving a darker heat fill than 0.50
    expect(m4Hues.blocks[0].rows[0][4].display).toContain("<0.001");
    expect(m4Hues.blocks[0].rows[0][4].bgHex).not.toBe(m4Hues.blocks[0].rows[2][4].bgHex);
    // OR = 1.00 sits at neutral center while OR = 2.00 and OR = 0.50 diverge to opposite poles
    expect(m4Hues.blocks[0].rows[0][3].bgHex).not.toBe(m4Hues.blocks[0].rows[1][3].bgHex);

    // Cohort isolation under per_row: single-column cohort falls back to per_column instead of flattening to 0.5!
    doc.style.heatScope = "per_row";
    const mPerRow = buildModel(doc, "zh");
    expect(mPerRow.blocks[0].rows[0][1].bgHex).not.toBe(mPerRow.blocks[0].rows[2][1].bgHex);

    // Turning OFF heatmap ("plain") on 1 column inside matrix_heatmap leaves all other columns heated
    doc.style.preset = "matrix_heatmap";
    doc.style.heatScope = "per_column";
    for (const c of doc.structure.columns) {
      c.visual = "auto";
      c.visualConfig = undefined;
    }
    colRmse.visual = "plain";
    const mMatrix = buildModel(doc, "zh");
    expect(mMatrix.blocks[0].rows[0][1].bgHex).not.toBeNull();
    expect(mMatrix.blocks[0].rows[0][2].bgHex).toBeNull();
  });

  it("supports v0.6.1 universal inline bars on merged Mean (SD), 0-100 fixed domain, and signed bidirectional zero-axis geometry", () => {
    const snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_v061_bars",
      source: { filename: "bars.csv", sheet: "Sheet1", sheets: ["Sheet1"], kind: "sample", sha256: "v061b" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Group", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "ResponseRate", numeric_ratio: 1, detected_unit: "%", role: "normal" },
        { col: 2, name: "Delta", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 3, name: "Score_Mean", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 4, name: "Score_SD", numeric_ratio: 1, detected_unit: "", role: "normal" },
      ],
      grid: [
        ["Group", "ResponseRate", "Delta", "Score_Mean", "Score_SD"],
        ["Arm 1", "40", "-20", "75.2", "4.1"],
        ["Arm 2", "80", "80", "50.0", "6.3"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 2],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "normal", "2": "normal", "3": "normal", "4": "normal" },
        merges: [{ source_cols: [3, 4], pattern: "paren" }],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Group", "ResponseRate", "Delta", "Score_Mean", "Score_SD"],
      },
    });

    const doc = applySuggestionsToDoc(createInitialTableDoc(snap), "all", true);
    doc.style.preset = "cns_three_line";

    // Enable bar on ResponseRate (column_max vs percent_100), Delta (signed bidirectional), and merged Score_Mean (SD)!
    doc.structure.columns[1].visual = "bar";
    doc.structure.columns[2].visual = "bar";
    doc.structure.columns[3].visual = "bar";

    const mMax = buildModel(doc, "en");
    // Under default column_max, 80 is max -> widthPct = 100%, 40 -> widthPct = 50%
    expect(mMax.blocks[0].rows[1][1].barSpec?.widthPct).toBeCloseTo(100, 1);
    expect(mMax.blocks[0].rows[0][1].barSpec?.widthPct).toBeCloseTo(50, 1);

    // Switch ResponseRate to 0-100 fixed domain (User Decision #2): 80 -> widthPct = 80%, 40 -> widthPct = 40%
    doc.structure.columns[1].visualConfig = { barDomain: "percent_100" };
    const mPct = buildModel(doc, "en");
    expect(mPct.blocks[0].rows[1][1].barSpec?.widthPct).toBeCloseTo(80, 1);
    expect(mPct.blocks[0].rows[0][1].barSpec?.widthPct).toBeCloseTo(40, 1);

    // Signed bidirectional Delta (-20 and +80 -> span 100, zeroPct = 20%)
    const negBar = mPct.blocks[0].rows[0][2].barSpec!;
    const posBar = mPct.blocks[0].rows[1][2].barSpec!;
    expect(negBar.bidirectional).toBe(true);
    expect(negBar.zeroPct).toBeCloseTo(20, 1);
    expect(negBar.startPct).toBeCloseTo(0, 1);
    expect(negBar.widthPct).toBeCloseTo(20, 1);
    expect(negBar.isNegative).toBe(true);

    expect(posBar.zeroPct).toBeCloseTo(20, 1);
    expect(posBar.startPct).toBeCloseTo(20, 1);
    expect(posBar.widthPct).toBeCloseTo(80, 1);
    expect(posBar.isNegative).toBe(false);
    expect(negBar.fillHex).not.toBe(posBar.fillHex);

    // Merged Mean (SD) column carries BOTH aligned dual-part numbers AND barSpec + barValWidthCh!
    const mergedCell = mPct.blocks[0].rows[0][3];
    expect(mergedCell.parts).toHaveLength(2);
    expect(mergedCell.barSpec).not.toBeNull();
    expect(mPct.headers[3].barValWidthCh).toBeGreaterThanOrEqual(8);
  });

  it("evaluates v3 multi-scope sigBindings, Median [IQR] merges, flat-header spanners, and protagonist inline bars", () => {
    const hcvPath = path.resolve(
      __dirname,
      "../../../../bench/tables/out/hcv_multicohort_contrasts.csv",
    );
    const grid = fs
      .readFileSync(hcvPath, "utf-8")
      .trim()
      .split(/\r?\n/)
      .map((line: string) => line.split(","));

    const snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_hcv_test",
      sample_id: "hcv_multicohort_contrasts",
      source: {
        filename: "hcv_multicohort_contrasts.csv",
        sheet: "Sheet1",
        sheets: ["Sheet1"],
        kind: "sample",
        sha256: "hcv",
      },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: grid[0].map((name: string, col: number) => ({
        col,
        name,
        numeric_ratio: col === 0 ? 0 : 1,
        detected_unit: "",
        role: col === 5 || col === 10 ? "sig" : col === 4 || col === 9 ? "bar" : "normal",
      })),
      grid,
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, grid.length - 1],
        title_candidate: null,
        footnote_candidates: [],
        spanners: [
          { label: "Donor", source_cols: [1, 2, 3] },
          { label: "Fibrosis vs Donor", source_cols: [4, 5] },
          { label: "Cirrhosis", source_cols: [6, 7, 8] },
          { label: "Cirrhosis vs Donor", source_cols: [9, 10] },
        ],
        roles: {
          "0": "normal",
          "1": "normal",
          "2": "normal",
          "3": "normal",
          "4": "bar",
          "5": "sig",
          "6": "normal",
          "7": "normal",
          "8": "normal",
          "9": "bar",
          "10": "sig",
        },
        merges: [
          { source_cols: [1, 2, 3], pattern: "iqr" },
          { source_cols: [6, 7, 8], pattern: "iqr" },
        ],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: grid[0],
        leaf_headers: [
          "Biomarker",
          "Median",
          "Q1",
          "Q3",
          "log2FC",
          "FDR",
          "Median",
          "Q1",
          "Q3",
          "log2FC",
          "FDR",
        ],
        sig_bindings: [
          { source_col: 5, target_cols: [4], label: "Fibrosis vs Donor" },
          { source_col: 10, target_cols: [9], label: "Cirrhosis vs Donor" },
        ],
      },
    });

    const tidied = applySuggestionsToDoc(createInitialTableDoc(snap), "all", true);
    expect(tidied.style.preset).toBe("cns_three_line");
    expect(tidied.structure.sig.bindings).toHaveLength(2);

    const model = buildModel(tidied, "en");
    expect(model.headers.map((h) => h.label)).toEqual([
      "Biomarker",
      "Median [IQR]",
      "log2FC",
      "FDR",
      "Median [IQR]",
      "log2FC",
      "FDR",
    ]);
    expect(model.headers[2].effectiveVisual).toBe("bar");
    expect(model.headers[5].effectiveVisual).toBe("bar");
    expect(model.headers[1].effectiveVisual).toBe("plain");

    // Row 0: Albumin -> Fibrosis n.s. (-0.04, uniform 2 decimals, never -0.0!), Cirrhosis *** (-0.35***)
    const rowAlb = model.blocks[0].rows[0];
    expect(rowAlb[1].display).toContain("[");
    expect(rowAlb[2].display).toBe("-0.04");
    expect(rowAlb[2].bold).toBe(false);
    expect(rowAlb[5].display).toBe("-0.35***");
    expect(rowAlb[5].bold).toBe(true);

    // Row 1: Alkaline phosphatase -> Fibrosis *** (-0.75***), Cirrhosis n.s. (0.26)
    const rowAlp = model.blocks[0].rows[1];
    expect(rowAlp[2].display).toBe("-0.75***");
    expect(rowAlp[2].bold).toBe(true);
    expect(rowAlp[5].display).toBe("0.26");
    expect(rowAlp[5].bold).toBe(false);
  });

  it("formats computed Table 1 parent categorical rows, indented n(%) levels, and pre-bracketed [Q1–Q3] cleanly", () => {
    const snap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_comp_t1",
      source: { filename: "raw.csv", sheet: "Computed", sheets: ["Computed"], kind: "csv", sha256: "t1c" },
      sheets_meta: [{ name: "Computed", empty: false }],
      column_stats: [
        { col: 0, name: "Characteristic", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "No CAD_val", numeric_ratio: 0.75, detected_unit: "", role: "normal" },
        { col: 2, name: "No CAD_aux", numeric_ratio: 0.5, detected_unit: "", role: "normal" },
        { col: 3, name: "P value", numeric_ratio: 0.67, detected_unit: "", role: "sig" },
      ],
      grid: [
        ["Characteristic", "No CAD_val", "No CAD_aux", "P value"],
        ["Age (yr)^a", "52.6", "9.5", "0.0001"],
        ["ST Depression (mV)^c", "0.2", "[0.0–1.0]", "0.00001"],
        ["Major Vessels, n (%)^b", "", "", "0.00001"],
        ["0", "130", "80.7%", ""],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 4],
        title_candidate: "Table 1",
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "normal", "2": "normal", "3": "sig" },
        merges: [{ source_cols: [1, 2], pattern: "plusminus" }],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Characteristic", "No CAD_val", "No CAD_aux", "P value"],
      },
    });

    const doc = applySuggestionsToDoc(createInitialTableDoc(snap), "all", true);
    doc.structure.merges[0].mergedLabel = "No CAD (n=164)";
    doc.structure.rowIndents[3] = 1; // "0" numeric-code category sub-row indented

    const model = buildModel(doc, "en");
    const rows = model.blocks[0].rows;
    expect(rows[0][1].display).toBe("52.6 ± 9.5");
    // Pre-bracketed IQR string must NOT be double-wrapped as `([0.0–1.0])`
    expect(rows[1][1].display).toBe("0.2 [0.0–1.0]");
    // Categorical parent row arm cell stays blank "" while P value formats cleanly
    expect(rows[2][1].display).toBe("");
    expect(rows[2][2].display).toBe("<0.001***");
    // Indented numeric-coded category sub-row ("0") stays left-aligned literal "0" (NEVER right-aligned "0.00"!)
    expect(rows[3][0].display).toBe("0");
    expect(rows[3][0].align).toBe("left");
    expect(rows[3][0].indent).toBe(1);
    expect(rows[3][1].display).toBe("130 (80.7%)");
    expect(rows[3][2].display).toBe("");
  });

  it("supports non-destructive goToStage round-trips, stashedComputed recall, and unapplied suggestion tracking", () => {
    const rawSnap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_stage_rt",
      source: { filename: "rep.csv", sheet: "Sheet1", sheets: ["Sheet1"], kind: "csv", sha256: "rt1" },
      sheets_meta: [{ name: "Sheet1", empty: false }],
      column_stats: [
        { col: 0, name: "Feature", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "Ctrl_val", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 2, name: "Ctrl_sd", numeric_ratio: 1, detected_unit: "", role: "normal" },
        { col: 3, name: "P value", numeric_ratio: 1, detected_unit: "", role: "sig" },
      ],
      grid: [
        ["Feature", "Ctrl_val", "Ctrl_sd", "P value"],
        ["Radius", "12.1", "1.7", "0.002"],
        ["Area", "462.8", "134.3", "0.0004"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 2],
        title_candidate: null,
        footnote_candidates: ["* P < 0.05"],
        spanners: [],
        roles: { "0": "normal", "1": "normal", "2": "normal", "3": "sig" },
        merges: [{ source_cols: [1, 2], pattern: "plusminus" }],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Feature", "Ctrl_val", "Ctrl_sd", "P value"],
      },
    });

    // 1. User leaves `raw` stage by clicking a right-sidebar preset (`ft_editorial`) without running Tidy
    const initDoc = createInitialTableDoc(rawSnap);
    useTableStudioStore.setState({
      docs: { d1: initDoc },
      order: ["d1"],
      activeId: "d1",
      historyPast: { d1: [] },
      historyFuture: { d1: [] },
      isComparingRaw: false,
    });

    useTableStudioStore.getState().commit((draft) => {
      draft.style.preset = "ft_editorial";
      draft.style.lastStyledPreset = "ft_editorial";
      draft.structure.stage = "tidied";
      draft.structure.title = "Custom Cohort Title";
    });

    const afterPreset = useTableStudioStore.getState().docs.d1;
    // Unapplied suggestions (`footer`, `merges`, `sig`) remain discoverable!
    const unapplied = listUnappliedSuggestions(afterPreset);
    expect(unapplied).toContain("footer");
    expect(unapplied).toContain("merges");
    expect(unapplied).toContain("sig");

    // 2. User clicks `原表` (`goToStage("raw")`) -> switches to raw view WITHOUT losing custom title or `ft_editorial`
    useTableStudioStore.getState().goToStage("raw");
    const inRaw = useTableStudioStore.getState().docs.d1;
    expect(inRaw.structure.stage).toBe("raw");
    expect(inRaw.structure.title).toBe("Custom Cohort Title");
    expect(inRaw.style.lastStyledPreset).toBe("ft_editorial");

    // 3. User clicks `已整理` (`goToStage("tidied")`) -> unstyled grid (`preset === "raw"`), remembers `ft_editorial`
    useTableStudioStore.getState().goToStage("tidied");
    const inTidied = useTableStudioStore.getState().docs.d1;
    expect(inTidied.structure.stage).toBe("tidied");
    expect(inTidied.style.preset).toBe("raw");
    expect(inTidied.style.lastStyledPreset).toBe("ft_editorial");

    // 4. User clicks `已美化` (`goToStage("styled")`) -> restores `ft_editorial` AND custom title!
    useTableStudioStore.getState().goToStage("styled");
    const inStyled = useTableStudioStore.getState().docs.d1;
    expect(inStyled.structure.stage).toBe("tidied");
    expect(inStyled.style.preset).toBe("ft_editorial");
    expect(inStyled.structure.title).toBe("Custom Cohort Title");

    // 5. Auto-computed table (`sourceRaw != null`) stashes computed summary when clicking `原表` and restores on `已美化`
    const computedSnap = normalizeRawSnapshotPayload({
      snapshot_id: "tbl_comp_out",
      source: { filename: "rep.csv", sheet: "Computed", sheets: ["Computed"], kind: "csv", sha256: "cp1" },
      sheets_meta: [{ name: "Computed", empty: false }],
      column_stats: [
        { col: 0, name: "Feature", numeric_ratio: 0, detected_unit: "", role: "normal" },
        { col: 1, name: "Mean", numeric_ratio: 1, detected_unit: "", role: "normal" },
      ],
      grid: [
        ["Feature", "Mean"],
        ["Radius", "12.1 ± 1.7"],
      ],
      cell_merges: [],
      warnings: [],
      suggestions: {
        header_rows: [0, 0],
        body_range: [1, 1],
        title_candidate: "Computed Summary",
        footnote_candidates: [],
        spanners: [],
        roles: { "0": "normal", "1": "normal" },
        merges: [],
        part_by: null,
        sparkline_runs: [],
        pivot: null,
        decimal_comma: false,
        resolved_headers: ["Feature", "Mean"],
      },
    });
    const compDoc = applySuggestionsToDoc(createInitialTableDoc(computedSnap), "all", true);
    compDoc.style.preset = "cns_three_line";
    compDoc.style.lastStyledPreset = "cns_three_line";
    compDoc.sourceRaw = rawSnap;
    compDoc.structure.title = "Edited Computed Table";

    useTableStudioStore.setState({
      docs: { d1: compDoc },
      historyPast: { d1: [] },
      historyFuture: { d1: [] },
    });

    // Click `原表` (or `revertComputedToRaw`) -> restores rawSnap grid AND stashes computed table
    useTableStudioStore.getState().revertComputedToRaw();
    const backInRaw = useTableStudioStore.getState().docs.d1;
    expect(backInRaw.structure.stage).toBe("raw");
    expect(backInRaw.raw.snapshotId).toBe("tbl_stage_rt");
    expect(backInRaw.stashedComputed?.structure.title).toBe("Edited Computed Table");

    // Click `已美化` -> restores computed table + custom title!
    useTableStudioStore.getState().goToStage("styled");
    const restoredComp = useTableStudioStore.getState().docs.d1;
    expect(restoredComp.raw.snapshotId).toBe("tbl_comp_out");
    expect(restoredComp.sourceRaw?.snapshotId).toBe("tbl_stage_rt");
    expect(restoredComp.structure.title).toBe("Edited Computed Table");
    expect(restoredComp.style.preset).toBe("cns_three_line");
  });
});
