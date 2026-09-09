# Replay incremental updates — 2026-09-09

Implemented locally; this is a focused performance qualification, not a full Replay release acceptance.

## Changes

- A single DISPLAY_BAR advance can opt into `include_display_tail=true`. The response carries at most two server-authoritative display bars in `data.display_tail`, under the Run serialization barrier. Durable command results and execution semantics remain unchanged.
- Clients apply the tail only against the matching run, session, track, interval, data epoch and previous public boundary, with overlap at the existing last bar. Cold views, missing overlap, historical windows and incompatible responses retain the full projection recovery path.
- The market-tracks stream supplies ordinary account updates. A 750ms cursor-convergence check requests REST recovery only if the stream has not caught up. The hidden integrity drawer no longer refreshes its equity curve on every step.
- Replay MACD and VOL maintain bounded per-view incremental state. The first computation is compared with the Python server result. Context/parameter changes, history corrections and unsupported implementations use the server. SMA seeds, EMA recurrence, histogram sign/color and Python eight-decimal ties-to-even rounding are preserved. A Python-generated fixture exercises every prefix, repeated last-bar updates and resets.
- Hidden full-order-book views can pause presentation delivery using a negotiated protocol capability. The server continues draining its bounded subscription and holding its source lease; it skips display aggregation/serialization. The next visible delivery is a full snapshot. This does not suspend underlying market-data collection.

## Validation

- Replay frontend: 394 passed.
- Order-book frontend: 11 passed.
- Focused backend (commands, source grids, projection CAS, account stream and full-book delivery): 68 passed.
- TypeScript, targeted ESLint, Ruff and `git diff --check`: passed.
- Windows production build: passed from the physical workspace path `E:/Disk0Merged/H/program/CandleScope/frontend`. Running the same build through the H: alias exposed a pre-existing Vite HTML root/realpath mismatch; no unrelated build-configuration change was made.

## Browser results

Metric is click to the application's chart/indicator update event, not a direct compositor paint measurement. Small sequential samples use different market bars; they are not a statistically controlled p95 benchmark.

| Scenario | K-line update | VOL update | HTTP per step |
|---|---:|---:|---:|
| Before: development app, live market page active, two replay indicators | 672–792ms | 1015–1212ms | 5 |
| After: development app, two indicators, warm samples, no second live page | 367–410ms | 529–575ms | 1 |
| After: production app, two indicators, order/account panels and live page with 10 indicators/full book active, five samples | 551–657ms | 609–747ms | 1 |

The after-production samples were K-line 657/559/555/551/590ms and VOL 747/632/609/616/657ms. Each command returned two display bars; no separate display-projection, tracks, equity or indicator compute HTTP request was observed during these steps. Display count advanced exactly once per step and the run stayed PAUSED.

An earlier production run had no indicators because the preview port has separate browser preferences. It is retained as a separate artifact and excluded from the matched-indicator comparison. Cold-start and occasional longer backend waits remain. The simulated-hidden integration test verified sending `set_display_active:false` without closing the connection, but its three latency samples were noisy (586–1561ms to chart update); it does not establish a reliable speedup. Visibility overrides were removed afterwards.

## Remaining limits

The feature is faster but not universally instantaneous. Concurrent real-time ingestion and visible market panels still share CPU/GIL resources with replay. This change does not move those workloads into separate processes or broadly refactor React subscription boundaries. Indicator formulas update incrementally, but input-prefix validation and output-array construction remain linear in the bounded displayed window. Other builtin/custom indicators retain their existing compute path.

Evidence is in `output/replay-latency-20260909/`: `fixed-dev-*`, `fixed-production-matched-*`, `fixed-simulated-hidden-*`, test/build logs, and the earlier diagnosis/profile artifacts. Backend startup uses the original process environment and a SQLite backup was taken before restarting it.
