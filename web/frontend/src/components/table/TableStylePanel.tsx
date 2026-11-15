import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../../store";
import {
  BUILTIN_TABLE_RAMPS,
  filterContinuousCatalogPalettes,
} from "../../table/color";
import type {
  EmphasisPolicy,
  HeatScope,
  RowRhythm,
  TablePresetId,
} from "../../table/model";
import { buildModel } from "../../table/pipeline";
import { useTableStudioStore } from "../../table/tableStore";

const PRESET_IDS: TablePresetId[] = [
  "raw",
  "matrix_heatmap",
  "cns_three_line",
  "ft_editorial",
];

const HEAT_SCOPES: HeatScope[] = ["per_column", "per_part", "per_row", "global"];

const EMPHASIS_MODES: EmphasisPolicy[] = [
  "bold_star_mono",
  "accent_bold",
  "hairline_box",
  "off",
];

const RHYTHM_MODES: RowRhythm[] = ["none", "zebra", "group_breathing"];

export function TableStylePanel(): React.ReactElement | null {
  const { t, i18n } = useTranslation();
  const catalogPalettes = useStudioStore((s) => s.palettes);
  const docs = useTableStudioStore((s) => s.docs);
  const activeId = useTableStudioStore((s) => s.activeId);
  const styleDrawerOpen = useTableStudioStore((s) => s.styleDrawerOpen);
  const setStyleDrawerOpen = useTableStudioStore((s) => s.setStyleDrawerOpen);
  const commit = useTableStudioStore((s) => s.commit);

  const doc = docs[activeId];
  const isZh = i18n.language.startsWith("zh");
  const langKey: "en" | "zh" = isZh ? "zh" : "en";

  const accordionRef = useRef<HTMLDivElement | null>(null);
  const [rampSearch, setRampSearch] = useState("");
  const [customCenterText, setCustomCenterText] = useState("0");

  // Exclusive <details name="dq-style"> fallback for browsers without native Details `name` support
  useEffect(() => {
    const root = accordionRef.current;
    if (!root) return;
    if (
      typeof HTMLDetailsElement !== "undefined" &&
      Object.hasOwn(HTMLDetailsElement.prototype, "name")
    ) {
      return;
    }
    const onToggle = (ev: Event): void => {
      const opened = ev.target as HTMLDetailsElement | null;
      if (!opened || opened.tagName !== "DETAILS" || !opened.open) return;
      const group = opened.getAttribute("name");
      if (!group) return;
      root.querySelectorAll<HTMLDetailsElement>(`details[name="${group}"][open]`).forEach((el) => {
        if (el !== opened) el.open = false;
      });
    };
    root.addEventListener("toggle", onToggle, true);
    return () => root.removeEventListener("toggle", onToggle, true);
  }, []);

  const continuousCatalog = useMemo(
    () => filterContinuousCatalogPalettes(catalogPalettes),
    [catalogPalettes],
  );

  const filteredCatalog = useMemo(() => {
    const q = rampSearch.trim().toLowerCase();
    if (!q) return continuousCatalog.slice(0, 24);
    return continuousCatalog
      .filter(
        (p) =>
          p.name.en.toLowerCase().includes(q) ||
          p.name.zh.toLowerCase().includes(q) ||
          p.id.toLowerCase().includes(q),
      )
      .slice(0, 24);
  }, [continuousCatalog, rampSearch]);

  if (!doc) return null;

  const model = buildModel(doc, langKey, catalogPalettes);
  const { style, structure } = doc;
  const hasSigSource = Boolean(structure.sig.sourceId);
  const hasAnyHeatCapable = model.hasHeatColumns || model.hasActiveHeatColumns;
  const rhythmDisabled = style.preset === "matrix_heatmap";

  return (
    <aside
      aria-label={t("tableStudio.a11y.styleRegion")}
      className={`dq-right-sidebar dq-table-style-panel${
        styleDrawerOpen ? " dq-table-style-panel--open" : ""
      }`}
    >
      <div className="dq-table-drawer-head">
        <span>{t("tableStudio.topbar.styleDrawer")}</span>
        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("tableStudio.a11y.closeStyleDrawer")}
          title={t("tableStudio.a11y.closeStyleDrawer")}
          onClick={() => setStyleDrawerOpen(false)}
        >
          <X size={15} strokeWidth={1.6} aria-hidden="true" />
        </button>
      </div>

      <div ref={accordionRef} className="dq-table-style-accordion">
        {/* 1. Preset */}
        <details name="dq-style" className="dq-style-acc" open>
          <summary className="dq-style-acc__sum">
            <span>{t("tableStudio.style.secPreset")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-style-acc__body">
            <div className="dq-table-preset-list">
              {PRESET_IDS.map((pid) => (
                <button
                  key={pid}
                  type="button"
                  className="dq-table-preset-card"
                  aria-pressed={style.preset === pid}
                  onClick={() =>
                    commit((draft) => {
                      draft.style.preset = pid;
                      if (pid !== "raw" && draft.structure.stage === "raw") {
                        draft.structure.stage = "tidied";
                      }
                    })
                  }
                >
                  <span className="dq-table-preset-card__title">
                    {t(`tableStudio.style.presets.${pid}.title`)}
                  </span>
                  <span className="dq-table-preset-card__desc">
                    {t(`tableStudio.style.presets.${pid}.desc`)}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </details>

        {/* 2. Color Ramp */}
        <details name="dq-style" className="dq-style-acc">
          <summary className="dq-style-acc__sum">
            <span>{t("tableStudio.style.secRamp")}</span>
            <span className="dq-style-acc__badge">{t("tableStudio.palettes.autoContrastBadge")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-style-acc__body">
            {model.activeHueCount > 3 ? (
              <p className="dq-gentle-hue-note">
                {t("tableStudio.style.multiHueGentleNote", { count: model.activeHueCount })}
              </p>
            ) : null}

            {style.preset !== "matrix_heatmap" &&
            !model.hasActiveHeatColumns &&
            model.hasHeatColumns ? (
              <div className="dq-style-mode-hint">
                <span>{t("tableStudio.style.partialHeatNote")}</span>
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  onClick={() =>
                    commit((draft) => {
                      draft.style.preset = "matrix_heatmap";
                      if (draft.structure.stage === "raw") {
                        draft.structure.stage = "tidied";
                      }
                    })
                  }
                >
                  {t("tableStudio.style.switchToHeatmapBtn")}
                </button>
              </div>
            ) : null}

            {model.hasColumnVisualOverrides ? (
              <button
                type="button"
                className="dq-btn dq-btn--xs"
                onClick={() =>
                  commit((draft) => {
                    for (const col of draft.structure.columns) {
                      col.visual = "auto";
                      col.visualConfig = undefined;
                      if (col.role === "heat" || col.role === "bar") {
                        col.role = "normal";
                      }
                    }
                  })
                }
              >
                {t("tableStudio.style.resetColumnVisualsBtn")}
              </button>
            ) : null}

            <div className="dq-table-ramp-list">
              {BUILTIN_TABLE_RAMPS.map((ramp) => (
                <button
                  key={ramp.id}
                  type="button"
                  className="dq-table-ramp-btn"
                  aria-pressed={style.paletteId === ramp.id}
                  onClick={() =>
                    commit((draft) => {
                      draft.style.paletteId = ramp.id;
                    })
                  }
                >
                  <span className="dq-table-ramp-bars" aria-hidden="true">
                    <span
                      className="dq-table-ramp-bar"
                      style={{
                        background: `linear-gradient(90deg, ${ramp.stops.join(", ")})`,
                      }}
                    />
                    {ramp.secondaryStops ? (
                      <span
                        className="dq-table-ramp-bar"
                        style={{
                          background: `linear-gradient(90deg, ${ramp.secondaryStops.join(", ")})`,
                        }}
                      />
                    ) : null}
                  </span>
                  <span className="dq-table-ramp-name">{t(ramp.labelKey)}</span>
                </button>
              ))}
            </div>

            <div className="dq-table-catalog-search">
              <div className="dq-search-box">
                <Search size={13} strokeWidth={1.6} aria-hidden="true" />
                <input
                  type="search"
                  value={rampSearch}
                  placeholder={t("tableStudio.palettes.searchCatalog")}
                  aria-label={t("tableStudio.palettes.searchCatalog")}
                  onChange={(e) => setRampSearch(e.target.value)}
                />
              </div>
              <div className="dq-table-catalog-mini">
                {filteredCatalog.map((pal) => {
                  const stops =
                    pal.kind === "sequential" || pal.kind === "diverging"
                      ? pal.colors
                      : pal.partners.paired_sequential_stops ??
                        pal.partners.paired_diverging_stops ??
                        pal.colors;
                  return (
                    <button
                      key={pal.id}
                      type="button"
                      className="dq-table-ramp-btn"
                      aria-pressed={style.paletteId === pal.id}
                      onClick={() =>
                        commit((draft) => {
                          draft.style.paletteId = pal.id;
                        })
                      }
                    >
                      <span className="dq-table-ramp-bars" aria-hidden="true">
                        <span
                          className="dq-table-ramp-bar"
                          style={{
                            background: `linear-gradient(90deg, ${stops.join(", ")})`,
                          }}
                        />
                      </span>
                      <span className="dq-table-ramp-name">
                        {isZh ? pal.name.zh : pal.name.en}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </details>

        {/* 3. Heatmap */}
        <details name="dq-style" className="dq-style-acc">
          <summary className="dq-style-acc__sum">
            <span>{t("tableStudio.style.secHeatmap")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div
            className={`dq-style-acc__body${
              !hasAnyHeatCapable ? " dq-style-acc__body--disabled" : ""
            }`}
          >
            {!hasAnyHeatCapable ? (
              <p className="dq-style-disabled-note">{t("tableStudio.style.heatDisabledHint")}</p>
            ) : style.preset !== "matrix_heatmap" && !model.hasActiveHeatColumns ? (
              <div className="dq-style-mode-hint">
                <span>{t("tableStudio.style.scopeNeedHeatmapNote")}</span>
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  onClick={() =>
                    commit((draft) => {
                      draft.style.preset = "matrix_heatmap";
                      if (draft.structure.stage === "raw") {
                        draft.structure.stage = "tidied";
                      }
                    })
                  }
                >
                  {t("tableStudio.style.switchToHeatmapBtn")}
                </button>
              </div>
            ) : model.isMultiScaleHeat && style.heatScope === "per_column" ? (
              <div className="dq-style-mode-hint">
                <span>{t("tableStudio.style.multiScaleRowHint")}</span>
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  onClick={() =>
                    commit((draft) => {
                      draft.style.heatScope = "per_row";
                    })
                  }
                >
                  {t("tableStudio.style.switchToPerRowBtn")}
                </button>
              </div>
            ) : null}

            <div className="dq-field-label">{t("tableStudio.style.scopeLabel")}</div>
            <div className="dq-table-2x2-grid">
              {HEAT_SCOPES.map((sc) => {
                const blockedGlobal = sc === "global" && !model.globalHeatAllowed;
                const disabled = !hasAnyHeatCapable || blockedGlobal;
                return (
                  <button
                    key={sc}
                    type="button"
                    className="dq-btn dq-table-grid-btn"
                    disabled={disabled}
                    aria-pressed={style.heatScope === sc}
                    title={
                      blockedGlobal
                        ? t("tableStudio.style.globalDisabledReason")
                        : t(`tableStudio.style.scopes.${sc}`)
                    }
                    onClick={() =>
                      commit((draft) => {
                        draft.style.heatScope = sc;
                      })
                    }
                  >
                    {t(`tableStudio.style.scopes.${sc}`)}
                  </button>
                );
              })}
            </div>
            {!model.globalHeatAllowed && hasAnyHeatCapable ? (
              <p className="dq-style-disabled-note">
                {t("tableStudio.style.globalDisabledReason")}
              </p>
            ) : null}

            <div className="dq-table-inline-field">
              <span className="dq-field-label">{t("tableStudio.style.centerLabel")}</span>
              <div className="dq-inline-seg">
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  disabled={!hasAnyHeatCapable}
                  aria-pressed={style.heatCenter === "auto"}
                  onClick={() =>
                    commit((draft) => {
                      draft.style.heatCenter = "auto";
                    })
                  }
                >
                  {t("tableStudio.style.centerAuto")}
                </button>
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  disabled={!hasAnyHeatCapable}
                  aria-pressed={typeof style.heatCenter === "number"}
                  onClick={() => {
                    const num = Number(customCenterText);
                    commit((draft) => {
                      draft.style.heatCenter = Number.isFinite(num) ? num : 0;
                    });
                  }}
                >
                  {t("tableStudio.style.centerCustom")}
                </button>
              </div>
            </div>

            {typeof style.heatCenter === "number" ? (
              <input
                type="number"
                step="any"
                className="dq-input dq-input--compact"
                disabled={!hasAnyHeatCapable}
                aria-label={t("tableStudio.style.centerInputLabel")}
                value={String(style.heatCenter)}
                onChange={(e) => {
                  setCustomCenterText(e.target.value);
                  const num = Number(e.target.value);
                  if (Number.isFinite(num)) {
                    commit((draft) => {
                      draft.style.heatCenter = num;
                    });
                  }
                }}
              />
            ) : null}

            <label className="dq-check-row">
              <input
                type="checkbox"
                disabled={!hasAnyHeatCapable}
                checked={style.heatLog}
                onChange={(e) =>
                  commit((draft) => {
                    draft.style.heatLog = e.target.checked;
                  })
                }
              />
              <span>{t("tableStudio.style.logScale")}</span>
            </label>

            <label className="dq-check-row">
              <input
                type="checkbox"
                disabled={!hasAnyHeatCapable}
                checked={(style.heatDomainClip ?? "minmax") === "p5_p95"}
                onChange={(e) => {
                  const checked = e.target.checked;
                  commit((draft) => {
                    draft.style.heatDomainClip = checked ? "p5_p95" : "minmax";
                  });
                }}
              />
              <span>{t("tableStudio.style.outlierClipGlobal")}</span>
            </label>

            <label className="dq-check-row">
              <input
                type="checkbox"
                checked={structure.excludeSummaryRows !== false}
                onChange={(e) => {
                  const checked = e.target.checked;
                  commit((draft) => {
                    draft.structure.excludeSummaryRows = checked;
                  });
                }}
              />
              <span>{t("tableStudio.style.excludeSummaryRows")}</span>
            </label>
          </div>
        </details>

        {/* 4. Emphasis */}
        <details name="dq-style" className="dq-style-acc">
          <summary className="dq-style-acc__sum">
            <span>{t("tableStudio.style.secEmphasis")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div
            className={`dq-style-acc__body${!hasSigSource ? " dq-style-acc__body--disabled" : ""}`}
          >
            {!hasSigSource ? (
              <p className="dq-style-disabled-note">
                {t("tableStudio.style.emphasisDisabledHint")}
              </p>
            ) : null}
            <div className="dq-table-preset-list">
              {EMPHASIS_MODES.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className="dq-table-preset-card"
                  disabled={!hasSigSource}
                  aria-pressed={style.emphasis === mode}
                  onClick={() =>
                    commit((draft) => {
                      draft.style.emphasis = mode;
                    })
                  }
                >
                  <span className="dq-table-preset-card__title">
                    {t(`tableStudio.style.emphasisModes.${mode}.title`)}
                  </span>
                  <span className="dq-table-preset-card__desc">
                    {t(`tableStudio.style.emphasisModes.${mode}.desc`)}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </details>

        {/* 5. Row Rhythm & Tabular Nums */}
        <details name="dq-style" className="dq-style-acc">
          <summary className="dq-style-acc__sum">
            <span>{t("tableStudio.style.secRhythm")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-style-acc__body">
            {rhythmDisabled ? (
              <p className="dq-style-disabled-note">{t("tableStudio.style.rhythmDisabledHint")}</p>
            ) : null}
            <div className="dq-table-rhythm-row">
              {RHYTHM_MODES.map((rm) => (
                <button
                  key={rm}
                  type="button"
                  className="dq-btn dq-btn--xs"
                  disabled={rhythmDisabled}
                  aria-pressed={style.rowRhythm === rm}
                  onClick={() =>
                    commit((draft) => {
                      draft.style.rowRhythm = rm;
                    })
                  }
                >
                  {t(`tableStudio.style.rhythms.${rm}`)}
                </button>
              ))}
            </div>

            <label className="dq-check-row">
              <input
                type="checkbox"
                checked={style.tabularNums}
                onChange={(e) =>
                  commit((draft) => {
                    draft.style.tabularNums = e.target.checked;
                  })
                }
              />
              <span>{t("tableStudio.style.tabularNums")}</span>
            </label>
          </div>
        </details>
      </div>
    </aside>
  );
}
