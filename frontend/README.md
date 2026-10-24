# CandleScope Frontend

React/Vite charting UI for CandleScope.

## Architecture

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
