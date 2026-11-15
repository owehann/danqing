import { create } from "zustand";
import { useTableStudioStore } from "./table/tableStore";
import type {
  CrossPanelRule,
  CvdMode,
  ElementRole,
  FigureState,
  MultipageChoicePayload,
  PaletteItem,
  PresetSummary,
  SessionFigureSummary,
  StyleProfileItem,
  VibrancyMode,
} from "./types";

export type StudioMode = "figure" | "table";
export type PageMode = "landing" | "processing" | "editor";
export type ActiveDialog = "export" | "raster" | "multipage" | "shortcuts" | "error" | null;

interface ErrorModalPayload {
  code: string;
  detail?: string;
  filename?: string;
}

interface StudioStore {
  studioMode: StudioMode;
  pageMode: PageMode;
  palettes: PaletteItem[];
  styles: StyleProfileItem[];
  presets: PresetSummary[];
  openedFigureIds: string[];
  sessionFigures: SessionFigureSummary[];

  processingStage: string;
  processingProgress: number;
  processingFilename: string;
  slowWarning: boolean;

  figure: FigureState | null;
  targetPanels: string[];
  selectedIds: string[];
  hoveredEntityId: string | null;
  hoveredPanelLabel: string | null;
  hoveredPaletteId: string | null;
  hoveredStyleId: string | null;
  hoveredSwatch: { entityId: string; hex: string } | null;

  isComparingOriginal: boolean;
  splitCompareActive: boolean;
  cvdMode: CvdMode;
  palettesDrawerOpen: boolean;

  activeDialog: ActiveDialog;
  multipagePayload: MultipageChoicePayload | null;
  errorPayload: ErrorModalPayload | null;
  onboardingDismissed: boolean;

  initCatalog: () => Promise<void>;
  setStudioMode: (mode: StudioMode) => void;
  refreshSessionFigures: () => Promise<void>;
  uploadFile: (file: File, pageIndex?: number) => Promise<void>;
  uploadSvgText: (svgText: string) => Promise<void>;
  selectMultipagePage: (pageIndex: number) => Promise<void>;
  openPreset: (presetId: string) => Promise<void>;
  switchFigure: (figureId: string) => Promise<void>;
  goToLanding: () => void;

  mutateState: (payload: Record<string, unknown>) => Promise<void>;
  setTargetPanels: (panels: string[]) => void;
  toggleTargetPanel: (panelId: string, multi?: boolean) => void;
  applyPalette: (paletteId: string) => Promise<void>;
  resetToOriginal: () => Promise<void>;
  resetTargetPanels: () => Promise<void>;
  setElementRoles: (entityIds: string[], role: ElementRole) => Promise<void>;
  pickElementColor: (entityId: string, hexColor: string) => Promise<void>;
  toggleElementLock: (entityId: string, locked: boolean) => Promise<void>;
  renameElement: (entityId: string, label: string) => Promise<void>;
  splitSameName: (entityId: string) => Promise<void>;
  resetElement: (entityId: string) => Promise<void>;
  setRule: (rule: CrossPanelRule) => Promise<void>;
  setVibrancy: (vibrancy: VibrancyMode) => Promise<void>;
  setAestheticStyle: (styleId: string | null) => Promise<void>;
  invertScale: (scaleId: string) => Promise<void>;
  setKeepConsistent: (enabled: boolean) => Promise<void>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;

  selectEntity: (entityId: string | null, additive?: boolean, range?: boolean) => void;
  setHoveredEntity: (entityId: string | null, panelLabel?: string | null) => void;
  setHoveredPalette: (paletteId: string | null) => void;
  setHoveredStyle: (styleId: string | null) => void;
  setHoveredSwatch: (swatch: { entityId: string; hex: string } | null) => void;
  setComparingOriginal: (comparing: boolean) => void;
  toggleSplitCompare: () => void;
  setCvdMode: (mode: CvdMode) => void;
  setPalettesDrawerOpen: (open: boolean) => void;
  openDialog: (dialog: ActiveDialog) => void;
  closeDialog: () => void;
  dismissOnboarding: () => void;
}

const ONBOARDING_KEY = "danqing_onboarding_v2_dismissed";

function readOnboardingDismissed(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDING_KEY) === "1";
  } catch {
    return false;
  }
}

let activeEventSource: EventSource | null = null;

function closeActiveEventSource(): void {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }
}

export const useStudioStore = create<StudioStore>((set, get) => ({
  studioMode: "figure",
  pageMode: "landing",
  palettes: [],
  styles: [],
  presets: [],
  openedFigureIds: [],
  sessionFigures: [],

  processingStage: "reading_file",
  processingProgress: 10,
  processingFilename: "",
  slowWarning: false,

  figure: null,
  targetPanels: [],
  selectedIds: [],
  hoveredEntityId: null,
  hoveredPanelLabel: null,
  hoveredPaletteId: null,
  hoveredStyleId: null,
  hoveredSwatch: null,

  isComparingOriginal: false,
  splitCompareActive: false,
  cvdMode: "normal",
  palettesDrawerOpen: false,

  activeDialog: null,
  multipagePayload: null,
  errorPayload: null,
  onboardingDismissed: readOnboardingDismissed(),

  initCatalog: async () => {
    const res = await fetch("/api/v2/palettes");
    if (!res.ok) return;
    const data = await res.json();
    set({
      palettes: data.palettes || [],
      styles: data.styles || [],
      presets: data.presets || [],
    });
  },

  setStudioMode: (mode: StudioMode) => {
    set({ studioMode: mode });
  },

  refreshSessionFigures: async () => {
    const res = await fetch("/api/v2/figures");
    if (!res.ok) return;
    const data = await res.json();
    const opened = new Set(get().openedFigureIds);
    const all: SessionFigureSummary[] = data.figures || [];
    set({
      sessionFigures: all.filter((f) => !f.is_preset || opened.has(f.figure_id)),
    });
  },

  uploadFile: async (file: File, pageIndex?: number) => {
    const ext = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : "";
    if ([".csv", ".tsv", ".txt", ".xlsx", ".xls"].includes(ext)) {
      set({ studioMode: "table" });
      await useTableStudioStore.getState().uploadTableFile(file);
      return;
    }
    set({ studioMode: "figure" });
    if ([".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"].includes(ext)) {
      set({ activeDialog: "raster" });
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    if (pageIndex !== undefined) {
      fd.append("page_index", String(pageIndex));
    }

    const res = await fetch("/api/v2/figures", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (data.code === "RASTER_NOT_SUPPORTED") {
        set({ activeDialog: "raster" });
        return;
      }
      set({
        activeDialog: "error",
        errorPayload: { code: data.code || "PARSE_FAILED", detail: data.detail, filename: file.name },
      });
      return;
    }
    if (data.code === "MULTI_PAGE_SELECT_REQUIRED") {
      set({
        activeDialog: "multipage",
        multipagePayload: {
          pending_upload_id: data.pending_upload_id,
          filename: data.filename,
          page_count: data.page_count,
          pages: data.pages,
        },
      });
      return;
    }

    await startFigureLoading(data.figure_id, file.name, Boolean(data.slow_warning), set, get);
  },

  uploadSvgText: async (svgText: string) => {
    const fd = new FormData();
    fd.append("svg_text", svgText);
    const res = await fetch("/api/v2/figures", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      set({
        activeDialog: "error",
        errorPayload: { code: data.code || "PARSE_FAILED", detail: data.detail },
      });
      return;
    }
    await startFigureLoading(data.figure_id, "pasted_figure.svg", false, set, get);
  },

  selectMultipagePage: async (pageIndex: number) => {
    const mp = get().multipagePayload;
    if (!mp) return;
    set({ activeDialog: null, multipagePayload: null });
    const fd = new FormData();
    fd.append("pending_upload_id", mp.pending_upload_id);
    fd.append("page_index", String(pageIndex));
    const res = await fetch("/api/v2/figures", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      set({
        activeDialog: "error",
        errorPayload: { code: data.code || "PARSE_FAILED", detail: data.detail, filename: mp.filename },
      });
      return;
    }
    await startFigureLoading(data.figure_id, mp.filename, Boolean(data.slow_warning), set, get);
  },

  openPreset: async (presetId: string) => {
    const fd = new FormData();
    fd.append("preset_id", presetId);
    const presetMeta = get().presets.find((p) => p.preset_id === presetId);
    const res = await fetch("/api/v2/figures", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    const nextOpened = Array.from(new Set([...get().openedFigureIds, presetId]));
    set({ openedFigureIds: nextOpened });
    if (data.status === "ready") {
      await get().switchFigure(presetId);
    } else {
      await startFigureLoading(presetId, presetMeta?.filename || presetId, Boolean(data.slow_warning), set, get);
    }
  },

  switchFigure: async (figureId: string) => {
    closeActiveEventSource();
    const res = await fetch(`/api/v2/figures/${figureId}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status === "error") {
      set({
        pageMode: get().figure ? "editor" : "landing",
        activeDialog: "error",
        errorPayload: { code: data.code || "PARSE_FAILED", detail: data.detail },
      });
      return;
    }
    const nextOpened = Array.from(new Set([...get().openedFigureIds, figureId]));
    set({
      figure: data as FigureState,
      pageMode: "editor",
      targetPanels: [],
      selectedIds: [],
      hoveredEntityId: null,
      hoveredPaletteId: null,
      hoveredStyleId: null,
      hoveredSwatch: null,
      openedFigureIds: nextOpened,
      slowWarning: Boolean(data.slow_warning),
    });
    await get().refreshSessionFigures();
  },

  goToLanding: () => {
    closeActiveEventSource();
    set({
      studioMode: "figure",
      pageMode: "landing",
      targetPanels: [],
      selectedIds: [],
      hoveredEntityId: null,
      hoveredPaletteId: null,
      hoveredStyleId: null,
      hoveredSwatch: null,
    });
  },

  mutateState: async (payload: Record<string, unknown>) => {
    const fig = get().figure;
    if (!fig) return;
    const res = await fetch(`/api/v2/figures/${fig.figure_id}/state`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return;
    const diff = await res.json();

    set((state) => {
      if (!state.figure || state.figure.figure_id !== fig.figure_id) return state;
      const updatedElements = diff.structure_changed
        ? diff.elements
        : state.figure.elements.map((el) => {
            const meta = diff.entity_meta?.[el.entity_id];
            return {
              ...el,
              current_hex: diff.entity_colors?.[el.entity_id] ?? el.current_hex,
              label: meta?.label ?? el.label,
              role: meta?.role ?? el.role,
              locked: meta?.locked ?? el.locked,
              unlinked: meta?.unlinked ?? el.unlinked,
              panels: meta?.panels ?? el.panels,
              inspector_swatches: diff.inspector_swatches?.[el.entity_id] ?? el.inspector_swatches,
            };
          });

      const updatedLut = diff.structure_changed
        ? diff.categorical_lut
        : state.figure.categorical_lut.map((entry) => ({
            ...entry,
            current_hex: diff.group_colors?.[entry.group_id] ?? entry.current_hex,
          }));

      return {
        hoveredPaletteId: null,
        hoveredStyleId: null,
        hoveredSwatch: null,
        figure: {
          ...state.figure,
          revision: diff.revision,
          render_url: diff.render_url,
          palette_id: diff.palette_id,
          active_palette_fallback: diff.active_palette_fallback,
          is_original_mode: diff.is_original_mode,
          panel_palettes: diff.panel_palettes ?? state.figure.panel_palettes ?? {},
          rule: diff.rule,
          vibrancy: diff.vibrancy,
          aesthetic_style: diff.aesthetic_style ?? null,
          keep_consistent: diff.keep_consistent,
          can_undo: diff.can_undo,
          can_redo: diff.can_redo,
          elements: updatedElements,
          categorical_lut: updatedLut,
          continuous_scales: diff.continuous_scales ?? state.figure.continuous_scales,
          diagnostics: diff.diagnostics ?? state.figure.diagnostics,
        },
      };
    });
  },

  setTargetPanels: (panels: string[]) => {
    set({ targetPanels: panels, hoveredPaletteId: null });
  },
  toggleTargetPanel: (panelId: string, multi = false) => {
    const fig = get().figure;
    const allCount = fig?.panels.length ?? 0;
    const prev = get().targetPanels;
    if (!multi) {
      if (prev.length === 1 && prev[0] === panelId) {
        set({ targetPanels: [], hoveredPaletteId: null });
      } else {
        set({ targetPanels: [panelId], hoveredPaletteId: null });
      }
      return;
    }
    const next = prev.includes(panelId)
      ? prev.filter((id) => id !== panelId)
      : [...prev, panelId];
    if (allCount > 0 && next.length >= allCount) {
      set({ targetPanels: [], hoveredPaletteId: null });
    } else {
      set({ targetPanels: next, hoveredPaletteId: null });
    }
  },
  applyPalette: async (paletteId: string) => {
    const tp = get().targetPanels;
    await get().mutateState({
      action: "set_palette",
      palette_id: paletteId,
      ...(tp.length > 0 ? { target_panels: tp } : {}),
    });
  },
  resetToOriginal: async () => {
    await get().mutateState({ action: "reset_to_original" });
  },
  resetTargetPanels: async () => {
    const tp = get().targetPanels;
    if (tp.length === 0) {
      await get().mutateState({ action: "reset_to_original" });
      return;
    }
    await get().mutateState({ action: "reset_panel", target_panels: tp });
  },
  setElementRoles: async (entityIds: string[], role: ElementRole) => {
    await get().mutateState({ action: "set_roles", entity_ids: entityIds, role });
  },
  pickElementColor: async (entityId: string, hexColor: string) => {
    await get().mutateState({ action: "pick_color", entity_id: entityId, hex_color: hexColor });
  },
  toggleElementLock: async (entityId: string, locked: boolean) => {
    await get().mutateState({ action: "set_lock", entity_id: entityId, locked });
  },
  renameElement: async (entityId: string, label: string) => {
    await get().mutateState({ action: "rename_element", entity_id: entityId, label });
  },
  splitSameName: async (entityId: string) => {
    await get().mutateState({ action: "split_same_name", entity_id: entityId });
  },
  resetElement: async (entityId: string) => {
    await get().mutateState({ action: "reset_element", entity_id: entityId });
  },
  setRule: async (rule: CrossPanelRule) => {
    await get().mutateState({ action: "set_rule", rule });
  },
  setVibrancy: async (vibrancy: VibrancyMode) => {
    await get().mutateState({ action: "set_vibrancy", vibrancy });
  },
  setAestheticStyle: async (styleId: string | null) => {
    await get().mutateState({ action: "set_aesthetic_style", aesthetic_style: styleId });
  },
  invertScale: async (scaleId: string) => {
    await get().mutateState({ action: "invert_scale", scale_id: scaleId });
  },
  setKeepConsistent: async (enabled: boolean) => {
    await get().mutateState({ action: "set_keep_consistent", keep_consistent: enabled });
  },
  undo: async () => {
    if (!get().figure?.can_undo) return;
    await get().mutateState({ action: "undo" });
  },
  redo: async () => {
    if (!get().figure?.can_redo) return;
    await get().mutateState({ action: "redo" });
  },

  selectEntity: (entityId: string | null, additive = false, range = false) => {
    if (!entityId) {
      set({ selectedIds: [] });
      return;
    }
    const fig = get().figure;
    const prev = get().selectedIds;
    if (range && fig && prev.length > 0) {
      const order = fig.elements.map((e) => e.entity_id);
      const a = order.indexOf(prev[prev.length - 1]);
      const b = order.indexOf(entityId);
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        const slice = order.slice(lo, hi + 1);
        set({ selectedIds: Array.from(new Set([...prev, ...slice])) });
        return;
      }
    }
    if (additive) {
      if (prev.includes(entityId)) {
        set({ selectedIds: prev.filter((id) => id !== entityId) });
      } else {
        set({ selectedIds: [...prev, entityId] });
      }
      return;
    }
    set({ selectedIds: [entityId] });
  },

  setHoveredEntity: (entityId: string | null, panelLabel: string | null = null) => {
    set({ hoveredEntityId: entityId, hoveredPanelLabel: panelLabel });
  },
  setHoveredPalette: (paletteId: string | null) => {
    set({ hoveredPaletteId: paletteId });
  },
  setHoveredStyle: (styleId: string | null) => {
    set({ hoveredStyleId: styleId });
  },
  setHoveredSwatch: (swatch) => {
    set({ hoveredSwatch: swatch });
  },
  setComparingOriginal: (comparing: boolean) => {
    set({ isComparingOriginal: comparing });
  },
  toggleSplitCompare: () => {
    set((s) => ({ splitCompareActive: !s.splitCompareActive }));
  },
  setCvdMode: (mode: CvdMode) => {
    set({ cvdMode: mode });
  },
  setPalettesDrawerOpen: (open: boolean) => {
    set({ palettesDrawerOpen: open });
  },
  openDialog: (dialog: ActiveDialog) => {
    set({ activeDialog: dialog });
  },
  closeDialog: () => {
    set({ activeDialog: null });
  },
  dismissOnboarding: () => {
    try {
      window.localStorage.setItem(ONBOARDING_KEY, "1");
    } catch {
      // ignore storage errors
    }
    set({ onboardingDismissed: true });
  },
}));

async function startFigureLoading(
  figureId: string,
  filename: string,
  slowWarning: boolean,
  set: (partial: Partial<StudioStore>) => void,
  get: () => StudioStore,
): Promise<void> {
  closeActiveEventSource();
  set({
    pageMode: "processing",
    processingStage: "reading_file",
    processingProgress: 10,
    processingFilename: filename,
    slowWarning,
  });

  await new Promise<void>((resolve) => {
    const es = new EventSource(`/api/v2/figures/${figureId}/events`);
    activeEventSource = es;

    es.onmessage = async (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.stage === "ready" || msg.stage === "done") {
          closeActiveEventSource();
          await get().switchFigure(figureId);
          resolve();
          return;
        }
        if (msg.stage === "error") {
          closeActiveEventSource();
          set({
            pageMode: get().figure ? "editor" : "landing",
            activeDialog: "error",
            errorPayload: { code: msg.code || "PARSE_FAILED", detail: msg.detail, filename },
          });
          resolve();
          return;
        }
        set({
          processingStage: msg.stage || "detecting_colors",
          processingProgress: typeof msg.progress === "number" ? msg.progress : 45,
        });
      } catch {
        // ignore malformed heartbeat
      }
    };

    es.onerror = async () => {
      closeActiveEventSource();
      await get().switchFigure(figureId);
      resolve();
    };
  });
}
