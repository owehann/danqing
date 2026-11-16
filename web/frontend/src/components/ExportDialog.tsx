import React, { useEffect, useState } from "react";
import { AlertCircle, Check, Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";
import type { ExportChecksResult, ExportFormat } from "../types";
import { ModalDialog } from "./ModalDialog";

export function ExportDialog(): React.ReactElement | null {
  const { t } = useTranslation();
  const activeDialog = useStudioStore((s) => s.activeDialog);
  const closeDialog = useStudioStore((s) => s.closeDialog);
  const figure = useStudioStore((s) => s.figure);

  const open = activeDialog === "export" && Boolean(figure);

  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [includeR, setIncludeR] = useState(true);
  const [includePython, setIncludePython] = useState(true);
  const [includeJson, setIncludeJson] = useState(false);
  const [includeChanges, setIncludeChanges] = useState(false);

  const [verifying, setVerifying] = useState(false);
  const [checksData, setChecksData] = useState<ExportChecksResult | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (figure) {
      setFormat(figure.kind === "svg" ? "svg" : "pdf");
    }
  }, [figure?.figure_id, figure?.kind]);

  useEffect(() => {
    if (!open || !figure) {
      setChecksData(null);
      return;
    }
    let cancelled = false;
    setVerifying(true);
    setChecksData(null);

    fetch(`/api/v2/figures/${figure.figure_id}/export/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        format,
        include_r: includeR,
        include_python: includePython,
        include_json: includeJson,
        include_change_report: includeChanges,
      }),
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("verify_failed"))))
      .then((data: ExportChecksResult) => {
        if (!cancelled) {
          setChecksData(data);
          setVerifying(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setVerifying(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open, figure?.figure_id, figure?.revision]);

  if (!figure) return null;

  const triggerDownload = async (force: boolean): Promise<void> => {
    if (downloading) return;
    setDownloading(true);
    try {
      const res = await fetch(`/api/v2/figures/${figure.figure_id}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format,
          include_r: includeR,
          include_python: includePython,
          include_json: includeJson,
          include_change_report: includeChanges,
          force,
        }),
      });
      if (!res.ok) return;
      const blob = await res.blob();
      const disp = res.headers.get("Content-Disposition") || "";
      const match = /filename="([^"]+)"/.exec(disp);
      const fallbackExt =
        includeR || includePython || includeJson || includeChanges
          ? "zip"
          : format.startsWith("png")
            ? "png"
            : format;
      const outName = match ? match[1] : `danqing_export.${fallbackExt}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = outName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1500);
      closeDialog();
    } finally {
      setDownloading(false);
    }
  };

  const formats: ExportFormat[] = ["pdf", "svg", "png_300", "png_600"];
  const allPassed = Boolean(checksData?.checks.all_passed);

  return (
    <ModalDialog
      open={open}
      onClose={closeDialog}
      title={t("export.title")}
      closeLabel={t("export.close")}
      footer={
        <>
          {checksData && !allPassed ? (
            <button
              type="button"
              className="dq-btn dq-btn--ghost"
              disabled={downloading}
              onClick={() => void triggerDownload(true)}
            >
              {t("export.downloadAnyway")}
            </button>
          ) : null}
          <button
            type="button"
            className="dq-btn dq-btn--primary"
            disabled={verifying || !checksData || !allPassed || downloading}
            onClick={() => void triggerDownload(false)}
          >
            <Download size={15} strokeWidth={1.5} aria-hidden="true" />
            <span>
              {downloading ? t("tableStudio.exportDialog.generating") : t("export.download")}
            </span>
          </button>
        </>
      }
    >
      <fieldset className="dq-field-group">
        <legend>{t("export.formatLabel")}</legend>
        <div className="dq-format-grid">
          {formats.map((fmt) => {
            const isSameAsInput =
              (fmt === "pdf" && figure.kind === "pdf") ||
              (fmt === "svg" && figure.kind === "svg");
            return (
              <label key={fmt} className="dq-format-item">
                <input
                  type="radio"
                  name="dq-export-format"
                  value={fmt}
                  checked={format === fmt}
                  onChange={() => setFormat(fmt)}
                />
                <span>
                  {t(`export.formats.${fmt}`)}{" "}
                  {isSameAsInput ? (
                    <span style={{ color: "var(--text-3)", fontSize: 11.5 }}>
                      {t("export.sameAsInput")}
                    </span>
                  ) : null}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <fieldset className="dq-field-group">
        <legend>{t("export.alsoInclude")}</legend>
        <label className="dq-radio-option">
          <input
            type="checkbox"
            checked={includeR}
            onChange={(e) => setIncludeR(e.target.checked)}
          />
          <span>{t("export.incR")}</span>
        </label>
        <label className="dq-radio-option">
          <input
            type="checkbox"
            checked={includePython}
            onChange={(e) => setIncludePython(e.target.checked)}
          />
          <span>{t("export.incPython")}</span>
        </label>
        <label className="dq-radio-option">
          <input
            type="checkbox"
            checked={includeJson}
            onChange={(e) => setIncludeJson(e.target.checked)}
          />
          <span>{t("export.incJson")}</span>
        </label>
        <label className="dq-radio-option">
          <input
            type="checkbox"
            checked={includeChanges}
            onChange={(e) => setIncludeChanges(e.target.checked)}
          />
          <span>{t("export.incChanges")}</span>
        </label>
      </fieldset>

      <div className="dq-field-group">
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-2)" }}>
          {t("export.checksLabel")}
        </div>
        <div className="dq-checks-box">
          {verifying || !checksData ? (
            <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>
              {t("export.verifying")}
            </div>
          ) : (
            <>
              <div
                className={`dq-check-row${
                  checksData.checks.shapes_and_text_unchanged ? "" : " dq-check-row--fail"
                }`}
              >
                {checksData.checks.shapes_and_text_unchanged ? (
                  <Check size={15} strokeWidth={1.8} aria-hidden="true" />
                ) : (
                  <AlertCircle size={15} strokeWidth={1.8} aria-hidden="true" />
                )}
                <span>{t("export.checkShapes")}</span>
              </div>

              <div
                className={`dq-check-row${
                  checksData.checks.raw_images_untouched.passed ? "" : " dq-check-row--fail"
                }`}
              >
                {checksData.checks.raw_images_untouched.passed ? (
                  <Check size={15} strokeWidth={1.8} aria-hidden="true" />
                ) : (
                  <AlertCircle size={15} strokeWidth={1.8} aria-hidden="true" />
                )}
                <span>
                  {t("export.checkImages", {
                    count: checksData.checks.raw_images_untouched.count,
                  })}
                </span>
              </div>

              <div
                className={`dq-check-row${
                  checksData.checks.colorblind_safe.passed ? "" : " dq-check-row--fail"
                }`}
              >
                {checksData.checks.colorblind_safe.passed ? (
                  <Check size={15} strokeWidth={1.8} aria-hidden="true" />
                ) : (
                  <AlertCircle size={15} strokeWidth={1.8} aria-hidden="true" />
                )}
                <span>
                  {checksData.checks.colorblind_safe.passed
                    ? t("export.checkColorblind")
                    : t("export.checkColorblindWarn", {
                        panels:
                          checksData.checks.colorblind_safe.problem_panels.join(", ") || "Panel A",
                      })}
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </ModalDialog>
  );
}
