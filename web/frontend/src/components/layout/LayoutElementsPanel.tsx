import React, { useId, useMemo, useRef } from "react";
import { ArrowDown, ArrowUp, Lock, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { type LayoutPanelItem, useLayoutStudioStore } from "../../layout/layoutStore";

export function LayoutElementsPanel(): React.ReactElement {
  const { t } = useTranslation();
  const panels = useLayoutStudioStore((s) => s.panels);
  const selectedIds = useLayoutStudioStore((s) => s.selectedIds);
  const focusedPanelId = useLayoutStudioStore((s) => s.focusedPanelId);
  const lockedOverrides = useLayoutStudioStore((s) => s.lockedOverrides);
  const composed = useLayoutStudioStore((s) => s.composed);

  const togglePanel = useLayoutStudioStore((s) => s.togglePanel);
  const movePanelOrder = useLayoutStudioStore((s) => s.movePanelOrder);
  const selectQuickCount = useLayoutStudioStore((s) => s.selectQuickCount);
  const setFocusedPanelId = useLayoutStudioStore((s) => s.setFocusedPanelId);
  const uploadLayoutFiles = useLayoutStudioStore((s) => s.uploadLayoutFiles);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputId = useId();

  const tagMap = useMemo(() => {
    const m: Record<string, string> = {};
    composed?.slots.forEach((s) => {
      m[s.panel_id] = s.tag_label;
    });
    return m;
  }, [composed]);

  const orderedList = useMemo(() => {
    const active = selectedIds
      .map((id) => panels.find((p) => p.panel_id === id))
      .filter((x): x is LayoutPanelItem => Boolean(x));
    const inactive = panels.filter((p) => !selectedIds.includes(p.panel_id));
    return [...active, ...inactive];
  }, [panels, selectedIds]);

  const quickCounts = useMemo(() => {
    const tot = panels.length;
    if (tot <= 12) {
      return [6, 9, 10, 12].filter((c) => c <= tot);
    }
    const base = [8, 12, 16, 24].filter((c) => c < tot);
    return [...base.slice(0, 3), tot];
  }, [panels.length]);

  return (
    <aside
      className="dq-elements-panel dq-layout-left"
      aria-label={t("layoutStudio.a11y.panelsRegion")}
    >
      <div className="dq-section-head">
        <h2>
          {t("layoutStudio.left.poolHeading", {
            selected: selectedIds.length,
            total: panels.length,
          })}
        </h2>
        <div>
          <label htmlFor={fileInputId} className="visually-hidden">
            {t("layoutStudio.left.uploadMore")}
          </label>
          <input
            ref={fileInputRef}
            id={fileInputId}
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
            className="dq-btn dq-btn--ghost dq-btn--icon"
            aria-label={t("layoutStudio.left.uploadMore")}
            title={t("layoutStudio.left.uploadMore")}
            onClick={() => fileInputRef.current?.click()}
          >
            <Plus size={14} strokeWidth={1.6} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="dq-layout-quick-counts">
        {quickCounts.map((cnt) => {
          const isAll = cnt === panels.length && panels.length > 12;
          return (
            <button
              key={cnt}
              type="button"
              className="dq-btn dq-layout-count-btn"
              aria-pressed={selectedIds.length === cnt}
              onClick={() => selectQuickCount(cnt)}
            >
              {isAll
                ? t("layoutStudio.left.quickAll", { count: cnt })
                : t("layoutStudio.left.quickCount", { count: cnt })}
            </button>
          );
        })}
      </div>
      <p className="dq-layout-pool-note">{t("layoutStudio.left.capacityHint")}</p>

      <div className="dq-layout-panel-list">
        {orderedList.map((panel, poolIdx) => {
          const isChecked = selectedIds.includes(panel.panel_id);
          const idxInSel = selectedIds.indexOf(panel.panel_id);
          const isFocused = focusedPanelId === panel.panel_id;
          const isLocked = lockedOverrides[panel.panel_id] ?? panel.locked_special;
          const tag = tagMap[panel.panel_id];
          const displayLabel =
            isChecked && tag
              ? t("layoutStudio.left.panelNameTagged", { tag: tag.toUpperCase() })
              : isChecked
                ? t("layoutStudio.left.panelNameTagged", { tag: String(idxInSel + 1) })
                : t("layoutStudio.left.panelNameUntagged", { num: poolIdx + 1 });

          return (
            <div
              key={panel.panel_id}
              className={`dq-layout-item${isChecked ? " dq-layout-item--checked" : ""}${
                isFocused ? " dq-layout-item--focused" : ""
              }`}
              onClick={() => setFocusedPanelId(panel.panel_id, true)}
            >
              <div
                className="dq-layout-item__thumb"
                dangerouslySetInnerHTML={{ __html: panel.thumb_svg }}
              />

              <div className="dq-layout-item__body">
                <div className="dq-layout-item__row">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    aria-label={t("layoutStudio.left.selectAria", { title: displayLabel })}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => togglePanel(panel.panel_id)}
                  />
                  {isChecked && tag ? <span className="dq-layout-tag">{tag}</span> : null}
                  <span className="dq-layout-item__title">{displayLabel}</span>
                </div>

                <div className="dq-layout-item__sub">
                  {isLocked ? (
                    <span className="dq-layout-lock-pill">
                      <Lock size={10} strokeWidth={1.7} aria-hidden="true" />
                      <span>{t("layoutStudio.left.lockedBadge")}</span>
                    </span>
                  ) : (
                    <span className="dq-layout-item__fname">{panel.filename}</span>
                  )}
                </div>
              </div>

              {isChecked ? (
                <div className="dq-layout-item__order" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="dq-btn dq-btn--ghost dq-btn--icon dq-layout-order-btn"
                    disabled={idxInSel <= 0}
                    aria-label={t("layoutStudio.left.moveUp")}
                    title={t("layoutStudio.left.moveUp")}
                    onClick={() => movePanelOrder(panel.panel_id, -1)}
                  >
                    <ArrowUp size={12} strokeWidth={1.6} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="dq-btn dq-btn--ghost dq-btn--icon dq-layout-order-btn"
                    disabled={idxInSel < 0 || idxInSel >= selectedIds.length - 1}
                    aria-label={t("layoutStudio.left.moveDown")}
                    title={t("layoutStudio.left.moveDown")}
                    onClick={() => movePanelOrder(panel.panel_id, 1)}
                  >
                    <ArrowDown size={12} strokeWidth={1.6} aria-hidden="true" />
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
