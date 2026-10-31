# Reproduce the three-PR acceptance

Read `../PR138_144_148_INTEGRATION_20261031.md` and `source-identity.json` first.
This folder contains bounded, inspectable receipts; large applications, raw logs,
SQLite/profile files and failed candidates remain in the isolated worktree output.
Do not copy a preparation database into another cache owner or relabel prior evidence.

Run from repository root with the pinned backend requirements/CCXT fork and frontend
lockfile installed in this checkout. The backend runner expects `.venv/bin/python`
and the pytest asyncio, anyio and timeout plugins.

```sh
python3 docs/qa/backend-joint-20261031/run_backend.py
npm --prefix frontend run check
```

Build the native app with its bundled Python and current frontend, using the
repository's desktop runtime/control preparation and macOS package commands.
Then run the actual packaged application with a new isolated profile and data root:

```sh
CANDLE_JOINT_NATIVE_OUTPUT=/tmp/candlescope-joint-native-new \
  node docs/qa/backend-joint-20261031/native_acceptance.mjs
```

This test reads live public OKX futures candles, enables AI control only in its own
profile, creates four charts/EMA plus a safe local Pine SMA, changes periods, saves,
fully quits the main/backend/plugin processes, and verifies two subsequent launches.
It uses ports 19679/19692 and requires the local macOS arm64 package path. It does
not install or publish an application. Use an unused output directory on each run.
Provider availability and quotas can fail the live test; do not bypass cooldowns.
For the separate fresh-order-book check, keep the same output directory and run
`node docs/qa/backend-joint-20261031/native_market_settle.mjs`; it reopens that isolated
profile, waits for a current OKX snapshot, then fully exits.

The real-source outage probe takes several minutes and writes its own SQLite DB:

```sh
PYTHONPATH=backend CANDLE_DATA_DIR=/tmp/candlescope-joint-live-new/data \
  LIVE_PROBE_OUTPUT=/tmp/candlescope-joint-live-new \
  .venv/bin/python docs/qa/backend-joint-20261031/live_probe.py
```

Only the outage and a three-second repair scheduling delay are injected. It compares
each repaired closed bar with an independent REST read and waits for the next natural
close. The 0.75-second strict subscriber is expected to fail independently; default
10-second strict and gap-aware subscribers must continue without recovery errors.
This is one venue/product sample, not all-channel or all-network qualification.

The fixed-input microbenchmark is reproducible with:

```sh
.venv/bin/python backend/scripts/benchmark_custom_history_streaming.py \
  --repeats 3 --out /tmp/candlescope-history-benchmark.json
```

Run it while the machine is otherwise idle. It measures synthetic query execution,
not provider/disk latency or total process RSS.
