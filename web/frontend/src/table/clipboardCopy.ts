let lastAnnouncedMessage = "";

export function formatLiveStatusMessage(msg: string): string {
  let out = msg;
  if (out === lastAnnouncedMessage) {
    out += "\u00A0";
  }
  lastAnnouncedMessage = out;
  return out;
}

export async function copyRichTableToClipboard(
  richHtml: string,
  plainTsv: string,
): Promise<boolean> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    typeof navigator.clipboard.write === "function" &&
    typeof ClipboardItem !== "undefined"
  ) {
    try {
      const item = new ClipboardItem({
        "text/html": new Blob([richHtml], { type: "text/html" }),
        "text/plain": new Blob([plainTsv], { type: "text/plain" }),
      });
      await navigator.clipboard.write([item]);
      return true;
    } catch {
      // Fall through to synchronous DOM selection copy
    }
  }

  if (typeof document === "undefined") return false;
  const host = document.createElement("div");
  host.setAttribute("contenteditable", "true");
  host.style.cssText =
    "position:fixed;inset-block-start:0;inset-inline-start:-9999px;opacity:0;pointer-events:none;background:#FFFFFF;color:#111827;";
  host.innerHTML = richHtml;
  document.body.appendChild(host);

  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(host);
  selection?.removeAllRanges();
  selection?.addRange(range);

  const onCopy = (ev: ClipboardEvent): void => {
    if (ev.clipboardData) {
      ev.clipboardData.setData("text/html", richHtml);
      ev.clipboardData.setData("text/plain", plainTsv);
      ev.preventDefault();
    }
  };
  document.addEventListener("copy", onCopy);
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.removeEventListener("copy", onCopy);
    selection?.removeAllRanges();
    host.remove();
  }
}

export async function copyTextToClipboard(text: string): Promise<boolean> {
  if (!text) return false;
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to legacy textarea fallback
    }
  }
  if (typeof document === "undefined") return false;
  const field = Object.assign(document.createElement("textarea"), { value: text });
  field.setAttribute("readonly", "");
  field.style.cssText = "position:fixed;inset-block-start:0;opacity:0;";
  document.body.append(field);
  field.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
  }
}
