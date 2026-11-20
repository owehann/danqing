import React, { useId, useMemo } from "react";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  RotateCcw,
  Sparkles,
  SplitSquareHorizontal,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_PANEL_OVERRIDE,
  DEFAULT_TEXT_ITEM_OVERRIDE,
  type LegendOrientMode,
  type LegendPosMode,
  useLayoutStudioStore,
} from "../../layout/layoutStore";

const FAMILY_ORDER = [
  "nature",
  "science",
  "cell",
  "nejm",
  "lancet",
  "hepatology",
  "oncology",
  "pnas",
  "custom",
] as const;

const MODE_IDS = [
  "auto_bento",
  "hero_bento",
  "uniform_3col",
  "compact_4col",
  "asymmetric_bands",
] as const;

const LEGEND_POS_IDS: LegendPosMode[] = [
  "auto",
  "inside_tr",
  "inside_tl",
  "inside_br",
  "inside_bl",
  "top",
  "bottom",
  "right",
  "custom",
  "hidden",
];

const LEGEND_ORIENT_IDS: LegendOrientMode[] = ["auto", "horizontal", "vertical"];

const LEGEND_COLOR_PRESETS = [
  { id: "black", hex: "#000000" },
  { id: "crimson", hex: "#B91C1C" },
  { id: "cobalt", hex: "#1D4ED8" },
  { id: "teal", hex: "#0F766E" },
] as const;

const SINGLE_ITEM_COLORS = [
  { id: "black", hex: "#000000" },
  { id: "crimson", hex: "#B91C1C" },
  { id: "cobalt", hex: "#1D4ED8" },
  { id: "teal", hex: "#0F766E" },
  { id: "muted", hex: "#64748B" },
] as const;

export function LayoutRightSidebar(): React.ReactElement {
  const { t } = useTranslation();

  const panels = useLayoutStudioStore((s) => s.panels);
  const journals = useLayoutStudioStore((s) => s.journals);
  const focusedPanelId = useLayoutStudioStore((s) => s.focusedPanelId);
  const focusedTextKey = useLayoutStudioStore((s) => s.focusedTextKey);
  const inspectorTab = useLayoutStudioStore((s) => s.inspectorTab);
  const journalId = useLayoutStudioStore((s) => s.journalId);
  const customWidthMm = useLayoutStudioStore((s) => s.customWidthMm);
  const customMaxHeightMm = useLayoutStudioStore((s) => s.customMaxHeightMm);
  const tagCaseOverride = useLayoutStudioStore((s) => s.tagCaseOverride);
  const tagFlow = useLayoutStudioStore((s) => s.tagFlow);
  const layoutMode = useLayoutStudioStore((s) => s.layoutMode);
  const fontFamilies = useLayoutStudioStore((s) => s.fontFamilies);
  const fontFamily = useLayoutStudioStore((s) => s.fontFamily);
  const tagPt = useLayoutStudioStore((s) => s.tagPt);
  const titlePt = useLayoutStudioStore((s) => s.titlePt);
  const axisTitlePt = useLayoutStudioStore((s) => s.axisTitlePt);
  const tickPt = useLayoutStudioStore((s) => s.tickPt);
  const axisStrokePt = useLayoutStudioStore((s) => s.axisStrokePt);
  const dataStrokePt = useLayoutStudioStore((s) => s.dataStrokePt);
  const gutterMm = useLayoutStudioStore((s) => s.gutterMm);
  const showPanelTitles = useLayoutStudioStore((s) => s.showPanelTitles);
  const hoistSharedLegends = useLayoutStudioStore((s) => s.hoistSharedLegends);
  const spanOverrides = useLayoutStudioStore((s) => s.spanOverrides);
  const lockedOverrides = useLayoutStudioStore((s) => s.lockedOverrides);
  const roiOverrides = useLayoutStudioStore((s) => s.roiOverrides);
  const panelOverrides = useLayoutStudioStore((s) => s.panelOverrides);
  const inspectorDrawerOpen = useLayoutStudioStore((s) => s.inspectorDrawerOpen);
  const composed = useLayoutStudioStore((s) => s.composed);

  const setInspectorTab = useLayoutStudioStore((s) => s.setInspectorTab);
  const applyJournalPreset = useLayoutStudioStore((s) => s.applyJournalPreset);
  const setCustomDimensions = useLayoutStudioStore((s) => s.setCustomDimensions);
  const setTagCaseOverride = useLayoutStudioStore((s) => s.setTagCaseOverride);
  const setTagFlow = useLayoutStudioStore((s) => s.setTagFlow);
  const setLayoutMode = useLayoutStudioStore((s) => s.setLayoutMode);
  const setTypographyField = useLayoutStudioStore((s) => s.setTypographyField);
  const setSpanOverride = useLayoutStudioStore((s) => s.setSpanOverride);
  const setLockedOverride = useLayoutStudioStore((s) => s.setLockedOverride);
  const updateRoi = useLayoutStudioStore((s) => s.updateRoi);
  const updatePanelOverride = useLayoutStudioStore((s) => s.updatePanelOverride);
  const setFocusedText = useLayoutStudioStore((s) => s.setFocusedText);
  const updateTextItemOverride = useLayoutStudioStore((s) => s.updateTextItemOverride);
  const resetTextItemOverride = useLayoutStudioStore((s) => s.resetTextItemOverride);
  const resetPanelOverride = useLayoutStudioStore((s) => s.resetPanelOverride);
  const unstackPanel = useLayoutStudioStore((s) => s.unstackPanel);
  const setInspectorDrawerOpen = useLayoutStudioStore((s) => s.setInspectorDrawerOpen);

  const famSelId = useId();
  const tierSelId = useId();
  const flowSelId = useId();
  const caseSelId = useId();
  const fontSelId = useId();
  const spanSelId = useId();
  const tagInputId = useId();
  const legPosSelId = useId();
  const pFontSelId = useId();
  const legFontSelId = useId();
  const legCustomColorId = useId();
  const itemFontSelId = useId();
  const itemTextInpId = useId();
  const itemCustomColorId = useId();

  const currentJournal = useMemo(
    () => journals.find((j) => j.id === journalId) || journals[0] || null,
    [journals, journalId],
  );
  const activeFamily = currentJournal?.family_id || "nature";
  const familyJournals = useMemo(
    () => journals.filter((j) => j.family_id === activeFamily),
    [journals, activeFamily],
  );

  const focusedPanel = useMemo(
    () => panels.find((p) => p.panel_id === focusedPanelId) || panels[0] || null,
    [panels, focusedPanelId],
  );
  const focusedSlot = useMemo(
    () => composed?.slots.find((s) => s.panel_id === focusedPanel?.panel_id) || null,
    [composed, focusedPanel],
  );
  const focusedIsLocked = focusedPanel
    ? (lockedOverrides[focusedPanel.panel_id] ?? focusedPanel.locked_special)
    : false;
  const focusedRoi = focusedPanel
    ? roiOverrides[focusedPanel.panel_id] || focusedPanel.default_roi
    : null;
  const focusedOv = focusedPanel
    ? panelOverrides[focusedPanel.panel_id] || DEFAULT_PANEL_OVERRIDE
    : DEFAULT_PANEL_OVERRIDE;

  const slotTextItems = focusedSlot?.text_items || [];
  const activeTextItem = useMemo(
    () =>
      focusedTextKey
        ? slotTextItems.find((ti) => ti.item_key === focusedTextKey) || null
        : null,
    [slotTextItems, focusedTextKey],
  );
  const activeTextOv =
    activeTextItem && focusedOv.text_overrides
      ? focusedOv.text_overrides[activeTextItem.item_key] || DEFAULT_TEXT_ITEM_OVERRIDE
      : DEFAULT_TEXT_ITEM_OVERRIDE;
  const customizedCount = Object.keys(focusedOv.text_overrides || {}).length;

  const isInVerticalStack = useMemo(() => {
    if (!focusedPanel || !composed) return false;
    return composed.bento_rows.some((r) =>
      r.blocks.some((b) => b.panel_ids.length > 1 && b.panel_ids.includes(focusedPanel.panel_id)),
    );
  }, [composed, focusedPanel]);

  const panelShortName = focusedSlot?.tag_label
    ? t("layoutStudio.right.slotHeadingTagged", { tag: focusedSlot.tag_label.toUpperCase() })
    : t("layoutStudio.right.slotHeadingUntagged");

  const handleFamilyChange = (fam: string): void => {
    const candidates = journals.filter((j) => j.family_id === fam);
    if (!candidates.length) return;
    const preferredTier = currentJournal?.tier_id || "full";
    const match =
      candidates.find((c) => c.tier_id === preferredTier) ||
      candidates.find((c) => c.tier_id === "full") ||
      candidates[0];
    applyJournalPreset(match.id);
  };

  const handleQuickJournalAutopilot = (fam: "nature" | "science" | "cell" | "nejm"): void => {
    const candidates = journals.filter((j) => j.family_id === fam);
    const match = candidates.find((c) => c.tier_id === "full") || candidates[0];
    if (match) {
      applyJournalPreset(match.id);
    }
    setLayoutMode(fam === "nejm" ? "uniform_3col" : "auto_bento");
    setTypographyField({ hoistSharedLegends: true });
  };

  return (
    <aside
      className={`dq-right-sidebar dq-layout-right${
        inspectorDrawerOpen ? " dq-right-sidebar--open" : ""
      }`}
      aria-label={t("layoutStudio.a11y.inspectorRegion")}
    >
      <div className="dq-layout-drawer-head dq-drawer-trigger">
        <span>{t("layoutStudio.topbar.inspectorDrawer")}</span>
        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("layoutStudio.a11y.closeInspector")}
          title={t("layoutStudio.a11y.closeInspector")}
          onClick={() => setInspectorDrawerOpen(false)}
        >
          <X size={15} strokeWidth={1.6} aria-hidden="true" />
        </button>
      </div>

      {/* Apple Keynote Top Segmented Switch: Page & Grid vs Selected Panel */}
      <div className="dq-keynote-bar">
        <div className="dq-keynote-seg" role="tablist" aria-label={t("layoutStudio.a11y.inspectorRegion")}>
          <button
            type="button"
            role="tab"
            className="dq-keynote-seg__btn"
            aria-selected={inspectorTab === "page"}
            onClick={() => setInspectorTab("page")}
          >
            {t("layoutStudio.right.tabPage")}
          </button>
          <button
            type="button"
            role="tab"
            className="dq-keynote-seg__btn"
            aria-selected={inspectorTab === "panel"}
            onClick={() => setInspectorTab("panel")}
          >
            {t("layoutStudio.right.tabPanel", { name: panelShortName })}
          </button>
        </div>
      </div>

      {inspectorTab === "page" ? (
        <div className="dq-layout-scroll">
          {/* Foolproof One-Click Journal Layout Card */}
          <div className="dq-autopilot-card dq-autopilot-card--layout">
            <div className="dq-autopilot-card__head">
              <span className="dq-autopilot-card__title">
                <Sparkles size={13} strokeWidth={1.7} aria-hidden="true" />
                <span>{t("layoutStudio.right.quickHeading")}</span>
              </span>
            </div>
            <p className="dq-autopilot-card__sub">{t("layoutStudio.right.quickSub")}</p>
            <div className="dq-autopilot-grid">
              {(["nature", "science", "cell", "nejm"] as const).map((qf) => {
                const isActiveQuick =
                  activeFamily === qf && currentJournal?.tier_id === "full";
                return (
                  <button
                    key={qf}
                    type="button"
                    className="dq-autopilot-pill"
                    aria-pressed={isActiveQuick}
                    onClick={() => handleQuickJournalAutopilot(qf)}
                  >
                    {t(`layoutStudio.right.quickPresets.${qf}`)}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Section 1: Journal Family, Column Tier & Grid Architecture */}
          <section className="dq-layout-block">
            <h3 className="dq-layout-block__title">{t("layoutStudio.right.journalSection")}</h3>

            <div className="dq-layout-field">
              <label htmlFor={famSelId}>{t("layoutStudio.right.journalFamilyLabel")}</label>
              <select
                id={famSelId}
                value={activeFamily}
                onChange={(e) => handleFamilyChange(e.target.value)}
              >
                {FAMILY_ORDER.map((fid) => (
                  <option key={fid} value={fid}>
                    {t(`layoutStudio.right.families.${fid}`)}
                  </option>
                ))}
              </select>
            </div>

            {familyJournals.length > 0 && activeFamily !== "custom" ? (
              <div className="dq-layout-field">
                <label htmlFor={tierSelId}>{t("layoutStudio.right.journalColTierLabel")}</label>
                <select
                  id={tierSelId}
                  value={journalId}
                  onChange={(e) => applyJournalPreset(e.target.value)}
                >
                  {familyJournals.map((j) => (
                    <option key={j.id} value={j.id}>
                      {t(`layoutStudio.right.tiers.${j.tier_id}`, { mm: j.width_mm })}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            {journalId === "custom_canvas" ? (
              <div className="dq-layout-grid-2">
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.customWidthLabel", { val: Math.round(customWidthMm) })}
                  </label>
                  <input
                    type="range"
                    min={55}
                    max={220}
                    step={1}
                    value={customWidthMm}
                    onChange={(e) => setCustomDimensions({ customWidthMm: Number(e.target.value) })}
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.customHeightLabel", {
                      val: Math.round(customMaxHeightMm),
                    })}
                  </label>
                  <input
                    type="range"
                    min={90}
                    max={270}
                    step={2}
                    value={customMaxHeightMm}
                    onChange={(e) =>
                      setCustomDimensions({ customMaxHeightMm: Number(e.target.value) })
                    }
                  />
                </div>
              </div>
            ) : null}

            <div className="dq-layout-modes">
              {MODE_IDS.map((mid) => (
                <button
                  key={mid}
                  type="button"
                  className="dq-layout-mode-card"
                  aria-pressed={layoutMode === mid}
                  onClick={() => setLayoutMode(mid)}
                >
                  <span className="dq-layout-mode-card__title">
                    {t(`layoutStudio.right.layoutModes.${mid}.title`)}
                  </span>
                  <span className="dq-layout-mode-card__desc">
                    {t(`layoutStudio.right.layoutModes.${mid}.desc`)}
                  </span>
                </button>
              ))}
            </div>
          </section>

          {/* Disclosure 1: Numbering Flow, Gutter & Legend Merge */}
          <details className="dq-keynote-acc">
            <summary className="dq-keynote-acc__sum">
              <span className="dq-keynote-acc__lead">
                <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("layoutStudio.right.secFlowAndSpacing")}</span>
              </span>
              <span className="dq-style-pill">
                {`${
                  tagFlow === "row_major"
                    ? t("layoutStudio.right.flowRowShort")
                    : t("layoutStudio.right.flowColShort")
                } · ${gutterMm.toFixed(1)} mm`}
              </span>
            </summary>
            <div className="dq-keynote-acc__body">
              <div className="dq-layout-grid-2">
                <div className="dq-layout-field">
                  <label htmlFor={flowSelId}>{t("layoutStudio.right.tagFlowLabel")}</label>
                  <select
                    id={flowSelId}
                    value={tagFlow}
                    onChange={(e) => setTagFlow(e.target.value as "row_major" | "col_major")}
                  >
                    <option value="row_major">{t("layoutStudio.right.tagFlowRow")}</option>
                    <option value="col_major">{t("layoutStudio.right.tagFlowCol")}</option>
                  </select>
                </div>
                <div className="dq-layout-field">
                  <label htmlFor={caseSelId}>{t("layoutStudio.right.tagCaseLabel")}</label>
                  <select
                    id={caseSelId}
                    value={tagCaseOverride || "auto"}
                    onChange={(e) => {
                      const v = e.target.value;
                      setTagCaseOverride(v === "auto" ? null : (v as "lower" | "upper"));
                    }}
                  >
                    <option value="auto">{t("layoutStudio.right.tagCaseAuto")}</option>
                    <option value="upper">{t("layoutStudio.right.tagCaseUpper")}</option>
                    <option value="lower">{t("layoutStudio.right.tagCaseLower")}</option>
                  </select>
                </div>
              </div>

              <div className="dq-layout-field">
                <label>{t("layoutStudio.right.gutterLabel", { val: gutterMm.toFixed(1) })}</label>
                <input
                  type="range"
                  min={2.0}
                  max={5.5}
                  step={0.2}
                  value={gutterMm}
                  onChange={(e) => setTypographyField({ gutterMm: Number(e.target.value) })}
                />
              </div>

              <div className="dq-layout-checks-inline">
                <label className="dq-layout-check-label">
                  <input
                    type="checkbox"
                    checked={hoistSharedLegends}
                    onChange={(e) => setTypographyField({ hoistSharedLegends: e.target.checked })}
                  />
                  <span>{t("layoutStudio.right.mergeLegends")}</span>
                </label>
                <label className="dq-layout-check-label">
                  <input
                    type="checkbox"
                    checked={showPanelTitles}
                    onChange={(e) => setTypographyField({ showPanelTitles: e.target.checked })}
                  />
                  <span>{t("layoutStudio.right.showTitles")}</span>
                </label>
              </div>
            </div>
          </details>

          {/* Disclosure 2: Global Typography & Line Weights */}
          <details className="dq-keynote-acc">
            <summary className="dq-keynote-acc__sum">
              <span className="dq-keynote-acc__lead">
                <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("layoutStudio.right.typoSection")}</span>
              </span>
              <span className="dq-style-pill">
                {`${fontFamily} · ${tickPt.toFixed(1)} pt`}
              </span>
            </summary>
            <div className="dq-keynote-acc__body">
              <div className="dq-layout-field">
                <label htmlFor={fontSelId}>{t("layoutStudio.right.fontFamilyLabel")}</label>
                <select
                  id={fontSelId}
                  value={fontFamily}
                  onChange={(e) => setTypographyField({ fontFamily: e.target.value })}
                >
                  {fontFamilies.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>

              <div className="dq-layout-grid-2">
                <div className="dq-layout-field">
                  <label>{t("layoutStudio.right.tagPtLabel", { val: tagPt.toFixed(1) })}</label>
                  <input
                    type="range"
                    min={7.0}
                    max={10.0}
                    step={0.5}
                    value={tagPt}
                    onChange={(e) => setTypographyField({ tagPt: Number(e.target.value) })}
                  />
                </div>
                <div className="dq-layout-field">
                  <label>{t("layoutStudio.right.titlePtLabel", { val: titlePt.toFixed(1) })}</label>
                  <input
                    type="range"
                    min={5.5}
                    max={8.5}
                    step={0.2}
                    value={titlePt}
                    onChange={(e) => setTypographyField({ titlePt: Number(e.target.value) })}
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.axisTitlePtLabel", { val: axisTitlePt.toFixed(1) })}
                  </label>
                  <input
                    type="range"
                    min={5.5}
                    max={8.0}
                    step={0.25}
                    value={axisTitlePt}
                    onChange={(e) => setTypographyField({ axisTitlePt: Number(e.target.value) })}
                  />
                </div>
                <div className="dq-layout-field">
                  <label>{t("layoutStudio.right.tickPtLabel", { val: tickPt.toFixed(1) })}</label>
                  <input
                    type="range"
                    min={5.0}
                    max={7.5}
                    step={0.2}
                    value={tickPt}
                    onChange={(e) => setTypographyField({ tickPt: Number(e.target.value) })}
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.axisStrokeLabel", { val: axisStrokePt.toFixed(2) })}
                  </label>
                  <input
                    type="range"
                    min={0.3}
                    max={1.0}
                    step={0.05}
                    value={axisStrokePt}
                    onChange={(e) => setTypographyField({ axisStrokePt: Number(e.target.value) })}
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.dataStrokeLabel", { val: dataStrokePt.toFixed(2) })}
                  </label>
                  <input
                    type="range"
                    min={0.4}
                    max={1.2}
                    step={0.05}
                    value={dataStrokePt}
                    onChange={(e) => setTypographyField({ dataStrokePt: Number(e.target.value) })}
                  />
                </div>
              </div>
            </div>
          </details>

          {/* Disclosure 3: Quality Verification Summary */}
          {composed ? (
            <details
              className="dq-keynote-acc"
              open={composed.audit.passed_count < composed.audit.total_count}
            >
              <summary className="dq-keynote-acc__sum">
                <span className="dq-keynote-acc__lead">
                  <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                  <span>
                    {t("layoutStudio.right.checksSection", {
                      passed: composed.audit.passed_count,
                      total: composed.audit.total_count,
                    })}
                  </span>
                </span>
                <span
                  className={`dq-style-pill${
                    composed.audit.passed_count === composed.audit.total_count
                      ? " dq-style-pill--pass"
                      : ""
                  }`}
                >
                  {`${composed.audit.passed_count}/${composed.audit.total_count}`}
                </span>
              </summary>
              <div className="dq-keynote-acc__body">
                <div className="dq-layout-checks">
                  {composed.audit.gates.map((g) => (
                    <div key={g.id} className="dq-layout-check-row">
                      <span className="dq-layout-check-row__name">
                        <Check
                          size={12}
                          strokeWidth={2}
                          color={g.passed ? "#111827" : "#B91C1C"}
                          aria-hidden="true"
                        />
                        <span>{t(`layoutStudio.right.checks.${g.id}`)}</span>
                      </span>
                      <span className="dq-layout-check-row__val">{g.metric.split(" (")[0]}</span>
                    </div>
                  ))}
                </div>
              </div>
            </details>
          ) : null}
        </div>
      ) : focusedPanel ? (
        <div className="dq-layout-scroll">
          {/* Per-Panel Inspector Header */}
          <section className="dq-layout-block">
            <div className="dq-layout-panel-head">
              <div>
                <h3 className="dq-layout-block__title">{panelShortName}</h3>
                <span className="dq-layout-panel-fname">{focusedPanel.filename}</span>
              </div>
              <div className="dq-layout-panel-actions">
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost dq-layout-mini-btn"
                  onClick={() => setInspectorTab("page")}
                >
                  <ArrowLeft size={12} strokeWidth={1.6} aria-hidden="true" />
                  <span>{t("layoutStudio.right.backToPageBtn")}</span>
                </button>
                {isInVerticalStack ? (
                  <button
                    type="button"
                    className="dq-btn dq-btn--ghost dq-layout-mini-btn"
                    onClick={() => unstackPanel(focusedPanel.panel_id)}
                  >
                    <SplitSquareHorizontal size={12} strokeWidth={1.6} aria-hidden="true" />
                    <span>{t("layoutStudio.right.unstackBtn")}</span>
                  </button>
                ) : null}
                <button
                  type="button"
                  className="dq-btn dq-btn--ghost dq-layout-mini-btn"
                  onClick={() => resetPanelOverride(focusedPanel.panel_id)}
                >
                  <RotateCcw size={12} strokeWidth={1.6} aria-hidden="true" />
                  <span>{t("layoutStudio.right.resetPanelBtn")}</span>
                </button>
              </div>
            </div>

            <div className="dq-layout-grid-2">
              <div className="dq-layout-field">
                <label htmlFor={tagInputId}>{t("layoutStudio.right.customTagLabel")}</label>
                <input
                  id={tagInputId}
                  type="text"
                  maxLength={6}
                  disabled={focusedOv.custom_tag === ""}
                  value={focusedOv.custom_tag ?? ""}
                  placeholder={t("layoutStudio.right.customTagPlaceholder", {
                    auto: focusedSlot?.tag_label || "A",
                  })}
                  onChange={(e) => {
                    const val = e.target.value;
                    updatePanelOverride(focusedPanel.panel_id, {
                      custom_tag: val.length > 0 ? val : null,
                    });
                  }}
                />
              </div>

              <div className="dq-layout-field">
                <label htmlFor={spanSelId}>{t("layoutStudio.right.spanLabel")}</label>
                <select
                  id={spanSelId}
                  value={spanOverrides[focusedPanel.panel_id] || 0}
                  onChange={(e) => setSpanOverride(focusedPanel.panel_id, Number(e.target.value))}
                >
                  <option value={0}>
                    {t("layoutStudio.right.spanAuto", { cols: focusedSlot?.col_span ?? 4 })}
                  </option>
                  <option value={3}>{t("layoutStudio.right.span3")}</option>
                  <option value={4}>{t("layoutStudio.right.span4")}</option>
                  <option value={5}>{t("layoutStudio.right.span5")}</option>
                  <option value={6}>{t("layoutStudio.right.span6")}</option>
                  <option value={8}>{t("layoutStudio.right.span8")}</option>
                  <option value={12}>{t("layoutStudio.right.span12")}</option>
                </select>
              </div>
            </div>

            <div className="dq-layout-checks-inline">
              <label className="dq-layout-check-label">
                <input
                  type="checkbox"
                  checked={focusedOv.custom_tag === ""}
                  onChange={(e) =>
                    updatePanelOverride(focusedPanel.panel_id, {
                      custom_tag: e.target.checked ? "" : null,
                    })
                  }
                />
                <span>{t("layoutStudio.right.hideTagToggle")}</span>
              </label>

              {!focusedIsLocked ? (
                <label className="dq-layout-check-label">
                  <input
                    type="checkbox"
                    checked={focusedOv.show_title ?? showPanelTitles}
                    onChange={(e) =>
                      updatePanelOverride(focusedPanel.panel_id, {
                        show_title: e.target.checked,
                      })
                    }
                  />
                  <span>{t("layoutStudio.right.showPanelTitleToggle")}</span>
                </label>
              ) : null}

              <label className="dq-layout-check-label">
                <input
                  type="checkbox"
                  checked={focusedIsLocked}
                  disabled={focusedPanel.locked_special}
                  onChange={(e) => setLockedOverride(focusedPanel.panel_id, e.target.checked)}
                />
                <span>{t("layoutStudio.right.lockAspect")}</span>
              </label>
            </div>
            {focusedPanel.locked_special ? (
              <p className="dq-layout-hint">{t("layoutStudio.right.lockEnforcedHint")}</p>
            ) : null}
          </section>

          {/* Disclosure: Individual Single-Text / Single-Tick / Single-Legend-Item Precision Styling */}
          {slotTextItems.length > 0 ? (
            <details className="dq-keynote-acc" open={Boolean(activeTextItem)}>
              <summary className="dq-keynote-acc__sum">
                <span className="dq-keynote-acc__lead">
                  <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                  <span>{t("layoutStudio.right.singleTextHeading")}</span>
                </span>
                {customizedCount > 0 ? (
                  <span className="dq-style-pill dq-style-pill--active">{customizedCount}</span>
                ) : null}
              </summary>
              <div className="dq-keynote-acc__body">
                {customizedCount > 0 ? (
                  <div className="dq-layout-panel-actions">
                    <button
                      type="button"
                      className="dq-btn dq-btn--ghost dq-layout-mini-btn"
                      onClick={() => resetTextItemOverride(focusedPanel.panel_id)}
                    >
                      <RotateCcw size={11} strokeWidth={1.6} aria-hidden="true" />
                      <span>{t("layoutStudio.right.singleResetAll", { count: customizedCount })}</span>
                    </button>
                  </div>
                ) : null}

                <p className="dq-layout-hint">{t("layoutStudio.right.singleTextHint")}</p>

                <div
                  role="group"
                  aria-label={t("layoutStudio.right.singleTextHeading")}
                  className="dq-layout-token-pool"
                >
                  {slotTextItems.map((ti) => {
                    const isSel = focusedTextKey === ti.item_key;
                    const hasCustom = Boolean(focusedOv.text_overrides?.[ti.item_key]);
                    return (
                      <button
                        key={ti.item_key}
                        type="button"
                        className={`dq-btn dq-layout-token-chip${
                          hasCustom ? " dq-layout-token-chip--edited" : ""
                        }`}
                        aria-pressed={isSel}
                        onClick={() =>
                          setFocusedText(focusedPanel.panel_id, isSel ? null : ti.item_key, true)
                        }
                      >
                        <span
                          className="dq-layout-color-chip__dot"
                          style={{ backgroundColor: ti.fill }}
                          aria-hidden="true"
                        />
                        <span className="dq-layout-token-chip__lbl">{ti.text}</span>
                      </button>
                    );
                  })}
                </div>

                {activeTextItem ? (
                  <div className="dq-layout-highlight-box dq-layout-single-editor">
                    <div className="dq-layout-panel-head">
                      <strong>
                        {t("layoutStudio.right.singleEditingNow", { text: activeTextItem.text })}
                      </strong>
                      <div className="dq-layout-panel-actions">
                        <button
                          type="button"
                          className="dq-btn dq-btn--ghost dq-layout-mini-btn"
                          onClick={() =>
                            resetTextItemOverride(focusedPanel.panel_id, activeTextItem.item_key)
                          }
                        >
                          <RotateCcw size={11} strokeWidth={1.6} aria-hidden="true" />
                          <span>{t("layoutStudio.right.singleResetOne")}</span>
                        </button>
                        <button
                          type="button"
                          className="dq-btn dq-btn--ghost dq-layout-mini-btn"
                          aria-label={t("layoutStudio.canvas.txtCloseItem")}
                          title={t("layoutStudio.canvas.txtCloseItem")}
                          onClick={() => setFocusedText(focusedPanel.panel_id, null, true)}
                        >
                          <X size={11} strokeWidth={1.7} aria-hidden="true" />
                        </button>
                      </div>
                    </div>

                    <div className="dq-layout-field">
                      <span>{t("layoutStudio.right.singleColorLabel")}</span>
                      <div
                        role="group"
                        aria-label={t("layoutStudio.right.singleColorLabel")}
                        className="dq-layout-color-chips"
                      >
                        {activeTextItem.swatch_color ? (
                          <button
                            type="button"
                            className="dq-btn dq-layout-color-chip"
                            aria-pressed={activeTextOv.color === "SWATCH"}
                            onClick={() =>
                              updateTextItemOverride(
                                focusedPanel.panel_id,
                                activeTextItem.item_key,
                                { color: activeTextOv.color === "SWATCH" ? null : "SWATCH" },
                              )
                            }
                          >
                            <span
                              className="dq-layout-color-chip__dot"
                              style={{ backgroundColor: activeTextItem.swatch_color }}
                              aria-hidden="true"
                            />
                            <span>{t("layoutStudio.right.legendColorMatch")}</span>
                          </button>
                        ) : null}

                        {SINGLE_ITEM_COLORS.map((cp) => {
                          const isSw =
                            activeTextOv.color !== "SWATCH" &&
                            activeTextItem.fill.toUpperCase() === cp.hex;
                          return (
                            <button
                              key={cp.id}
                              type="button"
                              className="dq-btn dq-layout-color-chip"
                              aria-pressed={isSw}
                              onClick={() =>
                                updateTextItemOverride(
                                  focusedPanel.panel_id,
                                  activeTextItem.item_key,
                                  { color: cp.hex },
                                )
                              }
                            >
                              <span
                                className="dq-layout-color-chip__dot"
                                style={{ backgroundColor: cp.hex }}
                                aria-hidden="true"
                              />
                              <span>{t(`layoutStudio.right.singleColors.${cp.id}`)}</span>
                            </button>
                          );
                        })}

                        <label className="dq-layout-color-picker" htmlFor={itemCustomColorId}>
                          <input
                            id={itemCustomColorId}
                            type="color"
                            value={
                              activeTextOv.color && activeTextOv.color.startsWith("#")
                                ? activeTextOv.color
                                : activeTextItem.fill
                            }
                            aria-label={t("layoutStudio.right.legendColorCustom")}
                            onChange={(e) =>
                              updateTextItemOverride(
                                focusedPanel.panel_id,
                                activeTextItem.item_key,
                                { color: e.target.value },
                              )
                            }
                          />
                          <span>{t("layoutStudio.right.legendColorCustom")}</span>
                        </label>
                      </div>
                    </div>

                    <div className="dq-layout-grid-2">
                      <div className="dq-layout-field">
                        <label htmlFor={itemFontSelId}>
                          {t("layoutStudio.right.singleFontLabel")}
                        </label>
                        <select
                          id={itemFontSelId}
                          value={activeTextOv.font_family ?? ""}
                          onChange={(e) =>
                            updateTextItemOverride(focusedPanel.panel_id, activeTextItem.item_key, {
                              font_family: e.target.value || null,
                            })
                          }
                        >
                          <option value="">{t("layoutStudio.right.legendFontFollow")}</option>
                          {fontFamilies.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.singleScaleLabel", {
                            val: Math.round((activeTextOv.font_scale || 1.0) * 100),
                          })}
                        </label>
                        <input
                          type="range"
                          min={0.7}
                          max={1.5}
                          step={0.05}
                          value={activeTextOv.font_scale || 1.0}
                          onChange={(e) =>
                            updateTextItemOverride(focusedPanel.panel_id, activeTextItem.item_key, {
                              font_scale: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                    </div>

                    <div className="dq-layout-checks-inline">
                      <label className="dq-layout-check-label">
                        <input
                          type="checkbox"
                          checked={activeTextItem.bold}
                          onChange={(e) =>
                            updateTextItemOverride(focusedPanel.panel_id, activeTextItem.item_key, {
                              bold: e.target.checked,
                            })
                          }
                        />
                        <span>{t("layoutStudio.right.singleBoldToggle")}</span>
                      </label>
                      <label className="dq-layout-check-label">
                        <input
                          type="checkbox"
                          checked={activeTextItem.italic}
                          onChange={(e) =>
                            updateTextItemOverride(focusedPanel.panel_id, activeTextItem.item_key, {
                              italic: e.target.checked,
                            })
                          }
                        />
                        <span>{t("layoutStudio.right.singleItalicToggle")}</span>
                      </label>
                    </div>

                    <div className="dq-layout-field">
                      <label htmlFor={itemTextInpId}>
                        {t("layoutStudio.right.singleTextInputLabel")}
                      </label>
                      <input
                        id={itemTextInpId}
                        type="text"
                        value={activeTextOv.text ?? ""}
                        placeholder={activeTextItem.orig_text}
                        onChange={(e) =>
                          updateTextItemOverride(focusedPanel.panel_id, activeTextItem.item_key, {
                            text: e.target.value.length > 0 ? e.target.value : null,
                          })
                        }
                      />
                    </div>
                  </div>
                ) : null}
              </div>
            </details>
          ) : null}

          {/* Disclosure: Per-Panel Legend Placement, Orientation & Typography/Color Emphasis */}
          {!focusedIsLocked && (focusedPanel.has_legend || focusedSlot?.has_legend) ? (
            <details className="dq-keynote-acc">
              <summary className="dq-keynote-acc__sum">
                <span className="dq-keynote-acc__lead">
                  <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                  <span>{t("layoutStudio.right.legendHeading")}</span>
                </span>
                <span className="dq-style-pill">
                  {t(`layoutStudio.right.legendOrient.${focusedOv.legend_orient}`)}
                </span>
              </summary>
              <div className="dq-keynote-acc__body">
                <div className="dq-layout-field">
                  <label htmlFor={legPosSelId}>{t("layoutStudio.right.legendPosLabel")}</label>
                  <select
                    id={legPosSelId}
                    value={focusedOv.legend_pos}
                    onChange={(e) => {
                      const nextPos = e.target.value as LegendPosMode;
                      updatePanelOverride(focusedPanel.panel_id, {
                        legend_pos: nextPos,
                        ...(nextPos === "top" || nextPos === "bottom" || nextPos === "right"
                          ? { legend_orient: "auto" }
                          : {}),
                      });
                    }}
                  >
                    {LEGEND_POS_IDS.map((lid) => (
                      <option key={lid} value={lid}>
                        {t(`layoutStudio.right.legendPos.${lid}`)}
                      </option>
                    ))}
                  </select>
                </div>

                {focusedOv.legend_pos !== "hidden" ? (
                  <>
                    <div className="dq-layout-field">
                      <span>{t("layoutStudio.right.legendOrientLabel")}</span>
                      <div
                        role="group"
                        aria-label={t("layoutStudio.right.legendOrientLabel")}
                        className="dq-layout-seg-row"
                      >
                        {LEGEND_ORIENT_IDS.map((oid) => (
                          <button
                            key={oid}
                            type="button"
                            className="dq-btn dq-layout-seg-btn"
                            aria-pressed={focusedOv.legend_orient === oid}
                            onClick={() =>
                              updatePanelOverride(focusedPanel.panel_id, {
                                legend_orient: oid,
                              })
                            }
                          >
                            {t(`layoutStudio.right.legendOrient.${oid}`)}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="dq-layout-grid-2">
                      <div className="dq-layout-field">
                        <label htmlFor={legFontSelId}>
                          {t("layoutStudio.right.legendFontLabel")}
                        </label>
                        <select
                          id={legFontSelId}
                          value={focusedOv.legend_font_family ?? ""}
                          onChange={(e) =>
                            updatePanelOverride(focusedPanel.panel_id, {
                              legend_font_family: e.target.value || null,
                            })
                          }
                        >
                          <option value="">{t("layoutStudio.right.legendFontFollow")}</option>
                          {fontFamilies.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.pLegendScale", {
                            val: Math.round(focusedOv.legend_scale * 100),
                          })}
                        </label>
                        <input
                          type="range"
                          min={0.65}
                          max={1.45}
                          step={0.05}
                          value={focusedOv.legend_scale}
                          onChange={(e) =>
                            updatePanelOverride(focusedPanel.panel_id, {
                              legend_scale: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                    </div>

                    {!(focusedSlot?.is_colorbar || focusedPanel.is_colorbar) &&
                    focusedOv.legend_orient === "auto" ? (
                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.pLegendCols", { val: focusedOv.legend_cols })}
                        </label>
                        <input
                          type="range"
                          min={1}
                          max={3}
                          step={1}
                          value={focusedOv.legend_cols}
                          onChange={(e) =>
                            updatePanelOverride(focusedPanel.panel_id, {
                              legend_cols: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                    ) : null}

                    <div className="dq-layout-field">
                      <span>{t("layoutStudio.right.legendColorLabel")}</span>
                      <div
                        role="group"
                        aria-label={t("layoutStudio.right.legendColorLabel")}
                        className="dq-layout-color-chips"
                      >
                        {!(focusedSlot?.is_colorbar || focusedPanel.is_colorbar) ? (
                          <button
                            type="button"
                            className="dq-btn dq-layout-color-chip"
                            aria-pressed={focusedOv.legend_match_swatch}
                            onClick={() =>
                              updatePanelOverride(focusedPanel.panel_id, {
                                legend_match_swatch: !focusedOv.legend_match_swatch,
                              })
                            }
                          >
                            <span className="dq-layout-color-chip__multi" aria-hidden="true" />
                            <span>{t("layoutStudio.right.legendColorMatch")}</span>
                          </button>
                        ) : null}

                        {LEGEND_COLOR_PRESETS.map((cp) => {
                          const isSel =
                            !focusedOv.legend_match_swatch &&
                            focusedOv.legend_text_color.toUpperCase() === cp.hex;
                          return (
                            <button
                              key={cp.id}
                              type="button"
                              className="dq-btn dq-layout-color-chip"
                              aria-pressed={isSel}
                              onClick={() =>
                                updatePanelOverride(focusedPanel.panel_id, {
                                  legend_match_swatch: false,
                                  legend_text_color: cp.hex,
                                })
                              }
                            >
                              <span
                                className="dq-layout-color-chip__dot"
                                style={{ backgroundColor: cp.hex }}
                                aria-hidden="true"
                              />
                              <span>{t(`layoutStudio.right.legendColors.${cp.id}`)}</span>
                            </button>
                          );
                        })}

                        <label className="dq-layout-color-picker" htmlFor={legCustomColorId}>
                          <input
                            id={legCustomColorId}
                            type="color"
                            value={focusedOv.legend_text_color}
                            aria-label={t("layoutStudio.right.legendColorCustom")}
                            onChange={(e) =>
                              updatePanelOverride(focusedPanel.panel_id, {
                                legend_match_swatch: false,
                                legend_text_color: e.target.value,
                              })
                            }
                          />
                          <span>{t("layoutStudio.right.legendColorCustom")}</span>
                        </label>
                      </div>
                    </div>

                    <div className="dq-layout-checks-inline">
                      <label className="dq-layout-check-label">
                        <input
                          type="checkbox"
                          checked={focusedOv.legend_bold}
                          onChange={(e) =>
                            updatePanelOverride(focusedPanel.panel_id, {
                              legend_bold: e.target.checked,
                            })
                          }
                        />
                        <span>{t("layoutStudio.right.legendBoldToggle")}</span>
                      </label>
                      <label className="dq-layout-check-label">
                        <input
                          type="checkbox"
                          checked={focusedOv.legend_bg}
                          onChange={(e) =>
                            updatePanelOverride(focusedPanel.panel_id, {
                              legend_bg: e.target.checked,
                            })
                          }
                        />
                        <span>{t("layoutStudio.right.legendBgToggle")}</span>
                      </label>
                    </div>
                  </>
                ) : null}
              </div>
            </details>
          ) : null}

          {/* Disclosure: Per-Panel Typography & Lossless Geometry (Vector Plots) */}
          {!focusedIsLocked ? (
            <details className="dq-keynote-acc">
              <summary className="dq-keynote-acc__sum">
                <span className="dq-keynote-acc__lead">
                  <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                  <span>{t("layoutStudio.right.panelScaleHeading")}</span>
                </span>
                <span className="dq-style-pill">{`${Math.round(focusedOv.font_scale * 100)}%`}</span>
              </summary>
              <div className="dq-keynote-acc__body">
                <div className="dq-layout-field">
                  <label htmlFor={pFontSelId}>{t("layoutStudio.right.pFontFamilyLabel")}</label>
                  <select
                    id={pFontSelId}
                    value={focusedOv.panel_font_family ?? ""}
                    onChange={(e) =>
                      updatePanelOverride(focusedPanel.panel_id, {
                        panel_font_family: e.target.value || null,
                      })
                    }
                  >
                    <option value="">
                      {t("layoutStudio.right.pFontFollowPage", { font: fontFamily })}
                    </option>
                    {fontFamilies.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </div>

                {(focusedSlot?.is_categorical_x || focusedPanel.is_categorical_x) ? (
                  <div className="dq-layout-highlight-box">
                    <div className="dq-layout-field">
                      <label>
                        {t("layoutStudio.right.pCategorySpacing", {
                          val: Math.round(focusedOv.category_spacing * 100),
                        })}
                      </label>
                      <input
                        type="range"
                        min={0.35}
                        max={1.2}
                        step={0.05}
                        value={focusedOv.category_spacing}
                        onChange={(e) =>
                          updatePanelOverride(focusedPanel.panel_id, {
                            category_spacing: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <p className="dq-layout-hint">{t("layoutStudio.right.pCategoryHint")}</p>
                  </div>
                ) : null}

                <div className="dq-layout-grid-2">
                  <div className="dq-layout-field">
                    <label>
                      {t("layoutStudio.right.pFontScale", {
                        val: Math.round(focusedOv.font_scale * 100),
                      })}
                    </label>
                    <input
                      type="range"
                      min={0.7}
                      max={1.45}
                      step={0.05}
                      value={focusedOv.font_scale}
                      onChange={(e) =>
                        updatePanelOverride(focusedPanel.panel_id, {
                          font_scale: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                  <div className="dq-layout-field">
                    <label>
                      {t("layoutStudio.right.pMarkerScale", {
                        val: Math.round(focusedOv.marker_scale * 100),
                      })}
                    </label>
                    <input
                      type="range"
                      min={0.5}
                      max={1.8}
                      step={0.05}
                      value={focusedOv.marker_scale}
                      onChange={(e) =>
                        updatePanelOverride(focusedPanel.panel_id, {
                          marker_scale: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                  <div className="dq-layout-field">
                    <label>
                      {t("layoutStudio.right.pStrokeScale", {
                        val: Math.round(focusedOv.stroke_scale * 100),
                      })}
                    </label>
                    <input
                      type="range"
                      min={0.6}
                      max={1.6}
                      step={0.05}
                      value={focusedOv.stroke_scale}
                      onChange={(e) =>
                        updatePanelOverride(focusedPanel.panel_id, {
                          stroke_scale: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                  <div className="dq-layout-field">
                    <label>
                      {t("layoutStudio.right.pFrameWidth", {
                        val: Math.round(focusedOv.frame_width_ratio * 100),
                      })}
                    </label>
                    <input
                      type="range"
                      min={0.5}
                      max={1.0}
                      step={0.02}
                      value={focusedOv.frame_width_ratio}
                      onChange={(e) =>
                        updatePanelOverride(focusedPanel.panel_id, {
                          frame_width_ratio: Number(e.target.value),
                        })
                      }
                    />
                  </div>
                </div>
              </div>
            </details>
          ) : null}

          {/* Disclosure: Per-Panel 4-Side Margin Trim & Special-Figure Vector ROI */}
          <details className="dq-keynote-acc" open={Boolean(focusedIsLocked && focusedRoi?.enabled)}>
            <summary className="dq-keynote-acc__sum">
              <span className="dq-keynote-acc__lead">
                <ChevronDown className="dq-styles-chevron" size={14} strokeWidth={1.6} aria-hidden="true" />
                <span>{t("layoutStudio.right.marginHeading")}</span>
              </span>
              <span className="dq-style-pill">{`${focusedOv.pad_top_mm.toFixed(1)} mm`}</span>
            </summary>
            <div className="dq-keynote-acc__body">
              <div className="dq-layout-grid-2">
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.padTop", { val: focusedOv.pad_top_mm.toFixed(1) })}
                  </label>
                  <input
                    type="range"
                    min={-8.0}
                    max={8.0}
                    step={0.5}
                    value={focusedOv.pad_top_mm}
                    onChange={(e) =>
                      updatePanelOverride(focusedPanel.panel_id, {
                        pad_top_mm: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.padBottom", { val: focusedOv.pad_bottom_mm.toFixed(1) })}
                  </label>
                  <input
                    type="range"
                    min={-8.0}
                    max={8.0}
                    step={0.5}
                    value={focusedOv.pad_bottom_mm}
                    onChange={(e) =>
                      updatePanelOverride(focusedPanel.panel_id, {
                        pad_bottom_mm: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.padLeft", { val: focusedOv.pad_left_mm.toFixed(1) })}
                  </label>
                  <input
                    type="range"
                    min={-8.0}
                    max={8.0}
                    step={0.5}
                    value={focusedOv.pad_left_mm}
                    onChange={(e) =>
                      updatePanelOverride(focusedPanel.panel_id, {
                        pad_left_mm: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div className="dq-layout-field">
                  <label>
                    {t("layoutStudio.right.padRight", { val: focusedOv.pad_right_mm.toFixed(1) })}
                  </label>
                  <input
                    type="range"
                    min={-8.0}
                    max={8.0}
                    step={0.5}
                    value={focusedOv.pad_right_mm}
                    onChange={(e) =>
                      updatePanelOverride(focusedPanel.panel_id, {
                        pad_right_mm: Number(e.target.value),
                      })
                    }
                  />
                </div>
              </div>

              {focusedIsLocked && focusedRoi && !focusedRoi.linked_source_id ? (
                <div className="dq-layout-roi-controls">
                  <label className="dq-layout-check-label">
                    <input
                      type="checkbox"
                      checked={focusedRoi.enabled}
                      onChange={(e) => updateRoi(focusedPanel.panel_id, { enabled: e.target.checked })}
                    />
                    <span>{t("layoutStudio.right.roiToggle")}</span>
                  </label>

                  {focusedRoi.enabled ? (
                    <div className="dq-layout-grid-2">
                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.roiX", { val: Math.round(focusedRoi.x_norm * 100) })}
                        </label>
                        <input
                          type="range"
                          min={0}
                          max={0.85}
                          step={0.01}
                          value={focusedRoi.x_norm}
                          onChange={(e) =>
                            updateRoi(focusedPanel.panel_id, { x_norm: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.roiY", { val: Math.round(focusedRoi.y_norm * 100) })}
                        </label>
                        <input
                          type="range"
                          min={0}
                          max={0.85}
                          step={0.01}
                          value={focusedRoi.y_norm}
                          onChange={(e) =>
                            updateRoi(focusedPanel.panel_id, { y_norm: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.roiW", { val: Math.round(focusedRoi.w_norm * 100) })}
                        </label>
                        <input
                          type="range"
                          min={0.08}
                          max={0.8}
                          step={0.01}
                          value={focusedRoi.w_norm}
                          onChange={(e) =>
                            updateRoi(focusedPanel.panel_id, { w_norm: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="dq-layout-field">
                        <label>
                          {t("layoutStudio.right.roiH", { val: Math.round(focusedRoi.h_norm * 100) })}
                        </label>
                        <input
                          type="range"
                          min={0.08}
                          max={0.8}
                          step={0.01}
                          value={focusedRoi.h_norm}
                          onChange={(e) =>
                            updateRoi(focusedPanel.panel_id, { h_norm: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="dq-layout-field">
                        <label>{t("layoutStudio.right.roiLabel")}</label>
                        <input
                          type="text"
                          value={focusedRoi.label}
                          onChange={(e) => updateRoi(focusedPanel.panel_id, { label: e.target.value })}
                        />
                      </div>
                      <div className="dq-layout-field">
                        <label>{t("layoutStudio.right.roiColor")}</label>
                        <select
                          value={focusedRoi.color}
                          onChange={(e) => updateRoi(focusedPanel.panel_id, { color: e.target.value })}
                        >
                          <option value="#F59E0B">{t("layoutStudio.right.roiColorAmber")}</option>
                          <option value="#38BDF8">{t("layoutStudio.right.roiColorCyan")}</option>
                          <option value="#EF4444">{t("layoutStudio.right.roiColorCrimson")}</option>
                          <option value="#FFFFFF">{t("layoutStudio.right.roiColorWhite")}</option>
                        </select>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {focusedIsLocked && focusedRoi?.linked_source_id ? (
                <p className="dq-layout-hint">
                  {t("layoutStudio.right.roiLinkedNote", { src: focusedRoi.linked_source_id })}
                </p>
              ) : null}
            </div>
          </details>
        </div>
      ) : null}
    </aside>
  );
}
