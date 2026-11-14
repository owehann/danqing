import React, { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";

interface ModalDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  closeLabel: string;
  wide?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function ModalDialog({
  open,
  onClose,
  title,
  closeLabel,
  wide = false,
  children,
  footer,
}: ModalDialogProps): React.ReactElement {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const handleClose = (): void => {
      dialog.returnValue = "";
      onClose();
    };
    dialog.addEventListener("close", handleClose);

    // Fallback for browsers without native <dialog closedby="any"> support
    let handleClickFallback: ((ev: MouseEvent) => void) | null = null;
    if (typeof HTMLDialogElement !== "undefined" && !("closedBy" in HTMLDialogElement.prototype)) {
      handleClickFallback = (event: MouseEvent): void => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (isDialogContent) return;
        dialog.close();
      };
      dialog.addEventListener("click", handleClickFallback);
    }

    return () => {
      dialog.removeEventListener("close", handleClose);
      if (handleClickFallback) {
        dialog.removeEventListener("click", handleClickFallback);
      }
    };
  }, [onClose]);

  const dialogAttrs = { closedby: "any" } as Record<string, unknown>;

  return (
    <dialog
      ref={dialogRef}
      className={`dq-dialog${wide ? " dq-dialog--wide" : ""}`}
      aria-labelledby={titleId}
      {...dialogAttrs}
    >
      <div className="dq-dialog__header">
        <h2 id={titleId} className="dq-dialog__title">
          {title}
        </h2>
        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={closeLabel}
          title={closeLabel}
          onClick={() => dialogRef.current?.close()}
        >
          <X size={16} strokeWidth={1.5} aria-hidden="true" />
        </button>
      </div>
      <div className="dq-dialog__body">{children}</div>
      {footer ? <div className="dq-dialog__footer">{footer}</div> : null}
    </dialog>
  );
}

/**
 * Progressive-enhancement tethering fallback when CSS Anchor Positioning (`position-area`)
 * is unavailable: keeps a native `[popover="auto"]` panel visually anchored to its trigger.
 */
export function tetherPopoverFallback(
  popoverEl: HTMLElement | null,
  triggerEl: HTMLElement | null,
  alignEnd = false,
): void {
  if (!popoverEl || !triggerEl) return;
  if (typeof CSS !== "undefined" && CSS.supports("position-area", "block-end")) return;

  const tRect = triggerEl.getBoundingClientRect();
  const pRect = popoverEl.getBoundingClientRect();
  const margin = 6;
  const fitsBelow = tRect.bottom + margin + pRect.height <= window.innerHeight - 8;
  const top = fitsBelow
    ? tRect.bottom + margin
    : Math.max(8, tRect.top - margin - pRect.height);
  const rawLeft = alignEnd ? tRect.right - pRect.width : tRect.left;
  const left = Math.max(8, Math.min(rawLeft, window.innerWidth - pRect.width - 8));

  popoverEl.style.top = `${Math.round(top)}px`;
  popoverEl.style.left = `${Math.round(left)}px`;
}
