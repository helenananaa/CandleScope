# Trusted host extensions

CandleScope now has a separate, explicitly approved host extension channel. Existing
`.cspkg` plugins and `trusted-local` approvals do not acquire host execution rights.
The new `.csext` ZIP format uses `candlescope.extension/1`. It shares the existing
plugin platform root, management session, loopback/Origin/CSRF checks and atomic
storage primitives; its contract and registry are independent of v2 sidecar manifests.

## Install and use

Build the included packages from the repository root:

```powershell
.venv\Scripts\python.exe backend/scripts/build_trusted_extensions.py
```

In the desktop app, open Settings → Plugins → **Trusted extensions**. Import a
`.csext` file, review its execution realms and exact digest, then explicitly enable
that version. Importing only stages bytes; it never imports Python or JavaScript.
The theme and layout selectors choose one provider each. Different providers may
be selected for each. Disabling the selected provider restores the app default.

Each code entry shows its actual running version independently of the desired
installed version. The manager distinguishes a pending start, a running version,
an old activation awaiting restart, a pending stop, a load failure, unavailable
diagnostics, and recovery mode. Backend and desktop errors are shown separately;
a frontend error no longer hides an error from another entry. Uninstalling a
package that still runs in a background process leaves a restart notice.
Desktop diagnostics use readonly IPC restricted to managed application frames;
they contain version/activation identities and errors, not management credentials.

The samples are:

- `paper.csext`: a data-only light theme, including chart and editor colors.
- `terminal.csext`: a full-trust theme/layout, custom top bar, a Python service,
  and an Electron lifecycle listener. The sample does not place orders or access
  credentials. Theme and layout selection remain explicit after enabling its code.

Packages are currently local, unsigned imports. A digest establishes byte identity,
not publisher authenticity. The UI states this distinction. Marketplace publication
and signing are not implemented for this new format.

## Manifest

```json
{
  "schema": "candlescope.extension/1",
  "id": "example.workbench",
  "name": "My workbench",
  "version": "1.0.0",
  "apiVersion": 1,
  "internalApiVersion": 1,
  "trust": "full-trust",
  "entries": {
    "frontend": "frontend.mjs",
    "backend": "backend.py",
    "desktop": "desktop.mjs"
  }
}
```

Each entry is optional. A package must contribute code, a theme, or a layout.
`trust: "theme"` permits validated theme tokens and forbids code and layout entries.
API versions are checked before activation. Optional dependencies map extension IDs
to exact package versions; activation rejects missing versions, cycles and upgrades
that would invalidate active dependents. Disable dependents before their provider.

Paths are relative to the archive root. The archive must contain files only (no
directory records), at most 256 files, and at most 16 MiB compressed and expanded.
Traversal, Windows device names, case collisions, links, encrypted entries and
unsupported manifest fields are rejected. Asset contents are checked against the
approved archive digest when served/materialized. Executable asset URLs are issued
only through authenticated management, and are bound to a particular activation.

Theme tokens and layout examples are in `examples/trusted-extensions/`. Data themes
cover the shared palette, fonts, radii, selected control dimensions and chart/editor
colors. They do not rewrite every historical hard-coded component style. Full-trust
code can supply additional CSS or replace those components.

## Frontend SDK

`frontend.mjs` exports `activate(context)` and optionally `deactivate()`. Activation
may return another cleanup function. Each window owns one extension runtime,
regardless of chart count. Bundle frontend code as ESM; use `context.React` instead
of bundling a second React runtime. Relative module imports resolve within the
verified package. Do not import repository source paths.

The TypeScript contract is `frontend/src/features/extensions/contracts.ts`:

- `ui.replaceSlot(name, Component)`: replace `shell`, `topBar`, `intervalSelector`,
  `workspace`, `featureSurfaces`, `statusBar`, `toolbar`, `chart`, `bottomPanel`,
  `rightRail`, or `exportOverlay`. The component receives `fallback`; `shell` also
  receives the host's `slots`. Two active replacements for the same slot fail
  explicitly; there is no installation-order winner.
- `ui.stylesheet(css)`: add an owned stylesheet that is removed on disposal.
- `commands.register(localName, handler)` / `commands.execute(fullName, payload)`:
  command names are prefixed with the extension ID.
- `services.register(localName, value)` / `services.get(name)`: plugin services
  are namespaced. Host services include `workspace`, `settings`, `desktop`, and
  `charts.<cellId>`, `market.<cellId>`, `indicators.<cellId>`, `drawings.<cellId>`.
  These services exist only while their owning view is mounted. Resolve them at
  use time instead of retaining an old render snapshot.
- `events.on(name, callback)` / `events.emit(name, value)`: a window-local event
  bus. Host bindings publish `<serviceName>.changed`. Listener failures are
  reported against the owning extension.
- `track(cleanup)`: clean up timers, listeners and resources created by the plugin.
- `assetUrl(relativePath)`: get a URL belonging to this activation.
- `internal.get(name)`: available when `internalApiVersion: 1` is declared. This
  provides no additional isolation; internal contracts can change in later versions.

Data layout ordering preserves the host slot tree: `page` reorders the outer page
slots; `workspace` positions the rail to either side, the drawing toolbar to either
side of the chart, and the bottom panel above/below the chart. Overlays remain in
the chart container. Arbitrary new geometry uses a component replacement.

Changing a theme updates chart appearance without recreating the chart canvas.
Data layout ordering also retains mounted chart components. Replacing an entire
component tree can remount its children, so an arbitrary plugin shell is responsible
for preserving its own state and reusing the supplied host slots appropriately.

Registry reads use a revision check every 10 seconds while a window is visible and
on focus. Unchanged reads do not unpack archives. Management actions refresh the
current window immediately; other visible windows reconcile on their next read.

## Python host entry

Backend entries load once per application process, not once per chart/window.
They may export `prepare(context)` before built-in service construction,
`activate(context)` after application services start, and `deactivate(context)`.
Callbacks may be asynchronous. The context provides:

- `app`: the FastAPI application, including its internal state. Treat objects
  accessed here as internal API and declare `internalApiVersion`.
- `wrap_factory(name, wrapper)`: during `prepare`, install one wrapper for
  `data-engine`, `replay`, `alert-delivery`, or `indicator-range`. The wrapper receives
  the original factory followed by its arguments and must preserve its contract.
  Competing wrappers fail explicitly. New service factories must be wired into the
  composition root before they can be replaced through this API.
- `replace_service(name, object)`: replace an `app.state` binding and register
  restoration. This does not rewrite references already captured by other services.
- `track(cleanup)`, `root`, `extension_id`, `api_version`, `internal_api_version`.

Relative imports resolve alongside the Python entry under a digest-specific module
namespace. In `LOCAL_OFFLINE`, the network guard and local dataset services start
before extension preparation. Live data/replay factories are unavailable in that
profile; protected extension management remains available to the desktop session.

For example, `prepare` can call
`context.wrap_factory("data-engine", my_start_wrapper)`. The normal application
bootstrap invokes that wrapper and downstream services receive the chosen runtime.
Factories must preserve the runtime's startup, state attachment and shutdown APIs.

## Electron host entry

Desktop entries run once after the backend is ready and the window manager exists.
They export `activate(context)` and optionally `deactivate()`. `context.electron`
exposes the app, BrowserWindow, dialog, ipcMain, screen and shell APIs;
`context.host` exposes the window manager, workspace bus, app work budget and
series snapshot hub. `track` registers owned cleanups. Desktop startup verifies all
materialized package file digests again before importing the entry.

## Updates, disposal and recovery

Enabling a different version or re-enabling a package requires approval bound to
its exact digest and trust level. Previously installed digests are retained for
review and rollback. Uninstall removes the registration but retains cached archives;
it does not erase plugin-created files elsewhere on disk.

Frontend disposal removes SDK-owned contributions and invokes cleanups in reverse
order. Async activation/cleanup has a bounded wait. JavaScript modules cannot be
unloaded from the page, and arbitrary global modifications cannot be undone
reliably: reload the window after code changes for a clean execution environment.
Backend and desktop activation, disable, upgrade and rollback take effect on the
next application restart; changing the desired configuration does not claim to
unload code already imported into those processes.
On desktop shutdown, the backend allows five seconds for HTTP connections and
requests to drain before cancelling unfinished requests and running lifespan
cleanup. The desktop's existing 15-second process stop limit is unchanged. Slow
or blocked extension cleanup can still exceed that limit and be forcibly stopped.

Recovery is available outside replaceable UI slots:

- The **Extension recovery** button opens management or reloads with
  `?extensions=off`. This skips frontend extensions for that document.
- Launch the desktop app with `--extensions-safe-mode`, or set
  `CANDLESCOPE_EXTENSIONS_SAFE_MODE=1`, to skip all extension execution realms.
- An interrupted-load marker skips the interrupted package activation on the next
  launch. After recovery, explicit approval of that version creates a new activation
  generation, allowing a deliberate retry.

Desktop crash markers are flushed to a temporary file and atomically replaced.
Exiting while restoring a marker must not truncate the last complete recovery
record. Invalid markers stop native extension loading while retaining management.

Full-trust code is application code. It can access the user's resources and bypass
in-process conventions. Permission UI, ErrorBoundary and cleanup ownership are not
security boundaries against such code. Synchronous infinite loops or native crashes
require restarting in recovery mode. External effects such as writes and network
requests are not rolled back by disabling a plugin.

## Validation

Backend tests: `backend/tests/test_trusted_extensions.py` (archive/approval,
dependency, generation/revocation, Python cleanup/factory and management API checks).
Frontend tests: `frontend/src/features/extensions/__tests__/runtime.test.tsx`.
Desktop tests: `frontend/desktop/trusted-extension-host.test.mjs`.

`backend/tests/run_trusted_extensions_browser_server.py --root <isolated-dir>`
serves the production frontend with deterministic market data and isolated plugin
state. It is a development fixture; its management bootstrap must never be used as
a production authentication mechanism. Browser evidence belongs under
`output/trusted-extensions/`. These checks do not establish marketplace release,
arbitrary third-party plugin compatibility, or packaged Electron qualification.

### Local validation, 2026-10-06

- 54 backend checks passed across extension packages/runtime/API, the actual
  `LOCAL_OFFLINE` boot, existing management/sandbox boundaries, plugin main
  lifecycle and trade-flow runtime.
- 216 frontend/desktop checks passed across extensions, existing plugins, chart
  appearance/lifecycle, shared market frames/rail state and Electron host helpers.
- TypeScript, changed-file ESLint, architecture, plugin-boundary and i18n checks
  passed. The production build passed with the existing large-chunk warning.
- A production-build browser fixture verified package consent, theme switching
  without canvas replacement, left/right layout changes, left-rail resize, theme
  synchronization between two pages, version upgrade and rollback, cleanup on
  disable, and recovery via `?extensions=off`. At 390 px viewport width, the manager
  remained within the viewport with no page horizontal overflow.
- Screenshots: `output/trusted-extensions/paper-desktop.png`,
  `terminal-desktop.png`, and `mobile-manager.png`. The fixture has 64 deterministic
  bars, three known unsupported-endpoint 404s (replay capabilities, indicator
  diagnostics, alert stream), and no live exchange connection. It is not a live
  market or packaged desktop acceptance run. The editor color integration was
  typechecked but not visually exercised in this browser pass.

## Packaged desktop acceptance

Build a separate desktop output directory and wait for the packager to exit
successfully before launching it. In a checkout with an already verified standalone
Python runtime, the normal Vite desktop build plus `electron-builder --win dir`
can reuse that runtime; `npm run desktop:package:dir` prepares a fresh one.

The repeatable acceptance driver is
`frontend/scripts/trusted-extensions-desktop-smoke.mjs`. From the repository root:

```powershell
node frontend/scripts/trusted-extensions-desktop-smoke.mjs `
  --executable <completed-package>/win-unpacked/CandleScope.exe `
  --playwright-module <playwright-core>/index.js
```

It creates a fresh directory under `output/playwright/trusted-extensions-desktop/`
for each run, with a separate Electron profile, plugin store, local dataset root,
and lifecycle receipts. It uses the packaged Python backend in `LOCAL_OFFLINE`.
No installed user plugins or exchange accounts are used. The generated probe
packages live only in this test directory and are not examples for distribution.

The checks cover consent through the real manager, restart-bound activation in
three realms, a second native window, actual-versus-desired version reporting,
upgrade, rollback, disable, shutdown cleanup, global safe mode, activation errors
in all realms, and a deliberately interrupted native startup followed by recovery.
The native crash probe uses Electron's `process.crash()` in the isolated test
process; the driver matches the recovery marker to that exact package digest.
Python calls `deactivate` before its tracked cleanups; frontend/desktop disposal
runs registered callbacks in reverse order, including `deactivate` registered
before activation. The driver checks that both callbacks ran once without imposing
an identical callback ordering across realms, for every normal shutdown. After
the native crash, it checks that the child backend has exited before reboot.
Playwright may forcibly reclaim that failed launch's process tree; cleanup
callbacks are not guaranteed for the intentional crash and are not asserted there.

Each report retains completed phases, failures, native logs, screenshots, process
IDs in lifecycle receipts, and SHA-256 identities of the executable, ASAR, extension
backend modules and Python-runtime manifest. A failed run is retained for diagnosis.
These are extension lifecycle checks on a Windows directory package; they do not
qualify a signed installer, live trading, arbitrary third-party packages or other
operating systems.

### Packaged result, 2026-10-06

- Final Windows x64 directory package:
  `frontend/desktop-dist/trusted-extensions-20261006-qualified/win-unpacked/`.
  Launch `CandleScope.exe` with the entire directory intact. Authenticode reports
  `NotSigned`; this is a local acceptance build.
- Final report:
  `output/playwright/trusted-extensions-desktop/run-WXjccQ/report.json`.
  All seven scenarios passed across ten fresh desktop starts in 66.7 seconds,
  including one intentional native crash. All normal shutdowns produced exactly
  one deactivate and cleanup receipt per activated probe process. The crash
  process tree was reclaimed and the next boot skipped the interrupted activation.
  No processes from this package remained after the run.
- The manager reports frontend, backend and desktop status separately, including
  the actual running version while a newly approved version awaits restart.
  Screenshots alongside the report include `pending-restart.png`,
  `failure-recovery.png`, `safe-mode.png`, and `interrupted-startup-recovery.png`.
- 39 backend and 148 frontend/desktop regression checks passed. TypeScript,
  changed-file ESLint, architecture, plugin-boundary, i18n and desktop Vite build
  checks passed. These are scoped checks, not the full repository suite.
- Acceptance found and repaired non-atomic desktop crash markers and an
  unbounded backend listener drain that prevented lifespan cleanup. The latter
  has a controlled regression that timed out before the fix and completed
  cleanup afterward, within the existing process stop budget.
- Executable/ASAR/backend/runtime hashes are retained in the report. Packaged
  native host, main, preload, sidecar and extension backend sources were compared
  with the tested checkout. `output/trusted-extensions/qualified-identity.json`
  records backend hash matches and signature status. Earlier failed and diagnostic
  runs remain on disk; the final report above is the acceptance result.

This completes the local packaged extension lifecycle stage. Signed distribution,
publisher verification, a marketplace, live exchange operation, cross-platform
acceptance and visual editor-theme qualification remain outside this result.
