import React, { useId, useRef, useState } from "react";
import { ExternalLink, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";
import { BrandMark } from "./BrandMark";

export function LandingView(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const presets = useStudioStore((s) => s.presets);
  const uploadFile = useStudioStore((s) => s.uploadFile);
  const openPreset = useStudioStore((s) => s.openPreset);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputId = useId();
  const [dragActive, setDragActive] = useState(false);

  const langKey = i18n.language.startsWith("zh") ? "zh" : "en";

  const handleFiles = (files: FileList | null): void => {
    if (!files || files.length === 0) return;
    void uploadFile(files[0]);
  };

  return (
    <main id="main-canvas" className="dq-landing">
      <div className="dq-landing__inner">
        <div className="dq-landing__hero">
          <div className="dq-landing__seal-wrap">
            <BrandMark variant="seal" size={52} className="dq-landing__seal" />
          </div>
          <h1>{t("landing.headline")}</h1>
          <p>{t("landing.tagline")}</p>
        </div>

        <div
          className={`dq-dropzone${dragActive ? " dq-dropzone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setDragActive(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload size={24} strokeWidth={1.5} aria-hidden="true" />
          <div className="dq-dropzone__title">{t("landing.dropTitle")}</div>
          <div>
            <label htmlFor={fileInputId} className="visually-hidden">
              {t("landing.browseButton")}
            </label>
            <input
              ref={fileInputRef}
              id={fileInputId}
              type="file"
              accept=".pdf,.svg,image/*"
              className="visually-hidden"
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                handleFiles(e.target.files);
                e.currentTarget.value = "";
              }}
            />
            <button
              type="button"
              className="dq-btn dq-btn--primary"
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
            >
              {t("landing.browseButton")}
            </button>
          </div>
          <div className="dq-dropzone__meta">{t("landing.formats")}</div>
        </div>

        <p className="dq-privacy-note">{t("landing.privacy")}</p>

        {presets.length > 0 ? (
          <section className="dq-samples">
            <h2>{t("landing.samplesHeading")}</h2>
            <div className="dq-samples__grid">
              {presets.map((preset) => {
                const title = preset.title[langKey] || preset.title.en;
                const sub = preset.subtitle[langKey] || preset.subtitle.en;
                const cite = preset.citation ? preset.citation[langKey] || preset.citation.en : "";
                return (
                  <article key={preset.preset_id} className="dq-sample-card">
                    <button
                      type="button"
                      className="dq-sample-card__action"
                      onClick={() => void openPreset(preset.preset_id)}
                    >
                      <div className="dq-sample-card__thumb">
                        <img
                          src={preset.thumbnail_url}
                          alt={t("a11y.presetThumbAlt", { title })}
                        />
                      </div>
                      <div className="dq-sample-card__meta">
                        <span className="dq-sample-card__title">{title}</span>
                        <span className="dq-sample-card__sub">{sub}</span>
                      </div>
                    </button>
                    {cite ? (
                      <div className="dq-sample-card__cite">
                        {preset.source_url ? (
                          <a
                            href={preset.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="dq-sample-card__cite-link"
                          >
                            <span>{cite}</span>
                            <ExternalLink size={11} strokeWidth={1.6} aria-hidden="true" />
                          </a>
                        ) : (
                          <span>{cite}</span>
                        )}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
