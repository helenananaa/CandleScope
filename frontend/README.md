# CandleScope Frontend

React/Vite charting UI for CandleScope.

## Architecture

- [Design system](../DESIGN.md) and [design refactor plan](FRONTEND_DESIGN_REFACTOR_PLAN.md)
- [Frontend Architecture](ARCHITECTURE.md)
- [前端架构](ARCHITECTURE_zh.md)
- [Feature Boundaries](src/features/README.md)
- [Shared Boundaries](src/shared/README.md)
- [Chart Adapter Boundaries](src/chart-adapter/README.md)
- [Runtime Boundaries](src/runtime/README.md)
- [Frontend Cleanup Execution Plan](FRONTEND_CLEANUP_EXECUTION.md)
- [前端清理执行计划](FRONTEND_CLEANUP_EXECUTION_zh.md)
- [前端理想架构执行文档](FRONTEND_ARCHITECTURE_REBUILD_EXECUTION_zh.md)
- [前端架构边界硬化执行文档](FRONTEND_ARCHITECTURE_HARDENING_EXECUTION_zh.md)
- [前端最终收尾执行计划](FRONTEND_FINAL_POLISH_EXECUTION_zh.md)
- [前端 TypeScript 渐进迁移执行文档](FRONTEND_TYPESCRIPT_MIGRATION_EXECUTION_zh.md)
- [绘图引擎 V2 丝滑重构执行文档](DRAWING_ENGINE_V2_REBUILD_EXECUTION_zh.md)

## Standalone browser workspace

From the `frontend` directory, build and serve the static workspace with:

```bash
npm ci
npm --prefix browser ci
npm run build:web
python3 -m http.server 4178 --bind 127.0.0.1 --directory dist-web
```

Open `http://127.0.0.1:4178/` in a browser supporting module Shared Workers, Service Workers, WebAssembly and IndexedDB. Public hosting requires HTTPS. Build from a Git checkout with Python 3, Node and curl available; `npm run build:web` first installs the Pyodide package of `browser/package.json`. The build downloads checksum-locked wheels into `browser/.host-cache`, unpacks them, and runs `browser/host/prepare_engine.mjs` on the bundled Pyodide: it computes the pinned CCXT catalog (`CANDLESCOPE_CCXT_CATALOG`) and compiles the modules that starting the backend imports. The CCXT packages load each exchange class on first use. The engine archive (`backend.zip`) holds the C extensions that importing loads, which the browser reads before Python starts, and one zstd stream of the other 4,900 files, which the interpreter's own zstd unpacks on each start. Similar files sit together in the stream, so it is about 40% smaller than the same files compressed one by one (18.5 MB instead of 29.6 MB) and unpacks faster. Compressing takes about 40 seconds; `browser/.host-cache` keeps the result for a rebuild of the same files. The deployed application serves its Python runtime and packages from the same static site, under `engine/<content hash>/`, so a deployment never pairs new pages with a cached older engine. Serve the HTML pages and `workspace-service.mjs` with `Cache-Control: no-cache`; the hashed engine and assets can be cached indefinitely. The Cloudflare Worker `candlescope-web` (`wrangler.jsonc`) serves the build at the root of its own host: Workers Builds runs `npm ci && npm run build:web` and `npx wrangler deploy` in this folder for `main`. The build writes the Worker's `_headers`, which keeps Cloudflare's revalidating default for the pages and the service worker and caches `engine/` and `assets/` for a year, and `_redirects`, which serves `/` from `index.html`: `html_handling` is `none`, so each page keeps its `.html` address, which the pages link to and the shell mirrors. The design mockups in `public/design-previews` are left out. The `Browser version` workflow builds the same way on Node 22 and Python 3.12, checks these files, and runs the storage acceptance. Serve the scripts, styles and `pyodide.asm.wasm` compressed (gzip or Brotli); the engine archives are compressed already. A first visit then downloads about 26 MB (37 MB uncompressed). The engine starts without waiting for the first venue catalog; the first market requests join that shared load. `browser/host/catalog.mjs` starts loading the opening market's catalog (Binance spot, 7 MB) while the interpreter starts, gives each of a start's readers that one copy, and keeps it in Cache Storage. A download that receives nothing for 15 seconds is given up, and its readers ask the venue themselves. A start within a day reads the stored copy and replaces it in the background; when the backend finds a symbol missing, its next read asks the venue. Parsing the catalog occupies the interpreter for about a second, so the engine hands it to the backend once the page has its first candles. Three backend rules differ in a browser tab, where every page load is a cold start: Binance streams share one socket per CCXT client, because browsers open the sockets to one host in turn; connection attempts are not spaced a second apart (Binance's limit of 300 per five minutes still applies); and a history request that meets another request's cold-start probe looks again after a quarter of a second instead of waiting for the probe's 30-second lease. After the first page has loaded, the shell starts `browser/host/snapshot-worker.mjs`, which imports the backend in a separate interpreter and keeps a memory snapshot of it (about 140 MB) in the site's Cache Storage. Later engine starts restore that snapshot instead of importing the backend. The build records the C extensions that importing loads (`dynlibs.json`); both interpreters load them before Python starts, so the restored memory finds them in place. The engine reads its archive as it arrives. The C extensions come first and compile while the rest downloads, and Pyodide downloads its runtime and starts Python meanwhile; only unpacking and importing the backend wait for the whole archive. The build fails if importing the backend reads or creates anything in the data directory, which a snapshot would keep. Each engine build has its own snapshot, and one that fails to restore is not used again. The engine also keeps its archive, Pyodide's runtime, the standard library and the lock file (about 31 MB) in Cache Storage beside the snapshot, and later starts and the snapshot worker read them from there. Safari did not reuse what workers had downloaded through its HTTP cache, so each of its starts downloaded them again. Storing a file or a snapshot removes those of other engine builds, and a start that fails drops the stored files. The engine's module scripts (about 1.3 MB) stay with the HTTP cache.

The market, replay and strategy entries load the original React entrypoints. A top-level visit opens a shell that owns the shared Pyodide worker and shows each original page in one same-origin frame. The shell loads that frame once the service worker is active, so the worker controls the page from its first request; Safari does not always hand a frame that already exists to a newly activated worker. A page that still finds itself uncontrolled reloads once, then reports the failure. The page does not wait for the engine: the application loads and shows at once, and its HTTP requests and sockets wait in the engine's queue until the engine has started. The service worker's 95-second limit on a request counts from when the engine takes it (the engine answers `accepted` on the request's channel), within 250 seconds overall. If the engine takes longer than 2.5 seconds, as a first visit's download does, the page says that it is starting; a failed start covers the page with the reason. `data-engine-instance` on the page's root element appears when the engine has answered. Moving between pages, reloading the frame and opening further tabs reuse the running engine; the shell mirrors the page's address and title, so reloading or sharing the URL opens the same page. Reloading or closing the site's last tab ends the engine. A service worker forwards application HTTP requests to the original FastAPI ASGI app in that worker. In-app WebSockets use that same app. Public exchange I/O uses browser Fetch/WebSocket below CCXT. Desktop query, backfill, storage, indicator and chart logic remain the owners of their contracts. SQLite files live in the browser profile. While the engine runs, its data directory is in memory; `browser/host/store.mjs` keeps a copy in IndexedDB as 64 KiB chunks, writes only the chunks that changed, and saves after each request and every two seconds in one transaction. A directory saved by earlier builds with IDBFS moves to it on the first start. If a save fails, the engine keeps serving and the page says that recent changes are not saved yet; the next save retries them. Only one engine build uses the storage at a time: tabs of another build wait until the running build's tabs have closed. The shell asks the browser to keep the site's data persistently. Clearing site data removes it. Because the data directory is held in memory, the browser host keeps no raw REST/WebSocket envelope log (`INGESTION_MARKET_SOURCE_CAPTURE_ENABLED=0`; the desktop app keeps it losslessly). A log that earlier browser builds kept is removed, and the database compacted, when the engine next starts.

The browser host disables native plugins, subprocess backtests, private exchange accounts and the optional Parquet trade-tape runtime. Exchange availability depends on the visitor's network and CORS. History studies and the research library in the WASM host use origin-scoped browser storage. Desktop local-access checks still apply on native hosts. The library uses the same CSV importer, IANA time zones, project ZIP files, dataset revisions, and replay sources as the desktop local-data profile. The replay picker uses imported bars and trade prints. Simulated and manual accounts and their journals are browser-local. Private exchange credentials and script execution require the desktop app. A tab shares the Python engine with other tabs on the same application origin. Closing the browser ends background work. Loading an original page does not by itself establish parity for all of its workflows.

On the replay page, choose **New training**, an exchange, a spot or linear perpetual market, the symbol, the UTC start and end, and **Start replay**. The desktop preparation job handles acquisition and launches the run. The browser resolves its warmup and forward window against saved library coverage, stitches overlapping revisions, and fetches the uncovered spans. The browser also skips the desktop whole-store maintenance sweeps so that opening a historical window does not enqueue a download from that window to today. Repeated launches can use a containing dataset offline. The research library still has a separate **Download** tab for explicitly saving a fixed range. Replay lists desktop providers with a declared continuous one-minute history basis. Exchange or regional access and published history can limit the usable window. Binance spot and USD-M use aggregate trades; OKX spot and linear swaps use historical trades with the original IDs and base-unit quantities. Other displayed markets offer bar replay. Download receipts distinguish the venue, product and symbol; old Binance spot receipts retain their keys. The library validates continuous trade sequences and retains its 200,000-record limit.

A window narrower than 640 px, a phone held upright, gets a phone layout (`src/app/phoneLayout.ts` and the `@media (max-width: 640px)` rules beside each surface's styles). The header takes two rows: the workspaces and Settings, then the page's own controls, whose actions move into 更多; the desktop download link leaves it. The market and replay rails become a bar of tabs under the chart, and a tab opens its view as a sheet over the lower part of the chart, one view at a time. Each visit starts with the sheet closed. Strategy research runs its modes across the top and scrolls as one column. The chart's pane controls, which a touch screen would otherwise show all the time over the legend, stay hidden.

### Browser acceptance

The live smoke uses the original market canvas and API to fetch public bars, request an older page and check the desktop MA against the displayed inputs. Before exiting it waits for the engine's memory snapshot and checks that the opening catalog was downloaded once for its readers. It exits Chromium completely, reopens the same profile with external market DNS blocked, checks that the engine started from the snapshot and the stored catalog without downloading its files again, compares all six OHLCV/time fields for 32 historical bars, then reopens online and extends the same series further. It creates and removes its own temporary browser profile.

With a local Playwright Core install and Chrome available, run from the frontend directory:

```sh
PLAYWRIGHT_MODULE=/path/to/node_modules/playwright-core CHROME_PATH=/path/to/chrome \
  node browser/host/acceptance.mjs http://127.0.0.1:4178/
```

The scripts drive the page frame through `browser/host/app-frame.mjs`, which also starts the browser: Chrome by default, or Playwright's WebKit (Safari's engine) with `BROWSER=webkit`. Playwright's WebKit cannot keep a profile directory on every macOS, so a script's visits share one context and a browser exit becomes closing every tab; its Cache Storage does not outlive the last tab, and it cannot block the network for pages a service worker controls. The scripts skip the snapshot and offline-network assertions it cannot show. Playwright's Firefox lets page requests bypass service workers, so it cannot run the web version; check Firefox and Safari themselves by hand. `browser/host/page-switch-acceptance.mjs` moves between the market, research and replay pages, then checks that each page shows and reports the same engine instance, application sockets do not accumulate, back and forward move the frame and address bar together, and a second tab or a reload joins the running engine.

`browser/host/multimarket-acceptance.mjs` exercises exchange/product selection, chart opening and venue-scoped cache reuse across Binance, OKX, Bybit and Bitget. `browser/host/replay-start-acceptance.mjs` exercises Start replay with cold, partially covered and offline inputs for both bars and aggregate trades. `browser/host/download-acceptance.mjs` covers the optional library download form. `browser/host/storage-acceptance.mjs` saves a SQLite database larger than one IndexedDB value, small updates and file operations, reads them back in a second interpreter and migrates an IDBFS directory. The companion `browser/host/research-acceptance.mjs` uses the same Chrome configuration. It imports CSV, exports and restores a project ZIP, starts BAR and trade-print training sessions, steps the BAR replay, subscribes to a practice account, writes a journal note and verifies state after restarting Chrome. Large archives, every exchange, other browser engines and native strategy providers have separate acceptance requirements.

## Backend Connection

The frontend uses same-origin `/api/v1` by default. During local development,
Vite proxies `/api` HTTP and WebSocket traffic to
`http://127.0.0.1:18080`. The default dev entrypoint is
`http://127.0.0.1:15173`.

Use `VITE_API_BASE` only when the backend is not reachable through the Vite
proxy, for example:

```bash
VITE_API_BASE=http://127.0.0.1:18080/api/v1 npm run dev
```

## Exchange Capabilities

The app loads `GET /api/v1/exchanges/` on startup and builds an exchange catalog from backend capabilities.

Frontend exchange behavior should prefer backend metadata:

- `native_intervals` drives the interval selector.
- `markets` drives available spot/futures choices where the UI exposes market filters.
- `ws_connection_model` and `protocol_features` decide whether live WS intervals are subscribed.
- `known_limitations` are surfaced in the status bar so exchange-specific gaps are visible to users.

The local `EXCHANGE_INTERVALS` table in `src/features/chart-session/exchangeCatalogRuntime.ts` is a fallback only. New exchange support should be added in the backend plugin first, then exposed through `ExchangeCapabilities`.

## Checks

Optimization execution notes:

- [Architecture](ARCHITECTURE.md)
- [Optimization Execution Plan](OPTIMIZATION_EXECUTION.md)
- [Frontend Cleanup Execution Plan](FRONTEND_CLEANUP_EXECUTION.md)

```bash
npm run check:architecture
npm run typecheck
npm run lint
npm test
npm run build
```

`npm run check` runs the same permanent gate in order. All application and test
source under `src` is TypeScript; JavaScript remains only in Node/Vite tooling.
`npm run typecheck` validates browser production code with `tsconfig.json` and
Node-based tests/tooling with `tsconfig.node.json`; the browser project does not
receive Node ambient globals. Both projects permanently enforce
`noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`; type-aware ESLint
keeps the six `no-unsafe-*` rules enabled for all TypeScript application, test,
and tooling files. Test discovery accepts both `.test.ts` and
`.test.tsx` at any depth below `src`, including nested `__tests__` directories
and tests colocated with source files.

### Design checks

`npm run check:styles` (part of `npm run check`) reports the design-refactor
metrics and fails when one that has reached zero comes back: class names with no
CSS rule, `!important` outside `prefers-reduced-motion`, native dialogs and the
legacy `--bg-*` colour names. Raw buttons, inline styles and `*-btn` class
families are still falling; each has a ratchet in `scripts/check-style-metrics.mjs`
that fails the check if the count rises. Lower a ratchet when its count falls. A
rule that must win everywhere goes in `src/styles/overrides.css` (the `overrides`
cascade layer) instead of using `!important`. See
[FRONTEND_DESIGN_REFACTOR_PLAN.md](FRONTEND_DESIGN_REFACTOR_PLAN.md) §7.

With the backend and Vite dev server running, capture named UI states in both
themes for before/after review, then pair two runs in a comparison page:

```bash
npm run design:snapshots -- --label before
npm run design:snapshots -- --label after --states market,alerts --viewports 1440x900,1024x768
node scripts/design-snapshots.mjs --compare ../output/design-snapshots/before ../output/design-snapshots/after
```

Snapshots go to `../output/design-snapshots/<label>/` (ignored by git). Steps name
i18n message keys, so `--locale en` captures the English interface.

Stylesheets live in cascade layers (see [DESIGN.md](../DESIGN.md#stylesheets-and-cascade-layers)).
`npm run check:css-layers` (part of `npm run check`) fails on CSS outside a layer.
Before moving rules between files or layers, compare with the base branch:

```bash
npm run css:cascade -- --base main
```

It lists declarations that were added or removed, and every pair of declarations
that can style the same element and would change winner. A pure move reports none.

### Browser smoke check

With the backend and Vite running, use the browser smoke check to verify the
rendered chart, drawing toolbar, lazy symbol search, and lazy Settings panel:

```bash
npm run smoke -- --url http://127.0.0.1:15173/
```

On this Windows Codex desktop environment, use the bundled Node executable if `npm` or `node` is not available on `PATH`.

## Desktop runtime cache

`npm run desktop:package:dir` prepares Python in `.desktop-runtime/runtime`.
After a successful replacement, the cache retains only the immediately previous
runtime as `previous-*` for rollback. Failed preparation removes its own staging
directory; failed promotion restores the active runtime. Dependencies and
first-party plugin bundles are prepared before replacing the active runtime.
Downloaded Python, plugin-build caches, control tools and other builds' staging
directories are preserved.

Promotion and backup pruning use an exclusive `runtime-promotion.lock`. If a
process is terminated during promotion, verify that its recorded owner PID is
no longer preparing a runtime before removing the stale lock and retrying.

The filesystem lifecycle checks can run without downloading dependencies:

```bash
node --test scripts/desktop-runtime-cache.test.mjs scripts/prepare-desktop-runtime.test.mjs
```
