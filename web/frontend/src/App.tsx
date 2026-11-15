import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ElementsPanel } from "./components/ElementsPanel";
import { ExportDialog } from "./components/ExportDialog";
import { FigureCanvas } from "./components/FigureCanvas";
import { LandingView } from "./components/LandingView";
import { ProcessingView } from "./components/ProcessingView";
import { RightSidebar } from "./components/RightSidebar";
import { TableCanvas } from "./components/table/TableCanvas";
import { TableDialogs } from "./components/table/TableDialogs";
import { TableLandingView } from "./components/table/TableLandingView";
import { TableStructurePanel } from "./components/table/TableStructurePanel";
import { TableStylePanel } from "./components/table/TableStylePanel";
import { TopBar } from "./components/TopBar";
import { UploadDialogs } from "./components/UploadDialogs";
import { useStudioStore } from "./store";
import { useTableStudioStore } from "./table/tableStore";

export function App(): React.ReactElement {
  const { t } = useTranslation();
  const studioMode = useStudioStore((s) => s.studioMode);
  const pageMode = useStudioStore((s) => s.pageMode);
  const tablePageMode = useTableStudioStore((s) => s.tablePageMode);
  const initCatalog = useStudioStore((s) => s.initCatalog);
  const uploadFile = useStudioStore((s) => s.uploadFile);
  const uploadSvgText = useStudioStore((s) => s.uploadSvgText);

  const [windowDragActive, setWindowDragActive] = useState(false);
  const dragDepthRef = useRef(0);

  useEffect(() => {
    void initCatalog();
  }, [initCatalog]);

  // Global drag-and-drop, clipboard SVG paste, keyboard shortcuts, and tab-close beacon cleanup
  useEffect(() => {
    const hasFiles = (dt: DataTransfer | null): boolean =>
      Boolean(dt && Array.from(dt.types).includes("Files"));

    const onDragEnter = (e: DragEvent): void => {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault();
      dragDepthRef.current += 1;
      setWindowDragActive(true);
    };

    const onDragOver = (e: DragEvent): void => {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault();
    };

    const onDragLeave = (e: DragEvent): void => {
      if (!hasFiles(e.dataTransfer)) return;
      dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
      if (dragDepthRef.current === 0) {
        setWindowDragActive(false);
      }
    };

    const onDrop = (e: DragEvent): void => {
      dragDepthRef.current = 0;
      setWindowDragActive(false);
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault();
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        void uploadFile(files[0]);
      }
    };

    const onPaste = (e: ClipboardEvent): void => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      const files = e.clipboardData?.files;
      if (files && files.length > 0) {
        e.preventDefault();
        void uploadFile(files[0]);
        return;
      }
      const html = e.clipboardData?.getData("text/html") || "";
      const txt = e.clipboardData?.getData("text/plain") || "";
      if (
        useStudioStore.getState().studioMode === "table" &&
        ((html && html.toLowerCase().includes("<table")) ||
          (txt.includes("\t") && txt.includes("\n")))
      ) {
        e.preventDefault();
        void useTableStudioStore.getState().submitPaste({ html, text: txt });
        return;
      }
      if (txt.includes("<svg") && txt.includes("</svg>")) {
        e.preventDefault();
        void uploadSvgText(txt);
      }
    };

    const onKeyDown = (e: KeyboardEvent): void => {
      const state = useStudioStore.getState();
      const target = e.target as HTMLElement | null;
      const inInput =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);
      if (inInput) return;

      if (e.key === "?") {
        e.preventDefault();
        state.openDialog("shortcuts");
        return;
      }

      if (state.studioMode === "table") {
        const tblState = useTableStudioStore.getState();
        if (e.key === "Escape") {
          if (tblState.isComparingRaw) {
            tblState.setComparingRaw(false);
          }
          return;
        }
        if (tblState.tablePageMode !== "editor" || tblState.activeModal !== null) return;
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
          e.preventDefault();
          if (e.shiftKey) {
            tblState.redo();
          } else {
            tblState.undo();
          }
          return;
        }
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "y") {
          e.preventDefault();
          tblState.redo();
          return;
        }
        if (e.key === "\\") {
          tblState.setComparingRaw(true);
        } else if (e.key.toLowerCase() === "e" && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          tblState.setActiveModal("export");
        }
        return;
      }

      if (state.pageMode !== "editor" || !state.figure) return;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          void state.redo();
        } else {
          void state.undo();
        }
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        void state.redo();
        return;
      }

      if (state.activeDialog !== null) return;

      if (e.key === "\\") {
        state.setComparingOriginal(true);
      } else if (e.key.toLowerCase() === "f" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("danqing:fit"));
      } else if ((e.key === "+" || e.key === "=") && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("danqing:zoom-in"));
      } else if ((e.key === "-" || e.key === "_") && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("danqing:zoom-out"));
      } else if (e.key === "Escape") {
        state.selectEntity(null);
      } else if (e.key === "1" && state.selectedIds.length > 0) {
        e.preventDefault();
        void state.setElementRoles(state.selectedIds, "focus");
      } else if (e.key === "2" && state.selectedIds.length > 0) {
        e.preventDefault();
        void state.setElementRoles(state.selectedIds, "normal");
      } else if (e.key === "3" && state.selectedIds.length > 0) {
        e.preventDefault();
        void state.setElementRoles(state.selectedIds, "background");
      } else if (e.key.toLowerCase() === "l" && state.selectedIds.length === 1) {
        e.preventDefault();
        const el = state.figure.elements.find((x) => x.entity_id === state.selectedIds[0]);
        if (el) {
          void state.toggleElementLock(el.entity_id, !el.locked);
        }
      } else if (e.key.toLowerCase() === "e" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        state.openDialog("export");
      }
    };

    const onKeyUp = (e: KeyboardEvent): void => {
      if (e.key === "\\") {
        useStudioStore.getState().setComparingOriginal(false);
        useTableStudioStore.getState().setComparingRaw(false);
      }
    };

    const onPageHide = (): void => {
      const { sessionFigures } = useStudioStore.getState();
      for (const sf of sessionFigures) {
        if (!sf.is_preset && typeof navigator.sendBeacon === "function") {
          navigator.sendBeacon(`/api/v2/figures/${sf.figure_id}/close`);
        }
      }
    };

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    window.addEventListener("paste", onPaste);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("pagehide", onPageHide);

    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("pagehide", onPageHide);
    };
  }, [uploadFile, uploadSvgText]);

  return (
    <>
      <div className="dq-desktop-guard">
        <h1>{t("app.desktopOnlyTitle")}</h1>
        <p>{t("app.desktopOnlyBody")}</p>
      </div>

      <div className="dq-app-shell">
        <a href="#main-canvas" className="skip-link visually-hidden">
          {t("a11y.skipToMain")}
        </a>

        {windowDragActive &&
        ((studioMode === "table" &&
          (tablePageMode === "editor" || tablePageMode === "landing")) ||
          (studioMode === "figure" && pageMode === "editor")) ? (
          <div className="dq-drop-overlay">
            <div className="dq-drop-overlay__box">
              {studioMode === "table"
                ? t("tableStudio.canvas.dropOverlay")
                : t("canvas.dropOverlay")}
            </div>
          </div>
        ) : null}

        <TopBar />

        {studioMode === "table" ? (
          <>
            {tablePageMode === "landing" ? (
              <TableLandingView />
            ) : (
              <div className="dq-table-editor">
                <TableStructurePanel />
                <TableCanvas />
                <TableStylePanel />
              </div>
            )}
            <TableDialogs />
          </>
        ) : (
          <>
            {pageMode === "landing" ? <LandingView /> : null}
            {pageMode === "processing" ? <ProcessingView /> : null}
            {pageMode === "editor" ? (
              <div className="dq-editor">
                <ElementsPanel />
                <FigureCanvas />
                <RightSidebar />
              </div>
            ) : null}
            <ExportDialog />
          </>
        )}

        <UploadDialogs />
      </div>
    </>
  );
}
