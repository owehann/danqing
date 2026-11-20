import React, { useEffect, useId, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ClipboardPaste,
  Copy,
  Eye,
  Grid,
  HelpCircle,
  Home,
  LayoutGrid,
  MoreHorizontal,
  Palette,
  Plus,
  Redo2,
  SlidersHorizontal,
  Table2,
  Undo2,
  Upload,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLayoutStudioStore } from "../layout/layoutStore";
import { useStudioStore } from "../store";
import {
  copyRichTableToClipboard,
  formatLiveStatusMessage,
} from "../table/clipboardCopy";
import {
  buildClipboardTsv,
  buildStandaloneStyledHtml,
} from "../table/exporters";
import { buildModel } from "../table/pipeline";
import { useTableStudioStore } from "../table/tableStore";
import { BrandMark } from "./BrandMark";
import { tetherPopoverFallback } from "./ModalDialog";

export function TopBar(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const studioMode = useStudioStore((s) => s.studioMode);
  const setStudioMode = useStudioStore((s) => s.setStudioMode);
  const pageMode = useStudioStore((s) => s.pageMode);
  const figure = useStudioStore((s) => s.figure);
  const catalogPalettes = useStudioStore((s) => s.palettes);
  const sessionFigures = useStudioStore((s) => s.sessionFigures);
  const isComparingOriginal = useStudioStore((s) => s.isComparingOriginal);
  const palettesDrawerOpen = useStudioStore((s) => s.palettesDrawerOpen);

  const goToLanding = useStudioStore((s) => s.goToLanding);
  const switchFigure = useStudioStore((s) => s.switchFigure);
  const uploadFile = useStudioStore((s) => s.uploadFile);
  const setKeepConsistent = useStudioStore((s) => s.setKeepConsistent);
  const undo = useStudioStore((s) => s.undo);
  const redo = useStudioStore((s) => s.redo);
  const setComparingOriginal = useStudioStore((s) => s.setComparingOriginal);
  const setPalettesDrawerOpen = useStudioStore((s) => s.setPalettesDrawerOpen);
  const openDialog = useStudioStore((s) => s.openDialog);

  // Table Studio v2 state
  const tablePageMode = useTableStudioStore((s) => s.tablePageMode);
  const tableSamples = useTableStudioStore((s) => s.samples);
  const tableDocs = useTableStudioStore((s) => s.docs);
  const pendingReuploads = useTableStudioStore((s) => s.pendingReuploads);
  const tableOrder = useTableStudioStore((s) => s.order);
  const activeTableId = useTableStudioStore((s) => s.activeId);
  const historyPast = useTableStudioStore((s) => s.historyPast);
  const historyFuture = useTableStudioStore((s) => s.historyFuture);
  const isComparingRaw = useTableStudioStore((s) => s.isComparingRaw);
  const styleDrawerOpen = useTableStudioStore((s) => s.styleDrawerOpen);

  const goToTableLanding = useTableStudioStore((s) => s.goToTableLanding);
  const switchDoc = useTableStudioStore((s) => s.switchDoc);
  const removeDoc = useTableStudioStore((s) => s.removeDoc);
  const tableUndo = useTableStudioStore((s) => s.undo);
  const tableRedo = useTableStudioStore((s) => s.redo);
  const setComparingRaw = useTableStudioStore((s) => s.setComparingRaw);
  const setTableModal = useTableStudioStore((s) => s.setActiveModal);
  const setStyleDrawerOpen = useTableStudioStore((s) => s.setStyleDrawerOpen);

  const activeTableDoc = activeTableId ? tableDocs[activeTableId] : undefined;
  const canTableUndo = (historyPast[activeTableId]?.length ?? 0) > 0;
  const canTableRedo = (historyFuture[activeTableId]?.length ?? 0) > 0;

  // Layout Studio state
  const layoutPageMode = useLayoutStudioStore((s) => s.layoutPageMode);
  const layoutComposed = useLayoutStudioStore((s) => s.composed);
  const layoutSelectedIds = useLayoutStudioStore((s) => s.selectedIds);
  const layoutComparingNaive = useLayoutStudioStore((s) => s.isComparingNaive);
  const layoutShowGuides = useLayoutStudioStore((s) => s.showGuides);
  const layoutInspectorOpen = useLayoutStudioStore((s) => s.inspectorDrawerOpen);
  const layoutHandoffBusy = useLayoutStudioStore((s) => s.handoffBusy);
  const goToLayoutLanding = useLayoutStudioStore((s) => s.goToLayoutLanding);
  const setLayoutComparingNaive = useLayoutStudioStore((s) => s.setComparingNaive);
  const setLayoutShowGuides = useLayoutStudioStore((s) => s.setShowGuides);
  const setLayoutInspectorOpen = useLayoutStudioStore((s) => s.setInspectorDrawerOpen);
  const setLayoutExportOpen = useLayoutStudioStore((s) => s.setExportModalOpen);
  const exportHandoffSvgFile = useLayoutStudioStore((s) => s.exportHandoffSvgFile);
  const uploadLayoutFiles = useLayoutStudioStore((s) => s.uploadLayoutFiles);
  const layoutAddInputRef = useRef<HTMLInputElement | null>(null);
  const layoutAddInputId = useId();

  const toolbarRef = useRef<HTMLDivElement | null>(null);
  const figTriggerRef = useRef<HTMLButtonElement | null>(null);
  const figPopoverRef = useRef<HTMLDivElement | null>(null);
  const addFileInputRef = useRef<HTMLInputElement | null>(null);

  const tblTriggerRef = useRef<HTMLButtonElement | null>(null);
  const tblPopoverRef = useRef<HTMLDivElement | null>(null);
  const tblFileInputRef = useRef<HTMLInputElement | null>(null);

  const exportSplitTriggerRef = useRef<HTMLButtonElement | null>(null);
  const exportSplitPopoverRef = useRef<HTMLDivElement | null>(null);
  const moreTriggerRef = useRef<HTMLButtonElement | null>(null);
  const morePopoverRef = useRef<HTMLDivElement | null>(null);

  const compareDownTsRef = useRef<number>(0);
  const comparePointerHeldRef = useRef<boolean>(false);
  const wasStickyCompareRef = useRef<boolean>(false);

  const figPopoverId = useId();
  const addFileInputId = useId();
  const tblPopoverId = useId();
  const tblFileInputId = useId();
  const exportSplitPopoverId = useId();
  const morePopoverId = useId();

  const isZh = i18n.language.startsWith("zh");
  const langKey: "en" | "zh" = isZh ? "zh" : "en";

  const [topCopyState, setTopCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [topCopyMsg, setTopCopyMsg] = useState("");
  const topCopyTimerRef = useRef<number | null>(null);

  const supportsFocusGroup = false;

  // Roving tabindex fallback when native focusgroup is unsupported
  useEffect(() => {
    const bar = toolbarRef.current;
    if (!bar || supportsFocusGroup) return;

    const getItems = (): HTMLButtonElement[] =>
      Array.from(bar.querySelectorAll<HTMLButtonElement>("button"));

    const initItems = getItems();
    initItems.forEach((b, idx) => {
      b.tabIndex = idx === 0 ? 0 : -1;
    });

    const onFocusIn = (ev: FocusEvent): void => {
      const target = ev.target as HTMLButtonElement | null;
      const items = getItems();
      if (target && items.includes(target)) {
        items.forEach((b) => {
          b.tabIndex = b === target ? 0 : -1;
        });
      }
    };

    const onKeyDown = (ev: KeyboardEvent): void => {
      const items = getItems();
      if (items.length === 0) return;
      const curIdx = Math.max(0, items.indexOf(document.activeElement as HTMLButtonElement));
      const rtl = getComputedStyle(bar).direction === "rtl";
      let nextIdx: number | null = null;
      if (ev.key === "ArrowRight") {
        nextIdx = (curIdx + (rtl ? -1 : 1) + items.length) % items.length;
      } else if (ev.key === "ArrowLeft") {
        nextIdx = (curIdx + (rtl ? 1 : -1) + items.length) % items.length;
      } else if (ev.key === "Home") {
        nextIdx = 0;
      } else if (ev.key === "End") {
        nextIdx = items.length - 1;
      }
      if (nextIdx !== null) {
        ev.preventDefault();
        items.forEach((b, idx) => {
          b.tabIndex = idx === nextIdx ? 0 : -1;
        });
        items[nextIdx]?.focus();
      }
    };

    bar.addEventListener("focusin", onFocusIn);
    bar.addEventListener("keydown", onKeyDown);
    return () => {
      bar.removeEventListener("focusin", onFocusIn);
      bar.removeEventListener("keydown", onKeyDown);
    };
  }, [studioMode, pageMode, figure?.figure_id, supportsFocusGroup]);

  // Tether figure switcher popover when CSS Anchor Positioning is unsupported
  useEffect(() => {
    const pop = figPopoverRef.current;
    if (!pop) return;
    const onToggle = (ev: Event): void => {
      const te = ev as ToggleEvent;
      if (te.newState === "open") {
        tetherPopoverFallback(pop, figTriggerRef.current, false);
      }
    };
    pop.addEventListener("toggle", onToggle);
    return () => pop.removeEventListener("toggle", onToggle);
  }, [studioMode, pageMode, figure?.figure_id]);

  useEffect(() => {
    const pop = tblPopoverRef.current;
    if (!pop) return;
    const onToggle = (ev: Event): void => {
      const te = ev as ToggleEvent;
      if (te.newState === "open") {
        tetherPopoverFallback(pop, tblTriggerRef.current, false);
      }
    };
    pop.addEventListener("toggle", onToggle);
    return () => pop.removeEventListener("toggle", onToggle);
  }, [studioMode, activeTableId]);

  useEffect(() => {
    const pop = exportSplitPopoverRef.current;
    if (!pop) return;
    const onToggle = (ev: Event): void => {
      const te = ev as ToggleEvent;
      if (te.newState === "open") {
        tetherPopoverFallback(pop, exportSplitTriggerRef.current, true);
      }
    };
    pop.addEventListener("toggle", onToggle);
    return () => pop.removeEventListener("toggle", onToggle);
  }, [studioMode, activeTableId]);

  useEffect(() => {
    const pop = morePopoverRef.current;
    if (!pop) return;
    const onToggle = (ev: Event): void => {
      const te = ev as ToggleEvent;
      if (te.newState === "open") {
        tetherPopoverFallback(pop, moreTriggerRef.current, true);
      }
    };
    pop.addEventListener("toggle", onToggle);
    return () => pop.removeEventListener("toggle", onToggle);
  }, []);

  const closeMorePopover = (): void => {
    const pop = morePopoverRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    pop?.hidePopover?.();
  };

  const closeFigPopover = (): void => {
    const pop = figPopoverRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    pop?.hidePopover?.();
  };

  const closeTblPopover = (): void => {
    const pop = tblPopoverRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    pop?.hidePopover?.();
  };

  const closeExportSplitPopover = (): void => {
    const pop = exportSplitPopoverRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    pop?.hidePopover?.();
  };

  const getDocDisplayName = (sampleId: string | undefined, filename: string): string => {
    if (sampleId) {
      const found = tableSamples.find((s) => s.id === sampleId);
      if (found) return isZh ? found.title_zh : found.title_en;
    }
    return filename;
  };

  const activeDocLabel = activeTableDoc
    ? getDocDisplayName(activeTableDoc.raw.sampleId, activeTableDoc.raw.source.filename)
    : "";

  const handleTopCopyRichTable = async (): Promise<void> => {
    if (!activeTableDoc) return;
    const model = buildModel(activeTableDoc, langKey, catalogPalettes);
    const ok = await copyRichTableToClipboard(
      buildStandaloneStyledHtml(activeTableDoc, model),
      buildClipboardTsv(model),
    );
    if (topCopyTimerRef.current !== null) window.clearTimeout(topCopyTimerRef.current);
    setTopCopyState(ok ? "copied" : "failed");
    setTopCopyMsg(
      formatLiveStatusMessage(
        ok ? t("tableStudio.copy.copiedToast") : t("tableStudio.copy.failedToast"),
      ),
    );
    topCopyTimerRef.current = window.setTimeout(() => {
      setTopCopyState("idle");
      setTopCopyMsg("");
    }, 2200);
  };

  const handleTopSendLayoutToFigure = async (): Promise<void> => {
    const file = await exportHandoffSvgFile();
    if (!file) return;
    setLayoutExportOpen(false);
    setStudioMode("figure");
    await uploadFile(file);
  };

  const toolbarFocusGroupAttrs = supportsFocusGroup
    ? ({ focusgroup: "toolbar wrap" } as Record<string, unknown>)
    : {};
  const popoverTriggerAttrs = { popovertarget: figPopoverId } as Record<string, unknown>;
  const tblPopoverTriggerAttrs = { popovertarget: tblPopoverId } as Record<string, unknown>;
  const exportSplitTriggerAttrs = { popovertarget: exportSplitPopoverId } as Record<string, unknown>;
  const morePopoverTriggerAttrs = { popovertarget: morePopoverId } as Record<string, unknown>;
  const popoverPanelAttrs = { popover: "auto" } as Record<string, unknown>;

  return (
    <header className="dq-topbar">
      <div className="dq-topbar__left">
        <button
          type="button"
          className="dq-brand-btn"
          onClick={() => {
            if (studioMode === "layout") {
              goToLayoutLanding();
            } else if (studioMode === "table") {
              goToTableLanding();
            } else {
              goToLanding();
            }
          }}
        >
          <BrandMark variant="mark" size={20} className="dq-brand-mark" />
          <span>{t("app.brand")}</span>
        </button>

        <div
          className="dq-mode-switch"
          role="group"
          aria-label={t("tableStudio.a11y.modeSwitcher")}
        >
          <button
            type="button"
            className="dq-mode-switch__btn"
            aria-pressed={studioMode === "layout"}
            onClick={() => setStudioMode("layout")}
          >
            <LayoutGrid size={13} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("tableStudio.mode.layout")}</span>
          </button>
          <button
            type="button"
            className="dq-mode-switch__btn"
            aria-pressed={studioMode === "figure"}
            onClick={() => setStudioMode("figure")}
          >
            <Palette size={13} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("tableStudio.mode.figure")}</span>
          </button>
          <button
            type="button"
            className="dq-mode-switch__btn"
            aria-pressed={studioMode === "table"}
            onClick={() => setStudioMode("table")}
          >
            <Table2 size={13} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("tableStudio.mode.table")}</span>
          </button>
        </div>

        {studioMode === "layout" && layoutPageMode === "editor" ? (
          <>
            <span className="dq-fig-trigger" style={{ cursor: "default" }}>
              <span>
                {t("layoutStudio.topbar.activeSummary", {
                  count: layoutSelectedIds.length,
                  w: layoutComposed?.page_width_mm ?? 183,
                  h: layoutComposed?.page_height_mm ?? 166,
                })}
              </span>
            </span>
            <label htmlFor={layoutAddInputId} className="visually-hidden">
              {t("layoutStudio.topbar.addPanels")}
            </label>
            <input
              ref={layoutAddInputRef}
              id={layoutAddInputId}
              type="file"
              multiple
              accept=".pdf,.svg,.png,.jpg,.jpeg,.tif,.tiff,.webp"
              className="visually-hidden"
              onChange={(e) => {
                if (e.target.files?.length) {
                  void uploadLayoutFiles(e.target.files);
                }
                e.currentTarget.value = "";
              }}
            />
            <button
              type="button"
              className="dq-btn dq-topbar-responsive-btn"
              onClick={() => layoutAddInputRef.current?.click()}
            >
              <Plus size={14} strokeWidth={1.6} aria-hidden="true" />
              <span className="dq-topbar-btn-label">{t("layoutStudio.topbar.addPanels")}</span>
            </button>
          </>
        ) : null}

        {studioMode === "figure" && pageMode === "editor" && figure ? (
          <>
            <button
              ref={figTriggerRef}
              type="button"
              className="dq-fig-trigger"
              aria-label={`${t("a11y.figureSwitcher")}: ${figure.filename}`}
              {...popoverTriggerAttrs}
            >
              <span>{figure.filename}</span>
              <ChevronDown size={14} strokeWidth={1.5} aria-hidden="true" />
            </button>

            <div
              ref={figPopoverRef}
              id={figPopoverId}
              className="dq-popover"
              {...popoverPanelAttrs}
            >
              {sessionFigures.map((sf) => (
                <button
                  key={sf.figure_id}
                  type="button"
                  className="dq-popover-item"
                  onClick={() => {
                    closeFigPopover();
                    if (sf.figure_id !== figure.figure_id) {
                      void switchFigure(sf.figure_id);
                    }
                  }}
                >
                  <span>{sf.filename}</span>
                  {sf.figure_id === figure.figure_id ? (
                    <Check size={14} strokeWidth={1.5} aria-hidden="true" />
                  ) : null}
                </button>
              ))}
              <div className="dq-popover-divider" />
              <label className="dq-popover-check">
                <input
                  type="checkbox"
                  checked={figure.keep_consistent}
                  onChange={(e) => void setKeepConsistent(e.target.checked)}
                />
                <span>{t("topbar.consistentAcrossFigures")}</span>
              </label>
              <div className="dq-popover-divider" />
              <label htmlFor={addFileInputId} className="visually-hidden">
                {t("topbar.addFigure")}
              </label>
              <input
                ref={addFileInputRef}
                id={addFileInputId}
                type="file"
                accept=".pdf,.svg,.csv,.tsv,.txt,.xlsx,.xls,image/*"
                className="visually-hidden"
                onChange={(e) => {
                  const files = e.target.files;
                  if (files && files.length > 0) {
                    closeFigPopover();
                    void uploadFile(files[0]);
                  }
                  e.currentTarget.value = "";
                }}
              />
              <button
                type="button"
                className="dq-popover-item"
                onClick={() => addFileInputRef.current?.click()}
              >
                <span>{t("topbar.addFigure")}</span>
                <Plus size={14} strokeWidth={1.5} aria-hidden="true" />
              </button>
            </div>
          </>
        ) : null}

        {studioMode === "table" && tablePageMode === "editor" && activeTableDoc ? (
          <>
            <button
              ref={tblTriggerRef}
              type="button"
              className="dq-fig-trigger dq-tbl-trigger"
              aria-label={`${t("tableStudio.topbar.datasetSwitcher")}: ${activeDocLabel}`}
              title={activeDocLabel}
              {...tblPopoverTriggerAttrs}
            >
              <span className="dq-tbl-trigger__name">{activeDocLabel}</span>
              <ChevronDown size={14} strokeWidth={1.5} aria-hidden="true" />
            </button>

            <label htmlFor={tblFileInputId} className="visually-hidden">
              {t("tableStudio.topbar.uploadMenu")}
            </label>
            <input
              ref={tblFileInputRef}
              id={tblFileInputId}
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.pdf,.svg"
              className="visually-hidden"
              onChange={(e) => {
                const files = e.target.files;
                if (files && files.length > 0) {
                  closeTblPopover();
                  void uploadFile(files[0]);
                }
                e.currentTarget.value = "";
              }}
            />

            <div
              ref={tblPopoverRef}
              id={tblPopoverId}
              className="dq-popover dq-popover--wide"
              {...popoverPanelAttrs}
            >
              {tableOrder.map((docId) => {
                const docItem = tableDocs[docId];
                const pendingMeta = pendingReuploads[docId];
                if (!docItem && !pendingMeta) return null;
                const itemLabel = docItem
                  ? getDocDisplayName(docItem.raw.sampleId, docItem.raw.source.filename)
                  : getDocDisplayName(pendingMeta.sampleId, pendingMeta.filename);
                const isActive = docId === activeTableId;

                return (
                  <div key={docId} className="dq-popover-doc-row">
                    <button
                      type="button"
                      className="dq-popover-item dq-popover-doc-row__main"
                      onClick={() => {
                        closeTblPopover();
                        if (docItem) {
                          switchDoc(docId);
                        } else {
                          tblFileInputRef.current?.click();
                        }
                      }}
                    >
                      <span className="dq-popover-doc-row__name">{itemLabel}</span>
                      {!docItem ? (
                        <span className="dq-reupload-tag">
                          ({t("tableStudio.topbar.reuploadTag")})
                        </span>
                      ) : isActive ? (
                        <Check size={14} strokeWidth={1.5} aria-hidden="true" />
                      ) : null}
                    </button>
                    <button
                      type="button"
                      className="dq-btn dq-btn--ghost dq-btn--icon dq-popover-doc-row__rm"
                      aria-label={t("tableStudio.topbar.removeDoc", { name: itemLabel })}
                      title={t("tableStudio.topbar.removeDoc", { name: itemLabel })}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeDoc(docId);
                      }}
                    >
                      <X size={13} strokeWidth={1.6} aria-hidden="true" />
                    </button>
                  </div>
                );
              })}

              <div className="dq-popover-divider" />

              <button
                type="button"
                className="dq-popover-item"
                onClick={() => {
                  closeTblPopover();
                  tblFileInputRef.current?.click();
                }}
              >
                <span>{t("tableStudio.topbar.uploadMenu")}</span>
                <Upload size={14} strokeWidth={1.5} aria-hidden="true" />
              </button>

              <button
                type="button"
                className="dq-popover-item"
                onClick={() => {
                  closeTblPopover();
                  setTableModal("paste");
                }}
              >
                <span>{t("tableStudio.topbar.pasteMenu")}</span>
                <ClipboardPaste size={14} strokeWidth={1.5} aria-hidden="true" />
              </button>

              <button
                type="button"
                className="dq-popover-item"
                onClick={() => {
                  closeTblPopover();
                  goToTableLanding();
                }}
              >
                <span>{t("tableStudio.topbar.backHome")}</span>
                <Home size={14} strokeWidth={1.5} aria-hidden="true" />
              </button>
            </div>
          </>
        ) : null}
      </div>

      {studioMode === "figure" && pageMode === "editor" && figure ? (
        <div
          ref={toolbarRef}
          role="toolbar"
          aria-label={t("a11y.editorToolbar")}
          className="dq-toolbar"
          {...toolbarFocusGroupAttrs}
        >
          <div role="group" aria-label={t("a11y.historyGroup")} className="dq-toolbar__group">
            <button
              type="button"
              className="dq-btn dq-btn--icon"
              aria-label={t("topbar.undo")}
              title={t("topbar.undo")}
              aria-disabled={!figure.can_undo}
              onClick={() => {
                if (!figure.can_undo) return;
                void undo();
              }}
            >
              <Undo2 size={16} strokeWidth={1.5} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="dq-btn dq-btn--icon"
              aria-label={t("topbar.redo")}
              title={t("topbar.redo")}
              aria-disabled={!figure.can_redo}
              onClick={() => {
                if (!figure.can_redo) return;
                void redo();
              }}
            >
              <Redo2 size={16} strokeWidth={1.5} aria-hidden="true" />
            </button>
          </div>

          <span role="separator" aria-orientation="vertical" className="dq-toolbar__sep" />

          <div role="group" aria-label={t("a11y.compareGroup")} className="dq-toolbar__group">
            <button
              type="button"
              className="dq-btn"
              aria-pressed={isComparingOriginal}
              onPointerDown={() => setComparingOriginal(true)}
              onPointerUp={() => setComparingOriginal(false)}
              onPointerLeave={() => setComparingOriginal(false)}
              onPointerCancel={() => setComparingOriginal(false)}
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  setComparingOriginal(true);
                }
              }}
              onKeyUp={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  setComparingOriginal(false);
                }
              }}
              onBlur={() => setComparingOriginal(false)}
            >
              <Eye size={15} strokeWidth={1.5} aria-hidden="true" />
              <span>{t("topbar.holdToCompare")}</span>
            </button>
          </div>
        </div>
      ) : (
        <div />
      )}

      <div className="dq-topbar__right">
        {studioMode === "layout" && layoutPageMode === "editor" ? (
          <>
            <button
              type="button"
              className="dq-btn dq-topbar-responsive-btn"
              aria-pressed={layoutShowGuides}
              onClick={() => setLayoutShowGuides(!layoutShowGuides)}
            >
              <Grid size={14} strokeWidth={1.5} aria-hidden="true" />
              <span className="dq-topbar-btn-label">{t("layoutStudio.topbar.spineGuides")}</span>
            </button>

            <button
              type="button"
              className="dq-btn dq-topbar-responsive-btn"
              aria-pressed={layoutComparingNaive}
              onClick={() => setLayoutComparingNaive(!layoutComparingNaive)}
            >
              <Eye size={15} strokeWidth={1.5} aria-hidden="true" />
              <span className="dq-topbar-btn-label">{t("layoutStudio.topbar.holdCompare")}</span>
            </button>

            <button
              type="button"
              className="dq-btn dq-drawer-trigger dq-topbar-responsive-btn"
              aria-pressed={layoutInspectorOpen}
              onClick={() => setLayoutInspectorOpen(!layoutInspectorOpen)}
            >
              <SlidersHorizontal size={14} strokeWidth={1.5} aria-hidden="true" />
              <span className="dq-topbar-btn-label">{t("layoutStudio.topbar.inspectorDrawer")}</span>
            </button>
          </>
        ) : null}

        {studioMode === "figure" && pageMode === "editor" && figure ? (
          <button
            type="button"
            className="dq-btn dq-drawer-trigger"
            aria-pressed={palettesDrawerOpen}
            onClick={() => setPalettesDrawerOpen(!palettesDrawerOpen)}
          >
            <Palette size={15} strokeWidth={1.5} aria-hidden="true" />
            <span>{t("topbar.palettesDrawer")}</span>
          </button>
        ) : null}

        {studioMode === "table" && tablePageMode === "editor" && activeTableDoc ? (
          <>
            <div role="group" aria-label={t("a11y.historyGroup")} className="dq-toolbar__group">
              <button
                type="button"
                className="dq-btn dq-btn--icon"
                aria-label={t("topbar.undo")}
                title={t("topbar.undo")}
                aria-disabled={!canTableUndo}
                onClick={() => {
                  if (!canTableUndo) return;
                  tableUndo();
                }}
              >
                <Undo2 size={15} strokeWidth={1.5} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="dq-btn dq-btn--icon"
                aria-label={t("topbar.redo")}
                title={t("topbar.redo")}
                aria-disabled={!canTableRedo}
                onClick={() => {
                  if (!canTableRedo) return;
                  tableRedo();
                }}
              >
                <Redo2 size={15} strokeWidth={1.5} aria-hidden="true" />
              </button>
            </div>

            <button
              type="button"
              className="dq-btn dq-topbar-responsive-btn"
              aria-label={t("tableStudio.topbar.holdCompare")}
              title={t("tableStudio.topbar.holdCompare")}
              aria-pressed={isComparingRaw}
              onPointerDown={() => {
                compareDownTsRef.current = performance.now();
                comparePointerHeldRef.current = true;
                wasStickyCompareRef.current = isComparingRaw;
                if (!isComparingRaw) {
                  setComparingRaw(true);
                }
              }}
              onPointerUp={() => {
                if (!comparePointerHeldRef.current) return;
                comparePointerHeldRef.current = false;
                const elapsed = performance.now() - compareDownTsRef.current;
                if (elapsed >= 180) {
                  setComparingRaw(false);
                } else if (wasStickyCompareRef.current) {
                  setComparingRaw(false);
                }
              }}
              onPointerLeave={() => {
                if (comparePointerHeldRef.current) {
                  comparePointerHeldRef.current = false;
                  setComparingRaw(false);
                }
              }}
              onPointerCancel={() => {
                if (comparePointerHeldRef.current) {
                  comparePointerHeldRef.current = false;
                  setComparingRaw(false);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  setComparingRaw(!isComparingRaw);
                }
              }}
            >
              <Eye size={15} strokeWidth={1.5} aria-hidden="true" />
              <span className="dq-topbar-btn-label">{t("tableStudio.topbar.holdCompare")}</span>
            </button>

            <span className="dq-copy-status-wrap dq-topbar-copy-standalone">
              <button
                type="button"
                className="dq-btn dq-topbar-responsive-btn"
                aria-label={t("tableStudio.copy.copyShortBtn")}
                title={t("tableStudio.copy.copyShortBtn")}
                onClick={() => void handleTopCopyRichTable()}
              >
                {topCopyState === "copied" ? (
                  <Check size={14} strokeWidth={1.8} aria-hidden="true" />
                ) : (
                  <Copy size={14} strokeWidth={1.6} aria-hidden="true" />
                )}
                <span className="dq-topbar-btn-label">{t("tableStudio.copy.copyShortBtn")}</span>
              </button>
              <span
                role="status"
                className={`dq-copy-live-bubble${
                  topCopyState !== "idle" ? " dq-copy-live-bubble--visible" : ""
                }`}
              >
                {topCopyMsg}
              </span>
            </span>

            <div className="dq-export-split-group">
              <button
                type="button"
                className="dq-btn dq-btn--primary dq-export-main-btn"
                onClick={() => setTableModal("export")}
              >
                {t("topbar.export")}
              </button>
              <button
                ref={exportSplitTriggerRef}
                type="button"
                className="dq-btn dq-btn--primary dq-export-split-caret"
                aria-label={t("tableStudio.topbar.moreExportActions")}
                title={t("tableStudio.topbar.moreExportActions")}
                {...exportSplitTriggerAttrs}
              >
                <ChevronDown size={13} strokeWidth={1.8} aria-hidden="true" />
              </button>

              <div
                ref={exportSplitPopoverRef}
                id={exportSplitPopoverId}
                className="dq-popover"
                {...popoverPanelAttrs}
              >
                <button
                  type="button"
                  className="dq-popover-item"
                  onClick={() => {
                    closeExportSplitPopover();
                    void handleTopCopyRichTable();
                  }}
                >
                  <span>{t("tableStudio.copy.copyShortBtn")}</span>
                  <Copy size={14} strokeWidth={1.5} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="dq-popover-item"
                  onClick={() => {
                    closeExportSplitPopover();
                    setTableModal("export");
                  }}
                >
                  <span>{t("topbar.export")}</span>
                </button>
              </div>
            </div>

            <button
              type="button"
              className="dq-btn dq-table-drawer-btn dq-topbar-responsive-btn"
              aria-label={t("tableStudio.topbar.styleDrawer")}
              title={t("tableStudio.topbar.styleDrawer")}
              aria-pressed={styleDrawerOpen}
              onClick={() => setStyleDrawerOpen(!styleDrawerOpen)}
            >
              <Palette size={15} strokeWidth={1.5} aria-hidden="true" />
              <span className="dq-topbar-btn-label">{t("tableStudio.topbar.styleDrawer")}</span>
            </button>
          </>
        ) : null}

        <button
          ref={moreTriggerRef}
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("topbar.moreMenu")}
          title={t("topbar.moreMenu")}
          {...morePopoverTriggerAttrs}
        >
          <MoreHorizontal size={16} strokeWidth={1.6} aria-hidden="true" />
        </button>

        <div
          ref={morePopoverRef}
          id={morePopoverId}
          className="dq-popover dq-popover--utility"
          {...popoverPanelAttrs}
        >
          <div className="dq-popover-lang-row">
            <span>{t("topbar.languageLabel")}</span>
            <div className="dq-lang-switch">
              <button
                type="button"
                aria-pressed={!isZh}
                onClick={() => {
                  void i18n.changeLanguage("en");
                  closeMorePopover();
                }}
              >
                {t("topbar.langEn")}
              </button>
              <button
                type="button"
                aria-pressed={isZh}
                onClick={() => {
                  void i18n.changeLanguage("zh");
                  closeMorePopover();
                }}
              >
                {t("topbar.langZh")}
              </button>
            </div>
          </div>

          <div className="dq-popover-divider" />

          <button
            type="button"
            className="dq-popover-item"
            onClick={() => {
              closeMorePopover();
              openDialog("shortcuts");
            }}
          >
            <span>{t("topbar.shortcuts")}</span>
            <HelpCircle size={14} strokeWidth={1.5} aria-hidden="true" />
          </button>
        </div>

        {studioMode === "layout" && layoutPageMode === "editor" ? (
          <>
            <button
              type="button"
              className="dq-btn dq-layout-handoff-topbtn dq-topbar-responsive-btn"
              disabled={!layoutComposed || layoutHandoffBusy}
              title={t("layoutStudio.topbar.sendToColorTitle")}
              onClick={() => void handleTopSendLayoutToFigure()}
            >
              <Palette size={14} strokeWidth={1.6} aria-hidden="true" />
              <span className="dq-topbar-btn-label">
                {layoutHandoffBusy
                  ? t("layoutStudio.topbar.sendingToColor")
                  : t("layoutStudio.topbar.sendToColor")}
              </span>
              <ArrowRight size={13} strokeWidth={1.7} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="dq-btn dq-btn--primary"
              onClick={() => setLayoutExportOpen(true)}
            >
              {t("layoutStudio.topbar.finishExport")}
            </button>
          </>
        ) : null}

        {studioMode === "figure" && pageMode === "editor" && figure ? (
          <>
            {figure.filename.startsWith("danqing_layout_") && layoutComposed ? (
              <button
                type="button"
                className="dq-btn dq-topbar-responsive-btn"
                title={t("layoutStudio.topbar.backToLayoutTitle")}
                onClick={() => setStudioMode("layout")}
              >
                <ArrowLeft size={13} strokeWidth={1.7} aria-hidden="true" />
                <span className="dq-topbar-btn-label">
                  {t("layoutStudio.topbar.backToLayout")}
                </span>
              </button>
            ) : null}
            <button
              type="button"
              className="dq-btn dq-btn--primary"
              onClick={() => openDialog("export")}
            >
              {t("topbar.export")}
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
}
