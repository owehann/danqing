import React, { useId } from "react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";

export function ProcessingView(): React.ReactElement {
  const { t } = useTranslation();
  const stage = useStudioStore((s) => s.processingStage);
  const progress = useStudioStore((s) => s.processingProgress);
  const filename = useStudioStore((s) => s.processingFilename);
  const slowWarning = useStudioStore((s) => s.slowWarning);
  const barId = useId();

  const stageLabel = t(`processing.stages.${stage}`, {
    defaultValue: t("processing.stages.reading_file"),
  });

  return (
    <main id="main-canvas" className="dq-processing">
      <div className="dq-processing__card">
        <h1>{t("processing.title")}</h1>
        {filename ? <div className="dq-processing__file">{filename}</div> : null}
        <label htmlFor={barId} className="dq-processing__stage">
          {stageLabel}
        </label>
        <progress id={barId} className="dq-processing__bar" max={100} value={progress} />
        {slowWarning ? <div className="dq-processing__slow">{t("processing.slowNotice")}</div> : null}
      </div>
    </main>
  );
}
