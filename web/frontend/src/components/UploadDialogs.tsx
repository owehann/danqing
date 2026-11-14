import React from "react";
import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";
import { ModalDialog } from "./ModalDialog";

const R_EXPORT_CODE = 'ggsave("fig.pdf", device = cairo_pdf)\nggsave("fig.svg")';
const PY_EXPORT_CODE = 'plt.savefig("fig.pdf")\nplt.savefig("fig.svg")';

const SHORTCUT_ROWS: Array<{ keys: string; labelKey: string }> = [
  { keys: "Cmd/Ctrl + Z", labelKey: "dialogs.scUndo" },
  { keys: "Shift + Cmd/Ctrl + Z", labelKey: "dialogs.scRedo" },
  { keys: "\\", labelKey: "dialogs.scCompare" },
  { keys: "F", labelKey: "dialogs.scFit" },
  { keys: "+ / −", labelKey: "dialogs.scZoom" },
  { keys: "Esc", labelKey: "dialogs.scClear" },
  { keys: "1 / 2 / 3", labelKey: "dialogs.scRoles" },
  { keys: "L", labelKey: "dialogs.scLock" },
  { keys: "E", labelKey: "dialogs.scExport" },
];

export function UploadDialogs(): React.ReactElement {
  const { t } = useTranslation();
  const activeDialog = useStudioStore((s) => s.activeDialog);
  const closeDialog = useStudioStore((s) => s.closeDialog);
  const multipagePayload = useStudioStore((s) => s.multipagePayload);
  const selectMultipagePage = useStudioStore((s) => s.selectMultipagePage);
  const errorPayload = useStudioStore((s) => s.errorPayload);

  const code = errorPayload?.code || "PARSE_FAILED";
  const isScanned = code === "SCANNED_PDF_NO_VECTORS";
  const errorTitle = isScanned ? t("dialogs.scannedTitle") : t("dialogs.errorTitle");
  const errorBody = isScanned
    ? t("dialogs.scannedBody")
    : code === "EMPTY_FILE"
      ? t("dialogs.emptyFileBody")
      : code === "UNSUPPORTED_FORMAT"
        ? t("dialogs.unsupportedBody")
        : errorPayload?.detail || t("dialogs.unsupportedBody");

  const issueUrl = `https://github.com/owehann/danqing/issues/new?title=${encodeURIComponent(
    `[Figure Parse] ${code}`,
  )}`;

  return (
    <>
      {/* 1. Raster rejection tutorial modal */}
      <ModalDialog
        open={activeDialog === "raster"}
        onClose={closeDialog}
        title={t("dialogs.rasterTitle")}
        closeLabel={t("export.close")}
        footer={
          <button type="button" className="dq-btn dq-btn--primary" onClick={closeDialog}>
            {t("export.close")}
          </button>
        }
      >
        <p style={{ margin: 0, color: "var(--text-2)" }}>{t("dialogs.rasterLead")}</p>
        <div>
          <div style={{ fontWeight: 600, fontSize: 12.5 }}>{t("dialogs.rasterR")}</div>
          <pre className="dq-code-snippet">{R_EXPORT_CODE}</pre>
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 12.5 }}>{t("dialogs.rasterPython")}</div>
          <pre className="dq-code-snippet">{PY_EXPORT_CODE}</pre>
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 12.5 }}>{t("dialogs.rasterPrism")}</div>
          <div style={{ color: "var(--text-2)", fontSize: 12.5 }}>
            {t("dialogs.rasterPrismStep")}
          </div>
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 12.5 }}>{t("dialogs.rasterIllustrator")}</div>
          <div style={{ color: "var(--text-2)", fontSize: 12.5 }}>
            {t("dialogs.rasterIllustratorStep")}
          </div>
        </div>
      </ModalDialog>

      {/* 2. Multi-page PDF page picker modal */}
      <ModalDialog
        open={activeDialog === "multipage" && Boolean(multipagePayload)}
        onClose={closeDialog}
        title={t("dialogs.multipageTitle", { count: multipagePayload?.page_count ?? 2 })}
        closeLabel={t("export.close")}
        wide
      >
        <div className="dq-page-grid">
          {(multipagePayload?.pages || []).map((pg) => {
            const pageNum = pg.index + 1;
            return (
              <button
                key={pg.index}
                type="button"
                className="dq-page-card"
                onClick={() => void selectMultipagePage(pg.index)}
              >
                <img
                  src={pg.thumbnail}
                  alt={t("a11y.pageThumbAlt", { num: pageNum })}
                />
                <span style={{ fontWeight: 600, fontSize: 12.5 }}>
                  {t("dialogs.pageLabel", { num: pageNum })}
                </span>
              </button>
            );
          })}
        </div>
      </ModalDialog>

      {/* 3. Scanned / Empty / Parse error modal */}
      <ModalDialog
        open={activeDialog === "error" && Boolean(errorPayload)}
        onClose={closeDialog}
        title={errorTitle}
        closeLabel={t("export.close")}
        footer={
          <>
            {!isScanned ? (
              <a
                href={issueUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="dq-btn"
                style={{ textDecoration: "none" }}
              >
                <span>{t("dialogs.reportIssue")}</span>
                <ExternalLink size={13} strokeWidth={1.5} aria-hidden="true" />
              </a>
            ) : null}
            <button type="button" className="dq-btn dq-btn--primary" onClick={closeDialog}>
              {t("export.close")}
            </button>
          </>
        }
      >
        <p style={{ margin: 0, color: "var(--text-2)" }}>{errorBody}</p>
      </ModalDialog>

      {/* 4. Keyboard shortcuts dialog */}
      <ModalDialog
        open={activeDialog === "shortcuts"}
        onClose={closeDialog}
        title={t("dialogs.shortcutsTitle")}
        closeLabel={t("export.close")}
      >
        <table className="dq-shortcuts-table">
          <caption className="visually-hidden">{t("dialogs.shortcutsTitle")}</caption>
          <tbody>
            {SHORTCUT_ROWS.map((row) => (
              <tr key={row.keys}>
                <th scope="row" style={{ width: "44%" }}>
                  <kbd className="dq-kbd">{row.keys}</kbd>
                </th>
                <td>{t(row.labelKey)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ModalDialog>
    </>
  );
}
