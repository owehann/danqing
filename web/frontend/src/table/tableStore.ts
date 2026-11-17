import { create } from "zustand";
import { formatLiveStatusMessage } from "./clipboardCopy";
import {
  buildStandaloneStyledHtml,
  makeSafeFilenameStem,
  serializeToBackendExportPayload,
  serializeToBackendZipPayload,
} from "./exporters";
import type {
  ColumnRole,
  ColumnStat,
  MergePattern,
  ParseWarning,
  PivotSpec,
  RawSnapshot,
  RenderModel,
  SampleCatalogItem,
  SheetMeta,
  SmartComputeSuggestion,
  StashedComputedState,
  StructureLayer,
  StyleLayer,
  TableDoc,
  TidySuggestions,
} from "./model";
import {
  type SuggestionCategory,
  applySuggestionsToDoc,
  createInitialTableDoc,
  inferRecommendedStyle,
  normalizeLegacyTableDoc,
} from "./pipeline";

const SESSION_STORAGE_KEY = "danqing_table_studio_v2_session";
const MAX_HISTORY_STEPS = 50;

interface HistoryEntry {
  raw?: RawSnapshot;
  sourceRaw?: RawSnapshot | null;
  stashedComputed?: StashedComputedState | null;
  structure: StructureLayer;
  style: StyleLayer;
}

interface PersistedDocMeta {
  id: string;
  sampleId?: string;
  filename: string;
  sha256: string;
  kind: RawSnapshot["source"]["kind"];
  computedRaw?: RawSnapshot;
  structure: StructureLayer;
  style: StyleLayer;
}

interface PersistedSessionState {
  order: string[];
  activeId: string | null;
  docs: Record<string, PersistedDocMeta>;
}

// Keep uploaded File blobs in memory so switching sheets in an .xlsx re-parses seamlessly
const uploadedFilesBySha = new Map<string, File>();

export function normalizeRawSnapshotPayload(apiData: Record<string, unknown>): RawSnapshot {
  const src = (apiData.source ?? {}) as Record<string, unknown>;
  const sug = (apiData.suggestions ?? {}) as Record<string, unknown>;
  const rawRoles = (sug.roles ?? {}) as Record<string, ColumnRole>;
  const numericRoles: Record<number, ColumnRole> = {};
  for (const [k, v] of Object.entries(rawRoles)) {
    numericRoles[Number(k)] = v;
  }

  const rawPivot = sug.pivot as Record<string, unknown> | null | undefined;
  const pivot: PivotSpec | null = rawPivot
    ? {
        rowKey: Number(rawPivot.row_key ?? rawPivot.rowKey ?? 0),
        colKey: Number(rawPivot.col_key ?? rawPivot.colKey ?? 0),
        valueCols: ((rawPivot.value_cols ?? rawPivot.valueCols ?? []) as number[]).map(Number),
        retainRowCols: ((rawPivot.retain_row_cols ?? rawPivot.retainRowCols ?? []) as number[]).map(
          Number,
        ),
        colCounts: (rawPivot.col_counts ?? rawPivot.colCounts ?? {}) as Record<string, string>,
      }
    : null;

  const rawSmart = (sug.smart_compute ?? sug.smartCompute ?? null) as Record<
    string,
    unknown
  > | null;
  let smartCompute: SmartComputeSuggestion | null = null;
  if (rawSmart && rawSmart.kind === "subject_table1") {
    smartCompute = {
      kind: "subject_table1",
      nSubjects: Number(rawSmart.n_subjects ?? rawSmart.nSubjects ?? 0),
      defaultGroupCol: Number(rawSmart.default_group_col ?? rawSmart.defaultGroupCol ?? 0),
      candidateGroupCols: (
        (rawSmart.candidate_group_cols ?? rawSmart.candidateGroupCols ?? []) as Array<
          Record<string, unknown>
        >
      ).map((cg) => ({
        col: Number(cg.col ?? 0),
        name: String(cg.name ?? ""),
        groups: (cg.groups ?? {}) as Record<string, number>,
      })),
      excludedIdCols: ((rawSmart.excluded_id_cols ?? rawSmart.excludedIdCols ?? []) as number[]).map(
        Number,
      ),
      nContinuous: Number(rawSmart.n_continuous ?? rawSmart.nContinuous ?? 0),
      nCategorical: Number(rawSmart.n_categorical ?? rawSmart.nCategorical ?? 0),
    };
  } else if (rawSmart && rawSmart.kind === "replicate_collapse") {
    smartCompute = {
      kind: "replicate_collapse",
      nFeatures: Number(rawSmart.n_features ?? rawSmart.nFeatures ?? 0),
      featureCol: Number(rawSmart.feature_col ?? rawSmart.featureCol ?? 0),
      groups: ((rawSmart.groups ?? []) as Array<Record<string, unknown>>).map((g) => ({
        name: String(g.name ?? ""),
        cols: ((g.cols ?? []) as number[]).map(Number),
        n: Number(g.n ?? 0),
      })),
      canPair: Boolean(rawSmart.can_pair ?? rawSmart.canPair ?? false),
      defaultEffect: ((rawSmart.default_effect ?? rawSmart.defaultEffect ?? "log2fc") as
        | "log2fc"
        | "fc"
        | "diff"),
    };
  }

  const rawSigBindings = (sug.sig_bindings ?? sug.sigBindings ?? []) as Array<
    Record<string, unknown>
  >;

  const suggestions: TidySuggestions = {
    headerRows: ((sug.header_rows ?? sug.headerRows ?? [0, 0]) as [number, number]),
    bodyRange: ((sug.body_range ?? sug.bodyRange ?? [1, 1]) as [number, number]),
    titleCandidate: (sug.title_candidate ?? sug.titleCandidate ?? null) as string | null,
    footnoteCandidates: ((sug.footnote_candidates ?? sug.footnoteCandidates ?? []) as string[]),
    spanners: ((sug.spanners ?? []) as Array<Record<string, unknown>>).map((sp) => ({
      label: String(sp.label ?? ""),
      sourceCols: ((sp.source_cols ?? sp.sourceCols ?? []) as number[]).map(Number),
    })),
    roles: numericRoles,
    merges: ((sug.merges ?? []) as Array<Record<string, unknown>>).map((mg) => ({
      sourceCols: ((mg.source_cols ?? mg.sourceCols ?? []) as number[]).map(Number),
      pattern: (mg.pattern as MergePattern) ?? "paren",
    })),
    partBy:
      sug.part_by !== undefined && sug.part_by !== null
        ? Number(sug.part_by)
        : sug.partBy !== undefined && sug.partBy !== null
          ? Number(sug.partBy)
          : null,
    sparklineRuns: ((sug.sparkline_runs ?? sug.sparklineRuns ?? []) as Array<Record<string, unknown>>).map(
      (r) => ({
        sourceCols: ((r.source_cols ?? r.sourceCols ?? []) as number[]).map(Number),
        label: String(r.label ?? ""),
      }),
    ),
    pivot,
    decimalComma: Boolean(sug.decimal_comma ?? sug.decimalComma ?? false),
    resolvedHeaders: ((sug.resolved_headers ?? sug.resolvedHeaders ?? []) as string[]),
    leafHeaders: ((sug.leaf_headers ?? sug.leafHeaders ?? undefined) as string[] | undefined),
    sigBindings: rawSigBindings.map((sb) => ({
      sourceCol: Number(sb.source_col ?? sb.sourceCol ?? 0),
      targetCols: ((sb.target_cols ?? sb.targetCols ?? []) as number[]).map(Number),
      label: sb.label ? String(sb.label) : undefined,
    })),
    smartCompute,
  };

  const columnStats: ColumnStat[] = (
    (apiData.column_stats ?? apiData.columnStats ?? []) as Array<Record<string, unknown>>
  ).map((st) => ({
    col: Number(st.col ?? 0),
    name: String(st.name ?? ""),
    numericRatio: Number(st.numeric_ratio ?? st.numericRatio ?? 0),
    minVal: st.min_val !== null && st.min_val !== undefined ? Number(st.min_val) : null,
    maxVal: st.max_val !== null && st.max_val !== undefined ? Number(st.max_val) : null,
    detectedUnit: String(st.detected_unit ?? st.detectedUnit ?? ""),
    seqRatio: Number(st.seq_ratio ?? st.seqRatio ?? 0),
    isAllInt: Boolean(st.is_all_int ?? st.isAllInt ?? false),
    role: (st.role as ColumnRole) ?? "normal",
  }));

  const sheetsMeta: SheetMeta[] = (
    (apiData.sheets_meta ?? apiData.sheetsMeta ?? []) as Array<Record<string, unknown>>
  ).map((sm) => ({
    name: String(sm.name ?? ""),
    empty: Boolean(sm.empty),
  }));

  return {
    snapshotId: String(apiData.snapshot_id ?? apiData.snapshotId ?? "tbl_unknown"),
    sampleId: apiData.sample_id ? String(apiData.sample_id) : undefined,
    source: {
      filename: String(src.filename ?? "table.csv"),
      sheet: String(src.sheet ?? "Sheet1"),
      sheets: ((src.sheets ?? ["Sheet1"]) as string[]),
      kind: ((src.kind ?? "csv") as RawSnapshot["source"]["kind"]),
      sha256: String(src.sha256 ?? ""),
    },
    sheetsMeta,
    columnStats,
    grid: ((apiData.grid ?? []) as string[][]),
    cellMerges: ((apiData.cell_merges ?? apiData.cellMerges ?? []) as Array<{
      r0: number;
      c0: number;
      r1: number;
      c1: number;
    }>),
    warnings: ((apiData.warnings ?? []) as ParseWarning[]),
    suggestions,
  };
}

function readPersistedSession(): PersistedSessionState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedSessionState;
  } catch {
    return null;
  }
}

function writePersistedSession(
  docs: Record<string, TableDoc>,
  pendingUploads: Record<string, PersistedDocMeta>,
  order: string[],
  activeId: string | null,
): void {
  if (typeof window === "undefined") return;
  try {
    const outDocs: Record<string, PersistedDocMeta> = { ...pendingUploads };
    for (const [id, doc] of Object.entries(docs)) {
      outDocs[id] = {
        id,
        sampleId: (doc.sourceRaw ?? doc.raw).sampleId,
        filename: (doc.sourceRaw ?? doc.raw).source.filename,
        sha256: (doc.sourceRaw ?? doc.raw).source.sha256,
        kind: (doc.sourceRaw ?? doc.raw).source.kind,
        ...(doc.sourceRaw ? { computedRaw: doc.raw } : {}),
        structure: doc.structure,
        style: doc.style,
      };
    }
    const payload: PersistedSessionState = { order, activeId, docs: outDocs };
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Ignore sessionStorage quota errors
  }
}

export type TableExportFormat = "xlsx" | "docx" | "html" | "zip";

interface TableStudioStoreState {
  samples: SampleCatalogItem[];
  docs: Record<string, TableDoc>;
  pendingReuploads: Record<string, PersistedDocMeta>;
  historyPast: Record<string, HistoryEntry[]>;
  historyFuture: Record<string, HistoryEntry[]>;
  order: string[];
  activeId: string;
  tablePageMode: "landing" | "editor";
  isComparingRaw: boolean;
  activeModal: "paste" | "export" | null;
  styleDrawerOpen: boolean;
  busy: boolean;
  errorKey: string | null;
  liveAnnouncement: string;

  initTableCatalog: () => Promise<void>;
  openSample: (sampleId: string) => Promise<void>;
  switchDoc: (docId: string) => void;
  removeDoc: (docId: string) => void;
  goToTableLanding: () => void;

  commit: (mutator: (draft: { structure: StructureLayer; style: StyleLayer }) => void) => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;

  applySuggestions: (which: SuggestionCategory, alsoStyle?: boolean) => void;
  dismissSuggestion: (which: Exclude<SuggestionCategory, "all">) => void;
  goToStage: (targetStage: "raw" | "tidied" | "styled") => void;
  runSmartCompute: (
    mode: "subject_table1" | "replicate_collapse",
    options?: Record<string, unknown>,
    lang?: "en" | "zh",
  ) => Promise<boolean>;
  revertComputedToRaw: () => void;

  setComparingRaw: (comparing: boolean) => void;
  setActiveModal: (modal: "paste" | "export" | null) => void;
  setStyleDrawerOpen: (open: boolean) => void;
  clearError: () => void;
  announce: (msg: string) => void;

  uploadTableFile: (file: File, sheetName?: string) => Promise<boolean>;
  switchSheet: (sheetName: string) => Promise<void>;
  submitPaste: (payload: { text?: string; html?: string }) => Promise<boolean>;
  downloadExport: (
    format: TableExportFormat,
    model: RenderModel,
    filenameStem?: string,
  ) => Promise<boolean>;
}

export const useTableStudioStore = create<TableStudioStoreState>((set, get) => ({
  samples: [],
  docs: {},
  pendingReuploads: {},
  historyPast: {},
  historyFuture: {},
  order: [],
  activeId: "",
  tablePageMode: "landing",
  isComparingRaw: false,
  activeModal: null,
  styleDrawerOpen: false,
  busy: false,
  errorKey: null,
  liveAnnouncement: "",

  initTableCatalog: async () => {
    if (get().samples.length === 0) {
      try {
        const res = await fetch("/api/v2/tables/samples");
        if (res.ok) {
          const body = (await res.json()) as { samples?: SampleCatalogItem[] };
          set({ samples: body.samples ?? [] });
        }
      } catch {
        // Ignore offline startup error until user interacts
      }
    }

    if (get().order.length > 0) return;
    const persisted = readPersistedSession();
    if (!persisted || persisted.order.length === 0) return;

    const restoredDocs: Record<string, TableDoc> = {};
    const pendingReuploads: Record<string, PersistedDocMeta> = {};

    for (const id of persisted.order) {
      const meta = persisted.docs[id];
      if (!meta) continue;
      if (meta.sampleId) {
        try {
          const sRes = await fetch(`/api/v2/tables/samples/${encodeURIComponent(meta.sampleId)}`);
          if (sRes.ok) {
            const snap = normalizeRawSnapshotPayload(
              (await sRes.json()) as Record<string, unknown>,
            );
            restoredDocs[id] = normalizeLegacyTableDoc({
              raw: meta.computedRaw ?? snap,
              sourceRaw: meta.computedRaw ? snap : null,
              structure: meta.structure,
              style: meta.style,
            });
          }
        } catch {
          // Skip failed sample restore
        }
      } else {
        pendingReuploads[id] = meta;
      }
    }

    const validOrder = persisted.order.filter((id) => restoredDocs[id] || pendingReuploads[id]);
    const nextActive =
      persisted.activeId && restoredDocs[persisted.activeId]
        ? persisted.activeId
        : Object.keys(restoredDocs)[0] ?? "";

    set({
      docs: restoredDocs,
      pendingReuploads,
      order: validOrder,
      activeId: nextActive,
      tablePageMode: nextActive ? "editor" : "landing",
    });
  },

  openSample: async (sampleId) => {
    const state = get();
    const existingEntry = Object.entries(state.docs).find(
      ([, d]) => d.raw.sampleId === sampleId,
    );
    if (existingEntry) {
      set({
        activeId: existingEntry[0],
        tablePageMode: "editor",
        isComparingRaw: false,
        errorKey: null,
      });
      return;
    }

    set({ busy: true, errorKey: null });
    try {
      const res = await fetch(`/api/v2/tables/samples/${encodeURIComponent(sampleId)}`);
      const body = (await res.json()) as Record<string, unknown>;
      if (!res.ok) {
        set({
          busy: false,
          errorKey: String(body.error_key ?? "tableStudio.errors.network"),
        });
        return;
      }
      const raw = normalizeRawSnapshotPayload(body);
      const doc = createInitialTableDoc(raw);
      const docId = raw.snapshotId;

      set((prev) => {
        const nextDocs = { ...prev.docs, [docId]: doc };
        const nextOrder = prev.order.includes(docId) ? prev.order : [...prev.order, docId];
        writePersistedSession(nextDocs, prev.pendingReuploads, nextOrder, docId);
        return {
          docs: nextDocs,
          order: nextOrder,
          activeId: docId,
          tablePageMode: "editor",
          isComparingRaw: false,
          busy: false,
          errorKey: null,
        };
      });
    } catch {
      set({ busy: false, errorKey: "tableStudio.errors.network" });
    }
  },

  switchDoc: (docId) => {
    const { docs, pendingReuploads, order } = get();
    if (!docs[docId]) return;
    writePersistedSession(docs, pendingReuploads, order, docId);
    set({
      activeId: docId,
      tablePageMode: "editor",
      isComparingRaw: false,
      errorKey: null,
    });
  },

  removeDoc: (docId) => {
    set((state) => {
      const nextDocs = { ...state.docs };
      delete nextDocs[docId];
      const nextPending = { ...state.pendingReuploads };
      delete nextPending[docId];
      const nextPast = { ...state.historyPast };
      delete nextPast[docId];
      const nextFuture = { ...state.historyFuture };
      delete nextFuture[docId];

      const nextOrder = state.order.filter((id) => id !== docId);
      const nextActive =
        state.activeId === docId
          ? nextOrder.find((id) => Boolean(nextDocs[id])) ?? ""
          : state.activeId;

      writePersistedSession(nextDocs, nextPending, nextOrder, nextActive || null);
      return {
        docs: nextDocs,
        pendingReuploads: nextPending,
        historyPast: nextPast,
        historyFuture: nextFuture,
        order: nextOrder,
        activeId: nextActive,
        tablePageMode: nextActive ? "editor" : "landing",
      };
    });
  },

  goToTableLanding: () => {
    set({ tablePageMode: "landing", isComparingRaw: false, errorKey: null });
  },

  commit: (mutator) => {
    set((state) => {
      const id = state.activeId;
      const current = state.docs[id];
      if (!current) return state;

      const prevSnap: HistoryEntry = {
        raw: current.raw,
        sourceRaw: current.sourceRaw ?? null,
        stashedComputed: current.stashedComputed ?? null,
        structure: structuredClone(current.structure),
        style: structuredClone(current.style),
      };
      const draft: HistoryEntry = {
        structure: structuredClone(current.structure),
        style: structuredClone(current.style),
      };
      mutator(draft);

      const past = [...(state.historyPast[id] ?? []), prevSnap].slice(-MAX_HISTORY_STEPS);
      const updatedDoc: TableDoc = {
        raw: current.raw,
        sourceRaw: current.sourceRaw ?? null,
        stashedComputed:
          current.structure.stage === "raw" && draft.structure.stage !== "raw"
            ? null
            : (current.stashedComputed ?? null),
        structure: draft.structure,
        style: draft.style,
      };
      const nextDocs = { ...state.docs, [id]: updatedDoc };
      writePersistedSession(nextDocs, state.pendingReuploads, state.order, id);

      return {
        docs: nextDocs,
        historyPast: { ...state.historyPast, [id]: past },
        historyFuture: { ...state.historyFuture, [id]: [] },
      };
    });
  },

  undo: () => {
    set((state) => {
      const id = state.activeId;
      const current = state.docs[id];
      const past = state.historyPast[id] ?? [];
      if (!current || past.length === 0) return state;

      const previous = past[past.length - 1];
      const restPast = past.slice(0, -1);
      const curSnap: HistoryEntry = {
        raw: current.raw,
        sourceRaw: current.sourceRaw ?? null,
        stashedComputed: current.stashedComputed ?? null,
        structure: structuredClone(current.structure),
        style: structuredClone(current.style),
      };
      const nextFuture = [curSnap, ...(state.historyFuture[id] ?? [])].slice(0, MAX_HISTORY_STEPS);
      const updatedDoc: TableDoc = {
        raw: previous.raw ?? current.raw,
        sourceRaw: previous.sourceRaw !== undefined ? previous.sourceRaw : (current.sourceRaw ?? null),
        stashedComputed:
          previous.stashedComputed !== undefined
            ? previous.stashedComputed
            : (current.stashedComputed ?? null),
        structure: previous.structure,
        style: previous.style,
      };
      const nextDocs = { ...state.docs, [id]: updatedDoc };
      writePersistedSession(nextDocs, state.pendingReuploads, state.order, id);

      return {
        docs: nextDocs,
        historyPast: { ...state.historyPast, [id]: restPast },
        historyFuture: { ...state.historyFuture, [id]: nextFuture },
      };
    });
  },

  redo: () => {
    set((state) => {
      const id = state.activeId;
      const current = state.docs[id];
      const future = state.historyFuture[id] ?? [];
      if (!current || future.length === 0) return state;

      const [nextEntry, ...restFuture] = future;
      const curSnap: HistoryEntry = {
        raw: current.raw,
        sourceRaw: current.sourceRaw ?? null,
        stashedComputed: current.stashedComputed ?? null,
        structure: structuredClone(current.structure),
        style: structuredClone(current.style),
      };
      const nextPast = [...(state.historyPast[id] ?? []), curSnap].slice(-MAX_HISTORY_STEPS);
      const updatedDoc: TableDoc = {
        raw: nextEntry.raw ?? current.raw,
        sourceRaw:
          nextEntry.sourceRaw !== undefined ? nextEntry.sourceRaw : (current.sourceRaw ?? null),
        stashedComputed:
          nextEntry.stashedComputed !== undefined
            ? nextEntry.stashedComputed
            : (current.stashedComputed ?? null),
        structure: nextEntry.structure,
        style: nextEntry.style,
      };
      const nextDocs = { ...state.docs, [id]: updatedDoc };
      writePersistedSession(nextDocs, state.pendingReuploads, state.order, id);

      return {
        docs: nextDocs,
        historyPast: { ...state.historyPast, [id]: nextPast },
        historyFuture: { ...state.historyFuture, [id]: restFuture },
      };
    });
  },

  canUndo: () => {
    const s = get();
    return (s.historyPast[s.activeId]?.length ?? 0) > 0;
  },

  canRedo: () => {
    const s = get();
    return (s.historyFuture[s.activeId]?.length ?? 0) > 0;
  },

  applySuggestions: (which, alsoStyle = true) => {
    const state = get();
    const cur = state.docs[state.activeId];
    if (!cur) return;
    const applied = applySuggestionsToDoc(cur, which, alsoStyle);
    state.commit((draft) => {
      draft.structure = applied.structure;
      draft.style = applied.style;
    });
  },

  dismissSuggestion: (which) => {
    get().commit((draft) => {
      if (!draft.structure.dismissedSuggestions.includes(which)) {
        draft.structure.dismissedSuggestions.push(which);
      }
    });
  },

  goToStage: (targetStage) => {
    set((state) => {
      const id = state.activeId;
      const current = state.docs[id];
      if (!current) return state;

      const curEffStage: "raw" | "tidied" | "styled" =
        current.structure.stage === "raw"
          ? "raw"
          : current.style.preset === "raw"
            ? "tidied"
            : "styled";

      if (curEffStage === targetStage && !state.isComparingRaw) {
        return state;
      }

      const prevSnap: HistoryEntry = {
        raw: current.raw,
        sourceRaw: current.sourceRaw ?? null,
        stashedComputed: current.stashedComputed ?? null,
        structure: structuredClone(current.structure),
        style: structuredClone(current.style),
      };
      const past = [...(state.historyPast[id] ?? []), prevSnap].slice(-MAX_HISTORY_STEPS);

      const hasPriorStructureWork = (st: StructureLayer): boolean =>
        st.spanners.length > 0 ||
        st.merges.length > 0 ||
        st.derived.length > 0 ||
        st.pivot !== null ||
        st.partBy !== null ||
        st.footnotes.length > 0 ||
        Boolean(st.sig.sourceId) ||
        Object.keys(st.cellOverrides).length > 0 ||
        Boolean(st.title.trim()) ||
        st.columns.some((c) => c.hidden || (c.visual && c.visual !== "auto"));

      let updatedDoc: TableDoc;

      if (targetStage === "raw") {
        if (current.sourceRaw) {
          const restoredRaw = createInitialTableDoc(current.sourceRaw);
          updatedDoc = {
            ...restoredRaw,
            stashedComputed: {
              raw: current.raw,
              structure: structuredClone(current.structure),
              style: structuredClone(current.style),
            },
          };
        } else {
          const nextStruct = structuredClone(current.structure);
          const nextStyle = structuredClone(current.style);
          nextStruct.stage = "raw";
          nextStruct.dismissedSuggestions = [];
          if (nextStyle.preset !== "raw") {
            nextStyle.lastStyledPreset = nextStyle.preset;
          }
          updatedDoc = {
            raw: current.raw,
            sourceRaw: null,
            stashedComputed: current.stashedComputed ?? null,
            structure: nextStruct,
            style: nextStyle,
          };
        }
      } else if (targetStage === "tidied") {
        if (current.stashedComputed) {
          const stashed = current.stashedComputed;
          const nextStyle = structuredClone(stashed.style);
          if (nextStyle.preset !== "raw") {
            nextStyle.lastStyledPreset = nextStyle.preset;
          }
          nextStyle.preset = "raw";
          updatedDoc = {
            raw: stashed.raw,
            sourceRaw: current.raw,
            stashedComputed: null,
            structure: { ...structuredClone(stashed.structure), stage: "tidied" },
            style: nextStyle,
          };
        } else if (current.structure.stage === "raw") {
          if (hasPriorStructureWork(current.structure)) {
            const nextStyle = structuredClone(current.style);
            if (nextStyle.preset !== "raw") {
              nextStyle.lastStyledPreset = nextStyle.preset;
            }
            nextStyle.preset = "raw";
            updatedDoc = {
              raw: current.raw,
              sourceRaw: current.sourceRaw ?? null,
              stashedComputed: null,
              structure: { ...structuredClone(current.structure), stage: "tidied" },
              style: nextStyle,
            };
          } else {
            updatedDoc = applySuggestionsToDoc(current, "all", false);
          }
        } else {
          const nextStyle = structuredClone(current.style);
          if (nextStyle.preset !== "raw") {
            nextStyle.lastStyledPreset = nextStyle.preset;
          }
          nextStyle.preset = "raw";
          updatedDoc = {
            raw: current.raw,
            sourceRaw: current.sourceRaw ?? null,
            stashedComputed: null,
            structure: structuredClone(current.structure),
            style: nextStyle,
          };
        }
      } else {
        // targetStage === "styled"
        if (current.stashedComputed) {
          const stashed = current.stashedComputed;
          const nextStyle = structuredClone(stashed.style);
          nextStyle.preset =
            nextStyle.preset !== "raw"
              ? nextStyle.preset
              : (nextStyle.lastStyledPreset ?? "cns_three_line");
          updatedDoc = {
            raw: stashed.raw,
            sourceRaw: current.raw,
            stashedComputed: null,
            structure: { ...structuredClone(stashed.structure), stage: "tidied" },
            style: nextStyle,
          };
        } else if (current.structure.stage === "raw") {
          if (hasPriorStructureWork(current.structure)) {
            const nextStruct: StructureLayer = {
              ...structuredClone(current.structure),
              stage: "tidied",
            };
            const nextStyle = structuredClone(current.style);
            const rec = inferRecommendedStyle({
              raw: current.raw,
              structure: nextStruct,
              style: nextStyle,
            });
            nextStyle.preset =
              nextStyle.preset !== "raw"
                ? nextStyle.preset
                : (nextStyle.lastStyledPreset ?? rec.preset);
            if (rec.rowRhythm && nextStyle.rowRhythm === "none") {
              nextStyle.rowRhythm = rec.rowRhythm;
            }
            updatedDoc = {
              raw: current.raw,
              sourceRaw: current.sourceRaw ?? null,
              stashedComputed: null,
              structure: nextStruct,
              style: nextStyle,
            };
          } else {
            updatedDoc = applySuggestionsToDoc(current, "all", true);
          }
        } else {
          const nextStyle = structuredClone(current.style);
          const rec = inferRecommendedStyle(current);
          nextStyle.preset = nextStyle.lastStyledPreset ?? rec.preset;
          if (rec.rowRhythm && nextStyle.rowRhythm === "none") {
            nextStyle.rowRhythm = rec.rowRhythm;
          }
          updatedDoc = {
            raw: current.raw,
            sourceRaw: current.sourceRaw ?? null,
            stashedComputed: null,
            structure: structuredClone(current.structure),
            style: nextStyle,
          };
        }
      }

      const nextDocs = { ...state.docs, [id]: updatedDoc };
      writePersistedSession(nextDocs, state.pendingReuploads, state.order, id);
      return {
        docs: nextDocs,
        historyPast: { ...state.historyPast, [id]: past },
        historyFuture: { ...state.historyFuture, [id]: [] },
        isComparingRaw: false,
      };
    });
  },

  runSmartCompute: async (mode, options = {}, lang = "zh") => {
    const state = get();
    const id = state.activeId;
    const cur = state.docs[id];
    if (!cur) return false;

    const baseRaw = cur.sourceRaw ?? cur.raw;
    set({ busy: true, errorKey: null });
    try {
      const res = await fetch("/api/v2/tables/compute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grid: baseRaw.grid,
          header_rows: baseRaw.suggestions.headerRows,
          body_range: baseRaw.suggestions.bodyRange,
          decimal_comma: baseRaw.suggestions.decimalComma,
          source: baseRaw.source,
          mode,
          options,
          lang,
        }),
      });
      const body = (await res.json()) as Record<string, unknown>;
      if (!res.ok) {
        set({
          busy: false,
          errorKey: String(body.error_key ?? "tableStudio.errors.decodeFailed"),
        });
        return false;
      }

      const compRaw = normalizeRawSnapshotPayload(
        (body.snapshot ?? {}) as Record<string, unknown>,
      );
      if (baseRaw.sampleId) {
        compRaw.sampleId = baseRaw.sampleId;
      }
      const compStruct = body.structure as StructureLayer;
      const compStyle = body.style as StyleLayer;

      // Normalize stringified rowIndents keys from JSON into numeric keys
      const normalizedIndents: Record<number, 0 | 1> = {};
      for (const [k, v] of Object.entries(compStruct.rowIndents ?? {})) {
        normalizedIndents[Number(k)] = v ? 1 : 0;
      }
      compStruct.rowIndents = normalizedIndents;

      set((prev) => {
        const current = prev.docs[id];
        if (!current) return { busy: false };
        const prevSnap: HistoryEntry = {
          raw: current.raw,
          sourceRaw: current.sourceRaw ?? null,
          stashedComputed: current.stashedComputed ?? null,
          structure: structuredClone(current.structure),
          style: structuredClone(current.style),
        };
        const past = [...(prev.historyPast[id] ?? []), prevSnap].slice(-MAX_HISTORY_STEPS);
        const updatedDoc = normalizeLegacyTableDoc({
          raw: compRaw,
          sourceRaw: baseRaw,
          stashedComputed: null,
          structure: compStruct,
          style: compStyle,
        });
        const nextDocs = { ...prev.docs, [id]: updatedDoc };
        writePersistedSession(nextDocs, prev.pendingReuploads, prev.order, id);
        return {
          docs: nextDocs,
          historyPast: { ...prev.historyPast, [id]: past },
          historyFuture: { ...prev.historyFuture, [id]: [] },
          isComparingRaw: false,
          busy: false,
          errorKey: null,
        };
      });
      return true;
    } catch {
      set({ busy: false, errorKey: "tableStudio.errors.network" });
      return false;
    }
  },

  revertComputedToRaw: () => {
    const state = get();
    const current = state.docs[state.activeId];
    if (!current || !current.sourceRaw) return;
    state.goToStage("raw");
  },

  setComparingRaw: (comparing) => set({ isComparingRaw: comparing }),
  setActiveModal: (modal) => set({ activeModal: modal, errorKey: null }),
  setStyleDrawerOpen: (open) => set({ styleDrawerOpen: open }),
  clearError: () => set({ errorKey: null }),
  announce: (msg) => set({ liveAnnouncement: formatLiveStatusMessage(msg) }),

  uploadTableFile: async (file, sheetName) => {
    if (file.size > 25 * 1024 * 1024) {
      set({ busy: false, errorKey: "tableStudio.errors.tooLarge" });
      return false;
    }
    const ext = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : "";
    if (ext && ![".csv", ".tsv", ".txt", ".xlsx"].includes(ext)) {
      set({ busy: false, errorKey: "tableStudio.errors.unsupported" });
      return false;
    }
    set({ busy: true, errorKey: null });
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (sheetName) fd.append("sheet_name", sheetName);

      const res = await fetch("/api/v2/tables/parse", {
        method: "POST",
        body: fd,
      });
      const body = (await res.json()) as Record<string, unknown>;
      if (!res.ok) {
        set({
          busy: false,
          errorKey: String(body.error_key ?? "tableStudio.errors.decodeFailed"),
        });
        return false;
      }

      const raw = normalizeRawSnapshotPayload(body);
      uploadedFilesBySha.set(raw.source.sha256, file);

      set((state) => {
        // Check if this sha256 matches a pending reupload from sessionStorage
        const matchingPendingEntry = Object.entries(state.pendingReuploads).find(
          ([, p]) => p.sha256 === raw.source.sha256,
        );
        let doc: TableDoc;
        let docId = raw.snapshotId;
        const nextPending = { ...state.pendingReuploads };

        if (matchingPendingEntry && !sheetName) {
          const [oldId, pMeta] = matchingPendingEntry;
          docId = oldId;
          doc = normalizeLegacyTableDoc({
            raw,
            structure: pMeta.structure,
            style: pMeta.style,
          });
          delete nextPending[oldId];
        } else {
          doc = createInitialTableDoc(raw);
        }

        const nextDocs = { ...state.docs, [docId]: doc };
        const nextOrder = state.order.includes(docId) ? state.order : [...state.order, docId];
        writePersistedSession(nextDocs, nextPending, nextOrder, docId);
        return {
          docs: nextDocs,
          pendingReuploads: nextPending,
          order: nextOrder,
          activeId: docId,
          tablePageMode: "editor",
          isComparingRaw: false,
          activeModal: null,
          busy: false,
          errorKey: null,
        };
      });
      return true;
    } catch {
      set({ busy: false, errorKey: "tableStudio.errors.network" });
      return false;
    }
  },

  switchSheet: async (sheetName) => {
    const state = get();
    const cur = state.docs[state.activeId];
    if (!cur) return;
    const cachedFile = uploadedFilesBySha.get(cur.raw.source.sha256);
    if (!cachedFile) return;
    await state.uploadTableFile(cachedFile, sheetName);
  },

  submitPaste: async ({ text, html }) => {
    set({ busy: true, errorKey: null });
    try {
      const fd = new FormData();
      if (text) fd.append("pasted_text", text);
      if (html) fd.append("pasted_html", html);

      const res = await fetch("/api/v2/tables/parse", {
        method: "POST",
        body: fd,
      });
      const body = (await res.json()) as Record<string, unknown>;
      if (!res.ok) {
        set({
          busy: false,
          errorKey: String(body.error_key ?? "tableStudio.errors.decodeFailed"),
        });
        return false;
      }

      const raw = normalizeRawSnapshotPayload(body);
      const restored = body.restored_rules as
        | { structure?: StructureLayer; style?: StyleLayer }
        | undefined;

      const baseDoc = createInitialTableDoc(raw);
      const finalDoc: TableDoc =
        restored?.structure && restored?.style
          ? normalizeLegacyTableDoc({ raw, structure: restored.structure, style: restored.style })
          : baseDoc;

      const docId = raw.snapshotId;
      set((state) => {
        const nextDocs = { ...state.docs, [docId]: finalDoc };
        const nextOrder = state.order.includes(docId) ? state.order : [...state.order, docId];
        writePersistedSession(nextDocs, state.pendingReuploads, nextOrder, docId);
        return {
          docs: nextDocs,
          order: nextOrder,
          activeId: docId,
          tablePageMode: "editor",
          isComparingRaw: false,
          activeModal: null,
          busy: false,
          errorKey: null,
        };
      });
      return true;
    } catch {
      set({ busy: false, errorKey: "tableStudio.errors.network" });
      return false;
    }
  },

  downloadExport: async (format, model, customStem) => {
    const state = get();
    const cur = state.docs[state.activeId];
    if (!cur) return false;
    const stem = (customStem || makeSafeFilenameStem(cur)).trim() || "danqing_table";

    if (format === "html") {
      const htmlStr = `<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>${stem}</title></head><body>\n${buildStandaloneStyledHtml(cur, model)}\n</body></html>`;
      const blob = new Blob([htmlStr], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${stem}.html`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      return true;
    }

    set({ busy: true, errorKey: null });
    try {
      const endpoint =
        format === "zip" ? "/api/v2/tables/export/zip" : `/api/v2/tables/export/${format}`;
      const payload =
        format === "zip"
          ? serializeToBackendZipPayload(cur, model, stem)
          : serializeToBackendExportPayload(model, stem, cur.sourceRaw);

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        set({ busy: false, errorKey: "tableStudio.errors.exportFailed" });
        return false;
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${stem}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      set({ busy: false });
      return true;
    } catch {
      set({ busy: false, errorKey: "tableStudio.errors.exportFailed" });
      return false;
    }
  },
}));
