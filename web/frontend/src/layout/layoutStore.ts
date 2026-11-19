import { create } from "zustand";

export type LegendPosMode =
  | "auto"
  | "inside_tr"
  | "inside_tl"
  | "inside_br"
  | "inside_bl"
  | "top"
  | "bottom"
  | "right"
  | "custom"
  | "hidden";

export type LegendOrientMode = "auto" | "vertical" | "horizontal";

export interface LayoutROIConfig {
  enabled: boolean;
  x_norm: number;
  y_norm: number;
  w_norm: number;
  h_norm: number;
  label: string;
  color: string;
  dashed: boolean;
  scale_bar_um: number | null;
  fov_width_um: number | null;
  linked_source_id: string | null;
}

export interface TextItemOverrideState {
  color: string | null;
  font_family: string | null;
  bold: boolean | null;
  italic: boolean;
  font_scale: number;
  text: string | null;
}

export const DEFAULT_TEXT_ITEM_OVERRIDE: TextItemOverrideState = {
  color: null,
  font_family: null,
  bold: null,
  italic: false,
  font_scale: 1.0,
  text: null,
};

export interface LayoutTextItemMeta {
  item_key: string;
  role: string;
  text: string;
  orig_text: string;
  bbox_mm: [number, number, number, number];
  font_pt: number;
  font_family: string;
  bold: boolean;
  italic: boolean;
  fill: string;
  angle_deg: number;
  swatch_color?: string | null;
}

export interface PanelOverrideState {
  custom_tag: string | null;
  font_scale: number;
  legend_scale: number;
  marker_scale: number;
  stroke_scale: number;
  show_title: boolean | null;
  panel_font_family: string | null;
  legend_font_family: string | null;
  legend_bold: boolean;
  legend_text_color: string;
  legend_match_swatch: boolean;
  legend_orient: LegendOrientMode;
  legend_pos: LegendPosMode;
  legend_xy_norm: [number, number];
  legend_cols: number;
  legend_bg: boolean;
  pad_top_mm: number;
  pad_bottom_mm: number;
  pad_left_mm: number;
  pad_right_mm: number;
  frame_width_ratio: number;
  category_spacing: number;
  text_overrides: Record<string, TextItemOverrideState>;
}

export const DEFAULT_PANEL_OVERRIDE: PanelOverrideState = {
  custom_tag: null,
  font_scale: 1.0,
  legend_scale: 1.0,
  marker_scale: 1.0,
  stroke_scale: 1.0,
  show_title: null,
  panel_font_family: null,
  legend_font_family: null,
  legend_bold: false,
  legend_text_color: "#000000",
  legend_match_swatch: false,
  legend_orient: "auto",
  legend_pos: "auto",
  legend_xy_norm: [0.62, 0.06],
  legend_cols: 1,
  legend_bg: true,
  pad_top_mm: 0.0,
  pad_bottom_mm: 0.0,
  pad_left_mm: 0.0,
  pad_right_mm: 0.0,
  frame_width_ratio: 1.0,
  category_spacing: 1.0,
  text_overrides: {},
};

export interface BentoBlockState {
  panel_ids: string[];
  weight: number;
}

export interface BentoRowState {
  blocks: BentoBlockState[];
  height_scale: number;
}

export type CanvasDropTarget =
  | {
      kind: "slot";
      dstPanelId: string;
      zone: "swap" | "left" | "right" | "stack_top" | "stack_bottom";
    }
  | {
      kind: "new_row";
      insertRowIdx: number;
    };

export interface LayoutPanelItem {
  panel_id: string;
  filename: string;
  elasticity: string;
  locked_special: boolean;
  has_legend: boolean;
  is_colorbar?: boolean;
  is_categorical_x: boolean;
  default_selected: boolean;
  raw_size_desc: string;
  source: string;
  is_builtin: boolean;
  thumb_svg: string;
  default_roi: LayoutROIConfig;
}

export interface LayoutSamplePack {
  pack_id: string;
  panel_ids: string[];
  panel_count: number;
  journal_id: string;
  layout_mode: string;
  title_zh: string;
  title_en: string;
  sub_zh: string;
  sub_en: string;
  cite_zh: string;
  cite_en: string;
  preview_svg: string;
}

export interface LayoutJournalFamily {
  id: string;
  name: string;
  name_zh: string;
}

export interface LayoutJournalItem {
  id: string;
  family_id: string;
  tier_id: string;
  name: string;
  name_zh: string;
  width_mm: number;
  double_col_mm?: number;
  max_height_mm: number;
  tag_case: string;
  tag_pt: number;
  title_pt: number;
  axis_title_pt: number;
  tick_pt: number;
  annotation_pt: number;
  axis_stroke_pt: number;
  data_stroke_pt: number;
  grid_stroke_pt: number;
  default_font: string;
}

export interface LayoutModeOption {
  id: string;
  name: string;
  name_zh: string;
  desc: string;
}

export interface LayoutGateResult {
  id: string;
  name: string;
  name_zh: string;
  passed: boolean;
  metric: string;
}

export interface LayoutSlotMeta {
  panel_id: string;
  tag_label: string;
  row_idx: number;
  block_idx: number;
  stack_idx: number;
  col_start: number;
  col_span: number;
  weight: number;
  row_span: number;
  outer_box_mm: [number, number, number, number];
  spine_box_mm: [number, number, number, number];
  legend_box_mm: [number, number, number, number] | null;
  effective_legend_pos?: string;
  effective_legend_orient?: string;
  has_legend: boolean;
  is_colorbar?: boolean;
  is_categorical_x: boolean;
  locked_special: boolean;
  elasticity: string;
  text_items?: LayoutTextItemMeta[];
}

export interface LayoutComposeResult {
  modular_svg: string;
  naive_svg: string;
  naive_stats: {
    min_font_pt: number;
    max_font_pt: number;
    min_stroke_pt: number;
    max_stroke_pt: number;
  };
  page_width_mm: number;
  page_height_mm: number;
  shared_legend_hoisted: boolean;
  overflow_warning: string | null;
  slots: LayoutSlotMeta[];
  bento_rows: BentoRowState[];
  row_bounds_mm: [number, number][];
  audit: {
    all_passed: boolean;
    passed_count: number;
    total_count: number;
    min_font_pt: number;
    max_font_pt: number;
    min_stroke_pt: number;
    max_stroke_pt: number;
    max_spine_error_mm: number;
    gates: LayoutGateResult[];
  };
  mode_b_contract: {
    r_snippet: string;
    python_snippet: string;
  };
}

interface LayoutStudioState {
  layoutPageMode: "landing" | "editor";
  initialized: boolean;
  busy: boolean;
  handoffBusy: boolean;

  panels: LayoutPanelItem[];
  packs: LayoutSamplePack[];
  journals: LayoutJournalItem[];
  journalFamilies: LayoutJournalFamily[];
  layoutModes: LayoutModeOption[];
  fontFamilies: string[];

  selectedIds: string[];
  focusedPanelId: string;
  focusedTextKey: string | null;
  inspectorTab: "page" | "panel";
  liveAnnouncement: string;

  journalId: string;
  customWidthMm: number;
  customMaxHeightMm: number;
  tagCaseOverride: "lower" | "upper" | null;
  tagFlow: "row_major" | "col_major";
  layoutMode: string;
  fontFamily: string;
  tagPt: number;
  titlePt: number;
  axisTitlePt: number;
  tickPt: number;
  annotationPt: number;
  axisStrokePt: number;
  dataStrokePt: number;
  gridStrokePt: number;
  gutterMm: number;
  markerPt: number;
  showPanelTitles: boolean;
  hoistSharedLegends: boolean;

  spanOverrides: Record<string, number>;
  lockedOverrides: Record<string, boolean>;
  roiOverrides: Record<string, LayoutROIConfig>;
  panelOverrides: Record<string, PanelOverrideState>;
  bentoRows: BentoRowState[] | null;

  isComparingNaive: boolean;
  showGuides: boolean;
  zoomPct: number;
  inspectorDrawerOpen: boolean;
  exportModalOpen: boolean;
  composed: LayoutComposeResult | null;

  initLayoutCatalog: () => Promise<void>;
  goToLayoutLanding: () => void;
  openSamplePack: (packId: string) => Promise<void>;
  openSandbox: (count?: number) => Promise<void>;
  uploadLayoutFiles: (files: FileList | File[]) => Promise<void>;

  togglePanel: (panelId: string) => void;
  movePanelOrder: (panelId: string, dir: -1 | 1) => void;
  selectQuickCount: (count: number) => void;
  setFocusedPanelId: (panelId: string, switchToPanelTab?: boolean) => void;
  setFocusedText: (panelId: string, itemKey: string | null, switchToPanelTab?: boolean) => void;
  setInspectorTab: (tab: "page" | "panel") => void;
  setLiveAnnouncement: (msg: string) => void;

  applyJournalPreset: (journalId: string) => void;
  setCustomDimensions: (patch: { customWidthMm?: number; customMaxHeightMm?: number }) => void;
  setTagCaseOverride: (mode: "lower" | "upper" | null) => void;
  setTagFlow: (flow: "row_major" | "col_major") => void;
  setLayoutMode: (modeId: string) => void;
  setTypographyField: (patch: Partial<LayoutStudioState>) => void;

  setSpanOverride: (panelId: string, cols: number) => void;
  setLockedOverride: (panelId: string, locked: boolean) => void;
  updateRoi: (panelId: string, patch: Partial<LayoutROIConfig>, immediate?: boolean) => void;
  updatePanelOverride: (
    panelId: string,
    patch: Partial<PanelOverrideState>,
    immediate?: boolean,
  ) => void;
  updateTextItemOverride: (
    panelId: string,
    itemKey: string,
    patch: Partial<TextItemOverrideState>,
    immediate?: boolean,
  ) => void;
  resetTextItemOverride: (panelId: string, itemKey?: string) => void;
  resetPanelOverride: (panelId: string) => void;

  movePanelOnGrid: (srcPanelId: string, target: CanvasDropTarget) => void;
  unstackPanel: (panelId: string) => void;
  resizeColumnBlocks: (rowIdx: number, leftBlockIdx: number, leftWeight: number, rightWeight: number) => void;
  resizeRowHeight: (rowIdx: number, nextHeightScale: number) => void;

  setComparingNaive: (comparing: boolean) => void;
  setShowGuides: (show: boolean) => void;
  setZoomPct: (pct: number) => void;
  setInspectorDrawerOpen: (open: boolean) => void;
  setExportModalOpen: (open: boolean) => void;

  getComposePayload: () => Record<string, unknown>;
  refreshCompose: () => Promise<void>;
  exportHandoffSvgFile: () => Promise<File | null>;
  downloadExport: (format: "pdf" | "svg" | "png" | "lockfile", dpi?: number) => Promise<void>;
}

let composeAbort: AbortController | null = null;
let composeTimer: number | null = null;
let lastComposeMs = 0;

function scheduleCompose(get: () => LayoutStudioState, immediate = false): void {
  if (composeTimer !== null) {
    window.clearTimeout(composeTimer);
    composeTimer = null;
  }
  const now = performance.now();
  const elapsed = now - lastComposeMs;
  if (immediate || elapsed >= 68) {
    lastComposeMs = now;
    void get().refreshCompose();
    return;
  }
  composeTimer = window.setTimeout(() => {
    composeTimer = null;
    lastComposeMs = performance.now();
    void get().refreshCompose();
  }, Math.max(12, 68 - elapsed));
}

function cloneRows(rows: BentoRowState[] | null | undefined): BentoRowState[] {
  if (!rows) return [];
  return rows.map((r) => ({
    height_scale: r.height_scale,
    blocks: r.blocks.map((b) => ({
      panel_ids: [...b.panel_ids],
      weight: b.weight,
    })),
  }));
}

function normalizeRowWeights(row: BentoRowState): void {
  const total = row.blocks.reduce((acc, b) => acc + Math.max(0.5, b.weight), 0);
  if (total <= 0) return;
  row.blocks.forEach((b) => {
    b.weight = Number(((Math.max(0.5, b.weight) / total) * 12.0).toFixed(3));
  });
}

function flattenRowIds(rows: BentoRowState[]): string[] {
  const out: string[] = [];
  for (const r of rows) {
    for (const b of r.blocks) {
      for (const pid of b.panel_ids) {
        if (!out.includes(pid)) out.push(pid);
      }
    }
  }
  return out;
}

function buildComposeBody(s: LayoutStudioState): Record<string, unknown> {
  return {
    panel_ids: s.selectedIds,
    journal_id: s.journalId,
    custom_width_mm: s.journalId === "custom_canvas" ? s.customWidthMm : null,
    custom_max_height_mm: s.journalId === "custom_canvas" ? s.customMaxHeightMm : null,
    tag_case_override: s.tagCaseOverride,
    tag_flow: s.tagFlow,
    layout_mode: s.layoutMode,
    font_family: s.fontFamily,
    tag_pt: s.tagPt,
    title_pt: s.titlePt,
    axis_title_pt: s.axisTitlePt,
    tick_pt: s.tickPt,
    annotation_pt: s.annotationPt,
    axis_stroke_pt: s.axisStrokePt,
    data_stroke_pt: s.dataStrokePt,
    grid_stroke_pt: s.gridStrokePt,
    gutter_mm: s.gutterMm,
    marker_pt: s.markerPt,
    show_panel_titles: s.showPanelTitles,
    hoist_shared_legends: s.hoistSharedLegends,
    show_guides: s.showGuides,
    include_naive: s.isComparingNaive,
    span_overrides: s.spanOverrides,
    locked_overrides: s.lockedOverrides,
    roi_overrides: s.roiOverrides,
    panel_overrides: s.panelOverrides,
    bento_rows: s.bentoRows,
  };
}

export const useLayoutStudioStore = create<LayoutStudioState>((set, get) => ({
  layoutPageMode: "landing",
  initialized: false,
  busy: false,
  handoffBusy: false,

  panels: [],
  packs: [],
  journals: [],
  journalFamilies: [],
  layoutModes: [],
  fontFamilies: ["Arial", "Helvetica", "Helvetica Neue", "Calibri", "Times New Roman"],

  selectedIds: [],
  focusedPanelId: "P01",
  focusedTextKey: null,
  inspectorTab: "page",
  liveAnnouncement: "",

  journalId: "nature_double",
  customWidthMm: 180,
  customMaxHeightMm: 240,
  tagCaseOverride: null,
  tagFlow: "row_major",
  layoutMode: "auto_bento",
  fontFamily: "Arial",
  tagPt: 8.0,
  titlePt: 6.8,
  axisTitlePt: 6.5,
  tickPt: 6.0,
  annotationPt: 5.6,
  axisStrokePt: 0.5,
  dataStrokePt: 0.65,
  gridStrokePt: 0.3,
  gutterMm: 3.2,
  markerPt: 1.35,
  showPanelTitles: true,
  hoistSharedLegends: false,

  spanOverrides: {},
  lockedOverrides: {},
  roiOverrides: {},
  panelOverrides: {},
  bentoRows: null,

  isComparingNaive: false,
  showGuides: true,
  zoomPct: 105,
  inspectorDrawerOpen: false,
  exportModalOpen: false,
  composed: null,

  initLayoutCatalog: async () => {
    if (get().initialized) return;
    const res = await fetch("/api/v2/layout/init");
    if (!res.ok) return;
    const data = await res.json();
    const panels: LayoutPanelItem[] = data.panels || [];
    const rois: Record<string, LayoutROIConfig> = {};
    const locks: Record<string, boolean> = {};
    for (const p of panels) {
      rois[p.panel_id] = { ...p.default_roi };
      locks[p.panel_id] = p.locked_special;
    }
    const defaults = panels.filter((p) => p.default_selected).map((p) => p.panel_id);
    set({
      initialized: true,
      panels,
      packs: data.packs || [],
      journals: data.journals || [],
      journalFamilies: data.journal_families || [],
      layoutModes: data.layout_modes || [],
      fontFamilies: data.font_families?.length ? data.font_families : get().fontFamilies,
      selectedIds: defaults.length > 0 ? defaults : panels.slice(0, 10).map((p) => p.panel_id),
      roiOverrides: rois,
      lockedOverrides: locks,
    });
  },

  goToLayoutLanding: () => {
    set({ layoutPageMode: "landing", isComparingNaive: false, exportModalOpen: false });
  },

  openSamplePack: async (packId: string) => {
    await get().initLayoutCatalog();
    const pack = get().packs.find((p) => p.pack_id === packId);
    if (!pack) return;
    const j = get().journals.find((x) => x.id === pack.journal_id);
    set({
      selectedIds: [...pack.panel_ids],
      focusedPanelId: pack.panel_ids[0] || "P01",
      inspectorTab: "page",
      journalId: pack.journal_id,
      layoutMode: pack.layout_mode,
      fontFamily: j?.default_font || "Arial",
      tagPt: j?.tag_pt ?? 8.0,
      titlePt: j?.title_pt ?? 6.8,
      axisTitlePt: j?.axis_title_pt ?? 6.5,
      tickPt: j?.tick_pt ?? 6.0,
      annotationPt: j?.annotation_pt ?? 5.6,
      axisStrokePt: j?.axis_stroke_pt ?? 0.5,
      dataStrokePt: j?.axis_stroke_pt ? j.data_stroke_pt : 0.65,
      layoutPageMode: "editor",
      spanOverrides: {},
      bentoRows: null,
    });
    await get().refreshCompose();
  },

  openSandbox: async (count = 10) => {
    await get().initLayoutCatalog();
    const ids = get()
      .panels.slice(0, Math.min(count, get().panels.length))
      .map((p) => p.panel_id);
    set({
      selectedIds: ids,
      focusedPanelId: ids[0] || "P01",
      inspectorTab: "page",
      bentoRows: null,
      layoutPageMode: "editor",
    });
    await get().refreshCompose();
  },

  uploadLayoutFiles: async (files: FileList | File[]) => {
    const arr = Array.from(files);
    if (arr.length === 0) return;
    await get().initLayoutCatalog();
    set({ busy: true });
    try {
      const fd = new FormData();
      arr.forEach((f) => fd.append("files", f));
      const res = await fetch("/api/v2/layout/upload", { method: "POST", body: fd });
      if (!res.ok) return;
      const data = await res.json();
      const uploaded: LayoutPanelItem[] = data.uploaded || [];
      if (uploaded.length === 0) return;
      const nextRois = { ...get().roiOverrides };
      const nextLocks = { ...get().lockedOverrides };
      for (const u of uploaded) {
        nextRois[u.panel_id] = { ...u.default_roi };
        nextLocks[u.panel_id] = u.locked_special;
      }
      const wasLanding = get().layoutPageMode === "landing";
      const uploadedIds = uploaded.map((u) => u.panel_id);
      const nextSel = wasLanding ? uploadedIds : [...get().selectedIds, ...uploadedIds];

      let nextBento: BentoRowState[] | null = get().bentoRows;
      if (wasLanding) {
        nextBento = null;
      } else if (nextBento !== null) {
        nextBento = cloneRows(nextBento);
        nextBento.push({
          blocks: uploadedIds.map((id) => ({ panel_ids: [id], weight: 4.0 })),
          height_scale: 1.0,
        });
      }

      set({
        panels: [...get().panels, ...uploaded],
        roiOverrides: nextRois,
        lockedOverrides: nextLocks,
        selectedIds: nextSel,
        bentoRows: nextBento,
        focusedPanelId: uploaded[0].panel_id,
        inspectorTab: "panel",
        layoutPageMode: "editor",
      });
      await get().refreshCompose();
    } finally {
      set({ busy: false });
    }
  },

  togglePanel: (panelId: string) => {
    const prev = get().selectedIds;
    const removing = prev.includes(panelId);
    if (removing && prev.length <= 1) return;
    const next = removing ? prev.filter((id) => id !== panelId) : [...prev, panelId];

    let nextBento = get().bentoRows;
    if (nextBento !== null) {
      nextBento = cloneRows(nextBento);
      if (removing) {
        for (const r of nextBento) {
          for (const b of r.blocks) {
            b.panel_ids = b.panel_ids.filter((id) => id !== panelId);
          }
          r.blocks = r.blocks.filter((b) => b.panel_ids.length > 0);
          normalizeRowWeights(r);
        }
        nextBento = nextBento.filter((r) => r.blocks.length > 0);
      } else {
        if (nextBento.length > 0 && nextBento[nextBento.length - 1].blocks.length < 3) {
          nextBento[nextBento.length - 1].blocks.push({ panel_ids: [panelId], weight: 4.0 });
          normalizeRowWeights(nextBento[nextBento.length - 1]);
        } else {
          nextBento.push({ blocks: [{ panel_ids: [panelId], weight: 12.0 }], height_scale: 1.0 });
        }
      }
    }

    set({ selectedIds: next, bentoRows: nextBento, focusedPanelId: panelId });
    scheduleCompose(get);
  },

  movePanelOrder: (panelId: string, dir: -1 | 1) => {
    const prev = [...get().selectedIds];
    const idx = prev.indexOf(panelId);
    const target = idx + dir;
    if (idx < 0 || target < 0 || target >= prev.length) return;
    const neighborId = prev[target];
    [prev[idx], prev[target]] = [prev[target], prev[idx]];

    let nextBento = get().bentoRows;
    if (nextBento !== null) {
      nextBento = cloneRows(nextBento);
      for (const r of nextBento) {
        for (const b of r.blocks) {
          b.panel_ids = b.panel_ids.map((id) =>
            id === panelId ? neighborId : id === neighborId ? panelId : id,
          );
        }
      }
    }

    set({ selectedIds: prev, bentoRows: nextBento });
    scheduleCompose(get);
  },

  selectQuickCount: (count: number) => {
    const ids = get()
      .panels.slice(0, Math.min(count, get().panels.length))
      .map((p) => p.panel_id);
    set({ selectedIds: ids, bentoRows: null, focusedPanelId: ids[0] || "P01" });
    scheduleCompose(get);
  },

  setFocusedPanelId: (panelId: string, switchToPanelTab = false) => {
    const changed = panelId !== get().focusedPanelId;
    set({
      focusedPanelId: panelId,
      focusedTextKey: changed ? null : get().focusedTextKey,
      inspectorTab: switchToPanelTab ? "panel" : get().inspectorTab,
    });
  },

  setFocusedText: (panelId: string, itemKey: string | null, switchToPanelTab = true) => {
    set({
      focusedPanelId: panelId,
      focusedTextKey: itemKey,
      inspectorTab: switchToPanelTab ? "panel" : get().inspectorTab,
    });
  },

  setInspectorTab: (tab: "page" | "panel") => {
    set({ inspectorTab: tab });
  },

  setLiveAnnouncement: (msg: string) => {
    set({ liveAnnouncement: msg });
  },

  applyJournalPreset: (journalId: string) => {
    const j = get().journals.find((x) => x.id === journalId);
    // Changing to a narrow single-column spec resets manual multi-col bentoRows so width caps apply cleanly
    const prevJ = get().journals.find((x) => x.id === get().journalId);
    const crossedTier = prevJ && j && Math.abs(prevJ.width_mm - j.width_mm) > 30;
    set({
      journalId,
      bentoRows: crossedTier ? null : get().bentoRows,
      fontFamily: j?.default_font || get().fontFamily,
      tagPt: j?.tag_pt ?? get().tagPt,
      titlePt: j?.title_pt ?? get().titlePt,
      axisTitlePt: j?.axis_title_pt ?? get().axisTitlePt,
      tickPt: j?.tick_pt ?? get().tickPt,
      annotationPt: j?.annotation_pt ?? get().annotationPt,
      axisStrokePt: j?.axis_stroke_pt ?? get().axisStrokePt,
      dataStrokePt: j?.data_stroke_pt ?? get().dataStrokePt,
      gridStrokePt: j?.grid_stroke_pt ?? get().gridStrokePt,
    });
    scheduleCompose(get);
  },

  setCustomDimensions: (patch) => {
    set({
      customWidthMm: patch.customWidthMm ?? get().customWidthMm,
      customMaxHeightMm: patch.customMaxHeightMm ?? get().customMaxHeightMm,
    });
    scheduleCompose(get);
  },

  setTagCaseOverride: (mode) => {
    set({ tagCaseOverride: mode });
    scheduleCompose(get);
  },

  setTagFlow: (flow) => {
    set({ tagFlow: flow });
    scheduleCompose(get);
  },

  setLayoutMode: (modeId: string) => {
    set({ layoutMode: modeId, bentoRows: null });
    scheduleCompose(get);
  },

  setTypographyField: (patch: Partial<LayoutStudioState>) => {
    set(patch);
    scheduleCompose(get);
  },

  setSpanOverride: (panelId: string, cols: number) => {
    const next = { ...get().spanOverrides };
    if (cols <= 0) delete next[panelId];
    else next[panelId] = cols;

    let nextBento = get().bentoRows;
    if (nextBento !== null && cols > 0) {
      nextBento = cloneRows(nextBento);
      for (const r of nextBento) {
        const blk = r.blocks.find((b) => b.panel_ids.includes(panelId));
        if (blk && r.blocks.length > 1) {
          const others = r.blocks.filter((b) => b !== blk);
          const rem = Math.max(2.0, 12.0 - cols);
          const sumOthers = others.reduce((a, b) => a + b.weight, 0) || 1.0;
          blk.weight = cols;
          others.forEach((b) => {
            b.weight = Number(((b.weight / sumOthers) * rem).toFixed(3));
          });
        }
      }
    }

    set({ spanOverrides: next, bentoRows: nextBento });
    scheduleCompose(get);
  },

  setLockedOverride: (panelId: string, locked: boolean) => {
    set({ lockedOverrides: { ...get().lockedOverrides, [panelId]: locked } });
    scheduleCompose(get);
  },

  updateRoi: (panelId: string, patch: Partial<LayoutROIConfig>, immediate = false) => {
    const cur = get().roiOverrides[panelId] || {
      enabled: true,
      x_norm: 0.25,
      y_norm: 0.25,
      w_norm: 0.3,
      h_norm: 0.3,
      label: "ROI",
      color: "#F59E0B",
      dashed: true,
      scale_bar_um: null,
      fov_width_um: null,
      linked_source_id: null,
    };
    set({
      roiOverrides: {
        ...get().roiOverrides,
        [panelId]: { ...cur, ...patch },
      },
    });
    scheduleCompose(get, immediate);
  },

  updatePanelOverride: (
    panelId: string,
    patch: Partial<PanelOverrideState>,
    immediate = false,
  ) => {
    const cur = get().panelOverrides[panelId] || { ...DEFAULT_PANEL_OVERRIDE, text_overrides: {} };
    set({
      panelOverrides: {
        ...get().panelOverrides,
        [panelId]: { ...cur, ...patch },
      },
    });
    scheduleCompose(get, immediate);
  },

  updateTextItemOverride: (
    panelId: string,
    itemKey: string,
    patch: Partial<TextItemOverrideState>,
    immediate = false,
  ) => {
    const curPanel = get().panelOverrides[panelId] || {
      ...DEFAULT_PANEL_OVERRIDE,
      text_overrides: {},
    };
    const curItem = curPanel.text_overrides[itemKey] || { ...DEFAULT_TEXT_ITEM_OVERRIDE };
    set({
      panelOverrides: {
        ...get().panelOverrides,
        [panelId]: {
          ...curPanel,
          text_overrides: {
            ...curPanel.text_overrides,
            [itemKey]: { ...curItem, ...patch },
          },
        },
      },
    });
    scheduleCompose(get, immediate);
  },

  resetTextItemOverride: (panelId: string, itemKey?: string) => {
    const curPanel = get().panelOverrides[panelId];
    if (!curPanel) return;
    const nextMap = { ...curPanel.text_overrides };
    if (itemKey) {
      delete nextMap[itemKey];
    } else {
      Object.keys(nextMap).forEach((k) => delete nextMap[k]);
    }
    set({
      panelOverrides: {
        ...get().panelOverrides,
        [panelId]: { ...curPanel, text_overrides: nextMap },
      },
    });
    scheduleCompose(get, true);
  },

  resetPanelOverride: (panelId: string) => {
    const next = { ...get().panelOverrides };
    delete next[panelId];
    const nextSpan = { ...get().spanOverrides };
    delete nextSpan[panelId];
    set({
      panelOverrides: next,
      spanOverrides: nextSpan,
      focusedTextKey: get().focusedPanelId === panelId ? null : get().focusedTextKey,
    });
    scheduleCompose(get, true);
  },

  movePanelOnGrid: (srcPanelId: string, target: CanvasDropTarget) => {
    const baseRows = cloneRows(get().bentoRows ?? get().composed?.bento_rows);
    if (baseRows.length === 0) return;

    if (target.kind === "slot") {
      if (srcPanelId === target.dstPanelId) return;
      if (target.zone === "swap") {
        for (const r of baseRows) {
          for (const b of r.blocks) {
            b.panel_ids = b.panel_ids.map((id) =>
              id === srcPanelId
                ? target.dstPanelId
                : id === target.dstPanelId
                  ? srcPanelId
                  : id,
            );
          }
        }
        set({
          bentoRows: baseRows,
          selectedIds: flattenRowIds(baseRows),
          focusedPanelId: srcPanelId,
        });
        scheduleCompose(get, true);
        return;
      }
    }

    // Remove srcPanelId from its current location first
    for (const r of baseRows) {
      for (const b of r.blocks) {
        b.panel_ids = b.panel_ids.filter((id) => id !== srcPanelId);
      }
      r.blocks = r.blocks.filter((b) => b.panel_ids.length > 0);
      normalizeRowWeights(r);
    }
    const cleanedRows = baseRows.filter((r) => r.blocks.length > 0);

    if (target.kind === "new_row") {
      const idx = Math.max(0, Math.min(cleanedRows.length, target.insertRowIdx));
      cleanedRows.splice(idx, 0, {
        blocks: [{ panel_ids: [srcPanelId], weight: 12.0 }],
        height_scale: 1.0,
      });
    } else {
      for (const r of cleanedRows) {
        const bi = r.blocks.findIndex((b) => b.panel_ids.includes(target.dstPanelId));
        if (bi < 0) continue;
        const dstBlock = r.blocks[bi];
        if (target.zone === "left" || target.zone === "right") {
          const insIdx = target.zone === "left" ? bi : bi + 1;
          const newW = Math.max(2.5, dstBlock.weight * 0.6);
          r.blocks.splice(insIdx, 0, { panel_ids: [srcPanelId], weight: newW });
          normalizeRowWeights(r);
        } else {
          // Vertical sub-stack inside dstBlock (cap at 3 panels per vertical stack)
          if (dstBlock.panel_ids.length >= 3) {
            r.blocks.splice(bi + 1, 0, { panel_ids: [srcPanelId], weight: 3.5 });
            normalizeRowWeights(r);
          } else {
            const subIdx = dstBlock.panel_ids.indexOf(target.dstPanelId);
            const insPos = target.zone === "stack_top" ? subIdx : subIdx + 1;
            dstBlock.panel_ids.splice(insPos, 0, srcPanelId);
            if (dstBlock.panel_ids.length >= 2 && r.blocks.length > 1) {
              r.height_scale = Math.max(r.height_scale, 1.25);
            }
          }
        }
        break;
      }
    }

    set({
      bentoRows: cleanedRows,
      selectedIds: flattenRowIds(cleanedRows),
      focusedPanelId: srcPanelId,
    });
    scheduleCompose(get, true);
  },

  unstackPanel: (panelId: string) => {
    const rows = cloneRows(get().bentoRows ?? get().composed?.bento_rows);
    if (rows.length === 0) return;
    let changed = false;
    for (const r of rows) {
      const bi = r.blocks.findIndex((b) => b.panel_ids.includes(panelId));
      if (bi < 0) continue;
      const blk = r.blocks[bi];
      if (blk.panel_ids.length <= 1) break;
      blk.panel_ids = blk.panel_ids.filter((id) => id !== panelId);
      const halfW = Math.max(2.2, blk.weight * 0.5);
      blk.weight = halfW;
      r.blocks.splice(bi + 1, 0, { panel_ids: [panelId], weight: halfW });
      normalizeRowWeights(r);
      changed = true;
      break;
    }
    if (!changed) return;
    set({ bentoRows: rows, selectedIds: flattenRowIds(rows) });
    scheduleCompose(get, true);
  },

  resizeColumnBlocks: (rowIdx: number, leftBlockIdx: number, leftWeight: number, rightWeight: number) => {
    const rows = cloneRows(get().bentoRows ?? get().composed?.bento_rows);
    const row = rows[rowIdx];
    if (!row || leftBlockIdx < 0 || leftBlockIdx + 1 >= row.blocks.length) return;
    row.blocks[leftBlockIdx].weight = Number(leftWeight.toFixed(3));
    row.blocks[leftBlockIdx + 1].weight = Number(rightWeight.toFixed(3));
    set({ bentoRows: rows });
    scheduleCompose(get, true);
  },

  resizeRowHeight: (rowIdx: number, nextHeightScale: number) => {
    const rows = cloneRows(get().bentoRows ?? get().composed?.bento_rows);
    if (!rows[rowIdx]) return;
    rows[rowIdx].height_scale = Math.max(0.55, Math.min(2.2, Number(nextHeightScale.toFixed(3))));
    set({ bentoRows: rows });
    scheduleCompose(get, true);
  },

  setComparingNaive: (comparing: boolean) => {
    set({ isComparingNaive: comparing });
    if (comparing && !get().composed?.naive_svg) {
      scheduleCompose(get, true);
    }
  },

  setShowGuides: (show: boolean) => {
    set({ showGuides: show });
    scheduleCompose(get);
  },

  setZoomPct: (pct: number) => {
    set({ zoomPct: Math.max(50, Math.min(200, pct)) });
  },

  setInspectorDrawerOpen: (open: boolean) => {
    set({ inspectorDrawerOpen: open });
  },

  setExportModalOpen: (open: boolean) => {
    set({ exportModalOpen: open });
  },

  getComposePayload: () => buildComposeBody(get()),

  refreshCompose: async () => {
    if (get().selectedIds.length === 0) return;
    if (composeAbort) composeAbort.abort();
    const ctrl = new AbortController();
    composeAbort = ctrl;
    set({ busy: true });
    try {
      const res = await fetch("/api/v2/layout/compose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildComposeBody(get())),
        signal: ctrl.signal,
      });
      if (!res.ok) return;
      const data: LayoutComposeResult = await res.json();
      set({ composed: data });
    } catch {
      // Aborted superseded compose request
    } finally {
      if (composeAbort === ctrl) {
        set({ busy: false });
      }
    }
  },

  exportHandoffSvgFile: async () => {
    const s = get();
    if (!s.composed || s.selectedIds.length === 0) return null;
    set({ handoffBusy: true });
    try {
      const payload = buildComposeBody(s);
      const res = await fetch("/api/v2/layout/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          show_guides: false,
          format: "svg",
        }),
      });
      const svgBlob = res.ok
        ? await res.blob()
        : new Blob([s.composed.modular_svg], { type: "image/svg+xml" });
      return new File(
        [svgBlob],
        `danqing_layout_${s.journalId}_${s.selectedIds.length}panels.svg`,
        { type: "image/svg+xml" },
      );
    } finally {
      set({ handoffBusy: false });
    }
  },

  downloadExport: async (format: "pdf" | "svg" | "png" | "lockfile", dpi = 300) => {
    const s = get();
    const res = await fetch("/api/v2/layout/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...buildComposeBody(s), format, dpi }),
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const ext = format === "lockfile" ? "lock.json" : format;
    a.download = `danqing_layout_${s.journalId}_${s.selectedIds.length}panels.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
}));
