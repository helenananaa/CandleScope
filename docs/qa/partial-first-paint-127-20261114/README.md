# Pending history can show its accepted candles

Product source: `02bbf13ca7521e384c36aacf42884c0016a2f6f7`, based on PR #411's final source `f8121ecaf`. This is a presentation change for #127 section 7. It does not meet the parent issues' completion definitions.

The initial history hook already clears loading when a nonempty history response commits. The uncovered path is a live/materialized tail painting while initial history is still pending: the chart previously covered that successful projection with an opaque loading overlay.

`ChartLoadingStatus` uses the existing current-dataset ownership check plus the main projection's successful painted dataset key and a nonempty source window. Only this combination changes the overlay to a small, non-intercepting status. Optimistic transitions, another series, unrendered data and empty replacements retain the opaque overlay. No runtime loading, history proof, indicator deferral, pagination gate, 128-bar threshold or marketReady condition changes.

## Local checks

The full frontend check passes: architecture, plugins, i18n, TypeScript, lint, 5107 functional tests, 1 isolated performance test, 134 desktop tests and production build. The existing React ref cleanup warning and Vite chunk warning remain. The first check's optional-property TypeScript failure and corrected terminal run are both retained. The focused ownership/initial-history suites also passed 50 tests.

The two new rendered-component tests use a real source window and cover pending history, empty replacement, outgoing symbol/interval ownership, optimistic data and absent successful paint. They check that rendering cannot alter source rows or completion/indicator metadata.

## Native observations

macOS arm64 retained native runtime/plugins/desktop, freshly built frontend and all 1006 tracked backend files overlaid; this is not a fresh release build. The assembler asserts unchanged desktop/dependency inputs, repacks ASAR and checks strict ad hoc signature. Before/after source hashes, ASAR hash and signature match. Each run uses a fresh profile with real public Binance USD-M traffic through the existing process-local proxy, without response replacement or database seed. No local test or benchmark runner overlapped either observation.

| Observation | Result | Limits |
| --- | --- | --- |
| Four cold charts, 89m/97m/101m/10007m, two local EMAs each | Final internal counts 70/43/34/0; first three have visible candles and nonblocking loading status | Four-chart witness assertion **failed (3/4)**. 10007m has no data and correctly retains opaque loading. All marketReady values remain false. |
| Single cold 10007m, two local EMAs | Visible candles and nonblocking status while loading remains true; final count 22; focused presentation assertion passes | marketReady remains false. This separate single-chart observation does not replace the failed four-chart result. |

The screenshots at sample 3 and sample 11 were inspected directly. They show real plotted candles and the small bottom status in the witnessed charts, rather than only an internal bar count. They do not prove complete coverage, ideal viewport fitting, nine-field equality, indicator warmup or current forming-bucket correctness.

Both runs observe zero HTTP4xx/5xx and no recorded page errors. Each exits all 11 owned processes. The original joint 128-bar/marketReady gate, canonical comparison, consumer probes, soak, hide/restore, switch/recreate and saved restart remain unqualified. No paired whole-product CPU/RSS/GC or latency percentile result is claimed.

## Evidence and reproduction

- `prepare-native.py`: retains the prior runtime, overlays the committed product source and built frontend, checks package/signature.
- `native.mjs`: retained failed four-chart observation; `native-single.mjs`: separate single-chart observation. Both sample twelve times at 15-second intervals, preserving readiness values.
- `verify-native.py`: checks package source/ASAR/signature after both full-process exits.
- `archive.py`: finite terminal logs, receipts, traffic, resources and screenshots only; profiles, databases, connection files, applications and plugins remain local.
- `evidence-index.json`: source/archive SHA256 and byte counts; `redactions.json`: structured secret-field redaction record.

Use `CANDLESCOPE_PLAYWRIGHT_PACKAGE` for the retained QA tooling package, `CANDLESCOPE_QA_HTTP_PROXY` for the existing loopback proxy, and the two `CANDLESCOPE_AGGREGATION_NATIVE_*` path overrides for an unused output/profile and the exact assembled executable. Retained output is under `output/partial-first-paint-127-20261114/`. Running another observation must use another profile directory.

Remaining product work includes fair cold completion and the large-period historical/live initialization costs; making accepted candles visible does not resolve those backend costs.
