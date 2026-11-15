import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Eye,
  EyeOff,
  GripVertical,
  Plus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { BUILTIN_TABLE_RAMPS } from "../../table/color";
import type {
  ColumnRole,
  ColumnSpec,
  ColumnVisualMode,
  PStyle,
  Precision,
  SemanticRole,
} from "../../table/model";
import {
  applySuggestionsToDoc,
  buildDerivedSparklineColumns,
  inferColumnDirectionHint,
  sliceBodyRows,
} from "../../table/pipeline";
import { useTableStudioStore } from "../../table/tableStore";

const SEMANTIC_ROLES: SemanticRole[] = ["normal", "count", "part", "sig"];
const VISUAL_MODES: ColumnVisualMode[] = ["auto", "plain", "heat", "bar"];
const PRECISIONS: Precision[] = ["auto", 0, 1, 2, 3];

export function TableStructurePanel(): React.ReactElement | null {
  const { t } = useTranslation();
  const docs = useTableStudioStore((s) => s.docs);
  const activeId = useTableStudioStore((s) => s.activeId);
  const commit = useTableStudioStore((s) => s.commit);
  const announce = useTableStudioStore((s) => s.announce);

  const doc = docs[activeId];

  const [selectedColId, setSelectedColId] = useState<string>("");
  const [editingColId, setEditingColId] = useState<string | null>(null);
  const [editingColText, setEditingColText] = useState("");
  const [dragColIdx, setDragColIdx] = useState<number | null>(null);
  const [dragOverColIdx, setDragOverColIdx] = useState<number | null>(null);

  // Local buffered title fields so typing commits 1 clean undo step on blur/Enter
  const [localNum, setLocalNum] = useState("");
  const [localTitle, setLocalTitle] = useState("");
  const [localSub, setLocalSub] = useState("");

  // Quick-builder states for Section 4 (Combinations)
  const [mergeFirstId, setMergeFirstId] = useState("");
  const [mergePattern, setMergePattern] = useState<"paren" | "plusminus" | "ci">("paren");
  const [spanFromId, setSpanFromId] = useState("");
  const [spanToId, setSpanToId] = useState("");
  const [spanLabel, setSpanLabel] = useState("");
  const [sparkFromId, setSparkFromId] = useState("");
  const [sparkToId, setSparkToId] = useState("");

  useEffect(() => {
    if (!doc) return;
    setLocalNum(doc.structure.tableNumber);
    setLocalTitle(doc.structure.title);
    setLocalSub(doc.structure.subtitle);
  }, [
    doc?.raw.snapshotId,
    doc?.structure.tableNumber,
    doc?.structure.title,
    doc?.structure.subtitle,
  ]);

  // Compute eligible low-cardinality text columns for `partBy` (§5.5 L310: cardinality <= 12)
  const eligiblePartColumns = useMemo(() => {
    if (!doc) return [];
    const body = sliceBodyRows(doc);
    return doc.structure.columns.filter((col) => {
      if (col.id === doc.structure.partBy) return true;
      if (col.source.kind !== "grid") return false;
      const stat = doc.raw.columnStats?.[col.source.col];
      if (stat && stat.numericRatio > 0.4) return false;
      const distinct = new Set<string>();
      for (const r of body) {
        const v = (r[col.source.col!] ?? "").trim();
        if (v) distinct.add(v);
      }
      return distinct.size >= 1 && distinct.size <= 12;
    });
  }, [doc]);

  // Distinct block names in appearance order when `partBy` is active
  const appearanceBlockNames = useMemo(() => {
    if (!doc || !doc.structure.partBy) return [];
    const partCol = doc.structure.columns.find((c) => c.id === doc.structure.partBy);
    if (!partCol || partCol.source.kind !== "grid") return [];
    const body = sliceBodyRows(doc);
    const seen: string[] = [];
    for (const r of body) {
      const v = (r[partCol.source.col] ?? "").trim();
      if (v && !seen.includes(v)) seen.push(v);
    }
    return seen;
  }, [doc]);

  if (!doc) return null;

  const { structure, raw } = doc;
  const visibleNonPartCols = structure.columns.filter(
    (c) => !c.hidden && c.id !== structure.partBy && c.role !== "part",
  );

  const ensureTidied = (draft: { structure: typeof structure }): void => {
    if (draft.structure.stage === "raw") {
      draft.structure.stage = "tidied";
    }
  };

  const moveColumn = (fromIdx: number, toIdx: number): void => {
    if (
      fromIdx === toIdx ||
      fromIdx < 0 ||
      toIdx < 0 ||
      fromIdx >= structure.columns.length ||
      toIdx >= structure.columns.length
    ) {
      return;
    }
    const movedName = structure.columns[fromIdx]?.label ?? "";
    commit((draft) => {
      ensureTidied(draft);
      const [item] = draft.structure.columns.splice(fromIdx, 1);
      draft.structure.columns.splice(toIdx, 0, item);
    });
    announce(`${movedName} → ${toIdx + 1}`);
  };

  const commitColRename = (colId: string): void => {
    const trimmed = editingColText.trim();
    setEditingColId(null);
    if (!trimmed) return;
    const existing = structure.columns.find((c) => c.id === colId);
    if (!existing || existing.label === trimmed) return;
    commit((draft) => {
      ensureTidied(draft);
      const target = draft.structure.columns.find((c) => c.id === colId);
      if (target) target.label = trimmed;
    });
  };

  const createSparklineFromCols = (srcIds: string[], label: string): void => {
    if (srcIds.length < 2) return;
    commit((draft) => {
      ensureTidied(draft);
      const drvId = `drv_spark_${Date.now()}`;
      const srcColSpecs = srcIds
        .map((sid) => draft.structure.columns.find((c) => c.id === sid))
        .filter((c): c is ColumnSpec => Boolean(c));
      if (srcColSpecs.length < 2) return;
      draft.structure.derived.push({
        id: drvId,
        kind: "sparkline",
        sourceIds: srcIds,
        sharedScale: false,
      });
      for (const sid of srcIds) {
        const cObj = draft.structure.columns.find((c) => c.id === sid);
        if (cObj) cObj.hidden = true;
      }
      draft.structure.columns.push(
        ...buildDerivedSparklineColumns(drvId, srcColSpecs, label),
      );
    });
  };

  const bodyPreviewLabels = sliceBodyRows(doc).slice(0, 12);

  return (
    <aside
      aria-label={t("tableStudio.a11y.structureRegion")}
      className="dq-elements-panel dq-table-structure-panel"
    >
      <div className="dq-table-structure-scroll">
        {/* 1. Titles */}
        <details className="dq-struct-sec" open>
          <summary className="dq-struct-sec__sum">
            <span>{t("tableStudio.structure.secTitles")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-struct-sec__body">
            <div className="dq-struct-field-row">
              <label className="dq-field-label dq-struct-short-lbl">
                <span>{t("tableStudio.structure.tableNumber")}</span>
                <input
                  type="text"
                  className="dq-input dq-input--compact"
                  value={localNum}
                  placeholder={t("tableStudio.canvas.editTableNumPlaceholder")}
                  onChange={(e) => setLocalNum(e.target.value)}
                  onBlur={() => {
                    if (localNum !== structure.tableNumber) {
                      commit((draft) => {
                        ensureTidied(draft);
                        draft.structure.tableNumber = localNum;
                      });
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                  }}
                />
              </label>
            </div>
            <label className="dq-field-label">
              <span>{t("tableStudio.structure.title")}</span>
              <input
                type="text"
                className="dq-input dq-input--compact"
                value={localTitle}
                placeholder={t("tableStudio.canvas.editTitlePlaceholder")}
                onChange={(e) => setLocalTitle(e.target.value)}
                onBlur={() => {
                  if (localTitle !== structure.title) {
                    commit((draft) => {
                      ensureTidied(draft);
                      draft.structure.title = localTitle;
                    });
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
              />
            </label>
            <label className="dq-field-label">
              <span>{t("tableStudio.structure.subtitle")}</span>
              <input
                type="text"
                className="dq-input dq-input--compact"
                value={localSub}
                placeholder={t("tableStudio.canvas.editSubtitlePlaceholder")}
                onChange={(e) => setLocalSub(e.target.value)}
                onBlur={() => {
                  if (localSub !== structure.subtitle) {
                    commit((draft) => {
                      ensureTidied(draft);
                      draft.structure.subtitle = localSub;
                    });
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
              />
            </label>
          </div>
        </details>

        {/* 2. Columns (Sortable Listbox) */}
        <details className="dq-struct-sec" open>
          <summary className="dq-struct-sec__sum">
            <span>{t("tableStudio.structure.secColumns")}</span>
            <span className="dq-struct-count">{structure.columns.length}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-struct-sec__body">
            <p className="dq-struct-hint">{t("tableStudio.structure.colListHint")}</p>
            <div
              role="listbox"
              aria-label={t("tableStudio.structure.secColumns")}
              className="dq-col-listbox"
            >
              {structure.columns.map((col, idx) => {
                const isSelected = selectedColId === col.id;
                const isDropTarget = dragOverColIdx === idx && dragColIdx !== idx;
                const enclosingSpanner = structure.spanners.find((sp) =>
                  sp.columnIds.includes(col.id),
                );
                const leadMerge = structure.merges.find(
                  (mg) => mg.columnIds[0] === col.id,
                );
                const secondaryMerge = structure.merges.find((mg) =>
                  mg.columnIds.slice(1).includes(col.id),
                );
                const curVisual: ColumnVisualMode =
                  col.visual ??
                  (col.role === "bar" ? "bar" : col.role === "heat" ? "auto" : "auto");
                const colStat =
                  col.source.kind === "grid" ? raw.columnStats?.[col.source.col] : undefined;
                const isTextOnlyCol = Boolean(colStat && colStat.numericRatio === 0);
                const showColRamp =
                  !secondaryMerge &&
                  !isTextOnlyCol &&
                  col.role !== "part" &&
                  (curVisual === "heat" ||
                    curVisual === "bar" ||
                    (doc.style.preset === "matrix_heatmap" && curVisual !== "plain"));
                return (
                  <div
                    key={col.id}
                    role="option"
                    aria-selected={isSelected}
                    tabIndex={0}
                    draggable={editingColId !== col.id}
                    className={`dq-col-item${col.hidden ? " dq-col-item--hidden" : ""}${
                      isDropTarget ? " dq-col-item--drop" : ""
                    }${secondaryMerge ? " dq-col-item--secondary" : ""}`}
                    onFocus={() => setSelectedColId(col.id)}
                    onClick={() => setSelectedColId(col.id)}
                    onKeyDown={(e) => {
                      if (e.altKey && e.key === "ArrowUp") {
                        e.preventDefault();
                        moveColumn(idx, idx - 1);
                      } else if (e.altKey && e.key === "ArrowDown") {
                        e.preventDefault();
                        moveColumn(idx, idx + 1);
                      }
                    }}
                    onDragStart={(e) => {
                      setDragColIdx(idx);
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", col.id);
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragOverColIdx(idx);
                    }}
                    onDragLeave={() => {
                      if (dragOverColIdx === idx) setDragOverColIdx(null);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (dragColIdx !== null && dragColIdx !== idx) {
                        moveColumn(dragColIdx, idx);
                      }
                      setDragColIdx(null);
                      setDragOverColIdx(null);
                    }}
                    onDragEnd={() => {
                      setDragColIdx(null);
                      setDragOverColIdx(null);
                    }}
                  >
                    <div className="dq-col-item__top">
                      <span
                        className="dq-drag-handle"
                        aria-label={t("tableStudio.structure.dragColHandle", { name: col.label })}
                        title={t("tableStudio.structure.dragColHandle", { name: col.label })}
                      >
                        <GripVertical size={13} strokeWidth={1.6} aria-hidden="true" />
                      </span>

                      <button
                        type="button"
                        className="dq-btn dq-btn--ghost dq-btn--icon dq-col-vis-btn"
                        aria-pressed={!col.hidden}
                        aria-label={t("tableStudio.structure.toggleColVis", { name: col.label })}
                        title={t("tableStudio.structure.toggleColVis", { name: col.label })}
                        onClick={(e) => {
                          e.stopPropagation();
                          commit((draft) => {
                            ensureTidied(draft);
                            const c = draft.structure.columns.find((x) => x.id === col.id);
                            if (c) c.hidden = !c.hidden;
                          });
                        }}
                      >
                        {col.hidden ? (
                          <EyeOff size={13} strokeWidth={1.6} aria-hidden="true" />
                        ) : (
                          <Eye size={13} strokeWidth={1.6} aria-hidden="true" />
                        )}
                      </button>

                      {editingColId === col.id ? (
                        <input
                          type="text"
                          className="dq-input dq-input--inline"
                          aria-label={t("tableStudio.colMenu.renameLabel")}
                          value={editingColText}
                          autoFocus
                          onChange={(e) => setEditingColText(e.target.value)}
                          onBlur={() => commitColRename(col.id)}
                          onKeyDown={(e) => {
                            e.stopPropagation();
                            if (e.key === "Enter") commitColRename(col.id);
                            if (e.key === "Escape") setEditingColId(null);
                          }}
                        />
                      ) : (
                        <span
                          className="dq-col-item__name"
                          title={t("elements.doubleClickRename")}
                          onDoubleClick={(e) => {
                            e.stopPropagation();
                            setEditingColId(col.id);
                            setEditingColText(col.label);
                          }}
                        >
                          {enclosingSpanner ? (
                            <span className="dq-col-spanner-prefix">
                              {`${enclosingSpanner.label} · `}
                            </span>
                          ) : null}
                          {col.label}
                        </span>
                      )}

                      {leadMerge ? (
                        <span className="dq-col-merged-badge">
                          {t("tableStudio.canvas.mergedBadge")}
                        </span>
                      ) : null}
                    </div>

                    {secondaryMerge ? (
                      <div className="dq-col-item__controls">
                        <span className="dq-col-secondary-note">
                          {t("tableStudio.canvas.mergedBadge")}
                        </span>
                        <select
                          className="dq-table-prec-select"
                          aria-label={t("tableStudio.colMenu.precisionLabel")}
                          value={String(col.precision)}
                          disabled={col.role === "sig" || col.role === "count"}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => {
                            const val = e.target.value;
                            const nextPrec: Precision =
                              val === "auto" ? "auto" : (Number(val) as 0 | 1 | 2 | 3);
                            commit((draft) => {
                              ensureTidied(draft);
                              const c = draft.structure.columns.find((x) => x.id === col.id);
                              if (c) c.precision = nextPrec;
                            });
                          }}
                        >
                          {PRECISIONS.map((p) => (
                            <option key={String(p)} value={String(p)}>
                              {p === "auto"
                                ? t("tableStudio.precisions.auto")
                                : t(`tableStudio.precisions.d${p}`)}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <>
                        <div className="dq-col-item__controls dq-col-item__controls--tri">
                          <select
                            className={`dq-table-role-select dq-table-role-select--${col.role}`}
                            aria-label={t("tableStudio.colMenu.roleLabel")}
                            value={
                              col.role === "heat" || col.role === "bar"
                                ? "normal"
                                : col.role
                            }
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              const nextRole = e.target.value as ColumnRole;
                              commit((draft) => {
                                ensureTidied(draft);
                                const c = draft.structure.columns.find((x) => x.id === col.id);
                                if (!c) return;
                                c.role = nextRole;
                                if (nextRole === "part") {
                                  draft.structure.partBy = col.id;
                                } else if (draft.structure.partBy === col.id) {
                                  draft.structure.partBy = null;
                                }
                                if (nextRole === "sig" && !draft.structure.sig.sourceId) {
                                  draft.structure.sig.sourceId = col.id;
                                  if (draft.structure.sig.targetIds.length === 0) {
                                    draft.structure.sig.targetIds = [col.id];
                                  }
                                }
                              });
                            }}
                          >
                            {SEMANTIC_ROLES.map((r) => (
                              <option key={r} value={r}>
                                {t(`tableStudio.roles.${r}`)}
                              </option>
                            ))}
                          </select>

                          <select
                            className={`dq-table-role-select${
                              curVisual === "heat" || curVisual === "bar"
                                ? " dq-table-role-select--heat"
                                : ""
                            }`}
                            aria-label={t("tableStudio.structure.colVisualAria", {
                              name: col.label,
                            })}
                            value={curVisual}
                            disabled={col.role === "part"}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              const nextVis = e.target.value as ColumnVisualMode;
                              commit((draft) => {
                                ensureTidied(draft);
                                if (
                                  (nextVis === "heat" || nextVis === "bar") &&
                                  draft.style.preset === "raw"
                                ) {
                                  draft.style.preset = "cns_three_line";
                                }
                                const c = draft.structure.columns.find((x) => x.id === col.id);
                                if (!c) return;
                                c.visual = nextVis;
                                if (nextVis === "plain" || nextVis === "auto") {
                                  if (c.role === "heat" || c.role === "bar") c.role = "normal";
                                } else if (nextVis === "heat") {
                                  if (c.role === "bar") c.role = "normal";
                                  if (
                                    !c.visualConfig?.direction &&
                                    inferColumnDirectionHint(c.label) === "reverse"
                                  ) {
                                    c.visualConfig = {
                                      ...(c.visualConfig ?? {}),
                                      direction: "reverse",
                                    };
                                  }
                                } else if (nextVis === "bar") {
                                  if (c.role === "heat") c.role = "normal";
                                }
                              });
                            }}
                          >
                            {VISUAL_MODES.map((vm) => (
                              <option key={vm} value={vm}>
                                {t(`tableStudio.visuals.${vm}`)}
                              </option>
                            ))}
                          </select>

                          <select
                            className="dq-table-prec-select"
                            aria-label={t("tableStudio.colMenu.precisionLabel")}
                            value={String(col.precision)}
                            disabled={col.role === "sig" || col.role === "count"}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              const val = e.target.value;
                              const nextPrec: Precision =
                                val === "auto" ? "auto" : (Number(val) as 0 | 1 | 2 | 3);
                              commit((draft) => {
                                ensureTidied(draft);
                                const c = draft.structure.columns.find((x) => x.id === col.id);
                                if (c) c.precision = nextPrec;
                              });
                            }}
                          >
                            {PRECISIONS.map((p) => (
                              <option key={String(p)} value={String(p)}>
                                {p === "auto"
                                  ? t("tableStudio.precisions.auto")
                                  : t(`tableStudio.precisions.d${p}`)}
                              </option>
                            ))}
                          </select>
                        </div>

                        {showColRamp ? (
                          <div className="dq-col-item__ramp-row">
                            <select
                              className="dq-table-role-select"
                              aria-label={t("tableStudio.structure.colRampAria", {
                                name: col.label,
                              })}
                              value={col.visualConfig?.paletteId ?? ""}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => {
                                const palId = e.target.value || undefined;
                                commit((draft) => {
                                  const c = draft.structure.columns.find(
                                    (x) => x.id === col.id,
                                  );
                                  if (!c) return;
                                  c.visualConfig = {
                                    ...(c.visualConfig ?? {}),
                                    paletteId: palId,
                                  };
                                });
                              }}
                            >
                              <option value="">
                                {t("tableStudio.colMenu.rampInherit")}
                              </option>
                              {BUILTIN_TABLE_RAMPS.map((r) => (
                                <option key={r.id} value={r.id}>
                                  {t(r.labelKey)}
                                </option>
                              ))}
                            </select>
                          </div>
                        ) : null}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </details>

        {/* 3. Grouping & Sort */}
        <details className="dq-struct-sec">
          <summary className="dq-struct-sec__sum">
            <span>{t("tableStudio.structure.secGrouping")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-struct-sec__body">
            <label className="dq-field-label">
              <span>{t("tableStudio.structure.blockBy")}</span>
              <select
                className="dq-select dq-select--compact"
                value={structure.partBy ?? ""}
                onChange={(e) => {
                  const val = e.target.value || null;
                  commit((draft) => {
                    ensureTidied(draft);
                    for (const c of draft.structure.columns) {
                      if (c.role === "part" && c.id !== val) c.role = "normal";
                      if (c.id === val) c.role = "part";
                    }
                    draft.structure.partBy = val;
                    draft.structure.partOrder = "appearance";
                  });
                }}
              >
                <option value="">{t("tableStudio.structure.none")}</option>
                {eligiblePartColumns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>

            {structure.partBy && appearanceBlockNames.length > 1 ? (
              <div className="dq-struct-subbox">
                <div className="dq-table-inline-field">
                  <span className="dq-field-label">{t("tableStudio.structure.blockOrder")}</span>
                  <div className="dq-inline-seg">
                    <button
                      type="button"
                      className="dq-btn dq-btn--xs"
                      aria-pressed={structure.partOrder === "appearance"}
                      onClick={() =>
                        commit((draft) => {
                          draft.structure.partOrder = "appearance";
                        })
                      }
                    >
                      {t("tableStudio.structure.orderAppearance")}
                    </button>
                    <button
                      type="button"
                      className="dq-btn dq-btn--xs"
                      aria-pressed={Array.isArray(structure.partOrder)}
                      onClick={() =>
                        commit((draft) => {
                          draft.structure.partOrder = [...appearanceBlockNames];
                        })
                      }
                    >
                      {t("tableStudio.structure.orderCustom")}
                    </button>
                  </div>
                </div>

                {Array.isArray(structure.partOrder) ? (
                  <div className="dq-mini-list">
                    {structure.partOrder.map((bName, bIdx) => (
                      <div key={bName} className="dq-mini-list__row">
                        <span className="dq-mini-list__text">{bName}</span>
                        <div className="dq-mini-list__btns">
                          <button
                            type="button"
                            className="dq-btn dq-btn--ghost dq-btn--icon"
                            disabled={bIdx === 0}
                            aria-label={t("tableStudio.structure.moveUp")}
                            title={t("tableStudio.structure.moveUp")}
                            onClick={() =>
                              commit((draft) => {
                                if (!Array.isArray(draft.structure.partOrder)) return;
                                const arr = [...draft.structure.partOrder];
                                [arr[bIdx - 1], arr[bIdx]] = [arr[bIdx], arr[bIdx - 1]];
                                draft.structure.partOrder = arr;
                              })
                            }
                          >
                            <ArrowUp size={12} strokeWidth={1.6} aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            className="dq-btn dq-btn--ghost dq-btn--icon"
                            disabled={bIdx === structure.partOrder.length - 1}
                            aria-label={t("tableStudio.structure.moveDown")}
                            title={t("tableStudio.structure.moveDown")}
                            onClick={() =>
                              commit((draft) => {
                                if (!Array.isArray(draft.structure.partOrder)) return;
                                const arr = [...draft.structure.partOrder];
                                [arr[bIdx], arr[bIdx + 1]] = [arr[bIdx + 1], arr[bIdx]];
                                draft.structure.partOrder = arr;
                              })
                            }
                          >
                            <ArrowDown size={12} strokeWidth={1.6} aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="dq-field-label">{t("tableStudio.structure.sortCol")}</div>
            <div className="dq-struct-inline-adder">
              <select
                className="dq-select dq-select--compact"
                aria-label={t("tableStudio.structure.sortCol")}
                value={structure.sort[0]?.columnId ?? ""}
                onChange={(e) => {
                  const cid = e.target.value;
                  commit((draft) => {
                    ensureTidied(draft);
                    draft.structure.sort = cid ? [{ columnId: cid, dir: "asc" }] : [];
                  });
                }}
              >
                <option value="">{t("tableStudio.structure.none")}</option>
                {visibleNonPartCols.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>

              {structure.sort[0] ? (
                <button
                  type="button"
                  className="dq-btn dq-btn--xs"
                  onClick={() =>
                    commit((draft) => {
                      const cur = draft.structure.sort[0];
                      if (cur) cur.dir = cur.dir === "asc" ? "desc" : "asc";
                    })
                  }
                >
                  {structure.sort[0].dir === "asc"
                    ? t("tableStudio.colMenu.sortAsc")
                    : t("tableStudio.colMenu.sortDesc")}
                </button>
              ) : null}
            </div>

            <label className="dq-check-row">
              <input
                type="checkbox"
                checked={structure.excludeSummaryRows !== false}
                onChange={(e) => {
                  const checked = e.target.checked;
                  commit((draft) => {
                    ensureTidied(draft);
                    draft.structure.excludeSummaryRows = checked;
                  });
                }}
              />
              <span>{t("tableStudio.structure.excludeSummaryRows")}</span>
            </label>

            {bodyPreviewLabels.length > 0 && !structure.pivot ? (
              <div className="dq-struct-subbox">
                <span className="dq-field-label">{t("tableStudio.structure.indentRows")}</span>
                <div className="dq-indent-pills">
                  {bodyPreviewLabels.map((rowArr, rIdx) => {
                    const rowName = (rowArr[0] ?? "").trim() || `#${rIdx + 1}`;
                    const indented = (structure.rowIndents[rIdx] ?? 0) === 1;
                    return (
                      <button
                        key={rIdx}
                        type="button"
                        className="dq-btn dq-btn--xs"
                        aria-pressed={indented}
                        title={t("tableStudio.structure.indentRowToggle", { row: rIdx + 1 })}
                        onClick={() =>
                          commit((draft) => {
                            ensureTidied(draft);
                            draft.structure.rowIndents[rIdx] = indented ? 0 : 1;
                          })
                        }
                      >
                        {rowName.slice(0, 14)}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </details>

        {/* 4. Combinations (Merges, Spanners, Sparklines, Pivot) */}
        <details className="dq-struct-sec">
          <summary className="dq-struct-sec__sum">
            <span>{t("tableStudio.structure.secCombos")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-struct-sec__body">
            {/* 4a. Merges */}
            <div className="dq-struct-subbox">
              <span className="dq-field-label">{t("tableStudio.structure.mergesTitle")}</span>
              {structure.merges.length === 0 ? (
                <p className="dq-struct-hint">{t("tableStudio.structure.noMerges")}</p>
              ) : (
                <div className="dq-mini-list">
                  {structure.merges.map((mg) => {
                    const names = mg.columnIds
                      .map((id) => structure.columns.find((c) => c.id === id)?.label ?? id)
                      .join(" + ");
                    return (
                      <div key={mg.id} className="dq-mini-list__row">
                        <span className="dq-mini-list__text">{names}</span>
                        <select
                          className="dq-table-prec-select"
                          aria-label={t("tableStudio.structure.mergesTitle")}
                          value={mg.pattern}
                          onChange={(e) => {
                            const pat = e.target.value as "paren" | "plusminus" | "ci";
                            commit((draft) => {
                              const item = draft.structure.merges.find((x) => x.id === mg.id);
                              if (item) item.pattern = pat;
                            });
                          }}
                        >
                          <option value="paren">{t("tableStudio.structure.fmtParen")}</option>
                          <option value="plusminus">
                            {t("tableStudio.structure.fmtPlusMinus")}
                          </option>
                          {mg.columnIds.length >= 3 ? (
                            <option value="ci">{t("tableStudio.structure.fmtCi")}</option>
                          ) : null}
                        </select>
                        <button
                          type="button"
                          className="dq-btn dq-btn--ghost dq-btn--icon"
                          aria-label={t("tableStudio.structure.removeItem")}
                          title={t("tableStudio.structure.removeItem")}
                          onClick={() =>
                            commit((draft) => {
                              draft.structure.merges = draft.structure.merges.filter(
                                (x) => x.id !== mg.id,
                              );
                            })
                          }
                        >
                          <Trash2 size={12} strokeWidth={1.6} aria-hidden="true" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              {visibleNonPartCols.length >= 2 ? (
                <div className="dq-struct-inline-adder">
                  <select
                    className="dq-select dq-select--compact"
                    aria-label={t("tableStudio.structure.fromCol")}
                    value={mergeFirstId || visibleNonPartCols[0]?.id || ""}
                    onChange={(e) => setMergeFirstId(e.target.value)}
                  >
                    {visibleNonPartCols.slice(0, -1).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                  <select
                    className="dq-table-prec-select"
                    aria-label={t("tableStudio.structure.mergesTitle")}
                    value={mergePattern}
                    onChange={(e) =>
                      setMergePattern(e.target.value as "paren" | "plusminus" | "ci")
                    }
                  >
                    <option value="paren">{t("tableStudio.structure.fmtParen")}</option>
                    <option value="plusminus">{t("tableStudio.structure.fmtPlusMinus")}</option>
                    <option value="ci">{t("tableStudio.structure.fmtCi")}</option>
                  </select>
                  <button
                    type="button"
                    className="dq-btn dq-btn--xs"
                    onClick={() => {
                      const firstId = mergeFirstId || visibleNonPartCols[0]?.id;
                      const startIdx = visibleNonPartCols.findIndex((c) => c.id === firstId);
                      if (startIdx < 0) return;
                      const count = mergePattern === "ci" ? 3 : 2;
                      const slice = visibleNonPartCols.slice(startIdx, startIdx + count);
                      if (slice.length < 2) return;
                      commit((draft) => {
                        ensureTidied(draft);
                        draft.structure.merges.push({
                          id: `mg_manual_${Date.now()}`,
                          columnIds: slice.map((s) => s.id),
                          pattern: slice.length === 3 ? mergePattern : mergePattern === "ci" ? "paren" : mergePattern,
                        });
                      });
                    }}
                  >
                    {t("tableStudio.structure.addMergeBtn")}
                  </button>
                </div>
              ) : null}
            </div>

            {/* 4b. Spanners */}
            <div className="dq-struct-subbox">
              <span className="dq-field-label">{t("tableStudio.structure.spannersTitle")}</span>
              {structure.spanners.length === 0 ? (
                <p className="dq-struct-hint">{t("tableStudio.structure.noSpanners")}</p>
              ) : (
                <div className="dq-mini-list">
                  {structure.spanners.map((sp) => (
                    <div key={sp.id} className="dq-mini-list__row">
                      <input
                        type="text"
                        className="dq-input dq-input--compact"
                        aria-label={t("tableStudio.structure.spannersTitle")}
                        value={sp.label}
                        onChange={(e) => {
                          const val = e.target.value;
                          commit((draft) => {
                            const target = draft.structure.spanners.find((x) => x.id === sp.id);
                            if (target) target.label = val;
                          });
                        }}
                      />
                      <button
                        type="button"
                        className="dq-btn dq-btn--ghost dq-btn--icon"
                        aria-label={t("tableStudio.structure.removeItem")}
                        title={t("tableStudio.structure.removeItem")}
                        onClick={() =>
                          commit((draft) => {
                            draft.structure.spanners = draft.structure.spanners.filter(
                              (x) => x.id !== sp.id,
                            );
                          })
                        }
                      >
                        <Trash2 size={12} strokeWidth={1.6} aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {visibleNonPartCols.length >= 2 ? (
                <div className="dq-struct-stack-adder">
                  <div className="dq-struct-inline-adder">
                    <select
                      className="dq-select dq-select--compact"
                      aria-label={t("tableStudio.structure.fromCol")}
                      value={spanFromId || visibleNonPartCols[0]?.id || ""}
                      onChange={(e) => setSpanFromId(e.target.value)}
                    >
                      {visibleNonPartCols.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                    <span>–</span>
                    <select
                      className="dq-select dq-select--compact"
                      aria-label={t("tableStudio.structure.toCol")}
                      value={spanToId || visibleNonPartCols[1]?.id || ""}
                      onChange={(e) => setSpanToId(e.target.value)}
                    >
                      {visibleNonPartCols.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="dq-struct-inline-adder">
                    <input
                      type="text"
                      className="dq-input dq-input--compact"
                      value={spanLabel}
                      placeholder={t("tableStudio.canvas.spannerPromptPlaceholder")}
                      onChange={(e) => setSpanLabel(e.target.value)}
                    />
                    <button
                      type="button"
                      className="dq-btn dq-btn--xs"
                      onClick={() => {
                        const a = visibleNonPartCols.findIndex(
                          (c) => c.id === (spanFromId || visibleNonPartCols[0]?.id),
                        );
                        const b = visibleNonPartCols.findIndex(
                          (c) => c.id === (spanToId || visibleNonPartCols[1]?.id),
                        );
                        if (a < 0 || b < 0) return;
                        const [lo, hi] = a <= b ? [a, b] : [b, a];
                        const ids = visibleNonPartCols.slice(lo, hi + 1).map((c) => c.id);
                        const lbl = spanLabel.trim() || "Group";
                        commit((draft) => {
                          ensureTidied(draft);
                          draft.structure.spanners.push({
                            id: `sp_manual_${Date.now()}`,
                            label: lbl,
                            columnIds: ids,
                          });
                        });
                        setSpanLabel("");
                      }}
                    >
                      {t("tableStudio.structure.addSpannerBtn")}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            {/* 4c. Sparklines */}
            <div className="dq-struct-subbox">
              <span className="dq-field-label">{t("tableStudio.structure.sparklinesTitle")}</span>
              {raw.suggestions.sparklineRuns.map((run, rIdx) => {
                const srcColIds = run.sourceCols
                  .map(
                    (sc) =>
                      structure.columns.find((c) => c.source.kind === "grid" && c.source.col === sc)
                        ?.id,
                  )
                  .filter((x): x is string => Boolean(x));
                const alreadyExists = structure.derived.some(
                  (d) =>
                    d.sourceIds.length === srcColIds.length &&
                    d.sourceIds[0] === srcColIds[0],
                );
                if (alreadyExists || srcColIds.length < 2) return null;
                return (
                  <button
                    key={rIdx}
                    type="button"
                    className="dq-btn dq-btn--xs"
                    onClick={() => createSparklineFromCols(srcColIds, run.label)}
                  >
                    <Plus size={12} strokeWidth={1.6} aria-hidden="true" />
                    <span>
                      {t("tableStudio.structure.createSparklineFromRun", { label: run.label })}
                    </span>
                  </button>
                );
              })}

              {structure.derived.length === 0 ? (
                <p className="dq-struct-hint">{t("tableStudio.structure.noSparklines")}</p>
              ) : (
                <div className="dq-mini-list">
                  {structure.derived.map((drv) => {
                    const drvCol = structure.columns.find(
                      (c) =>
                        c.source.kind === "derived" &&
                        c.source.derivedId === drv.id &&
                        (!c.source.metric || c.source.metric === "sparkline"),
                    );
                    const allHidden = drv.sourceIds.every(
                      (sid) => structure.columns.find((c) => c.id === sid)?.hidden,
                    );
                    return (
                      <div key={drv.id} className="dq-spark-item">
                        <div className="dq-mini-list__row">
                          <span className="dq-mini-list__text">
                            {drvCol?.label ?? drv.id} ({drv.sourceIds.length})
                          </span>
                          <button
                            type="button"
                            className="dq-btn dq-btn--ghost dq-btn--icon"
                            aria-label={t("tableStudio.structure.removeItem")}
                            title={t("tableStudio.structure.removeItem")}
                            onClick={() =>
                              commit((draft) => {
                                for (const sid of drv.sourceIds) {
                                  const sc = draft.structure.columns.find((c) => c.id === sid);
                                  if (sc) sc.hidden = false;
                                }
                                draft.structure.derived = draft.structure.derived.filter(
                                  (d) => d.id !== drv.id,
                                );
                                draft.structure.columns = draft.structure.columns.filter(
                                  (c) =>
                                    !(
                                      c.source.kind === "derived" &&
                                      c.source.derivedId === drv.id
                                    ),
                                );
                              })
                            }
                          >
                            <Trash2 size={12} strokeWidth={1.6} aria-hidden="true" />
                          </button>
                        </div>
                        <label className="dq-check-row dq-check-row--xs">
                          <input
                            type="checkbox"
                            checked={drv.sharedScale}
                            onChange={(e) =>
                              commit((draft) => {
                                const d = draft.structure.derived.find((x) => x.id === drv.id);
                                if (d) d.sharedScale = e.target.checked;
                              })
                            }
                          />
                          <span>{t("tableStudio.structure.sharedScale")}</span>
                        </label>
                        <label className="dq-check-row dq-check-row--xs">
                          <input
                            type="checkbox"
                            checked={allHidden}
                            onChange={(e) =>
                              commit((draft) => {
                                for (const sid of drv.sourceIds) {
                                  const sc = draft.structure.columns.find((c) => c.id === sid);
                                  if (sc) sc.hidden = e.target.checked;
                                }
                              })
                            }
                          />
                          <span>{t("tableStudio.structure.hideSources")}</span>
                        </label>
                      </div>
                    );
                  })}
                </div>
              )}

              {structure.columns.length >= 4 && !structure.pivot ? (
                <div className="dq-struct-inline-adder">
                  <select
                    className="dq-select dq-select--compact"
                    aria-label={t("tableStudio.structure.fromCol")}
                    value={sparkFromId || structure.columns[0]?.id || ""}
                    onChange={(e) => setSparkFromId(e.target.value)}
                  >
                    {structure.columns.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                  <span>–</span>
                  <select
                    className="dq-select dq-select--compact"
                    aria-label={t("tableStudio.structure.toCol")}
                    value={
                      sparkToId ||
                      structure.columns[structure.columns.length - 1]?.id ||
                      ""
                    }
                    onChange={(e) => setSparkToId(e.target.value)}
                  >
                    {structure.columns.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="dq-btn dq-btn--xs"
                    onClick={() => {
                      const a = structure.columns.findIndex(
                        (c) => c.id === (sparkFromId || structure.columns[0]?.id),
                      );
                      const b = structure.columns.findIndex(
                        (c) =>
                          c.id ===
                          (sparkToId ||
                            structure.columns[structure.columns.length - 1]?.id),
                      );
                      if (a < 0 || b < 0) return;
                      const [lo, hi] = a <= b ? [a, b] : [b, a];
                      const slice = structure.columns
                        .slice(lo, hi + 1)
                        .filter((c) => c.source.kind === "grid");
                      if (slice.length >= 2) {
                        createSparklineFromCols(
                          slice.map((c) => c.id),
                          `${slice[0].label}–${slice[slice.length - 1].label}`,
                        );
                      }
                    }}
                  >
                    {t("tableStudio.structure.createSparklineRange")}
                  </button>
                </div>
              ) : null}
            </div>

            {/* 4d. Pivot */}
            <div className="dq-struct-subbox">
              <span className="dq-field-label">{t("tableStudio.structure.pivotTitle")}</span>
              <label className="dq-check-row">
                <input
                  type="checkbox"
                  checked={Boolean(structure.pivot)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      if (raw.suggestions.pivot) {
                        const nextDoc = applySuggestionsToDoc(doc, "pivot", false);
                        commit((draft) => {
                          draft.structure = nextDoc.structure;
                        });
                      } else if ((raw.grid[0]?.length ?? 0) >= 3) {
                        const fallbackDoc: typeof doc = {
                          ...doc,
                          raw: {
                            ...raw,
                            suggestions: {
                              ...raw.suggestions,
                              pivot: { rowKey: 1, colKey: 0, valueCols: [2] },
                            },
                          },
                        };
                        const nextDoc = applySuggestionsToDoc(fallbackDoc, "pivot", false);
                        commit((draft) => {
                          draft.structure = nextDoc.structure;
                        });
                      }
                    } else {
                      // Restore unpivoted grid columns
                      const nCols = raw.grid[0]?.length ?? 0;
                      commit((draft) => {
                        ensureTidied(draft);
                        draft.structure.pivot = null;
                        draft.structure.spanners = [];
                        draft.structure.merges = [];
                        draft.structure.columns = Array.from(
                          { length: nCols },
                          (_, idx): ColumnSpec => ({
                            id: `c${idx}`,
                            source: { kind: "grid", col: idx },
                            label:
                              raw.suggestions.resolvedHeaders?.[idx] ||
                              raw.grid[draft.structure.headerRows[0]]?.[idx] ||
                              `Col ${idx + 1}`,
                            hidden: false,
                            role: raw.suggestions.roles[idx] ?? "normal",
                            precision: "auto",
                            unit: raw.columnStats?.[idx]?.detectedUnit ?? "",
                          }),
                        );
                      });
                    }
                  }}
                />
                <span>{t("tableStudio.structure.enablePivot")}</span>
              </label>
            </div>
          </div>
        </details>

        {/* 5. Footnotes */}
        <details className="dq-struct-sec">
          <summary className="dq-struct-sec__sum">
            <span>{t("tableStudio.structure.secFootnotes")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-struct-sec__body">
            {structure.footnotes.length === 0 ? (
              <p className="dq-struct-hint">{t("tableStudio.structure.noFootnotes")}</p>
            ) : (
              <div className="dq-mini-list">
                {structure.footnotes.map((fn) => (
                  <div key={fn.id} className="dq-fn-edit-card">
                    <div className="dq-struct-inline-adder">
                      <input
                        type="text"
                        className="dq-input dq-input--sym"
                        aria-label={t("tableStudio.canvas.editFootnoteSymbol")}
                        value={fn.symbol}
                        onChange={(e) => {
                          const sym = e.target.value;
                          commit((draft) => {
                            const f = draft.structure.footnotes.find((x) => x.id === fn.id);
                            if (f) f.symbol = sym;
                          });
                        }}
                      />
                      <select
                        className="dq-select dq-select--compact"
                        aria-label={t("tableStudio.structure.anchorCol")}
                        value={fn.anchorColumnIds[0] ?? ""}
                        onChange={(e) => {
                          const cid = e.target.value;
                          commit((draft) => {
                            const f = draft.structure.footnotes.find((x) => x.id === fn.id);
                            if (f) f.anchorColumnIds = cid ? [cid] : [];
                          });
                        }}
                      >
                        <option value="">{t("tableStudio.structure.noAnchor")}</option>
                        {visibleNonPartCols.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="dq-btn dq-btn--ghost dq-btn--icon"
                        aria-label={t("tableStudio.structure.removeItem")}
                        title={t("tableStudio.structure.removeItem")}
                        onClick={() =>
                          commit((draft) => {
                            draft.structure.footnotes = draft.structure.footnotes.filter(
                              (x) => x.id !== fn.id,
                            );
                          })
                        }
                      >
                        <Trash2 size={12} strokeWidth={1.6} aria-hidden="true" />
                      </button>
                    </div>
                    <input
                      type="text"
                      className="dq-input dq-input--compact"
                      aria-label={t("tableStudio.canvas.editFootnoteText")}
                      value={fn.text}
                      onChange={(e) => {
                        const txt = e.target.value;
                        commit((draft) => {
                          const f = draft.structure.footnotes.find((x) => x.id === fn.id);
                          if (f) f.text = txt;
                        });
                      }}
                    />
                  </div>
                ))}
              </div>
            )}

            <button
              type="button"
              className="dq-btn dq-btn--xs"
              onClick={() =>
                commit((draft) => {
                  ensureTidied(draft);
                  const nextIdx = draft.structure.footnotes.length;
                  const sym = String.fromCharCode(97 + (nextIdx % 26));
                  draft.structure.footnotes.push({
                    id: `fn_${Date.now()}`,
                    symbol: sym,
                    text: "",
                    anchorColumnIds: [],
                  });
                })
              }
            >
              <Plus size={12} strokeWidth={1.6} aria-hidden="true" />
              <span>{t("tableStudio.canvas.addFootnote")}</span>
            </button>

            {structure.sig.sourceId && structure.sig.stars ? (
              <div className="dq-fn-readonly-legend">{t("tableStudio.sig.legend")}</div>
            ) : null}
          </div>
        </details>

        {/* 6. Significance & Missing Values */}
        <details className="dq-struct-sec">
          <summary className="dq-struct-sec__sum">
            <span>{t("tableStudio.structure.secSig")}</span>
            <ChevronDown size={14} strokeWidth={1.6} className="dq-acc-chevron" aria-hidden="true" />
          </summary>
          <div className="dq-struct-sec__body">
            <label className="dq-field-label">
              <span>{t("tableStudio.structure.sigSource")}</span>
              <select
                className="dq-select dq-select--compact"
                value={structure.sig.sourceId ?? ""}
                onChange={(e) => {
                  const sid = e.target.value || null;
                  commit((draft) => {
                    ensureTidied(draft);
                    draft.structure.sig.sourceId = sid;
                    if (sid) {
                      const c = draft.structure.columns.find((x) => x.id === sid);
                      if (c) c.role = "sig";
                      if (draft.structure.sig.targetIds.length === 0) {
                        draft.structure.sig.targetIds = [sid];
                      }
                    }
                  });
                }}
              >
                <option value="">{t("tableStudio.structure.none")}</option>
                {structure.columns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>

            {structure.sig.sourceId ? (
              <>
                <label className="dq-field-label">
                  <span>{t("tableStudio.structure.pStyle")}</span>
                  <select
                    className="dq-select dq-select--compact"
                    value={structure.sig.pStyle}
                    onChange={(e) => {
                      const ps = e.target.value as PStyle;
                      commit((draft) => {
                        draft.structure.sig.pStyle = ps;
                      });
                    }}
                  >
                    <option value="nejm">{t("tableStudio.structure.pStyleNejm")}</option>
                    <option value="apa">{t("tableStudio.structure.pStyleApa")}</option>
                    <option value="exact">{t("tableStudio.structure.pStyleExact")}</option>
                  </select>
                </label>

                <label className="dq-check-row">
                  <input
                    type="checkbox"
                    checked={structure.sig.stars}
                    onChange={(e) =>
                      commit((draft) => {
                        draft.structure.sig.stars = e.target.checked;
                      })
                    }
                  />
                  <span>{t("tableStudio.structure.showStars")}</span>
                </label>

                <div className="dq-field-label">{t("tableStudio.structure.sigTargets")}</div>
                <div className="dq-target-checks">
                  {visibleNonPartCols.map((c) => {
                    const checked = structure.sig.targetIds.includes(c.id);
                    return (
                      <label key={c.id} className="dq-check-row dq-check-row--xs">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) =>
                            commit((draft) => {
                              const setIds = new Set(draft.structure.sig.targetIds);
                              if (e.target.checked) setIds.add(c.id);
                              else setIds.delete(c.id);
                              draft.structure.sig.targetIds = Array.from(setIds);
                            })
                          }
                        />
                        <span>{c.label}</span>
                      </label>
                    );
                  })}
                </div>
              </>
            ) : null}

            <div className="dq-field-label">{t("tableStudio.structure.missingLabel")}</div>
            <div className="dq-inline-seg">
              {(["—", "NA", ""] as const).map((tok) => (
                <button
                  key={tok || "blank"}
                  type="button"
                  className="dq-btn dq-btn--xs"
                  aria-pressed={structure.missingToken === tok}
                  onClick={() =>
                    commit((draft) => {
                      ensureTidied(draft);
                      draft.structure.missingToken = tok;
                    })
                  }
                >
                  {tok === "—"
                    ? t("tableStudio.structure.missingDash")
                    : tok === "NA"
                      ? t("tableStudio.structure.missingNa")
                      : t("tableStudio.structure.missingBlank")}
                </button>
              ))}
            </div>
          </div>
        </details>
      </div>

      <div role="status" aria-live="polite" className="visually-hidden">
        {useTableStudioStore((s) => s.liveAnnouncement)}
      </div>
    </aside>
  );
}
