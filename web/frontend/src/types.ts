export type ElementRole = "focus" | "normal" | "background";
export type CrossPanelRule = "same_name" | "unique";
export type VibrancyMode = "muted" | "standard" | "vivid";
export type CvdMode = "normal" | "deutan" | "protan" | "tritan" | "grayscale";
export type ExportFormat = "pdf" | "svg" | "png_300" | "png_600";

export interface LocalizedText {
  en: string;
  zh: string;
}

export interface PaletteSource {
  title: string;
  author: string;
  year: number | string;
  url: string;
  license: string;
}

export interface PaletteArtifact {
  museum: string;
  object_id: string;
  title: string;
  date: string;
  url: string;
  image_url?: string;
  thumbnail_url?: string;
  thumbnail?: string;
  image_license?: string;
}

export interface PaletteQc {
  color_count: number;
  max_colors: number;
  colorblind_safe: boolean;
  print_friendly: boolean;
  min_de2000_first6?: number;
}

export interface PaletteItem {
  id: string;
  name: LocalizedText;
  collection: "accessible" | "journal" | "museum" | "eastern" | "many" | "continuous" | "convention";
  kind: "qualitative" | "sequential" | "diverging";
  order: "discrete" | "gradient";
  colors: string[];
  neutral: string;
  partners: {
    sequential: string;
    diverging: string;
  };
  source: PaletteSource;
  artifact: PaletteArtifact | null;
  qc: PaletteQc;
  dynamic_generator: string | null;
  convention_keys: string[];
}

export interface PresetSummary {
  preset_id: string;
  filename: string;
  title: LocalizedText;
  subtitle: LocalizedText;
  citation?: LocalizedText;
  source_url?: string;
  thumbnail_url: string;
}

export interface InspectorSwatch {
  hex: string;
  min_de: number;
  too_close_to: string | null;
}

export interface FigureElement {
  entity_id: string;
  label: string;
  panels: string[];
  member_group_ids: string[];
  original_hex: string;
  current_hex: string;
  role: ElementRole;
  locked: boolean;
  unlinked: boolean;
  primitive_count: number;
  inspector_swatches: InspectorSwatch[];
}

export interface CategoricalLutEntry {
  cat_index: number;
  group_id: string;
  entity_id: string;
  panel_id: string;
  role: string;
  original_hex: string;
  current_hex: string;
}

export interface ContinuousScaleItem {
  scale_index: number;
  id_map_r_code: number;
  scale_id: string;
  panel_id: string;
  title: string;
  kind: "continuous_sequential" | "continuous_diverging";
  midpoint_t: number;
  colorbar_bbox: [number, number, number, number] | null;
  inverted_polarity: boolean;
  original_stops_hex: string[];
  current_stops_hex: string[];
  gradient_preview_stops: string[];
}

export interface ProtectedImageItem {
  region_id: string;
  name: string;
  panel_id: string;
  bbox: [number, number, number, number];
  width_px: number;
  height_px: number;
  subtype: string;
}

export interface PlainNotice {
  kind: "colorblind_hard_to_tell" | "inconsistent_same_name";
  panel?: string;
  count?: number;
  label?: string;
  panel_a?: string;
  panel_b?: string;
  entity_ids: string[];
}

export interface FigureDiagnostics {
  palette_color_count: number;
  required_color_count: number;
  generated_count: number;
  colorblind_deutan_safe: boolean;
  colorblind_protan_safe: boolean;
  colorblind_problem_panels: string[];
  min_de2000_normal: number;
  min_de2000_deutan: number;
}

export interface PanelBox {
  panel_id: string;
  title: string;
  bbox: [number, number, number, number];
}

export interface FigureState {
  figure_id: string;
  filename: string;
  kind: "pdf" | "svg";
  width: number;
  height: number;
  preview_scale: number;
  page_index: number;
  page_count: number;
  op_count: number;
  slow_warning: boolean;
  palette_id: string | null;
  active_palette_fallback: string;
  is_original_mode: boolean;
  panel_palettes?: Record<string, string>;
  rule: CrossPanelRule;
  vibrancy: VibrancyMode;
  keep_consistent: boolean;
  can_undo: boolean;
  can_redo: boolean;
  revision: number;
  render_url: string;
  original_url: string;
  pick_url: string;
  panels: PanelBox[];
  elements: FigureElement[];
  categorical_lut: CategoricalLutEntry[];
  continuous_scales: ContinuousScaleItem[];
  protected_images: ProtectedImageItem[];
  plain_notices: PlainNotice[];
  diagnostics: FigureDiagnostics;
  recommended_conventions: string[];
}

export interface SessionFigureSummary {
  figure_id: string;
  filename: string;
  kind: "pdf" | "svg";
  is_preset: boolean;
  is_original_mode: boolean;
  palette_id: string;
}

export interface MultipageChoicePayload {
  pending_upload_id: string;
  filename: string;
  page_count: number;
  pages: Array<{
    index: number;
    width: number;
    height: number;
    thumbnail: string;
  }>;
}

export interface ExportChecksResult {
  filename: string;
  size_kb: number;
  checks: {
    shapes_and_text_unchanged: boolean;
    raw_images_untouched: {
      passed: boolean;
      count: number;
    };
    colorblind_safe: {
      passed: boolean;
      min_de_deutan: number;
      problem_panels: string[];
    };
    all_passed: boolean;
    integrity_passed: boolean;
  };
}

export type ManuscriptPresetKey = "cns_clean" | "clinical" | "omics" | "museum";

export interface ManuscriptRecommendation {
  palette_id: string;
  reason: LocalizedText;
}
