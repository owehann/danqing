import React, { useEffect, useId, useRef, useState } from "react";
import {
  ArrowLeftRight,
  CircleDashed,
  Lock,
  MoreHorizontal,
  Star,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";
import type { FigureElement, PlainNotice } from "../types";
import { tetherPopoverFallback } from "./ModalDialog";

interface ElementRowProps {
  el: FigureElement;
  selected: boolean;
  hovered: boolean;
}

function ElementRow({ el, selected, hovered }: ElementRowProps): React.ReactElement {
  const { t, i18n } = useTranslation();
  const selectEntity = useStudioStore((s) => s.selectEntity);
  const setHoveredEntity = useStudioStore((s) => s.setHoveredEntity);
  const setElementRoles = useStudioStore((s) => s.setElementRoles);
  const toggleElementLock = useStudioStore((s) => s.toggleElementLock);
  const renameElement = useStudioStore((s) => s.renameElement);
  const splitSameName = useStudioStore((s) => s.splitSameName);
  const splitElementLayers = useStudioStore((s) => s.splitElementLayers);
  const resetElement = useStudioStore((s) => s.resetElement);

  const [editing, setEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState(el.label);
  const inputId = useId();
  const popoverId = useId();
  const moreBtnRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setDraftLabel(el.label);
  }, [el.label]);

  useEffect(() => {
    const pop = popRef.current;
    if (!pop) return;
    const onToggle = (ev: Event): void => {
      const te = ev as ToggleEvent;
      if (te.newState === "open") {
        tetherPopoverFallback(pop, moreBtnRef.current, true);
      }
    };
    pop.addEventListener("toggle", onToggle);
    return () => pop.removeEventListener("toggle", onToggle);
  }, []);

  const closeMenu = (): void => {
    const pop = popRef.current as (HTMLDivElement & { hidePopover?: () => void }) | null;
    pop?.hidePopover?.();
  };

  const commitRename = (): void => {
    setEditing(false);
    const trimmed = draftLabel.trim();
    if (trimmed && trimmed !== el.label) {
      void renameElement(el.entity_id, trimmed);
    } else {
      setDraftLabel(el.label);
    }
  };

  const canSplit = el.panels.length > 1 || el.member_group_ids.length > 1;
  const popoverTriggerAttrs = { popovertarget: popoverId } as Record<string, unknown>;
  const popoverPanelAttrs = { popover: "auto" } as Record<string, unknown>;

  return (
    <li
      className={`dq-element-row${selected ? " dq-element-row--selected" : ""}${
        hovered ? " dq-element-row--hovered" : ""
      }`}
      onMouseEnter={() => setHoveredEntity(el.entity_id, el.panels.join(", "))}
      onMouseLeave={() => setHoveredEntity(null, null)}
    >
      <span
        className="dq-swatch-chip"
        style={{
          backgroundColor: el.current_hex,
          opacity: Math.max(0.22, Math.min(1, el.alpha ?? 1)),
        }}
        title={el.current_hex}
      />

      {editing ? (
        <div style={{ flex: 1, minWidth: 0 }}>
          <label htmlFor={inputId} className="visually-hidden">
            {t("elements.rename")}
          </label>
          <input
            id={inputId}
            type="text"
            className="dq-element-rename"
            value={draftLabel}
            autoFocus
            onChange={(e) => setDraftLabel(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                commitRename();
              } else if (e.key === "Escape") {
                setDraftLabel(el.label);
                setEditing(false);
              }
            }}
          />
        </div>
      ) : (
        <button
          type="button"
          className="dq-element-main"
          title={t("elements.doubleClickRename")}
          onClick={(e) => {
            if (e.altKey) {
              void setElementRoles(
                [el.entity_id],
                el.role === "focus" ? "normal" : "focus",
              );
              return;
            }
            selectEntity(el.entity_id, e.metaKey || e.ctrlKey, e.shiftKey);
          }}
          onDoubleClick={() => setEditing(true)}
        >
          <span className="dq-element-title-line">
            <span className="dq-element-label">{el.label}</span>
            {el.role === "focus" ? (
              <span className="dq-role-icon" title={t("elements.roleFocus")}>
                <Star size={12} strokeWidth={1.8} aria-hidden="true" />
              </span>
            ) : null}
            {el.role === "background" ? (
              <span className="dq-role-icon" title={t("elements.roleBackground")}>
                <CircleDashed size={12} strokeWidth={1.8} aria-hidden="true" />
              </span>
            ) : null}
            {el.locked ? (
              <span className="dq-role-icon" title={t("elements.lockColor")}>
                <Lock size={12} strokeWidth={1.8} aria-hidden="true" />
              </span>
            ) : null}
          </span>
          {el.panels.length > 0 ? (
            <span className="dq-element-panels">{el.panels.join(", ")}</span>
          ) : null}
        </button>
      )}

      <button
        ref={moreBtnRef}
        type="button"
        className="dq-btn dq-btn--ghost dq-btn--icon"
        aria-label={`${t("elements.moreActions")}: ${el.label}`}
        title={t("elements.moreActions")}
        {...popoverTriggerAttrs}
      >
        <MoreHorizontal size={15} strokeWidth={1.5} aria-hidden="true" />
      </button>

      <div ref={popRef} id={popoverId} className="dq-popover" {...popoverPanelAttrs}>
        <button
          type="button"
          className="dq-popover-item"
          onClick={() => {
            closeMenu();
            void setElementRoles([el.entity_id], "focus");
          }}
        >
          <span>{t("elements.roleFocus")}</span>
        </button>
        <button
          type="button"
          className="dq-popover-item"
          onClick={() => {
            closeMenu();
            void setElementRoles([el.entity_id], "normal");
          }}
        >
          <span>{t("elements.roleNormal")}</span>
        </button>
        <button
          type="button"
          className="dq-popover-item"
          onClick={() => {
            closeMenu();
            void setElementRoles([el.entity_id], "background");
          }}
        >
          <span>{t("elements.roleBackground")}</span>
        </button>
        <div className="dq-popover-divider" />
        <button
          type="button"
          className="dq-popover-item"
          onClick={() => {
            closeMenu();
            void toggleElementLock(el.entity_id, !el.locked);
          }}
        >
          <span>{el.locked ? t("elements.unlockColor") : t("elements.lockColor")}</span>
        </button>
        <button
          type="button"
          className="dq-popover-item"
          onClick={() => {
            closeMenu();
            setEditing(true);
          }}
        >
          <span>{t("elements.rename")}</span>
        </button>
        {el.has_overlay_layers ? (
          <button
            type="button"
            className="dq-popover-item"
            onClick={() => {
              closeMenu();
              void splitElementLayers(el.entity_id, i18n.language);
            }}
          >
            <span>{t("elements.splitLayers")}</span>
          </button>
        ) : null}
        {canSplit ? (
          <button
            type="button"
            className="dq-popover-item"
            onClick={() => {
              closeMenu();
              void splitSameName(el.entity_id, i18n.language);
            }}
          >
            <span>{t("elements.splitSameName")}</span>
          </button>
        ) : null}
        <div className="dq-popover-divider" />
        <button
          type="button"
          className="dq-popover-item"
          onClick={() => {
            closeMenu();
            void resetElement(el.entity_id);
          }}
        >
          <span>{t("elements.resetElement")}</span>
        </button>
      </div>
    </li>
  );
}

export function ElementsPanel(): React.ReactElement | null {
  const { t } = useTranslation();
  const figure = useStudioStore((s) => s.figure);
  const targetPanels = useStudioStore((s) => s.targetPanels);
  const selectedIds = useStudioStore((s) => s.selectedIds);
  const hoveredEntityId = useStudioStore((s) => s.hoveredEntityId);
  const setTargetPanels = useStudioStore((s) => s.setTargetPanels);
  const setElementRoles = useStudioStore((s) => s.setElementRoles);
  const invertScale = useStudioStore((s) => s.invertScale);

  if (!figure) return null;

  const isPanelFiltered = targetPanels.length > 0 && figure.panels.length > 1;
  const targetSet = new Set(targetPanels);
  const visibleElements = isPanelFiltered
    ? figure.elements.filter((el) => el.panels.some((pn) => targetSet.has(pn)))
    : figure.elements;
  const visibleScales = isPanelFiltered
    ? figure.continuous_scales.filter((cs) => targetSet.has(cs.panel_id))
    : figure.continuous_scales;

  const notices = (figure.plain_notices || []).slice(0, 2);

  const renderNoticeText = (n: PlainNotice): string => {
    if (n.kind === "colorblind_hard_to_tell") {
      return t("elements.noticeColorblind", {
        count: n.count ?? 2,
        panel: n.panel ?? "Panel A",
      });
    }
    return t("elements.noticeInconsistent", {
      label: n.label ?? "",
      panelA: n.panel_a ?? "Panel A",
      panelB: n.panel_b ?? "Panel B",
    });
  };

  const handleNoticeClick = (n: PlainNotice): void => {
    if (n.entity_ids && n.entity_ids.length > 0) {
      useStudioStore.setState({ selectedIds: [...n.entity_ids] });
    }
  };

  return (
    <aside className="dq-elements-panel" aria-label={t("a11y.elementsRegion")}>
      {notices.length > 0 ? (
        <div className="dq-notices">
          {notices.map((n, idx) => (
            <button
              key={`${n.kind}-${idx}`}
              type="button"
              className="dq-notice-btn"
              onClick={() => handleNoticeClick(n)}
            >
              {renderNoticeText(n)}
            </button>
          ))}
        </div>
      ) : null}

      <div className="dq-section-head">
        <h2>{t("elements.heading")}</h2>
        {isPanelFiltered ? (
          <button
            type="button"
            className="dq-scope-tag"
            title={t("elements.showAllPanels")}
            onClick={() => setTargetPanels([])}
          >
            <span>{targetPanels.join(", ")}</span>
            <X size={11} strokeWidth={1.8} aria-hidden="true" />
          </button>
        ) : (
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>
            {visibleElements.length}
          </span>
        )}
      </div>

      {selectedIds.length > 1 ? (
        <div className="dq-batch-bar">
          <span>{t("elements.batchSelected", { count: selectedIds.length })}</span>
          <div className="dq-batch-bar__btns">
            <button
              type="button"
              className="dq-btn"
              onClick={() => void setElementRoles(selectedIds, "focus")}
            >
              {t("elements.roleFocus")}
            </button>
            <button
              type="button"
              className="dq-btn"
              onClick={() => void setElementRoles(selectedIds, "normal")}
            >
              {t("elements.roleNormal")}
            </button>
            <button
              type="button"
              className="dq-btn"
              onClick={() => void setElementRoles(selectedIds, "background")}
            >
              {t("elements.roleBackground")}
            </button>
          </div>
        </div>
      ) : null}

      <ul role="list" className="dq-element-list">
        {visibleElements.map((el) => (
          <ElementRow
            key={el.entity_id}
            el={el}
            selected={selectedIds.includes(el.entity_id)}
            hovered={hoveredEntityId === el.entity_id}
          />
        ))}
      </ul>

      {visibleScales.length > 0 ? (
        <div className="dq-sub-group">
          <div className="dq-section-head">
            <h2>{t("elements.continuousHeading")}</h2>
          </div>
          {visibleScales.map((cs) => {
            const stops =
              cs.gradient_preview_stops.length > 0
                ? cs.gradient_preview_stops
                : cs.current_stops_hex;
            const gradientCss = `linear-gradient(to right, ${stops.join(", ")})`;
            return (
              <div key={cs.scale_id} className="dq-scale-row">
                <span className="dq-scale-bar" style={{ background: gradientCss }} />
                <span className="dq-scale-title">{cs.title}</span>
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost dq-btn--icon"
                  aria-label={`${t("elements.invertScale")}: ${cs.title}`}
                  title={t("elements.invertScale")}
                  onClick={() => void invertScale(cs.scale_id)}
                >
                  <ArrowLeftRight size={14} strokeWidth={1.5} aria-hidden="true" />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}

      {figure.protected_images.length > 0 ? (
        <div className="dq-sub-group">
          <div className="dq-section-head">
            <h2>{t("elements.protectedHeading")}</h2>
          </div>
          <p className="dq-protected-note">{t("elements.protectedNote")}</p>
          {figure.protected_images.map((pi) => (
            <div key={pi.region_id} className="dq-protected-row">
              <Lock size={12} strokeWidth={1.6} aria-hidden="true" />
              <span>
                {pi.panel_id} · {pi.width_px}×{pi.height_px}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
