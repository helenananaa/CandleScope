# Replay chart workspace

## Acceptance contract

One training run owns the clock, market tracks and portfolio. A workspace owns
layout and chart bindings. A chart owns its interval, indicators, drawings and
viewport. Closing or hiding a chart never closes a position or cancels an order.

Reuse the existing workspace layout, editing and link tools. Keep replay storage
and runtime resources separate from the live workspace. Adding a watchlist item
must not select it unless the user asks to open it. Opening targets the active
cell (and its configured market links) or an explicit new split.

History and display projection endpoints already accept track/session/interval
bindings independently of the selected trading viewer. Reuse those endpoints;
do not introduce a second clock or duplicate brokers for chart cells. The global
selected viewer remains the trading/control binding, while chart selection is
persisted per cell. Revisit backend viewer storage only if these existing read
contracts prove insufficient.

## Delivery and evidence

- [x] Run-scoped workspace persistence and shared per-track frontend resources.
- [x] Independent chart interval/projection/history, with revealed-only data.
- [x] Shared layout editing, chart focus and links in the replay page.
- [x] Add-only/current-chart/new-chart watchlist actions and registered-track drag/drop.
- [x] Explicit trading target and stable global stepping interval.
- [x] Recovery of layout, chart analysis and run/account state.
- [x] Regression tests for isolation, duplicate charts and obsolete responses.
- [x] Browser journey: BTC 1m + BTC 15m + ETH 5m + SOL 5m; trade ETH/BTC,
      close ETH chart, advance and recover; verify live workspace isolation.
- [x] Record machine, source, dataset size and browser measurements. Initial
      qualification target: four visible charts, three distinct markets,
      warm local BAR data; control/focus response p95 <= 200 ms excluding data
      preparation, paused warm chart readiness p95 <= 1 s. Report backend pause
      completion separately from immediate UI acknowledgement. Additional chart
      capacities and AGG_TRADE need explicit measured evidence.

Status: implemented and locally qualified on 2026-09-27.

## Architecture and boundaries

`ReplayChartWorkspace` composes the existing workspace repository, layout tree,
cell menu, workspace panel and link coordinator. The active cell supplies shared
page controls through portals; inactive chart canvases remain mounted. Chart
interval selection does not change the global stepping interval. Trading waits
for the active market's authoritative controller binding; stale callbacks and
ReviewMode cannot submit an order through another cell.

Each distinct market adapter has one leased source runtime. Each cell owns its
display/history window, even when two cells show the same market and period.
This allows one chart to page into history while another follows the replay
edge. Source generation changes invalidate pending projections; coarse requests
finish serially and catch up without starvation during playback.

Replay layout storage has its own run namespace and no live workspace bus or
IndexedDB access. Indicators, chart appearance, price scale and viewport are
cell-specific. Drawing evidence uses a bounded v2 envelope of independent v1
chart documents; v1 remains readable. Closed chart documents remain recoverable,
and inherited drawing records are reparented before edits in a fork. Layouts
remain local to their training run; a fork does not clone the parent layout.

## Browser acceptance

Evidence: [four-chart screenshot](evidence/replay-chart-workspace/four-charts.png),
[final cells](evidence/replay-chart-workspace/browser-final.json),
[closed-chart account](evidence/replay-chart-workspace/closed-chart-account.json).

The isolated run `e8b17ed9745649bdb8569978dc5f6cb6` was initialized through the API.
The following interactions were exercised through the in-app browser:

1. Add ETH and SOL without replacing the active chart; arrange the four-chart/
   interval bindings listed above. Search and open ETH in an additional chart;
   close it again without replacing the original cells.
2. Add SMA(20) and a line to ETH, add a separate line to BTC 1m. Refresh and
   recover four chart bindings, independent analysis and the shared account.
3. Link the two BTC charts, enable period linking and confirm both change to
   5m while other symbols remain independent; disable period linking and restore
   BTC 1m/15m. Existing crosshair/range link logic is also covered by workspace tests.
4. Buy paper ETH 0.01 and BTC 0.001. Close ETH's chart and advance one base bar.
   All three server cursors become `1700020859999`; ETH remains FULL due to its
   position, and its mark changes from 2053 to 2057. Restoring the layout recovers
   the ETH chart and analysis.
5. Enter read-only review. Switching active charts leaves the original server
   viewer at track-2, semantic revision 39. Exit back to the original run.
6. Play at five base bars per second, then pause. A five-chart stress observation
   (including a duplicate ETH chart) caught up to one boundary in 905 ms including
   automation round trips. The final four-chart snapshot has no chart errors and
   all cells share boundary `1700027819999`.

Registered-track drag/drop uses the replay track payload and the existing layout
drop target; the browser journey above exercised the explicit opening buttons.
The [untruncated network observation](evidence/replay-chart-workspace/network-window.json)
contains replay endpoints plus development HMR requests, no live market feed.
Storage tests additionally seed a live layout and verify it remains unchanged.

## Measured qualification

Windows, Intel i9-13900HX (32 logical processors), approximately 64 GiB RAM,
in-app Chromium at 1280×720, local Vite development server and local Python API.
The [synthetic fixture](evidence/replay-chart-workspace/synthetic-fixture.json)
contains 4,005 one-minute bars, 801 five-minute bars and 267 fifteen-minute bars
per BTC/ETH/SOL market. These are synthetic QA data, not exchange accuracy evidence.

| Measurement | Samples | p95 | Maximum |
| --- | ---: | ---: | ---: |
| Focus pointer event to two animation frames after active-cell commit | 20 | 159.6 ms | 176.1 ms |
| Paused SOL 1m/5m switch to available chart/context, including automation overhead | 20 | 710 ms | 762 ms |

[Raw final samples](evidence/replay-chart-workspace/performance.json) retain counts
and method. Focus timing is development-only diagnostic instrumentation. Warm
readiness includes a minimum of 200 bars at 1m and 20 at 5m; further history can
load progressively. Immediate focus is separate from backend trading readiness:
an earlier exploratory 20-switch sample had controller-ready p95 1,144 ms including
automation overhead. The UI blocks orders until the binding is ready. The 905 ms
pause observation is one sample, not a p95 claim.

Qualification covers Web single-window, four charts/three BAR markets. Larger
layouts are available through the shared workspace, but 16-chart capacity,
AGG_TRADE performance and native multi-window operation are not qualified here.

## Validation and reproduction

- Replay regression suite: 422 passed. Chart-workspace suite: 104 passed.
- Backend drawing, Phase 17 review, Phase 4 multi-market and training-history tests:
  36 passed.
- TypeScript, ESLint, architecture and all 30 locale catalogs checked.
- Production build succeeded. On this machine, build from
  `E:\Disk0Merged\H\program\CandleScope\frontend` to avoid the existing H:/E: alias
  mismatch between Vite's root and its HTML entry paths. Bundle-size warnings remain.

Use an isolated QA directory for `KLINES_DB_PATH`, `REPLAY_DB_PATH`,
`REPLAY_HISTORY_ARCHIVE_DIR` and `CANDLE_DATA_DIR`. Start the existing
`python -m scripts.replay_smoke_fixture --port 18086 --disable-gap-maintenance`,
with `REPLAY_ENABLED=1`, `REPLAY_HISTORY_ORIGIN_URI=' '` and offline exchange
URLs. After it starts, run
`python -m scripts.replay_workspace_fixture --qa-root <absolute-qa-directory>`.
The latter publishes aligned synthetic native intervals. Repeat publication after
restarting the smoke fixture, which otherwise republishes its original manifests.
Run Vite with `VITE_API_PROXY_TARGET=http://127.0.0.1:18086` and `VITE_DEV_PORT=15186`.
Initialize a BAR run with the synthetic catalogue through the API and open its
`/replay.html?run=<run-id>` page. This evidence does not qualify the archive-download
or training-creation UI under the offline fixture.

Raw local command logs and intermediate screenshots are under
`output/replay-workspace-qa/`; stable evidence is retained alongside this document.
