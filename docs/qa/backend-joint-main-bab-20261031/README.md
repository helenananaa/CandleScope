# Reproduce the latest-main joint acceptance

Read `../PR138_144_148_LATEST_MAIN_20261031.md` and `source-identity.json`.
Receipts distinguish source tests, production-browser tests, real-source recovery,
and the native package. The previous native run passed data checks but failed
visual inspection; its report and screenshot are retained as `native-before-viewport-fix.*`.
`viewport-before.json` uses the same typed browser fixture as the passing run.

Install the checkout's pinned backend/frontend dependencies, then run from the repository root:

```sh
python3 docs/qa/backend-joint-main-bab-20261031/run_backend.py
npm --prefix frontend run check
node frontend/scripts/frontend-script-integration.mjs --history-stages \
  --out output/backend-joint-main-bab-reproduction/browser-history
node frontend/scripts/frontend-script-integration.mjs --market-health \
  --out output/backend-joint-main-bab-reproduction/browser-health
```

Also run the existing live Renko/semantic-axis regressions and replay navigation checks:

```sh
node docs/qa/backend-joint-main-bab-20261031/run_surface_browser.mjs
node frontend/scripts/frontend-script-integration.mjs --replay-visible \
  --out output/backend-joint-main-bab-reproduction/replay-viewport
```

These twelve checks use real Chromium and development React `act`; they are separate
from the production React staged-history fixture and native-package evidence. The
surface runner creates its two exclusive temporary fixture files and removes them on exit.

The history fixture includes six custom intervals with staged 128/500/1500 admission,
and the real `SingleChartPanes` component with a deliberately held shared display frame.
Its six viewport cases cover empty/one-row/128-row incoming caches with and without a
saved viewport, then verify 500-row hydration and preservation of manual navigation
through 1500-row hydration. They use controlled data, not a live exchange.

Prepare the bundled Python/control adapter and package the current macOS arm64 app
using the repository desktop scripts. Run the new native harness with a fresh directory:

```sh
CANDLE_JOINT_NATIVE_OUTPUT=/tmp/candlescope-main-bab-native-new \
  node docs/qa/backend-joint-main-bab-20261031/native_acceptance.mjs
CANDLE_JOINT_NATIVE_OUTPUT=/tmp/candlescope-main-bab-native-new \
  node docs/qa/backend-joint-20261031/native_market_settle.mjs
```

This opens the actual package, enables control only in its isolated profile, reads
public OKX futures data, creates four charts with EMA, adds a safe local Pine SMA,
changes 4d/5d, saves, fully exits all owned processes and checks two restarts. Unlike
the earlier harness, it also asserts a usable market viewport after paint. Inspect
the captured screenshot as well. Ports 19679 and 19692 must be free. It does not
install or replace the user's app or touch their profile/database.

For the separate real-source outage test, reuse the first-round portable script with
new output/data directories. It injects disconnection and a three-second scheduling
delay, then compares recovered bars with independent REST reads and waits for a
natural close. Respect provider cooldowns.

```sh
PYTHONPATH=backend CANDLE_DATA_DIR=/tmp/candlescope-main-bab-live-new/data \
  LIVE_PROBE_OUTPUT=/tmp/candlescope-main-bab-live-new \
  .venv/bin/python docs/qa/backend-joint-20261031/live_probe.py
```

Large apps, process logs, SQLite/profile data and intermediate failed candidates
remain in the isolated worktree's `output/backend-joint-main-bab-20261031/`.
`live-okx.json` keeps recovery, parity, delivery and budget evidence plus the raw
receipt hash; repetitive ingestion/tick records remain in that local output.
RSS samples sum process RSS and may count shared pages more than once; they are
observations rather than a memory cap, before/after performance claim or soak test.
