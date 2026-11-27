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
- `core/drawingDocument.ts` owns the immutable drawing business model and
  independent document, geometry, and style revisions.
- `core/drawingCommands.ts` and `core/drawingDocumentStore.ts` are the only
  committed mutation/publication path. Completed controller actions carry the
  complete canonical payload required by create, delete, move, resize,
  update-style, clear, or reorder; unrelated primitive drift rejects the whole
  transaction and can never supply missing command data.
- `core/drawingCodec.ts` owns fail-closed conversion between the canonical
  document and the unchanged legacy `SavedDrawing[]` wire contract.
- `core/drawingWireContract.ts` lists every geometry and style key per kind.
  Replay training saves canonical documents to the backend, whose allowlist in
  `backend/app/replay/training/review.py` must accept them all. After adding a
  kind or key, regenerate `frontend/contracts/drawing-wire.json` (the command is
  in the module) and extend the backend allowlist; the backend test
  `test_replay_drawing_wire_contract.py` fails until both agree.
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

## Source range measurements

The price, time and combined range tools create `range-measure` entities through the two-anchor scene interaction path. They retain source time and price; the displayed delta, percentage and elapsed duration do not depend on chart pixels or the current interval. Elapsed duration includes market closures and is not a count of bars. The percentage uses the absolute initial price and is unavailable for a zero initial price. The existing angle tool retains its screen-angle meaning.

Measurements use the canonical document, scene/display-list painter, hit index, properties, lock, visibility, undo/redo and persistence/export barriers. No per-object legacy primitive is introduced. The new tools are offered on ordinary time-axis charts with the default overlay interaction owner; legacy renderer controls do not offer them. A source anchor that cannot be projected does not produce a fabricated endpoint or measurement. Existing unsupported representations retain saved objects without reinterpreting their anchors.

## Arrows, parallel channels and rectangle zones

The arrow tool creates an ordinary `line` segment whose style carries `arrowEnd`. The arrowhead is presentation, not geometry: `lineType` keeps meaning only segment/ray/infinite extension, rays and infinite lines never paint a head, and the selected-segment settings can toggle the head on any segment. Arrows are offered wherever segments are, including source-lineage representations.

The parallel channel creates a `channel` entity with three source anchors: baseline start, baseline end, and a point the parallel line passes through. Creation is three clicks; the second click fixes the baseline without committing. The parallel offset is derived in screen space at projection time (baseline translated vertically through the third anchor), so the rails stay visually parallel on linear and logarithmic price scales and across zoom. The width handle sits at the middle of the parallel rail; dragging it moves only the third anchor, and dragging a rail or the band interior moves all three. Hits use point zones, rail polylines and a `polygon` zone for the interior. Like range measurements, channels are scene-path only with no legacy primitive, and are offered on ordinary time-axis charts.

Rectangles gain optional zone options: `extendRight` (geometry, because it changes the drawn extent and culling bounds; toggling it commits as a resize), and `midline`, `priceLabels` and a short `label` (style). The extension is painted only: anchors, resize handles and the persisted right edge never move to the pane edge. Boundary prices are read from the source anchors and formatted by magnitude. Ellipses ignore all zone options.

## Multi-select, groups, copy/paste and favorite tools

A selection is a primary drawing (the one whose style bar or handles show) plus the other selected ids in z-order (`interaction/drawingMultiSelection.ts`). Shift-click toggles a drawing; ⌘/Ctrl+A selects every drawing visible on the interval once something is selected. With two or more selected, `DrawingMultiSelectionBar` replaces the one-drawing style bar.

Groups are a common style flag, `groupId` (`grp_…`, validated by the codec and both persistence normalizers). Clicking any member selects the whole group. Group (⌘/Ctrl+G), ungroup (⌘/Ctrl+⇧G) and delete are each one `update-style` or `delete` batch, so one undo restores them.

Pressing the body of a selected drawing moves every selected drawing (`interaction/drawingGroupMove.ts`). Each member keeps its own body-drag descriptor and gets the same screen delta, and the whole move commits as one batch of `move` commands. With the magnet on, only the primary's first anchor snaps and the others follow by the corrected delta, so the group keeps its shape. A locked member keeps the selection in place. During the drag the members leave the static scene (`companionOverlayEntityIdsRef`) and the dynamic overlay paints them; their drafts stay there for two frames after the commit so nothing flickers. A handle press still resizes just that drawing.

Copy (⌘/Ctrl+C) keeps detached copies in memory for this window. Paste (⌘/Ctrl+V) and duplicate (⌘/Ctrl+D) create new drawings with new ids and new group ids, unlocked. Pasting onto the chart the copy came from offsets it by 16 px; another symbol or chart gets the same anchors. These shortcuts belong to the chart last pressed and skip text fields, dialogs and text editing.

Favorite tools are starred in any tool menu (or F on a focused row), up to nine, stored per browser profile under `candlescope.drawing.favoriteTools.v1`. They appear as their own toolbar strip, and Alt+1…Alt+9 (by physical key) picks them.

## Calculated drawings

Fib extension, anchored VWAP, fixed-range volume profile and regression channel are one `calculated` entity kind with a `calcType` and 3, 1, 2 or 2 time anchors (`geometry/calculatedDrawingMath.ts` holds the maths; `engine/drawingCalculatedProjection.ts` the projection). Only the anchors are stored. Values are recomputed on every projection from `DrawingFrameSnapshot.seriesData`, the bars the chart is showing, so a replay chart (which shows only revealed bars) can never feed them a later bar, and the world revision already changes with `dataRevision`. Bars are taken by position: a market closure has no bars and nothing fills it, a range anchored inside a closure starts at the next bar, and the regression slope is per bar, not per second. The volume profile spreads each bar's volume evenly over its high–low range and says "Estimated from N bars" on the chart. Like channels these are scene-path only, offered on ordinary time-axis charts with the overlay surface; the fib extension uses the three-click flow, the anchored VWAP a single click. Replay training offers them too and saves them in the run record like other drawings (the backend allowlist accepts the `calculated` kind). Selection handles come from the scene projection (fitted line ends, profile corners, first VWAP value) and map back to the stored anchors.

## Callouts and price labels

Both tools create ordinary `text` entities, so they reuse the inline editor, the text format bar, the object list, locking, interval visibility, history, persistence and export without a second store. `interaction/drawingTextAnnotations.ts` owns their creation payloads, drag parts and drag previews.

- A callout adds an optional `target` anchor to the text geometry. The first click fixes the target, the second places the box and opens the editor; an empty note removes the draft like any text. The scene paints a leader from the box's nearest border point to a dot on the target. Dragging the box moves only the box, the target dot (also a selection handle) moves only the target, and the leader line moves both. All three commit one normal geometry command.
- A price label sets `priceLabel` on the text style and keeps one anchor. Its content is the anchor's source price, formatted like zone boundary prices, so it is never opened for typing and follows the anchor when dragged. The tag is painted up and to the right of the anchor with a leader back to it.

Anchors keep source time and price, so interval switches, zoom and history backfill never move them. A stored price label never carries a target; strict persistence rejects that and malformed targets. The tools are offered on ordinary time-axis charts with the default overlay interaction owner; legacy renderer controls and source-lineage charts do not offer them, and the legacy text primitive keeps showing a callout as plain text.
