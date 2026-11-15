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
});
