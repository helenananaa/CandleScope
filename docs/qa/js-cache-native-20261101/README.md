# #178 installed macOS arm64 acceptance — 2026-11-01

The ZIP built from `8c5eb02bc027d42d8afdb60171193972520068b3` passes this local
installed-app scope. It was extracted to a separate installation directory and
launched with a fresh, isolated profile. `app.isPackaged` was true and the backend
used the Python executable inside the application bundle. Public Binance HTTP and
WebSocket data were real; no market responses were substituted. Later evidence-only
commits do not change the tested application sources.

## Native defect and repair

The original `0dcb049a` ZIP failed twice: moving the left chart to historical data
and switching BTC/1m to a cold ETH/5m or SOL/15m market produced `Value is null`
from Lightweight Charts line-style refresh. The left error boundary replaced the
chart, while the right chart kept running. Runtime readiness alone still reported
ready, so acceptance now requires both rendered chart surfaces and numeric output.
`original-failure.json` and `original-cold-switch-error.png` preserve this failure.

The repair commits indicator data before changed series options and skips options
whose values are unchanged. Native-scene identity changes still update their
autoscale closure. The browser driver now fails on renderer exceptions. A staged
real-chart browser case was added, but its unfixed control did **not** reproduce
the native failure; it is supplementary regression coverage, not the proof of the
repair. The rebuilt ZIP repeated the failing ETH/5m and SOL/15m paths, added cold
XRP/3m and returns to cached BTC/1m, and finished without renderer exceptions.

## Verified behavior

- Two unlinked charts retain separate JS input subscriptions and private history
  windows while sharing one BTC market subscription. Closed OHLCV and every JS
  close/scale/offset point were compared with the bundled backend's range rows.
- Editing right-chart parameters and script leaves the left chart unchanged;
  moving the left historical viewport leaves the right viewport unchanged.
- Removing one input preserves its sibling. Removing both leaves zero input
  leases and zero JS computation Workers. The two drawing Workers belong to the
  still-mounted charts; all application/backend descendants exit at final quit.
- HTTP offline plus minimization lasted 125,002 ms. CDP offline alone did not close
  existing WebSockets, so the test explicitly closed this application's actual
  sockets with native `WebSocket.close(4001)`, with no response replacement.
  The stream was observed closed, then reconnected. Two additional closed minute
  bars were recovered and rechecked; the historical viewport stayed fixed.
- A full process exit and restart restored both charts, scripts, parameters and
  zoom. Existing `planVisibleRangeRestore` intentionally opens at the latest bar
  after reopening; its tested contract does not restore an old historical anchor.
  The initially stricter probe and its policy resolution remain in the receipt.
- Final rendering errors: zero. Final owned processes: none. The bundled backend
  port was closed. The installed bundle passed strict signature verification again
  after execution.

## Provenance and limits

`package.json` records archive/ASAR SHA-256, the tested tree, changed-source hashes,
and comparison counts. All 163 packaged frontend output files matched a clean
desktop-mode rebuild; packaged backend and desktop source bytes matched the
checkout. The full 3,079-file source hash inventory and logs are retained under
`output/pr178-native-fixed-20261101` along with the ZIP, profile and automation
drivers. The original failed archive and logs remain separately under
`output/pr178-native-20261101`.

`native-acceptance.json` and the three fixed-package screenshots contain the native
observations. `local-checks.json` records 4,673 frontend tests, one isolated
performance gate, 124 desktop tests, the complete frontend check, 12 indicator-flow
browser cases, and the JS/editor browser suite. Both browser runs finished without
exceptions or retained Workers. Existing cleanup-ref and bundle-size warnings remain.

This qualifies local macOS arm64, not x64/Windows or notarized distribution.
Real-provider historical amendments were not observed; correction-notification
proof remains controlled-browser coverage. #164's wider result-subscription and
recovery consolidation remains open. This evidence does not qualify replay #180.
CI was not awaited and this work does not merge main.
