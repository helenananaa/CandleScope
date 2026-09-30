# Selected drawing style panel — 2026-09-29

Implemented in the existing selected-object editor; persistence and drawing defaults are unchanged.

- Immediate toolbar: stroke palette, session recent colors, custom HEX/native picker, explicit pixel width, shape line-style samples, separate settings and trash icons.
- Separate properties panel: local draft, save once through the existing style-patch callback, cancel/close discard. Switching selected objects remounts the editor to discard the previous draft.
- Keyboard: visible focus, layered Escape dismissal, native modal dialog focus containment, return focus to settings. Toolbar is inert while the properties panel is open.
- Toolbar grip supports pointer dragging, arrow keys (10 px; Shift for 1 px) and Home reset. Positions are clamped to the chart and remembered per chart container across selected-object changes, for the life of that container.
- Properties and color pickers use native top-layer surfaces, anchored to their triggers and clamped to the viewport. Pickers flip upward when necessary. Long properties lists scroll inside fixed headers/footers.
- Fibonacci duplicate/non-finite/over-limit additions are rejected with a visible hint; cancelling clears both the draft and unfinished add-level input. Opacity controls explicitly say opacity rather than transparency.
- Existing Fibonacci, highlighter, ellipse and position settings are retained. Trendline dashed styles are intentionally absent because the current style mutation path only supports them for shapes.

## Validation

- Drawing suite: 733 passed (including 2 layout boundary tests).
- Focused selected-object and positioning tests: 5 passed.
- Typecheck, scoped ESLint, architecture, 30-locale i18n check and production build passed. Build retains the existing large-chunk advisory.
- In-app browser at 1280 × 720, actual BTCUSDT chart: created a rectangle and line; selected both; changed stroke color and width; changed rectangle line style and fill; verified cancel restores the saved settings; save applies settings; Escape closes line settings; rectangle stroke/width/style survive reload.
- Latest production build: checked fill palette/save, number-edit/cancel, recent colors, and clicking outside the palette closes it. Screenshot: `output/drawing-style-panel/rectangle-settings.png`.
- No new drawing UI exception observed. A Vite HMR disconnection was logged while intentionally replacing the development server with a production preview. Market streams separately reported intermittent reconnections.
- Follow-up browser checks: toolbar drag hits left/bottom chart bounds; Home resets; Escape closes the color picker before the dialog. Fibonacci duplicate `0.5` is rejected, temporary `1.414` is discarded by Cancel. At 640 × 480 the long dialog stays within the viewport with the footer visible; the final-level picker opens above its trigger without toggling its checkbox. Dark theme was inspected, then the original light theme and default viewport were restored.
- Follow-up screenshots: `output/drawing-style-panel/fibonacci-narrow.png`, `output/drawing-style-panel/fibonacci-dark.png`.

## Boundaries

This iteration does not add coordinates, timeframe visibility, live chart preview of uncommitted dialog drafts, or new undo capabilities. Dense multi-chart layouts and native packaged Electron have not been qualified in this run. Toolbar placement is session/container-scoped, not saved across reloads.

Preview runs the latest `frontend/dist` at http://127.0.0.1:15173/ with the existing API proxy on port 18080. The normal Vite development configuration stopped responding during startup in this environment; preview uses a temporary in-memory server configuration. Repository Vite configuration was not changed.

## Text formatting and drawing history follow-up

- Text annotations now use the shared draggable toolbar, top-layer color palette and save/cancel property dialog. Font size commits on blur/Enter; Escape discards the input. Formatting no longer vanishes while the updated scene temporarily lacks a text screen box.
- Each document store retains at most 50 session history entries, sharing immutable entities. A terminal command batch is one step. Failed/no-op commits do not create entries; a new edit clears redo. History restores exact styles, geometry and stacking order through the normal scene commit/persistence barrier, advancing document/entity revisions. Reload starts a new history; the resulting drawings remain persisted.
- Undo/redo buttons are positioned inside their own native pane. Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl+Y target the last clicked pane, without intercepting text inputs or modal drafts. Legacy primitive mode does not expose these controls.
- Validation: 736 drawing tests passed, including history batching, order restoration, clear/delete recovery, revision/dirty-state handling, rejected replay, scope separation and the 50-step limit. Typecheck, scoped ESLint, architecture and i18n checks passed; production build passed with the existing chunk-size advisory.
- Actual browser checks: text creation; 32 -> 24 font change and undo/redo back to 32/24; combined bold/color save undone and redone as one step; deletion restored by Ctrl+Z and removed by Ctrl+Shift+Z; property Cancel and font-size Escape preserve saved values. At 640 x 480 the dialog and footer remain within the viewport. Reload retains the final text style and clears session history.
- The earlier no-undo boundary above applies to the earlier iteration. Coordinates/timeframe visibility, cross-reload history and packaged Electron qualification remain outside this follow-up. Store scope isolation is covered by tests; a multi-window manual qualification has not been performed.
- Additional pane check: created a CVD annotation and undid it with Ctrl+Z; the main-chart text and its 24 px bold style remained intact. Text selection now publishes its identity to the existing cross-pane deselection coordinator, so selecting text also retires another pane's formatting toolbar.

## Precise coordinate editor follow-up

- The existing properties dialog now has Style and Coordinates tabs for ordinary time-anchored lines, shapes, Fibonacci drawings, angle measurements and axis lines. Endpoints expose finite price/value inputs and explicit UTC date/time controls. Time and price changes remain drafts until Save; Cancel discards them. Invalid coordinates block Save across both tabs.
- A combined geometry/style change is validated as a complete saved-drawing candidate, then committed in one batch through the same scene persistence barrier. One undo restores both. A changed selection or stale coordinate baseline fails without applying the draft, leaving the dialog open with an error.
- Unsupported ordinal-lineage/logical anchors are not reinterpreted as timestamps. Untouched fractional-second precision is preserved, as are unrelated geometry fields and styles. Future timestamps remain absolute times.
- Browser evidence on the production preview: rectangle endpoint changed from 84483.14639154066 / 2026-09-28 04:30:52.474 UTC to 84400.25 / 04:31:52.474 UTC together with orange stroke; Save, Undo, Redo and reload all reflected the expected values. Empty price blocked Save on both tabs; Cancel restored the original values. At 640 x 480 the dialog fits the viewport, endpoint 2 is reachable by scrolling/focus and the footer remains visible.
- Screenshots: `output/drawing-style-panel/coordinates-settings.png`, `output/drawing-style-panel/coordinates-narrow.png`.
- Boundaries: this coordinate UI does not cover text, freehand, position risk levels or non-time anchors. Timeframe visibility and native packaged Electron remain unqualified in this iteration. There is no preview of uncommitted coordinate drafts.
- Final validation: 742 drawing tests passed; the 6 focused coordinate tests passed again after tightening their type assertions. Typecheck, scoped ESLint, architecture/i18n checks and production build passed. Build retains the pre-existing large-chunk advisory.

## Reusable style templates follow-up

- Added a collapsible Style templates section to the existing Style tab. Users can name/save the current draft style, apply a compatible saved template to the draft, or delete a template. Applying remains cancellable until the drawing is saved; one save is one undo step.
- The versioned device-local template store is separate from drawing documents. An allowlist stores only stroke, shape, highlighter and Fibonacci appearance fields, never coordinates, drawing IDs, text, position risk levels or new-object defaults. Rectangle/ellipse share a family; stroke-only tools share a compatible family. Text and position templates are not exposed in this iteration.
- Names are trimmed, limited to 32 characters and unique within each family (case-insensitive). Each family is limited to 20 templates. Reads validate the schema and style values; malformed/inaccessible storage is not overwritten, and write failures never report success. Reads before writes preserve other families; same-page and browser storage events refresh the UI.
- Validation: 747 drawing tests passed, including style-only allowlisting, family separation, reload/deletion, duplicate/limit handling, corrupt/quota-failed storage, and applying a template through the actual document command/undo path. Typecheck, scoped ESLint, architecture/i18n checks and build passed; the existing chunk-size advisory remains.
- Real browser: saved “橙色观察区” from the existing orange rectangle, rejected its duplicate name, applied it to a second rectangle, cancelled once, then saved. Coordinates were unchanged; the 2 px -> 4 px change reverted/restored with one undo/redo. A temporary template was created/deleted; the useful template survived reload. At 640 x 480 the template fields scroll within the panel and the drawing Save/Cancel footer stays visible.
- Screenshots: `output/drawing-style-panel/style-templates.png`, `output/drawing-style-panel/style-templates-narrow.png`.
- No account/cloud synchronization or packaged Electron qualification was added. Templates are stored independently; cancelling a drawing draft does not delete a template explicitly saved earlier.

## Properties panel crossing native panes

- Reproduced with the rectangle tool active: selecting an existing rectangle, opening its settings and moving down through the panel transferred the tool to the underlying indicator pane. Tool cleanup deselected the original object and removed its dialog. The same path with the passive cursor did not reproduce.
- Native pane hover routing now ignores drawing toolbar/editor descendants and holds ownership while a drawing properties dialog is open, including its backdrop and pointer leave. Closing the dialog restores ordinary hover routing. This covers shape/Fibonacci and text dialogs without changing drawing persistence or selection commands.
- Production-preview verification: the exact failing drag now leaves the dialog open; moving onto the lower-pane backdrop also preserves it. Bottom Save commits a 4 -> 5 px change; Cancel discards a 5 -> 4 px draft. Restored the original 4 px style afterward. After closing, moving into CVD transfers the active rectangle tool to CVD again. Long Fibonacci settings, a lower-level color popover, and text settings remain open across lower panes.
- Validation: all 13 pane-surface tests passed (2 new editor-boundary regressions), typecheck, scoped ESLint, architecture check, diff whitespace check and production build passed. Existing build chunk-size advisory remains. Screenshot: `output/drawing-style-panel/pane-pointer-fixed.png`. Packaged Electron and separate native windows were not tested in this fix.

## Restore unsaved settings

- Shape/Fibonacci/other drawing properties and text properties now offer Reset changes in the footer. It restores the currently saved drawing settings without closing the dialog or changing the selected tab. Coordinate errors and pending Fibonacci level input are cleared. Saved style templates remain independent and unchanged.
- Numeric inputs remount on reset so even locally staged values are discarded. Reset only clears UI drafts; saving immediately afterward does not issue a drawing mutation or add undo history. Footer actions can wrap for longer translations.
- Production-preview checks: staged rectangle width 7 resets to saved 4; empty endpoint price blocks Save, then Reset restores 84400.25, retains the Coordinates tab and re-enables Save. Saving this reset draft creates no undo button/history. Text size 40 resets to saved 24. All three footer buttons remain within the 640 x 480 viewport and Cancel is usable.
- Validation: 9 existing properties/editor tests, typecheck, scoped ESLint, i18n (30 locales / 4496 keys), architecture and production build passed. Existing build chunk-size advisory remains. Screenshot: `output/drawing-style-panel/reset-changes-narrow.png`. No packaged Electron qualification in this iteration.

## Lock drawing geometry

- Added a lock/unlock button to selected drawing and text toolbars in the document-backed overlay mode. Lock is an optional strict boolean in SavedDrawing and canonical style, preserving old unlocked payloads. It travels through the existing style command, persistence and undo/redo paths; style templates do not include it.
- Locked drawings remain selectable and allow style/text edits and explicit deletion. Pointer interaction does not start a move/resize draft, resize handles are hidden, and native chart panning remains available. Coordinates are read-only with an unlock hint. The property candidate and canonical move/resize command boundaries also reject locked geometry changes. Unlock is immediate and undoable.
- Regression testing found selected-object coordinates were stale after a committed drag until reselection. Successful entity drag commits now refresh the selected metadata immediately.
- Browser checks: locked rectangle coordinates remained exactly unchanged after dragging with both cursor and rectangle tool; style editing, style undo, lock undo/redo and refresh retention passed. Text lock retained style editing. A CVD line was created, locked, edited/cancelled and unlocked through its pane's undo; main-chart lock remained intact. The temporary CVD line was deleted. Unlocked rectangle resize changed endpoint time, immediately appeared in Coordinates, and was undone. Original rectangle geometry/width and text font size were restored; test objects were left unlocked.
- 750 drawing tests passed, including lock round trips for all nine families, strict boolean rejection, atomic move/resize rejection, editable styles, undo/redo and hidden handles. Scoped ESLint, architecture, i18n (30 locales / 4499 keys) and production build passed. Final typecheck passed (`output/drawing-lock-types-final.log`). Screenshot: `output/drawing-style-panel/drawing-locked.png`.
- Manual coverage uses native panes inside the web preview. Legacy primitive mode does not expose the lock controls; packaged Electron, separate chart windows and cross-window lock synchronization were not qualified here.

## Visibility by chart interval

- Added Display intervals to the existing shape/line/Fibonacci/etc. and text settings. All intervals is the default; users can select individual intervals, including the chart's current custom interval. Empty selections disable Save. Excluding the current interval shows a warning explaining where the drawing can be edited again. Save, Cancel and Reset retain their existing draft semantics.
- Optional `visibleIntervals` is strict, bounded, duplicate-free and preserved by the canonical codec for all nine drawing families. Missing/null means all intervals. The filter is stored through existing style commands, supports undo/redo and never changes geometry or lock state. Templates exclude this setting.
- Scene projection filters before geometry warmup/culling; the same accepted scene drives paint, hit testing and export. Interval changes invalidate the scene. Hidden selected objects lose selection after save and cannot retain active resize handles.
- Browser checks: rectangle limited to 1H disappears and cannot be selected on 15m; switching to 1H restores selection and unchanged endpoint coordinates; refresh retains the 1H filter. Restoring all intervals and undo/redo toggles visibility correctly. Cancel discards a draft and empty selection blocks Save. Text filtering hides its toolbar/object; undo restores it. At 640 x 480 all three footer actions remain within the viewport. Test drawings were restored to all intervals.
- Validation: 753 drawing tests and 13 pane-surface tests passed, covering strict filter validation, all-family round trips, undo without geometry mutation, and scene/hit-index removal and restoration. Scoped ESLint, i18n (30 locales / 4503 keys), architecture and production build passed. Existing large-chunk advisory remains. Final typecheck passed (`output/drawing-visibility-types-final.log`). Screenshots: `output/drawing-style-panel/visibility-intervals.png`, `output/drawing-style-panel/visibility-narrow.png`.
- Manual coverage is the overlay-mode web preview. Packaged Electron, separate windows and manual exported-image comparison were not qualified in this iteration. Legacy primitive mode does not expose the interval controls.

## Drawing object list

- Added one object-list entry per chart, grouping available drawing hosts by main/indicator pane. Rows use the canonical document subscription and reverse drawing order; selecting a visible object opens its existing formatter. Hidden objects stay listed, and interval-excluded objects have an explicit all-intervals recovery action.
- Individual `hidden` is an optional strict boolean in SavedDrawing/canonical style. Hide/show, lock and deletion use existing scope-checked commands, persistence and history. Scene projection and hit testing share the visibility predicate. No duplicate object registry or persistence format was introduced; style templates exclude visibility state.
- Pointer capture ignores the object list; the existing modal ownership guard covers its long/scrolling dialog. The new API registry follows the existing pane registration ownership checks so a late cleanup cannot remove a replacement host.
- Production-preview checks: hid the original rectangle from the list, refreshed and confirmed it remained hidden/listed, restored and selected it, deleted/undid it, and locked/unlocked it. A 1H-only rectangle was listed as unavailable on 15m and restored using All intervals. A temporary CVD line appeared in its own group; hiding, showing, selecting and deleting it did not affect the main chart or close the list. The temporary line was removed and the original rectangle restored to visible, unlocked, all intervals.
- Verified the 640 x 480 dialog keeps its header/close and footer inside the viewport, with the object body scrolling. Browser warning/error log was empty. Screenshots: `output/drawing-style-panel/object-list.png` and `object-list-narrow.png`.
- Validation: 755 drawing tests and 13 pane-surface tests passed; typecheck, scoped ESLint, i18n (30 locales / 4514 keys), architecture and production build passed. Existing bundle-size advisory remains. Packaged Electron and separate native windows were not exercised.

## Automatic selection from the cursor

- Added Auto-select beside Continuous drawing, default off, persisted independently in `candlescope-drawing-auto-select-enabled`. Wired through the chart workspace and strategy-research drawing surfaces.
- With auto-select off, passive cursor pointerdown passes through to native chart navigation without selecting an object; its double-click path cannot open drawing settings/text editing. Turning it off clears selection, cancels the gesture and returns an automatically entered tool to the remembered cursor. Explicit drawing tools and object-list selection remain intentional edit entry points.
- With auto-select on, a hit resolves its exact saved tool variant and enters the existing tool interaction branch in the same pointerdown. A narrowly marked automatic tool transition preserves that first gesture across React cleanup. Shapes, lines, Fibonacci, axis lines, positions and text use their existing drag behavior; freehand/highlighter selection opens their existing style controls without starting an accidental new stroke. Hidden/interval-excluded entities stay outside the hit index, and locked objects retain their geometry lock.
- Object-list selection also transfers pane ownership before the tool transition completes, fixing the case where selecting a main-chart object after editing CVD cleared the new selection.
- Production-preview checks: disabled cursor clicks on a rectangle did not select/open a toolbar; enabling permitted first-gesture rectangle movement and selected the rectangle tool; undo restored it. Turning the switch off removed selection and restored the cursor, and subsequent clicks stayed passive. Both enabled and disabled settings survived reload. A temporary CVD line selected its line tool and moved on the first gesture; main-chart object-list selection from CVD worked with auto-select off. Temporary text also switched to the text tool and moved from cursor mode. Temporary line/text were removed; the original rectangle was restored and the preference left off.
- Validation: 757 drawing tests, 30 toolbar/view-model/pane tests, typecheck, scoped ESLint, i18n (30 locales / 4516 keys), architecture and production build passed. Existing bundle-size advisory remains. Screenshot: `output/drawing-style-panel/auto-select-text.png`. No packaged Electron qualification in this iteration.

## Exit automatic object editing

- Blank pointerdown now exits an automatically entered object tool before reaching any creation branch, clears selection and returns to the remembered cursor. Explicitly chosen creation tools retain their placement behavior. This also applies when entering from the object list with auto-select off and when Continuous drawing is enabled.
- Native panes share transient automatic-tool intent through a WeakMap keyed by their chart container. Hovering into another pane no longer converts the edit session into an ordinary creation tool; unrelated chart containers remain isolated. This UI state is never persisted in drawing documents.
- Escape exits automatic editing and cancels its current gesture through the existing pointer-cancellation path. Inputs and dialogs retain their own Escape behavior; closing properties does not also exit object editing. Successful text commits on blank clicks also end automatic editing.
- Production-preview checks: reproduced the old blank click staying on the rectangle tool, then verified blank clicks in both main chart and CVD return to cursor without placing objects. Escape returns to cursor and clears selection. Escape inside properties closes only the dialog, retaining selection. Manually chosen rectangle tool still creates a rectangle with two clicks. Automatic edit exit works while Continuous drawing is enabled. Deleted only the temporary test rectangle; both pre-existing rectangles remain; restored Auto-select and Continuous drawing to off. Browser warning/error log was empty.
- Validation: 761 drawing tests, typecheck, scoped ESLint and production build passed; existing bundle-size advisory remains. No packaged Electron qualification in this iteration.


## Whole-stroke dragging (2026-09-29)

- Automatic selection and explicit object-list editing now support moving an entire pen/highlighter stroke on the overlay interaction surface. Manual pen creation remains unchanged.
- The gesture projects all saved samples, translates from the initial pointer position, and recaptures using the existing pane adapter. It preserves sample count, style, native-pane coordinates and the legacy quadratic path contract. Unresolved samples, partial captures, changed source identity and geometry locks fail closed. Legacy strokes requiring span-only recapture remain immovable rather than changing their curve representation.
- Dynamic preview uses the existing ownership/handoff mechanism. Mouseup uses the normal move command and document history; undo/redo restores the exact payload. No new persistence authority was added.
- Validation: 767 drawing tests, typecheck, scoped ESLint, architecture check and production build passed. Existing build chunk-size advisory remains.
- Final production-preview browser checks: main-chart pen moved as one stroke; undo restored its initial position and redo restored the moved position; after allowing the UI update to settle, reload retained that position. CVD highlighter moved with its pane-local price coordinates and stayed fixed while locked; its location and lock survived reload. With auto-selection off, clicking the pen did not open its toolbar. Test strokes were removed, original rectangles preserved, and auto-selection restored off.
- Screenshots: `output/drawing-style-panel/pen-whole-stroke-moved.png`, `pen-whole-stroke-redo.png`, `pen-whole-stroke-persisted.png`. Ordinal/span projection and legacy data are covered by code tests; native packaged Electron and large-stroke performance are not qualified here.


## Object search and status filters (2026-09-29)

- Added case-insensitive, whitespace-separated keyword search across translated drawing names, text annotation contents and object IDs. Search combines with All/Hidden/Locked/Hidden on this interval filters. Pane headings show matching/total counts; empty matches have a distinct message.
- Filters read the existing document subscriptions, so show/unlock actions immediately update membership. Reset clears both search and status; closing/reopening resets the local UI state. No drawing persistence or mutation path changed.
- Production-preview checks: uppercase ID and combined Chinese-name/ID queries returned the correct single rectangle; hiding then restoring it updated the Hidden filter from one match to zero; locking/unlocking updated the Locked filter. The interval filter correctly excluded the all-intervals rectangles. Reset and close/reopen restored the full list. Both original rectangles remain visible and unlocked.
- 640 x 480 viewport retained usable search, filter and close controls; browser error log was empty. Screenshots: `output/drawing-style-panel/object-search.png` and `object-search-narrow.png`.
- Typecheck, scoped ESLint, i18n validation (30 locales, 4522 keys), and production build passed. The existing bundle-size advisory remains. This slice was checked through browser interactions rather than adding implementation-mirroring tests.


## Object layering (2026-09-30)

- Object-list rows now provide Bring to front / Send to back. Boundary buttons are disabled using the complete pane document, not the filtered list. Other drawings retain their relative order; hidden and locked drawings remain eligible because this changes stacking, not geometry.
- The object API commits the existing canonical reorder command through the persistence barrier. No-op boundary requests do not create history. Undo/redo and saved document order use the existing mechanisms; panes retain independent orders.
- Validation: 768 drawing tests, typecheck, scoped ESLint, architecture, i18n (30 locales / 4524 keys), and production build passed. Added an integration test for hidden/locked peers, unchanged entity geometry/style identity, codec round-trip and history replay. Existing bundle-size advisory remains.
- Production preview: searched sh_10 and brought it to front despite it being the only filtered row; reset showed sh_10 above sh_11. Undo restored sh_11/sh_10, redo restored sh_10/sh_11, and reload retained the changed order. Send to back restored the original sh_11/sh_10 order. Both original drawings were preserved. The 640 x 480 layout retained accessible controls. Screenshots: `output/drawing-style-panel/object-layer-order.png` and `object-layer-order-narrow.png`.
- Browser validation covered list order, persistence and history; pixel-level overlap picking and packaged Electron were not separately exercised in this slice.

## Final interaction qualification and stroke performance (2026-09-30)

- Overlap picking in production preview followed the canonical order: the same overlap point selected the 2px rectangle after Bring to front and the 6px rectangle after Send to back. Original drawings and order were restored after testing.
- A long properties panel remained open across lower native panes and across a second independent chart. In a temporary two-chart workspace, undoing the lower chart's width change restored 2px while the upper chart retained its independently saved 5px width. Automatic selection off cleared the active selection. The temporary workspace was removed and original settings restored.
- A 240-point wave stroke was drawn and moved through the browser UI. Screenshots: `output/drawing-style-panel/final-two-chart-ownership.png` and `final-complex-pen.png`.
- Fixed unnecessary RDP simplification during whole-stroke translation with `preservePoints`. Valid-path checks remain active; sample retention now avoids simplification entirely. A regression test verifies all 4096 points of a full-capacity zigzag after translation.
- The same synthetic 4096-point benchmark (40 runs, first 5 discarded) improved coordinate-translation median from 124.64ms to 1.76ms, and p95 from 145.63ms to 6.04ms. This measures coordinate computation only, excluding input delivery, projection and rendering; it is not a frame-rate claim. Receipts: `output/drawing-final-pen-before.json` and `drawing-final-pen-after.json`.
- Final checks: 769 drawing tests and 30 toolbar/pane/view-model integration tests passed; TypeScript, scoped ESLint and the desktop production build passed. Existing chunk-size advisory remains.
- Both TypeScript configurations also passed with unstaged tracked files replaced by their Git index contents through a read-only compiler host, qualifying the staged drawing changes independently of the unrelated edits.
- Packaged executable `frontend/desktop-dist/drawing-editor-final-20260930/win-unpacked/CandleScope.exe` was launched with an isolated profile (`output/drawing-desktop-final-profile`) and UI/backend ports 18179/18180. Backend health returned ok. Actual Windows UI checks covered creating a rectangle, automatic selection with handles/toolbar, opening properties, saving width 2px to 5px, undoing to 2px and redoing to 5px. The QA application was then closed.
- The desktop artifact is an unsigned unpacked QA build, not an installer/release qualification. It was built from the current working tree, which also contains unrelated market-data/localization changes excluded from this drawing commit. Desktop multi-chart stress, long-duration performance and installed-update behavior are outside this check.
