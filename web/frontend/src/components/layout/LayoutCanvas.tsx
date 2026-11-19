import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRightToLine,
  ArrowUpToLine,
  Bold,
  Columns2,
  CornerDownLeft,
  CornerDownRight,
  CornerUpLeft,
  CornerUpRight,
  Eye,
  EyeOff,
  GripVertical,
  Italic,
  Minus,
  Move,
  Palette,
  Plus,
  RotateCcw,
  Square,
  Type,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  type CanvasDropTarget,
  DEFAULT_PANEL_OVERRIDE,
  DEFAULT_TEXT_ITEM_OVERRIDE,
  type LayoutROIConfig,
  type LayoutSlotMeta,
  type LayoutTextItemMeta,
  type LegendPosMode,
  useLayoutStudioStore,
} from "../../layout/layoutStore";

interface ColSplitterItem {
  rowIdx: number;
  leftBlockIdx: number;
  xMm: number;
  y0Mm: number;
  y1Mm: number;
  leftWeight: number;
  rightWeight: number;
  rowWidthMm: number;
}

type LegendMagZone =
  | "right"
  | "top"
  | "bottom"
  | "inside_tl"
  | "inside_tr"
  | "inside_bl"
  | "inside_br"
  | "custom";

const SINGLE_TEXT_SWATCHES = [
  { id: "black", hex: "#000000" },
  { id: "crimson", hex: "#B91C1C" },
  { id: "cobalt", hex: "#1D4ED8" },
  { id: "teal", hex: "#0F766E" },
  { id: "muted", hex: "#64748B" },
] as const;

export function LayoutCanvas(): React.ReactElement {
  const { t } = useTranslation();
  const composed = useLayoutStudioStore((s) => s.composed);
  const focusedPanelId = useLayoutStudioStore((s) => s.focusedPanelId);
  const focusedTextKey = useLayoutStudioStore((s) => s.focusedTextKey);
  const roiOverrides = useLayoutStudioStore((s) => s.roiOverrides);
  const panelOverrides = useLayoutStudioStore((s) => s.panelOverrides);
  const isComparingNaive = useLayoutStudioStore((s) => s.isComparingNaive);
  const zoomPct = useLayoutStudioStore((s) => s.zoomPct);
  const liveAnnouncement = useLayoutStudioStore((s) => s.liveAnnouncement);

  const setFocusedPanelId = useLayoutStudioStore((s) => s.setFocusedPanelId);
  const setFocusedText = useLayoutStudioStore((s) => s.setFocusedText);
  const movePanelOrder = useLayoutStudioStore((s) => s.movePanelOrder);
  const movePanelOnGrid = useLayoutStudioStore((s) => s.movePanelOnGrid);
  const updateRoi = useLayoutStudioStore((s) => s.updateRoi);
  const updatePanelOverride = useLayoutStudioStore((s) => s.updatePanelOverride);
  const updateTextItemOverride = useLayoutStudioStore((s) => s.updateTextItemOverride);
  const resetTextItemOverride = useLayoutStudioStore((s) => s.resetTextItemOverride);
  const resizeColumnBlocks = useLayoutStudioStore((s) => s.resizeColumnBlocks);
  const resizeRowHeight = useLayoutStudioStore((s) => s.resizeRowHeight);
  const setZoomPct = useLayoutStudioStore((s) => s.setZoomPct);
  const setLiveAnnouncement = useLayoutStudioStore((s) => s.setLiveAnnouncement);

  const paperRef = useRef<HTMLDivElement | null>(null);
  const panelGhostRef = useRef<HTMLDivElement | null>(null);
  const legToolbarRef = useRef<HTMLDivElement | null>(null);
  const txtToolbarRef = useRef<HTMLDivElement | null>(null);
  const txtColorInputRef = useRef<HTMLInputElement | null>(null);

  const [draggingPanelId, setDraggingPanelId] = useState<string | null>(null);
  const [draggingPanelTag, setDraggingPanelTag] = useState<string>("");
  const [activeDrop, setActiveDrop] = useState<CanvasDropTarget | null>(null);

  // Legend 120 FPS GPU drag state (only changes on drag start/end or magnetic zone crossing)
  const [legDragSlotId, setLegDragSlotId] = useState<string | null>(null);
  const [legMagZone, setLegMagZone] = useState<LegendMagZone | null>(null);

  // Live splitter preview guides (zero network calls during pointermove!)
  const [colGuide, setColGuide] = useState<{
    xPct: number;
    y0Pct: number;
    hPct: number;
    leftPct: number;
    rightPct: number;
  } | null>(null);
  const [rowGuide, setRowGuide] = useState<{
    yPct: number;
    heightMm: number;
  } | null>(null);

  const announcePolite = (msg: string): void => {
    setLiveAnnouncement("");
    window.setTimeout(() => setLiveAnnouncement(msg), 60);
  };

  // Clear any residual inline GPU transforms on legend handles once a fresh composed SVG lands
  useLayoutEffect(() => {
    const paperEl = paperRef.current;
    if (!paperEl) return;
    paperEl.querySelectorAll<HTMLElement>(".dq-layout-legend-box").forEach((el) => {
      el.style.transform = "";
    });
  }, [composed]);

  // Roving tabindex fallback for floating toolbars when native `focusgroup` is absent
  useEffect(() => {
    const bar = focusedTextKey ? txtToolbarRef.current : legToolbarRef.current;
    if (!bar || "focusGroup" in HTMLElement.prototype) return;
    const items = Array.from(bar.querySelectorAll<HTMLButtonElement>("button"));
    if (!items.length) return;
    const hasZero = items.some((b) => b.tabIndex === 0);
    if (!hasZero) {
      items.forEach((b, i) => {
        b.tabIndex = i === 0 ? 0 : -1;
      });
    }
    const onFocusIn = (ev: FocusEvent): void => {
      const tgt = ev.target as HTMLButtonElement | null;
      if (tgt && items.includes(tgt)) {
        items.forEach((b) => {
          b.tabIndex = b === tgt ? 0 : -1;
        });
      }
    };
    bar.addEventListener("focusin", onFocusIn);
    return () => bar.removeEventListener("focusin", onFocusIn);
  }, [focusedPanelId, focusedTextKey, composed, legDragSlotId]);

  const hitTestTextItem = (
    slot: LayoutSlotMeta,
    xMm: number,
    yMm: number,
    onlyLegend: boolean,
  ): LayoutTextItemMeta | null => {
    const list = slot.text_items || [];
    const pad = 0.85;
    let best: LayoutTextItemMeta | null = null;
    let bestDist = 1e9;
    for (const ti of list) {
      const isLegItem = ti.item_key.startsWith("LEG:") || ti.item_key.startsWith("CB_");
      if (onlyLegend && !isLegItem) continue;
      if (!onlyLegend && isLegItem) continue;
      const [bx0, by0, bx1, by1] = ti.bbox_mm;
      if (xMm >= bx0 - pad && xMm <= bx1 + pad && yMm >= by0 - pad && yMm <= by1 + pad) {
        const d = Math.hypot(xMm - 0.5 * (bx0 + bx1), yMm - 0.5 * (by0 + by1));
        if (d < bestDist) {
          bestDist = d;
          best = ti;
        }
      }
    }
    return best;
  };

  const handleToolbarKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if ("focusGroup" in HTMLElement.prototype) return;
    const bar = e.currentTarget;
    const items = Array.from(bar.querySelectorAll<HTMLButtonElement>("button"));
    if (!items.length) return;
    const curIdx = Math.max(0, items.indexOf(document.activeElement as HTMLButtonElement));
    const rtl = getComputedStyle(bar).direction === "rtl";
    let nextIdx = -1;
    if (e.key === "ArrowRight") {
      nextIdx = (curIdx + (rtl ? -1 : 1) + items.length) % items.length;
    } else if (e.key === "ArrowLeft") {
      nextIdx = (curIdx + (rtl ? 1 : -1) + items.length) % items.length;
    } else if (e.key === "Home") {
      nextIdx = 0;
    } else if (e.key === "End") {
      nextIdx = items.length - 1;
    }
    if (nextIdx >= 0) {
      e.preventDefault();
      items.forEach((b, i) => {
        b.tabIndex = i === nextIdx ? 0 : -1;
      });
      items[nextIdx].focus();
    }
  };

  // Compute column splitters from composed slots & bento_rows
  const colSplitters = useMemo<ColSplitterItem[]>(() => {
    if (!composed) return [];
    const out: ColSplitterItem[] = [];
    composed.bento_rows.forEach((row, rIdx) => {
      if (row.blocks.length < 2) return;
      const rowSlots = composed.slots.filter((s) => s.row_idx === rIdx);
      if (rowSlots.length === 0) return;
      const rowX0 = Math.min(...rowSlots.map((s) => s.outer_box_mm[0]));
      const rowX1 = Math.max(...rowSlots.map((s) => s.outer_box_mm[2]));
      const rowY0 = Math.min(...rowSlots.map((s) => s.outer_box_mm[1]));
      const rowY1 = Math.max(...rowSlots.map((s) => s.outer_box_mm[3]));

      const totalW = row.blocks.reduce((a, b) => a + b.weight, 0) || 12;
      for (let bIdx = 0; bIdx < row.blocks.length - 1; bIdx++) {
        const leftSlots = rowSlots.filter((s) => s.block_idx === bIdx);
        const rightSlots = rowSlots.filter((s) => s.block_idx === bIdx + 1);
        if (!leftSlots.length || !rightSlots.length) continue;
        const leftEdge = Math.max(...leftSlots.map((s) => s.outer_box_mm[2]));
        const rightEdge = Math.min(...rightSlots.map((s) => s.outer_box_mm[0]));
        out.push({
          rowIdx: rIdx,
          leftBlockIdx: bIdx,
          xMm: 0.5 * (leftEdge + rightEdge),
          y0Mm: rowY0,
          y1Mm: rowY1,
          leftWeight: (row.blocks[bIdx].weight / totalW) * 12.0,
          rightWeight: (row.blocks[bIdx + 1].weight / totalW) * 12.0,
          rowWidthMm: Math.max(20, rowX1 - rowX0),
        });
      }
    });
    return out;
  }, [composed]);

  const hitTestDropTarget = (xMm: number, yMm: number, srcPanelId: string): CanvasDropTarget | null => {
    if (!composed) return null;
    const bounds = composed.row_bounds_mm;
    for (let rIdx = 0; rIdx <= bounds.length; rIdx++) {
      if (rIdx === 0 && bounds.length > 0 && yMm < bounds[0][0] + 2.5) {
        return { kind: "new_row", insertRowIdx: 0 };
      }
      if (rIdx === bounds.length && bounds.length > 0 && yMm > bounds[bounds.length - 1][1] - 2.5) {
        return { kind: "new_row", insertRowIdx: bounds.length };
      }
      if (rIdx > 0 && rIdx < bounds.length) {
        const prevY1 = bounds[rIdx - 1][1];
        const nextY0 = bounds[rIdx][0];
        if (yMm >= prevY1 - 2.2 && yMm <= nextY0 + 2.2) {
          return { kind: "new_row", insertRowIdx: rIdx };
        }
      }
    }

    for (const sl of composed.slots) {
      if (sl.panel_id === srcPanelId) continue;
      const [ox0, oy0, ox1, oy1] = sl.outer_box_mm;
      if (xMm < ox0 || xMm > ox1 || yMm < oy0 || yMm > oy1) continue;
      const rx = (xMm - ox0) / Math.max(1e-3, ox1 - ox0);
      const ry = (yMm - oy0) / Math.max(1e-3, oy1 - oy0);
      if (rx < 0.22) return { kind: "slot", dstPanelId: sl.panel_id, zone: "left" };
      if (rx > 0.78) return { kind: "slot", dstPanelId: sl.panel_id, zone: "right" };
      if (ry < 0.23) return { kind: "slot", dstPanelId: sl.panel_id, zone: "stack_top" };
      if (ry > 0.77) return { kind: "slot", dstPanelId: sl.panel_id, zone: "stack_bottom" };
      return { kind: "slot", dstPanelId: sl.panel_id, zone: "swap" };
    }
    return null;
  };

  // ---------------- 1. Panel Reorder / Stack Drag (120 FPS Ghost Pill + Drop Marker) ----------------
  const startPanelDrag = (e: React.PointerEvent<HTMLButtonElement>, slot: LayoutSlotMeta): void => {
    if (e.button !== 0 || !composed) return;
    e.stopPropagation();
    e.preventDefault();
    const paperEl = paperRef.current;
    if (!paperEl) return;

    const activePid = e.pointerId;
    const startX = e.clientX;
    const startY = e.clientY;
    let started = false;
    let latestTarget: CanvasDropTarget | null = null;
    const tagStr = (slot.tag_label || slot.panel_id).toUpperCase();

    setFocusedPanelId(slot.panel_id, true);

    const cleanup = (): void => {
      document.documentElement.classList.remove("dq-is-dragging");
      setDraggingPanelId(null);
      setActiveDrop(null);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKeyDown);
    };

    const onMove = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      if (!started && Math.hypot(ev.clientX - startX, ev.clientY - startY) < 4) return;
      if (!started) {
        started = true;
        document.documentElement.classList.add("dq-is-dragging");
        setDraggingPanelTag(tagStr);
        setDraggingPanelId(slot.panel_id);
      }
      if (panelGhostRef.current) {
        panelGhostRef.current.style.transform = `translate3d(${ev.clientX + 12}px, ${ev.clientY + 12}px, 0)`;
      }
      const rect = paperEl.getBoundingClientRect();
      const xMm = ((ev.clientX - rect.left) / Math.max(1, rect.width)) * composed.page_width_mm;
      const yMm = ((ev.clientY - rect.top) / Math.max(1, rect.height)) * composed.page_height_mm;
      latestTarget = hitTestDropTarget(xMm, yMm, slot.panel_id);
      setActiveDrop(latestTarget);
    };

    const onUp = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      const drop = latestTarget;
      cleanup();
      if (started && drop) {
        movePanelOnGrid(slot.panel_id, drop);
        announcePolite(t("layoutStudio.canvas.liveMovedPanel", { tag: tagStr }));
      }
    };

    const onCancel = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      cleanup();
    };

    const onKeyDown = (ev: KeyboardEvent): void => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        cleanup();
        announcePolite(t("layoutStudio.canvas.liveCanceledDrag"));
      }
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKeyDown);
  };

  // ---------------- 2. Legend / Colorbar 120 FPS GPU Drag + Magnetic Inner/Outer Dock Zones ----------------
  const commitLegendNorm = (slot: LayoutSlotMeta, nx: number, ny: number): void => {
    const clampedX = Math.max(-0.08, Math.min(0.96, Number(nx.toFixed(3))));
    const clampedY = Math.max(-0.08, Math.min(0.94, Number(ny.toFixed(3))));
    updatePanelOverride(
      slot.panel_id,
      {
        legend_pos: "custom",
        legend_xy_norm: [clampedX, clampedY],
      },
      true,
    );
  };

  const resolveLegendZone = (
    slot: LayoutSlotMeta,
    candX0: number,
    candY0: number,
    candX1: number,
    candY1: number,
    ptrXMm: number,
    ptrYMm: number,
    altKey: boolean,
  ): LegendMagZone => {
    const [sx0, sy0, sx1, sy1] = slot.spine_box_mm;
    // 1. Crossing above top plot frame -> Dock outside at Top (horizontal)!
    if ((ptrYMm < sy0 + 1.0 || candY0 < sy0 - 1.2) && ptrXMm <= sx1 + 16.0) {
      return "top";
    }
    // 2. Crossing below bottom plot frame -> Dock outside at Bottom (horizontal)!
    if ((ptrYMm > sy1 + 1.4 || candY1 > sy1 + 2.4) && ptrXMm <= sx1 + 16.0) {
      return "bottom";
    }
    // 3. Crossing past right plot frame -> Dock outside at Right (carves dedicated outer margin)!
    if (ptrXMm > sx1 - 1.5 || candX1 > sx1 + 1.4) {
      return "right";
    }
    // 3. Soft inner-corner magnetic snap (hold Alt/Option to bypass for 100% free placement)
    if (!altKey) {
      const snapTol = 3.8;
      if (Math.abs(candX0 - (sx0 + 0.5)) <= snapTol && Math.abs(candY0 - (sy0 + 0.6)) <= snapTol) {
        return "inside_tl";
      }
      if (Math.abs(candX1 - (sx1 - 0.5)) <= snapTol && Math.abs(candY0 - (sy0 + 0.6)) <= snapTol) {
        return "inside_tr";
      }
      if (Math.abs(candX0 - (sx0 + 0.5)) <= snapTol && Math.abs(candY1 - (sy1 - 0.5)) <= snapTol) {
        return "inside_bl";
      }
      if (Math.abs(candX1 - (sx1 - 0.5)) <= snapTol && Math.abs(candY1 - (sy1 - 0.5)) <= snapTol) {
        return "inside_br";
      }
    }
    return "custom";
  };

  const startLegendDrag = (e: React.PointerEvent<HTMLButtonElement>, slot: LayoutSlotMeta): void => {
    if (e.button !== 0 || !composed || !slot.legend_box_mm) return;
    e.stopPropagation();
    e.preventDefault();
    setFocusedPanelId(slot.panel_id, true);
    const paperEl = paperRef.current;
    if (!paperEl) return;

    const activePid = e.pointerId;
    const handleEl = e.currentTarget;
    const svgRoot = paperEl.querySelector("svg");
    const svgLegGroup = paperEl.querySelector<SVGGElement>(`#legend-layer-${slot.panel_id}`);

    const startClientX = e.clientX;
    const startClientY = e.clientY;
    const [origLx0, origLy0, origLx1, origLy1] = slot.legend_box_mm;
    const boxW = origLx1 - origLx0;
    const boxH = origLy1 - origLy0;

    let started = false;
    let currentZone: LegendMagZone = "custom";
    let finalCandX0 = origLx0;
    let finalCandY0 = origLy0;

    const cleanupVisuals = (revertSvg: boolean): void => {
      document.documentElement.classList.remove("dq-is-dragging");
      setLegDragSlotId(null);
      setLegMagZone(null);
      if (revertSvg) {
        handleEl.style.transform = "";
        svgLegGroup?.removeAttribute("transform");
      }
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKeyDown);
    };

    const onMove = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      const dxPx = ev.clientX - startClientX;
      const dyPx = ev.clientY - startClientY;
      if (!started && Math.hypot(dxPx, dyPx) < 3.5) return;
      if (!started) {
        started = true;
        document.documentElement.classList.add("dq-is-dragging");
        setLegDragSlotId(slot.panel_id);
      }

      // 120 FPS zero-reflow GPU transform on both the handle AND the live SVG <g id="legend-layer-...">
      handleEl.style.transform = `translate3d(${dxPx}px, ${dyPx}px, 0)`;
      const paperRect = paperEl.getBoundingClientRect();
      if (svgLegGroup && svgRoot) {
        const vbW = svgRoot.viewBox.baseVal.width || (composed.page_width_mm * 96) / 25.4;
        const vbH = svgRoot.viewBox.baseVal.height || (composed.page_height_mm * 96) / 25.4;
        const dxSvg = dxPx * (vbW / Math.max(1, paperRect.width));
        const dySvg = dyPx * (vbH / Math.max(1, paperRect.height));
        svgLegGroup.setAttribute("transform", `translate(${dxSvg.toFixed(2)}, ${dySvg.toFixed(2)})`);
      }

      const pxPerMmX = paperRect.width / composed.page_width_mm;
      const pxPerMmY = paperRect.height / composed.page_height_mm;
      const dxMm = dxPx / Math.max(0.1, pxPerMmX);
      const dyMm = dyPx / Math.max(0.1, pxPerMmY);
      const ptrXMm = (ev.clientX - paperRect.left) / Math.max(0.1, pxPerMmX);
      const ptrYMm = (ev.clientY - paperRect.top) / Math.max(0.1, pxPerMmY);

      finalCandX0 = origLx0 + dxMm;
      finalCandY0 = origLy0 + dyMm;
      const nextZone = resolveLegendZone(
        slot,
        finalCandX0,
        finalCandY0,
        finalCandX0 + boxW,
        finalCandY0 + boxH,
        ptrXMm,
        ptrYMm,
        ev.altKey,
      );
      if (nextZone !== currentZone) {
        currentZone = nextZone;
        setLegMagZone(nextZone);
      } else if (legMagZone === null) {
        setLegMagZone(nextZone);
      }
    };

    const onUp = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      if (!started) {
        cleanupVisuals(true);
        const paperRect = paperEl.getBoundingClientRect();
        const clickXMm = ((ev.clientX - paperRect.left) / Math.max(1, paperRect.width)) * composed.page_width_mm;
        const clickYMm = ((ev.clientY - paperRect.top) / Math.max(1, paperRect.height)) * composed.page_height_mm;
        const hitLegTxt = hitTestTextItem(slot, clickXMm, clickYMm, true);
        if (hitLegTxt) {
          setFocusedText(slot.panel_id, hitLegTxt.item_key, true);
        } else {
          setFocusedText(slot.panel_id, null, true);
        }
        return;
      }
      // Keep SVG group translated in place for the ~8ms until the new SVG arrives (zero snap-back flash!)
      cleanupVisuals(false);
      const [sx0, sy0, sx1, sy1] = slot.spine_box_mm;
      if (currentZone !== "custom") {
        const nextPatch =
          currentZone === "top" || currentZone === "bottom" || currentZone === "right"
            ? { legend_pos: currentZone, legend_orient: "auto" as const }
            : { legend_pos: currentZone };
        updatePanelOverride(slot.panel_id, nextPatch, true);
      } else {
        const nx = (finalCandX0 + 0.6 - sx0) / Math.max(5.0, sx1 - sx0);
        const ny = (finalCandY0 + 0.5 - sy0) / Math.max(5.0, sy1 - sy0);
        commitLegendNorm(slot, nx, ny);
      }
      announcePolite(
        t("layoutStudio.canvas.liveMovedLegend", {
          tag: (slot.tag_label || slot.panel_id).toUpperCase(),
        }),
      );
    };

    const onCancel = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      cleanupVisuals(true);
    };

    const onKeyDown = (ev: KeyboardEvent): void => {
      if (ev.key === "Escape" && started) {
        ev.preventDefault();
        cleanupVisuals(true);
        announcePolite(t("layoutStudio.canvas.liveCanceledDrag"));
      }
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKeyDown);
  };

  const handleLegendKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, slot: LayoutSlotMeta): void => {
    if (!slot.legend_box_mm) return;
    const [sx0, sy0, sx1, sy1] = slot.spine_box_mm;
    const [lx0, ly0] = slot.legend_box_mm;
    const curOv = panelOverrides[slot.panel_id] || DEFAULT_PANEL_OVERRIDE;
    const baseNx =
      curOv.legend_pos === "custom"
        ? curOv.legend_xy_norm[0]
        : (lx0 + 0.6 - sx0) / Math.max(5.0, sx1 - sx0);
    const baseNy =
      curOv.legend_pos === "custom"
        ? curOv.legend_xy_norm[1]
        : (ly0 + 0.5 - sy0) / Math.max(5.0, sy1 - sy0);

    const step = 0.04;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      commitLegendNorm(slot, baseNx - step, baseNy);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      commitLegendNorm(slot, baseNx + step, baseNy);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      commitLegendNorm(slot, baseNx, baseNy - step);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      commitLegendNorm(slot, baseNx, baseNy + step);
    } else {
      return;
    }
    announcePolite(
      t("layoutStudio.canvas.liveMovedLegend", {
        tag: (slot.tag_label || slot.panel_id).toUpperCase(),
      }),
    );
  };

  // ---------------- 3. ROI Callout Box 120 FPS Direct CSS Drag + Commit on Release ----------------
  const startRoiDrag = (
    e: React.PointerEvent<HTMLElement>,
    mode: "move" | "resize",
    slot: LayoutSlotMeta,
    roi: LayoutROIConfig,
    roiBoxEl: HTMLButtonElement | null,
  ): void => {
    if (e.button !== 0 || !composed || !roiBoxEl) return;
    e.stopPropagation();
    e.preventDefault();
    const paperEl = paperRef.current;
    if (!paperEl) return;
    const activePid = e.pointerId;
    const rect = paperEl.getBoundingClientRect();
    const pxPerMmX = rect.width / composed.page_width_mm;
    const pxPerMmY = rect.height / composed.page_height_mm;
    const [sx0, sy0, sx1, sy1] = slot.spine_box_mm;
    const imgWpx = Math.max(20, (sx1 - sx0) * pxPerMmX);
    const imgHpx = Math.max(20, (sy1 - sy0) * pxPerMmY);

    const startX = e.clientX;
    const startY = e.clientY;
    const orig = { ...roi };
    let nextPatch: Partial<LayoutROIConfig> = {};
    let moved = false;

    document.documentElement.classList.add("dq-is-dragging");

    const onMove = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      moved = true;
      const dx = (ev.clientX - startX) / imgWpx;
      const dy = (ev.clientY - startY) / imgHpx;
      const xn =
        mode === "move"
          ? Math.max(0, Math.min(1 - orig.w_norm, Number((orig.x_norm + dx).toFixed(3))))
          : orig.x_norm;
      const yn =
        mode === "move"
          ? Math.max(0, Math.min(1 - orig.h_norm, Number((orig.y_norm + dy).toFixed(3))))
          : orig.y_norm;
      const wn =
        mode === "resize"
          ? Math.max(0.08, Math.min(1 - orig.x_norm, Number((orig.w_norm + dx).toFixed(3))))
          : orig.w_norm;
      const hn =
        mode === "resize"
          ? Math.max(0.08, Math.min(1 - orig.y_norm, Number((orig.h_norm + dy).toFixed(3))))
          : orig.h_norm;
      nextPatch = mode === "move" ? { x_norm: xn, y_norm: yn } : { w_norm: wn, h_norm: hn };

      // Update live overlay box at 120 FPS without touching network or React state!
      roiBoxEl.style.left = `${((sx0 + xn * (sx1 - sx0)) / composed.page_width_mm) * 100}%`;
      roiBoxEl.style.top = `${((sy0 + yn * (sy1 - sy0)) / composed.page_height_mm) * 100}%`;
      roiBoxEl.style.width = `${((wn * (sx1 - sx0)) / composed.page_width_mm) * 100}%`;
      roiBoxEl.style.height = `${((hn * (sy1 - sy0)) / composed.page_height_mm) * 100}%`;
    };

    const onUp = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      document.documentElement.classList.remove("dq-is-dragging");
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onUp);
      if (moved) {
        updateRoi(slot.panel_id, nextPatch, true);
        announcePolite(
          t("layoutStudio.canvas.liveMovedRoi", {
            tag: (slot.tag_label || slot.panel_id).toUpperCase(),
          }),
        );
      }
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  };

  const handleRoiKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    slot: LayoutSlotMeta,
    roi: LayoutROIConfig,
  ): void => {
    const step = 0.025;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      updateRoi(slot.panel_id, { x_norm: Math.max(0, Number((roi.x_norm - step).toFixed(3))) }, true);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      updateRoi(
        slot.panel_id,
        { x_norm: Math.min(1 - roi.w_norm, Number((roi.x_norm + step).toFixed(3))) },
        true,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      updateRoi(slot.panel_id, { y_norm: Math.max(0, Number((roi.y_norm - step).toFixed(3))) }, true);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      updateRoi(
        slot.panel_id,
        { y_norm: Math.min(1 - roi.h_norm, Number((roi.y_norm + step).toFixed(3))) },
        true,
      );
    }
  };

  // ---------------- 4. Column & Row Splitters (120 FPS Guide Line + Commit on Release) ----------------
  const startColSplitterDrag = (e: React.PointerEvent<HTMLDivElement>, sp: ColSplitterItem): void => {
    if (e.button !== 0 || !composed) return;
    e.stopPropagation();
    e.preventDefault();
    const paperEl = paperRef.current;
    if (!paperEl) return;
    const activePid = e.pointerId;
    const rect = paperEl.getBoundingClientRect();
    const pxPerMmX = rect.width / composed.page_width_mm;
    const startX = e.clientX;
    const pairSum = sp.leftWeight + sp.rightWeight;
    let finalLeft = sp.leftWeight;
    let finalRight = sp.rightWeight;
    let moved = false;

    document.documentElement.classList.add("dq-is-dragging");

    const onMove = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      moved = true;
      const dxMm = (ev.clientX - startX) / Math.max(0.1, pxPerMmX);
      const deltaWeight = (dxMm / sp.rowWidthMm) * 12.0;
      const minW = Math.min(1.8, pairSum * 0.25);
      finalLeft = Math.max(minW, Math.min(pairSum - minW, sp.leftWeight + deltaWeight));
      finalRight = pairSum - finalLeft;
      const effDxMm = ((finalLeft - sp.leftWeight) / 12.0) * sp.rowWidthMm;
      setColGuide({
        xPct: ((sp.xMm + effDxMm) / composed.page_width_mm) * 100,
        y0Pct: (sp.y0Mm / composed.page_height_mm) * 100,
        hPct: ((sp.y1Mm - sp.y0Mm) / composed.page_height_mm) * 100,
        leftPct: Math.round((finalLeft / pairSum) * 100),
        rightPct: Math.round((finalRight / pairSum) * 100),
      });
    };

    const onEnd = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      document.documentElement.classList.remove("dq-is-dragging");
      setColGuide(null);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onEnd);
      document.removeEventListener("pointercancel", onEnd);
      if (moved) {
        resizeColumnBlocks(sp.rowIdx, sp.leftBlockIdx, finalLeft, finalRight);
      }
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onEnd);
    document.addEventListener("pointercancel", onEnd);
  };

  const startRowSplitterDrag = (
    e: React.PointerEvent<HTMLDivElement>,
    rowIdx: number,
    ry0: number,
    ry1: number,
    origScale: number,
  ): void => {
    if (e.button !== 0 || !composed) return;
    e.stopPropagation();
    e.preventDefault();
    const paperEl = paperRef.current;
    if (!paperEl) return;
    const activePid = e.pointerId;
    const rect = paperEl.getBoundingClientRect();
    const pxPerMmY = rect.height / composed.page_height_mm;
    const startY = e.clientY;
    const rowH = Math.max(12, ry1 - ry0);
    let finalScale = origScale;
    let moved = false;

    document.documentElement.classList.add("dq-is-dragging");

    const onMove = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      moved = true;
      const dyMm = (ev.clientY - startY) / Math.max(0.1, pxPerMmY);
      const ratio = (rowH + dyMm) / rowH;
      finalScale = Math.max(0.55, Math.min(2.2, origScale * ratio));
      const newH = rowH * (finalScale / Math.max(0.1, origScale));
      setRowGuide({
        yPct: ((ry0 + newH) / composed.page_height_mm) * 100,
        heightMm: Math.round(newH),
      });
    };

    const onEnd = (ev: PointerEvent): void => {
      if (ev.pointerId !== activePid) return;
      document.documentElement.classList.remove("dq-is-dragging");
      setRowGuide(null);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onEnd);
      document.removeEventListener("pointercancel", onEnd);
      if (moved) {
        resizeRowHeight(rowIdx, finalScale);
      }
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onEnd);
    document.addEventListener("pointercancel", onEnd);
  };

  const paperWidthPx = composed
    ? Math.round((composed.page_width_mm / 25.4) * 96 * (zoomPct / 100))
    : 692;

  const dropLabelForZone = (zone: "swap" | "left" | "right" | "stack_top" | "stack_bottom"): string => {
    if (zone === "left") return t("layoutStudio.canvas.dropLeft");
    if (zone === "right") return t("layoutStudio.canvas.dropRight");
    if (zone === "stack_top") return t("layoutStudio.canvas.dropStackTop");
    if (zone === "stack_bottom") return t("layoutStudio.canvas.dropStackBottom");
    return t("layoutStudio.canvas.dropSwap");
  };

  const focusedSlot = useMemo(
    () => composed?.slots.find((s) => s.panel_id === focusedPanelId) || null,
    [composed, focusedPanelId],
  );
  const focusedTextItem = useMemo(
    () =>
      focusedSlot && focusedTextKey
        ? (focusedSlot.text_items || []).find((ti) => ti.item_key === focusedTextKey) || null
        : null,
    [focusedSlot, focusedTextKey],
  );
  const legDraggingSlot = useMemo(
    () => (legDragSlotId ? composed?.slots.find((s) => s.panel_id === legDragSlotId) || null : null),
    [composed, legDragSlotId],
  );

  return (
    <main id="main-canvas" className="dq-layout-stage">
      {/* Registered polite live region outside toolbars for accessible drag & action announcements */}
      <div className="visually-hidden" aria-live="polite">
        {liveAnnouncement}
      </div>

      {/* 120 FPS Floating Ghost Badge During Panel Reorder */}
      {draggingPanelId ? (
        <div ref={panelGhostRef} className="dq-layout-panel-ghost" aria-hidden="true">
          <span>{t("layoutStudio.left.panelNameTagged", { tag: draggingPanelTag })}</span>
        </div>
      ) : null}

      <div className="dq-layout-stage__scroll">
        {isComparingNaive && composed ? (
          <div className="dq-layout-notice dq-layout-notice--warn" style={{ maxWidth: `${paperWidthPx}px` }}>
            <strong>{t("layoutStudio.canvas.naiveBannerLead")}</strong>{" "}
            <span>
              {t("layoutStudio.canvas.naiveBannerBody", {
                minPt: composed.naive_stats.min_font_pt,
                maxSw: composed.naive_stats.max_stroke_pt,
              })}
            </span>
          </div>
        ) : null}

        {!isComparingNaive && composed?.overflow_warning ? (
          <div className="dq-layout-notice" style={{ maxWidth: `${paperWidthPx}px` }}>
            <strong>{t("layoutStudio.canvas.overflowLead")}</strong>{" "}
            <span>{t("layoutStudio.canvas.overflowBody", { h: composed.page_height_mm })}</span>
          </div>
        ) : null}

        {composed ? (
          <div
            ref={paperRef}
            className="dq-layout-paper"
            style={{ width: `${paperWidthPx}px` }}
          >
            <div
              className="dq-layout-paper__svg"
              dangerouslySetInnerHTML={{
                __html:
                  isComparingNaive && composed.naive_svg ? composed.naive_svg : composed.modular_svg,
              }}
            />

            {/* Column Splitters */}
            {!isComparingNaive &&
              !draggingPanelId &&
              !legDragSlotId &&
              colSplitters.map((sp) => (
                <div
                  key={`col-sp-${sp.rowIdx}-${sp.leftBlockIdx}`}
                  className="dq-layout-col-splitter"
                  style={{
                    left: `${(sp.xMm / composed.page_width_mm) * 100}%`,
                    top: `${(sp.y0Mm / composed.page_height_mm) * 100}%`,
                    height: `${((sp.y1Mm - sp.y0Mm) / composed.page_height_mm) * 100}%`,
                  }}
                  title={t("layoutStudio.canvas.colResizeTitle")}
                  onPointerDown={(e) => startColSplitterDrag(e, sp)}
                />
              ))}

            {/* Live Column Splitter Guide */}
            {colGuide ? (
              <div
                className="dq-layout-live-col-guide"
                style={{
                  left: `${colGuide.xPct}%`,
                  top: `${colGuide.y0Pct}%`,
                  height: `${colGuide.hPct}%`,
                }}
              >
                <span>
                  {t("layoutStudio.canvas.splitterRatio", {
                    left: colGuide.leftPct,
                    right: colGuide.rightPct,
                  })}
                </span>
              </div>
            ) : null}

            {/* Row Height Splitters */}
            {!isComparingNaive &&
              !draggingPanelId &&
              !legDragSlotId &&
              composed.row_bounds_mm.map(([ry0, ry1], rIdx) => {
                const rowState = composed.bento_rows[rIdx];
                if (!rowState) return null;
                return (
                  <div
                    key={`row-sp-${rIdx}`}
                    className="dq-layout-row-splitter"
                    style={{
                      top: `${(ry1 / composed.page_height_mm) * 100}%`,
                    }}
                    title={t("layoutStudio.canvas.rowResizeTitle")}
                    onPointerDown={(e) =>
                      startRowSplitterDrag(e, rIdx, ry0, ry1, rowState.height_scale)
                    }
                  />
                );
              })}

            {/* Live Row Splitter Guide */}
            {rowGuide ? (
              <div className="dq-layout-live-row-guide" style={{ top: `${rowGuide.yPct}%` }}>
                <span>{t("layoutStudio.canvas.splitterHeight", { mm: rowGuide.heightMm })}</span>
              </div>
            ) : null}

            {/* Magnetic Inner & Outer Dock Halo Zones While Dragging Any Legend */}
            {!isComparingNaive && legDraggingSlot ? (() => {
              const [sx0, sy0, sx1, sy1] = legDraggingSlot.spine_box_mm;
              const sLeft = (sx0 / composed.page_width_mm) * 100;
              const sTop = (sy0 / composed.page_height_mm) * 100;
              const sW = ((sx1 - sx0) / composed.page_width_mm) * 100;
              const sH = ((sy1 - sy0) / composed.page_height_mm) * 100;
              return (
                <>
                  {/* Outer Top Magnetic Strip */}
                  <div
                    className={`dq-leg-mag-strip dq-leg-mag-strip--top${
                      legMagZone === "top" ? " dq-leg-mag-strip--active" : ""
                    }`}
                    style={{
                      left: `${sLeft}%`,
                      top: `${Math.max(0.4, sTop - 3.0)}%`,
                      width: `${sW}%`,
                    }}
                  >
                    <span>{t("layoutStudio.canvas.magDockTop")}</span>
                  </div>

                  {/* Outer Bottom Magnetic Strip (Horizontal Colorbar / Legend Dock!) */}
                  <div
                    className={`dq-leg-mag-strip dq-leg-mag-strip--bottom${
                      legMagZone === "bottom" ? " dq-leg-mag-strip--active" : ""
                    }`}
                    style={{
                      left: `${sLeft}%`,
                      top: `${Math.min(97.5, sTop + sH + 0.8)}%`,
                      width: `${sW}%`,
                    }}
                  >
                    <span>{t("layoutStudio.canvas.magDockBottom")}</span>
                  </div>

                  {/* Outer Right Magnetic Strip (Lets trapped inside legends escape effortlessly!) */}
                  <div
                    className={`dq-leg-mag-strip dq-leg-mag-strip--right${
                      legMagZone === "right" ? " dq-leg-mag-strip--active" : ""
                    }`}
                    style={{
                      left: `${Math.min(97.5, sLeft + sW - 0.6)}%`,
                      top: `${sTop}%`,
                      height: `${sH}%`,
                    }}
                  >
                    <span>{t("layoutStudio.canvas.magDockRight")}</span>
                  </div>

                  {/* 4 Inner Corner Snap Brackets */}
                  <div
                    className="dq-leg-mag-frame"
                    style={{ left: `${sLeft}%`, top: `${sTop}%`, width: `${sW}%`, height: `${sH}%` }}
                  >
                    <span
                      className={`dq-leg-mag-corner dq-leg-mag-corner--tl${
                        legMagZone === "inside_tl" ? " dq-leg-mag-corner--active" : ""
                      }`}
                    />
                    <span
                      className={`dq-leg-mag-corner dq-leg-mag-corner--tr${
                        legMagZone === "inside_tr" ? " dq-leg-mag-corner--active" : ""
                      }`}
                    />
                    <span
                      className={`dq-leg-mag-corner dq-leg-mag-corner--bl${
                        legMagZone === "inside_bl" ? " dq-leg-mag-corner--active" : ""
                      }`}
                    />
                    <span
                      className={`dq-leg-mag-corner dq-leg-mag-corner--br${
                        legMagZone === "inside_br" ? " dq-leg-mag-corner--active" : ""
                      }`}
                    />
                  </div>
                </>
              );
            })() : null}

            {/* New-Row Drop Indicator */}
            {!isComparingNaive &&
              draggingPanelId &&
              activeDrop?.kind === "new_row" &&
              composed.row_bounds_mm.length > 0 && (() => {
                const idx = activeDrop.insertRowIdx;
                const bounds = composed.row_bounds_mm;
                const yMm =
                  idx <= 0
                    ? bounds[0][0]
                    : idx >= bounds.length
                      ? bounds[bounds.length - 1][1]
                      : 0.5 * (bounds[idx - 1][1] + bounds[idx][0]);
                return (
                  <div
                    className="dq-layout-newrow-marker"
                    style={{ top: `${(yMm / composed.page_height_mm) * 100}%` }}
                  >
                    <span>{t("layoutStudio.canvas.dropNewRow")}</span>
                  </div>
                );
              })()}

            {/* Panel Slots, Dedicated Drag Grips, Draggable Legends & Draggable ROIs */}
            {!isComparingNaive &&
              composed.slots.map((sl) => {
                const [ox0, oy0, ox1, oy1] = sl.outer_box_mm;
                const [sx0, sy0, sx1, sy1] = sl.spine_box_mm;
                const leftPct = (ox0 / composed.page_width_mm) * 100;
                const topPct = (oy0 / composed.page_height_mm) * 100;
                const wPct = ((ox1 - ox0) / composed.page_width_mm) * 100;
                const hPct = ((oy1 - oy0) / composed.page_height_mm) * 100;
                const isActive = sl.panel_id === focusedPanelId;
                const isDraggingSource = sl.panel_id === draggingPanelId;
                const slotDropZone =
                  activeDrop?.kind === "slot" && activeDrop.dstPanelId === sl.panel_id
                    ? activeDrop.zone
                    : null;

                const pRoi = roiOverrides[sl.panel_id];
                const canDragRoi =
                  isActive &&
                  sl.locked_special &&
                  Boolean(pRoi?.enabled) &&
                  !pRoi?.linked_source_id &&
                  (pRoi?.w_norm ?? 0) > 0.03;

                const rLeft =
                  ((sx0 + (pRoi?.x_norm ?? 0) * (sx1 - sx0)) / composed.page_width_mm) * 100;
                const rTop =
                  ((sy0 + (pRoi?.y_norm ?? 0) * (sy1 - sy0)) / composed.page_height_mm) * 100;
                const rW = (((pRoi?.w_norm ?? 0.25) * (sx1 - sx0)) / composed.page_width_mm) * 100;
                const rH = (((pRoi?.h_norm ?? 0.25) * (sy1 - sy0)) / composed.page_height_mm) * 100;

                const canDragLegend = !sl.locked_special && Boolean(sl.legend_box_mm);

                return (
                  <React.Fragment key={sl.panel_id}>
                    <div
                      className={`dq-layout-slot-hit${isActive ? " dq-layout-slot-hit--active" : ""}${
                        isDraggingSource ? " dq-layout-slot-hit--source" : ""
                      }${slotDropZone ? ` dq-layout-slot-hit--drop-${slotDropZone}` : ""}`}
                      style={{
                        left: `${leftPct}%`,
                        top: `${topPct}%`,
                        width: `${wPct}%`,
                        height: `${hPct}%`,
                      }}
                      title={
                        sl.tag_label
                          ? t("layoutStudio.canvas.slotTitle", { tag: sl.tag_label.toUpperCase() })
                          : t("layoutStudio.canvas.slotTitleUntagged")
                      }
                      onClick={(e) => {
                        const paperEl = paperRef.current;
                        if (paperEl && composed) {
                          const r = paperEl.getBoundingClientRect();
                          const xMm = ((e.clientX - r.left) / Math.max(1, r.width)) * composed.page_width_mm;
                          const yMm = ((e.clientY - r.top) / Math.max(1, r.height)) * composed.page_height_mm;
                          const hitTxt = hitTestTextItem(sl, xMm, yMm, false);
                          if (hitTxt) {
                            setFocusedText(sl.panel_id, hitTxt.item_key, true);
                            return;
                          }
                        }
                        setFocusedText(sl.panel_id, null, true);
                      }}
                    >
                      <button
                        type="button"
                        className="dq-layout-grab-btn"
                        aria-label={t("layoutStudio.canvas.grabHandleLabel", {
                          tag: (sl.tag_label || sl.panel_id).toUpperCase(),
                        })}
                        title={t("layoutStudio.canvas.grabHandleLabel", {
                          tag: (sl.tag_label || sl.panel_id).toUpperCase(),
                        })}
                        onClick={(e) => {
                          e.stopPropagation();
                          setFocusedPanelId(sl.panel_id, true);
                        }}
                        onPointerDown={(e) => startPanelDrag(e, sl)}
                        onKeyDown={(e) => {
                          if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                            e.preventDefault();
                            movePanelOrder(sl.panel_id, -1);
                            announcePolite(
                              t("layoutStudio.canvas.liveMovedPanel", {
                                tag: (sl.tag_label || sl.panel_id).toUpperCase(),
                              }),
                            );
                          } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                            e.preventDefault();
                            movePanelOrder(sl.panel_id, 1);
                            announcePolite(
                              t("layoutStudio.canvas.liveMovedPanel", {
                                tag: (sl.tag_label || sl.panel_id).toUpperCase(),
                              }),
                            );
                          }
                        }}
                      >
                        <GripVertical size={11} strokeWidth={1.8} aria-hidden="true" />
                      </button>

                      {slotDropZone ? (
                        <div className={`dq-layout-drop-badge dq-layout-drop-badge--${slotDropZone}`}>
                          <span>{dropLabelForZone(slotDropZone)}</span>
                        </div>
                      ) : null}
                    </div>

                    {/* Draggable Legend / Colorbar Overlay on All Vector Panels */}
                    {canDragLegend && sl.legend_box_mm ? (
                      <button
                        type="button"
                        className={`dq-layout-legend-box${
                          isActive ? " dq-layout-legend-box--active" : ""
                        }`}
                        style={{
                          left: `${(sl.legend_box_mm[0] / composed.page_width_mm) * 100}%`,
                          top: `${(sl.legend_box_mm[1] / composed.page_height_mm) * 100}%`,
                          width: `${((sl.legend_box_mm[2] - sl.legend_box_mm[0]) / composed.page_width_mm) * 100}%`,
                          height: `${((sl.legend_box_mm[3] - sl.legend_box_mm[1]) / composed.page_height_mm) * 100}%`,
                        }}
                        aria-label={t("layoutStudio.canvas.legendHandleLabel", {
                          tag: (sl.tag_label || sl.panel_id).toUpperCase(),
                        })}
                        title={t("layoutStudio.canvas.legendHandleLabel", {
                          tag: (sl.tag_label || sl.panel_id).toUpperCase(),
                        })}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (e.detail === 0) {
                            setFocusedText(sl.panel_id, null, true);
                          }
                        }}
                        onPointerDown={(e) => startLegendDrag(e, sl)}
                        onKeyDown={(e) => handleLegendKeyDown(e, sl)}
                      >
                        <span className="dq-layout-legend-grip" aria-hidden="true">
                          <Move size={9} strokeWidth={2} />
                        </span>
                      </button>
                    ) : null}

                    {/* Individual Non-Legend Text Click Targets on Active Panel */}
                    {isActive &&
                      !draggingPanelId &&
                      !legDragSlotId &&
                      (sl.text_items || [])
                        .filter(
                          (ti) =>
                            !ti.item_key.startsWith("LEG:") && !ti.item_key.startsWith("CB_"),
                        )
                        .map((ti) => {
                          const [bx0, by0, bx1, by1] = ti.bbox_mm;
                          const padMm = 0.45;
                          const isSelTxt = focusedTextKey === ti.item_key;
                          return (
                            <button
                              key={`txt-${sl.panel_id}-${ti.item_key}`}
                              type="button"
                              className={`dq-layout-text-hit${
                                isSelTxt ? " dq-layout-text-hit--selected" : ""
                              }`}
                              style={{
                                left: `${((bx0 - padMm) / composed.page_width_mm) * 100}%`,
                                top: `${((by0 - padMm) / composed.page_height_mm) * 100}%`,
                                width: `${((bx1 - bx0 + 2 * padMm) / composed.page_width_mm) * 100}%`,
                                height: `${((by1 - by0 + 2 * padMm) / composed.page_height_mm) * 100}%`,
                              }}
                              aria-label={t("layoutStudio.canvas.textHitLabel", {
                                text: ti.text,
                              })}
                              title={t("layoutStudio.canvas.textHitLabel", {
                                text: ti.text,
                              })}
                              onClick={(e) => {
                                e.stopPropagation();
                                setFocusedText(
                                  sl.panel_id,
                                  isSelTxt ? null : ti.item_key,
                                  true,
                                );
                              }}
                            />
                          );
                        })}

                    {/* Draggable ROI Overlay on Locked Special Panel */}
                    {canDragRoi && pRoi ? (
                      <button
                        type="button"
                        className="dq-layout-roi-box"
                        style={{
                          left: `${rLeft}%`,
                          top: `${rTop}%`,
                          width: `${rW}%`,
                          height: `${rH}%`,
                        }}
                        aria-label={t("layoutStudio.canvas.roiDragTitle")}
                        title={t("layoutStudio.canvas.roiDragTitle")}
                        onClick={(e) => e.stopPropagation()}
                        onPointerDown={(e) => startRoiDrag(e, "move", sl, pRoi, e.currentTarget)}
                        onKeyDown={(e) => handleRoiKeyDown(e, sl, pRoi)}
                      >
                        <span
                          className="dq-layout-roi-knob"
                          title={t("layoutStudio.canvas.roiResizeTitle")}
                          onPointerDown={(e) =>
                            startRoiDrag(
                              e,
                              "resize",
                              sl,
                              pRoi,
                              e.currentTarget.parentElement as HTMLButtonElement | null,
                            )
                          }
                        />
                      </button>
                    ) : null}
                  </React.Fragment>
                );
              })}

            {/* Active Selection Ring + Contextual Single-Text Floating Style Toolbar! */}
            {!isComparingNaive &&
              !draggingPanelId &&
              !legDragSlotId &&
              focusedSlot &&
              focusedTextItem && (() => {
                const [bx0, by0, bx1, by1] = focusedTextItem.bbox_mm;
                const padMm = 0.55;
                const curPanelOv = panelOverrides[focusedSlot.panel_id] || DEFAULT_PANEL_OVERRIDE;
                const curItemOv =
                  curPanelOv.text_overrides?.[focusedTextItem.item_key] ||
                  DEFAULT_TEXT_ITEM_OVERRIDE;
                const cxPct = Math.max(
                  22,
                  Math.min(78, ((0.5 * (bx0 + bx1)) / composed.page_width_mm) * 100),
                );
                const placeBelow = by0 < 14.0;
                const yPct = placeBelow
                  ? ((by1 + 0.8) / composed.page_height_mm) * 100
                  : ((by0 - 0.6) / composed.page_height_mm) * 100;

                return (
                  <>
                    <div
                      className="dq-layout-text-selected-ring"
                      aria-hidden="true"
                      style={{
                        left: `${((bx0 - padMm) / composed.page_width_mm) * 100}%`,
                        top: `${((by0 - padMm) / composed.page_height_mm) * 100}%`,
                        width: `${((bx1 - bx0 + 2 * padMm) / composed.page_width_mm) * 100}%`,
                        height: `${((by1 - by0 + 2 * padMm) / composed.page_height_mm) * 100}%`,
                      }}
                    />

                    <input
                      ref={txtColorInputRef}
                      type="color"
                      tabIndex={-1}
                      aria-hidden="true"
                      className="visually-hidden"
                      value={
                        curItemOv.color && curItemOv.color.startsWith("#")
                          ? curItemOv.color
                          : focusedTextItem.fill
                      }
                      onChange={(e) =>
                        updateTextItemOverride(
                          focusedSlot.panel_id,
                          focusedTextItem.item_key,
                          { color: e.target.value },
                        )
                      }
                    />

                    <div
                      ref={txtToolbarRef}
                      role="toolbar"
                      {...({ focusgroup: "toolbar wrap" } as Record<string, string>)}
                      aria-label={t("layoutStudio.canvas.txtToolbarLabel", {
                        text: focusedTextItem.text,
                      })}
                      className={`dq-leg-toolbar${placeBelow ? " dq-leg-toolbar--below" : ""}`}
                      style={{ left: `${cxPct}%`, top: `${yPct}%` }}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          e.preventDefault();
                          setFocusedText(focusedSlot.panel_id, null, true);
                          return;
                        }
                        handleToolbarKeyDown(e);
                      }}
                    >
                      <span className="dq-txt-toolbar__badge" aria-hidden="true">
                        {focusedTextItem.text}
                      </span>

                      <span
                        role="separator"
                        aria-orientation="vertical"
                        className="dq-leg-toolbar__sep"
                      />

                      <div
                        role="group"
                        aria-label={t("layoutStudio.canvas.txtGroupColor")}
                        className="dq-leg-toolbar__grp"
                      >
                        {SINGLE_TEXT_SWATCHES.map((sw) => {
                          const isSwSel =
                            curItemOv.color !== "SWATCH" &&
                            focusedTextItem.fill.toUpperCase() === sw.hex;
                          return (
                            <button
                              key={sw.id}
                              type="button"
                              className="dq-leg-toolbar__btn"
                              aria-pressed={isSwSel}
                              aria-label={t(`layoutStudio.right.singleColors.${sw.id}`)}
                              title={t(`layoutStudio.right.singleColors.${sw.id}`)}
                              onClick={() =>
                                updateTextItemOverride(
                                  focusedSlot.panel_id,
                                  focusedTextItem.item_key,
                                  { color: sw.hex },
                                  true,
                                )
                              }
                            >
                              <span
                                className="dq-layout-color-chip__dot"
                                style={{ backgroundColor: sw.hex }}
                                aria-hidden="true"
                              />
                            </button>
                          );
                        })}

                        {focusedTextItem.swatch_color ? (
                          <button
                            type="button"
                            className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                            aria-pressed={curItemOv.color === "SWATCH"}
                            aria-label={t("layoutStudio.canvas.legToggleMatch")}
                            title={t("layoutStudio.canvas.legToggleMatch")}
                            onClick={() =>
                              updateTextItemOverride(
                                focusedSlot.panel_id,
                                focusedTextItem.item_key,
                                { color: curItemOv.color === "SWATCH" ? null : "SWATCH" },
                                true,
                              )
                            }
                          >
                            <span
                              className="dq-layout-color-chip__dot"
                              style={{ backgroundColor: focusedTextItem.swatch_color }}
                              aria-hidden="true"
                            />
                            <span>{t("layoutStudio.canvas.legMatchShort")}</span>
                          </button>
                        ) : null}

                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-label={t("layoutStudio.right.legendColorCustom")}
                          title={t("layoutStudio.right.legendColorCustom")}
                          onClick={() => txtColorInputRef.current?.click()}
                        >
                          <Palette size={11} strokeWidth={1.8} aria-hidden="true" />
                        </button>
                      </div>

                      <span
                        role="separator"
                        aria-orientation="vertical"
                        className="dq-leg-toolbar__sep"
                      />

                      <div
                        role="group"
                        aria-label={t("layoutStudio.canvas.txtGroupFont")}
                        className="dq-leg-toolbar__grp"
                      >
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-pressed={focusedTextItem.bold}
                          aria-label={t("layoutStudio.canvas.txtToggleBold")}
                          title={t("layoutStudio.canvas.txtToggleBold")}
                          onClick={() =>
                            updateTextItemOverride(
                              focusedSlot.panel_id,
                              focusedTextItem.item_key,
                              { bold: !focusedTextItem.bold },
                              true,
                            )
                          }
                        >
                          <Bold size={11} strokeWidth={2} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-pressed={focusedTextItem.italic}
                          aria-label={t("layoutStudio.canvas.txtToggleItalic")}
                          title={t("layoutStudio.canvas.txtToggleItalic")}
                          onClick={() =>
                            updateTextItemOverride(
                              focusedSlot.panel_id,
                              focusedTextItem.item_key,
                              { italic: !focusedTextItem.italic },
                              true,
                            )
                          }
                        >
                          <Italic size={11} strokeWidth={1.9} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                          aria-pressed={focusedTextItem.font_family === "Times New Roman"}
                          aria-label={t("layoutStudio.canvas.txtToggleSerif")}
                          title={t("layoutStudio.canvas.txtToggleSerif")}
                          onClick={() =>
                            updateTextItemOverride(
                              focusedSlot.panel_id,
                              focusedTextItem.item_key,
                              {
                                font_family:
                                  focusedTextItem.font_family === "Times New Roman"
                                    ? "Arial"
                                    : "Times New Roman",
                              },
                              true,
                            )
                          }
                        >
                          <Type size={11} strokeWidth={1.8} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-label={t("layoutStudio.canvas.txtScaleDown")}
                          title={t("layoutStudio.canvas.txtScaleDown")}
                          onClick={() =>
                            updateTextItemOverride(
                              focusedSlot.panel_id,
                              focusedTextItem.item_key,
                              {
                                font_scale: Math.max(
                                  0.7,
                                  Number(((curItemOv.font_scale || 1.0) - 0.1).toFixed(2)),
                                ),
                              },
                              true,
                            )
                          }
                        >
                          <Minus size={11} strokeWidth={1.9} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-label={t("layoutStudio.canvas.txtScaleUp")}
                          title={t("layoutStudio.canvas.txtScaleUp")}
                          onClick={() =>
                            updateTextItemOverride(
                              focusedSlot.panel_id,
                              focusedTextItem.item_key,
                              {
                                font_scale: Math.min(
                                  1.5,
                                  Number(((curItemOv.font_scale || 1.0) + 0.1).toFixed(2)),
                                ),
                              },
                              true,
                            )
                          }
                        >
                          <Plus size={11} strokeWidth={1.9} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-label={t("layoutStudio.canvas.txtResetItem")}
                          title={t("layoutStudio.canvas.txtResetItem")}
                          onClick={() =>
                            resetTextItemOverride(focusedSlot.panel_id, focusedTextItem.item_key)
                          }
                        >
                          <RotateCcw size={11} strokeWidth={1.8} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn"
                          aria-label={t("layoutStudio.canvas.txtCloseItem")}
                          title={t("layoutStudio.canvas.txtCloseItem")}
                          onClick={() => setFocusedText(focusedSlot.panel_id, null, true)}
                        >
                          <X size={11} strokeWidth={1.9} aria-hidden="true" />
                        </button>
                      </div>
                    </div>
                  </>
                );
              })()}

            {/* Contextual In-Place Legend Floating Mini-Toolbar (when no single text item is active) */}
            {!isComparingNaive &&
              !draggingPanelId &&
              !legDragSlotId &&
              !focusedTextItem &&
              focusedSlot &&
              focusedSlot.has_legend &&
              !focusedSlot.locked_special && (() => {
                const fTag = (focusedSlot.tag_label || focusedSlot.panel_id).toUpperCase();
                const curOv = panelOverrides[focusedSlot.panel_id] || DEFAULT_PANEL_OVERRIDE;
                const effPos = (focusedSlot.effective_legend_pos || curOv.legend_pos) as LegendPosMode;

                if (effPos === "hidden" || !focusedSlot.legend_box_mm) {
                  const [, sy0, sx1] = focusedSlot.spine_box_mm;
                  return (
                    <button
                      type="button"
                      className="dq-leg-restore-pill"
                      style={{
                        left: `${Math.min(94, (sx1 / composed.page_width_mm) * 100)}%`,
                        top: `${(sy0 / composed.page_height_mm) * 100}%`,
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        updatePanelOverride(focusedSlot.panel_id, { legend_pos: "auto" }, true);
                        announcePolite(t("layoutStudio.canvas.liveRestoredLegend", { tag: fTag }));
                      }}
                    >
                      <Eye size={11} strokeWidth={1.8} aria-hidden="true" />
                      <span>{t("layoutStudio.canvas.legRestore")}</span>
                    </button>
                  );
                }

                const [lx0, ly0, lx1, ly1] = focusedSlot.legend_box_mm;
                const cxPct = Math.max(20, Math.min(80, ((0.5 * (lx0 + lx1)) / composed.page_width_mm) * 100));
                const placeBelow = ly0 < 12.0;
                const yPct = placeBelow
                  ? (ly1 / composed.page_height_mm) * 100
                  : (ly0 / composed.page_height_mm) * 100;
                const isHoriz = focusedSlot.effective_legend_orient
                  ? focusedSlot.effective_legend_orient === "horizontal"
                  : curOv.legend_orient === "horizontal";

                const setQuickPos = (pos: LegendPosMode): void => {
                  const patch =
                    pos === "top" || pos === "bottom" || pos === "right"
                      ? { legend_pos: pos, legend_orient: "auto" as const }
                      : { legend_pos: pos };
                  updatePanelOverride(focusedSlot.panel_id, patch, true);
                  announcePolite(t("layoutStudio.canvas.liveMovedLegend", { tag: fTag }));
                };

                return (
                  <div
                    ref={legToolbarRef}
                    role="toolbar"
                    {...({ focusgroup: "toolbar wrap" } as Record<string, string>)}
                    aria-label={t("layoutStudio.canvas.legToolbarLabel", { tag: fTag })}
                    className={`dq-leg-toolbar${placeBelow ? " dq-leg-toolbar--below" : ""}`}
                    style={{ left: `${cxPct}%`, top: `${yPct}%` }}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={handleToolbarKeyDown}
                  >
                    <div role="group" aria-label={t("layoutStudio.canvas.legGroupPos")} className="dq-leg-toolbar__grp">
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-pressed={effPos === "inside_tl"}
                        aria-label={t("layoutStudio.canvas.legTL")}
                        title={t("layoutStudio.canvas.legTL")}
                        onClick={() => setQuickPos("inside_tl")}
                      >
                        <CornerUpLeft size={12} strokeWidth={1.8} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-pressed={effPos === "inside_tr"}
                        aria-label={t("layoutStudio.canvas.legTR")}
                        title={t("layoutStudio.canvas.legTR")}
                        onClick={() => setQuickPos("inside_tr")}
                      >
                        <CornerUpRight size={12} strokeWidth={1.8} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-pressed={effPos === "inside_bl"}
                        aria-label={t("layoutStudio.canvas.legBL")}
                        title={t("layoutStudio.canvas.legBL")}
                        onClick={() => setQuickPos("inside_bl")}
                      >
                        <CornerDownLeft size={12} strokeWidth={1.8} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-pressed={effPos === "inside_br"}
                        aria-label={t("layoutStudio.canvas.legBR")}
                        title={t("layoutStudio.canvas.legBR")}
                        onClick={() => setQuickPos("inside_br")}
                      >
                        <CornerDownRight size={12} strokeWidth={1.8} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                        aria-pressed={effPos === "top"}
                        aria-label={t("layoutStudio.canvas.legTop")}
                        title={t("layoutStudio.canvas.legTop")}
                        onClick={() => setQuickPos("top")}
                      >
                        <ArrowUpToLine size={11} strokeWidth={1.8} aria-hidden="true" />
                        <span>{t("layoutStudio.canvas.legTopShort")}</span>
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                        aria-pressed={effPos === "bottom"}
                        aria-label={t("layoutStudio.canvas.legBottom")}
                        title={t("layoutStudio.canvas.legBottom")}
                        onClick={() => setQuickPos("bottom")}
                      >
                        <ArrowDownToLine size={11} strokeWidth={1.8} aria-hidden="true" />
                        <span>{t("layoutStudio.canvas.legBottomShort")}</span>
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                        aria-pressed={effPos === "right"}
                        aria-label={t("layoutStudio.canvas.legRight")}
                        title={t("layoutStudio.canvas.legRight")}
                        onClick={() => setQuickPos("right")}
                      >
                        <ArrowRightToLine size={11} strokeWidth={1.8} aria-hidden="true" />
                        <span>{t("layoutStudio.canvas.legRightShort")}</span>
                      </button>
                    </div>

                    <span role="separator" aria-orientation="vertical" className="dq-leg-toolbar__sep" />

                    <div role="group" aria-label={t("layoutStudio.canvas.legGroupStyle")} className="dq-leg-toolbar__grp">
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                        aria-pressed={isHoriz}
                        aria-label={t("layoutStudio.canvas.legToggleOrient")}
                        title={t("layoutStudio.canvas.legToggleOrient")}
                        onClick={() => {
                          const nextOr = isHoriz ? "vertical" : "horizontal";
                          updatePanelOverride(
                            focusedSlot.panel_id,
                            focusedSlot.is_colorbar
                              ? { legend_orient: nextOr }
                              : { legend_orient: nextOr, legend_cols: nextOr === "horizontal" ? 3 : 1 },
                            true,
                          );
                        }}
                      >
                        <Columns2 size={12} strokeWidth={1.8} aria-hidden="true" />
                        <span>{t("layoutStudio.canvas.legHorizShort")}</span>
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-pressed={curOv.legend_bold}
                        aria-label={t("layoutStudio.canvas.legToggleBold")}
                        title={t("layoutStudio.canvas.legToggleBold")}
                        onClick={() =>
                          updatePanelOverride(
                            focusedSlot.panel_id,
                            { legend_bold: !curOv.legend_bold },
                            true,
                          )
                        }
                      >
                        <Bold size={11} strokeWidth={2} aria-hidden="true" />
                      </button>
                      {!focusedSlot.is_colorbar ? (
                        <button
                          type="button"
                          className="dq-leg-toolbar__btn dq-leg-toolbar__btn--text"
                          aria-pressed={curOv.legend_match_swatch}
                          aria-label={t("layoutStudio.canvas.legToggleMatch")}
                          title={t("layoutStudio.canvas.legToggleMatch")}
                          onClick={() =>
                            updatePanelOverride(
                              focusedSlot.panel_id,
                              { legend_match_swatch: !curOv.legend_match_swatch },
                              true,
                            )
                          }
                        >
                          <Palette size={11} strokeWidth={1.8} aria-hidden="true" />
                          <span>{t("layoutStudio.canvas.legMatchShort")}</span>
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-pressed={curOv.legend_bg}
                        aria-label={t("layoutStudio.canvas.legToggleBg")}
                        title={t("layoutStudio.canvas.legToggleBg")}
                        onClick={() =>
                          updatePanelOverride(
                            focusedSlot.panel_id,
                            { legend_bg: !curOv.legend_bg },
                            true,
                          )
                        }
                      >
                        <Square size={11} strokeWidth={1.8} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-label={t("layoutStudio.canvas.legScaleDown")}
                        title={t("layoutStudio.canvas.legScaleDown")}
                        onClick={() =>
                          updatePanelOverride(
                            focusedSlot.panel_id,
                            { legend_scale: Math.max(0.65, Number((curOv.legend_scale - 0.1).toFixed(2))) },
                            true,
                          )
                        }
                      >
                        <Minus size={11} strokeWidth={1.9} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-label={t("layoutStudio.canvas.legScaleUp")}
                        title={t("layoutStudio.canvas.legScaleUp")}
                        onClick={() =>
                          updatePanelOverride(
                            focusedSlot.panel_id,
                            { legend_scale: Math.min(1.45, Number((curOv.legend_scale + 0.1).toFixed(2))) },
                            true,
                          )
                        }
                      >
                        <Plus size={11} strokeWidth={1.9} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="dq-leg-toolbar__btn"
                        aria-label={t("layoutStudio.canvas.legHide")}
                        title={t("layoutStudio.canvas.legHide")}
                        onClick={() => {
                          updatePanelOverride(focusedSlot.panel_id, { legend_pos: "hidden" }, true);
                          announcePolite(t("layoutStudio.canvas.liveHiddenLegend", { tag: fTag }));
                        }}
                      >
                        <EyeOff size={11} strokeWidth={1.8} aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                );
              })()}
          </div>
        ) : null}
      </div>

      {/* Danqing Floating Zoom Pill */}
      <div className="dq-layout-zoom" role="group" aria-label={t("a11y.zoomToolbar")}>
        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("layoutStudio.canvas.zoomOut")}
          title={t("layoutStudio.canvas.zoomOut")}
          onClick={() => setZoomPct(zoomPct - 15)}
        >
          <Minus size={14} strokeWidth={1.6} aria-hidden="true" />
        </button>
        <span className="dq-layout-zoom__val">{zoomPct}%</span>
        <button
          type="button"
          className="dq-btn dq-btn--ghost dq-btn--icon"
          aria-label={t("layoutStudio.canvas.zoomIn")}
          title={t("layoutStudio.canvas.zoomIn")}
          onClick={() => setZoomPct(zoomPct + 15)}
        >
          <Plus size={14} strokeWidth={1.6} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="dq-btn dq-btn--ghost"
          onClick={() => setZoomPct(105)}
        >
          {t("layoutStudio.canvas.zoomFit")}
        </button>
      </div>
    </main>
  );
}
