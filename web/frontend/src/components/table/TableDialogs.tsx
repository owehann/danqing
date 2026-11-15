import React, { useEffect, useId, useMemo, useState } from "react";
import { Download, FileSpreadsheet } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../../store";
import {
  buildPythonPreviewCode,
  buildStandaloneStyledHtml,
  makeSafeFilenameStem,
} from "../../table/exporters";
import { buildModel } from "../../table/pipeline";
import { type TableExportFormat, useTableStudioStore } from "../../table/tableStore";
import { ModalDialog } from "../ModalDialog";

const EXPORT_FORMATS: TableExportFormat[] = ["xlsx", "docx", "html", "zip"];

export function TableDialogs(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const catalogPalettes = useStudioStore((s) => s.palettes);
  const docs = useTableStudioStore((s) => s.docs);
  const activeId = useTableStudioStore((s) => s.activeId);
  const activeModal = useTableStudioStore((s) => s.activeModal);
  const busy = useTableStudioStore((s) => s.busy);
  const errorKey = useTableStudioStore((s) => s.errorKey);
  const setActiveModal = useTableStudioStore((s) => s.setActiveModal);
  const submitPaste = useTableStudioStore((s) => s.submitPaste);
  const commit = useTableStudioStore((s) => s.commit);
  const downloadExport = useTableStudioStore((s) => s.downloadExport);

  const doc = docs[activeId];
  const isZh = i18n.language.startsWith("zh");
  const langKey: "en" | "zh" = isZh ? "zh" : "en";

  const [pasteText, setPasteText] = useState("");
  const [pasteHtml, setPasteHtml] = useState("");
  const [exportFormat, setExportFormat] = useState<TableExportFormat>("xlsx");
  const [filenameStem, setFilenameStem] = useState("danqing_table");
  const [includeFootnotes, setIncludeFootnotes] = useState(true);

  const filenameInputId = useId();
  const tableNumInputId = useId();
  const tableTitleInputId = useId();

  useEffect(() => {
    if (activeModal === "export" && doc) {
      setFilenameStem(makeSafeFilenameStem(doc));
      setIncludeFootnotes(true);
    }
    if (activeModal === "paste") {
      setPasteText("");
      setPasteHtml("");
    }
  }, [activeModal, doc?.raw.snapshotId]);

  const exportModel = useMemo(() => {
    if (!doc) return null;
    const base = buildModel(doc, langKey, catalogPalettes);
    if (!includeFootnotes) {
      return { ...base, footnotes: [] };
    }
    return base;
  }, [doc, langKey, catalogPalettes, includeFootnotes]);

  const handleLoadSamplePaste = async (): Promise<void> => {
    try {
      const res = await fetch("/api/v2/tables/samples/penguins_long");
      if (!res.ok) return;
      const body = (await res.json()) as { grid?: string[][] };
      const topRows = (body.grid ?? []).slice(0, 6);
      setPasteText(topRows.map((r) => r.join("\t")).join("\n"));
      setPasteHtml("");
    } catch {
      // Ignore sample fetch errors
    }
  };

  const hasSparklines = useMemo(() => {
    if (!exportModel) return false;
    return exportModel.blocks.some((b) =>
      b.rows.some((r) => r.some((c) => Boolean(c.sparklineValues && c.sparklineValues.length >= 2))),
    );
  }, [exportModel]);

  return (
    <>
      {/* Paste Modal */}
      <ModalDialog
        open={activeModal === "paste"}
        onClose={() => setActiveModal(null)}
        title={t("tableStudio.pasteDialog.title")}
        closeLabel={t("export.close")}
        wide
        footer={
          <>
            <button
              type="button"
              className="dq-btn"
              disabled={busy}
              onClick={() => void handleLoadSamplePaste()}
            >
              <FileSpreadsheet size={14} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.pasteDialog.fillSample")}</span>
            </button>
            <button
              type="button"
              className="dq-btn dq-btn--primary"
              disabled={busy || (!pasteText.trim() && !pasteHtml.trim())}
              onClick={() => void submitPaste({ text: pasteText, html: pasteHtml })}
            >
              <span>
                {busy
                  ? t("tableStudio.pasteDialog.parsing")
                  : t("tableStudio.pasteDialog.submit")}
              </span>
            </button>
          </>
        }
      >
        <p className="dq-table-dialog-lead">{t("tableStudio.pasteDialog.lead")}</p>
        {errorKey ? (
          <div className="dq-table-error-banner" role="alert">
            <span>{t(errorKey)}</span>
          </div>
        ) : null}
        <textarea
          rows={9}
          className="dq-table-paste-textarea"
          value={pasteText}
          placeholder={t("tableStudio.pasteDialog.placeholder")}
          aria-label={t("tableStudio.pasteDialog.placeholder")}
          onChange={(e) => {
            setPasteText(e.target.value);
            setPasteHtml("");
          }}
          onPaste={(e) => {
            const html = e.clipboardData?.getData("text/html") || "";
            if (html && html.includes("<table")) {
              setPasteHtml(html);
            }
          }}
        />
      </ModalDialog>

      {/* Export Modal */}
      <ModalDialog
        open={activeModal === "export" && Boolean(doc && exportModel)}
        onClose={() => setActiveModal(null)}
        title={t("tableStudio.exportDialog.title")}
        closeLabel={t("export.close")}
        wide
        footer={
          <button
            type="button"
            className="dq-btn dq-btn--primary"
            disabled={busy || !exportModel}
            onClick={async () => {
              if (!exportModel) return;
              const ok = await downloadExport(exportFormat, exportModel, filenameStem);
              if (ok) setActiveModal(null);
            }}
          >
            <Download size={14} strokeWidth={1.6} aria-hidden="true" />
            <span>
              {busy
                ? t("tableStudio.exportDialog.generating")
                : t("tableStudio.exportDialog.downloadBtn", {
                    ext: `.${exportFormat}`,
                  })}
            </span>
          </button>
        }
      >
        {doc && exportModel ? (
          <div className="dq-export-split-grid">
            {/* Left pane: Filename, Title/Footnotes quick controls, Format radios */}
            <div className="dq-export-left-col">
              {errorKey ? (
                <div className="dq-table-error-banner" role="alert">
                  <span>{t(errorKey)}</span>
                </div>
              ) : null}

              <div className="dq-export-field">
                <label htmlFor={filenameInputId} className="dq-field-label">
                  {t("tableStudio.exportDialog.filenameLabel")}
                </label>
                <div className="dq-filename-row">
                  <input
                    id={filenameInputId}
                    type="text"
                    className="dq-input"
                    value={filenameStem}
                    onChange={(e) => setFilenameStem(e.target.value)}
                  />
                  <span className="dq-filename-ext">{`.${exportFormat}`}</span>
                </div>
              </div>

              <div className="dq-export-meta-pair">
                <div className="dq-export-field dq-export-field--num">
                  <label htmlFor={tableNumInputId} className="dq-field-label">
                    {t("tableStudio.exportDialog.tableNumLabel")}
                  </label>
                  <input
                    id={tableNumInputId}
                    type="text"
                    className="dq-input dq-input--compact"
                    value={doc.structure.tableNumber}
                    onChange={(e) =>
                      commit((draft) => {
                        draft.structure.tableNumber = e.target.value;
                      })
                    }
                  />
                </div>
                <div className="dq-export-field dq-export-field--grow">
                  <label htmlFor={tableTitleInputId} className="dq-field-label">
                    {t("tableStudio.exportDialog.tableTitleLabel")}
                  </label>
                  <input
                    id={tableTitleInputId}
                    type="text"
                    className="dq-input dq-input--compact"
                    value={doc.structure.title}
                    placeholder={t("tableStudio.canvas.editTitlePlaceholder")}
                    onChange={(e) =>
                      commit((draft) => {
                        draft.structure.title = e.target.value;
                      })
                    }
                  />
                </div>
              </div>

              <label className="dq-check-row">
                <input
                  type="checkbox"
                  checked={includeFootnotes}
                  onChange={(e) => setIncludeFootnotes(e.target.checked)}
                />
                <span>{t("tableStudio.exportDialog.includeFootnotes")}</span>
              </label>

              <div className="dq-field-label">{t("tableStudio.exportDialog.formatLabel")}</div>
              <div className="dq-export-format-radios">
                {EXPORT_FORMATS.map((fmt) => (
                  <label
                    key={fmt}
                    className={`dq-export-radio-card${
                      exportFormat === fmt ? " dq-export-radio-card--active" : ""
                    }`}
                  >
                    <input
                      type="radio"
                      name="dq-table-export-format"
                      checked={exportFormat === fmt}
                      onChange={() => setExportFormat(fmt)}
                    />
                    <div className="dq-export-radio-card__text">
                      <span className="dq-export-radio-card__title">
                        {t(`tableStudio.exportDialog.formats.${fmt}.title`)}
                      </span>
                      <span className="dq-export-radio-card__desc">
                        {t(`tableStudio.exportDialog.formats.${fmt}.desc`)}
                      </span>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Right pane: Live summary / HTML preview / Python great_tables script */}
            <div className="dq-export-right-col">
              <div className="dq-field-label">{t("tableStudio.exportDialog.previewHeading")}</div>

              {exportFormat === "xlsx" || exportFormat === "docx" ? (
                <div className="dq-export-summary-box">
                  <ul className="dq-export-summary-list">
                    <li>
                      {t("tableStudio.exportDialog.summaryHeaderLayers", {
                        count: exportModel.spanners.length > 0 ? 2 : 1,
                      })}
                    </li>
                    <li>
                      {t("tableStudio.exportDialog.summaryColumns", {
                        count: exportModel.totalCols,
                        rows: exportModel.totalRows,
                      })}
                    </li>
                    <li>
                      {t("tableStudio.exportDialog.summaryBlocks", {
                        count: exportModel.blockCount,
                      })}
                    </li>
                    <li>
                      {t("tableStudio.exportDialog.summaryFootnotes", {
                        count: exportModel.footnotes.length,
                      })}
                    </li>
                    <li>
                      {t("tableStudio.exportDialog.summaryEdits", {
                        count: exportModel.editedCount,
                      })}
                    </li>
                    {exportFormat === "xlsx" ? (
                      <li>{t("tableStudio.exportDialog.summaryRawDataSheet")}</li>
                    ) : null}
                  </ul>
                  {exportFormat === "xlsx" && hasSparklines ? (
                    <p className="dq-style-disabled-note">
                      {t("tableStudio.exportDialog.sparklineFallbackNote")}
                    </p>
                  ) : null}
                </div>
              ) : exportFormat === "html" ? (
                <div
                  className="dq-export-html-preview"
                  dangerouslySetInnerHTML={{
                    __html: buildStandaloneStyledHtml(doc, exportModel),
                  }}
                />
              ) : (
                <pre className="dq-code-block dq-table-code-pre">
                  <code>{buildPythonPreviewCode(doc, exportModel)}</code>
                </pre>
              )}
            </div>
          </div>
        ) : null}
      </ModalDialog>
    </>
  );
}
