import React, { useEffect, useId, useRef, useState } from "react";
import { ClipboardPaste, ExternalLink, FileSpreadsheet, Upload, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTableStudioStore } from "../../table/tableStore";
import { BrandMark } from "../BrandMark";

export function TableLandingView(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const samples = useTableStudioStore((s) => s.samples);
  const busy = useTableStudioStore((s) => s.busy);
  const errorKey = useTableStudioStore((s) => s.errorKey);
  const initTableCatalog = useTableStudioStore((s) => s.initTableCatalog);
  const openSample = useTableStudioStore((s) => s.openSample);
  const uploadTableFile = useTableStudioStore((s) => s.uploadTableFile);
  const setActiveModal = useTableStudioStore((s) => s.setActiveModal);
  const clearError = useTableStudioStore((s) => s.clearError);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputId = useId();
  const [dragOver, setDragOver] = useState(false);
  const isZh = i18n.language.startsWith("zh");

  useEffect(() => {
    void initTableCatalog();
  }, [initTableCatalog]);

  const handleFiles = (files: FileList | null): void => {
    if (!files || files.length === 0) return;
    void uploadTableFile(files[0]);
  };

  return (
    <main id="main-canvas" className="dq-landing">
      <div className="dq-landing__inner">
        <section className="dq-landing__hero">
          <div className="dq-landing__seal-wrap">
            <BrandMark variant="seal" size={52} className="dq-landing__seal" />
          </div>
          <h1>{t("tableStudio.landing.headline")}</h1>
          <p>{t("tableStudio.landing.tagline")}</p>
        </section>

        {errorKey ? (
          <div className="dq-table-error-banner" role="alert">
            <span>{t(errorKey)}</span>
            <button
              type="button"
              className="dq-btn dq-btn--ghost dq-btn--icon"
              aria-label={t("tableStudio.errors.dismiss")}
              title={t("tableStudio.errors.dismiss")}
              onClick={clearError}
            >
              <X size={14} strokeWidth={1.6} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        <div
          className={`dq-dropzone${dragOver ? " dq-dropzone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={(e) => {
            if ((e.target as HTMLElement).closest("button")) return;
            fileInputRef.current?.click();
          }}
        >
          <FileSpreadsheet size={28} strokeWidth={1.4} aria-hidden="true" />
          <div className="dq-dropzone__title">{t("tableStudio.landing.dropTitle")}</div>

          <label htmlFor={fileInputId} className="visually-hidden">
            {t("tableStudio.landing.browseButton")}
          </label>
          <input
            ref={fileInputRef}
            id={fileInputId}
            type="file"
            accept=".csv,.tsv,.txt,.xlsx"
            className="visually-hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.currentTarget.value = "";
            }}
          />

          <div className="dq-table-landing-actions">
            <button
              type="button"
              className="dq-btn dq-btn--primary"
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={14} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.landing.browseButton")}</span>
            </button>

            <button
              type="button"
              className="dq-btn"
              disabled={busy}
              onClick={() => setActiveModal("paste")}
            >
              <ClipboardPaste size={14} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.landing.pasteButton")}</span>
            </button>
          </div>

          <div className="dq-dropzone__meta">{t("tableStudio.landing.formats")}</div>
        </div>

        <p className="dq-privacy-note">{t("tableStudio.landing.privacy")}</p>

        <section className="dq-samples">
          <h2>{t("tableStudio.landing.samplesHeading")}</h2>
          <div className="dq-samples__grid dq-samples__grid--three">
            {samples.map((sample) => {
              const titleText = isZh ? sample.title_zh : sample.title_en;
              const needsText = isZh ? sample.needs_zh : sample.needs_en;
              const providerText = isZh ? sample.provider_zh : sample.provider_en;
              const previewRows = (sample.preview_grid ?? []).slice(0, 6);

              return (
                <div key={sample.id} className="dq-sample-card dq-table-sample-card">
                  <button
                    type="button"
                    className="dq-sample-card__action"
                    disabled={busy}
                    onClick={() => void openSample(sample.id)}
                  >
                    <div
                      className="dq-sample-card__thumb dq-table-sample-thumb"
                      aria-label={t("tableStudio.a11y.rawPreviewLabel", { title: titleText })}
                    >
                      <table className="dq-raw-preview-table" aria-hidden="true">
                        <tbody>
                          {previewRows.map((row, rIdx) => (
                            <tr key={rIdx}>
                              {Array.from({ length: 5 }, (_, cIdx) => (
                                <td key={cIdx}>{row[cIdx] ?? ""}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    <div className="dq-sample-card__meta">
                      <span className="dq-sample-card__title">{titleText}</span>
                      <span className="dq-sample-card__sub">
                        {t("tableStudio.landing.needsPrefix", { detail: needsText })}
                      </span>
                    </div>
                  </button>

                  <div className="dq-sample-card__cite">
                    <a
                      href={sample.source_page}
                      target="_blank"
                      rel="noreferrer"
                      className="dq-sample-card__cite-link"
                    >
                      <span>
                        {t("tableStudio.landing.sourceCredit", {
                          provider: providerText,
                          license: sample.license,
                        })}
                      </span>
                      <ExternalLink size={11} strokeWidth={1.6} aria-hidden="true" />
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
