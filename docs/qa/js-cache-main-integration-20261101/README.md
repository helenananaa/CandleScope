# JS shared-input acceptance after main integration

Application source `6847f1c017a6498553a7b904f994e1691bef75dd` combines PR #178
with main `a4dc6e5374a719a98e9a8e8d797170f4448279aa` (B130 aggregation and
H127 history reader). This follow-up commit adds evidence only.

## Validation

- Full frontend check: 4,673 tests, one isolated performance gate, 124 desktop
  tests, architecture, plugin boundaries, i18n, TypeScript, lint and build passed.
- 155 history-reader/shared-aggregation/backend integration tests passed.
- A freshly built, relocated arm64 ZIP used its bundled backend and isolated
  profile with real public Binance HTTP/WebSocket data. No responses were replaced.
- Two charts retained independent scripts, parameters and historical views.
  All closed OHLCV and JS values were compared against backend data. Repeated
  cold ETH/5m, SOL/15m and XRP/3m switches back to BTC/1m passed.
- After 125 seconds minimized and genuinely disconnected, both charts caught up
  by at least two closed minutes in 16,824 ms. Historical time range and zoom
  remained unchanged; the recovery budget was 45 seconds.
- Saved charts, scripts, parameters and zoom survived restart. Reopening follows
  the existing latest-bar policy. Two normal exits took 18,654 and 15,799 ms;
  all captured application descendants exited and backend ports closed.
- Removing each input released only its subscription. Final subscriptions and
  blob Workers were zero; no renderer exceptions occurred.
- 963 packaged source files and 163 frontend build files matched byte-for-byte;
  strict signature verification passed before and after execution.

See [acceptance.json](acceptance.json), [checks.json](checks.json),
[package.json](package.json) and [restart screenshot](restart-1.png).

## Harness corrections and scope

Earlier failed attempts are retained under the local output's `attempt-01` to
`attempt-04` directories. They exposed harness assumptions: a sibling left at
the live tail naturally advanced; its 500-row window did not contain index 700;
the first healthy reconnect snapshot preceded catch-up; and calling `app.quit`
while retaining Playwright's Node debugger delayed process termination.

The final checks pin valid historical sibling ranges and wait for actual closed
bar advancement. The saved fourth-attempt profile was resumed without reseeding.
The retained receipt includes its earlier timeout and the continuation. The
continuation performed another complete save/normal-exit/restart cycle using
Playwright `app.close` (app.quit followed by inspector detach), without signals.
The original cold-switch/offline evidence was preserved, not relabeled as a
single uninterrupted run.

The scripts are the exact local QA harness and include execution-machine paths.
This qualifies the local macOS arm64 package only. Windows/x64 installation,
notarization, real-provider historical corrections and the broader 157-item
acceptance matrix are outside this receipt. Cloud CI must pass at the submitted
head before merge.
