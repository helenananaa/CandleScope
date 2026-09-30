# Drawings Feature

`features/drawings` owns native chart drawing tools, drawing selection, interaction state, persistence, and export-time drawing preparation.

## Public Contract

`useDrawingRuntime({ chartSurfaceActions, drawingScopeBase?, session })` exposes:

```ts
{
  view: {
    drawingTool,
    penColor,
    penSize,
    textFontSize,
    textBold,
    textItalic,
    fibLevels,
    fibInverted,
    positionSize,
    drawingsHidden,
    drawingSnapEnabled,
    drawingContinuousEnabled,
    selectedDrawing,
  },
  actions: {
    setDrawingTool,
    setPenColor,
    setPenSize,
    setTextFontSize,
    setTextBold,
    setTextItalic,
    handleClearDrawing,
    handleToggleDrawingsHidden,
    handleDrawingSnapEnabledChange,
    handleDrawingContinuousEnabledChange,
    handleSelectedDrawingChange,
    handleSelectedDrawingStyleChange,
    prepareExport,
    exportInstrumentation,
    handleIndicatorRemoved,
  },
  status: {},
}
```

The hook returns only `view`, `actions`, and `status`; callers must not depend
on legacy flat fields.

## Internal Ownership

- `drawingModel.ts` owns tool ids, drawing constants, id creation, and pure geometry helpers.
- `drawingToolState.ts` owns toolbar-facing defaults and the active selection snapshot.
- `SelectedDrawingStyleBar.tsx` owns the chart-local controls for the selected
  drawing. Its patches target only that drawing; toolbar color and width remain
  defaults for newly created drawings. Text keeps its inline format bar.
- `DrawingStyleInputs.tsx` owns shared color, width and shape line-style controls.
  `useDrawingEditorLayout.ts` clamps the draggable toolbar within its chart and
  anchors native top-layer dialogs/popovers within the viewport. Toolbar positions
  are container-local UI state; detailed settings stay in a draft until saved
  through the existing drawing style command path.
- `core/drawingDocument.ts` owns the immutable nine-kind business model and
  independent document, geometry, and style revisions.
- `core/drawingCommands.ts` and `core/drawingDocumentStore.ts` are the only
  committed mutation/publication path. Completed controller actions carry the
  complete canonical payload required by create, delete, move, resize,
  update-style, clear, or reorder; unrelated primitive drift rejects the whole
  transaction and can never supply missing command data.
- `core/drawingCodec.ts` owns fail-closed conversion between the canonical
  document and the unchanged legacy `SavedDrawing[]` wire contract.
- `persistence/drawingDocumentRepository.ts` owns the canonical scope-keyed
  IndexedDB record, manifest validation, bounded encode/decode, and v2-first
  load policy. `drawingPersistenceCoordinator.ts` owns debounced single-flight
  writes, latest-pending retry, lifecycle flushes, and compatible snapshot
  refresh. `legacyDrawingImporter.ts` is the bounded legacy import/export
  boundary; it does not become a second source of truth.
- `drawingPersistence.ts` retains the validated `SavedDrawing[]` compatibility
  codec/storage helpers used by rollback builds and import tests.
- `useDrawingPersistenceLifecycle.ts` owns command commit, dirty-session retry,
  document repository coordination, renderer compensation, restore/rebind,
  surface credentials, export preparation, and retryable symbol/scope
  isolation. User mutations remain blocked until the requested symbol, active
  store, and current chart surface agree.
- `drawingScopePersistence.ts` clears removed pane/indicator scopes through the
  document session registry, including retryable empty storage tombstones.
- `engine/` owns revision-stamped scene scheduling, canonical scene projection,
  registry publication, shadow parity, and latest-frame runtime coordination.
- `rendering/` owns the clipped display list, the single visible
  `DrawingScenePrimitive`, kind-specific Canvas painters, and the dynamic
  interaction overlay. Final Lightweight Charts-bound projection stays on the
  main-thread adapter boundary.
- `geometry/` owns canonical bounds, pixel-budget LOD, and the spatial hit
  index. `worker/` may process typed, clipped/LOD display-list jobs with
  latest-wins backpressure; it must not import chart-adapter or reproduce
  Lightweight Charts coordinate logic.
- `interaction/` owns document-native create, drag, hit, text-edit, live-ink,
  and dynamic-overlay behavior. The top-level pointer, selection, erase,
  keyboard, snap, and interaction controllers coordinate those operations with
  the chart adapter.
- `export/` owns the exact-revision render/persistence barrier, hidden-scene
  lifecycle, post-capture revalidation, and fail-closed export readiness.
- `DrawingEngineHost.tsx` mounts the mode-locked document/scene/legacy owner,
  interaction controller, overlay canvases, and text editing surfaces.
- `legacy/`, `primitives/`, and `drawingPrimitiveFactory.ts` are retained only
  for the current legacy renderer, rollback builds, and compatibility probes.
  They are not persistent business truth and must not be extended as the V2
  rendering path.
- `performance/` owns drawing-local counters and runtime evidence used by the
  performance, soak, and rollback gates.

## Allowed Dependencies

- May consume chart session through the runtime argument to derive drawing storage keys for drawing-owned cleanup.
- May expose event-style actions, such as `handleIndicatorRemoved`, so the app
  composition root can route lifecycle events without knowing drawing storage keys.
- May depend on explicit `chart-adapter` surface actions passed by the app
  composition root.
- May use legacy primitive implementations only inside the documented rollback
  renderer and compatibility probes; new visible rendering belongs in the
  scene/display-list path.
- May expose feature UI entry points such as `DrawingToolbar` and `DrawingEngineHost`.

## Forbidden Dependencies

- Do not load K-line data, indicators, watchlist, settings, or export options here.
- Do not import App internals or sibling feature internals.
- Do not expose raw Lightweight Charts refs or series instances from the public runtime contract.
- Do not let generic UI components own IndexedDB, legacy snapshot, or drawing
  persistence policy.
- Do not let drawing workers import `chart-adapter`/Lightweight Charts or
  duplicate time/price projection internals.

## Migration Notes

Phase 11 removed the old `src/hooks` and `src/runtime/workflows` drawing wrappers.
`src/services/drawingStorage.ts` remains a compatibility re-export; storage
policy stays inside this feature.

Drawing Engine V2 Phases 0-8 and the local Phase 9 rollback drills are complete.
The canonical document, batch coordinate projector, visible `scene-canary`
renderer, `overlay` interaction surface, and worker raster backend are now the
repository release defaults. Full `scene` remains fail-closed until production
cohorts, observation windows, the one-hour soak, and migration-loss audit pass.

Set `VITE_DRAWING_DOCUMENT_AUTHORITY=legacy`,
`VITE_DRAWING_COORDINATE_PROJECTOR=scalar`,
`VITE_DRAWING_ENGINE_MODE=legacy`,
`VITE_DRAWING_INTERACTION_OVERLAY=legacy`, or
`VITE_DRAWING_RASTER_BACKEND=main-thread` only as scoped emergency rollback
controls. V2
IndexedDB writes continue refreshing the bounded legacy-compatible
`SavedDrawing[]` snapshot; no rollback path may delete user data. Legacy
primitives and their factory remain until the Phase 9 deletion conditions are
satisfied.

Text annotation formatting shares the selected-object toolbar and top-layer draft dialog. Drawing document stores keep a bounded, session-only undo/redo history (50 committed batches). History replay uses the existing scene persistence barrier and monotonic revisions; it does not load an old persisted document. Native-pane history buttons and keyboard ownership are handled by `DrawingHistoryBar`; legacy primitive mode does not advertise history.

The selected-object properties dialog supports precise price/time endpoints for ordinary time-anchored line/shape/Fibonacci/angle/axis objects. `drawingProperties.ts` validates the supported anchor forms and prepares an immutable candidate; the interaction controller commits combined geometry and style as one undoable batch. The coordinate UI uses explicit UTC and refuses to reinterpret source-lineage or legacy logical anchors.

`drawingStyleTemplateStore.ts` owns versioned, device-local reusable style preferences. `DrawingStyleTemplates` only copies compatible whitelisted appearance fields into the properties draft; saving that draft uses the normal drawing command and undo path. Templates never become a parallel authority for drawing coordinates or defaults. Template operations validate names/schema/limits and fail visibly on storage errors.

## Geometry locking

Overlay-mode toolbars persist optional `locked` state through the existing document style commands. Locked objects remain selectable, style-editable and deletable, but pointer gestures and property coordinates cannot move or resize them. Canonical move/resize commands reject changes while locked; undo/redo restores document snapshots normally. Old payloads without the flag remain unlocked. Saved style templates exclude the flag. Legacy primitive controls do not expose locking.

## Interval visibility

Optional `visibleIntervals` is a canonical style field; missing/null means all chart intervals. `drawingVisibility.ts` validates exact interval tokens (minute `m` differs from month `M`). The lifecycle's scene projection filter reads the current interval and invalidates on interval changes, so paint, hit-index and export use the same filtered nodes. Hidden drawings remain in the document. Settings save through the existing command/history path and clear selection if the object becomes hidden; templates never copy interval filters.

`DrawingObjectList` groups the mounted pane APIs within one chart and subscribes directly to each scope's `DrawingDocumentStore`; UI state holds only API registrations, dialog state and operation feedback. `DrawingObjectApi` resolves arbitrary IDs through the active document and persists edits using the existing mutation barrier/commands. The optional strict `hidden` style field controls individual visibility independently of interval filters and the global hide-all switch. The scene predicate handles both hidden and interval-filtered entities, including hit testing. List selection reuses the existing cross-pane selection coordinator. Legacy primitive mode does not publish the object API.

Auto-selection is an opt-in local preference beside continuous drawing. Passive pointerdown/double-click cannot select drawings when it is off. When enabled, `drawingToolForSavedObject` resolves the precise tool variant and the controller reuses the existing tool's drag path in the same pointerdown. Only the explicitly marked automatic tool transition skips normal tool-switch gesture cleanup. Explicit object-list selection transfers pane ownership and enters the object's tool even with passive auto-selection off; freehand/highlighter support whole-stroke dragging in overlay mode.

Automatic object editing ends on a blank chart click or Escape, before the creation state machine runs. A chart-container-scoped WeakMap retains only automatic-tool intent across native pane hover ownership changes; a manually selected tool clears it. Escape in dialogs/inputs remains owned by those editors. Explicit drawing creation and its continuous-drawing preference are unaffected.

Whole-stroke movement resolves every canonical sample (including lineage spans and exact ordinal anchors), translates from the gesture's original screen coordinates, and recaptures through the pane adapter. It never uses the decimated display list or simplifies a saved stroke again. Unresolved points, partial capture, changed capture identity, and locked drawings reject the move. Legacy point payloads retain quadratic rendering; legacy moves requiring span-only captures fail closed. Dynamic previews preserve brush/compositing and use pane-local canvas coordinates. Mouseup commits one normal document/history batch; a stationary click is a geometry no-op.

The object list provides local keyword search over translated names, annotation text and IDs, combined with hidden/locked/interval-excluded filters. Filtering uses the same subscribed canonical document and interval predicate as the rows. Counts and membership update after edits; closing the dialog clears only its search/filter UI state.

Object-list front/back actions reorder the complete current pane document through the existing canonical reorder command and persistence/history barrier. Canonical z-order is back-to-front while the list displays front-to-back. Filtered rows use full-document boundaries; layering does not mutate geometry or styles and remains available for hidden/geometry-locked objects.
