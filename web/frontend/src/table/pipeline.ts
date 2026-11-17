import type { PaletteItem } from "../types";
import {
  cushionSmallSampleT,
  interpolateRampHex,
  isChromaticPalette,
  orientRampStops,
  pickWcagForeground,
  resolveColumnBarColors,
  resolveTableRamp,
} from "./color";
import type {
  BarDomainMode,
  BarRenderSpec,
  ColumnRole,
  ColumnSpec,
  ColumnVisualMode,
  DerivedMetricKind,
  DomainClipMode,
  FootnoteSpec,
  HeatLegendModel,
  HeatScope,
  MergeSpec,
  RawDataSheetModel,
  RawSnapshot,
  RenderModel,
  RenderedBlock,
  RenderedCell,
  RenderedCellPart,
  RenderedFootnote,
  RenderedHeader,
  RenderedSpanner,
  RowRhythm,
  SpannerSpec,
  StructureLayer,
  StyleLayer,
  TableDoc,
  TablePresetId,
} from "./model";
import {
  buildExcelNumFmt,
  computeSigStars,
  formatNumberFixed,
  formatP,
  parseNumber,
  parseSequence,
  resolvePrecision,
} from "./numeric";

const RATIO_NAME_RE = /\b(OR|HR|RR|odds|hazard|ratio)\b/i;
const DIMENSIONLESS_EFFECT_RE = /\b(log2?fc|lfc|fold[\s_]?change|fc|or|hr|rr|odds|hazard|auc|r2|corr)\b/i;
const LOWER_BETTER_NAME_RE = /\b(RMSE|MAE|MSE|MAPE|NLL|BIC|AIC|IC50|EC50|KD|Ki|error|loss|latency|rank|brier)\b/i;
const SUPERSCRIPT_TOKEN_RE = /\^([a-zA-Z0-9,*†‡§]+)/;
const LEADING_FN_SYM_RE = /^([a-zA-Z*†‡§])\s+(.+)$/;
const TABLE_NUM_PREFIX_RE = /^(Table\s+\d+|表\s*\d+)\s*[.:：·—–-]?\s*(.*)$/i;
const SUMMARY_ROW_EXACT_RE =
  /^(?:total|totals|grand\s+total|subtotal|overall|sum|all(?:\s+(?:patients|subjects|participants|cases|samples|cohorts))?|合计|总计|小计|汇总|全队列|总体)(?:\s*(?:[,:：]\s*(?:n\b.*)?|\([^)]*\)|（[^）]*）|\[[^\]]*\]))?$/i;

export function isSummaryRowLabel(rawLabel: string): boolean {
  const clean = rawLabel.replace(SUPERSCRIPT_TOKEN_RE, "").trim();
  if (!clean) return false;
  return SUMMARY_ROW_EXACT_RE.test(clean);
}

export function inferColumnDirectionHint(label: string): "normal" | "reverse" {
  return LOWER_BETTER_NAME_RE.test(label) ? "reverse" : "normal";
}

export function normalizeLegacyTableDoc(doc: TableDoc): TableDoc {
  const next = structuredClone(doc);
  if (next.structure.excludeSummaryRows === undefined) {
    next.structure.excludeSummaryRows = true;
  }
  if (next.style.heatDomainClip === undefined) {
    next.style.heatDomainClip = "minmax";
  }
  for (const col of next.structure.columns) {
    if (!col.visual) {
      col.visual = "auto";
    }
  }
  return next;
}

function splitInlineSuperscript(raw: string): { clean: string; sup: string } {
  const m = SUPERSCRIPT_TOKEN_RE.exec(raw);
  if (!m) return { clean: raw, sup: "" };
  return {
    clean: raw.replace(SUPERSCRIPT_TOKEN_RE, "").trim(),
    sup: m[1],
  };
}

function leafHeaderName(label: string): string {
  const parts = label.split(" · ");
  return parts[parts.length - 1].trim();
}

export function buildDerivedSparklineColumns(
  derivedId: string,
  srcCols: ColumnSpec[],
  runLabel: string,
): ColumnSpec[] {
  const firstCol = srcCols[0];
  const lastCol = srcCols[srcCols.length - 1];
  const unit = firstCol?.unit ?? "";
  if (srcCols.length >= 4 && firstCol && lastCol) {
    const firstLbl = leafHeaderName(firstCol.label) || "Start";
    const lastLbl = leafHeaderName(lastCol.label) || "End";
    return [
      {
        id: `col_${derivedId}_first`,
        source: { kind: "derived", derivedId, metric: "first" },
        label: firstLbl,
        hidden: false,
        role: "normal",
        precision: "auto",
        unit,
      },
      {
        id: `col_${derivedId}_last`,
        source: { kind: "derived", derivedId, metric: "last" },
        label: lastLbl,
        hidden: false,
        role: "bar",
        precision: "auto",
        unit,
      },
      {
        id: `col_${derivedId}_delta`,
        source: { kind: "derived", derivedId, metric: "delta" },
        label: `Δ ${runLabel}`,
        hidden: false,
        role: "normal",
        precision: 1,
        unit,
      },
      {
        id: `col_${derivedId}`,
        source: { kind: "derived", derivedId, metric: "sparkline" },
        label: runLabel,
        hidden: false,
        role: "normal",
        precision: 1,
        unit,
      },
    ];
  }
  return [
    {
      id: `col_${derivedId}`,
      source: { kind: "derived", derivedId, metric: "sparkline" },
      label: runLabel,
      hidden: false,
      role: "normal",
      precision: 1,
      unit,
    },
  ];
}

export function inferRecommendedStyle(doc: TableDoc): {
  preset: Exclude<TablePresetId, "raw">;
  heatScope?: HeatScope;
  rowRhythm?: RowRhythm;
} {
  const { raw, structure } = doc;
  const sug = raw.suggestions;
  const decimalComma = sug.decimalComma;

  // 1. Wide time-series / sparkline tables -> FT editorial
  if (structure.derived.length > 0 || sug.sparklineRuns.length > 0) {
    return { preset: "ft_editorial" };
  }

  // 2. Detect clinical mixed binary n (%) + continuous Mean ± SD Table 1
  const [b0, b1] = structure.stage === "raw" ? sug.bodyRange : structure.bodyRange;
  const bodySlice: string[][] = [];
  for (let r = Math.max(0, b0); r <= Math.min(raw.grid.length - 1, b1); r++) {
    const row = raw.grid[r];
    if (row && row.some((c) => c.trim() !== "")) bodySlice.push(row);
  }

  const checkMerges =
    structure.merges.length > 0
      ? structure.merges
          .map((m) =>
            m.columnIds
              .map((cid) => structure.columns.find((c) => c.id === cid))
              .filter(
                (c): c is ColumnSpec & { source: { kind: "grid"; col: number } } =>
                  Boolean(c && c.source.kind === "grid"),
              )
              .map((c) => c.source.col),
          )
          .filter((cols) => cols.length >= 2)
      : sug.merges.map((m) => m.sourceCols).filter((cols) => cols.length >= 2);

  let hasBinaryPctRow = false;
  let hasContinuousMergeRow = false;
  for (const mCols of checkMerges) {
    const [c0, c1] = mCols;
    for (const row of bodySlice) {
      const p0 = parseNumber(row[c0] ?? "", decimalComma);
      const p1 = parseNumber(row[c1] ?? "", decimalComma);
      if (p0.value !== null && p1.value !== null) {
        if (Number.isInteger(p0.value) && p1.unit === "%") {
          hasBinaryPctRow = true;
        } else {
          hasContinuousMergeRow = true;
        }
      }
    }
  }
  const activePivot = structure.pivot ?? sug.pivot;
  if (hasBinaryPctRow && hasContinuousMergeRow) {
    return {
      preset: "cns_three_line",
      heatScope: "per_row",
      rowRhythm: Object.keys(structure.rowIndents).length > 0 ? "none" : "zebra",
    };
  }

  // 2b. Non-pivoted contrast / regression / clinical tables with statistical merges -> CNS three-line
  if (!activePivot && checkMerges.length > 0) {
    return {
      preset: "cns_three_line",
      heatScope: "per_row",
      rowRhythm: Object.keys(structure.rowIndents).length > 0 ? "none" : "zebra",
    };
  }

  // 3. Long-to-wide pivoted summary tables (e.g. Palmer Penguins) -> Matrix heatmap
  if (activePivot) {
    const primaryVc = activePivot.valueCols[0];
    const posVals: number[] = [];
    if (primaryVc !== undefined) {
      for (const row of bodySlice) {
        const pn = parseNumber(row[primaryVc] ?? "", decimalComma);
        if (pn.value !== null && Math.abs(pn.value) > 0) {
          posVals.push(Math.abs(pn.value));
        }
      }
    }
    const spanRatio =
      posVals.length >= 2 ? Math.max(...posVals) / Math.max(Math.min(...posVals), 1e-12) : 1;
    return {
      preset: "matrix_heatmap",
      heatScope: spanRatio >= 20 ? "per_row" : "per_column",
    };
  }

  // 4. General numeric matrix vs pure qualitative text table
  const numericDataStats = (raw.columnStats ?? []).filter(
    (st, idx) =>
      st.numericRatio >= 0.5 &&
      st.role !== "sig" &&
      st.role !== "count" &&
      st.role !== "part" &&
      !(idx === 0 && st.numericRatio < 0.6),
  );
  if (numericDataStats.length > 0) {
    const multiScaleCols = numericDataStats.filter((st) => {
      if (st.minVal === null || st.maxVal === null) return false;
      const lo = Math.min(Math.abs(st.minVal), Math.abs(st.maxVal));
      const hi = Math.max(Math.abs(st.minVal), Math.abs(st.maxVal));
      return lo > 0 && hi / lo >= 20;
    });
    return {
      preset: "matrix_heatmap",
      heatScope:
        numericDataStats.length >= 2 && multiScaleCols.length >= 2 ? "per_row" : undefined,
    };
  }

  return { preset: "cns_three_line", rowRhythm: "zebra" };
}

export function createInitialTableDoc(raw: RawSnapshot): TableDoc {
  const nCols = raw.grid[0]?.length ?? 0;
  const h0 = raw.suggestions.headerRows[0] ?? 0;
  const rawHeaderRow = raw.grid[h0] ?? [];

  const columns: ColumnSpec[] = Array.from({ length: nCols }, (_, idx) => {
    const resolved = raw.suggestions.resolvedHeaders?.[idx];
    const fallback = rawHeaderRow[idx]?.trim() || `Col ${idx + 1}`;
    const stat = raw.columnStats?.[idx];
    return {
      id: `c${idx}`,
      source: { kind: "grid", col: idx },
      label: resolved || fallback,
      hidden: false,
      role: "normal",
      visual: "auto",
      precision: "auto",
      unit: stat?.detectedUnit ?? "",
    };
  });

  const structure: StructureLayer = {
    stage: "raw",
    headerRows: [...raw.suggestions.headerRows] as [number, number],
    bodyRange: [...raw.suggestions.bodyRange] as [number, number],
    pivot: null,
    columns,
    spanners: [],
    merges: [],
    derived: [],
    partBy: null,
    partOrder: "appearance",
    sort: [],
    cellOverrides: {},
    rowIndents: {},
    missingToken: "—",
    tableNumber: "Table 1",
    title: "",
    subtitle: "",
    footnotes: [],
    sig: {
      sourceId: null,
      targetIds: [],
      pStyle: "nejm",
      stars: true,
    },
    dismissedSuggestions: [],
    excludeSummaryRows: true,
  };

  const style: StyleLayer = {
    preset: "raw",
    paletteId: "danqing_umi_teal",
    heatScope: "per_column",
    heatCenter: "auto",
    heatLog: false,
    heatDomainClip: "minmax",
    emphasis: "bold_star_mono",
    rowRhythm: "none",
    tabularNums: true,
  };

  return { raw, structure, style };
}

export type SuggestionCategory =
  | "all"
  | "headerRows"
  | "footer"
  | "partBy"
  | "merges"
  | "sig"
  | "sparkline"
  | "pivot";

export function listAvailableSuggestions(doc: TableDoc): SuggestionCategory[] {
  const s = doc.raw.suggestions;
  const dismissed = new Set(doc.structure.dismissedSuggestions);
  const out: SuggestionCategory[] = [];

  const hasMultiHeaderOrTitle =
    s.headerRows[0] > 0 || s.headerRows[1] > s.headerRows[0] || s.spanners.length > 0 || Boolean(s.titleCandidate);
  if (hasMultiHeaderOrTitle && !dismissed.has("headerRows")) out.push("headerRows");
  if (s.footnoteCandidates.length > 0 && !dismissed.has("footer")) out.push("footer");
  if (s.pivot && !dismissed.has("pivot")) {
    out.push("pivot");
  } else {
    if (s.partBy !== null && !dismissed.has("partBy")) out.push("partBy");
    if (s.merges.length > 0 && !dismissed.has("merges")) out.push("merges");
  }
  if (s.sparklineRuns.length > 0 && !dismissed.has("sparkline")) out.push("sparkline");
  const hasSig = Object.values(s.roles).some((r) => r === "sig");
  if (hasSig && !dismissed.has("sig")) out.push("sig");

  return out;
}

export function listUnappliedSuggestions(doc: TableDoc): SuggestionCategory[] {
  const s = doc.raw.suggestions;
  const st = doc.structure;
  const dismissed = new Set(st.dismissedSuggestions);
  const out: SuggestionCategory[] = [];

  const needHeaderOrSpanner =
    (s.spanners.length > 0 && st.spanners.length === 0 && !st.pivot) ||
    (Boolean(s.titleCandidate) && !st.title);
  if (needHeaderOrSpanner && !dismissed.has("headerRows")) out.push("headerRows");

  if (s.footnoteCandidates.length > 0 && st.footnotes.length === 0 && !dismissed.has("footer")) {
    out.push("footer");
  }
  if (s.pivot && !st.pivot && !dismissed.has("pivot")) {
    out.push("pivot");
  } else if (!s.pivot) {
    if (s.partBy !== null && st.partBy === null && !dismissed.has("partBy")) {
      out.push("partBy");
    }
    if (s.merges.length > 0 && st.merges.length === 0 && !dismissed.has("merges")) {
      out.push("merges");
    }
  }
  if (s.sparklineRuns.length > 0 && st.derived.length === 0 && !dismissed.has("sparkline")) {
    out.push("sparkline");
  }
  const hasSig = Object.values(s.roles).some((r) => r === "sig");
  if (hasSig && !st.sig.sourceId && !dismissed.has("sig")) {
    out.push("sig");
  }
  return out;
}

export function applySuggestionsToDoc(
  doc: TableDoc,
  which: SuggestionCategory,
  alsoStyle = true,
): TableDoc {
  const raw = doc.raw;
  const sug = raw.suggestions;
  const nextStruct: StructureLayer = structuredClone(doc.structure);
  const nextStyle: StyleLayer = structuredClone(doc.style);

  nextStruct.stage = "tidied";

  const applyHeaderAndSpanners = () => {
    nextStruct.headerRows = [...sug.headerRows] as [number, number];
    nextStruct.bodyRange = [...sug.bodyRange] as [number, number];
    if (sug.titleCandidate && !nextStruct.title) {
      const m = TABLE_NUM_PREFIX_RE.exec(sug.titleCandidate);
      if (m) {
        nextStruct.tableNumber = m[1].trim();
        nextStruct.title = m[2].trim() || sug.titleCandidate;
      } else {
        nextStruct.title = sug.titleCandidate;
      }
    }
    if (sug.spanners.length > 0 && !nextStruct.pivot) {
      const newSpanners: SpannerSpec[] = [];
      sug.spanners.forEach((sp, idx) => {
        const colIds = sp.sourceCols
          .map((sc) => nextStruct.columns.find((c) => c.source.kind === "grid" && c.source.col === sc)?.id)
          .filter((x): x is string => Boolean(x));
        if (colIds.length >= 2) {
          newSpanners.push({ id: `sp_${idx}`, label: sp.label, columnIds: colIds });
          sp.sourceCols.forEach((sc) => {
            const colObj = nextStruct.columns.find(
              (c) => c.source.kind === "grid" && c.source.col === sc,
            );
            if (!colObj) return;
            const suggestedLeaf = sug.leafHeaders?.[sc];
            if (suggestedLeaf && suggestedLeaf !== colObj.label) {
              colObj.label = suggestedLeaf;
            } else if (colObj.label.startsWith(`${sp.label} · `)) {
              colObj.label = colObj.label.slice(`${sp.label} · `.length).trim();
            }
          });
        }
      });
      nextStruct.spanners = newSpanners;
    }
  };

  const applyFootnotes = () => {
    if (sug.footnoteCandidates.length === 0) return;
    const existingTexts = new Set(nextStruct.footnotes.map((f) => f.text));
    sug.footnoteCandidates.forEach((rawFn, idx) => {
      const m = LEADING_FN_SYM_RE.exec(rawFn.trim());
      const sym = m ? m[1] : "";
      const txt = m ? m[2].trim() : rawFn.trim();
      if (txt && !existingTexts.has(txt)) {
        nextStruct.footnotes.push({
          id: `fn_sug_${idx}`,
          symbol: sym,
          text: txt,
          anchorColumnIds: [],
        });
      }
    });
  };

  const applyRolesAndSig = (includeAllRoles: boolean) => {
    for (const col of nextStruct.columns) {
      if (col.source.kind === "grid") {
        const suggestedRole = sug.roles[col.source.col];
        if (suggestedRole) {
          if (includeAllRoles || suggestedRole === "sig") {
            if (suggestedRole !== "part" || which === "all" || which === "partBy") {
              col.role = suggestedRole;
            }
          }
        }
      }
    }
    if (sug.sigBindings && sug.sigBindings.length > 0 && !nextStruct.pivot) {
      const builtBindings = sug.sigBindings
        .map((sb, idx) => {
          const srcCol = nextStruct.columns.find(
            (c) => c.source.kind === "grid" && c.source.col === sb.sourceCol && !c.hidden,
          );
          if (!srcCol) return null;
          const tIds = sb.targetCols
            .map(
              (tc) =>
                nextStruct.columns.find((c) => c.source.kind === "grid" && c.source.col === tc)?.id,
            )
            .filter((x): x is string => Boolean(x));
          if (sug.leafHeaders?.[sb.sourceCol]) {
            srcCol.label = sug.leafHeaders[sb.sourceCol];
          }
          return {
            id: `sb_${idx}`,
            sourceId: srcCol.id,
            targetIds: tIds.length > 0 ? tIds : [srcCol.id],
            label: sb.label,
          };
        })
        .filter((x): x is NonNullable<typeof x> => Boolean(x));

      if (builtBindings.length > 0) {
        nextStruct.sig.bindings = builtBindings;
        nextStruct.sig.sourceId = builtBindings[0].sourceId;
        nextStruct.sig.targetIds = builtBindings[0].targetIds;
        return;
      }
    }

    const sigCol = nextStruct.columns.find((c) => c.role === "sig" && !c.hidden);
    if (sigCol) {
      nextStruct.sig.sourceId = sigCol.id;
      if (nextStruct.sig.targetIds.length === 0) {
        nextStruct.sig.targetIds = [sigCol.id];
      }
      nextStruct.sig.bindings = [
        {
          id: "sb_0",
          sourceId: sigCol.id,
          targetIds: nextStruct.sig.targetIds,
        },
      ];
    }
  };

  const applyPartBy = () => {
    if (sug.partBy === null || nextStruct.pivot) return;
    const partCol = nextStruct.columns.find(
      (c) => c.source.kind === "grid" && c.source.col === sug.partBy,
    );
    if (partCol) {
      partCol.role = "part";
      nextStruct.partBy = partCol.id;
    }
  };

  const applyMerges = () => {
    if (sug.merges.length === 0 || nextStruct.pivot) return;
    const newMerges: MergeSpec[] = [];
    sug.merges.forEach((mg, idx) => {
      const colIds = mg.sourceCols
        .map((sc) => nextStruct.columns.find((c) => c.source.kind === "grid" && c.source.col === sc)?.id)
        .filter((x): x is string => Boolean(x));
      if (colIds.length >= 2) {
        for (const cid of colIds) {
          const cObj = nextStruct.columns.find((c) => c.id === cid);
          if (cObj && cObj.role === "heat") cObj.role = "normal";
        }
        newMerges.push({
          id: `mg_${idx}`,
          columnIds: colIds,
          pattern: mg.pattern,
        });
      }
    });
    nextStruct.merges = newMerges;
  };

  const applySparklines = () => {
    if (sug.sparklineRuns.length === 0) return;
    sug.sparklineRuns.forEach((run, idx) => {
      const srcCols = run.sourceCols
        .map((sc) => nextStruct.columns.find((c) => c.source.kind === "grid" && c.source.col === sc))
        .filter((x): x is ColumnSpec => Boolean(x));
      if (srcCols.length >= 4) {
        const derivedId = `drv_spark_${idx}`;
        if (!nextStruct.derived.some((d) => d.id === derivedId)) {
          nextStruct.derived.push({
            id: derivedId,
            kind: "sparkline",
            sourceIds: srcCols.map((c) => c.id),
            sharedScale: false,
          });
          for (const sc of srcCols) {
            sc.hidden = true;
          }
          nextStruct.columns.push(...buildDerivedSparklineColumns(derivedId, srcCols, run.label));
        }
      }
    });
  };

  const applyPivot = () => {
    if (!sug.pivot) return;
    const piv = sug.pivot;
    nextStruct.pivot = structuredClone(piv);
    nextStruct.partBy = null;

    const [bStart, bEnd] = sug.bodyRange;
    const colKeysSeen: string[] = [];
    for (let r = bStart; r <= bEnd; r++) {
      const row = raw.grid[r];
      if (!row) continue;
      const ck = (row[piv.colKey] ?? "").trim();
      if (ck && !colKeysSeen.includes(ck)) {
        colKeysSeen.push(ck);
      }
    }

    const rowKeyHeader = sug.resolvedHeaders?.[piv.rowKey] || `Col ${piv.rowKey + 1}`;
    const newCols: ColumnSpec[] = [
      {
        id: `c${piv.rowKey}`,
        source: { kind: "grid", col: piv.rowKey },
        label: rowKeyHeader,
        hidden: false,
        role: "normal",
        precision: "auto",
        unit: "",
      },
    ];
    const newSpanners: SpannerSpec[] = [];
    const newMerges: MergeSpec[] = [];

    // Check if valueCols represent a Mean+SD pair
    const vLabels = piv.valueCols.map((vc) =>
      leafHeaderName(sug.resolvedHeaders?.[vc] || "").toLowerCase(),
    );
    const isMeanSdPair =
      piv.valueCols.length === 2 &&
      (vLabels[0].includes("mean") || vLabels[0].includes("avg") || vLabels[0].includes("均值")) &&
      (vLabels[1].includes("sd") || vLabels[1].includes("std") || vLabels[1].includes("标准差"));

    colKeysSeen.forEach((ck, gIdx) => {
      const groupColIds: string[] = [];
      piv.valueCols.forEach((vc) => {
        const cid = `piv_${gIdx}_${vc}`;
        const rawVcLabel = leafHeaderName(sug.resolvedHeaders?.[vc] || `Val ${vc}`);
        const prettyVcLabel =
          rawVcLabel.toLowerCase() === "std"
            ? "SD"
            : rawVcLabel.toLowerCase() === "mean"
              ? "Mean"
              : rawVcLabel;
        const stat = raw.columnStats?.[vc];
        newCols.push({
          id: cid,
          source: { kind: "pivot", key: ck, valueCol: vc },
          label: piv.valueCols.length === 1 ? ck : prettyVcLabel,
          hidden: false,
          role: isMeanSdPair ? "normal" : "heat",
          precision: "auto",
          unit: stat?.detectedUnit ?? "",
        });
        groupColIds.push(cid);
      });

      const nCount = piv.colCounts?.[ck];
      const spLabel = nCount ? `${ck} (n=${nCount})` : ck;
      if (groupColIds.length >= 1 && piv.valueCols.length >= 2) {
        newSpanners.push({
          id: `sp_piv_${gIdx}`,
          label: spLabel,
          columnIds: groupColIds,
        });
      }
      if (isMeanSdPair && groupColIds.length === 2) {
        newMerges.push({
          id: `mg_piv_${gIdx}`,
          columnIds: groupColIds,
          pattern: "paren",
          mergedLabel: "Mean (SD)",
        });
      }
    });

    for (const rc of piv.retainRowCols ?? []) {
      const rcName = sug.resolvedHeaders?.[rc] || `Col ${rc + 1}`;
      const rcRole: ColumnRole = sug.roles[rc] === "sig" ? "sig" : "normal";
      const stat = raw.columnStats?.[rc];
      newCols.push({
        id: `c${rc}`,
        source: { kind: "grid", col: rc },
        label: rcRole === "sig" && rcName === "p_value" ? "P value" : rcName,
        hidden: false,
        role: rcRole,
        precision: "auto",
        unit: stat?.detectedUnit ?? "",
      });
    }

    nextStruct.columns = newCols;
    nextStruct.spanners = newSpanners;
    nextStruct.merges = newMerges;

    const sigCol = newCols.find((c) => c.role === "sig");
    if (sigCol) {
      nextStruct.sig.sourceId = sigCol.id;
      nextStruct.sig.targetIds = [sigCol.id];
    }
  };

  if (which === "all") {
    applyHeaderAndSpanners();
    applyFootnotes();
    if (sug.pivot) {
      applyPivot();
    } else {
      applyRolesAndSig(true);
      applyPartBy();
      applyMerges();
      applySparklines();
    }
    nextStruct.dismissedSuggestions = [];
  } else if (which === "headerRows") {
    applyHeaderAndSpanners();
  } else if (which === "footer") {
    applyFootnotes();
  } else if (which === "pivot") {
    applyHeaderAndSpanners();
    applyPivot();
  } else if (which === "partBy") {
    applyPartBy();
  } else if (which === "merges") {
    applyMerges();
  } else if (which === "sig") {
    applyRolesAndSig(false);
  } else if (which === "sparkline") {
    applySparklines();
  }

  if (which !== "all" && !nextStruct.dismissedSuggestions.includes(which)) {
    nextStruct.dismissedSuggestions.push(which);
  }

  const tempTidiedDoc: TableDoc = { raw, structure: nextStruct, style: nextStyle };
  const rec = inferRecommendedStyle(tempTidiedDoc);
  if (rec.heatScope && nextStyle.heatScope === "per_column") {
    nextStyle.heatScope = rec.heatScope;
  }

  if (alsoStyle && nextStyle.preset === "raw") {
    nextStyle.preset = rec.preset;
    nextStyle.lastStyledPreset = rec.preset;
    if (rec.rowRhythm && nextStyle.rowRhythm === "none") {
      nextStyle.rowRhythm = rec.rowRhythm;
    }
  } else if (nextStyle.preset !== "raw") {
    nextStyle.lastStyledPreset = nextStyle.preset;
  }

  return { raw, structure: nextStruct, style: nextStyle };
}

interface InternalRow {
  bodyRowIndex: number;
  cellsByColId: Record<string, string>;
  editedFromByColId: Record<string, string>;
  partValue: string;
}

export function sliceBodyRows(doc: TableDoc): string[][] {
  const [b0, b1] = doc.structure.bodyRange;
  const rows: string[][] = [];
  for (let r = Math.max(0, b0); r <= Math.min(doc.raw.grid.length - 1, b1); r++) {
    const row = doc.raw.grid[r];
    if (row && row.some((c) => c.trim() !== "")) {
      rows.push(row);
    }
  }
  return rows;
}

export function buildInternalRows(doc: TableDoc): InternalRow[] {
  const { structure, raw } = doc;
  const bodySlice = sliceBodyRows(doc);
  const overrides = structure.cellOverrides;

  if (structure.pivot) {
    const piv = structure.pivot;
    const groupedMap = new Map<
      string,
      { firstRow: string[]; byColKey: Record<string, string[]> }
    >();
    for (const r of bodySlice) {
      const rk = (r[piv.rowKey] ?? "").trim();
      const ck = (r[piv.colKey] ?? "").trim();
      if (!rk) continue;
      let entry = groupedMap.get(rk);
      if (!entry) {
        entry = { firstRow: r, byColKey: {} };
        groupedMap.set(rk, entry);
      }
      entry.byColKey[ck] = r;
    }

    const out: InternalRow[] = [];
    let rowIdx = 0;
    for (const [, entry] of groupedMap.entries()) {
      const cellsByColId: Record<string, string> = {};
      const editedFromByColId: Record<string, string> = {};

      for (const col of structure.columns) {
        let baseVal = "";
        if (col.source.kind === "grid") {
          baseVal = entry.firstRow[col.source.col] ?? "";
        } else if (col.source.kind === "pivot") {
          const matchRow = entry.byColKey[col.source.key];
          baseVal = matchRow ? (matchRow[col.source.valueCol] ?? "") : "";
        }
        const ovKey = `${rowIdx}:${col.id}`;
        const ov = overrides[ovKey];
        if (ov) {
          cellsByColId[col.id] = ov.to;
          editedFromByColId[col.id] = ov.from;
        } else {
          cellsByColId[col.id] = baseVal;
        }
      }

      const partVal = structure.partBy ? (cellsByColId[structure.partBy] ?? "").trim() : "";
      out.push({
        bodyRowIndex: rowIdx,
        cellsByColId,
        editedFromByColId,
        partValue: partVal,
      });
      rowIdx += 1;
    }
    return out;
  }

  // Non-pivoted rows
  // Ensure every grid column also can be referenced by derived sparklines even if hidden
  const allColSpecs = [...structure.columns];
  const coveredGridIndices = new Set(
    allColSpecs
      .filter((c): c is ColumnSpec & { source: { kind: "grid"; col: number } } => c.source.kind === "grid")
      .map((c) => c.source.col),
  );
  const nGridCols = raw.grid[0]?.length ?? 0;
  for (let gc = 0; gc < nGridCols; gc++) {
    if (!coveredGridIndices.has(gc)) {
      allColSpecs.push({
        id: `c${gc}`,
        source: { kind: "grid", col: gc },
        label: `Col ${gc + 1}`,
        hidden: true,
        role: "normal",
        precision: "auto",
        unit: "",
      });
    }
  }

  return bodySlice.map((r, rowIdx) => {
    const cellsByColId: Record<string, string> = {};
    const editedFromByColId: Record<string, string> = {};
    for (const col of allColSpecs) {
      if (col.source.kind === "grid") {
        const baseVal = r[col.source.col] ?? "";
        const ovKey = `${rowIdx}:${col.id}`;
        const ov = overrides[ovKey];
        if (ov) {
          cellsByColId[col.id] = ov.to;
          editedFromByColId[col.id] = ov.from;
        } else {
          cellsByColId[col.id] = baseVal;
        }
      }
    }
    const partVal = structure.partBy ? (cellsByColId[structure.partBy] ?? "").trim() : "";
    return {
      bodyRowIndex: rowIdx,
      cellsByColId,
      editedFromByColId,
      partValue: partVal,
    };
  });
}

interface EffectiveDisplaySlot {
  slotId: string;
  memberSpecs: ColumnSpec[];
  mergeSpec: MergeSpec | null;
}

export function buildModel(
  doc: TableDoc,
  lang: "en" | "zh" = "en",
  catalogPalettes: PaletteItem[] = [],
): RenderModel {
  const { raw, structure, style } = doc;
  const decimalComma = raw.suggestions.decimalComma;

  const footerCount = raw.suggestions.footnoteCandidates.length;
  const suggestedFooterStart =
    footerCount > 0 ? Math.max(0, raw.grid.length - footerCount) : null;

  const rec = inferRecommendedStyle(doc);
  const baseRamp = resolveTableRamp(
    style.paletteId,
    catalogPalettes,
    typeof style.heatCenter === "number",
  );
  const accentHex = baseRamp.partAccents[0] ?? "#2E6F95";

  // Step 1: Raw stage short-circuit
  if (structure.stage === "raw") {
    return {
      stage: "raw",
      preset: "raw",
      recommendedPreset: rec.preset,
      accentHex,
      tabularNums: true,
      tableNumber: structure.tableNumber,
      title: structure.title,
      subtitle: structure.subtitle,
      rawGrid: raw.grid,
      suggestedHeaderRows: raw.suggestions.headerRows,
      suggestedFooterRowStart: suggestedFooterStart,
      spanners: [],
      headers: [],
      blocks: [],
      footnotes: [],
      totalRows: raw.grid.length,
      totalCols: raw.grid[0]?.length ?? 0,
      blockCount: 0,
      editedCount: 0,
      globalHeatAllowed: true,
      hasHeatColumns: false,
      hasActiveHeatColumns: false,
      hasColumnVisualOverrides: false,
      activeHueCount: 0,
      detectedSummaryRowCount: 0,
      isMultiScaleHeat: false,
      heatLegend: null,
      heatLegends: [],
      rawDataSheet: {
        headers: raw.grid[0] ?? [],
        rows: raw.grid.slice(1),
      },
    };
  }

  // Steps 2–4: Slice, Pivot, CellOverrides
  const internalRows = buildInternalRows(doc);
  const editedCount = Object.keys(structure.cellOverrides).length;

  // Step 5: Derived sparkline series computation
  const derivedSeriesByRowCol: Record<string, number[]> = {};
  const derivedSharedBounds: Record<string, [number, number]> = {};

  for (const drv of structure.derived) {
    let globalLo = Infinity;
    let globalHi = -Infinity;
    for (const row of internalRows) {
      const vals: number[] = [];
      for (const sid of drv.sourceIds) {
        const p = parseNumber(row.cellsByColId[sid] ?? "", decimalComma);
        if (p.value !== null) {
          vals.push(p.value);
          if (p.value < globalLo) globalLo = p.value;
          if (p.value > globalHi) globalHi = p.value;
        }
      }
      derivedSeriesByRowCol[`${row.bodyRowIndex}:${drv.id}`] = vals;
    }
    if (Number.isFinite(globalLo) && Number.isFinite(globalHi)) {
      derivedSharedBounds[drv.id] = [globalLo, globalHi];
    }
  }

  // Step 6 & 7: Visible columns in display order + 2/3-col merges (excluding partBy column which becomes block banners)
  const visibleCols = structure.columns.filter(
    (c) => !c.hidden && c.id !== structure.partBy && c.role !== "part",
  );

  const mergeByFirstColId = new Map<string, MergeSpec>();
  const secondaryMergedIds = new Set<string>();

  for (const mg of structure.merges) {
    const visMembers = mg.columnIds.filter((cid) => visibleCols.some((vc) => vc.id === cid));
    if (visMembers.length >= 2) {
      // Check adjacency in visibleCols
      const indices = visMembers.map((cid) => visibleCols.findIndex((vc) => vc.id === cid));
      const contiguous = indices.every((idx, i) => i === 0 || idx === indices[i - 1] + 1);
      if (contiguous) {
        mergeByFirstColId.set(visMembers[0], { ...mg, columnIds: visMembers });
        for (const sec of visMembers.slice(1)) {
          secondaryMergedIds.add(sec);
        }
      }
    }
  }

  const slots: EffectiveDisplaySlot[] = [];
  for (const vc of visibleCols) {
    if (secondaryMergedIds.has(vc.id)) continue;
    const mg = mergeByFirstColId.get(vc.id) ?? null;
    if (mg) {
      const memberSpecs = mg.columnIds
        .map((id) => visibleCols.find((x) => x.id === id)!)
        .filter(Boolean);
      slots.push({ slotId: vc.id, memberSpecs, mergeSpec: mg });
    } else {
      slots.push({ slotId: vc.id, memberSpecs: [vc], mergeSpec: null });
    }
  }

  // Precompute parsed numbers & resolved precisions per ColumnSpec
  const colParsedValues: Record<string, number[]> = {};
  const colResolvedDecimals: Record<string, 0 | 1 | 2 | 3> = {};
  const colIsMultiScaleAuto: Record<string, boolean> = {};

  for (const col of structure.columns) {
    const vals: number[] = [];
    if (col.source.kind === "derived") {
      const metric: DerivedMetricKind = col.source.metric ?? "sparkline";
      if (metric !== "sparkline") {
        for (const r of internalRows) {
          const sVals = derivedSeriesByRowCol[`${r.bodyRowIndex}:${col.source.derivedId}`] ?? [];
          if (metric === "first" && sVals.length >= 1) vals.push(sVals[0]);
          else if (metric === "last" && sVals.length >= 1) vals.push(sVals[sVals.length - 1]);
          else if (metric === "delta" && sVals.length >= 2) {
            vals.push(sVals[sVals.length - 1] - sVals[0]);
          }
        }
      }
    } else {
      for (const r of internalRows) {
        const p = parseNumber(r.cellsByColId[col.id] ?? "", decimalComma);
        if (p.value !== null) vals.push(p.value);
      }
    }
    colParsedValues[col.id] = vals;
    const isDimensionlessEffect = DIMENSIONLESS_EFFECT_RE.test(col.label);
    colResolvedDecimals[col.id] =
      col.precision === "auto" && isDimensionlessEffect
        ? 2
        : resolvePrecision(col.precision, vals, col.role, col.unit);
    if (
      col.precision === "auto" &&
      !isDimensionlessEffect &&
      col.role !== "count" &&
      col.role !== "sig" &&
      col.role !== "bar" &&
      !col.unit.includes("%")
    ) {
      const posAbs = vals.map((v) => Math.abs(v)).filter((v) => v > 0);
      if (posAbs.length >= 2) {
        const minAbs = Math.min(...posAbs);
        const maxAbs = Math.max(...posAbs);
        if (maxAbs >= 50 && maxAbs / Math.max(minAbs, 1e-12) >= 20) {
          colIsMultiScaleAuto[col.id] = true;
        }
      }
    }
  }

  // Row-level auto precision across primary summary slots for heterogeneous multi-trait tables
  const rowAutoDecimals: Record<number, 0 | 1 | 2 | 3> = {};
  for (const r of internalRows) {
    const rowPrimaryNums: number[] = [];
    for (const slot of slots) {
      const pSpec = slot.memberSpecs[0];
      if (!pSpec || pSpec.role === "sig" || pSpec.role === "count" || pSpec.source.kind === "derived") {
        continue;
      }
      const pVal = parseNumber(r.cellsByColId[pSpec.id] ?? "", decimalComma);
      if (pVal.value !== null) rowPrimaryNums.push(pVal.value);
    }
    rowAutoDecimals[r.bodyRowIndex] = resolvePrecision("auto", rowPrimaryNums, "normal", "");
  }

  // Step 8: Group into Part blocks & sort inside each block
  const groupedBlocksMap = new Map<string, InternalRow[]>();
  if (structure.partBy) {
    for (const r of internalRows) {
      const pName = r.partValue || (lang === "zh" ? "未分组" : "Ungrouped");
      const arr = groupedBlocksMap.get(pName) ?? [];
      arr.push(r);
      groupedBlocksMap.set(pName, arr);
    }
  } else {
    groupedBlocksMap.set("", [...internalRows]);
  }

  let orderedPartNames = Array.from(groupedBlocksMap.keys());
  if (structure.partBy && Array.isArray(structure.partOrder) && structure.partOrder.length > 0) {
    const orderIdx = new Map(structure.partOrder.map((p, i) => [p, i]));
    orderedPartNames.sort((a, b) => (orderIdx.get(a) ?? 999) - (orderIdx.get(b) ?? 999));
  }

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  if (structure.sort.length > 0) {
    for (const pName of orderedPartNames) {
      const rowsInBlock = groupedBlocksMap.get(pName)!;
      rowsInBlock.sort((ra, rb) => {
        for (const rule of structure.sort) {
          const factor = rule.dir === "asc" ? 1 : -1;
          const rawA = ra.cellsByColId[rule.columnId] ?? "";
          const rawB = rb.cellsByColId[rule.columnId] ?? "";
          const pA = parseNumber(rawA, decimalComma);
          const pB = parseNumber(rawB, decimalComma);
          if (pA.value !== null && pB.value !== null) {
            if (pA.value !== pB.value) return factor * (pA.value - pB.value);
          } else if (pA.value !== null && pB.value === null) {
            return -1;
          } else if (pA.value === null && pB.value !== null) {
            return 1;
          } else {
            const cmp = collator.compare(rawA, rawB);
            if (cmp !== 0) return factor * cmp;
          }
        }
        return 0;
      });
    }
  }

  // Footnote anchor superscripts per column
  const anchorSupsByColId: Record<string, string[]> = {};
  for (const fn of structure.footnotes) {
    if (!fn.symbol) continue;
    for (const cid of fn.anchorColumnIds) {
      anchorSupsByColId[cid] = anchorSupsByColId[cid] ?? [];
      if (!anchorSupsByColId[cid].includes(fn.symbol)) {
        anchorSupsByColId[cid].push(fn.symbol);
      }
    }
  }

  // Detect summary rows (Total / Overall / 合计) in the leading visible column
  const detectedSummaryBodyIndices = new Set<number>();
  const leadLabelColId = slots[0]?.memberSpecs[0]?.id ?? null;
  if (leadLabelColId && internalRows.length >= 3) {
    const matchingRows = internalRows.filter((ir) =>
      isSummaryRowLabel(ir.cellsByColId[leadLabelColId] ?? ""),
    );
    if (matchingRows.length > 0 && internalRows.length - matchingRows.length >= 2) {
      for (const mr of matchingRows) {
        detectedSummaryBodyIndices.add(mr.bodyRowIndex);
      }
    }
  }
  const detectedSummaryRowCount = detectedSummaryBodyIndices.size;
  const excludeSummaryActive =
    (structure.excludeSummaryRows ?? true) && detectedSummaryRowCount > 0;

  // Multi-scope significance bindings per (bodyRowIndex, targetColId)
  const effectiveSigBindings =
    structure.sig.bindings && structure.sig.bindings.length > 0
      ? structure.sig.bindings.filter((b) => Boolean(b.sourceId))
      : structure.sig.sourceId
        ? [
            {
              id: "sb_legacy",
              sourceId: structure.sig.sourceId,
              targetIds:
                structure.sig.targetIds.length > 0
                  ? structure.sig.targetIds
                  : [structure.sig.sourceId],
            },
          ]
        : [];

  const hasAnySigSource = effectiveSigBindings.length > 0;
  const cellStarsByRowCol: Record<string, "" | "*" | "**" | "***"> = {};
  const cellIsSigByRowCol: Record<string, boolean> = {};
  let anyStarEmitted = false;

  for (const bind of effectiveSigBindings) {
    const srcId = bind.sourceId;
    const tIds = bind.targetIds.length > 0 ? bind.targetIds : [srcId];
    for (const r of internalRows) {
      const rawSig = r.cellsByColId[srcId] ?? "";
      const pSig = parseNumber(rawSig, decimalComma);
      const stars = computeSigStars(pSig.value, pSig.prefix);
      if (stars !== "") {
        for (const tid of tIds) {
          cellStarsByRowCol[`${r.bodyRowIndex}:${tid}`] = stars;
          cellIsSigByRowCol[`${r.bodyRowIndex}:${tid}`] = true;
        }
        if (structure.sig.stars) {
          anyStarEmitted = true;
        }
      }
    }
  }

  // Step 9 & 10: Build formatted cells per block + track merged part widths
  const maxPartWidthsBySlot: Record<number, [number, number]> = {};
  const isUnstyledGrid = style.preset === "raw";
  const ramp = baseRamp;
  let hasMixedRowUnits = false;

  const visibleDerivedDeltas = new Set(
    slots
      .map((sl) => sl.memberSpecs[0])
      .filter(
        (c): c is ColumnSpec & { source: { kind: "derived"; derivedId: string; metric?: DerivedMetricKind } } =>
          Boolean(c && c.source.kind === "derived" && c.source.metric === "delta"),
      )
      .map((c) => c.source.derivedId),
  );

  const blocks: RenderedBlock[] = orderedPartNames.map((partName, bIdx) => {
    const bRows = groupedBlocksMap.get(partName) ?? [];
    const partAccent = isUnstyledGrid
      ? "#94A3B8"
      : (ramp.partAccents[bIdx % ramp.partAccents.length] ?? "#2E6F95");

    const renderedRows: RenderedCell[][] = bRows.map((iRow) => {
      const indentLvl = structure.rowIndents[iRow.bodyRowIndex] ?? 0;
      const isCatParentRow =
        indentLvl === 0 && (structure.rowIndents[iRow.bodyRowIndex + 1] ?? 0) === 1;
      const isSummaryRow = detectedSummaryBodyIndices.has(iRow.bodyRowIndex);

      return slots.map((slot, sIdx) => {
        const primary = slot.memberSpecs[0];
        const decPrimary = colIsMultiScaleAuto[primary.id]
          ? (rowAutoDecimals[iRow.bodyRowIndex] ?? colResolvedDecimals[primary.id] ?? 2)
          : (colResolvedDecimals[primary.id] ?? 2);

        // Derived series / metric slot (start, latest, delta, or sparkline)
        if (primary.source.kind === "derived") {
          const drvId = primary.source.derivedId;
          const metric: DerivedMetricKind = primary.source.metric ?? "sparkline";
          const drvSpec = structure.derived.find((d) => d.id === drvId);
          const sVals = drvSpec
            ? (derivedSeriesByRowCol[`${iRow.bodyRowIndex}:${drvSpec.id}`] ?? [])
            : [];

          if (metric !== "sparkline") {
            let mVal: number | null = null;
            if (metric === "first" && sVals.length >= 1) mVal = sVals[0];
            else if (metric === "last" && sVals.length >= 1) mVal = sVals[sVals.length - 1];
            else if (metric === "delta" && sVals.length >= 2) {
              mVal = sVals[sVals.length - 1] - sVals[0];
            }

            let mDisp: string = structure.missingToken;
            let mNumFmt = "";
            if (mVal !== null) {
              const baseFmt = formatNumberFixed(mVal, decPrimary);
              mDisp = metric === "delta" && mVal > 0 ? `+${baseFmt}` : baseFmt;
              mNumFmt =
                metric === "delta"
                  ? `+${buildExcelNumFmt(decPrimary)};-${buildExcelNumFmt(decPrimary)};${buildExcelNumFmt(decPrimary)}`
                  : buildExcelNumFmt(decPrimary);
            }

            return {
              key: `r${iRow.bodyRowIndex}_${slot.slotId}`,
              bodyRowIndex: iRow.bodyRowIndex,
              colId: slot.slotId,
              editableColId: null,
              raw: mVal !== null ? String(mVal) : "",
              value: mVal,
              heatValue: primary.role === "part" ? null : mVal,
              display: mDisp,
              superscript: "",
              numFmt: mNumFmt,
              edited: false,
              editedFrom: null,
              indent: sIdx === 0 ? indentLvl : 0,
              align: "right",
              role: primary.role,
              bgHex: null,
              fgHex: "#111827",
              bold: !isUnstyledGrid && isSummaryRow,
              boxBorder: false,
              noWrap: true,
              parts: null,
              sparklineValues: null,
              sparklineDomain: null,
              barRatio: null,
              barSpec: null,
              isSummaryRow,
            };
          }

          let deltaStr = "";
          let domain: [number, number] | null = null;
          if (sVals.length >= 2) {
            if (!visibleDerivedDeltas.has(drvId)) {
              const delta = sVals[sVals.length - 1] - sVals[0];
              const sign = delta > 0 ? "+" : "";
              deltaStr = `${sign}${delta.toFixed(1)}${primary.unit || ""}`;
            }
            if (drvSpec?.sharedScale && derivedSharedBounds[drvSpec.id]) {
              domain = derivedSharedBounds[drvSpec.id];
            } else {
              domain = [Math.min(...sVals), Math.max(...sVals)];
            }
          } else {
            deltaStr = structure.missingToken;
          }
          return {
            key: `r${iRow.bodyRowIndex}_${slot.slotId}`,
            bodyRowIndex: iRow.bodyRowIndex,
            colId: slot.slotId,
            editableColId: null,
            raw: sVals.join(", "),
            value: null,
            heatValue: null,
            display: deltaStr,
            superscript: "",
            numFmt: "",
            edited: false,
            editedFrom: null,
            indent: sIdx === 0 ? indentLvl : 0,
            align: "right",
            role: primary.role,
            bgHex: null,
            fgHex: "#111827",
            bold: !isUnstyledGrid && isSummaryRow,
            boxBorder: false,
            noWrap: true,
            parts: null,
            sparklineValues: sVals.length >= 2 ? sVals : null,
            sparklineDomain: domain,
            barRatio: null,
            barSpec: null,
            isSummaryRow,
          };
        }

        // Composite Merged Slot (2-col or 3-col, with row-aware binary n (%) protection)
        if (slot.mergeSpec && slot.memberSpecs.length >= 2) {
          const m0 = slot.memberSpecs[0];
          const m1 = slot.memberSpecs[1];
          const m2 = slot.memberSpecs[2];
          const raw0 = iRow.cellsByColId[m0.id] ?? "";
          const raw1 = iRow.cellsByColId[m1.id] ?? "";
          const raw2 = m2 ? (iRow.cellsByColId[m2.id] ?? "") : "";

          const p0 = parseNumber(raw0, decimalComma);
          const p1 = parseNumber(raw1, decimalComma);
          const p2 = m2 ? parseNumber(raw2, decimalComma) : null;

          const editedFrom =
            iRow.editedFromByColId[m0.id] ??
            iRow.editedFromByColId[m1.id] ??
            (m2 ? iRow.editedFromByColId[m2.id] : undefined) ??
            null;

          let disp: string =
            isCatParentRow && raw0.trim() === "" && raw1.trim() === ""
              ? ""
              : structure.missingToken;
          let parts: RenderedCellPart[] | null = null;
          let mergedHeatVal: number | null = p0.value;

          if (p0.value !== null) {
            const isBinaryCountPct =
              Number.isInteger(p0.value) && p1.value !== null && (p1.unit === "%" || m1.unit === "%");

            if (isBinaryCountPct && p1.value !== null) {
              hasMixedRowUnits = true;
              mergedHeatVal = p1.value;
              const partA = String(Math.round(p0.value));
              const partB = `(${p1.value.toFixed(1)}%)`;
              disp = `${partA} ${partB}`;
              parts = [
                { display: partA, value: p0.value },
                { display: partB, value: p1.value },
              ];
            } else if (slot.mergeSpec.pattern === "iqr" && m2 && p1.value !== null && p2?.value !== null) {
              const partA = formatNumberFixed(p0.value, decPrimary, p0.prefix);
              const partB = `[${formatNumberFixed(p1.value, decPrimary)}–${formatNumberFixed(p2!.value, decPrimary)}]`;
              disp = `${partA} ${partB}`;
              parts = [
                { display: partA, value: p0.value },
                { display: partB, value: p1.value },
              ];
            } else if (slot.mergeSpec.pattern === "ci" && m2 && p1.value !== null && p2?.value !== null) {
              const partA = formatNumberFixed(p0.value, decPrimary, p0.prefix);
              const partB = `(${formatNumberFixed(p1.value, decPrimary)}–${formatNumberFixed(p2!.value, decPrimary)})`;
              disp = `${partA} ${partB}`;
              parts = [
                { display: partA, value: p0.value },
                { display: partB, value: p1.value },
              ];
            } else if (p1.value !== null) {
              const partA = formatNumberFixed(p0.value, decPrimary, p0.prefix);
              const fmtB = formatNumberFixed(p1.value, decPrimary, p1.prefix);
              const partB =
                slot.mergeSpec.pattern === "plusminus"
                  ? `± ${fmtB}`
                  : slot.mergeSpec.pattern === "iqr"
                    ? `[${fmtB}]`
                    : `(${fmtB})`;
              disp = `${partA} ${partB}`;
              parts = [
                { display: partA, value: p0.value },
                { display: partB, value: p1.value },
              ];
            } else if (raw1.trim() !== "") {
              const t1 = raw1.trim();
              const alreadyBracketed =
                (t1.startsWith("[") && t1.endsWith("]")) ||
                (t1.startsWith("(") && t1.endsWith(")"));
              const rawDecMatch = /\.(\d+)$/.exec(raw0.trim());
              const effDec: 0 | 1 | 2 | 3 =
                alreadyBracketed && m0.precision === "auto" && rawDecMatch
                  ? (Math.min(3, rawDecMatch[1].length) as 0 | 1 | 2 | 3)
                  : decPrimary;
              const partA = formatNumberFixed(p0.value, effDec, p0.prefix);
              const partB = alreadyBracketed ? t1 : `(${t1})`;
              disp = `${partA} ${partB}`;
              parts = [
                { display: partA, value: p0.value },
                { display: partB, value: null },
              ];
            } else {
              disp = formatNumberFixed(p0.value, decPrimary, p0.prefix);
            }
          }

          const matchedMemberTarget = slot.memberSpecs.find(
            (ms) => Boolean(cellIsSigByRowCol[`${iRow.bodyRowIndex}:${ms.id}`]),
          );
          const rowStars = matchedMemberTarget
            ? (cellStarsByRowCol[`${iRow.bodyRowIndex}:${matchedMemberTarget.id}`] ?? "")
            : "";
          if (matchedMemberTarget && structure.sig.stars && rowStars && disp !== "") {
            disp = `${disp}${rowStars}`;
            if (parts && parts.length === 2) {
              parts[1] = { ...parts[1], display: `${parts[1].display}${rowStars}` };
            }
          }

          if (parts && parts.length === 2) {
            const prev = maxPartWidthsBySlot[sIdx] ?? [0, 0];
            maxPartWidthsBySlot[sIdx] = [
              Math.max(prev[0], parts[0].display.length),
              Math.max(prev[1], parts[1].display.length),
            ];
          }

          const isSigHighlight =
            !isUnstyledGrid &&
            Boolean(matchedMemberTarget) &&
            style.emphasis !== "off";

          return {
            key: `r${iRow.bodyRowIndex}_${slot.slotId}`,
            bodyRowIndex: iRow.bodyRowIndex,
            colId: slot.slotId,
            editableColId: m0.id,
            raw: raw0,
            value: p0.value,
            heatValue: m0.role === "part" ? null : mergedHeatVal,
            display: disp,
            superscript: "",
            numFmt: "",
            edited: editedFrom !== null,
            editedFrom,
            indent: sIdx === 0 ? indentLvl : 0,
            align: "right",
            role: m0.role,
            bgHex: null,
            fgHex:
              isSigHighlight && style.emphasis === "accent_bold" ? "#9E2A2B" : "#111827",
            bold:
              (!isUnstyledGrid && isSummaryRow) ||
              (isSigHighlight && style.emphasis !== "hairline_box"),
            boxBorder: isSigHighlight && style.emphasis === "hairline_box",
            noWrap: true,
            parts,
            sparklineValues: null,
            sparklineDomain: null,
            barRatio: null,
            barSpec: null,
            isSummaryRow,
          };
        }

        // Single Column Slot
        const rawCell = iRow.cellsByColId[primary.id] ?? "";
        const { clean: cleanStr, sup: cellSup } = splitInlineSuperscript(rawCell);
        const isLeadingStubCol =
          sIdx === 0 &&
          primary.role === "normal" &&
          primary.visual !== "heat" &&
          primary.visual !== "bar" &&
          (indentLvl > 0 ||
            (colParsedValues[primary.id]?.length ?? 0) / Math.max(1, internalRows.length) < 0.6);
        const parsed = isLeadingStubCol
          ? { value: null, prefix: "", unit: "", pText: null, isSequence: false }
          : parseNumber(cleanStr, decimalComma);
        const editedFrom = iRow.editedFromByColId[primary.id] ?? null;

        let display = "";
        let numFmt = "";
        let sparkVals: number[] | null = null;

        if (primary.role === "sig") {
          if (parsed.value === null && !parsed.pText) {
            display = cleanStr ? cleanStr : indentLvl === 1 ? "" : structure.missingToken;
          } else {
            display = formatP(parsed.value, parsed.prefix, structure.sig.pStyle, parsed.pText);
          }
        } else if (parsed.isSequence) {
          sparkVals = parseSequence(cleanStr);
          if (sparkVals && sparkVals.length >= 2) {
            const d = sparkVals[sparkVals.length - 1] - sparkVals[0];
            display = `${d > 0 ? "+" : ""}${d.toFixed(1)}`;
          } else {
            display = cleanStr;
          }
        } else if (parsed.value !== null) {
          display = formatNumberFixed(parsed.value, decPrimary, parsed.prefix);
          numFmt = buildExcelNumFmt(decPrimary);
        } else {
          display = cleanStr === "" || parseNumber(cleanStr, decimalComma).value === null && ["NA", "N/A", "-", "—"].includes(cleanStr.trim())
            ? isCatParentRow && sIdx > 0
              ? ""
              : structure.missingToken
            : cleanStr;
        }

        const isTarget = Boolean(cellIsSigByRowCol[`${iRow.bodyRowIndex}:${primary.id}`]);
        const rowStars = cellStarsByRowCol[`${iRow.bodyRowIndex}:${primary.id}`] ?? "";
        if (
          isTarget &&
          structure.sig.stars &&
          rowStars &&
          display !== "" &&
          display !== structure.missingToken &&
          display !== "n.s."
        ) {
          display = `${display}${rowStars}`;
        }

        const isSigHighlight =
          !isUnstyledGrid &&
          isTarget &&
          style.emphasis !== "off";

        const isNumericAligned =
          primary.role === "sig" ||
          primary.role === "heat" ||
          primary.role === "count" ||
          primary.role === "bar" ||
          primary.visual === "heat" ||
          primary.visual === "bar" ||
          parsed.value !== null ||
          sparkVals !== null;

        const singleHeatVal =
          primary.role === "part" || sparkVals !== null
            ? null
            : primary.role === "sig"
              ? parsed.value !== null && parsed.value >= 0
                ? parsed.prefix === "<"
                  ? parsed.value * 0.5
                  : parsed.value
                : null
              : parsed.value;

        return {
          key: `r${iRow.bodyRowIndex}_${primary.id}`,
          bodyRowIndex: iRow.bodyRowIndex,
          colId: primary.id,
          editableColId: primary.id,
          raw: rawCell,
          value: parsed.value,
          heatValue: singleHeatVal,
          display,
          superscript: cellSup,
          numFmt,
          edited: editedFrom !== null,
          editedFrom,
          indent: sIdx === 0 ? indentLvl : 0,
          align: sIdx === 0 && !isNumericAligned ? "left" : isNumericAligned ? "right" : "left",
          role: primary.role,
          bgHex: null,
          fgHex: isSigHighlight && style.emphasis === "accent_bold" ? "#9E2A2B" : "#111827",
          bold:
            (!isUnstyledGrid && isSummaryRow) ||
            (isSigHighlight && style.emphasis !== "hairline_box"),
          boxBorder: isSigHighlight && style.emphasis === "hairline_box",
          noWrap: false,
          parts: null,
          sparklineValues: sparkVals,
          sparklineDomain: sparkVals ? [Math.min(...sparkVals), Math.max(...sparkVals)] : null,
          barRatio: null,
          barSpec: null,
          isSummaryRow,
        };
      });
    });

    return {
      blockIndex: bIdx,
      partName,
      partAccent,
      rows: renderedRows,
    };
  });

  // Evaluate numeric values per slot (optionally excluding summary rows from bounds)
  const totalBodyRows = blocks.reduce((acc, b) => acc + b.rows.length, 0);
  const slotNumericValuesForBounds: number[][] = slots.map((_, sIdx) => {
    const arr: number[] = [];
    blocks.forEach((b) =>
      b.rows.forEach((r) => {
        const cell = r[sIdx];
        if (!cell) return;
        if (excludeSummaryActive && cell.isSummaryRow) return;
        const hv = cell.heatValue;
        if (hv !== null && hv !== undefined && Number.isFinite(hv)) {
          arr.push(hv);
        }
      }),
    );
    return arr;
  });

  const slotAllNumericValues: number[][] = slots.map((_, sIdx) => {
    const arr: number[] = [];
    blocks.forEach((b) =>
      b.rows.forEach((r) => {
        const hv = r[sIdx]?.heatValue;
        if (hv !== null && hv !== undefined && Number.isFinite(hv)) {
          arr.push(hv);
        }
      }),
    );
    return arr;
  });

  // Resolve visualMode & effectiveVisual per slot
  const slotVisualModes: ColumnVisualMode[] = slots.map((slot) => {
    const primary = slot.memberSpecs[0];
    if (primary.visual && primary.visual !== "auto") return primary.visual;
    const memberOverride = slot.memberSpecs.find((ms) => ms.visual && ms.visual !== "auto");
    return memberOverride?.visual ?? primary.visual ?? "auto";
  });

  const slotIsSparklineSvg = (slot: EffectiveDisplaySlot): boolean => {
    const p = slot.memberSpecs[0];
    if (p.source.kind === "derived" && (p.source.metric ?? "sparkline") === "sparkline") {
      return true;
    }
    return blocks.some((b) =>
      b.rows.some((r) => {
        const sIdx = slots.indexOf(slot);
        return sIdx >= 0 && r[sIdx]?.sparklineValues !== null;
      }),
    );
  };

  const autoHeatCandidateSlots: number[] = [];
  const legacyRoleHeatSlots: number[] = [];
  slots.forEach((slot, sIdx) => {
    const primary = slot.memberSpecs[0];
    const vals = slotAllNumericValues[sIdx];
    if (vals.length === 0) return;
    if (slotIsSparklineSvg(slot)) return;
    if (primary.role === "sig" || primary.role === "count" || primary.role === "part") return;
    const isLabelFirstCol =
      sIdx === 0 &&
      !slot.mergeSpec &&
      primary.role === "normal" &&
      vals.length / Math.max(1, totalBodyRows) < 0.6;
    if (isLabelFirstCol) return;

    autoHeatCandidateSlots.push(sIdx);
    if (slot.memberSpecs.some((ms) => ms.role === "heat")) {
      legacyRoleHeatSlots.push(sIdx);
    }
  });

  const defaultMatrixHeatSlotSet = new Set<number>(
    legacyRoleHeatSlots.length > 0 ? legacyRoleHeatSlots : autoHeatCandidateSlots,
  );

  const slotEffectiveVisuals: Array<"plain" | "heat" | "bar"> = slots.map((slot, sIdx) => {
    const primary = slot.memberSpecs[0];
    const vm = slotVisualModes[sIdx];
    const hasNums = slotAllNumericValues[sIdx].length > 0 && !slotIsSparklineSvg(slot);
    if (isUnstyledGrid || !hasNums) return "plain";
    if (vm === "plain") return "plain";
    if (vm === "heat") return "heat";
    if (vm === "bar") return "bar";
    // vm === "auto"
    if (style.preset === "matrix_heatmap") {
      return defaultMatrixHeatSlotSet.has(sIdx) ? "heat" : "plain";
    }
    if (primary.role === "bar") {
      return "bar";
    }
    return "plain";
  });

  const slotEffectivePaletteIds: string[] = slots.map((slot) => {
    const vc = slot.memberSpecs[0].visualConfig;
    return vc?.paletteId && vc.paletteId !== "inherit" ? vc.paletteId : style.paletteId;
  });

  // Render Inline Bar Specs & compute aligned barValWidthCh for all active bar slots
  const barValWidthChBySlot: Record<number, number> = {};
  slots.forEach((slot, sIdx) => {
    if (slotEffectiveVisuals[sIdx] !== "bar") return;
    const primary = slot.memberSpecs[0];
    const vc = primary.visualConfig ?? {};
    const barDomainMode: BarDomainMode = vc.barDomain ?? "column_max";
    const direction = vc.direction ?? "normal";
    const effPaletteId = slotEffectivePaletteIds[sIdx];
    const { posHex, negHex } = resolveColumnBarColors(effPaletteId, catalogPalettes, direction);

    const boundVals =
      slotNumericValuesForBounds[sIdx].length > 0
        ? slotNumericValuesForBounds[sIdx]
        : slotAllNumericValues[sIdx];
    if (boundVals.length === 0) return;

    const rawMin = Math.min(...boundVals);
    const rawMax = Math.max(...boundVals);

    let domainMin = 0;
    let domainMax = 1;
    let bidirectional = false;
    let zeroPct = 0;

    if (rawMin >= 0) {
      domainMin = 0;
      domainMax =
        barDomainMode === "percent_100" ? Math.max(100, rawMax) : Math.max(rawMax, 1e-9);
      bidirectional = false;
      zeroPct = 0;
    } else if (rawMax <= 0) {
      domainMax = 0;
      domainMin =
        barDomainMode === "percent_100" ? Math.min(-100, rawMin) : Math.min(rawMin, -1e-9);
      bidirectional = true;
      zeroPct = 100;
    } else {
      domainMin = barDomainMode === "percent_100" ? Math.min(-100, rawMin) : rawMin;
      domainMax = barDomainMode === "percent_100" ? Math.max(100, rawMax) : rawMax;
      const span = Math.max(domainMax - domainMin, 1e-9);
      bidirectional = true;
      zeroPct = (Math.abs(domainMin) / span) * 100;
    }

    const spanTotal = Math.max(domainMax - domainMin, 1e-9);
    const maxAbsBound = Math.max(Math.abs(domainMin), Math.abs(domainMax), 1e-9);

    let maxLabelChars = 0;
    const mergedPartWidths = maxPartWidthsBySlot[sIdx];
    if (mergedPartWidths) {
      maxLabelChars = mergedPartWidths[0] + 1 + mergedPartWidths[1];
    }

    blocks.forEach((b) =>
      b.rows.forEach((r) => {
        const cell = r[sIdx];
        if (!cell) return;
        if (!mergedPartWidths) {
          const charLen =
            (cell.display?.length ?? 0) + (cell.superscript ? cell.superscript.length * 0.75 : 0);
          if (charLen > maxLabelChars) maxLabelChars = charLen;
        }
        if (excludeSummaryActive && cell.isSummaryRow) {
          cell.barRatio = null;
          cell.barSpec = null;
          return;
        }
        const mVal = cell.heatValue;
        if (mVal === null || mVal === undefined || !Number.isFinite(mVal)) {
          cell.barRatio = null;
          cell.barSpec = null;
          return;
        }

        let startPct = 0;
        let widthPct = 0;
        let ratio = 0;
        if (!bidirectional) {
          ratio = Math.max(0, Math.min(1, mVal / Math.max(domainMax, 1e-9)));
          startPct = 0;
          widthPct = ratio * 100;
        } else if (domainMax === 0) {
          ratio = Math.max(0, Math.min(1, Math.abs(mVal) / Math.max(Math.abs(domainMin), 1e-9)));
          widthPct = ratio * 100;
          startPct = Math.max(0, 100 - widthPct);
        } else {
          widthPct = Math.max(0, Math.min(100, (Math.abs(mVal) / spanTotal) * 100));
          startPct = mVal >= 0 ? zeroPct : Math.max(0, zeroPct - widthPct);
          ratio = Math.max(0, Math.min(1, Math.abs(mVal) / maxAbsBound));
        }

        const spec: BarRenderSpec = {
          ratio,
          zeroPct,
          startPct,
          widthPct,
          fillHex: mVal < 0 ? negHex : posHex,
          bidirectional,
          isNegative: mVal < 0,
          domainMin,
          domainMax,
        };
        cell.barRatio = ratio;
        cell.barSpec = spec;
      }),
    );

    barValWidthChBySlot[sIdx] = Math.max(3.5, Math.ceil((maxLabelChars + 0.5) * 2) / 2);
  });

  // Evaluate Heatmap Slot Candidates & Unit / Scale Compatibility (§2.5 + v0.6.1 Multi-Cohort Engine)
  const activeHeatSlots: number[] = [];
  slots.forEach((_, sIdx) => {
    if (slotEffectiveVisuals[sIdx] === "heat") {
      activeHeatSlots.push(sIdx);
    }
  });
  const activeHeatSlotSet = new Set<number>(activeHeatSlots);

  const compatibilityHeatSlots =
    activeHeatSlots.length > 0 ? activeHeatSlots : Array.from(defaultMatrixHeatSlotSet);

  const heatUnits = new Set<string>();
  const logBlockedCols = new Set<string>();
  let isMultiScaleHeat = false;

  for (const sIdx of compatibilityHeatSlots) {
    const primary = slots[sIdx].memberSpecs[0];
    const vc = primary.visualConfig ?? {};
    const isSigCol = primary.role === "sig";
    const isRatioOne = !isSigCol && vc.center === "ratio_1";
    const useLog10 = !isSigCol && !isRatioOne && style.heatLog;

    heatUnits.add(isSigCol ? "-log10P" : primary.unit || "");
    const vals =
      slotNumericValuesForBounds[sIdx].length > 0
        ? slotNumericValuesForBounds[sIdx]
        : slotAllNumericValues[sIdx];
    if ((useLog10 || isRatioOne) && vals.some((v) => v <= 0)) {
      logBlockedCols.add(primary.id);
    }
    const posAbs = vals.map((v) => Math.abs(v)).filter((v) => v > 0);
    if (compatibilityHeatSlots.length >= 2 && posAbs.length >= 2) {
      if (Math.max(...posAbs) / Math.max(Math.min(...posAbs), 1e-12) >= 20) {
        isMultiScaleHeat = true;
      }
    }
  }

  const hasHeatColumns = compatibilityHeatSlots.length > 0;
  const hasActiveHeatColumns = activeHeatSlots.length > 0;
  const globalHeatAllowed = heatUnits.size <= 1 && !hasMixedRowUnits;
  const effectiveHeatScope: HeatScope =
    style.heatScope === "global" && !globalHeatAllowed
      ? isMultiScaleHeat
        ? "per_row"
        : "per_column"
      : style.heatScope;

  const computeDomainBounds = (vals: number[], clipMode: DomainClipMode): [number, number] => {
    if (vals.length === 0) return [0, 1];
    const sorted = [...vals].sort((a, b) => a - b);
    const loAll = sorted[0];
    const hiAll = sorted[sorted.length - 1];
    if (clipMode === "p5_p95" && sorted.length >= 5) {
      const interp = (q: number) => {
        const pos = q * (sorted.length - 1);
        const i0 = Math.floor(pos);
        const i1 = Math.min(sorted.length - 1, i0 + 1);
        const f = pos - i0;
        return sorted[i0] + (sorted[i1] - sorted[i0]) * f;
      };
      const q05 = interp(0.05);
      const q95 = interp(0.95);
      if (q95 - q05 > 1e-12) {
        return [q05, q95];
      }
    }
    return [loAll, hiAll];
  };

  // Map StructureLayer spanners onto visible slot indices first so legends & headers know spanner prefixes
  const spanners: RenderedSpanner[] = [];
  for (const sp of structure.spanners) {
    const matchedSlotIndices: number[] = [];
    slots.forEach((slot, sIdx) => {
      if (slot.memberSpecs.some((ms) => sp.columnIds.includes(ms.id))) {
        matchedSlotIndices.push(sIdx);
      }
    });
    if (matchedSlotIndices.length >= 1) {
      const contiguous = matchedSlotIndices.every(
        (idx, i) => i === 0 || idx === matchedSlotIndices[i - 1] + 1,
      );
      if (contiguous) {
        const { clean: spClean, sup: spSup } = splitInlineSuperscript(sp.label);
        spanners.push({
          id: sp.id,
          label: spClean,
          superscript: spSup,
          startCol: matchedSlotIndices[0],
          endCol: matchedSlotIndices[matchedSlotIndices.length - 1],
          columnIds: sp.columnIds,
        });
      }
    }
  }

  const spannerPrefixBySlot: string[] = slots.map((_, sIdx) => {
    const enc = spanners.find((sp) => sIdx >= sp.startCol && sIdx <= sp.endCol);
    return enc ? enc.label : "";
  });

  const buildSlotDisplayLabel = (slot: EffectiveDisplaySlot): string => {
    const primary = slot.memberSpecs[0];
    const { clean: cleanLbl } = splitInlineSuperscript(primary.label);
    let displayLabel = cleanLbl;
    if (slot.mergeSpec) {
      if (slot.mergeSpec.mergedLabel) {
        displayLabel = slot.mergeSpec.mergedLabel;
      } else if (slot.mergeSpec.pattern === "iqr") {
        displayLabel =
          slot.memberSpecs.length >= 3
            ? `${cleanLbl} [IQR]`
            : `${cleanLbl} [${leafHeaderName(slot.memberSpecs[1].label)}]`;
      } else if (slot.mergeSpec.pattern === "ci") {
        displayLabel = `${cleanLbl} (95% CI)`;
      } else if (slot.mergeSpec.pattern === "plusminus") {
        displayLabel = `${cleanLbl} ± ${leafHeaderName(slot.memberSpecs[1].label)}`;
      } else {
        displayLabel = `${cleanLbl} (${leafHeaderName(slot.memberSpecs[1].label)})`;
      }
    }
    if (
      primary.unit &&
      !displayLabel.includes(`(${primary.unit})`) &&
      !displayLabel.endsWith(primary.unit)
    ) {
      displayLabel = `${displayLabel} (${primary.unit})`;
    }
    return displayLabel;
  };

  const slotDisplayLabels = slots.map((sl) => buildSlotDisplayLabel(sl));

  // Step 11: Multi-Cohort Heatmap Normalization (works in Matrix Heatmap AND selective columns in CNS / FT)
  const heatLegends: HeatLegendModel[] = [];
  const headerRampStopsBySlot: Record<number, string[]> = {};

  if (!isUnstyledGrid && activeHeatSlots.length > 0) {
    interface HeatCohort {
      key: string;
      slotIndices: number[];
      paletteId: string;
      direction: "normal" | "reverse";
      center: "auto" | "ratio_1" | number;
      domainClip: DomainClipMode;
      isSigNegLog: boolean;
      isRatioOne: boolean;
      useLog10: boolean;
    }

    const cohortMap = new Map<string, HeatCohort>();
    for (const sIdx of activeHeatSlots) {
      const primary = slots[sIdx].memberSpecs[0];
      if (logBlockedCols.has(primary.id)) continue;
      const vc = primary.visualConfig ?? {};
      const paletteId = slotEffectivePaletteIds[sIdx];
      const direction = vc.direction ?? "normal";
      const center: "auto" | "ratio_1" | number = vc.center ?? style.heatCenter;
      const domainClip: DomainClipMode = vc.domainClip ?? style.heatDomainClip ?? "minmax";
      const isSigNegLog = primary.role === "sig";
      const isRatioOne = !isSigNegLog && center === "ratio_1";
      const useLog10 = !isSigNegLog && !isRatioOne && style.heatLog;
      const unitKey = isSigNegLog ? "__sig_neglog10__" : primary.unit || "";
      const scaleKey = isSigNegLog
        ? "sig"
        : isRatioOne
          ? "ratio1"
          : useLog10
            ? "log10"
            : "lin";
      const key = `${paletteId}|${unitKey}|${direction}|${String(center)}|${scaleKey}|${domainClip}`;

      let cohort = cohortMap.get(key);
      if (!cohort) {
        cohort = {
          key,
          slotIndices: [],
          paletteId,
          direction,
          center,
          domainClip,
          isSigNegLog,
          isRatioOne,
          useLog10,
        };
        cohortMap.set(key, cohort);
      }
      cohort.slotIndices.push(sIdx);
    }

    const paintHeatCell = (cell: RenderedCell, stops: string[], tNorm: number) => {
      const bg = interpolateRampHex(stops, tNorm);
      cell.bgHex = bg;
      const wcagFg = pickWcagForeground(bg);
      if (cell.bold && style.emphasis === "accent_bold" && wcagFg === "#111827") {
        cell.fgHex = "#7F1D1D";
      } else {
        cell.fgHex = wcagFg;
      }
    };

    const fmtLegendNum = (n: number): string =>
      Math.abs(n) >= 100 ? Math.round(n).toLocaleString() : Number(n.toFixed(1)).toString();

    const cohorts = Array.from(cohortMap.values());

    for (const cohort of cohorts) {
      const wantDiverging =
        cohort.isRatioOne || typeof cohort.center === "number";
      const resolvedCohortRamp = resolveTableRamp(
        cohort.paletteId,
        catalogPalettes,
        wantDiverging,
      );
      const primaryStops = orientRampStops(resolvedCohortRamp.stops, cohort.direction);
      const secondaryStops = resolvedCohortRamp.secondaryStops
        ? orientRampStops(resolvedCohortRamp.secondaryStops, cohort.direction)
        : undefined;

      const transformCohortVal = (v: number): number | null => {
        if (!Number.isFinite(v)) return null;
        if (cohort.isSigNegLog) {
          return -Math.log10(Math.max(v, 1e-16));
        }
        if (cohort.isRatioOne) {
          return v > 0 ? Math.log10(v) : null;
        }
        if (cohort.useLog10) {
          return v > 0 ? Math.log10(v) : null;
        }
        return v;
      };

      const normalizeCohortT = (val: number, lo: number, hi: number, count: number): number => {
        const clampedVal = Math.max(lo, Math.min(hi, val));
        const numericCenter = cohort.isRatioOne
          ? 0
          : typeof cohort.center === "number"
            ? cohort.useLog10
              ? cohort.center > 0
                ? Math.log10(cohort.center)
                : 0
              : cohort.center
            : lo < 0 && hi > 0
              ? 0
              : null;

        if (numericCenter !== null && resolvedCohortRamp.diverging) {
          const maxArm = Math.max(
            Math.abs(hi - numericCenter),
            Math.abs(numericCenter - lo),
            1e-12,
          );
          return Math.max(0, Math.min(1, 0.5 + 0.5 * ((clampedVal - numericCenter) / maxArm)));
        }
        if (hi - lo <= 1e-12) return 0.45;
        const rawT = Math.max(0, Math.min(1, (clampedVal - lo) / (hi - lo)));
        return cushionSmallSampleT(rawT, count, resolvedCohortRamp.diverging);
      };

      // Single-column cohort cannot normalize per_row (lo === hi), so fall back cleanly to per_column
      const cohortScope: HeatScope =
        effectiveHeatScope === "per_row" && cohort.slotIndices.length < 2
          ? "per_column"
          : effectiveHeatScope;

      let cohortMinRaw = Infinity;
      let cohortMaxRaw = -Infinity;
      cohort.slotIndices.forEach((sIdx) => {
        const rawPool =
          slotNumericValuesForBounds[sIdx].length > 0
            ? slotNumericValuesForBounds[sIdx]
            : slotAllNumericValues[sIdx];
        for (const v of rawPool) {
          if (v < cohortMinRaw) cohortMinRaw = v;
          if (v > cohortMaxRaw) cohortMaxRaw = v;
        }
      });

      if (cohortScope === "global") {
        const boundT: number[] = [];
        blocks.forEach((b) =>
          b.rows.forEach((r) =>
            cohort.slotIndices.forEach((sIdx) => {
              const cell = r[sIdx];
              if (!cell || (excludeSummaryActive && cell.isSummaryRow)) return;
              if (cell.heatValue !== null) {
                const tv = transformCohortVal(cell.heatValue);
                if (tv !== null) boundT.push(tv);
              }
            }),
          ),
        );
        if (boundT.length > 0) {
          const [lo, hi] = computeDomainBounds(boundT, cohort.domainClip);
          blocks.forEach((b, bIdx) => {
            const stops = bIdx % 2 === 1 && secondaryStops ? secondaryStops : primaryStops;
            b.rows.forEach((r) =>
              cohort.slotIndices.forEach((sIdx) => {
                const cell = r[sIdx];
                if (!cell || (excludeSummaryActive && cell.isSummaryRow)) return;
                if (cell.heatValue !== null) {
                  const tv = transformCohortVal(cell.heatValue);
                  if (tv !== null) {
                    paintHeatCell(cell, stops, normalizeCohortT(tv, lo, hi, boundT.length));
                  }
                }
              }),
            );
          });
        }
      } else if (cohortScope === "per_part") {
        blocks.forEach((b, bIdx) => {
          const stops = bIdx % 2 === 1 && secondaryStops ? secondaryStops : primaryStops;
          const partVals: number[] = [];
          b.rows.forEach((r) =>
            cohort.slotIndices.forEach((sIdx) => {
              const cell = r[sIdx];
              if (!cell || (excludeSummaryActive && cell.isSummaryRow)) return;
              if (cell.heatValue !== null) {
                const tv = transformCohortVal(cell.heatValue);
                if (tv !== null) partVals.push(tv);
              }
            }),
          );
          if (partVals.length > 0) {
            const [lo, hi] = computeDomainBounds(partVals, cohort.domainClip);
            b.rows.forEach((r) =>
              cohort.slotIndices.forEach((sIdx) => {
                const cell = r[sIdx];
                if (!cell || (excludeSummaryActive && cell.isSummaryRow)) return;
                if (cell.heatValue !== null) {
                  const tv = transformCohortVal(cell.heatValue);
                  if (tv !== null) {
                    paintHeatCell(cell, stops, normalizeCohortT(tv, lo, hi, partVals.length));
                  }
                }
              }),
            );
          }
        });
      } else if (cohortScope === "per_row") {
        blocks.forEach((b, bIdx) => {
          const stops = bIdx % 2 === 1 && secondaryStops ? secondaryStops : primaryStops;
          b.rows.forEach((r) => {
            const firstCell = r[cohort.slotIndices[0]];
            if (excludeSummaryActive && firstCell?.isSummaryRow) return;
            const rowVals: number[] = [];
            cohort.slotIndices.forEach((sIdx) => {
              const v = r[sIdx]?.heatValue;
              if (v !== null && v !== undefined) {
                const tv = transformCohortVal(v);
                if (tv !== null) rowVals.push(tv);
              }
            });
            if (rowVals.length > 0) {
              const [lo, hi] = computeDomainBounds(rowVals, cohort.domainClip);
              cohort.slotIndices.forEach((sIdx) => {
                const cell = r[sIdx];
                if (cell && cell.heatValue !== null) {
                  const tv = transformCohortVal(cell.heatValue);
                  if (tv !== null) {
                    paintHeatCell(cell, stops, normalizeCohortT(tv, lo, hi, rowVals.length));
                  }
                }
              });
            }
          });
        });
      } else {
        // per_column
        cohort.slotIndices.forEach((sIdx) => {
          const colVals: number[] = [];
          blocks.forEach((b) =>
            b.rows.forEach((r) => {
              const cell = r[sIdx];
              if (!cell || (excludeSummaryActive && cell.isSummaryRow)) return;
              if (cell.heatValue !== null) {
                const tv = transformCohortVal(cell.heatValue);
                if (tv !== null) colVals.push(tv);
              }
            }),
          );
          if (colVals.length > 0) {
            const [lo, hi] = computeDomainBounds(colVals, cohort.domainClip);
            blocks.forEach((b, bIdx) => {
              const stops = bIdx % 2 === 1 && secondaryStops ? secondaryStops : primaryStops;
              b.rows.forEach((r) => {
                const cell = r[sIdx];
                if (!cell || (excludeSummaryActive && cell.isSummaryRow)) return;
                if (cell.heatValue !== null) {
                  const tv = transformCohortVal(cell.heatValue);
                  if (tv !== null) {
                    paintHeatCell(cell, stops, normalizeCohortT(tv, lo, hi, colVals.length));
                  }
                }
              });
            });
          }
        });
      }

      for (const sIdx of cohort.slotIndices) {
        headerRampStopsBySlot[sIdx] = primaryStops;
      }

      let cohortLabel: string | undefined;
      if (cohorts.length > 1) {
        const names = cohort.slotIndices.map((sIdx) => {
          const sp = spannerPrefixBySlot[sIdx];
          const lbl = slotDisplayLabels[sIdx];
          return sp ? `${sp} · ${lbl}` : lbl;
        });
        cohortLabel =
          names.length <= 2 ? names.join(", ") : `${names[0]} +${names.length - 1}`;
      }

      const showNumericEnds =
        !cohort.isSigNegLog &&
        !cohort.isRatioOne &&
        (cohortScope === "global" || cohort.slotIndices.length === 1) &&
        Number.isFinite(cohortMinRaw) &&
        Number.isFinite(cohortMaxRaw);

      const minLabel = cohort.isSigNegLog
        ? "n.s."
        : cohort.isRatioOne
          ? "< 1"
          : showNumericEnds
            ? fmtLegendNum(cohortMinRaw)
            : lang === "zh"
              ? "低"
              : "Low";

      const maxLabel = cohort.isSigNegLog
        ? "-log₁₀P"
        : cohort.isRatioOne
          ? "> 1"
          : showNumericEnds
            ? fmtLegendNum(cohortMaxRaw)
            : lang === "zh"
              ? "高"
              : "High";

      heatLegends.push({
        id: cohort.key,
        label: cohortLabel,
        stops: primaryStops,
        secondaryStops: blocks.length >= 2 ? secondaryStops : undefined,
        scope: cohortScope,
        minLabel,
        maxLabel,
        diverging: resolvedCohortRamp.diverging,
        reversed: cohort.direction === "reverse",
      });
    }
  }

  // Row rhythm on non-heat columns when preset is cns_three_line or ft_editorial
  if (!isUnstyledGrid && style.preset !== "matrix_heatmap" && style.rowRhythm !== "none") {
    const tintHex = style.preset === "ft_editorial" ? "#F5EFE6" : "#F3F6FA";
    blocks.forEach((b) => {
      b.rows.forEach((r, rIdx) => {
        const tinted =
          style.rowRhythm === "zebra"
            ? rIdx % 2 === 1
            : Math.floor(rIdx / 3) % 2 === 1;
        if (tinted) {
          r.forEach((cell, sIdx) => {
            if (!cell.bgHex && !activeHeatSlotSet.has(sIdx)) {
              cell.bgHex = tintHex;
            }
          });
        }
      });
    });
  }

  const heatLegend: HeatLegendModel | null = heatLegends[0] ?? null;

  // Compute activeHueCount (distinct chromatic palettes across active heat/bar slots) & override indicator
  const activeChromaticPalettes = new Set<string>();
  slots.forEach((_, sIdx) => {
    const ev = slotEffectiveVisuals[sIdx];
    if (ev === "heat" || ev === "bar") {
      const pid = slotEffectivePaletteIds[sIdx];
      if (isChromaticPalette(pid, catalogPalettes)) {
        activeChromaticPalettes.add(pid);
      }
    }
  });
  const activeHueCount = activeChromaticPalettes.size;

  const hasColumnVisualOverrides = visibleCols.some((c) => {
    if (c.visual && c.visual !== "auto") return true;
    const vc = c.visualConfig;
    if (!vc) return false;
    return Boolean(
      (vc.paletteId && vc.paletteId !== "inherit") ||
        (vc.direction && vc.direction !== "normal") ||
        (vc.center !== undefined && vc.center !== "auto") ||
        (vc.domainClip && vc.domainClip !== "minmax") ||
        (vc.barDomain && vc.barDomain !== "column_max"),
    );
  });

  // Build RenderedHeaders
  const showHeaderInlineRamps = heatLegends.length > 3;
  const headers: RenderedHeader[] = slots.map((slot, sIdx) => {
    const primary = slot.memberSpecs[0];
    const { sup: inlineSup } = splitInlineSuperscript(primary.label);
    const anchoredSups = slot.memberSpecs.flatMap((ms) => anchorSupsByColId[ms.id] ?? []);
    const allSups = [inlineSup, ...anchoredSups].filter(Boolean).join(",");
    const displayLabel = slotDisplayLabels[sIdx];

    const activeSort = structure.sort.find((s) => s.columnId === primary.id);
    const firstCellAlign = blocks[0]?.rows[0]?.[sIdx]?.align;
    const align: "left" | "right" =
      sIdx === 0 && primary.role === "normal" && !slot.mergeSpec
        ? "left"
        : firstCellAlign ?? "right";

    return {
      colId: slot.slotId,
      memberColIds: slot.memberSpecs.map((m) => m.id),
      label: displayLabel,
      rawLabel: primary.label,
      spannerPrefix: spannerPrefixBySlot[sIdx] ?? "",
      unit: primary.unit,
      superscript: allSups,
      role: primary.role,
      visualMode: slotVisualModes[sIdx],
      effectiveVisual: slotEffectiveVisuals[sIdx],
      effectivePaletteId: slotEffectivePaletteIds[sIdx],
      headerRampStops: showHeaderInlineRamps ? (headerRampStopsBySlot[sIdx] ?? null) : null,
      align,
      isMerged: Boolean(slot.mergeSpec),
      partWidthsCh: maxPartWidthsBySlot[sIdx] ?? null,
      barValWidthCh: barValWidthChBySlot[sIdx] ?? null,
      hasNumericValues: slotAllNumericValues[sIdx].length > 0 && !slotIsSparklineSvg(slot),
      sortDir: activeSort?.dir ?? null,
      ratioHint: RATIO_NAME_RE.test(primary.label),
      logBlocked: logBlockedCols.has(primary.id),
    };
  });

  // Build Footnotes + automatic read-only star legend (§2.4 L177, §6 L361)
  const footnotes: RenderedFootnote[] = structure.footnotes.map((fn) => ({
    id: fn.id,
    symbol: fn.symbol,
    text: fn.text,
    readOnly: false,
  }));

  if (hasAnySigSource && structure.sig.stars && anyStarEmitted) {
    const legendText =
      lang === "zh"
        ? "* P < 0.05；** P < 0.01；*** P < 0.001。"
        : "* P < 0.05; ** P < 0.01; *** P < 0.001.";
    footnotes.push({
      id: "fn_auto_sig_legend",
      symbol: "",
      text: legendText,
      readOnly: true,
    });
  }

  // Build unmerged `rawDataSheet` (all visible columns unmerged + derived sparkline source columns)
  const rawSheetCols: ColumnSpec[] = [];
  const addedIds = new Set<string>();
  const pushRawCol = (c: ColumnSpec | undefined) => {
    if (!c || addedIds.has(c.id)) return;
    addedIds.add(c.id);
    rawSheetCols.push(c);
  };

  if (structure.partBy) {
    pushRawCol(structure.columns.find((c) => c.id === structure.partBy));
  }
  for (const slot of slots) {
    for (const ms of slot.memberSpecs) {
      if (ms.source.kind === "derived") {
        const drvId = ms.source.derivedId;
        const drv = structure.derived.find((d) => d.id === drvId);
        for (const sid of drv?.sourceIds ?? []) {
          pushRawCol(structure.columns.find((c) => c.id === sid));
        }
      } else {
        pushRawCol(ms);
      }
    }
  }

  const orderedInternalRows = orderedPartNames.flatMap((pn) => groupedBlocksMap.get(pn) ?? []);
  const rawDataSheet: RawDataSheetModel = {
    headers: rawSheetCols.map((c) => c.label),
    rows: orderedInternalRows.map((ir) =>
      rawSheetCols.map((c) => {
        const strVal = ir.cellsByColId[c.id] ?? "";
        const pn = parseNumber(strVal, decimalComma);
        if (pn.value !== null && pn.prefix === "" && pn.unit === "") {
          return pn.value;
        }
        return strVal;
      }),
    ),
  };

  return {
    stage: style.preset === "raw" ? "tidied" : "styled",
    preset: style.preset,
    recommendedPreset: rec.preset,
    accentHex,
    tabularNums: style.tabularNums,
    tableNumber: structure.tableNumber,
    title: structure.title,
    subtitle: structure.subtitle,
    rawGrid: raw.grid,
    suggestedHeaderRows: raw.suggestions.headerRows,
    suggestedFooterRowStart: suggestedFooterStart,
    spanners,
    headers,
    blocks,
    footnotes,
    totalRows: totalBodyRows,
    totalCols: headers.length,
    blockCount: structure.partBy ? blocks.length : 0,
    editedCount,
    globalHeatAllowed,
    hasHeatColumns,
    hasActiveHeatColumns,
    hasColumnVisualOverrides,
    activeHueCount,
    detectedSummaryRowCount,
    isMultiScaleHeat,
    heatLegend,
    heatLegends: showHeaderInlineRamps ? [] : heatLegends,
    rawDataSheet,
  };
}
