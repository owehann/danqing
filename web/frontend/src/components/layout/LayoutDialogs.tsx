import React, { useState } from "react";
import { ArrowRight, Check, Copy, Download, FileCode2, Palette, Table2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLayoutStudioStore } from "../../layout/layoutStore";
import { useStudioStore } from "../../store";
import { ModalDialog } from "../ModalDialog";

export function LayoutDialogs(): React.ReactElement {
  const { t } = useTranslation();
  const exportModalOpen = useLayoutStudioStore((s) => s.exportModalOpen);
  const composed = useLayoutStudioStore((s) => s.composed);
  const handoffBusy = useLayoutStudioStore((s) => s.handoffBusy);
  const setExportModalOpen = useLayoutStudioStore((s) => s.setExportModalOpen);
  const exportHandoffSvgFile = useLayoutStudioStore((s) => s.exportHandoffSvgFile);
  const downloadExport = useLayoutStudioStore((s) => s.downloadExport);

  const setStudioMode = useStudioStore((s) => s.setStudioMode);
  const uploadFile = useStudioStore((s) => s.uploadFile);

  const [codeTab, setCodeTab] = useState<"r" | "py">("r");
  const [copied, setCopied] = useState(false);

  const handleSendToFigureColor = async (): Promise<void> => {
    const file = await exportHandoffSvgFile();
    if (!file) return;
    setExportModalOpen(false);
    setStudioMode("figure");
    await uploadFile(file);
  };

  const handleOpenTableStudio = (): void => {
    setExportModalOpen(false);
    setStudioMode("table");
  };

  const snippet = composed
    ? codeTab === "r"
      ? composed.mode_b_contract.r_snippet
      : composed.mode_b_contract.python_snippet
    : "";

  return (
    <ModalDialog
      open={exportModalOpen}
      onClose={() => setExportModalOpen(false)}
      title={t("layoutStudio.dialog.title")}
      closeLabel={t("layoutStudio.dialog.close")}
      wide
      footer={
        <button
          type="button"
          className="dq-btn"
          onClick={() => setExportModalOpen(false)}
        >
          {t("layoutStudio.dialog.stayBtn")}
        </button>
      }
    >
      {/* 1. Seamless Handoff to Figure Recoloring or Table Studio */}
      <div className="dq-layout-handoff-box">
        <div className="dq-layout-handoff-box__head">
          <strong>{t("layoutStudio.dialog.nextStageHeading")}</strong>
          <p>{t("layoutStudio.dialog.nextStageLead")}</p>
        </div>

        <div className="dq-layout-handoff-cards">
          <div className="dq-layout-handoff-card dq-layout-handoff-card--primary">
            <div className="dq-layout-handoff-card__title">
              <Palette size={15} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("layoutStudio.dialog.toFigureTitle")}</span>
            </div>
            <p>{t("layoutStudio.dialog.toFigureDesc")}</p>
            <button
              type="button"
              className="dq-btn dq-btn--primary"
              disabled={handoffBusy}
              onClick={() => void handleSendToFigureColor()}
            >
              <span>
                {handoffBusy
                  ? t("layoutStudio.topbar.sendingToColor")
                  : t("layoutStudio.dialog.toFigureBtn")}
              </span>
              <ArrowRight size={14} strokeWidth={1.6} aria-hidden="true" />
            </button>
          </div>

          <div className="dq-layout-handoff-card">
            <div className="dq-layout-handoff-card__title">
              <Table2 size={15} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("layoutStudio.dialog.toTableTitle")}</span>
            </div>
            <p>{t("layoutStudio.dialog.toTableDesc")}</p>
            <button
              type="button"
              className="dq-btn"
              onClick={handleOpenTableStudio}
            >
              <span>{t("layoutStudio.dialog.toTableBtn")}</span>
              <ArrowRight size={14} strokeWidth={1.6} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      {/* 2. Mode A Direct Exports */}
      <div className="dq-layout-export-group">
        <h4>{t("layoutStudio.dialog.exportHeading")}</h4>
        <div className="dq-layout-export-btns">
          <button
            type="button"
            className="dq-btn dq-btn--primary"
            onClick={() => void downloadExport("pdf")}
          >
            <Download size={14} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("layoutStudio.dialog.dlPdf")}</span>
          </button>
          <button
            type="button"
            className="dq-btn"
            onClick={() => void downloadExport("svg")}
          >
            <Download size={14} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("layoutStudio.dialog.dlSvg")}</span>
          </button>
          <button
            type="button"
            className="dq-btn"
            onClick={() => void downloadExport("png", 300)}
          >
            <Download size={14} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("layoutStudio.dialog.dlPng300")}</span>
          </button>
          <button
            type="button"
            className="dq-btn"
            onClick={() => void downloadExport("png", 600)}
          >
            <Download size={14} strokeWidth={1.6} aria-hidden="true" />
            <span>{t("layoutStudio.dialog.dlPng600")}</span>
          </button>
        </div>
      </div>

      {/* 3. Mode B Slot Lockfile & Code */}
      {composed ? (
        <div className="dq-layout-export-group">
          <div className="dq-layout-code-head">
            <div>
              <h4>{t("layoutStudio.dialog.modeBHeading")}</h4>
              <p>{t("layoutStudio.dialog.modeBLead")}</p>
            </div>
            <button
              type="button"
              className="dq-btn"
              onClick={() => void downloadExport("lockfile")}
            >
              <FileCode2 size={14} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("layoutStudio.dialog.dlLockfile")}</span>
            </button>
          </div>

          <div className="dq-layout-code-bar">
            <div className="dq-mode-switch">
              <button
                type="button"
                className="dq-mode-switch__btn"
                aria-pressed={codeTab === "r"}
                onClick={() => setCodeTab("r")}
              >
                <span>{t("layoutStudio.dialog.tabR")}</span>
              </button>
              <button
                type="button"
                className="dq-mode-switch__btn"
                aria-pressed={codeTab === "py"}
                onClick={() => setCodeTab("py")}
              >
                <span>{t("layoutStudio.dialog.tabPy")}</span>
              </button>
            </div>

            <button
              type="button"
              className="dq-btn"
              onClick={() => {
                void navigator.clipboard.writeText(snippet);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1600);
              }}
            >
              {copied ? (
                <Check size={13} strokeWidth={1.8} aria-hidden="true" />
              ) : (
                <Copy size={13} strokeWidth={1.6} aria-hidden="true" />
              )}
              <span>{copied ? t("layoutStudio.dialog.copied") : t("layoutStudio.dialog.copyCode")}</span>
            </button>
          </div>

          <pre className="dq-layout-code-pre">{snippet}</pre>
        </div>
      ) : null}
    </ModalDialog>
  );
}
