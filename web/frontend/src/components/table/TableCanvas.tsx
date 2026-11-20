import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Calculator,
  ChevronRight,
  Plus,
  RotateCcw,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../../store";
import { BUILTIN_TABLE_RAMPS } from "../../table/color";
import type {
  ColumnRole,
  ColumnSpec,
  ColumnVisualMode,
  Precision,
  RenderedCell,
  RenderedHeader,
  SemanticRole,
} from "../../table/model";
import { stripStarsInput } from "../../table/numeric";
import {
  type SuggestionCategory,
  buildDerivedSparklineColumns,
  buildInternalRows,
  buildModel,
  inferColumnDirectionHint,
  listAvailableSuggestions,
  listUnappliedSuggestions,
} from "../../table/pipeline";
import { useTableStudioStore } from "../../table/tableStore";
import { tetherPopoverFallback } from "../ModalDialog";

const SEMANTIC_ROLES: SemanticRole[] = ["normal", "count", "part", "sig"];
const VISUAL_MODES: ColumnVisualMode[] = ["auto", "plain", "heat", "bar"];
const PRECISIONS: Precision[] = ["auto", 0, 1, 2, 3];

function InlineSparklineSvg({
  values,
  domain,
  strokeHex,
}: {
  values: number[];
  domain: [number, number] | null;
  strokeHex: string;
}): React.ReactElement {
  const w = 68;
  const h = 18;
  const pad = 2;
  const [lo, hi] = domain ?? [Math.min(...values), Math.max(...values)];
  const span = hi - lo || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / Math.max(1, values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - lo) / span) * (h - pad * 2);
    return [x, y] as const;
  });
  const pointsAttr = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lastX, lastY] = pts[pts.length - 1];

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="dq-sparkline-svg"
      aria-hidden="true"
    >
      <polyline
        fill="none"
        stroke={strokeHex}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={pointsAttr}
      />
      <circle cx={lastX} cy={lastY} r="2.1" fill={strokeHex} />
    </svg>
  );
}

export function TableCanvas(): React.ReactElement | null {
  const { t, i18n } = useTranslation();
  const catalogPalettes = useStudioStore((s) => s.palettes);
  const docs = useTableStudioStore((s) => s.docs);
  const activeId = useTableStudioStore((s) => s.activeId);
  const isComparingRaw = useTableStudioStore((s) => s.isComparingRaw);
  const errorKey = useTableStudioStore((s) => s.errorKey);
  const clearError = useTableStudioStore((s) => s.clearError);
  const commit = useTableStudioStore((s) => s.commit);
  const applySuggestions = useTableStudioStore((s) => s.applySuggestions);
  const dismissSuggestion = useTableStudioStore((s) => s.dismissSuggestion);
  const goToStage = useTableStudioStore((s) => s.goToStage);
  const runSmartCompute = useTableStudioStore((s) => s.runSmartCompute);
  const revertComputedToRaw = useTableStudioStore((s) => s.revertComputedToRaw);
  const busy = useTableStudioStore((s) => s.busy);
  const switchSheet = useTableStudioStore((s) => s.switchSheet);
  const announce = useTableStudioStore((s) => s.announce);

  const doc = docs[activeId];
  const isZh = i18n.language.startsWith("zh");
  const langKey: "en" | "zh" = isZh ? "zh" : "en";

  const captionId = useId();
  const scrollWrapRef = useRef<HTMLDivElement | null>(null);
  const leftSentinelRef = useRef<HTMLSpanElement | null>(null);
  const rightSentinelRef = useRef<HTMLSpanElement | null>(null);
  const colMenuRef = useRef<HTMLDivElement | null>(null);

  const [showWarnings, setShowWarnings] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [computeDrawerOpen, setComputeDrawerOpen] = useState(false);
  const [suggestDrawerOpen, setSuggestDrawerOpen] = useState(false);
  const [tableGuideDismissed, setTableGuideDismissed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem("danqing_table_guide_dismissed") === "1";
    } catch {
      return false;
    }
  });
  const [shadowLeft, setShadowLeft] = useState(false);
  const [shadowRight, setShadowRight] = useState(false);

  // Caption & Spanner inline editing
  const [editingCaptionField, setEditingCaptionField] = useState<
    "title" | "subtitle" | null
  >(null);
  const [captionDraft, setCaptionDraft] = useState("");
  const [editingSpannerId, setEditingSpannerId] = useState<string | null>(null);
  const [spannerDraft, setSpannerDraft] = useState("");

  // Cell double-click editing
  const [editingCellKey, setEditingCellKey] = useState<string | null>(null);
  const [cellDraft, setCellDraft] = useState("");

  // Header menu popover + multi-header Shift+Click selection + drag reorder
  const [openMenuColId, setOpenMenuColId] = useState<string | null>(null);
  const [menuAnchorEl, setMenuAnchorEl] = useState<HTMLElement | null>(null);
  const [menuRenameDraft, setMenuRenameDraft] = useState("");
  const [menuUnitDraft, setMenuUnitDraft] = useState("");
  const [menuSpannerInput, setMenuSpannerInput] = useState("");
  const [showMenuSpannerInput, setShowMenuSpannerInput] = useState(false);

  const [selectedHeaderIds, setSelectedHeaderIds] = useState<string[]>([]);
  const [multiSpannerLabel, setMultiSpannerLabel] = useState("");
  const [showMultiSpannerInput, setShowMultiSpannerInput] = useState(false);

  const [dragHeaderColId, setDragHeaderColId] = useState<string | null>(null);
  const [dropTargetColId, setDropTargetColId] = useState<string | null>(null);

  // Smart statistical compute controls (synced to active doc's smartCompute / activeCompute)
  const [t1GroupCol, setT1GroupCol] = useState<string>("");
  const [t1ContMode, setT1ContMode] = useState<"auto" | "parametric" | "nonparametric">("auto");
  const [t1Overall, setT1Overall] = useState<boolean>(true);
  const [t1AdjustP, setT1AdjustP] = useState<boolean>(false);
  const [repSumMode, setRepSumMode] = useState<"parametric" | "nonparametric">("parametric");
  const [repEffect, setRepEffect] = useState<"auto" | "log2fc" | "fc" | "diff">("auto");
  const [repPaired, setRepPaired] = useState<boolean>(false);

  useEffect(() => {
    setComputeDrawerOpen(false);
    setSuggestDrawerOpen(false);
  }, [doc?.raw.snapshotId, doc?.structure.stage]);

  useEffect(() => {
    if (!doc) return;
    const baseRaw = doc.sourceRaw ?? doc.raw;
    const sc = baseRaw.suggestions.smartCompute;
    const ac = doc.structure.activeCompute;
    if (sc?.kind === "subject_table1") {
      setT1GroupCol(
        ac?.groupCol !== undefined
          ? ac.groupCol === null
            ? "none"
            : String(ac.groupCol)
          : String(sc.defaultGroupCol),
      );
      setT1ContMode(ac?.continuousMode ?? "auto");
      setT1Overall(ac?.includeOverall ?? true);
      setT1AdjustP(ac?.adjustP ?? false);
    } else if (sc?.kind === "replicate_collapse") {
      setRepSumMode(ac?.summaryMode ?? "parametric");
      setRepEffect(ac?.effectMetric ?? "auto");
      setRepPaired(ac?.paired ?? false);
    }
  }, [doc?.raw.snapshotId, doc?.sourceRaw?.snapshotId, doc?.structure.activeCompute]);

  // Close header menu on Escape or outside click
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        setOpenMenuColId(null);
        setSelectedHeaderIds([]);
        setShowMultiSpannerInput(false);
      }
    };
    const onPointerDown = (e: PointerEvent): void => {
      if (!openMenuColId) return;
      const target = e.target as Node | null;
      if (
        colMenuRef.current &&
        target &&
        !colMenuRef.current.contains(target) &&
        (!menuAnchorEl || !menuAnchorEl.contains(target))
      ) {
        setOpenMenuColId(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [openMenuColId, menuAnchorEl]);

  // Position column menu below clicked header
  useEffect(() => {
    if (openMenuColId && colMenuRef.current && menuAnchorEl) {
      tetherPopoverFallback(colMenuRef.current, menuAnchorEl, false);
    }
  }, [openMenuColId, menuAnchorEl]);

  const model = useMemo(
    () => (doc ? buildModel(doc, langKey, catalogPalettes) : null),
    [doc, langKey, catalogPalettes],
  );

  const baseInternalRows = useMemo(() => (doc ? buildInternalRows(doc) : []), [doc]);

  // Horizontal scroll edge shadow observer (`modern-web-guidance: scrollability-affordance-hints`)
  useEffect(() => {
    const scroller = scrollWrapRef.current;
    const leftEl = leftSentinelRef.current;
    const rightEl = rightSentinelRef.current;
    if (!scroller || !leftEl || !rightEl || typeof IntersectionObserver === "undefined") {
      return;
    }

    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.target === leftEl) {
            setShadowLeft(!entry.isIntersecting);
          } else if (entry.target === rightEl) {
            setShadowRight(!entry.isIntersecting);
          }
        }
      },
      {
        root: scroller,
        rootMargin: "0px 1px 0px 1px",
        threshold: 0.99,
      },
    );
    obs.observe(leftEl);
    obs.observe(rightEl);
    return () => obs.disconnect();
  }, [doc?.raw.snapshotId, model?.stage, model?.totalCols, isComparingRaw]);

  if (!doc || !model) return null;

  const { raw, structure } = doc;
  const showingRaw = structure.stage === "raw" || isComparingRaw;
  const effectiveStage = isComparingRaw ? "raw" : model.stage;
  const availableSuggestions = listAvailableSuggestions(doc);
  const unappliedSuggestions = listUnappliedSuggestions(doc);
  const activeSuggestionCats =
    structure.stage === "raw" ? availableSuggestions : unappliedSuggestions;

  const describeSuggestion = (cat: Exclude<SuggestionCategory, "all">): string => {
    const sug = raw.suggestions;
    switch (cat) {
      case "headerRows":
        return t("tableStudio.suggest.headerRows");
      case "footer":
        return t("tableStudio.suggest.footer", {
          count: sug.footnoteCandidates.length,
        });
      case "partBy": {
        const colName =
          sug.partBy !== null
            ? sug.resolvedHeaders[sug.partBy] || `Col ${sug.partBy + 1}`
            : "";
        return t("tableStudio.suggest.partBy", { col: colName });
      }
      case "merges":
        return t("tableStudio.suggest.merges", { count: sug.merges.length });
      case "sig":
        return t("tableStudio.suggest.sig");
      case "sparkline": {
        const count = sug.sparklineRuns[0]?.sourceCols.length ?? 0;
        return t("tableStudio.suggest.sparkline", { count });
      }
      case "pivot":
        return t("tableStudio.suggest.pivot");
    }
  };

  const reorderHeaderByColId = (sourceColId: string, targetColId: string): void => {
    if (sourceColId === targetColId) return;
    commit((draft) => {
      const cols = draft.structure.columns;
      const fromIdx = cols.findIndex((c) => c.id === sourceColId);
      const toIdx = cols.findIndex((c) => c.id === targetColId);
      if (fromIdx < 0 || toIdx < 0) return;
      const [moved] = cols.splice(fromIdx, 1);
      cols.splice(toIdx, 0, moved);
    });
  };

  const moveHeaderStep = (colId: string, dir: -1 | 1): void => {
    const visIdx = model.headers.findIndex((h) => h.colId === colId);
    const neighbor = model.headers[visIdx + dir];
    if (!neighbor) return;
    reorderHeaderByColId(colId, neighbor.colId);
    announce(`${model.headers[visIdx].label} → ${visIdx + dir + 1}`);
  };

  const openHeaderMenu = (h: RenderedHeader, anchor: HTMLElement): void => {
    const spec = structure.columns.find((c) => c.id === h.colId);
    setOpenMenuColId(h.colId);
    setMenuAnchorEl(anchor);
    setMenuRenameDraft(spec?.label ?? h.rawLabel);
    setMenuUnitDraft(spec?.unit ?? h.unit);
    setShowMenuSpannerInput(false);
    setMenuSpannerInput("");
  };

  const handleHeaderClick = (
    e: React.MouseEvent<HTMLButtonElement>,
    h: RenderedHeader,
    hIdx: number,
  ): void => {
    if (e.shiftKey) {
      e.preventDefault();
      setOpenMenuColId(null);
      setSelectedHeaderIds((prev) => {
        if (prev.length === 0) return [h.colId];
        const anchorIdx = model.headers.findIndex((x) => x.colId === prev[0]);
        if (anchorIdx < 0) return [h.colId];
        const [lo, hi] = anchorIdx <= hIdx ? [anchorIdx, hIdx] : [hIdx, anchorIdx];
        return model.headers.slice(lo, hi + 1).map((x) => x.colId);
      });
      return;
    }
    setSelectedHeaderIds([]);
    if (openMenuColId === h.colId) {
      setOpenMenuColId(null);
    } else {
      openHeaderMenu(h, e.currentTarget);
    }
  };

  const applyVisualToColumnIds = (
    targetColIds: string[],
    nextVis: ColumnVisualMode,
  ): void => {
    commit((draft) => {
      if (draft.structure.stage === "raw") {
        draft.structure.stage = "tidied";
      }
      if ((nextVis === "heat" || nextVis === "bar") && draft.style.preset === "raw") {
        draft.style.preset = "cns_three_line";
      }
      for (const cid of targetColIds) {
        const c = draft.structure.columns.find((x) => x.id === cid);
        if (!c) continue;
        c.visual = nextVis;
        if (nextVis === "plain" || nextVis === "auto") {
          if (c.role === "heat" || c.role === "bar") c.role = "normal";
        } else if (nextVis === "heat") {
          if (c.role === "bar") c.role = "normal";
          if (!c.visualConfig?.direction && inferColumnDirectionHint(c.label) === "reverse") {
            c.visualConfig = { ...(c.visualConfig ?? {}), direction: "reverse" };
          }
        } else if (nextVis === "bar") {
          if (c.role === "heat") c.role = "normal";
        }
      }
    });
  };

  const commitCellEdit = (cell: RenderedCell): void => {
    const targetColId = cell.editableColId;
    setEditingCellKey(null);
    if (!targetColId) return;
    const cleaned = stripStarsInput(cellDraft);
    const ovKey = `${cell.bodyRowIndex}:${targetColId}`;
    const existingOv = structure.cellOverrides[ovKey];
    const baseRow = baseInternalRows.find((r) => r.bodyRowIndex === cell.bodyRowIndex);
    const originalVal = existingOv
      ? existingOv.from
      : (baseRow?.cellsByColId[targetColId] ?? cell.raw);

    if (cleaned === originalVal) {
      if (existingOv) {
        commit((draft) => {
          delete draft.structure.cellOverrides[ovKey];
        });
      }
      return;
    }

    commit((draft) => {
      draft.structure.cellOverrides[ovKey] = {
        from: originalVal,
        to: cleaned,
      };
    });
  };

  const activeMenuHeader = openMenuColId
    ? model.headers.find((h) => h.colId === openMenuColId) ?? null
    : null;
  const activeMenuColSpec = openMenuColId
    ? structure.columns.find((c) => c.id === openMenuColId) ?? null
    : null;
  const activeMenuVisIdx = openMenuColId
    ? model.headers.findIndex((h) => h.colId === openMenuColId)
    : -1;

  const rawForCompare = isComparingRaw && doc.sourceRaw ? doc.sourceRaw : raw;
  const displayRowCount = showingRaw ? rawForCompare.grid.length : model.totalRows;
  const displayColCount = showingRaw ? (rawForCompare.grid[0]?.length ?? 0) : model.totalCols;
  const totalRenderedBodyRows = model.blocks.reduce((s, b) => s + b.rows.length, 0);
  let bodyRowCounter = 0;

  const baseSmartCompute = (doc.sourceRaw ?? raw).suggestions.smartCompute ?? null;

  return (
    <main id="main-canvas" className="dq-canvas-area dq-table-canvas-area">
      {/* Status Bar (Zero Duplicate Action Buttons) */}
      <div className="dq-table-status-bar">
        <div className="dq-table-status-bar__left">
          <div className="dq-stage-stepper" role="group" aria-label={t("tableStudio.a11y.modeSwitcher")}>
            <button
              type="button"
              className={`dq-stage-step${
                effectiveStage === "raw" ? " dq-stage-step--active" : ""
              }`}
              aria-current={effectiveStage === "raw" ? "step" : undefined}
              title={t("tableStudio.canvas.switchStageTitle", {
                stage: t("tableStudio.canvas.stageRaw"),
              })}
              onClick={() => goToStage("raw")}
            >
              {t("tableStudio.canvas.stageRaw")}
            </button>
            <ChevronRight size={12} strokeWidth={1.6} aria-hidden="true" />
            <button
              type="button"
              className={`dq-stage-step${
                effectiveStage === "tidied" ? " dq-stage-step--active" : ""
              }`}
              aria-current={effectiveStage === "tidied" ? "step" : undefined}
              title={t("tableStudio.canvas.switchStageTitle", {
                stage: t("tableStudio.canvas.stageTidied"),
              })}
              onClick={() => goToStage("tidied")}
            >
              {t("tableStudio.canvas.stageTidied")}
            </button>
            <ChevronRight size={12} strokeWidth={1.6} aria-hidden="true" />
            <button
              type="button"
              className={`dq-stage-step${
                effectiveStage === "styled" ? " dq-stage-step--active" : ""
              }`}
              aria-current={effectiveStage === "styled" ? "step" : undefined}
              title={t("tableStudio.canvas.switchStageTitle", {
                stage: t("tableStudio.canvas.stageStyled"),
              })}
              onClick={() => goToStage("styled")}
            >
              {t("tableStudio.canvas.stageStyled")}
            </button>
          </div>

          <span className="dq-table-meta-text">
            {t("tableStudio.canvas.dimensions", {
              rows: displayRowCount,
              cols: displayColCount,
            })}
          </span>

          {!showingRaw && model.blockCount > 0 ? (
            <span className="dq-table-meta-text">
              {t("tableStudio.canvas.blocksCount", { count: model.blockCount })}
            </span>
          ) : null}

          {effectiveStage === "styled" ? (
            <span className="dq-table-styled-note">
              {t("tableStudio.canvas.styledSubhint")}
            </span>
          ) : null}

          {raw.sheetsMeta.length > 1 ? (
            <label className="dq-sheet-select-wrap">
              <span>{t("tableStudio.canvas.sheetLabel")}</span>
              <select
                className="dq-select dq-select--compact"
                value={raw.source.sheet}
                onChange={(e) => void switchSheet(e.target.value)}
              >
                {raw.sheetsMeta.map((sm) => (
                  <option key={sm.name} value={sm.name} disabled={sm.empty}>
                    {sm.empty
                      ? `${sm.name} (${t("tableStudio.canvas.emptySheetSuffix")})`
                      : sm.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>

        <div className="dq-table-status-bar__right">
          {!showingRaw && !doc.sourceRaw && raw.suggestions.smartCompute ? (
            <button
              type="button"
              className="dq-recall-pill dq-recall-pill--compute"
              aria-expanded={computeDrawerOpen}
              onClick={() => setComputeDrawerOpen((v) => !v)}
            >
              <Calculator size={12} strokeWidth={1.7} aria-hidden="true" />
              <span>{t("tableStudio.compute.reopenPill")}</span>
            </button>
          ) : null}

          {!showingRaw && !raw.suggestions.smartCompute && unappliedSuggestions.length > 0 ? (
            <button
              type="button"
              className="dq-recall-pill dq-recall-pill--suggest"
              aria-expanded={suggestDrawerOpen}
              onClick={() => setSuggestDrawerOpen((v) => !v)}
            >
              <Wand2 size={12} strokeWidth={1.7} aria-hidden="true" />
              <span>
                {t("tableStudio.suggest.reopenPill", { count: unappliedSuggestions.length })}
              </span>
            </button>
          ) : null}

          {raw.warnings.length > 0 ? (
            <button
              type="button"
              className="dq-warn-badge-btn"
              aria-expanded={showWarnings}
              onClick={() => setShowWarnings((v) => !v)}
            >
              <AlertTriangle size={12} strokeWidth={1.7} aria-hidden="true" />
              <span>
                {t("tableStudio.warnings.badgeCount", { count: raw.warnings.length })}
              </span>
            </button>
          ) : null}
        </div>
      </div>

      {!tableGuideDismissed ? (
        <div className="dq-guide-pill">
          <div className="dq-guide-pill__lead">
            <Sparkles size={14} strokeWidth={1.7} aria-hidden="true" />
            <span>{t("onboarding.tableGuide")}</span>
          </div>
          <button
            type="button"
            className="dq-guide-pill__dismiss"
            onClick={() => {
              setTableGuideDismissed(true);
              try {
                window.localStorage.setItem("danqing_table_guide_dismissed", "1");
              } catch {
                // ignore storage errors
              }
            }}
          >
            {t("onboarding.dismiss")}
          </button>
        </div>
      ) : null}

      {errorKey ? (
        <div className="dq-table-error-banner dq-table-error-banner--inline" role="alert">
          <span>{t(errorKey)}</span>
          <button
            type="button"
            className="dq-btn dq-btn--ghost dq-btn--icon"
            aria-label={t("tableStudio.errors.dismiss")}
            title={t("tableStudio.errors.dismiss")}
            onClick={clearError}
          >
            <X size={14} strokeWidth={1.6} aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {showWarnings && raw.warnings.length > 0 ? (
        <div className="dq-warn-details-panel">
          {raw.warnings.map((w, idx) => (
            <div key={`${w.code}_${idx}`} className="dq-warn-details-row">
              <AlertTriangle size={12} strokeWidth={1.6} aria-hidden="true" />
              <span>{t(`tableStudio.warnings.${w.code}`, w.detail)}</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Smart Statistical Compute Card (Raw Stage or Recalled Drawer on Subject Records / Replicate Matrix) */}
      {((structure.stage === "raw" && !isComparingRaw) ||
        (computeDrawerOpen && !doc.sourceRaw && !isComparingRaw)) &&
      raw.suggestions.smartCompute ? (
        <div className="dq-compute-banner">
          <div className="dq-compute-banner__top">
            <div className="dq-compute-banner__lead">
              <Calculator size={15} strokeWidth={1.7} aria-hidden="true" />
              <span>
                {raw.suggestions.smartCompute.kind === "subject_table1"
                  ? t("tableStudio.compute.t1Lead", {
                      rows: raw.suggestions.smartCompute.nSubjects,
                      cont: raw.suggestions.smartCompute.nContinuous,
                      cat: raw.suggestions.smartCompute.nCategorical,
                    })
                  : t("tableStudio.compute.repLead", {
                      groups: raw.suggestions.smartCompute.groups.length,
                      cols: raw.suggestions.smartCompute.groups.reduce((s, g) => s + g.n, 0),
                      rows: raw.suggestions.smartCompute.nFeatures,
                    })}
              </span>
            </div>
            {structure.stage === "raw" ? (
              <button
                type="button"
                className="dq-btn dq-btn--ghost dq-btn--xs"
                onClick={() => applySuggestions("all", true)}
              >
                {t("tableStudio.compute.tidyWithoutCompute")}
              </button>
            ) : (
              <button
                type="button"
                className="dq-btn dq-btn--ghost dq-btn--xs"
                onClick={() => setComputeDrawerOpen(false)}
              >
                {t("tableStudio.compute.hideCard")}
              </button>
            )}
          </div>

          {raw.suggestions.smartCompute.kind === "subject_table1" ? (
            <div className="dq-compute-banner__controls">
              <label className="dq-compute-ctrl">
                <span>{t("tableStudio.compute.groupLabel")}</span>
                <select
                  className="dq-select dq-select--compact"
                  value={t1GroupCol}
                  onChange={(e) => setT1GroupCol(e.target.value)}
                >
                  {raw.suggestions.smartCompute.candidateGroupCols.map((cg) => (
                    <option key={cg.col} value={String(cg.col)}>
                      {cg.name} ({Object.keys(cg.groups).length})
                    </option>
                  ))}
                  <option value="none">{t("tableStudio.compute.overallOnlyOption")}</option>
                </select>
              </label>

              <label className="dq-compute-ctrl">
                <span>{t("tableStudio.compute.distLabel")}</span>
                <select
                  className="dq-select dq-select--compact"
                  value={t1ContMode}
                  onChange={(e) =>
                    setT1ContMode(e.target.value as "auto" | "parametric" | "nonparametric")
                  }
                >
                  <option value="auto">{t("tableStudio.compute.distAuto")}</option>
                  <option value="parametric">{t("tableStudio.compute.distParam")}</option>
                  <option value="nonparametric">{t("tableStudio.compute.distNonparam")}</option>
                </select>
              </label>

              {t1GroupCol !== "none" ? (
                <>
                  <label className="dq-check-row dq-check-row--xs">
                    <input
                      type="checkbox"
                      checked={t1Overall}
                      onChange={(e) => setT1Overall(e.target.checked)}
                    />
                    <span>{t("tableStudio.compute.includeOverall")}</span>
                  </label>

                  <label className="dq-check-row dq-check-row--xs">
                    <input
                      type="checkbox"
                      checked={t1AdjustP}
                      onChange={(e) => setT1AdjustP(e.target.checked)}
                    />
                    <span>{t("tableStudio.compute.adjustFdr")}</span>
                  </label>
                </>
              ) : null}

              <button
                type="button"
                className="dq-btn dq-btn--primary dq-btn--xs"
                disabled={busy}
                onClick={() => {
                  setComputeDrawerOpen(false);
                  void runSmartCompute(
                    "subject_table1",
                    {
                      group_col: t1GroupCol === "none" ? "none" : Number(t1GroupCol),
                      continuous_mode: t1ContMode,
                      include_overall: t1Overall,
                      adjust_p: t1AdjustP,
                    },
                    langKey,
                  );
                }}
              >
                <Sparkles size={13} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("tableStudio.compute.runTable1Btn")}</span>
              </button>
            </div>
          ) : (
            <div className="dq-compute-banner__controls">
              <label className="dq-compute-ctrl">
                <span>{t("tableStudio.compute.repSummaryLabel")}</span>
                <select
                  className="dq-select dq-select--compact"
                  value={repSumMode}
                  onChange={(e) =>
                    setRepSumMode(e.target.value as "parametric" | "nonparametric")
                  }
                >
                  <option value="parametric">{t("tableStudio.compute.repParam")}</option>
                  <option value="nonparametric">{t("tableStudio.compute.repNonparam")}</option>
                </select>
              </label>

              <label className="dq-compute-ctrl">
                <span>{t("tableStudio.compute.effectLabel")}</span>
                <select
                  className="dq-select dq-select--compact"
                  value={repEffect}
                  onChange={(e) =>
                    setRepEffect(e.target.value as "auto" | "log2fc" | "fc" | "diff")
                  }
                >
                  <option value="auto">{t("tableStudio.compute.effectAuto")}</option>
                  <option value="log2fc">{t("tableStudio.compute.effectLog2fc")}</option>
                  <option value="fc">{t("tableStudio.compute.effectFc")}</option>
                  <option value="diff">{t("tableStudio.compute.effectDiff")}</option>
                </select>
              </label>

              {raw.suggestions.smartCompute.canPair ? (
                <label className="dq-check-row dq-check-row--xs">
                  <input
                    type="checkbox"
                    checked={repPaired}
                    onChange={(e) => setRepPaired(e.target.checked)}
                  />
                  <span>{t("tableStudio.compute.pairedCheck")}</span>
                </label>
              ) : null}

              <button
                type="button"
                className="dq-btn dq-btn--primary dq-btn--xs"
                disabled={busy}
                onClick={() => {
                  setComputeDrawerOpen(false);
                  void runSmartCompute(
                    "replicate_collapse",
                    {
                      summary_mode: repSumMode,
                      effect_metric: repEffect,
                      paired: repPaired,
                    },
                    langKey,
                  );
                }}
              >
                <Sparkles size={13} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("tableStudio.compute.runRepBtn")}</span>
              </button>
            </div>
          )}
        </div>
      ) : null}

      {/* Live Recompute Provenance Bar (shown after auto-computing from raw observations) */}
      {doc.sourceRaw && !isComparingRaw && baseSmartCompute ? (
        <div className="dq-computed-bar">
          <div className="dq-computed-bar__meta">
            <Calculator size={13} strokeWidth={1.7} aria-hidden="true" />
            <strong>
              {baseSmartCompute.kind === "subject_table1"
                ? t("tableStudio.compute.computedProvenanceT1", {
                    rows: baseSmartCompute.nSubjects,
                  })
                : t("tableStudio.compute.computedProvenanceRep", {
                    cols: baseSmartCompute.groups.reduce((s, g) => s + g.n, 0),
                  })}
            </strong>
            <span className="dq-computed-bar__sub">
              {t("tableStudio.compute.sourceSheetNote")}
            </span>
          </div>

          <div className="dq-computed-bar__controls">
            {baseSmartCompute.kind === "subject_table1" ? (
              <>
                <select
                  className="dq-select dq-select--compact"
                  aria-label={t("tableStudio.compute.groupLabel")}
                  value={t1GroupCol}
                  disabled={busy}
                  onChange={(e) => {
                    const nextG = e.target.value;
                    setT1GroupCol(nextG);
                    void runSmartCompute(
                      "subject_table1",
                      {
                        group_col: nextG === "none" ? "none" : Number(nextG),
                        continuous_mode: t1ContMode,
                        include_overall: t1Overall,
                        adjust_p: t1AdjustP,
                      },
                      langKey,
                    );
                  }}
                >
                  {baseSmartCompute.candidateGroupCols.map((cg) => (
                    <option key={cg.col} value={String(cg.col)}>
                      {cg.name} ({Object.keys(cg.groups).length})
                    </option>
                  ))}
                  <option value="none">{t("tableStudio.compute.overallOnlyOption")}</option>
                </select>

                <select
                  className="dq-select dq-select--compact"
                  aria-label={t("tableStudio.compute.distLabel")}
                  value={t1ContMode}
                  disabled={busy}
                  onChange={(e) => {
                    const nextM = e.target.value as "auto" | "parametric" | "nonparametric";
                    setT1ContMode(nextM);
                    void runSmartCompute(
                      "subject_table1",
                      {
                        group_col: t1GroupCol === "none" ? "none" : Number(t1GroupCol),
                        continuous_mode: nextM,
                        include_overall: t1Overall,
                        adjust_p: t1AdjustP,
                      },
                      langKey,
                    );
                  }}
                >
                  <option value="auto">{t("tableStudio.compute.distAuto")}</option>
                  <option value="parametric">{t("tableStudio.compute.distParam")}</option>
                  <option value="nonparametric">{t("tableStudio.compute.distNonparam")}</option>
                </select>
              </>
            ) : (
              <>
                <select
                  className="dq-select dq-select--compact"
                  aria-label={t("tableStudio.compute.repSummaryLabel")}
                  value={repSumMode}
                  disabled={busy}
                  onChange={(e) => {
                    const nextS = e.target.value as "parametric" | "nonparametric";
                    setRepSumMode(nextS);
                    void runSmartCompute(
                      "replicate_collapse",
                      {
                        summary_mode: nextS,
                        effect_metric: repEffect,
                        paired: repPaired,
                      },
                      langKey,
                    );
                  }}
                >
                  <option value="parametric">{t("tableStudio.compute.repParam")}</option>
                  <option value="nonparametric">{t("tableStudio.compute.repNonparam")}</option>
                </select>

                <select
                  className="dq-select dq-select--compact"
                  aria-label={t("tableStudio.compute.effectLabel")}
                  value={repEffect}
                  disabled={busy}
                  onChange={(e) => {
                    const nextE = e.target.value as "auto" | "log2fc" | "fc" | "diff";
                    setRepEffect(nextE);
                    void runSmartCompute(
                      "replicate_collapse",
                      {
                        summary_mode: repSumMode,
                        effect_metric: nextE,
                        paired: repPaired,
                      },
                      langKey,
                    );
                  }}
                >
                  <option value="auto">{t("tableStudio.compute.effectAuto")}</option>
                  <option value="log2fc">{t("tableStudio.compute.effectLog2fc")}</option>
                  <option value="fc">{t("tableStudio.compute.effectFc")}</option>
                  <option value="diff">{t("tableStudio.compute.effectDiff")}</option>
                </select>
              </>
            )}

            <button
              type="button"
              className="dq-btn dq-btn--xs"
              disabled={busy}
              onClick={revertComputedToRaw}
            >
              <RotateCcw size={12} strokeWidth={1.7} aria-hidden="true" />
              <span>
                {t("tableStudio.compute.revertToRawBtn", {
                  rows: Math.max(0, doc.sourceRaw.grid.length - 1),
                })}
              </span>
            </button>
          </div>
        </div>
      ) : null}

      {/* Tidy Suggestion Bar (shown in Raw stage or recalled via Status Bar pill) */}
      {((structure.stage === "raw" && !raw.suggestions.smartCompute) ||
        (suggestDrawerOpen && !raw.suggestions.smartCompute && unappliedSuggestions.length > 0)) &&
      !isComparingRaw ? (
        <div className="dq-suggest-bar">
          <div className="dq-suggest-bar__main">
            <div className="dq-suggest-bar__summary">
              <Wand2 size={14} strokeWidth={1.6} aria-hidden="true" />
              {activeSuggestionCats.length > 0 ? (
                <span>
                  <strong>{t("tableStudio.suggest.detectedLead")}</strong>{" "}
                  {activeSuggestionCats
                    .map((cat) =>
                      describeSuggestion(cat as Exclude<SuggestionCategory, "all">),
                    )
                    .join(" · ")}
                </span>
              ) : (
                <span>{t("tableStudio.suggest.readyToTidy")}</span>
              )}
            </div>

            <div className="dq-suggest-bar__actions">
              {activeSuggestionCats.length > 0 ? (
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  aria-expanded={reviewOpen}
                  onClick={() => setReviewOpen((v) => !v)}
                >
                  {reviewOpen
                    ? t("tableStudio.suggest.hideReview")
                    : t("tableStudio.suggest.review")}
                </button>
              ) : null}

              <button
                type="button"
                className="dq-btn dq-btn--xs"
                onClick={() => {
                  setSuggestDrawerOpen(false);
                  applySuggestions("all", false);
                }}
              >
                <span>{t("tableStudio.suggest.applyStructureOnly")}</span>
              </button>

              <button
                type="button"
                className="dq-btn dq-btn--primary dq-btn--xs"
                onClick={() => {
                  setSuggestDrawerOpen(false);
                  applySuggestions("all", true);
                }}
              >
                <Sparkles size={13} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("tableStudio.suggest.applyAll")}</span>
              </button>

              {structure.stage !== "raw" ? (
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost dq-btn--xs"
                  onClick={() => setSuggestDrawerOpen(false)}
                >
                  {t("tableStudio.compute.hideCard")}
                </button>
              ) : null}
            </div>
          </div>

          {reviewOpen && activeSuggestionCats.length > 0 ? (
            <div className="dq-suggest-bar__items">
              {activeSuggestionCats.map((cat) => {
                const typedCat = cat as Exclude<SuggestionCategory, "all">;
                return (
                  <div key={typedCat} className="dq-suggest-item">
                    <span>{describeSuggestion(typedCat)}</span>
                    <div className="dq-suggest-item__btns">
                      <button
                        type="button"
                        className="dq-btn dq-btn--xs"
                        onClick={() => applySuggestions(typedCat, false)}
                      >
                        {t("tableStudio.suggest.accept")}
                      </button>
                      <button
                        type="button"
                        className="dq-btn dq-btn--ghost dq-btn--xs"
                        onClick={() => dismissSuggestion(typedCat)}
                      >
                        {t("tableStudio.suggest.dismiss")}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Tidied Stage Prompt Bar (shown when structure is tidied on unstyled grid) */}
      {model.stage === "tidied" && !showingRaw ? (
        <div className="dq-tidied-bar">
          <span className="dq-tidied-bar__lead">
            {t("tableStudio.canvas.tidiedReadyLead")}
          </span>
          <button
            type="button"
            className="dq-btn dq-btn--primary dq-btn--xs"
            onClick={() =>
              commit((draft) => {
                draft.style.preset = model.recommendedPreset;
                if (
                  model.recommendedPreset === "cns_three_line" &&
                  draft.style.rowRhythm === "none"
                ) {
                  draft.style.rowRhythm = "zebra";
                }
                if (model.isMultiScaleHeat) {
                  draft.style.heatScope = "per_row";
                }
              })
            }
          >
            <Sparkles size={13} strokeWidth={1.6} aria-hidden="true" />
            <span>
              {t("tableStudio.canvas.applyRecommendedStyle", {
                preset: t(`tableStudio.style.presets.${model.recommendedPreset}.title`),
              })}
            </span>
          </button>
        </div>
      ) : null}

      {/* Shift+Click Multi-Header Floating Bar */}
      {!showingRaw && selectedHeaderIds.length >= 2 ? (
        <div className="dq-multi-col-bar">
          <span className="dq-multi-col-bar__count">
            {t("tableStudio.canvas.multiSelected", { count: selectedHeaderIds.length })}
          </span>

          <div className="dq-inline-seg">
            {(
              [
                ["auto", "tableStudio.canvas.multiVisualAuto"],
                ["plain", "tableStudio.canvas.multiVisualPlain"],
                ["heat", "tableStudio.canvas.multiVisualHeat"],
                ["bar", "tableStudio.canvas.multiVisualBar"],
              ] as const
            ).map(([vm, labelKey]) => (
              <button
                key={vm}
                type="button"
                className="dq-btn dq-btn--xs"
                onClick={() => applyVisualToColumnIds(selectedHeaderIds, vm)}
              >
                {t(labelKey)}
              </button>
            ))}
          </div>

          <select
            className="dq-select dq-select--compact"
            aria-label={t("tableStudio.canvas.multiPaletteAria")}
            defaultValue=""
            onChange={(e) => {
              const palId = e.target.value || undefined;
              commit((draft) => {
                for (const cid of selectedHeaderIds) {
                  const c = draft.structure.columns.find((x) => x.id === cid);
                  if (!c) continue;
                  c.visualConfig = { ...(c.visualConfig ?? {}), paletteId: palId };
                }
              });
            }}
          >
            <option value="">{t("tableStudio.colMenu.rampInherit")}</option>
            {BUILTIN_TABLE_RAMPS.map((r) => (
              <option key={r.id} value={r.id}>
                {t(r.labelKey)}
              </option>
            ))}
          </select>

          {showMultiSpannerInput ? (
            <div className="dq-struct-inline-adder">
              <input
                type="text"
                className="dq-input dq-input--compact"
                value={multiSpannerLabel}
                placeholder={t("tableStudio.canvas.spannerPromptPlaceholder")}
                autoFocus
                onChange={(e) => setMultiSpannerLabel(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const memberIds = selectedHeaderIds.flatMap(
                      (hid) =>
                        model.headers.find((h) => h.colId === hid)?.memberColIds ?? [hid],
                    );
                    commit((draft) => {
                      draft.structure.spanners.push({
                        id: `sp_${Date.now()}`,
                        label: multiSpannerLabel.trim() || "Group",
                        columnIds: memberIds,
                      });
                    });
                    setShowMultiSpannerInput(false);
                    setMultiSpannerLabel("");
                    setSelectedHeaderIds([]);
                  }
                }}
              />
              <button
                type="button"
                className="dq-btn dq-btn--primary dq-btn--xs"
                onClick={() => {
                  const memberIds = selectedHeaderIds.flatMap(
                    (hid) =>
                      model.headers.find((h) => h.colId === hid)?.memberColIds ?? [hid],
                  );
                  commit((draft) => {
                    draft.structure.spanners.push({
                      id: `sp_${Date.now()}`,
                      label: multiSpannerLabel.trim() || "Group",
                      columnIds: memberIds,
                    });
                  });
                  setShowMultiSpannerInput(false);
                  setMultiSpannerLabel("");
                  setSelectedHeaderIds([]);
                }}
              >
                {t("tableStudio.suggest.accept")}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="dq-btn dq-btn--xs"
              onClick={() => setShowMultiSpannerInput(true)}
            >
              {t("tableStudio.canvas.multiAddSpanner")}
            </button>
          )}

          {selectedHeaderIds.length === 2 || selectedHeaderIds.length === 3 ? (
            <button
              type="button"
              className="dq-btn dq-btn--xs"
              onClick={() => {
                const memberIds = selectedHeaderIds.flatMap(
                  (hid) =>
                    model.headers.find((h) => h.colId === hid)?.memberColIds ?? [hid],
                );
                commit((draft) => {
                  draft.structure.merges.push({
                    id: `mg_${Date.now()}`,
                    columnIds: memberIds,
                    pattern: memberIds.length === 3 ? "ci" : "paren",
                  });
                });
                setSelectedHeaderIds([]);
              }}
            >
              {t("tableStudio.canvas.multiMerge")}
            </button>
          ) : null}

          <button
            type="button"
            className="dq-btn dq-btn--xs"
            onClick={() => {
              const memberIds = selectedHeaderIds.flatMap(
                (hid) => model.headers.find((h) => h.colId === hid)?.memberColIds ?? [hid],
              );
              const firstLbl =
                model.headers.find((h) => h.colId === selectedHeaderIds[0])?.label ?? "";
              const lastLbl =
                model.headers.find(
                  (h) => h.colId === selectedHeaderIds[selectedHeaderIds.length - 1],
                )?.label ?? "";
              commit((draft) => {
                const drvId = `drv_spark_${Date.now()}`;
                const srcColSpecs = memberIds
                  .map((mid) => draft.structure.columns.find((x) => x.id === mid))
                  .filter((x): x is ColumnSpec => Boolean(x));
                if (srcColSpecs.length < 2) return;
                draft.structure.derived.push({
                  id: drvId,
                  kind: "sparkline",
                  sourceIds: memberIds,
                  sharedScale: false,
                });
                for (const mid of memberIds) {
                  const c = draft.structure.columns.find((x) => x.id === mid);
                  if (c) c.hidden = true;
                }
                draft.structure.columns.push(
                  ...buildDerivedSparklineColumns(
                    drvId,
                    srcColSpecs,
                    `${firstLbl}–${lastLbl}`,
                  ),
                );
              });
              setSelectedHeaderIds([]);
            }}
          >
            {t("tableStudio.canvas.multiSparkline")}
          </button>

          <button
            type="button"
            className="dq-btn dq-btn--xs"
            onClick={() => {
              const memberIds = selectedHeaderIds.flatMap(
                (hid) => model.headers.find((h) => h.colId === hid)?.memberColIds ?? [hid],
              );
              commit((draft) => {
                for (const mid of memberIds) {
                  const c = draft.structure.columns.find((x) => x.id === mid);
                  if (c) c.hidden = true;
                }
              });
              setSelectedHeaderIds([]);
            }}
          >
            {t("tableStudio.canvas.multiHide")}
          </button>

          <button
            type="button"
            className="dq-btn dq-btn--ghost dq-btn--xs"
            onClick={() => setSelectedHeaderIds([])}
          >
            {t("tableStudio.canvas.multiClear")}
          </button>
        </div>
      ) : null}

      {/* Main Table Stage */}
      <div className="dq-table-stage-outer">
        <div
          className={`dq-scroll-shadow-shell${
            shadowLeft ? " dq-scroll-shadow--left" : ""
          }${shadowRight ? " dq-scroll-shadow--right" : ""}`}
        >
          <div
            ref={scrollWrapRef}
            tabIndex={0}
            role="region"
            aria-labelledby={showingRaw ? undefined : captionId}
            aria-label={showingRaw ? t("tableStudio.a11y.tableScrollRegion") : undefined}
            className={`dq-table-scroll-region dq-table-scroll-region--${
              showingRaw ? "raw" : model.preset
            }`}
          >
            <div
              className={`dq-table-paper dq-table-paper--${
                showingRaw ? "raw" : model.preset
              }${model.tabularNums ? " dq-table-paper--tabular" : ""}`}
            >
              <span
                ref={leftSentinelRef}
                className="dq-scroll-sentinel dq-scroll-sentinel--left"
                aria-hidden="true"
              />

              {showingRaw ? (
                /* Raw Grid View (`stage === "raw"` or Hold-to-Compare) */
                <table className="dq-raw-grid">
                  <tbody>
                    {rawForCompare.grid.map((row, rIdx) => {
                      const [h0, h1] = rawForCompare.suggestions.headerRows;
                      const isSugHeader = rIdx >= h0 && rIdx <= h1;
                      const isSugFooter =
                        model.suggestedFooterRowStart !== null &&
                        rIdx >= model.suggestedFooterRowStart;
                      return (
                        <tr
                          key={rIdx}
                          className={
                            isSugHeader
                              ? "dq-raw-grid__row--header"
                              : isSugFooter
                                ? "dq-raw-grid__row--footer"
                                : undefined
                          }
                        >
                          <th scope="row" className="dq-raw-grid__rownum">
                            {rIdx + 1}
                          </th>
                          {row.map((cellText, cIdx) => (
                            <td
                              key={cIdx}
                              title={
                                isSugHeader
                                  ? t("tableStudio.canvas.rawHeaderTag")
                                  : isSugFooter
                                    ? t("tableStudio.canvas.rawFooterTag")
                                    : undefined
                              }
                            >
                              {cellText}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                /* Tidied / Styled Semantic Table View */
                <>
                  <table className={`dq-pub-table dq-pub-table--${model.preset}`}>
                    <caption id={captionId} className="dq-pub-caption">
                      {model.preset === "ft_editorial" ? (
                        <div className="dq-ft-header__topline" aria-hidden="true" />
                      ) : null}

                      <div className="dq-pub-caption__head">
                        <div className="dq-pub-caption__titles">
                          {editingCaptionField === "title" ? (
                            <input
                              type="text"
                              className="dq-input dq-caption-edit-input"
                              aria-label={t("tableStudio.structure.title")}
                              value={captionDraft}
                              autoFocus
                              onChange={(e) => setCaptionDraft(e.target.value)}
                              onBlur={() => {
                                commit((draft) => {
                                  draft.structure.title = captionDraft.trim();
                                });
                                setEditingCaptionField(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                if (e.key === "Escape") setEditingCaptionField(null);
                              }}
                            />
                          ) : (
                            <span
                              className={
                                model.preset === "ft_editorial"
                                  ? "dq-ft-header__title dq-editable-caption"
                                  : "dq-pub-caption__title dq-editable-caption"
                              }
                              onClick={() => {
                                setEditingCaptionField("title");
                                setCaptionDraft(structure.title);
                              }}
                            >
                              {structure.tableNumber ? `${structure.tableNumber}. ` : ""}
                              {structure.title || t("tableStudio.canvas.editTitlePlaceholder")}
                            </span>
                          )}

                          {editingCaptionField === "subtitle" ? (
                            <input
                              type="text"
                              className="dq-input dq-input--compact dq-caption-edit-input"
                              aria-label={t("tableStudio.structure.subtitle")}
                              value={captionDraft}
                              autoFocus
                              onChange={(e) => setCaptionDraft(e.target.value)}
                              onBlur={() => {
                                commit((draft) => {
                                  draft.structure.subtitle = captionDraft.trim();
                                });
                                setEditingCaptionField(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                if (e.key === "Escape") setEditingCaptionField(null);
                              }}
                            />
                          ) : structure.subtitle ? (
                            <span
                              className="dq-pub-caption__sub dq-editable-caption"
                              onClick={() => {
                                setEditingCaptionField("subtitle");
                                setCaptionDraft(structure.subtitle);
                              }}
                            >
                              {structure.subtitle}
                            </span>
                          ) : null}
                        </div>

                        {model.heatLegends.length > 0 ? (
                          <div
                            className="dq-heat-legend-group"
                            aria-label={t("tableStudio.canvas.heatLegendAria")}
                          >
                            {model.heatLegends.map((leg, lIdx) => (
                              <div
                                key={leg.id ?? `leg_${lIdx}`}
                                className="dq-heat-legend"
                              >
                                {leg.label && model.heatLegends.length > 1 ? (
                                  <span className="dq-heat-legend__label">{leg.label}</span>
                                ) : (
                                  <span className="dq-heat-legend__scope">
                                    {t(`tableStudio.style.scopes.${leg.scope}`)}
                                  </span>
                                )}
                                <span className="dq-heat-legend__tick">{leg.minLabel}</span>
                                <span className="dq-heat-legend__bars" aria-hidden="true">
                                  <span
                                    className="dq-heat-legend__bar"
                                    style={{
                                      background: `linear-gradient(90deg, ${leg.stops.join(", ")})`,
                                    }}
                                  />
                                  {leg.secondaryStops ? (
                                    <span
                                      className="dq-heat-legend__bar"
                                      style={{
                                        background: `linear-gradient(90deg, ${leg.secondaryStops.join(", ")})`,
                                      }}
                                    />
                                  ) : null}
                                </span>
                                <span className="dq-heat-legend__tick">{leg.maxLabel}</span>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </caption>

                    <thead>
                      {/* Optional Spanner Row */}
                      {model.spanners.length > 0 ? (
                        <tr className="dq-pub-spanner-row">
                          {(() => {
                            const ths: React.ReactNode[] = [];
                            let c = 0;
                            while (c < model.headers.length) {
                              const sp = model.spanners.find((s) => s.startCol === c);
                              if (sp) {
                                const span = sp.endCol - sp.startCol + 1;
                                ths.push(
                                  <th
                                    key={sp.id}
                                    colSpan={span}
                                    scope="colgroup"
                                    className="dq-pub-spanner-th"
                                    onDoubleClick={() => {
                                      setEditingSpannerId(sp.id);
                                      setSpannerDraft(sp.label);
                                    }}
                                  >
                                    {editingSpannerId === sp.id ? (
                                      <input
                                        type="text"
                                        className="dq-input dq-input--inline"
                                        aria-label={t("tableStudio.structure.spannersTitle")}
                                        value={spannerDraft}
                                        autoFocus
                                        onChange={(e) => setSpannerDraft(e.target.value)}
                                        onBlur={() => {
                                          commit((draft) => {
                                            const item = draft.structure.spanners.find(
                                              (x) => x.id === sp.id,
                                            );
                                            if (item && spannerDraft.trim()) {
                                              item.label = spannerDraft.trim();
                                            }
                                          });
                                          setEditingSpannerId(null);
                                        }}
                                        onKeyDown={(e) => {
                                          if (e.key === "Enter") {
                                            (e.target as HTMLInputElement).blur();
                                          }
                                          if (e.key === "Escape") setEditingSpannerId(null);
                                        }}
                                      />
                                    ) : (
                                      <span className="dq-pub-spanner-inner">
                                        {sp.label}
                                        {sp.superscript ? (
                                          <sup className="dq-table-sup">{sp.superscript}</sup>
                                        ) : null}
                                      </span>
                                    )}
                                  </th>,
                                );
                                c = sp.endCol + 1;
                              } else {
                                ths.push(
                                  <th
                                    key={`empty_sp_${c}`}
                                    className={`dq-pub-spanner-empty${
                                      c === 0 ? " dq-pub-sticky-col" : ""
                                    }`}
                                  />,
                                );
                                c += 1;
                              }
                            }
                            return ths;
                          })()}
                        </tr>
                      ) : null}

                      {/* Leaf Column Header Row */}
                      <tr>
                        {model.headers.map((h, hIdx) => {
                          const isSelected = selectedHeaderIds.includes(h.colId);
                          const isDrop =
                            dropTargetColId === h.colId && dragHeaderColId !== h.colId;
                          return (
                            <th
                              key={h.colId}
                              scope="col"
                              aria-sort={
                                h.sortDir === "asc"
                                  ? "ascending"
                                  : h.sortDir === "desc"
                                    ? "descending"
                                    : undefined
                              }
                              draggable
                              onDragStart={(e) => {
                                setDragHeaderColId(h.colId);
                                e.dataTransfer.effectAllowed = "move";
                                e.dataTransfer.setData("text/plain", h.colId);
                              }}
                              onDragOver={(e) => {
                                e.preventDefault();
                                setDropTargetColId(h.colId);
                              }}
                              onDragLeave={() => {
                                if (dropTargetColId === h.colId) setDropTargetColId(null);
                              }}
                              onDrop={(e) => {
                                e.preventDefault();
                                if (dragHeaderColId && dragHeaderColId !== h.colId) {
                                  reorderHeaderByColId(dragHeaderColId, h.colId);
                                }
                                setDragHeaderColId(null);
                                setDropTargetColId(null);
                              }}
                              onDragEnd={() => {
                                setDragHeaderColId(null);
                                setDropTargetColId(null);
                              }}
                              className={`dq-pub-align-${h.align}${
                                hIdx === 0 ? " dq-pub-sticky-col" : ""
                              }${isSelected ? " dq-th--selected" : ""}${
                                isDrop ? " dq-th--drop-target" : ""
                              }`}
                            >
                              <button
                                type="button"
                                className="dq-col-th-btn"
                                aria-label={t("tableStudio.colMenu.openLabel", {
                                  name: h.label,
                                })}
                                aria-expanded={openMenuColId === h.colId}
                                onClick={(e) => handleHeaderClick(e, h, hIdx)}
                                onKeyDown={(e) => {
                                  if (e.altKey && e.key === "ArrowLeft") {
                                    e.preventDefault();
                                    moveHeaderStep(h.colId, -1);
                                  } else if (e.altKey && e.key === "ArrowRight") {
                                    e.preventDefault();
                                    moveHeaderStep(h.colId, 1);
                                  }
                                }}
                              >
                                <span>{h.label}</span>
                                {h.superscript ? (
                                  <sup className="dq-table-sup">{h.superscript}</sup>
                                ) : null}
                                  {h.sortDir === "asc" ? (
                                    <ArrowUp size={11} strokeWidth={1.8} aria-hidden="true" />
                                  ) : h.sortDir === "desc" ? (
                                    <ArrowDown size={11} strokeWidth={1.8} aria-hidden="true" />
                                  ) : null}
                                </button>
                                {h.headerRampStops ? (
                                  <span
                                    className="dq-th-ramp-underline"
                                    aria-hidden="true"
                                    style={{
                                      background: `linear-gradient(90deg, ${h.headerRampStops.join(", ")})`,
                                    }}
                                  />
                                ) : null}
                              </th>
                            );
                          })}
                        </tr>
                      </thead>

                      <tbody>
                        {model.blocks.map((block) => (
                          <React.Fragment key={`blk_${block.blockIndex}_${block.partName}`}>
                            {block.partName ? (
                              <tr className="dq-pub-part-row">
                                <th
                                  colSpan={Math.max(1, model.headers.length)}
                                  scope="colgroup"
                                  className="dq-pub-part-cell"
                                  style={{ borderInlineStartColor: block.partAccent }}
                                >
                                  {block.partName}
                                </th>
                              </tr>
                            ) : null}

                            {block.rows.map((row) => {
                              bodyRowCounter += 1;
                              const isLastRow = bodyRowCounter === totalRenderedBodyRows;
                              const isSummaryRow = Boolean(row[0]?.isSummaryRow);
                              const rowClass =
                                [
                                  isLastRow ? "dq-pub-row--final" : "",
                                  isSummaryRow ? "dq-pub-row--summary" : "",
                                ]
                                  .filter(Boolean)
                                  .join(" ") || undefined;
                              return (
                                <tr
                                  key={`row_${row[0]?.bodyRowIndex ?? bodyRowCounter}`}
                                  className={rowClass}
                                >
                                  {row.map((cell, cIdx) => {
                                    const hdr = model.headers[cIdx];
                                    const CellTag =
                                      cIdx === 0 && cell.align === "left" ? "th" : "td";
                                    const isEditing = editingCellKey === cell.key;
                                    const isPartialHeat =
                                      model.preset !== "matrix_heatmap" &&
                                      hdr?.effectiveVisual === "heat" &&
                                      Boolean(cell.bgHex);
                                    const styleObj: React.CSSProperties = {
                                      backgroundColor: cell.bgHex ?? undefined,
                                      color: cell.fgHex,
                                      fontWeight: cell.bold ? 700 : undefined,
                                      paddingInlineStart:
                                        cell.indent > 0 ? `${11 + cell.indent * 16}px` : undefined,
                                    };

                                    return (
                                      <CellTag
                                        key={cell.key}
                                        scope={CellTag === "th" ? "row" : undefined}
                                        style={styleObj}
                                        title={
                                          cell.edited
                                            ? t("tableStudio.canvas.originalValueTitle", {
                                                value: cell.editedFrom ?? "",
                                              })
                                            : undefined
                                        }
                                        onDoubleClick={() => {
                                          if (!cell.editableColId) return;
                                          setEditingCellKey(cell.key);
                                          setCellDraft(stripStarsInput(cell.raw));
                                        }}
                                        className={`dq-pub-cell dq-pub-align-${cell.align}${
                                          cIdx === 0 ? " dq-pub-sticky-col" : ""
                                        }${cell.boxBorder ? " dq-pub-cell--boxed" : ""}${
                                          isPartialHeat ? " dq-pub-cell--partial-heat" : ""
                                        }${cell.edited ? " dq-cell-edited" : ""}`}
                                      >
                                        {isEditing ? (
                                          <input
                                            type="text"
                                            className="dq-input dq-input--cell"
                                            aria-label={t("tableStudio.canvas.editCellLabel")}
                                            value={cellDraft}
                                            autoFocus
                                            onChange={(e) => setCellDraft(e.target.value)}
                                            onBlur={() => commitCellEdit(cell)}
                                            onKeyDown={(e) => {
                                              if (e.key === "Enter") commitCellEdit(cell);
                                              if (e.key === "Escape") setEditingCellKey(null);
                                            }}
                                          />
                                        ) : cell.sparklineValues ? (
                                          <span className="dq-sparkline-wrap">
                                            <InlineSparklineSvg
                                              values={cell.sparklineValues}
                                              domain={cell.sparklineDomain}
                                              strokeHex={
                                                cell.bgHex && cell.fgHex === "#FFFFFF"
                                                  ? "#FFFFFF"
                                                  : model.preset === "raw"
                                                    ? "#475569"
                                                    : model.accentHex
                                              }
                                            />
                                            {cell.display ? (
                                              <span className="dq-sparkline-end">{cell.display}</span>
                                            ) : null}
                                          </span>
                                        ) : cell.barSpec !== null ? (
                                          <span className="dq-inlinebar-wrap">
                                            <span
                                              className="dq-inlinebar-val"
                                              style={
                                                hdr?.barValWidthCh
                                                  ? { inlineSize: `${hdr.barValWidthCh}ch` }
                                                  : undefined
                                              }
                                            >
                                              {cell.parts &&
                                              cell.parts.length === 2 &&
                                              hdr?.partWidthsCh ? (
                                                <span className="dq-num-merge">
                                                  <span
                                                    className="dq-num-a"
                                                    style={{
                                                      inlineSize: `${hdr.partWidthsCh[0]}ch`,
                                                    }}
                                                  >
                                                    {cell.parts[0].display}
                                                  </span>
                                                  <span
                                                    className="dq-num-b"
                                                    style={{
                                                      inlineSize: `${hdr.partWidthsCh[1]}ch`,
                                                    }}
                                                  >
                                                    {cell.parts[1].display}
                                                  </span>
                                                </span>
                                              ) : (
                                                <>
                                                  <span>{cell.display}</span>
                                                  {cell.superscript ? (
                                                    <sup className="dq-table-sup">
                                                      {cell.superscript}
                                                    </sup>
                                                  ) : null}
                                                </>
                                              )}
                                            </span>
                                            <span className="dq-inlinebar-track" aria-hidden="true">
                                              {cell.barSpec.bidirectional ? (
                                                <span
                                                  className="dq-inlinebar-zero"
                                                  style={{
                                                    left: `${cell.barSpec.zeroPct.toFixed(1)}%`,
                                                  }}
                                                />
                                              ) : null}
                                              <span
                                                className="dq-inlinebar-fill"
                                                style={{
                                                  left: `${cell.barSpec.startPct.toFixed(1)}%`,
                                                  width: `${Math.max(
                                                    cell.barSpec.widthPct,
                                                    cell.barSpec.ratio > 0 ? 2 : 0,
                                                  ).toFixed(1)}%`,
                                                  backgroundColor:
                                                    cell.bgHex && cell.fgHex === "#FFFFFF"
                                                      ? "rgb(255 255 255 / 0.85)"
                                                      : cell.barSpec.fillHex,
                                                }}
                                              />
                                            </span>
                                          </span>
                                        ) : cell.parts &&
                                        cell.parts.length === 2 &&
                                        hdr?.partWidthsCh ? (
                                        <span className="dq-num-merge">
                                          <span
                                            className="dq-num-a"
                                            style={{ inlineSize: `${hdr.partWidthsCh[0]}ch` }}
                                          >
                                            {cell.parts[0].display}
                                          </span>
                                          <span
                                            className="dq-num-b"
                                            style={{ inlineSize: `${hdr.partWidthsCh[1]}ch` }}
                                          >
                                            {cell.parts[1].display}
                                          </span>
                                        </span>
                                      ) : (
                                        <>
                                          <span>{cell.display}</span>
                                          {cell.superscript ? (
                                            <sup className="dq-table-sup">{cell.superscript}</sup>
                                          ) : null}
                                        </>
                                      )}
                                    </CellTag>
                                  );
                                })}
                              </tr>
                            );
                          })}
                        </React.Fragment>
                      ))}
                    </tbody>
                  </table>

                  {/* Footnotes Footer */}
                  <div className="dq-pub-footnotes">
                    {model.footnotes.map((fn) => (
                      <div
                        key={fn.id}
                        className={`dq-pub-footnote-row${
                          fn.readOnly ? " dq-pub-footnote-row--readonly" : ""
                        }`}
                      >
                        {fn.symbol ? <sup className="dq-table-sup">{fn.symbol}</sup> : null}
                        {fn.readOnly ? (
                          <span>{fn.text}</span>
                        ) : (
                          <input
                            type="text"
                            className="dq-fn-inline-input"
                            aria-label={t("tableStudio.canvas.editFootnoteText")}
                            value={fn.text}
                            placeholder={t("tableStudio.canvas.editFootnoteText")}
                            onChange={(e) => {
                              const val = e.target.value;
                              commit((draft) => {
                                const item = draft.structure.footnotes.find(
                                  (x) => x.id === fn.id,
                                );
                                if (item) item.text = val;
                              });
                            }}
                          />
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      className="dq-add-fn-inline"
                      onClick={() =>
                        commit((draft) => {
                          const idx = draft.structure.footnotes.length;
                          draft.structure.footnotes.push({
                            id: `fn_${Date.now()}`,
                            symbol: String.fromCharCode(97 + (idx % 26)),
                            text: "",
                            anchorColumnIds: [],
                          });
                        })
                      }
                    >
                      <Plus size={11} strokeWidth={1.6} aria-hidden="true" />
                      <span>{t("tableStudio.canvas.addFootnote")}</span>
                    </button>
                  </div>
                </>
              )}

              <span
                ref={rightSentinelRef}
                className="dq-scroll-sentinel dq-scroll-sentinel--right"
                aria-hidden="true"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Anchored Column Header Popover Menu */}
      {activeMenuHeader && activeMenuColSpec ? (
        <div
          ref={colMenuRef}
          role="dialog"
          aria-label={t("tableStudio.colMenu.openLabel", { name: activeMenuHeader.label })}
          className="dq-col-menu"
        >
          <label className="dq-field-label">
            <span>
              {activeMenuHeader.spannerPrefix ? (
                <span className="dq-col-spanner-prefix">
                  {`${activeMenuHeader.spannerPrefix} · `}
                </span>
              ) : null}
              {t("tableStudio.colMenu.renameLabel")}
            </span>
            <input
              type="text"
              className="dq-input dq-input--compact"
              value={menuRenameDraft}
              onChange={(e) => setMenuRenameDraft(e.target.value)}
              onBlur={() => {
                const trimmed = menuRenameDraft.trim();
                if (trimmed && trimmed !== activeMenuColSpec.label) {
                  commit((draft) => {
                    const c = draft.structure.columns.find(
                      (x) => x.id === activeMenuColSpec.id,
                    );
                    if (c) c.label = trimmed;
                    const mg = draft.structure.merges.find(
                      (m) => m.columnIds[0] === activeMenuColSpec.id,
                    );
                    if (mg) mg.mergedLabel = trimmed;
                  });
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  (e.target as HTMLInputElement).blur();
                  setOpenMenuColId(null);
                }
              }}
            />
          </label>

          {/* 4-Way Column Visual Mode Segmented Control */}
          <div className="dq-col-menu__section">
            <span className="dq-field-label">{t("tableStudio.colMenu.visualLabel")}</span>
            <div className="dq-col-visual-seg">
              {VISUAL_MODES.map((vm) => {
                const disabled =
                  (vm === "heat" || vm === "bar") && !activeMenuHeader.hasNumericValues;
                return (
                  <button
                    key={vm}
                    type="button"
                    className="dq-btn dq-btn--xs"
                    disabled={disabled}
                    aria-pressed={activeMenuHeader.visualMode === vm}
                    onClick={() => applyVisualToColumnIds([activeMenuColSpec.id], vm)}
                  >
                    {t(`tableStudio.visuals.${vm}`)}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Per-Column Color Ramp & Scale Controls */}
          {activeMenuHeader.effectiveVisual === "heat" ||
          activeMenuHeader.effectiveVisual === "bar" ? (
            <div className="dq-col-menu__visual-box">
              <label className="dq-field-label">
                <span>{t("tableStudio.colMenu.colRampLabel")}</span>
                <select
                  className="dq-select dq-select--compact"
                  value={activeMenuColSpec.visualConfig?.paletteId ?? ""}
                  onChange={(e) => {
                    const palId = e.target.value || undefined;
                    commit((draft) => {
                      const c = draft.structure.columns.find(
                        (x) => x.id === activeMenuColSpec.id,
                      );
                      if (!c) return;
                      c.visualConfig = { ...(c.visualConfig ?? {}), paletteId: palId };
                    });
                  }}
                >
                  <option value="">{t("tableStudio.colMenu.rampInherit")}</option>
                  {BUILTIN_TABLE_RAMPS.map((r) => (
                    <option key={r.id} value={r.id}>
                      {t(r.labelKey)}
                    </option>
                  ))}
                  {activeMenuColSpec.visualConfig?.paletteId &&
                  !BUILTIN_TABLE_RAMPS.some(
                    (r) => r.id === activeMenuColSpec.visualConfig?.paletteId,
                  ) ? (
                    <option value={activeMenuColSpec.visualConfig.paletteId}>
                      {activeMenuColSpec.visualConfig.paletteId}
                    </option>
                  ) : null}
                </select>
              </label>

              <div className="dq-col-ramp-pills">
                {BUILTIN_TABLE_RAMPS.filter((r) => r.id !== "danqing_dual_part").map((r) => {
                  const isActive = activeMenuColSpec.visualConfig?.paletteId === r.id;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      className="dq-col-ramp-pill"
                      aria-pressed={isActive}
                      aria-label={t(r.labelKey)}
                      title={t(r.labelKey)}
                      onClick={() =>
                        commit((draft) => {
                          const c = draft.structure.columns.find(
                            (x) => x.id === activeMenuColSpec.id,
                          );
                          if (!c) return;
                          const nextPal =
                            c.visualConfig?.paletteId === r.id ? undefined : r.id;
                          c.visualConfig = {
                            ...(c.visualConfig ?? {}),
                            paletteId: nextPal,
                          };
                        })
                      }
                    >
                      <span
                        className="dq-col-ramp-pill__bar"
                        aria-hidden="true"
                        style={{
                          background: `linear-gradient(90deg, ${r.stops.join(", ")})`,
                        }}
                      />
                    </button>
                  );
                })}
              </div>

              {activeMenuHeader.effectiveVisual === "bar" ? (
                <div className="dq-table-inline-field">
                  <span className="dq-field-label">
                    {t("tableStudio.colMenu.barDomainLabel")}
                  </span>
                  <div className="dq-inline-seg">
                    <button
                      type="button"
                      className="dq-btn dq-btn--xs"
                      aria-pressed={
                        (activeMenuColSpec.visualConfig?.barDomain ?? "column_max") ===
                        "column_max"
                      }
                      onClick={() =>
                        commit((draft) => {
                          const c = draft.structure.columns.find(
                            (x) => x.id === activeMenuColSpec.id,
                          );
                          if (!c) return;
                          c.visualConfig = {
                            ...(c.visualConfig ?? {}),
                            barDomain: "column_max",
                          };
                        })
                      }
                    >
                      {t("tableStudio.colMenu.barDomainMax")}
                    </button>
                    <button
                      type="button"
                      className="dq-btn dq-btn--xs"
                      aria-pressed={
                        activeMenuColSpec.visualConfig?.barDomain === "percent_100"
                      }
                      onClick={() =>
                        commit((draft) => {
                          const c = draft.structure.columns.find(
                            (x) => x.id === activeMenuColSpec.id,
                          );
                          if (!c) return;
                          c.visualConfig = {
                            ...(c.visualConfig ?? {}),
                            barDomain: "percent_100",
                          };
                        })
                      }
                    >
                      {t("tableStudio.colMenu.barDomainPct100")}
                    </button>
                  </div>
                </div>
              ) : null}

              <label className="dq-check-row">
                <input
                  type="checkbox"
                  checked={activeMenuColSpec.visualConfig?.direction === "reverse"}
                  onChange={(e) => {
                    const rev = e.target.checked;
                    commit((draft) => {
                      const c = draft.structure.columns.find(
                        (x) => x.id === activeMenuColSpec.id,
                      );
                      if (!c) return;
                      c.visualConfig = {
                        ...(c.visualConfig ?? {}),
                        direction: rev ? "reverse" : "normal",
                      };
                    });
                  }}
                />
                <span>{t("tableStudio.colMenu.reverseScale")}</span>
              </label>

              {activeMenuHeader.effectiveVisual === "heat" ? (
                <>
                  <label className="dq-check-row">
                    <input
                      type="checkbox"
                      checked={activeMenuColSpec.visualConfig?.center === "ratio_1"}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        commit((draft) => {
                          const c = draft.structure.columns.find(
                            (x) => x.id === activeMenuColSpec.id,
                          );
                          if (!c) return;
                          c.visualConfig = {
                            ...(c.visualConfig ?? {}),
                            center: checked ? "ratio_1" : "auto",
                          };
                        });
                      }}
                    />
                    <span>{t("tableStudio.colMenu.ratioCenterOne")}</span>
                  </label>

                  <label className="dq-check-row">
                    <input
                      type="checkbox"
                      checked={
                        (activeMenuColSpec.visualConfig?.domainClip ??
                          doc.style.heatDomainClip ??
                          "minmax") === "p5_p95"
                      }
                      onChange={(e) => {
                        const checked = e.target.checked;
                        commit((draft) => {
                          const c = draft.structure.columns.find(
                            (x) => x.id === activeMenuColSpec.id,
                          );
                          if (!c) return;
                          c.visualConfig = {
                            ...(c.visualConfig ?? {}),
                            domainClip: checked ? "p5_p95" : "minmax",
                          };
                        });
                      }}
                    />
                    <span>{t("tableStudio.colMenu.outlierClipP95")}</span>
                  </label>

                  {activeMenuColSpec.role === "sig" ? (
                    <p className="dq-col-menu__hint">
                      {t("tableStudio.colMenu.sigNegLogHint")}
                    </p>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}

          {activeMenuHeader.ratioHint ? (
            <p className="dq-col-menu__hint">{t("tableStudio.colMenu.ratioHint")}</p>
          ) : null}
          {activeMenuHeader.logBlocked ? (
            <p className="dq-col-menu__hint">{t("tableStudio.colMenu.logBlockedHint")}</p>
          ) : null}

          <div className="dq-col-menu__grid">
            <label className="dq-field-label">
              <span>{t("tableStudio.colMenu.roleLabel")}</span>
              <select
                className="dq-select dq-select--compact"
                value={
                  activeMenuColSpec.role === "heat" || activeMenuColSpec.role === "bar"
                    ? "normal"
                    : activeMenuColSpec.role
                }
                onChange={(e) => {
                  const nextRole = e.target.value as ColumnRole;
                  commit((draft) => {
                    const c = draft.structure.columns.find(
                      (x) => x.id === activeMenuColSpec.id,
                    );
                    if (!c) return;
                    c.role = nextRole;
                    if (nextRole === "part") {
                      draft.structure.partBy = c.id;
                      setOpenMenuColId(null);
                    } else if (draft.structure.partBy === c.id) {
                      draft.structure.partBy = null;
                    }
                    if (nextRole === "sig" && !draft.structure.sig.sourceId) {
                      draft.structure.sig.sourceId = c.id;
                      draft.structure.sig.targetIds = [c.id];
                    }
                  });
                }}
              >
                {SEMANTIC_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t(`tableStudio.roles.${r}`)}
                  </option>
                ))}
              </select>
            </label>

            <label className="dq-field-label">
              <span>{t("tableStudio.colMenu.precisionLabel")}</span>
              <select
                className="dq-select dq-select--compact"
                value={String(activeMenuColSpec.precision)}
                disabled={
                  activeMenuColSpec.role === "sig" || activeMenuColSpec.role === "count"
                }
                onChange={(e) => {
                  const val = e.target.value;
                  const nextPrec: Precision =
                    val === "auto" ? "auto" : (Number(val) as 0 | 1 | 2 | 3);
                  commit((draft) => {
                    const c = draft.structure.columns.find(
                      (x) => x.id === activeMenuColSpec.id,
                    );
                    if (c) c.precision = nextPrec;
                  });
                }}
              >
                {PRECISIONS.map((p) => (
                  <option key={String(p)} value={String(p)}>
                    {p === "auto"
                      ? t("tableStudio.precisions.auto")
                      : t(`tableStudio.precisions.d${p}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="dq-field-label">
            <span>{t("tableStudio.colMenu.unitLabel")}</span>
            <input
              type="text"
              className="dq-input dq-input--compact"
              value={menuUnitDraft}
              placeholder={t("tableStudio.colMenu.unitPlaceholder")}
              onChange={(e) => setMenuUnitDraft(e.target.value)}
              onBlur={() => {
                if (menuUnitDraft !== activeMenuColSpec.unit) {
                  commit((draft) => {
                    const c = draft.structure.columns.find(
                      (x) => x.id === activeMenuColSpec.id,
                    );
                    if (c) c.unit = menuUnitDraft.trim();
                  });
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              }}
            />
          </label>

          <div className="dq-col-menu__row-btns">
            <button
              type="button"
              className="dq-btn dq-btn--xs"
              aria-pressed={activeMenuHeader.sortDir === "asc"}
              onClick={() =>
                commit((draft) => {
                  draft.structure.sort = [
                    { columnId: activeMenuColSpec.id, dir: "asc" },
                  ];
                })
              }
            >
              <ArrowUp size={11} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.colMenu.sortAsc")}</span>
            </button>
            <button
              type="button"
              className="dq-btn dq-btn--xs"
              aria-pressed={activeMenuHeader.sortDir === "desc"}
              onClick={() =>
                commit((draft) => {
                  draft.structure.sort = [
                    { columnId: activeMenuColSpec.id, dir: "desc" },
                  ];
                })
              }
            >
              <ArrowDown size={11} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.colMenu.sortDesc")}</span>
            </button>
            {activeMenuHeader.sortDir ? (
              <button
                type="button"
                className="dq-btn dq-btn--ghost dq-btn--xs"
                onClick={() =>
                  commit((draft) => {
                    draft.structure.sort = [];
                  })
                }
              >
                {t("tableStudio.colMenu.sortClear")}
              </button>
            ) : null}
          </div>

          <div className="dq-col-menu__row-btns">
            <button
              type="button"
              className="dq-btn dq-btn--xs"
              disabled={activeMenuVisIdx <= 0}
              onClick={() => moveHeaderStep(activeMenuHeader.colId, -1)}
            >
              <ArrowLeft size={11} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.colMenu.moveLeft")}</span>
            </button>
            <button
              type="button"
              className="dq-btn dq-btn--xs"
              disabled={activeMenuVisIdx >= model.headers.length - 1}
              onClick={() => moveHeaderStep(activeMenuHeader.colId, 1)}
            >
              <span>{t("tableStudio.colMenu.moveRight")}</span>
              <ArrowRight size={11} strokeWidth={1.6} aria-hidden="true" />
            </button>
          </div>

          <div className="dq-popover-divider" />

          {activeMenuHeader.isMerged ? (
            <button
              type="button"
              className="dq-popover-item"
              onClick={() => {
                commit((draft) => {
                  draft.structure.merges = draft.structure.merges.filter(
                    (m) => m.columnIds[0] !== activeMenuColSpec.id,
                  );
                });
                setOpenMenuColId(null);
              }}
            >
              <span>{t("tableStudio.colMenu.unmerge")}</span>
            </button>
          ) : activeMenuVisIdx < model.headers.length - 1 ? (
            <>
              <button
                type="button"
                className="dq-popover-item"
                onClick={() => {
                  const rightHdr = model.headers[activeMenuVisIdx + 1];
                  if (!rightHdr) return;
                  commit((draft) => {
                    draft.structure.merges.push({
                      id: `mg_${Date.now()}`,
                      columnIds: [activeMenuColSpec.id, rightHdr.colId],
                      pattern: "paren",
                    });
                  });
                  setOpenMenuColId(null);
                }}
              >
                <span>{t("tableStudio.colMenu.mergeRightParen")}</span>
              </button>
              <button
                type="button"
                className="dq-popover-item"
                onClick={() => {
                  const rightHdr = model.headers[activeMenuVisIdx + 1];
                  if (!rightHdr) return;
                  commit((draft) => {
                    draft.structure.merges.push({
                      id: `mg_${Date.now()}`,
                      columnIds: [activeMenuColSpec.id, rightHdr.colId],
                      pattern: "plusminus",
                    });
                  });
                  setOpenMenuColId(null);
                }}
              >
                <span>{t("tableStudio.colMenu.mergeRightPm")}</span>
              </button>
              {activeMenuVisIdx < model.headers.length - 2 ? (
                <button
                  type="button"
                  className="dq-popover-item"
                  onClick={() => {
                    const h1 = model.headers[activeMenuVisIdx + 1];
                    const h2 = model.headers[activeMenuVisIdx + 2];
                    if (!h1 || !h2) return;
                    commit((draft) => {
                      draft.structure.merges.push({
                        id: `mg_${Date.now()}`,
                        columnIds: [activeMenuColSpec.id, h1.colId, h2.colId],
                        pattern: "ci",
                      });
                    });
                    setOpenMenuColId(null);
                  }}
                >
                  <span>{t("tableStudio.colMenu.mergeRightCi")}</span>
                </button>
              ) : null}

              {showMenuSpannerInput ? (
                <div className="dq-struct-inline-adder">
                  <input
                    type="text"
                    className="dq-input dq-input--compact"
                    value={menuSpannerInput}
                    placeholder={t("tableStudio.canvas.spannerPromptPlaceholder")}
                    autoFocus
                    onChange={(e) => setMenuSpannerInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        const rightHdr = model.headers[activeMenuVisIdx + 1];
                        if (!rightHdr) return;
                        commit((draft) => {
                          draft.structure.spanners.push({
                            id: `sp_${Date.now()}`,
                            label: menuSpannerInput.trim() || "Group",
                            columnIds: [
                              ...activeMenuHeader.memberColIds,
                              ...rightHdr.memberColIds,
                            ],
                          });
                        });
                        setOpenMenuColId(null);
                      }
                    }}
                  />
                </div>
              ) : (
                <button
                  type="button"
                  className="dq-popover-item"
                  onClick={() => setShowMenuSpannerInput(true)}
                >
                  <span>{t("tableStudio.colMenu.spannerRight")}</span>
                </button>
              )}
            </>
          ) : null}

          <button
            type="button"
            className="dq-popover-item"
            onClick={() => {
              commit((draft) => {
                draft.structure.sig.sourceId = activeMenuColSpec.id;
                const c = draft.structure.columns.find((x) => x.id === activeMenuColSpec.id);
                if (c) c.role = "sig";
                if (!draft.structure.sig.targetIds.includes(activeMenuColSpec.id)) {
                  draft.structure.sig.targetIds.push(activeMenuColSpec.id);
                }
              });
              setOpenMenuColId(null);
            }}
          >
            <span>{t("tableStudio.colMenu.setSigSource")}</span>
          </button>

          <button
            type="button"
            className="dq-popover-item"
            onClick={() => {
              commit((draft) => {
                for (const mid of activeMenuHeader.memberColIds) {
                  const c = draft.structure.columns.find((x) => x.id === mid);
                  if (c) c.hidden = true;
                }
              });
              setOpenMenuColId(null);
            }}
          >
            <span>{t("tableStudio.colMenu.hideCol")}</span>
          </button>
        </div>
      ) : null}
    </main>
  );
}
