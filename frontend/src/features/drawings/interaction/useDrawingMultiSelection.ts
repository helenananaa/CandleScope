import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import type { DrawingCommand } from "../core/drawingCommands.js";
import type { DrawingDocument } from "../core/drawingDocument.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import type { SavedDrawing, ScreenBox, ScreenPoint } from "../drawingTypes.js";
import { copyDrawingSelection, pastedDrawings, readDrawingClipboard } from "./drawingClipboard.js";
import {
  groupMoveDescriptor,
  groupMoveDrafts,
  snappedGroupDelta,
  type GroupMoveContext,
  type GroupMoveMember,
} from "./drawingGroupMove.js";
import {
  deleteSelectionCommands,
  drawingSelection,
  EMPTY_DRAWING_SELECTION,
  groupSelectionCommands,
  selectAllDrawings,
  selectionAfterClick,
  selectionIsGrouped,
  ungroupSelectionCommands,
  type DrawingSelection,
} from "./drawingMultiSelection.js";
import type { DynamicOverlayDecoration } from "./dynamicOverlayController.js";
import { hasOpenOverlay } from "../../../components/ui/overlay/overlayRuntime.js";

/** What the controller lends the multi-selection; read fresh on every use. */
export interface DrawingMultiSelectionDeps {
  readonly enabled: boolean;
  readonly interval: string;
  getDocument(): DrawingDocument;
  getSavedDrawing(id: string): SavedDrawing | null;
  selectPrimitive(id: string): void;
  deselectAll(): void;
  prepareMutation(): boolean;
  persist(commands: readonly DrawingCommand[]): { readonly committed: boolean } | null;
  moveContext(): GroupMoveContext;
  snapEnabled(): boolean;
  invalidateScene(): void;
  requestRender(): void;
  getScreenBox(id: string): ScreenBox | null;
  draftDecorations(saved: SavedDrawing): readonly DynamicOverlayDecoration[];
  isTextEditing(): boolean;
  selectionColor: string;
}

interface GroupDrag {
  readonly primary: SavedDrawing;
  readonly members: readonly GroupMoveMember[];
  readonly startMouse: ScreenPoint;
  drafts: readonly SavedDrawing[] | null;
}

export interface DrawingMultiSelectionView {
  readonly count: number;
  readonly grouped: boolean;
}

/** Pasting onto the chart the copy came from offsets it so both stay visible. */
const PASTE_OFFSET_PX = 16;
const MAX_HANDOFF_FRAMES = 2;

/** The chart the user last pressed in owns the shortcuts, like the undo bar. */
let activeOwner: object | null = null;

function editableTarget(target: EventTarget | null): boolean {
  return target instanceof Element
    && !!target.closest('dialog, input, textarea, select, [contenteditable="true"], [role="dialog"]');
}

/**
 * Multi-select, groups, moving several drawings together, copy/paste and
 * their shortcuts (PL-4). Every change is one command batch on the canonical
 * document, so undo/redo restores it in one step.
 */
export function useDrawingMultiSelection(depsRef: MutableRefObject<DrawingMultiSelectionDeps>, keyboardActive: boolean) {
  const selectionRef = useRef<DrawingSelection>(EMPTY_DRAWING_SELECTION);
  const [view, setView] = useState<DrawingMultiSelectionView>({ count: 0, grouped: false });
  const groupDragRef = useRef<GroupDrag | null>(null);
  const handoffRef = useRef<readonly SavedDrawing[] | null>(null);
  /** Members detached from the static scene while the group drag paints them. */
  const companionIdsRef = useRef<ReadonlySet<string>>(new Set());
  const ownerRef = useRef<object>({});

  const markActive = useCallback(() => { activeOwner = ownerRef.current; }, []);
  useEffect(() => {
    const owner = ownerRef.current;
    return () => { if (activeOwner === owner) activeOwner = null; };
  }, []);

  const publish = useCallback((selection: DrawingSelection) => {
    selectionRef.current = selection;
    const deps = depsRef.current;
    setView((current) => {
      const next = { count: selection.ids.length, grouped: selection.ids.length > 0 && selectionIsGrouped(deps.getDocument(), selection) };
      return current.count === next.count && current.grouped === next.grouped ? current : next;
    });
    deps.requestRender();
  }, [depsRef]);

  const clear = useCallback(() => {
    if (selectionRef.current.ids.length === 0) return;
    publish(EMPTY_DRAWING_SELECTION);
  }, [publish]);

  /** Keep the set in step when the controller selects one drawing some other way. */
  const syncPrimary = useCallback((id: string | null) => {
    const current = selectionRef.current;
    if (id === null) {
      if (groupDragRef.current === null) clear();
      return;
    }
    if (current.ids.includes(id)) {
      if (current.primary !== id) publish(Object.freeze({ ...current, primary: id }));
      return;
    }
    publish(drawingSelection(depsRef.current.getDocument(), id, [id]));
  }, [clear, depsRef, publish]);

  const applySelection = useCallback((selection: DrawingSelection) => {
    const deps = depsRef.current;
    publish(selection);
    if (selection.primary) deps.selectPrimitive(selection.primary);
    else deps.deselectAll();
  }, [depsRef, publish]);

  const releaseCompanions = useCallback(() => {
    if (companionIdsRef.current.size === 0) return;
    companionIdsRef.current = new Set();
    depsRef.current.invalidateScene();
  }, [depsRef]);

  /** Pointer down on a drawing. True when the multi-selection handled it. */
  const pointerDown = useCallback((hitId: string, pos: ScreenPoint, toggle: boolean, bodyHit: boolean): boolean => {
    const deps = depsRef.current;
    if (!deps.enabled) return false;
    const document = deps.getDocument();
    const next = selectionAfterClick(document, selectionRef.current, hitId, toggle);
    if (toggle) {
      applySelection(next);
      return true;
    }
    // One drawing, or a handle press: the controller's own select/drag/resize
    // path runs, and the set stays shown around it.
    if (next.ids.length <= 1 || !bodyHit) {
      publish(next);
      return false;
    }
    applySelection(next);
    const context = deps.moveContext();
    const members: GroupMoveMember[] = [];
    for (const id of next.ids) {
      const original = deps.getSavedDrawing(id);
      const descriptor = original ? groupMoveDescriptor(original, pos, context) : null;
      // A locked or unmovable member keeps the whole selection in place.
      if (!original || !descriptor) return true;
      members.push({ original, descriptor });
    }
    const primary = members.find((member) => member.original.id === hitId)?.original;
    if (!primary) return true;
    groupDragRef.current = { primary, members, startMouse: pos, drafts: null };
    companionIdsRef.current = new Set(next.ids);
    deps.invalidateScene();
    deps.requestRender();
    return true;
  }, [applySelection, depsRef, publish]);

  const pointerMove = useCallback((pos: ScreenPoint, disableSnap: boolean): boolean => {
    const drag = groupDragRef.current;
    if (!drag) return false;
    const deps = depsRef.current;
    const context = deps.moveContext();
    const raw = { dx: pos.x - drag.startMouse.x, dy: pos.y - drag.startMouse.y };
    const delta = snappedGroupDelta(drag.primary, raw, context, deps.snapEnabled() && !disableSnap);
    const drafts = groupMoveDrafts(drag.members, delta, context);
    if (drafts) drag.drafts = drafts;
    deps.requestRender();
    return true;
  }, [depsRef]);

  const pointerUp = useCallback((): boolean => {
    const drag = groupDragRef.current;
    if (!drag) return false;
    groupDragRef.current = null;
    const deps = depsRef.current;
    const commands = drag.drafts?.flatMap((draft) => drawingCommandsForSavedDrawing(draft, { type: "update", geometryCommand: "move" }) ?? []) ?? [];
    const committed = commands.length > 0 && drag.drafts !== null
      && commands.length >= drag.drafts.length && deps.prepareMutation()
      && deps.persist(commands)?.committed === true;
    if (committed && drag.drafts) {
      // Keep the moved drafts on the dynamic canvas until the static scene
      // has repainted with the committed geometry.
      handoffRef.current = drag.drafts;
      let frames = 0;
      const step = () => {
        frames += 1;
        if (frames < MAX_HANDOFF_FRAMES) {
          requestAnimationFrame(step);
          return;
        }
        handoffRef.current = null;
        depsRef.current.requestRender();
      };
      requestAnimationFrame(step);
    }
    releaseCompanions();
    deps.requestRender();
    return true;
  }, [depsRef, releaseCompanions]);

  const cancelDrag = useCallback((): boolean => {
    if (!groupDragRef.current) return false;
    groupDragRef.current = null;
    releaseCompanions();
    depsRef.current.requestRender();
    return true;
  }, [depsRef, releaseCompanions]);

  const commit = useCallback((commands: readonly DrawingCommand[] | null): boolean => {
    const deps = depsRef.current;
    if (!deps.enabled || !commands || commands.length === 0 || !deps.prepareMutation()) return false;
    return deps.persist(commands)?.committed === true;
  }, [depsRef]);

  const group = useCallback((): boolean => {
    const deps = depsRef.current;
    const done = commit(groupSelectionCommands(deps.getDocument(), selectionRef.current));
    if (done) publish(drawingSelection(deps.getDocument(), selectionRef.current.primary, selectionRef.current.ids));
    return done;
  }, [commit, depsRef, publish]);

  const ungroup = useCallback((): boolean => {
    const deps = depsRef.current;
    const done = commit(ungroupSelectionCommands(deps.getDocument(), selectionRef.current));
    if (done) publish(drawingSelection(deps.getDocument(), selectionRef.current.primary, selectionRef.current.ids));
    return done;
  }, [commit, depsRef, publish]);

  /** Deletes a multi-selection in one step; false leaves single deletes to the controller. */
  const deleteSelection = useCallback((): boolean => {
    const deps = depsRef.current;
    if (selectionRef.current.ids.length < 2) return false;
    if (commit(deleteSelectionCommands(deps.getDocument(), selectionRef.current))) {
      publish(EMPTY_DRAWING_SELECTION);
      deps.deselectAll();
    }
    return true;
  }, [commit, depsRef, publish]);

  const selectAll = useCallback((): boolean => {
    const deps = depsRef.current;
    if (!deps.enabled) return false;
    const selection = selectAllDrawings(deps.getDocument(), deps.interval);
    if (selection.ids.length === 0) return false;
    applySelection(selection);
    return true;
  }, [applySelection, depsRef]);

  const copy = useCallback((): number => {
    const deps = depsRef.current;
    if (!deps.enabled || selectionRef.current.ids.length === 0) return 0;
    return copyDrawingSelection(deps.getDocument(), selectionRef.current);
  }, [depsRef]);

  const paste = useCallback((): boolean => {
    const deps = depsRef.current;
    const clipboard = readDrawingClipboard();
    if (!deps.enabled || !clipboard) return false;
    const document = deps.getDocument();
    const offset = clipboard.sourceScope === document.scopeKey ? PASTE_OFFSET_PX : 0;
    const context = deps.moveContext();
    const created = pastedDrawings(clipboard, (drawing) => {
      if (offset === 0) return drawing;
      const temporary = { ...drawing, id: "__paste__" } as SavedDrawing;
      const descriptor = groupMoveDescriptor(temporary, { x: 0, y: 0 }, context);
      // Drawings that cannot be offset (none in practice) keep their anchors.
      const moved = descriptor ? groupMoveDrafts([{ original: temporary, descriptor }], { dx: offset, dy: offset }, context)?.[0] : null;
      return moved ?? drawing;
    });
    if (!created || created.length === 0) return false;
    const commands = created.flatMap((drawing) => drawingCommandsForSavedDrawing(drawing, { type: "create" }) ?? []);
    if (commands.length !== created.length || !commit(commands)) return false;
    const ids = created.map((drawing) => drawing.id!);
    applySelection(drawingSelection(deps.getDocument(), ids.at(-1) ?? null, ids));
    return true;
  }, [applySelection, commit, depsRef]);

  const duplicate = useCallback((): boolean => copy() > 0 && paste(), [copy, paste]);

  /** Extra decorations for the dynamic canvas: moved drafts and the other selected drawings' boxes. */
  const decorations = useCallback((): readonly DynamicOverlayDecoration[] => {
    const deps = depsRef.current;
    const result: DynamicOverlayDecoration[] = [];
    const drafts = groupDragRef.current
      ? groupDragRef.current.drafts ?? groupDragRef.current.members.map((member) => member.original)
      : handoffRef.current;
    if (drafts) for (const draft of drafts) result.push(...deps.draftDecorations(draft));
    const selection = selectionRef.current;
    if (selection.ids.length > 1 && !groupDragRef.current) {
      for (const id of selection.ids) {
        const box = deps.getScreenBox(id);
        if (!box || !Number.isFinite(box.width) || !Number.isFinite(box.height)) continue;
        result.push(Object.freeze({
          type: "box" as const,
          box: Object.freeze({ x: box.x - 4, y: box.y - 4, width: box.width + 8, height: box.height + 8 }),
          color: deps.selectionColor,
          dashed: true,
        }));
      }
    }
    return result;
  }, [depsRef]);

  const isCompanion = useCallback((id: string) => companionIdsRef.current.has(id), []);

  // Shortcuts on the active chart: ⌘/Ctrl + A, G, ⇧G, C, V, D.
  useEffect(() => {
    if (!keyboardActive) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      const deps = depsRef.current;
      if (activeOwner !== ownerRef.current || !deps.enabled || event.defaultPrevented || !(event.metaKey || event.ctrlKey)
        || event.altKey || deps.isTextEditing() || editableTarget(event.target) || hasOpenOverlay()) return;
      const key = event.key.toLowerCase();
      const hasSelection = selectionRef.current.ids.length > 0;
      let handled = false;
      if (key === "a" && !event.shiftKey && hasSelection) handled = selectAll();
      else if (key === "g" && !event.shiftKey && selectionRef.current.ids.length > 1) handled = group();
      else if (key === "g" && event.shiftKey && hasSelection) handled = ungroup();
      else if (key === "c" && !event.shiftKey && hasSelection) handled = copy() > 0;
      else if (key === "v" && !event.shiftKey && readDrawingClipboard() !== null) handled = paste();
      else if (key === "d" && !event.shiftKey && hasSelection) handled = duplicate();
      if (handled) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [keyboardActive, copy, depsRef, duplicate, group, paste, selectAll, ungroup]);

  return useMemo(() => ({
    view,
    selectionRef,
    companionIdsRef,
    isCompanion,
    markActive,
    syncPrimary,
    clear,
    pointerDown,
    pointerMove,
    pointerUp,
    cancelDrag,
    isDragging: () => groupDragRef.current !== null,
    deleteSelection,
    selectAll,
    group,
    ungroup,
    copy,
    paste,
    duplicate,
    decorations,
  }), [cancelDrag, clear, copy, decorations, deleteSelection, duplicate, group, isCompanion, markActive, paste, pointerDown, pointerMove, pointerUp, selectAll, syncPrimary, ungroup, view]);
}

export type DrawingMultiSelectionRuntime = ReturnType<typeof useDrawingMultiSelection>;
