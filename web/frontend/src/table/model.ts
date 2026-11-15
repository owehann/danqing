export type ColumnRole = "normal" | "count" | "part" | "heat" | "sig" | "bar";
export type Precision = "auto" | 0 | 1 | 2 | 3;
export type PStyle = "nejm" | "apa" | "exact";

export type ParseWarningCode =
  | "FORMULA_NO_CACHE"
  | "RAGGED_ROWS"
  | "DUPLICATE_HEADERS"
  | "LOCALE_DECIMAL_COMMA"
  | "EMPTY_SHEET"
  | "TITLE_ROWS_SKIPPED"
  | "FOOTER_ROWS_DETECTED";

export interface ParseWarning {
  code: ParseWarningCode;
  detail: Record<string, string | number>;
}

export interface SheetMeta {
  name: string;
  empty: boolean;
}

export interface ColumnStat {
  col: number;
  name: string;
  numericRatio: number;
  minVal: number | null;
  maxVal: number | null;
  detectedUnit: string;
  seqRatio: number;
  isAllInt: boolean;
  role: ColumnRole;
}

export interface PivotSpec {
  rowKey: number;
  colKey: number;
  valueCols: number[];
  retainRowCols?: number[];
  colCounts?: Record<string, string>;
}

export interface TidySuggestions {
  headerRows: [number, number];
  bodyRange: [number, number];
  titleCandidate: string | null;
  footnoteCandidates: string[];
  spanners: Array<{ label: string; sourceCols: number[] }>;
  roles: Record<number, ColumnRole>;
  merges: Array<{ sourceCols: number[]; pattern: "paren" | "plusminus" | "ci" }>;
  partBy: number | null;
  sparklineRuns: Array<{ sourceCols: number[]; label: string }>;
  pivot: PivotSpec | null;
  decimalComma: boolean;
  resolvedHeaders: string[];
}

export interface RawSnapshot {
  snapshotId: string;
  sampleId?: string;
  source: {
    filename: string;
    sheet: string;
    sheets: string[];
    kind: "csv" | "tsv" | "xlsx" | "paste" | "sample";
    sha256: string;
  };
  sheetsMeta: SheetMeta[];
  columnStats: ColumnStat[];
  grid: string[][];
  cellMerges: Array<{ r0: number; c0: number; r1: number; c1: number }>;
  warnings: ParseWarning[];
  suggestions: TidySuggestions;
}

export type DerivedMetricKind = "sparkline" | "first" | "last" | "delta";

export type ColumnSource =
  | { kind: "grid"; col: number }
  | { kind: "derived"; derivedId: string; metric?: DerivedMetricKind }
  | { kind: "pivot"; key: string; valueCol: number };

export interface ColumnSpec {
  id: string;
  source: ColumnSource;
  label: string;
  hidden: boolean;
  role: ColumnRole;
  precision: Precision;
  unit: string;
}

export interface SpannerSpec {
  id: string;
  label: string;
  columnIds: string[];
}

export interface MergeSpec {
  id: string;
  columnIds: string[];
  pattern: "paren" | "plusminus" | "ci";
  mergedLabel?: string;
}

export interface DerivedSparklineSpec {
  id: string;
  kind: "sparkline";
  sourceIds: string[];
  sharedScale: boolean;
}

export interface FootnoteSpec {
  id: string;
  symbol: string;
  text: string;
  anchorColumnIds: string[];
}

export interface SigConfig {
  sourceId: string | null;
  targetIds: string[];
  pStyle: PStyle;
  stars: boolean;
}

export interface StructureLayer {
  stage: "raw" | "tidied";
  headerRows: [number, number];
  bodyRange: [number, number];
  pivot: PivotSpec | null;
  columns: ColumnSpec[];
  spanners: SpannerSpec[];
  merges: MergeSpec[];
  derived: DerivedSparklineSpec[];
  partBy: string | null;
  partOrder: string[] | "appearance";
  sort: Array<{ columnId: string; dir: "asc" | "desc" }>;
  cellOverrides: Record<string, { from: string; to: string }>;
  rowIndents: Record<number, 0 | 1>;
  missingToken: "—" | "NA" | "";
  tableNumber: string;
  title: string;
  subtitle: string;
  footnotes: FootnoteSpec[];
  sig: SigConfig;
  dismissedSuggestions: string[];
}

export type TablePresetId = "raw" | "matrix_heatmap" | "cns_three_line" | "ft_editorial";
export type HeatScope = "per_column" | "per_part" | "per_row" | "global";
export type EmphasisPolicy = "bold_star_mono" | "accent_bold" | "hairline_box" | "off";
export type RowRhythm = "none" | "zebra" | "group_breathing";

export interface StyleLayer {
  preset: TablePresetId;
  paletteId: string;
  heatScope: HeatScope;
  heatCenter: "auto" | number;
  heatLog: boolean;
  emphasis: EmphasisPolicy;
  rowRhythm: RowRhythm;
  tabularNums: boolean;
}

export interface TableDoc {
  raw: RawSnapshot;
  structure: StructureLayer;
  style: StyleLayer;
}

export interface SampleCatalogItem {
  id: string;
  filename: string;
  raw_filename: string;
  url: string;
  source_page: string;
  provider_en: string;
  provider_zh: string;
  license: string;
  title_en: string;
  title_zh: string;
  needs_en: string;
  needs_zh: string;
  raw_sha256: string;
  out_sha256: string;
  rows: number;
  cols: number;
  preview_grid: string[][];
}

export interface RenderedCellPart {
  display: string;
  value: number | null;
}

export interface RenderedCell {
  key: string;
  bodyRowIndex: number;
  colId: string;
  editableColId: string | null;
  raw: string;
  value: number | null;
  heatValue: number | null;
  display: string;
  superscript: string;
  numFmt: string;
  edited: boolean;
  editedFrom: string | null;
  indent: 0 | 1;
  align: "left" | "right";
  role: ColumnRole;
  bgHex: string | null;
  fgHex: string;
  bold: boolean;
  boxBorder: boolean;
  noWrap: boolean;
  parts: RenderedCellPart[] | null;
  sparklineValues: number[] | null;
  sparklineDomain: [number, number] | null;
  barRatio: number | null;
}

export interface RenderedHeader {
  colId: string;
  memberColIds: string[];
  label: string;
  rawLabel: string;
  unit: string;
  superscript: string;
  role: ColumnRole;
  align: "left" | "right";
  isMerged: boolean;
  partWidthsCh: [number, number] | null;
  sortDir: "asc" | "desc" | null;
  ratioHint: boolean;
  logBlocked: boolean;
}

export interface RenderedSpanner {
  id: string;
  label: string;
  superscript: string;
  startCol: number;
  endCol: number;
  columnIds: string[];
}

export interface RenderedBlock {
  blockIndex: number;
  partName: string;
  partAccent: string;
  rows: RenderedCell[][];
}

export interface RenderedFootnote {
  id: string;
  symbol: string;
  text: string;
  readOnly: boolean;
}

export interface RawDataSheetModel {
  headers: string[];
  rows: Array<Array<string | number | null>>;
}

export interface HeatLegendModel {
  stops: string[];
  secondaryStops?: string[];
  scope: HeatScope;
  minLabel: string;
  maxLabel: string;
  diverging: boolean;
}

export interface RenderModel {
  stage: "raw" | "tidied" | "styled";
  preset: TablePresetId;
  recommendedPreset: Exclude<TablePresetId, "raw">;
  accentHex: string;
  tabularNums: boolean;
  tableNumber: string;
  title: string;
  subtitle: string;
  rawGrid: string[][];
  suggestedHeaderRows: [number, number];
  suggestedFooterRowStart: number | null;
  spanners: RenderedSpanner[];
  headers: RenderedHeader[];
  blocks: RenderedBlock[];
  footnotes: RenderedFootnote[];
  totalRows: number;
  totalCols: number;
  blockCount: number;
  editedCount: number;
  globalHeatAllowed: boolean;
  hasHeatColumns: boolean;
  isMultiScaleHeat: boolean;
  heatLegend: HeatLegendModel | null;
  rawDataSheet: RawDataSheetModel;
}
