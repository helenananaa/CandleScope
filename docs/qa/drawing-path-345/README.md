# Editable drawing paths on macOS

The packaged LIVE app runs against an isolated profile and a bundled backend seeded with minute bars. The driver selects both tools from the drawing palette, places vertices with real pointer events and compares the drawing documents through the app's local control interface.

- On two independent BTCUSDT charts, draw a four-point arrow with two prices at the same time and a backward turn. Drag a vertex, insert a vertex from the segment menu and undo the insertion. Zoom the chart on a logarithmic price scale. Finish a second, plain path with Enter and undo and redo its creation.
- Switch from 1m to 15m, wait for the workspace to save and quit. Check the app and its child processes have exited. Restart on 15m, switch back to 1m and compare both objects' IDs, geometry, style and order. The independent second chart stays empty.
- Enable peer drawing linkage. Create a path, compare both charts, delete it and undo. Repeat the 15m save, full quit, restart and return to 1m. Compare both copies with the pre-quit document.

The filtered [native receipt](native-acceptance.json) contains the source revision, package digest and observed anchor values. The [independent](restored.png) and [linked](linked-restored.png) screenshots show the restored workspaces.

## Reproduce

Use the repository's packaged macOS arm64 app and a fresh QA directory. Put the bundle at `$CANDLESCOPE_BATCH1_QA_ROOT/Installed App/CandleScope.app`. The Playwright tooling package must provide `playwright-core`. Run from the repository root.

```sh
CANDLESCOPE_BATCH1_QA_ROOT="/absolute/path/to/qa" \
CANDLESCOPE_PLAYWRIGHT_PACKAGE="/absolute/path/to/tooling/package.json" \
node docs/qa/drawing-path-345/native.mjs
```

For browser coverage, run `node scripts/frontend-script-integration.mjs --annotation-tools` from `frontend`. It covers draft cancellation, Backspace, Enter, the minimum vertex count, single-vertex and whole-path dragging, right-click insertion and removal, arrow toggling, history, IndexedDB remount and export synchronization. The replay tape viewer test separately checks snapping before and after rewind against its displayed series.
