import React, { useEffect, useId, useRef, useState } from "react";
import { LayoutGrid, SlidersHorizontal, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLayoutStudioStore } from "../../layout/layoutStore";
import { BrandMark } from "../BrandMark";

export function LayoutLandingView(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const packs = useLayoutStudioStore((s) => s.packs);
  const busy = useLayoutStudioStore((s) => s.busy);
  const initLayoutCatalog = useLayoutStudioStore((s) => s.initLayoutCatalog);
  const openSamplePack = useLayoutStudioStore((s) => s.openSamplePack);
  const openSandbox = useLayoutStudioStore((s) => s.openSandbox);
  const uploadLayoutFiles = useLayoutStudioStore((s) => s.uploadLayoutFiles);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputId = useId();
  const [dragOver, setDragOver] = useState(false);
  const isZh = i18n.language.startsWith("zh");

  useEffect(() => {
    void initLayoutCatalog();
  }, [initLayoutCatalog]);

  const handleFiles = (files: FileList | null): void => {
    if (!files || files.length === 0) return;
    void uploadLayoutFiles(files);
  };

  return (
    <main id="main-canvas" className="dq-landing">
      <div className="dq-landing__inner">
        <section className="dq-landing__hero">
          <div className="dq-landing__seal-wrap">
            <BrandMark variant="seal" size={52} className="dq-landing__seal" />
          </div>
          <h1>{t("layoutStudio.landing.headline")}</h1>
          <p>{t("layoutStudio.landing.tagline")}</p>
        </section>

        <div
          className={`dq-dropzone${dragOver ? " dq-dropzone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={(e) => {
            if ((e.target as HTMLElement).closest("button")) return;
            fileInputRef.current?.click();
          }}
        >
          <LayoutGrid size={26} strokeWidth={1.45} aria-hidden="true" />
          <div className="dq-dropzone__title">{t("layoutStudio.landing.dropTitle")}</div>

          <label htmlFor={fileInputId} className="visually-hidden">
            {t("layoutStudio.landing.browseButton")}
          </label>
          <input
            ref={fileInputRef}
            id={fileInputId}
            type="file"
            multiple
            accept=".pdf,.svg,.png,.jpg,.jpeg,.tif,.tiff,.webp"
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
              <span>{t("layoutStudio.landing.browseButton")}</span>
            </button>

            <button
              type="button"
              className="dq-btn"
              disabled={busy}
              onClick={() => void openSandbox(10)}
            >
              <SlidersHorizontal size={14} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("layoutStudio.landing.sandboxButton")}</span>
            </button>
          </div>

          <div className="dq-dropzone__meta">{t("layoutStudio.landing.formats")}</div>
        </div>

        <p className="dq-privacy-note">{t("layoutStudio.landing.privacy")}</p>

        {packs.length > 0 ? (
          <section className="dq-samples">
            <h2>{t("layoutStudio.landing.samplesHeading")}</h2>
            <div className="dq-samples__grid dq-samples__grid--three">
              {packs.map((pack) => {
                const title = isZh ? pack.title_zh : pack.title_en;
                const sub = isZh ? pack.sub_zh : pack.sub_en;
                const cite = isZh ? pack.cite_zh : pack.cite_en;
                return (
                  <article key={pack.pack_id} className="dq-sample-card">
                    <button
                      type="button"
                      className="dq-sample-card__action"
                      disabled={busy}
                      onClick={() => void openSamplePack(pack.pack_id)}
                    >
                      <div
                        className="dq-sample-card__thumb dq-layout-sample-thumb"
                        aria-label={t("layoutStudio.a11y.packThumbAlt", { title })}
                        dangerouslySetInnerHTML={{ __html: pack.preview_svg }}
                      />
                      <div className="dq-sample-card__meta">
                        <div className="dq-sample-card__title-row">
                          <span className="dq-sample-card__title">{title}</span>
                          <span className="dq-sample-workflow-badge dq-sample-workflow-badge--tidy">
                            {t("layoutStudio.landing.panelCountBadge", { count: pack.panel_count })}
                          </span>
                        </div>
                        <span className="dq-sample-card__sub">{sub}</span>
                      </div>
                    </button>
                    <div className="dq-sample-card__cite">
                      <span>{cite}</span>
                    </div>
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
