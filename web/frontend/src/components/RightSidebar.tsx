import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  ExternalLink,
  Info,
  Lock,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";
import type {
  CvdMode,
  ElementRole,
  FigureElement,
  ManuscriptPresetKey,
  ManuscriptRecommendation,
  PaletteItem,
  VibrancyMode,
} from "../types";
import { tetherPopoverFallback } from "./ModalDialog";

type TabCategory =
  | "all"
  | "accessible"
  | "journal"
  | "museum"
  | "eastern"
  | "many"
  | "continuous";

const TAB_KEYS: TabCategory[] = [
  "all",
  "accessible",
  "journal",
  "museum",
  "eastern",
  "many",
  "continuous",
];

function InspectorCard({ el }: { el: FigureElement }): React.ReactElement {
  const { t } = useTranslation();
  const selectEntity = useStudioStore((s) => s.selectEntity);
  const setElementRoles = useStudioStore((s) => s.setElementRoles);
  const pickElementColor = useStudioStore((s) => s.pickElementColor);
  const toggleElementLock = useStudioStore((s) => s.toggleElementLock);
  const resetElement = useStudioStore((s) => s.resetElement);
  const setHoveredSwatch = useStudioStore((s) => s.setHoveredSwatch);

  const [hexDraft, setHexDraft] = useState(el.current_hex);
  const colorPickerId = useId();
  const hexInputId = useId();

  useEffect(() => {
    setHexDraft(el.current_hex);
  }, [el.current_hex]);

  const roles: ElementRole[] = ["focus", "normal", "background"];
  const roleLabelKey: Record<ElementRole, string> = {
    focus: "elements.roleFocus",
    normal: "elements.roleNormal",
    background: "elements.roleBackground",
  };

  const activeSw = el.inspector_swatches.find(
    (sw) => sw.hex.toUpperCase() === el.current_hex.toUpperCase(),
  );

  const commitCustomHex = (val: string): void => {
    const cleaned = val.trim();
    if (/^#?[0-9a-fA-F]{6}$/.test(cleaned)) {
      const normalized = cleaned.startsWith("#") ? cleaned.toUpperCase() : `#${cleaned.toUpperCase()}`;
      void pickElementColor(el.entity_id, normalized);
    } else {
      setHexDraft(el.current_hex);
    }
  };

  return (
    <section className="dq-inspector" aria-label={el.label}>
      <div className="dq-inspector__head">
        <div>
          <h3 className="dq-inspector__title">{el.label}</h3>
          {el.panels.length > 0 ? (
            <div className="dq-inspector__sub">
              {el.panels.length > 1
                ? t("inspector.appearsIn", { panels: el.panels.join(", ") })
                : t("inspector.appearsSingle", { panels: el.panels[0] })}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("inspector.close")}
          title={t("inspector.close")}
          onClick={() => selectEntity(null)}
        >
          <X size={14} strokeWidth={1.5} aria-hidden="true" />
        </button>
      </div>

      <div className="dq-segmented" role="group" aria-label={t("inspector.roleLabel")}>
        {roles.map((r) => (
          <button
            key={r}
            type="button"
            className="dq-btn"
            aria-pressed={el.role === r}
            title={t(`inspector.roleTips.${r}`)}
            onClick={() => void setElementRoles([el.entity_id], r)}
          >
            {t(roleLabelKey[r])}
          </button>
        ))}
      </div>

      <div className="dq-swatch-grid">
        {el.inspector_swatches.map((sw) => {
          const isCurrent = sw.hex.toUpperCase() === el.current_hex.toUpperCase();
          const conflict = Boolean(sw.too_close_to) && !isCurrent;
          const tip = sw.too_close_to
            ? `${sw.hex} — ${t("inspector.tooCloseTo", { label: sw.too_close_to })}`
            : sw.hex;
          return (
            <button
              key={sw.hex}
              type="button"
              className={`dq-swatch-btn${isCurrent ? " dq-swatch-btn--active" : ""}${
                conflict ? " dq-swatch-btn--conflict" : ""
              }`}
              style={{ backgroundColor: sw.hex }}
              aria-label={tip}
              title={tip}
              onMouseEnter={() => setHoveredSwatch({ entityId: el.entity_id, hex: sw.hex })}
              onMouseLeave={() => setHoveredSwatch(null)}
              onClick={() => void pickElementColor(el.entity_id, sw.hex)}
            />
          );
        })}
      </div>

      <div className="dq-custom-color-row">
        <label htmlFor={colorPickerId} style={{ fontSize: 12, color: "var(--text-2)" }}>
          {t("inspector.customColor")}
        </label>
        <input
          id={colorPickerId}
          type="color"
          className="dq-color-input"
          value={/^#[0-9a-fA-F]{6}$/.test(el.current_hex) ? el.current_hex : "#111827"}
          onChange={(e) => void pickElementColor(el.entity_id, e.target.value)}
        />
        <label htmlFor={hexInputId} className="visually-hidden">
          {t("inspector.hexLabel")}
        </label>
        <input
          id={hexInputId}
          type="text"
          className="dq-hex-input"
          value={hexDraft}
          onChange={(e) => setHexDraft(e.target.value)}
          onBlur={() => commitCustomHex(hexDraft)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              commitCustomHex(hexDraft);
            }
          }}
        />
      </div>

      <div className="dq-inspector__hint">
        {el.locked
          ? t("inspector.lockedHint")
          : activeSw?.too_close_to
            ? t("inspector.tooCloseTo", { label: activeSw.too_close_to })
            : t("inspector.distinguishableAll")}
      </div>

      <div className="dq-inspector__actions">
        <button
          type="button"
          className="dq-btn"
          aria-pressed={el.locked}
          onClick={() => void toggleElementLock(el.entity_id, !el.locked)}
        >
          <Lock size={13} strokeWidth={1.6} aria-hidden="true" />
          <span>{el.locked ? t("inspector.lockedButton") : t("inspector.lockButton")}</span>
        </button>
        <button
          type="button"
          className="dq-btn"
          onClick={() => void resetElement(el.entity_id)}
        >
          <RotateCcw size={13} strokeWidth={1.6} aria-hidden="true" />
          <span>{t("inspector.resetButton")}</span>
        </button>
      </div>
    </section>
  );
}

interface PaletteCardProps {
  palette: PaletteItem;
  active: boolean;
  langKey: "en" | "zh";
  onHoverStart: (id: string) => void;
  onHoverEnd: () => void;
  onApply: (id: string) => void;
}

function PaletteCard({
  palette,
  active,
  langKey,
  onHoverStart,
  onHoverEnd,
  onApply,
}: PaletteCardProps): React.ReactElement {
  const { t } = useTranslation();
  const infoBtnRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const popId = useId();

  useEffect(() => {
    const pop = popRef.current;
    if (!pop) return;
    const onToggle = (ev: Event): void => {
      const te = ev as ToggleEvent;
      if (te.newState === "open") {
        tetherPopoverFallback(pop, infoBtnRef.current, true);
      }
    };
    pop.addEventListener("toggle", onToggle);
    return () => pop.removeEventListener("toggle", onToggle);
  }, []);

  const displayName = palette.name[langKey] || palette.name.en;
  const visibleSwatches = palette.colors.slice(0, 12);
  const overflowCount = Math.max(0, palette.colors.length - 12);
  const thumbUrl = palette.artifact?.thumbnail_url || palette.artifact?.thumbnail;
  const countNum = palette.dynamic_generator ? palette.qc.max_colors : palette.colors.length;

  const popoverTriggerAttrs = { popovertarget: popId } as Record<string, unknown>;
  const popoverPanelAttrs = { popover: "auto" } as Record<string, unknown>;

  return (
    <div
      className={`dq-palette-card${active ? " dq-palette-card--active" : ""}`}
      onMouseEnter={() => onHoverStart(palette.id)}
      onMouseLeave={onHoverEnd}
    >
      <button
        type="button"
        className="dq-palette-card__apply"
        onClick={() => onApply(palette.id)}
      >
        <div className="dq-palette-card__swatches">
          {palette.order === "gradient" ? (
            <span
              className="dq-palette-bar"
              style={{
                background: `linear-gradient(to right, ${palette.colors.join(", ")})`,
              }}
            />
          ) : (
            <span className="dq-palette-bar">
              {visibleSwatches.map((hex, i) => (
                <span key={`${hex}-${i}`} style={{ backgroundColor: hex }} />
              ))}
            </span>
          )}
          {overflowCount > 0 ? (
            <span className="dq-palette-overflow">
              {t("palettes.moreSwatches", { count: overflowCount })}
            </span>
          ) : null}
        </div>

        <div className="dq-palette-card__row1">
          <span className="dq-palette-name">{displayName}</span>
          {palette.qc.colorblind_safe ? (
            <span className="dq-badge">{t("palettes.badgeCbSafe")}</span>
          ) : null}
        </div>

        <div className="dq-palette-card__row2">
          <span>
            {palette.source.author} · {palette.source.year}
          </span>
          <span>{t("palettes.colorCount", { count: countNum })}</span>
        </div>
      </button>

      <button
        ref={infoBtnRef}
        type="button"
        className="dq-palette-info-btn"
        aria-label={`${t("palettes.sourceInfo")}: ${displayName}`}
        title={t("palettes.sourceInfo")}
        {...popoverTriggerAttrs}
      >
        <Info size={14} strokeWidth={1.5} aria-hidden="true" />
      </button>

      <div
        ref={popRef}
        id={popId}
        className="dq-popover dq-popover--card"
        {...popoverPanelAttrs}
      >
        {thumbUrl ? (
          <img
            src={thumbUrl}
            alt={t("a11y.artifactThumbAlt", {
              title: palette.artifact?.title || displayName,
            })}
            className="dq-prov-thumb"
            loading="lazy"
          />
        ) : null}
        <div className="dq-prov-title">{palette.artifact?.title || palette.source.title}</div>
        <dl className="dq-prov-dl">
          {palette.artifact ? (
            <>
              <dt>{t("palettes.provenance.museum")}</dt>
              <dd>{palette.artifact.museum}</dd>
              <dt>{t("palettes.provenance.accession")}</dt>
              <dd>{palette.artifact.object_id}</dd>
              <dt>{t("palettes.provenance.year")}</dt>
              <dd>{palette.artifact.date}</dd>
            </>
          ) : (
            <>
              <dt>{t("palettes.provenance.author")}</dt>
              <dd>{palette.source.author}</dd>
              <dt>{t("palettes.provenance.year")}</dt>
              <dd>{String(palette.source.year)}</dd>
            </>
          )}
          <dt>{t("palettes.provenance.license")}</dt>
          <dd>{palette.artifact?.image_license || palette.source.license}</dd>
          {palette.partners.paired_sequential_stops && palette.partners.paired_sequential_stops.length >= 2 ? (
            <>
              <dt>{t("palettes.provenance.pairedSequential")}</dt>
              <dd>
                <span
                  style={{
                    display: "block",
                    height: 8,
                    borderRadius: 3,
                    marginTop: 4,
                    background: `linear-gradient(to right, ${palette.partners.paired_sequential_stops.join(", ")})`,
                    border: "1px solid var(--border-subtle)",
                  }}
                />
              </dd>
            </>
          ) : null}
          {palette.partners.paired_diverging_stops && palette.partners.paired_diverging_stops.length >= 2 ? (
            <>
              <dt>{t("palettes.provenance.pairedDiverging")}</dt>
              <dd>
                <span
                  style={{
                    display: "block",
                    height: 8,
                    borderRadius: 3,
                    marginTop: 4,
                    background: `linear-gradient(to right, ${palette.partners.paired_diverging_stops.join(", ")})`,
                    border: "1px solid var(--border-subtle)",
                  }}
                />
              </dd>
            </>
          ) : null}
        </dl>
        {(palette.artifact?.url || palette.source.url) ? (
          <a
            href={palette.artifact?.url || palette.source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="dq-prov-link"
          >
            <span>{t("palettes.provenance.openLink")}</span>
            <ExternalLink size={12} strokeWidth={1.6} aria-hidden="true" />
          </a>
        ) : null}
      </div>
    </div>
  );
}

export function RightSidebar(): React.ReactElement | null {
  const { t, i18n } = useTranslation();
  const figure = useStudioStore((s) => s.figure);
  const targetPanels = useStudioStore((s) => s.targetPanels);
  const palettes = useStudioStore((s) => s.palettes);
  const styles = useStudioStore((s) => s.styles);
  const selectedIds = useStudioStore((s) => s.selectedIds);
  const hoveredStyleId = useStudioStore((s) => s.hoveredStyleId);
  const cvdMode = useStudioStore((s) => s.cvdMode);
  const palettesDrawerOpen = useStudioStore((s) => s.palettesDrawerOpen);

  const setTargetPanels = useStudioStore((s) => s.setTargetPanels);
  const toggleTargetPanel = useStudioStore((s) => s.toggleTargetPanel);
  const applyPalette = useStudioStore((s) => s.applyPalette);
  const resetToOriginal = useStudioStore((s) => s.resetToOriginal);
  const resetTargetPanels = useStudioStore((s) => s.resetTargetPanels);
  const setHoveredPalette = useStudioStore((s) => s.setHoveredPalette);
  const setHoveredStyle = useStudioStore((s) => s.setHoveredStyle);
  const setRule = useStudioStore((s) => s.setRule);
  const setVibrancy = useStudioStore((s) => s.setVibrancy);
  const setAestheticStyle = useStudioStore((s) => s.setAestheticStyle);
  const setCvdMode = useStudioStore((s) => s.setCvdMode);
  const setPalettesDrawerOpen = useStudioStore((s) => s.setPalettesDrawerOpen);

  const [activeTab, setActiveTab] = useState<TabCategory>("all");
  const [query, setQuery] = useState("");
  const [filterCbSafe, setFilterCbSafe] = useState(false);
  const [filterEnoughColors, setFilterEnoughColors] = useState(true);
  const [filterPrintFriendly, setFilterPrintFriendly] = useState(false);
  const [visibleLimit, setVisibleLimit] = useState(80);

  useEffect(() => {
    setVisibleLimit(80);
  }, [activeTab, query, filterCbSafe, filterEnoughColors, filterPrintFriendly]);

  const [manuscriptOpen, setManuscriptOpen] = useState(false);
  const [manuscriptPreset, setManuscriptPreset] = useState<ManuscriptPresetKey | null>(null);
  const [manuscriptBrief, setManuscriptBrief] = useState("");
  const [manuscriptLoading, setManuscriptLoading] = useState(false);
  const [manuscriptRecs, setManuscriptRecs] = useState<ManuscriptRecommendation[]>([]);
  const [geminiKeyOpen, setGeminiKeyOpen] = useState(false);
  const [geminiKey, setGeminiKey] = useState<string>(() => {
    try {
      return window.sessionStorage.getItem("danqing_gemini_key") || "";
    } catch {
      return "";
    }
  });

  const runManuscriptMatch = async (presetOverride?: ManuscriptPresetKey | null): Promise<void> => {
    if (!figure) return;
    const chosenPreset = presetOverride !== undefined ? presetOverride : manuscriptPreset;
    setManuscriptLoading(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (geminiKey.trim()) {
        headers["X-Gemini-Key"] = geminiKey.trim();
      }
      const res = await fetch(`/api/v2/figures/${encodeURIComponent(figure.figure_id)}/manuscript-match`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          preset: chosenPreset,
          brief: manuscriptBrief.trim(),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setManuscriptRecs(data.recommendations || []);
        setActiveTab("all");
      }
    } finally {
      setManuscriptLoading(false);
    }
  };

  const tablistRef = useRef<HTMLDivElement | null>(null);
  const hoverTimerRef = useRef<number | null>(null);
  const styleHoverTimerRef = useRef<number | null>(null);
  const searchId = useId();
  const cvdSelectId = useId();
  const tabIdPrefix = useId();
  const styleDescId = useId();

  const langKey: "en" | "zh" = i18n.language.startsWith("zh") ? "zh" : "en";

  useEffect(() => {
    return () => {
      if (hoverTimerRef.current !== null) {
        window.clearTimeout(hoverTimerRef.current);
      }
      if (styleHoverTimerRef.current !== null) {
        window.clearTimeout(styleHoverTimerRef.current);
      }
    };
  }, []);

  // Scroll selected tab into view & provide arrow-key selection-follows-focus fallback
  useEffect(() => {
    const list = tablistRef.current;
    if (!list) return;
    const tabs = Array.from(list.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const selectedBtn = tabs.find((b) => b.getAttribute("aria-selected") === "true");
    if (selectedBtn) {
      selectedBtn.scrollIntoView({
        block: "nearest",
        inline: "nearest",
        container: "nearest",
      } as ScrollIntoViewOptions);
    }

    if (typeof HTMLElement !== "undefined" && "focusGroup" in HTMLElement.prototype) return;

    tabs.forEach((b) => {
      b.tabIndex = b.getAttribute("aria-selected") === "true" ? 0 : -1;
    });

    const onKeyDown = (ev: KeyboardEvent): void => {
      const items = Array.from(list.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
      const curIdx = items.indexOf(document.activeElement as HTMLButtonElement);
      if (curIdx < 0) return;
      let nextIdx: number | null = null;
      if (ev.key === "ArrowRight") {
        nextIdx = (curIdx + 1) % items.length;
      } else if (ev.key === "ArrowLeft") {
        nextIdx = (curIdx - 1 + items.length) % items.length;
      } else if (ev.key === "Home") {
        nextIdx = 0;
      } else if (ev.key === "End") {
        nextIdx = items.length - 1;
      }
      if (nextIdx !== null) {
        ev.preventDefault();
        const nextKey = TAB_KEYS[nextIdx];
        setActiveTab(nextKey);
        items[nextIdx]?.focus();
      }
    };

    list.addEventListener("keydown", onKeyDown);
    return () => list.removeEventListener("keydown", onKeyDown);
  }, [activeTab]);

  const hoverDelayMs =
    figure && (figure.slow_warning || figure.op_count > 100000) ? 420 : 250;

  const handleHoverStart = (pid: string): void => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
    }
    hoverTimerRef.current = window.setTimeout(() => {
      setHoveredPalette(pid);
    }, hoverDelayMs);
  };

  const handleHoverEnd = (): void => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setHoveredPalette(null);
  };

  const handleStyleHoverStart = (sid: string): void => {
    if (styleHoverTimerRef.current !== null) {
      window.clearTimeout(styleHoverTimerRef.current);
    }
    styleHoverTimerRef.current = window.setTimeout(() => {
      setHoveredStyle(sid);
    }, hoverDelayMs);
  };

  const handleStyleHoverEnd = (): void => {
    if (styleHoverTimerRef.current !== null) {
      window.clearTimeout(styleHoverTimerRef.current);
      styleHoverTimerRef.current = null;
    }
    setHoveredStyle(null);
  };

  const requiredColors = useMemo(() => {
    if (!figure) return 1;
    if (targetPanels.length === 0) {
      return figure.diagnostics.required_color_count ?? 1;
    }
    const tset = new Set(targetPanels);
    const scopedCount = figure.elements.filter(
      (e) => e.role !== "background" && e.panels.some((pn) => tset.has(pn)),
    ).length;
    return Math.max(1, scopedCount);
  }, [figure, targetPanels]);

  const { recommendedList, mainList } = useMemo(() => {
    if (!figure) return { recommendedList: [] as PaletteItem[], mainList: [] as PaletteItem[] };
    const recIds = new Set(figure.recommended_conventions || []);
    const q = query.trim().toLowerCase();

    const rec = palettes.filter((p) => p.collection === "convention" && recIds.has(p.id));

    const filtered = palettes.filter((p) => {
      if (p.collection === "convention") {
        return recIds.has(p.id) && activeTab === "all";
      }
      if (activeTab !== "all" && p.collection !== activeTab) {
        return false;
      }
      if (filterCbSafe && !p.qc.colorblind_safe) {
        return false;
      }
      if (filterPrintFriendly && !p.qc.print_friendly) {
        return false;
      }
      if (
        filterEnoughColors &&
        p.kind === "qualitative" &&
        !p.dynamic_generator &&
        p.qc.max_colors < requiredColors
      ) {
        return false;
      }
      if (q) {
        const hay = [
          p.id,
          p.name.en,
          p.name.zh,
          p.source.title,
          p.source.author,
          p.artifact?.title || "",
          p.artifact?.museum || "",
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (activeTab === "all" && !q) {
      const isBulk = (id: string): number =>
        id.startsWith("pypal_") || id.startsWith("nice_cl_") || id.startsWith("thiagodnf_")
          ? 1
          : 0;
      filtered.sort((a, b) => isBulk(a.id) - isBulk(b.id));
    }

    return { recommendedList: rec, mainList: filtered };
  }, [
    figure,
    palettes,
    activeTab,
    query,
    filterCbSafe,
    filterEnoughColors,
    filterPrintFriendly,
    requiredColors,
  ]);

  if (!figure) return null;

  const singleSelectedElement =
    selectedIds.length === 1
      ? figure.elements.find((e) => e.entity_id === selectedIds[0]) || null
      : null;

  const tablistFocusGroupAttrs = { focusgroup: "tablist nomemory" } as Record<string, unknown>;
  const vibrancyModes: VibrancyMode[] = ["muted", "standard", "vivid"];
  const cvdModes: CvdMode[] = ["normal", "deutan", "protan", "tritan", "grayscale"];
  const panelPals = figure.panel_palettes || {};
  const hasMultiplePanels = figure.panels.length > 1;

  const activePaletteForScope = useMemo(() => {
    if (targetPanels.length > 0 && Object.keys(panelPals).length > 0) {
      const firstVal = panelPals[targetPanels[0]];
      const allSame = targetPanels.every((pid) => panelPals[pid] === firstVal);
      if (allSame && firstVal && firstVal !== "__original__") {
        return firstVal;
      }
      return null;
    }
    if (Object.keys(panelPals).length > 0) {
      return null;
    }
    return !figure.is_original_mode ? figure.palette_id : null;
  }, [figure.is_original_mode, figure.palette_id, panelPals, targetPanels]);

  const canResetScoped = useMemo(() => {
    if (targetPanels.length === 0) {
      return !figure.is_original_mode || Boolean(figure.aesthetic_style);
    }
    if (Object.keys(panelPals).length === 0) {
      return !figure.is_original_mode || Boolean(figure.aesthetic_style);
    }
    return targetPanels.some((pid) => panelPals[pid] && panelPals[pid] !== "__original__");
  }, [figure.aesthetic_style, figure.is_original_mode, panelPals, targetPanels]);

  const activeStyleObj = useMemo(
    () => (figure.aesthetic_style ? styles.find((s) => s.id === figure.aesthetic_style) || null : null),
    [figure.aesthetic_style, styles],
  );

  const previewedStyleObj = useMemo(() => {
    if (hoveredStyleId && hoveredStyleId !== "__none__") {
      return styles.find((s) => s.id === hoveredStyleId) || activeStyleObj;
    }
    if (hoveredStyleId === "__none__") {
      return null;
    }
    return activeStyleObj;
  }, [activeStyleObj, hoveredStyleId, styles]);

  return (
    <aside
      className={`dq-right-sidebar${palettesDrawerOpen ? " dq-right-sidebar--open" : ""}`}
      aria-label={t("a11y.palettesRegion")}
    >
      {singleSelectedElement ? <InspectorCard el={singleSelectedElement} /> : null}

      <div className="dq-palettes-pane">
        <div className="dq-palettes-top">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
            <h2 style={{ margin: 0, fontSize: 12, fontWeight: 600, color: "var(--text-2)" }}>
              {t("palettes.heading")}
            </h2>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <button
                type="button"
                className="dq-chip"
                aria-expanded={manuscriptOpen}
                aria-pressed={manuscriptOpen}
                style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                onClick={() => setManuscriptOpen((v) => !v)}
              >
                <BookOpen size={12} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("palettes.manuscript.toggle")}</span>
              </button>
              {canResetScoped ? (
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost"
                  style={{ fontSize: 11.5, padding: "2px 6px", minBlockSize: 24 }}
                  onClick={() =>
                    targetPanels.length > 0 ? void resetTargetPanels() : void resetToOriginal()
                  }
                >
                  {targetPanels.length > 0 ? t("palettes.resetPanel") : t("palettes.resetOriginal")}
                </button>
              ) : null}
              <button
                type="button"
                className="dq-btn dq-btn--ghost dq-btn--icon dq-drawer-trigger"
                aria-label={t("a11y.closeDrawer")}
                onClick={() => setPalettesDrawerOpen(false)}
              >
                <X size={15} strokeWidth={1.5} aria-hidden="true" />
              </button>
            </div>
          </div>

          {manuscriptOpen ? (
            <div className="dq-manuscript-box">
              <p className="dq-manuscript-lead">{t("palettes.manuscript.lead")}</p>
              <div className="dq-filter-chips">
                {(["cns_clean", "clinical", "omics", "museum"] as ManuscriptPresetKey[]).map((pk) => (
                  <button
                    key={pk}
                    type="button"
                    className="dq-chip"
                    aria-pressed={manuscriptPreset === pk}
                    onClick={() => {
                      setManuscriptPreset(pk);
                      void runManuscriptMatch(pk);
                    }}
                  >
                    {t(`palettes.manuscript.presets.${pk}`)}
                  </button>
                ))}
              </div>
              <div className="dq-manuscript-row">
                <input
                  type="text"
                  className="dq-manuscript-input"
                  placeholder={t("palettes.manuscript.briefPlaceholder")}
                  aria-label={t("palettes.manuscript.briefPlaceholder")}
                  value={manuscriptBrief}
                  onChange={(e) => setManuscriptBrief(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void runManuscriptMatch();
                    }
                  }}
                />
                <button
                  type="button"
                  className="dq-btn dq-btn--primary"
                  style={{ minBlockSize: 28, padding: "3px 9px", fontSize: 12 }}
                  disabled={manuscriptLoading}
                  onClick={() => void runManuscriptMatch()}
                >
                  {manuscriptLoading
                    ? t("palettes.manuscript.matching")
                    : t("palettes.manuscript.matchAction")}
                </button>
              </div>
              <div>
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost"
                  style={{ fontSize: 11, padding: "1px 4px", minBlockSize: 20, color: "var(--text-3)" }}
                  aria-expanded={geminiKeyOpen}
                  onClick={() => setGeminiKeyOpen((v) => !v)}
                >
                  {t("palettes.manuscript.keyToggle")}
                </button>
                {geminiKeyOpen ? (
                  <input
                    type="password"
                    className="dq-manuscript-input"
                    style={{ width: "100%", marginTop: 4 }}
                    placeholder={t("palettes.manuscript.keyPlaceholder")}
                    aria-label={t("palettes.manuscript.keyPlaceholder")}
                    value={geminiKey}
                    onChange={(e) => {
                      const v = e.target.value;
                      setGeminiKey(v);
                      try {
                        if (v) window.sessionStorage.setItem("danqing_gemini_key", v);
                        else window.sessionStorage.removeItem("danqing_gemini_key");
                      } catch {
                        // ignore storage quota errors
                      }
                    }}
                  />
                ) : null}
              </div>
            </div>
          ) : null}

          {hasMultiplePanels ? (
            <div className="dq-scope-row" role="group" aria-label={t("a11y.panelScope")}>
              <div className="dq-scope-label" title={t("palettes.scopeHint")}>
                {t("palettes.scopeLabel")}
              </div>
              <div className="dq-scope-chips">
                <button
                  type="button"
                  className="dq-chip"
                  aria-pressed={targetPanels.length === 0}
                  onClick={() => setTargetPanels([])}
                >
                  {t("palettes.scopeAll")}
                </button>
                {figure.panels.map((pb) => {
                  const isPressed = targetPanels.includes(pb.panel_id);
                  const assignedPal = panelPals[pb.panel_id];
                  const hasCustom = Boolean(assignedPal && assignedPal !== "__original__");
                  return (
                    <button
                      key={pb.panel_id}
                      type="button"
                      className="dq-chip"
                      aria-pressed={isPressed}
                      title={t("palettes.scopeHint")}
                      onClick={(e) =>
                        toggleTargetPanel(pb.panel_id, e.shiftKey || e.metaKey || e.ctrlKey)
                      }
                    >
                      <span>{pb.panel_id}</span>
                      {hasCustom ? <span className="dq-scope-dot" aria-hidden="true" /> : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {figure.is_original_mode ? (
            <p className="dq-pick-prompt">{t("palettes.pickPrompt")}</p>
          ) : null}

          <div className="dq-search-wrap">
            <Search size={14} strokeWidth={1.5} aria-hidden="true" />
            <label htmlFor={searchId} className="visually-hidden">
              {t("a11y.searchPalettes")}
            </label>
            <input
              id={searchId}
              type="search"
              className="dq-search-input"
              placeholder={t("palettes.searchPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div
            ref={tablistRef}
            role="tablist"
            aria-label={t("a11y.paletteCategories")}
            className="dq-tablist"
            {...tablistFocusGroupAttrs}
          >
            {TAB_KEYS.map((cat) => {
              const isSelected = activeTab === cat;
              const tabStartAttrs = isSelected
                ? ({ focusgroupstart: "" } as Record<string, unknown>)
                : {};
              return (
                <button
                  key={cat}
                  id={`${tabIdPrefix}-${cat}`}
                  type="button"
                  role="tab"
                  aria-selected={isSelected}
                  className="dq-tab"
                  onClick={() => setActiveTab(cat)}
                  {...tabStartAttrs}
                >
                  {t(`palettes.tabs.${cat}`)}
                </button>
              );
            })}
          </div>

          <div className="dq-filter-chips">
            <button
              type="button"
              className="dq-chip"
              aria-pressed={filterCbSafe}
              onClick={() => setFilterCbSafe((v) => !v)}
            >
              {t("palettes.filters.cbSafe")}
            </button>
            <button
              type="button"
              className="dq-chip"
              aria-pressed={filterEnoughColors}
              onClick={() => setFilterEnoughColors((v) => !v)}
            >
              {t("palettes.filters.enoughColors")}
            </button>
            <button
              type="button"
              className="dq-chip"
              aria-pressed={filterPrintFriendly}
              onClick={() => setFilterPrintFriendly((v) => !v)}
            >
              {t("palettes.filters.printFriendly")}
            </button>
          </div>
        </div>

        <div
          role="tabpanel"
          aria-labelledby={`${tabIdPrefix}-${activeTab}`}
          className="dq-palette-list"
          onScroll={(e) => {
            const el = e.currentTarget;
            if (el.scrollHeight - el.scrollTop - el.clientHeight < 280) {
              setVisibleLimit((prev) => (prev < mainList.length ? prev + 80 : prev));
            }
          }}
        >
          {manuscriptRecs.length > 0 && activeTab === "all" && !query ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 6 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text-1)" }}>
                  {t("palettes.manuscript.resultsHeading")}
                </span>
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost"
                  style={{ fontSize: 11, padding: "1px 5px", minBlockSize: 20 }}
                  onClick={() => setManuscriptRecs([])}
                >
                  {t("palettes.manuscript.clearResults")}
                </button>
              </div>
              {manuscriptRecs.map((rec) => {
                const palObj = palettes.find((x) => x.id === rec.palette_id);
                if (!palObj) return null;
                return (
                  <div key={`ms-${palObj.id}`} style={{ display: "flex", flexDirection: "column" }}>
                    <PaletteCard
                      palette={palObj}
                      active={activePaletteForScope === palObj.id}
                      langKey={langKey}
                      onHoverStart={handleHoverStart}
                      onHoverEnd={handleHoverEnd}
                      onApply={(pid) => void applyPalette(pid)}
                    />
                    <div className="dq-manuscript-reason">
                      {rec.reason[langKey] || rec.reason.en}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}

          {recommendedList.length > 0 && activeTab === "all" && !query ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 4 }}>
              <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text-2)" }}>
                {t("palettes.recommendedHeading")}
              </div>
              {recommendedList.map((p) => (
                <PaletteCard
                  key={`rec-${p.id}`}
                  palette={p}
                  active={activePaletteForScope === p.id}
                  langKey={langKey}
                  onHoverStart={handleHoverStart}
                  onHoverEnd={handleHoverEnd}
                  onApply={(pid) => void applyPalette(pid)}
                />
              ))}
            </div>
          ) : null}

          {mainList.length === 0 ? (
            <div style={{ padding: "16px 6px", fontSize: 12.5, color: "var(--text-3)" }}>
              {t("palettes.emptyMatch")}
            </div>
          ) : (
            <>
              {mainList.slice(0, visibleLimit).map((p) => (
                <PaletteCard
                  key={p.id}
                  palette={p}
                  active={activePaletteForScope === p.id}
                  langKey={langKey}
                  onHoverStart={handleHoverStart}
                  onHoverEnd={handleHoverEnd}
                  onApply={(pid) => void applyPalette(pid)}
                />
              ))}
              {mainList.length > visibleLimit ? (
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost"
                  style={{ width: "100%", marginTop: 4, fontSize: 12 }}
                  onClick={() => setVisibleLimit((prev) => prev + 120)}
                >
                  {t("palettes.showMore", { count: mainList.length - visibleLimit })}
                </button>
              ) : null}
            </>
          )}
        </div>
      </div>

      {styles.length > 0 ? (
        <details className="dq-rules dq-styles-section" open>
          <summary>
            <span className="dq-styles-summary-main">
              <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("styles.heading")}</span>
            </span>
            {activeStyleObj ? (
              <span className="dq-style-pill dq-style-pill--active">
                {activeStyleObj.name[langKey] || activeStyleObj.name.en}
              </span>
            ) : (
              <span className="dq-style-pill">{t("styles.optionalTag")}</span>
            )}
          </summary>
          <div className="dq-styles__body">
            <p id={styleDescId} className="dq-styles-lead">
              {previewedStyleObj
                ? previewedStyleObj.description[langKey] || previewedStyleObj.description.en
                : t("styles.lead")}
            </p>
            <div
              className="dq-style-grid"
              role="group"
              aria-label={t("styles.heading")}
              aria-describedby={styleDescId}
            >
              <button
                type="button"
                className="dq-style-chip dq-style-chip--off"
                aria-pressed={!figure.aesthetic_style}
                onMouseEnter={() => handleStyleHoverStart("__none__")}
                onMouseLeave={handleStyleHoverEnd}
                onClick={() => void setAestheticStyle(null)}
              >
                <span className="dq-style-chip__name">{t("styles.off")}</span>
              </button>
              {styles.map((st) => {
                const stName = st.name[langKey] || st.name.en;
                const isPressed = figure.aesthetic_style === st.id;
                return (
                  <button
                    key={st.id}
                    type="button"
                    className="dq-style-chip"
                    aria-pressed={isPressed}
                    onMouseEnter={() => handleStyleHoverStart(st.id)}
                    onMouseLeave={handleStyleHoverEnd}
                    onClick={() => void setAestheticStyle(isPressed ? null : st.id)}
                  >
                    <span className="dq-style-swatches" aria-hidden="true">
                      {st.preview_swatches.slice(0, 4).map((sw, idx) => (
                        <span
                          key={`${st.id}-${idx}`}
                          className="dq-style-swatch-dot"
                          style={{ background: sw }}
                        />
                      ))}
                    </span>
                    <span className="dq-style-chip__name">{stName}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </details>
      ) : null}

      <details className="dq-rules">
        <summary>
          <span className="dq-styles-summary-main">
            <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("rules.heading")}</span>
          </span>
        </summary>
        <div className="dq-rules__body">
          <div className="dq-rule-block">
            <div className="dq-rule-label">{t("rules.crossPanelLabel")}</div>
            <label className="dq-radio-option">
              <input
                type="radio"
                name="dq-cross-panel-rule"
                checked={figure.rule === "same_name"}
                onChange={() => void setRule("same_name")}
              />
              <div>
                <div>{t("rules.sameName")}</div>
                <div className="dq-radio-help">{t("rules.sameNameHelp")}</div>
              </div>
            </label>
            <label className="dq-radio-option">
              <input
                type="radio"
                name="dq-cross-panel-rule"
                checked={figure.rule === "unique"}
                onChange={() => void setRule("unique")}
              />
              <div>
                <div>{t("rules.unique")}</div>
                <div className="dq-radio-help">{t("rules.uniqueHelp")}</div>
              </div>
            </label>
            {!figure.is_original_mode && figure.diagnostics.generated_count > 0 ? (
              <div className="dq-generated-note">
                {t("rules.generatedNotice", {
                  paletteCount: figure.diagnostics.palette_color_count,
                  requiredCount: figure.diagnostics.required_color_count,
                  generatedCount: figure.diagnostics.generated_count,
                })}
              </div>
            ) : null}
          </div>

          <div className="dq-rule-block">
            <label htmlFor={cvdSelectId} className="dq-rule-label">
              <span>{t("rules.cvdLabel")}</span>
              <span style={{ fontWeight: 400, color: "var(--text-3)", fontSize: 11 }}>
                {t("rules.cvdPreviewOnly")}
              </span>
            </label>
            <select
              id={cvdSelectId}
              className="dq-select"
              value={cvdMode}
              onChange={(e) => setCvdMode(e.target.value as CvdMode)}
            >
              {cvdModes.map((m) => (
                <option key={m} value={m}>
                  {t(`rules.cvdModes.${m}`)}
                </option>
              ))}
            </select>
          </div>

          <div className="dq-rule-block">
            <div className="dq-rule-label">{t("rules.vibrancyLabel")}</div>
            <div className="dq-segmented" role="group" aria-label={t("rules.vibrancyLabel")}>
              {vibrancyModes.map((vm) => (
                <button
                  key={vm}
                  type="button"
                  className="dq-btn"
                  aria-pressed={figure.vibrancy === vm}
                  onClick={() => void setVibrancy(vm)}
                >
                  {t(`rules.vibrancyModes.${vm}`)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </details>
    </aside>
  );
}
