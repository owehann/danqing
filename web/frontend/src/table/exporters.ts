import { orientRampStops, resolveTableRamp } from "./color";
import type { RenderModel, TableDoc } from "./model";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function composeFullTitle(model: RenderModel): string {
  const num = model.tableNumber.trim();
  const ttl = model.title.trim();
  if (num && ttl) return `${num}. ${ttl}`;
  return ttl || num || "Table 1";
}

export function makeSafeFilenameStem(doc: TableDoc): string {
  const rawBase = [doc.structure.tableNumber, doc.structure.title]
    .map((s) => s.trim())
    .filter(Boolean)
    .join("_");
  const fallback = doc.raw.source.filename.replace(/\.[^.]+$/, "") || "danqing_table";
  const candidate = (rawBase || fallback)
    .replace(/[^\w\-\u4e00-\u9fff]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return candidate.slice(0, 64) || "danqing_table";
}

export function serializeToBackendExportPayload(
  model: RenderModel,
  filenameStem: string,
  sourceRaw?: TableDoc["sourceRaw"],
): Record<string, unknown> {
  const sourceDataSheet =
    sourceRaw && sourceRaw.grid.length > 0
      ? {
          headers: sourceRaw.grid[0] ?? [],
          rows: sourceRaw.grid.slice(1),
        }
      : null;

  return {
    filename_stem: filenameStem,
    title: composeFullTitle(model),
    subtitle: model.subtitle,
    preset: model.preset === "raw" ? "cns_three_line" : model.preset,
    spanners: model.spanners.map((sp) => ({
      label: sp.label,
      superscript: sp.superscript,
      start_col: sp.startCol,
      end_col: sp.endCol,
    })),
    headers: model.headers.map((h) => ({
      label: h.label,
      superscript: h.superscript,
      align: h.align,
      effective_visual: h.effectiveVisual,
    })),
    blocks: model.blocks.map((b) => ({
      part_name: b.partName,
      part_accent: b.partAccent,
      rows: b.rows.map((r) =>
        r.map((c) => ({
          text: c.display,
          superscript: c.superscript,
          align: c.align,
          bg_hex: c.bgHex ?? "#FFFFFF",
          fg_hex: c.fgHex,
          bold: c.bold,
          box_border: c.boxBorder,
          no_wrap: c.noWrap,
          raw_number: c.parts ? null : c.value,
          number_format: c.numFmt,
          sparkline_values: c.sparklineValues,
          bar_spec: c.barSpec
            ? {
                ratio: c.barSpec.ratio,
                zero_pct: c.barSpec.zeroPct,
                start_pct: c.barSpec.startPct,
                width_pct: c.barSpec.widthPct,
                fill_hex: c.barSpec.fillHex,
                bidirectional: c.barSpec.bidirectional,
                is_negative: c.barSpec.isNegative,
                domain_min: c.barSpec.domainMin,
                domain_max: c.barSpec.domainMax,
              }
            : null,
          edited_from: c.editedFrom,
          indent: c.indent,
        })),
      ),
    })),
    footnotes: model.footnotes.map((fn) => ({
      symbol: fn.symbol,
      text: fn.text,
    })),
    raw_data_sheet: model.rawDataSheet,
    ...(sourceDataSheet ? { source_data_sheet: sourceDataSheet } : {}),
  };
}

export function buildRuleJsonObject(doc: TableDoc): Record<string, unknown> {
  return {
    schema: "danqing.table_studio.v2",
    source: doc.raw.source,
    structure: doc.structure,
    style: doc.style,
  };
}

export function serializeToBackendZipPayload(
  doc: TableDoc,
  model: RenderModel,
  filenameStem: string,
): Record<string, unknown> {
  const csvHeaders = model.rawDataSheet.headers;
  const csvRows = model.rawDataSheet.rows;

  // Map column IDs to rawDataSheet column names for great_tables script
  const colIdToName = new Map<string, string>();
  doc.structure.columns.forEach((c) => {
    colIdToName.set(c.id, c.label);
  });

  // Deduplicate csvHeaders if needed so pandas/great_tables columns are unique
  const seenCounts = new Map<string, number>();
  const uniqueCsvHeaders = csvHeaders.map((h) => {
    const cnt = (seenCounts.get(h) ?? 0) + 1;
    seenCounts.set(h, cnt);
    return cnt === 1 ? h : `${h}_${cnt}`;
  });

  // Also map visible non-derived columns in order onto uniqueCsvHeaders
  const rawSpecList = (() => {
    const list: string[] = [];
    const added = new Set<string>();
    const push = (id: string | undefined) => {
      if (!id || added.has(id)) return;
      const c = doc.structure.columns.find((x) => x.id === id);
      if (!c) return;
      added.add(id);
      list.push(id);
    };
    if (doc.structure.partBy) push(doc.structure.partBy);
    for (const h of model.headers) {
      for (const mid of h.memberColIds) {
        const mc = doc.structure.columns.find((x) => x.id === mid);
        if (mc?.source.kind === "derived") {
          const drvId = mc.source.derivedId;
          const drv = doc.structure.derived.find((d) => d.id === drvId);
          for (const sid of drv?.sourceIds ?? []) push(sid);
        } else {
          push(mid);
        }
      }
    }
    return list;
  })();

  rawSpecList.forEach((cid, idx) => {
    if (idx < uniqueCsvHeaders.length) {
      colIdToName.set(cid, uniqueCsvHeaders[idx]);
    }
  });

  const firstHeader = model.headers[0];
  const rownameCol =
    firstHeader && firstHeader.align === "left" && !firstHeader.isMerged
      ? (colIdToName.get(firstHeader.colId) ?? "")
      : "";
  const groupnameCol = doc.structure.partBy
    ? (colIdToName.get(doc.structure.partBy) ?? "")
    : "";

  const pCols = doc.structure.columns
    .filter((c) => c.role === "sig" && colIdToName.has(c.id))
    .map((c) => colIdToName.get(c.id)!);

  const decimalsMap: Record<string, number> = {};
  for (const c of doc.structure.columns) {
    const mapped = colIdToName.get(c.id);
    if (!mapped || c.role === "sig" || mapped === rownameCol || mapped === groupnameCol) continue;
    if (typeof c.precision === "number") {
      decimalsMap[mapped] = c.precision;
    }
  }

  const gtSpanners = doc.structure.spanners
    .map((sp) => ({
      label: sp.label,
      columns: sp.columnIds.map((cid) => colIdToName.get(cid)).filter((x): x is string => Boolean(x)),
    }))
    .filter((sp) => sp.columns.length >= 1);

  const gtMerges = doc.structure.merges
    .map((mg) => {
      const cols = mg.columnIds
        .map((cid) => colIdToName.get(cid))
        .filter((x): x is string => Boolean(x));
      const pattern =
        mg.pattern === "iqr"
          ? cols.length >= 3
            ? "{0} [{1}–{2}]"
            : "{0} [{1}]"
          : mg.pattern === "ci" && cols.length >= 3
            ? "{0} ({1}–{2})"
            : mg.pattern === "plusminus"
              ? "{0} ± {1}"
              : "{0} ({1})";
      return { columns: cols, pattern };
    })
    .filter((mg) => mg.columns.length >= 2);

  const gtHeatGroupMap = new Map<string, { columns: string[]; palette: string[] }>();
  for (const h of model.headers) {
    if (h.effectiveVisual !== "heat") continue;
    const leadId = h.memberColIds[0] ?? h.colId;
    const mappedName = colIdToName.get(leadId);
    if (!mappedName) continue;
    const colSpec = doc.structure.columns.find((x) => x.id === leadId);
    const dir = colSpec?.visualConfig?.direction ?? "normal";
    const wantDiv =
      colSpec?.visualConfig?.center === "ratio_1" ||
      typeof (colSpec?.visualConfig?.center ?? doc.style.heatCenter) === "number";
    const stops = orientRampStops(resolveTableRamp(h.effectivePaletteId, [], wantDiv).stops, dir);
    const pKey = stops.join("|");
    let grp = gtHeatGroupMap.get(pKey);
    if (!grp) {
      grp = { columns: [], palette: stops };
      gtHeatGroupMap.set(pKey, grp);
    }
    if (!grp.columns.includes(mappedName)) {
      grp.columns.push(mappedName);
    }
  }
  const gtHeatCols = Array.from(gtHeatGroupMap.values());

  const sourceDataSheet =
    doc.sourceRaw && doc.sourceRaw.grid.length > 0
      ? {
          headers: doc.sourceRaw.grid[0] ?? [],
          rows: doc.sourceRaw.grid.slice(1),
        }
      : null;

  return {
    filename_stem: filenameStem,
    table_json: buildRuleJsonObject(doc),
    csv_headers: uniqueCsvHeaders,
    csv_rows: csvRows,
    ...(sourceDataSheet ? { source_data_sheet: sourceDataSheet } : {}),
    gt_meta: {
      title: composeFullTitle(model),
      subtitle: model.subtitle,
      rowname_col: rownameCol,
      groupname_col: groupnameCol,
      p_cols: pCols,
      decimals_map: decimalsMap,
      spanners: gtSpanners,
      merges: gtMerges,
      heat_cols: gtHeatCols,
      footnotes: model.footnotes.map((f) => ({ symbol: f.symbol, text: f.text })),
    },
  };
}

export function buildPythonPreviewCode(doc: TableDoc, model: RenderModel): string {
  const payload = serializeToBackendZipPayload(doc, model, "preview") as {
    gt_meta: {
      title: string;
      subtitle: string;
      rowname_col: string;
      groupname_col: string;
      p_cols: string[];
      decimals_map: Record<string, number>;
      spanners: Array<{ label: string; columns: string[] }>;
      merges: Array<{ columns: string[]; pattern: string }>;
      heat_cols: Array<{ columns: string[]; palette: string[] }>;
      footnotes: Array<{ symbol: string; text: string }>;
    };
  };
  const m = payload.gt_meta;
  const lines: string[] = [
    "from pathlib import Path",
    "import pandas as pd",
    "from great_tables import GT",
    "",
    'HERE = Path(__file__).resolve().parent',
    'df = pd.read_csv(HERE / "data.csv")',
  ];
  for (const pc of m.p_cols) {
    lines.push(`if ${JSON.stringify(pc)} in df.columns:`);
    lines.push(`    df[${JSON.stringify(pc)}] = pd.to_numeric(df[${JSON.stringify(pc)}], errors="coerce")`);
  }
  const gtArgs: string[] = ["df"];
  if (m.rowname_col) gtArgs.push(`rowname_col=${JSON.stringify(m.rowname_col)}`);
  if (m.groupname_col) gtArgs.push(`groupname_col=${JSON.stringify(m.groupname_col)}`);
  lines.push(`gt = GT(${gtArgs.join(", ")})`);
  if (m.title) {
    lines.push(
      m.subtitle
        ? `gt = gt.tab_header(title=${JSON.stringify(m.title)}, subtitle=${JSON.stringify(m.subtitle)})`
        : `gt = gt.tab_header(title=${JSON.stringify(m.title)})`,
    );
  }
  for (const [col, dec] of Object.entries(m.decimals_map)) {
    lines.push(`gt = gt.fmt_number(columns=[${JSON.stringify(col)}], decimals=${dec})`);
  }
  for (const sp of m.spanners) {
    lines.push(
      `gt = gt.tab_spanner(label=${JSON.stringify(sp.label)}, columns=${JSON.stringify(sp.columns)})`,
    );
  }
  for (const hc of m.heat_cols) {
    lines.push(
      `gt = gt.data_color(columns=${JSON.stringify(hc.columns)}, palette=${JSON.stringify(hc.palette)})`,
    );
  }
  for (const mg of m.merges) {
    lines.push(
      `gt = gt.cols_merge(columns=${JSON.stringify(mg.columns)}, pattern=${JSON.stringify(mg.pattern)})`,
    );
  }
  for (const fn of m.footnotes) {
    const txt = `${fn.symbol} ${fn.text}`.trim();
    if (txt) lines.push(`gt = gt.tab_source_note(source_note=${JSON.stringify(txt)})`);
  }
  lines.push('Path("table_rendered.html").write_text(gt.as_raw_html(), encoding="utf-8")');
  return lines.join("\n");
}

export function buildStandaloneStyledHtml(doc: TableDoc, model: RenderModel): string {
  if (model.stage === "raw") {
    const trs = model.rawGrid
      .map(
        (r) =>
          `<tr>${r
            .map(
              (c) =>
                `<td style="padding:4px 8px;border:1px solid #CBD5E1;font-family:monospace;font-size:12px;">${escapeHtml(c)}</td>`,
            )
            .join("")}</tr>`,
      )
      .join("\n");
    return `<table style="border-collapse:collapse;background:#FFFFFF;color:#111827;"><tbody>${trs}</tbody></table>`;
  }

  const embeddedRules = escapeHtml(
    JSON.stringify({
      ...buildRuleJsonObject(doc),
      rawGrid: doc.raw.grid,
      cellMerges: doc.raw.cellMerges,
    }),
  );

  const nCols = Math.max(model.headers.length, 1);
  const fullTitle = composeFullTitle(model);
  const preset = model.preset;
  const isRawGrid = preset === "raw";
  const isMatrix = preset === "matrix_heatmap";
  const isFt = preset === "ft_editorial";
  const cardBg = isFt ? "#FFFDF9" : "#FFFFFF";
  const thBg = isRawGrid || isMatrix ? "#F8FAFC" : cardBg;
  const cellBorder = isRawGrid
    ? "border:1px solid #CBD5E1;"
    : isFt
      ? "border-bottom:1px solid #E6DFD5;"
      : "";

  let spannerRowHtml = "";
  if (model.spanners.length > 0) {
    const cells: string[] = [];
    let c = 0;
    while (c < nCols) {
      const sp = model.spanners.find((s) => s.startCol === c);
      if (sp) {
        const span = sp.endCol - sp.startCol + 1;
        const supHtml = sp.superscript ? `<sup>${escapeHtml(sp.superscript)}</sup>` : "";
        const spRule = isRawGrid
          ? "border:1px solid #CBD5E1;background:#F8FAFC;"
          : `border-top:${isFt ? "1px solid #D1D5DB" : "2px solid #000000"};border-bottom:1px solid #000000;background:${thBg};`;
        cells.push(
          `<th colspan="${span}" scope="colgroup" style="text-align:center;padding:6px 10px;${spRule}font-weight:700;color:#000000;">${escapeHtml(sp.label)}${supHtml}</th>`,
        );
        c = sp.endCol + 1;
      } else {
        const emptyRule = isRawGrid
          ? "border:1px solid #CBD5E1;background:#F8FAFC;"
          : `border-top:${isFt ? "1px solid #D1D5DB" : "2px solid #000000"};background:${thBg};`;
        cells.push(`<th style="padding:6px 10px;${emptyRule}"></th>`);
        c += 1;
      }
    }
    spannerRowHtml = `<tr>${cells.join("")}</tr>`;
  }

  const topRuleCss = isRawGrid
    ? ""
    : model.spanners.length > 0
      ? ""
      : isFt
        ? "border-top:1px solid #D1D5DB;"
        : "border-top:2px solid #000000;";
  const headerRuleCss = isRawGrid
    ? "border:1px solid #CBD5E1;"
    : `${topRuleCss}border-bottom:${isMatrix || isFt ? "1.5px" : "1px"} solid #000000;`;
  const headerCellsHtml = model.headers
    .map((h) => {
      const supHtml = h.superscript ? `<sup>${escapeHtml(h.superscript)}</sup>` : "";
      return `<th scope="col" style="text-align:${h.align};padding:7px 10px;background:${thBg};${headerRuleCss}font-weight:700;color:#000000;">${escapeHtml(h.label)}${supHtml}</th>`;
    })
    .join("");

  const totalBodyRows = model.blocks.reduce((s, b) => s + b.rows.length, 0);
  let emitted = 0;
  const bodyRowsHtml: string[] = [];

  for (const block of model.blocks) {
    if (block.partName) {
      const partStyle = isRawGrid
        ? "padding:6px 10px;background:#F8FAFC;color:#1E293B;font-weight:700;border:1px solid #CBD5E1;"
        : `padding:6px 10px;background:${isFt ? "#F6F1E7" : "#F8FAFC"};color:#111827;font-weight:700;border-left:4px solid ${block.partAccent};border-top:1px solid #E2E8F0;border-bottom:1px solid #E2E8F0;`;
      bodyRowsHtml.push(
        `<tr><td colspan="${nCols}" style="${partStyle}">${escapeHtml(block.partName)}</td></tr>`,
      );
    }
    for (const r of block.rows) {
      emitted += 1;
      const isLast = emitted === totalBodyRows;
      const tds = r
        .map((c, cIdx) => {
          const fallbackStubBg = isMatrix && cIdx === 0 && !c.bgHex ? "#F8FAFC" : null;
          const resolvedBg = c.bgHex ?? fallbackStubBg;
          const bg = resolvedBg ? `background:${resolvedBg};` : "";
          const fw = c.bold ? "font-weight:700;" : "";
          const padLeft = 10 + c.indent * 16;
          const btm =
            !isRawGrid && isLast ? "border-bottom:2px solid #000000;" : "";
          const isHeatCol = model.headers[cIdx]?.effectiveVisual === "heat";
          const partialHeatGap =
            !isRawGrid && !isMatrix && isHeatCol && c.bgHex
              ? "border-left:1px solid #FFFFFF;border-right:1px solid #FFFFFF;border-top:1px solid #FFFFFF;"
              : "";
          const radius = isMatrix ? "border-radius:3px;" : "";
          const box = c.boxBorder ? "outline:1px solid #000000;outline-offset:-1px;" : "";
          const supHtml = c.superscript ? `<sup>${escapeHtml(c.superscript)}</sup>` : "";
          let cellInnerHtml = `${escapeHtml(c.display)}${supHtml}`;
          if (c.barSpec) {
            const bs = c.barSpec;
            const zeroTickHtml = bs.bidirectional
              ? `<span style="position:absolute;top:-1px;bottom:-1px;left:${bs.zeroPct.toFixed(1)}%;width:1px;background:#64748B;"></span>`
              : "";
            const barTrackHtml = `<span aria-hidden="true" style="position:relative;display:inline-block;vertical-align:middle;width:54px;height:8px;margin-left:8px;background:#EEF2F6;border-radius:2px;overflow:hidden;"><span style="position:absolute;top:0;bottom:0;left:${bs.startPct.toFixed(1)}%;width:${Math.max(bs.widthPct, bs.ratio > 0 ? 2 : 0).toFixed(1)}%;background:${bs.fillHex};border-radius:1.5px;"></span>${zeroTickHtml}</span>`;
            cellInnerHtml = `<span style="display:inline-flex;align-items:center;justify-content:flex-end;"><span>${cellInnerHtml}</span>${barTrackHtml}</span>`;
          }
          return `<td style="text-align:${c.align};padding:6px 10px 6px ${padLeft}px;${bg}color:${c.fgHex};${fw}${cellBorder}${partialHeatGap}${btm}${radius}${box}font-variant-numeric:tabular-nums;">${cellInnerHtml}</td>`;
        })
        .join("");
      bodyRowsHtml.push(`<tr>${tds}</tr>`);
    }
  }

  const fnHtml = model.footnotes
    .map((f) => {
      const sym = f.symbol ? `<sup>${escapeHtml(f.symbol)}</sup> ` : "";
      return `<div style="font-size:11.5px;color:#475569;margin-top:3px;">${sym}${escapeHtml(f.text)}</div>`;
    })
    .join("");

  const tableBorderCss = isMatrix
    ? "border-collapse:separate;border-spacing:3px;"
    : "border-collapse:collapse;";
  const ftTopBar = isFt
    ? `<div style="height:3.5px;background:#111827;margin-bottom:8px;"></div>`
    : "";
  const captionFont = isFt
    ? "font-family:Georgia,'Times New Roman',serif;font-size:16.5px;"
    : "font-size:14px;";

  return [
    `<div style="background:${cardBg};color:#111827;font-family:Arial,Helvetica,sans-serif;padding:14px;">`,
    `<table data-danqing-rules="${embeddedRules}" style="${tableBorderCss}width:100%;font-size:13px;background:${cardBg};color:#111827;">`,
    `<caption style="caption-side:top;text-align:left;font-weight:700;${captionFont}padding-bottom:8px;color:#000000;">${ftTopBar}${escapeHtml(fullTitle)}${model.subtitle ? `<div style="font-family:Arial,Helvetica,sans-serif;font-weight:400;font-size:12px;color:#475569;margin-top:2px;">${escapeHtml(model.subtitle)}</div>` : ""}</caption>`,
    `<thead>${spannerRowHtml}<tr>${headerCellsHtml}</tr></thead>`,
    `<tbody>${bodyRowsHtml.join("\n")}</tbody>`,
    `</table>`,
    fnHtml ? `<div style="margin-top:6px;">${fnHtml}</div>` : "",
    `</div>`,
  ].join("\n");
}

export function buildClipboardTsv(model: RenderModel): string {
  if (model.stage === "raw") {
    return model.rawGrid.map((r) => r.join("\t")).join("\n");
  }
  const lines: string[] = [];
  if (model.title || model.tableNumber) {
    lines.push(composeFullTitle(model));
  }
  lines.push(model.headers.map((h) => h.label).join("\t"));
  for (const b of model.blocks) {
    if (b.partName) lines.push(`# ${b.partName}`);
    for (const r of b.rows) {
      lines.push(r.map((c) => c.display).join("\t"));
    }
  }
  for (const fn of model.footnotes) {
    lines.push(`${fn.symbol} ${fn.text}`.trim());
  }
  return lines.join("\n");
}
