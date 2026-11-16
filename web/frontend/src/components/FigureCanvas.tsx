import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Columns2, Maximize2, Minus, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useStudioStore } from "../store";

interface DecodedPickMap {
  width: number;
  height: number;
  pixels: Uint8ClampedArray;
}

export function FigureCanvas(): React.ReactElement | null {
  const { t } = useTranslation();
  const figure = useStudioStore((s) => s.figure);
  const targetPanels = useStudioStore((s) => s.targetPanels);
  const selectedIds = useStudioStore((s) => s.selectedIds);
  const hoveredEntityId = useStudioStore((s) => s.hoveredEntityId);
  const hoveredPanelLabel = useStudioStore((s) => s.hoveredPanelLabel);
  const hoveredPaletteId = useStudioStore((s) => s.hoveredPaletteId);
  const hoveredStyleId = useStudioStore((s) => s.hoveredStyleId);
  const hoveredSwatch = useStudioStore((s) => s.hoveredSwatch);
  const hoveredAlpha = useStudioStore((s) => s.hoveredAlpha);
  const isComparingOriginal = useStudioStore((s) => s.isComparingOriginal);
  const splitCompareActive = useStudioStore((s) => s.splitCompareActive);
  const cvdMode = useStudioStore((s) => s.cvdMode);
  const onboardingDismissed = useStudioStore((s) => s.onboardingDismissed);

  const selectEntity = useStudioStore((s) => s.selectEntity);
  const setHoveredEntity = useStudioStore((s) => s.setHoveredEntity);
  const setElementRoles = useStudioStore((s) => s.setElementRoles);
  const toggleSplitCompare = useStudioStore((s) => s.toggleSplitCompare);
  const dismissOnboarding = useStudioStore((s) => s.dismissOnboarding);

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const [viewportSize, setViewportSize] = useState({ w: 800, h: 600 });
  const [zoomFactor, setZoomFactor] = useState(1.0);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [spaceDown, setSpaceDown] = useState(false);
  const [draggingPan, setDraggingPan] = useState(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  const [displayedSrc, setDisplayedSrc] = useState<string>("");
  const blobUrlRef = useRef<string | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [renderError, setRenderError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  const [pickMap, setPickMap] = useState<DecodedPickMap | null>(null);
  const [pointerPos, setPointerPos] = useState<{ x: number; y: number } | null>(null);
  const [splitRatio, setSplitRatio] = useState(0.5);
  const draggingSplitRef = useRef(false);

  // Measure available viewport container
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const cr = entry.contentRect;
        if (cr.width > 0 && cr.height > 0) {
          setViewportSize({ w: cr.width, h: cr.height });
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Reset zoom & pan on figure switch
  useEffect(() => {
    setZoomFactor(1.0);
    setPan({ x: 0, y: 0 });
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
    setDisplayedSrc("");
    setRenderError(false);
  }, [figure?.figure_id]);

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, []);

  // Listen to global keyboard zoom/fit events
  useEffect(() => {
    const onFit = (): void => {
      setZoomFactor(1.0);
      setPan({ x: 0, y: 0 });
    };
    const onZoomIn = (): void => setZoomFactor((z) => Math.min(4.0, +(z + 0.25).toFixed(2)));
    const onZoomOut = (): void => setZoomFactor((z) => Math.max(0.4, +(z - 0.25).toFixed(2)));

    const onKeyDown = (e: KeyboardEvent): void => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.code === "Space") {
        setSpaceDown(true);
      }
    };
    const onKeyUp = (e: KeyboardEvent): void => {
      if (e.code === "Space") {
        setSpaceDown(false);
        setDraggingPan(false);
      }
    };

    window.addEventListener("danqing:fit", onFit);
    window.addEventListener("danqing:zoom-in", onZoomIn);
    window.addEventListener("danqing:zoom-out", onZoomOut);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("danqing:fit", onFit);
      window.removeEventListener("danqing:zoom-in", onZoomIn);
      window.removeEventListener("danqing:zoom-out", onZoomOut);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  // Build target render URL (with hover palette / panel scope / swatch / hi-DPI scale)
  const targetRenderUrl = useMemo(() => {
    if (!figure) return "";
    const params = new URLSearchParams();
    params.set("rev", String(figure.revision));
    if (hoveredPaletteId) {
      params.set("palette", hoveredPaletteId);
      if (targetPanels.length > 0 && figure.panels.length > 1) {
        params.set("panels", targetPanels.join(","));
      }
    }
    if (hoveredStyleId) {
      params.set("style", hoveredStyleId);
    }
    if (hoveredSwatch) {
      params.set("pe", hoveredSwatch.entityId);
      params.set("ph", hoveredSwatch.hex.replace("#", ""));
    }
    if (hoveredAlpha) {
      params.set("pe", hoveredAlpha.entityId);
      params.set("pa", String(hoveredAlpha.alpha));
    }
    if (zoomFactor > 1.5 && figure.kind === "pdf") {
      const hiScale = Math.min(5.0, +(figure.preview_scale * zoomFactor).toFixed(2));
      params.set("scale", String(hiScale));
    }
    if (retryNonce > 0) {
      params.set("retry", String(retryNonce));
    }
    return `/api/v2/figures/${figure.figure_id}/render?${params.toString()}`;
  }, [figure, hoveredPaletteId, hoveredStyleId, targetPanels, hoveredSwatch, hoveredAlpha, zoomFactor, retryNonce]);

  // Abortable fetch + offscreen decode + silent auto-retry (prevents hover backlog & transient complex-PDF failures)
  useEffect(() => {
    if (!targetRenderUrl) return;
    const controller = new AbortController();
    let cancelled = false;
    setIsUpdating(true);
    setRenderError(false);

    const loadPreview = async (): Promise<void> => {
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const res = await fetch(targetRenderUrl, { signal: controller.signal });
          if (cancelled || controller.signal.aborted) return;
          if (res.status === 204) {
            // Superseded intermediate hover preview — keep current image cleanly
            setIsUpdating(false);
            return;
          }
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
          }
          const blob = await res.blob();
          if (cancelled || controller.signal.aborted) return;
          const nextObjUrl = URL.createObjectURL(blob);
          const decImg = new Image();
          decImg.src = nextObjUrl;
          try {
            await decImg.decode();
          } catch {
            // Safari / SVG fallback if decode() rejects on valid image
          }
          if (cancelled || controller.signal.aborted) {
            URL.revokeObjectURL(nextObjUrl);
            return;
          }
          const prevObjUrl = blobUrlRef.current;
          blobUrlRef.current = nextObjUrl;
          setDisplayedSrc(nextObjUrl);
          setIsUpdating(false);
          setRenderError(false);
          if (prevObjUrl) {
            window.setTimeout(() => URL.revokeObjectURL(prevObjUrl), 120);
          }
          return;
        } catch {
          if (cancelled || controller.signal.aborted) return;
          if (attempt === 0) {
            await new Promise((r) => window.setTimeout(r, 220));
            continue;
          }
          setIsUpdating(false);
          // Only show persistent error banner for committed state renders, not transient hover previews
          if (!hoveredPaletteId && !hoveredSwatch && !hoveredAlpha) {
            setRenderError(true);
          }
        }
      }
    };

    void loadPreview();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [targetRenderUrl, hoveredPaletteId, hoveredSwatch, hoveredAlpha]);

  // Load and decode pick_url into offscreen RGBA array
  useEffect(() => {
    if (!figure?.pick_url) {
      setPickMap(null);
      return;
    }
    let cancelled = false;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (cancelled) return;
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(img, 0, 0);
      const data = ctx.getImageData(0, 0, c.width, c.height).data;
      setPickMap({ width: c.width, height: c.height, pixels: data });
    };
    img.src = figure.pick_url;
    return () => {
      cancelled = true;
    };
  }, [figure?.figure_id, figure?.pick_url]);

  // Map cat_index -> entity_id, panel_id & mark_kind
  const catMaps = useMemo(() => {
    const toEntity = new Map<number, string>();
    const toPanel = new Map<number, string>();
    const toMarkKind = new Map<number, string>();
    const entityToCats = new Map<string, Set<number>>();
    if (figure) {
      for (const entry of figure.categorical_lut) {
        toEntity.set(entry.cat_index, entry.entity_id);
        toPanel.set(entry.cat_index, entry.panel_id);
        toMarkKind.set(entry.cat_index, entry.mark_kind || "area");
        if (!entityToCats.has(entry.entity_id)) {
          entityToCats.set(entry.entity_id, new Set());
        }
        entityToCats.get(entry.entity_id)!.add(entry.cat_index);
      }
    }
    return { toEntity, toPanel, toMarkKind, entityToCats };
  }, [figure]);

  // Draw hover dim veil (60%) + 2px white + 1px black contour for hovered / selected elements
  useEffect(() => {
    const canvas = overlayCanvasRef.current;
    if (!canvas || !pickMap) return;

    if (canvas.width !== pickMap.width || canvas.height !== pickMap.height) {
      canvas.width = pickMap.width;
      canvas.height = pickMap.height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (isComparingOriginal) return;

    const w = pickMap.width;
    const h = pickMap.height;
    const hasScopedPanels =
      Boolean(figure) && targetPanels.length > 0 && (figure?.panels.length ?? 0) > 1;

    const activeSet = new Set<number>();
    const isHoverActive = Boolean(hoveredEntityId);
    if (hoveredEntityId) {
      const s = catMaps.entityToCats.get(hoveredEntityId);
      if (s) s.forEach((v) => activeSet.add(v));
    } else if (selectedIds.length > 0) {
      for (const sid of selectedIds) {
        const s = catMaps.entityToCats.get(sid);
        if (s) s.forEach((v) => activeSet.add(v));
      }
    }

    if (activeSet.size === 0) {
      // If user focused specific panel(s), softly dim non-target areas & frame active panel(s)
      if (hasScopedPanels && figure) {
        const sx = w / Math.max(1, figure.width);
        const sy = h / Math.max(1, figure.height);
        const tset = new Set(targetPanels);
        ctx.save();
        ctx.fillStyle = "rgba(255, 255, 255, 0.42)";
        ctx.fillRect(0, 0, w, h);
        for (const pb of figure.panels) {
          if (!tset.has(pb.panel_id)) continue;
          const [x0, y0, x1, y1] = pb.bbox;
          const rx = Math.max(0, Math.floor(x0 * sx) - 4);
          const ry = Math.max(0, Math.floor(y0 * sy) - 4);
          const rw = Math.min(w - rx, Math.ceil((x1 - x0) * sx) + 8);
          const rh = Math.min(h - ry, Math.ceil((y1 - y0) * sy) + 8);
          ctx.clearRect(rx, ry, rw, rh);
        }
        ctx.strokeStyle = "rgba(17, 24, 39, 0.36)";
        ctx.lineWidth = Math.max(1.5, Math.round(sx));
        ctx.setLineDash([6, 4]);
        for (const pb of figure.panels) {
          if (!tset.has(pb.panel_id)) continue;
          const [x0, y0, x1, y1] = pb.bbox;
          const rx = Math.max(1, Math.floor(x0 * sx) - 3);
          const ry = Math.max(1, Math.floor(y0 * sy) - 3);
          const rw = Math.min(w - rx - 1, Math.ceil((x1 - x0) * sx) + 6);
          const rh = Math.min(h - ry - 1, Math.ceil((y1 - y0) * sy) + 6);
          ctx.strokeRect(rx, ry, rw, rh);
        }
        ctx.restore();
      }
      return;
    }

    const src = pickMap.pixels;
    const mask = new Uint8Array(w * h);

    for (let i = 0, p = 0; i < mask.length; i++, p += 4) {
      const r = src[p];
      if (r >= 1 && r <= 240) {
        const catIdx = r - 1 + src[p + 1] * 240;
        if (activeSet.has(catIdx)) {
          mask[i] = 1;
        }
      }
    }

    const outImg = ctx.createImageData(w, h);
    const dst = outImg.data;

    // 1. If hovering an element, dim all non-hovered pixels by 60% white veil (Spec 4.3)
    if (isHoverActive) {
      for (let i = 0, p = 0; i < mask.length; i++, p += 4) {
        if (mask[i] === 0) {
          dst[p] = 255;
          dst[p + 1] = 255;
          dst[p + 2] = 255;
          dst[p + 3] = 153; // 60% of 255
        }
      }
    }

    // 2. Compute 1px inner black boundary + 2px outer white halo around mask==1 (Spec 4.4)
    const edge1 = new Uint8Array(w * h);
    for (let y = 1; y < h - 1; y++) {
      const row = y * w;
      for (let x = 1; x < w - 1; x++) {
        const idx = row + x;
        if (mask[idx] === 0) {
          if (
            mask[idx - 1] === 1 ||
            mask[idx + 1] === 1 ||
            mask[idx - w] === 1 ||
            mask[idx + w] === 1
          ) {
            edge1[idx] = 1;
          }
        }
      }
    }

    for (let y = 2; y < h - 2; y++) {
      const row = y * w;
      for (let x = 2; x < w - 2; x++) {
        const idx = row + x;
        if (edge1[idx] === 1) {
          const p = idx * 4;
          dst[p] = 17;
          dst[p + 1] = 24;
          dst[p + 2] = 39;
          dst[p + 3] = 255;
        } else if (mask[idx] === 0) {
          // 2px white halo outside the 1px black contour
          if (
            edge1[idx - 1] === 1 ||
            edge1[idx + 1] === 1 ||
            edge1[idx - w] === 1 ||
            edge1[idx + w] === 1 ||
            edge1[idx - w - 1] === 1 ||
            edge1[idx - w + 1] === 1 ||
            edge1[idx + w - 1] === 1 ||
            edge1[idx + w + 1] === 1
          ) {
            const p = idx * 4;
            dst[p] = 255;
            dst[p + 1] = 255;
            dst[p + 2] = 255;
            dst[p + 3] = 245;
          }
        }
      }
    }

    ctx.putImageData(outImg, 0, 0);
  }, [pickMap, figure, targetPanels, hoveredEntityId, selectedIds, catMaps, isComparingOriginal]);

  const lookupHitAtClient = useCallback(
    (
      clientX: number,
      clientY: number,
      cycleFromEntityId?: string | null,
    ): { entityId: string | null; panelId: string | null } => {
      const stage = stageRef.current;
      if (!stage || !pickMap) return { entityId: null, panelId: null };
      const rect = stage.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return { entityId: null, panelId: null };
      const nx = (clientX - rect.left) / rect.width;
      const ny = (clientY - rect.top) / rect.height;
      if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return { entityId: null, panelId: null };
      const px = Math.min(pickMap.width - 1, Math.max(0, Math.floor(nx * pickMap.width)));
      const py = Math.min(pickMap.height - 1, Math.max(0, Math.floor(ny * pickMap.height)));
      const readCatAt = (x: number, y: number): number => {
        if (x < 0 || x >= pickMap.width || y < 0 || y >= pickMap.height) return -1;
        const off = (y * pickMap.width + x) * 4;
        const r = pickMap.pixels[off];
        return r >= 1 && r <= 240 ? r - 1 + pickMap.pixels[off + 1] * 240 : -1;
      };

      const centerCat = readCatAt(px, py);
      let directPointHit: { entityId: string; panelId: string | null } | null = null;
      let directAreaHit: { entityId: string; panelId: string | null } | null = null;
      if (centerCat >= 0) {
        const eid = catMaps.toEntity.get(centerCat) || null;
        const pid = catMaps.toPanel.get(centerCat) || null;
        if (eid) {
          if (catMaps.toMarkKind.get(centerCat) !== "area") {
            directPointHit = { entityId: eid, panelId: pid };
          } else {
            directAreaHit = { entityId: eid, panelId: pid };
          }
        }
      }

      // Check if `(px, py)` sits inside a hollow open-circle marker overlaid on an `area` shape
      if (!directPointHit && directAreaHit) {
        for (const rRing of [1, 2, 3]) {
          const leftC = readCatAt(px - rRing, py);
          const rightC = readCatAt(px + rRing, py);
          if (leftC >= 0 && rightC >= 0 && catMaps.toMarkKind.get(leftC) !== "area") {
            const le = catMaps.toEntity.get(leftC);
            if (le && le === catMaps.toEntity.get(rightC)) {
              directPointHit = { entityId: le, panelId: catMaps.toPanel.get(leftC) || null };
              break;
            }
          }
          const upC = readCatAt(px, py - rRing);
          const downC = readCatAt(px, py + rRing);
          if (upC >= 0 && downC >= 0 && catMaps.toMarkKind.get(upC) !== "area") {
            const ue = catMaps.toEntity.get(upC);
            if (ue && ue === catMaps.toEntity.get(downC)) {
              directPointHit = { entityId: ue, panelId: catMaps.toPanel.get(upC) || null };
              break;
            }
          }
        }
      }

      // Scan local radius for magnetic standalone-dot snap (when cursor is on empty background)
      // AND for underlying `area` / nearby `point` layer cycling when clicking overlapping layers!
      let bestPointD2 = 999;
      let bestPointHit: { entityId: string; panelId: string | null } | null = null;
      let bestNearAreaD2 = 999;
      let bestNearAreaHit: { entityId: string; panelId: string | null } | null = directAreaHit;
      const maxR = 5;
      for (let dy = -maxR; dy <= maxR; dy++) {
        const yy = py + dy;
        if (yy < 0 || yy >= pickMap.height) continue;
        for (let dx = -maxR; dx <= maxR; dx++) {
          if (dx === 0 && dy === 0) continue;
          const d2 = dx * dx + dy * dy;
          if (d2 > maxR * maxR) continue;
          const xx = px + dx;
          if (xx < 0 || xx >= pickMap.width) continue;
          const cIdx = readCatAt(xx, yy);
          if (cIdx < 0) continue;
          const eid = catMaps.toEntity.get(cIdx) || null;
          if (!eid) continue;
          const mk = catMaps.toMarkKind.get(cIdx) || "area";
          if (mk !== "area") {
            if (d2 <= 9 && d2 < bestPointD2) {
              bestPointD2 = d2;
              bestPointHit = { entityId: eid, panelId: catMaps.toPanel.get(cIdx) || null };
            }
          } else if (d2 < bestNearAreaD2 && (!directPointHit || eid !== directPointHit.entityId)) {
            bestNearAreaD2 = d2;
            bestNearAreaHit = { entityId: eid, panelId: catMaps.toPanel.get(cIdx) || null };
          }
        }
      }

      const primary =
        directPointHit ||
        directAreaHit ||
        bestPointHit ||
        (bestNearAreaD2 <= 9 ? bestNearAreaHit : null);
      if (!primary) return { entityId: null, panelId: null };

      // Click-through cycling: if user clicks again on an already-selected point sitting over a boxplot (or vice versa), cycle layers!
      if (cycleFromEntityId && primary.entityId === cycleFromEntityId) {
        if (directPointHit && bestNearAreaHit && bestNearAreaHit.entityId !== primary.entityId) {
          return bestNearAreaHit;
        }
        if (directAreaHit && bestPointHit && bestPointHit.entityId !== primary.entityId) {
          return bestPointHit;
        }
      }
      return primary;
    },
    [pickMap, catMaps],
  );

  if (!figure) return null;

  const availW = Math.max(160, viewportSize.w - 48);
  const availH = Math.max(160, viewportSize.h - 48);
  const fitScale = Math.min(availW / Math.max(1, figure.width), availH / Math.max(1, figure.height));
  const stageW = Math.max(80, Math.round(figure.width * fitScale * zoomFactor));
  const stageH = Math.max(80, Math.round(figure.height * fitScale * zoomFactor));

  const cvdFilterStyle =
    cvdMode === "normal" ? undefined : `url(#danqing-cvd-${cvdMode})`;

  const hoveredElementObj = hoveredEntityId
    ? figure.elements.find((e) => e.entity_id === hoveredEntityId)
    : null;

  const activeImageSrc = isComparingOriginal
    ? figure.original_url
    : displayedSrc || figure.render_url;

  return (
    <main id="main-canvas" className="dq-canvas-area">
      <h1 className="visually-hidden">{figure.filename}</h1>

      {!onboardingDismissed ? (
        <div className="dq-onboarding-bar">
          <div className="dq-onboarding-steps">
            <span>{t("onboarding.step1")}</span>
            <span>{t("onboarding.step2")}</span>
            <span>{t("onboarding.step3")}</span>
          </div>
          <button type="button" className="dq-btn" onClick={dismissOnboarding}>
            {t("onboarding.dismiss")}
          </button>
        </div>
      ) : null}

      <div
        ref={viewportRef}
        className={`dq-canvas-viewport${
          draggingPan ? " dq-canvas-viewport--grabbing" : spaceDown ? " dq-canvas-viewport--grab" : ""
        }`}
        onWheel={(e) => {
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 0.12 : -0.12;
            setZoomFactor((z) => Math.max(0.4, Math.min(4.0, +(z + delta).toFixed(2))));
          } else if (zoomFactor > 1.02) {
            setPan((p) => ({ x: p.x - e.deltaX, y: p.y - e.deltaY }));
          }
        }}
        onPointerDown={(e) => {
          if (spaceDown || e.button === 1) {
            e.preventDefault();
            setDraggingPan(true);
            panStartRef.current = {
              x: e.clientX,
              y: e.clientY,
              panX: pan.x,
              panY: pan.y,
            };
            (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            return;
          }
          if (e.target === e.currentTarget) {
            selectEntity(null);
          }
        }}
        onPointerMove={(e) => {
          if (draggingPan) {
            const dx = e.clientX - panStartRef.current.x;
            const dy = e.clientY - panStartRef.current.y;
            setPan({ x: panStartRef.current.panX + dx, y: panStartRef.current.panY + dy });
            return;
          }
          if (draggingSplitRef.current && stageRef.current) {
            const r = stageRef.current.getBoundingClientRect();
            if (r.width > 0) {
              setSplitRatio(Math.max(0.05, Math.min(0.95, (e.clientX - r.left) / r.width)));
            }
          }
        }}
        onPointerUp={() => {
          setDraggingPan(false);
          draggingSplitRef.current = false;
        }}
      >
        {isComparingOriginal ? (
          <div className="dq-status-pill">{t("canvas.comparingOriginal")}</div>
        ) : renderError ? (
          <div className="dq-status-pill dq-status-pill--error">
            <span>{t("canvas.renderFailed")}</span>
            <button
              type="button"
              className="dq-btn"
              onClick={() => setRetryNonce((n) => n + 1)}
            >
              {t("canvas.retry")}
            </button>
          </div>
        ) : isUpdating ? (
          <div className="dq-status-pill">{t("canvas.updating")}</div>
        ) : null}

        <div
          ref={stageRef}
          className="dq-paper-stage"
          style={{
            width: `${stageW}px`,
            height: `${stageH}px`,
            transform: `translate(${pan.x}px, ${pan.y}px)`,
            filter: cvdFilterStyle,
            cursor: spaceDown ? "grab" : hoveredEntityId ? "pointer" : "default",
          }}
          onPointerMove={(e) => {
            if (spaceDown || draggingPan || draggingSplitRef.current) return;
            const hit = lookupHitAtClient(e.clientX, e.clientY);
            setPointerPos({ x: e.clientX, y: e.clientY });
            if (hit.entityId !== hoveredEntityId || hit.panelId !== hoveredPanelLabel) {
              setHoveredEntity(hit.entityId, hit.panelId);
            }
          }}
          onPointerLeave={() => {
            setPointerPos(null);
            setHoveredEntity(null, null);
          }}
          onClick={(e) => {
            if (spaceDown || draggingPan) return;
            const cycleFrom =
              !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && selectedIds.length === 1
                ? selectedIds[0]
                : null;
            const hit = lookupHitAtClient(e.clientX, e.clientY, cycleFrom);
            if (!hit.entityId) {
              selectEntity(null);
              return;
            }
            if (e.altKey) {
              const targetEl = figure.elements.find((x) => x.entity_id === hit.entityId);
              if (targetEl) {
                void setElementRoles(
                  [targetEl.entity_id],
                  targetEl.role === "focus" ? "normal" : "focus",
                );
              }
              return;
            }
            selectEntity(hit.entityId, e.metaKey || e.ctrlKey, e.shiftKey);
          }}
        >
          <img
            src={activeImageSrc}
            alt={t("a11y.figurePreviewAlt", { filename: figure.filename })}
            className="dq-paper-img"
            draggable={false}
          />

          {splitCompareActive && !isComparingOriginal ? (
            <>
              <div
                className="dq-paper-split"
                style={{ clipPath: `inset(0 ${(1 - splitRatio) * 100}% 0 0)` }}
              >
                <img
                  src={figure.original_url}
                  alt={t("a11y.originalPreviewAlt", { filename: figure.filename })}
                  className="dq-paper-img"
                  draggable={false}
                />
              </div>
              <div
                className="dq-paper-split-handle"
                style={{ left: `${splitRatio * 100}%` }}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  draggingSplitRef.current = true;
                }}
              />
            </>
          ) : null}

          <canvas ref={overlayCanvasRef} className="dq-overlay-canvas" aria-hidden="true" />
        </div>

        {hoveredElementObj && pointerPos && !isComparingOriginal ? (
          <div
            className="dq-hover-pill"
            style={{
              left: `${Math.min(window.innerWidth - 180, pointerPos.x + 14)}px`,
              top: `${Math.max(52, pointerPos.y - 30)}px`,
            }}
          >
            {hoveredPanelLabel
              ? `${hoveredElementObj.label} · ${hoveredPanelLabel}`
              : hoveredElementObj.label}
          </div>
        ) : null}

        <div className="dq-zoom-bar" role="group" aria-label={t("a11y.zoomToolbar")}>
          <button
            type="button"
            className="dq-btn dq-btn--ghost dq-btn--icon"
            aria-label={t("canvas.zoomOut")}
            title={t("canvas.zoomOut")}
            onClick={() => setZoomFactor((z) => Math.max(0.4, +(z - 0.25).toFixed(2)))}
          >
            <Minus size={14} strokeWidth={1.5} aria-hidden="true" />
          </button>
          <span className="dq-zoom-pct">{Math.round(zoomFactor * 100)}%</span>
          <button
            type="button"
            className="dq-btn dq-btn--ghost dq-btn--icon"
            aria-label={t("canvas.zoomIn")}
            title={t("canvas.zoomIn")}
            onClick={() => setZoomFactor((z) => Math.min(4.0, +(z + 0.25).toFixed(2)))}
          >
            <Plus size={14} strokeWidth={1.5} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="dq-btn dq-btn--ghost"
            onClick={() => {
              setZoomFactor(1.0);
              setPan({ x: 0, y: 0 });
            }}
          >
            <Maximize2 size={13} strokeWidth={1.5} aria-hidden="true" />
            <span>{t("canvas.fit")}</span>
          </button>
          <button
            type="button"
            className="dq-btn dq-btn--ghost dq-btn--icon"
            aria-label={t("canvas.splitCompare")}
            title={t("canvas.splitCompare")}
            aria-pressed={splitCompareActive}
            onClick={toggleSplitCompare}
          >
            <Columns2 size={14} strokeWidth={1.5} aria-hidden="true" />
          </button>
        </div>
      </div>
    </main>
  );
}
