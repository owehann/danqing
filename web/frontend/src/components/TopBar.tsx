import React, { useEffect, useId, useRef } from "react";
import {
  Check,
  ChevronDown,
  Eye,
  HelpCircle,
  Palette,
  Plus,
  Redo2,
  Undo2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";
import { BrandMark } from "./BrandMark";
import { tetherPopoverFallback } from "./ModalDialog";

export function TopBar(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const pageMode = useStudioStore((s) => s.pageMode);
  const figure = useStudioStore((s) => s.figure);
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

  const toolbarRef = useRef<HTMLDivElement | null>(null);
  const figTriggerRef = useRef<HTMLButtonElement | null>(null);
  const figPopoverRef = useRef<HTMLDivElement | null>(null);
  const addFileInputRef = useRef<HTMLInputElement | null>(null);
  const figPopoverId = useId();
  const addFileInputId = useId();

  const isZh = i18n.language.startsWith("zh");

  // Roving tabindex fallback when native focusgroup is unsupported
  useEffect(() => {
    const bar = toolbarRef.current;
    if (!bar) return;
    if (typeof HTMLElement !== "undefined" && "focusGroup" in HTMLElement.prototype) return;

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
  }, [pageMode, figure?.figure_id]);

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
  }, [pageMode, figure?.figure_id]);

  const closeFigPopover = (): void => {
    const pop = figPopoverRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    pop?.hidePopover?.();
  };

  const toolbarFocusGroupAttrs = { focusgroup: "toolbar wrap" } as Record<string, unknown>;
  const popoverTriggerAttrs = { popovertarget: figPopoverId } as Record<string, unknown>;
  const popoverPanelAttrs = { popover: "auto" } as Record<string, unknown>;

  return (
    <header className="dq-topbar">
      <div className="dq-topbar__left">
        <button type="button" className="dq-brand-btn" onClick={goToLanding}>
          <BrandMark variant="mark" size={20} className="dq-brand-mark" />
          <span>{t("app.brand")}</span>
        </button>

        {pageMode === "editor" && figure ? (
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
                accept=".pdf,.svg,image/*"
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
      </div>

      {pageMode === "editor" && figure ? (
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
        {pageMode === "editor" && figure ? (
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

        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("topbar.shortcuts")}
          title={t("topbar.shortcuts")}
          onClick={() => openDialog("shortcuts")}
        >
          <HelpCircle size={16} strokeWidth={1.5} aria-hidden="true" />
        </button>

        <div className="dq-lang-switch">
          <button
            type="button"
            aria-pressed={!isZh}
            onClick={() => void i18n.changeLanguage("en")}
          >
            {t("topbar.langEn")}
          </button>
          <button
            type="button"
            aria-pressed={isZh}
            onClick={() => void i18n.changeLanguage("zh")}
          >
            {t("topbar.langZh")}
          </button>
        </div>

        {pageMode === "editor" && figure ? (
          <button
            type="button"
            className="dq-btn dq-btn--primary"
            onClick={() => openDialog("export")}
          >
            {t("topbar.export")}
          </button>
        ) : null}
      </div>
    </header>
  );
}
