# Bounded dispatch work when foreground capacity is full

Runtime source: `b97628d261e314d3729ea11cd3aadb237ed32205`, based on main `765d012e3ba3451dbda0ee115a5e6df0e48b3778`. Scope: #127 scheduling work, with the original #126/#129 contracts preserved. Parent completion definitions remain unmet.

## Confirmed defect

The deliberately single-lane scheduler allowed a second candidate slot while checking for its maintenance reserve. Even when its sole task was foreground work and no candidate could use that reserve, every incoming demand popped, examined and requeued all waiting chunks. With N waiting requests, repeated enqueues caused quadratic decision work, and each pop itself searched/rebuilt the heap.

The original source fails both new single-lane regressions: 16 pending requests cause 136 inspections; 64 cause 2080. The two full-capacity two-lane controls pass. The tests exercise the real coordinator with a controlled blocked engine and a linear decision-work allowance; they do not measure real HTTP savings.

## Change

Drain now examines the queue only when ordinary dispatch has capacity or the existing single maintenance task can offer its interactive reserve. Capacity is rechecked after dispatch, so newly started maintenance can still admit a foreground reserve within the same drain. The existing per-candidate admission, priority/aging, identity, cancellation, finality, quota and concurrency checks remain in force.

No work is discarded or marked complete. No new queue, cache, writer, revision log or resource limit is introduced.

## Verification

- Original source: **2 failed / 2 passed**, including both two-lane controls.
- Fixed coordinator, interest-priority and public-admission suites: **170 passed**.
- Complete composed backend integration: **2465 passed**, 66 warnings, 580.35 seconds.
- Architecture check passes without migration allowlist entries.

Existing related tests preserve the maintenance/foreground reserve, bounded recovery aging, three/four-owner rotation, cancellation and quota/dependency behavior. Overlapping suite counts are not added.

## Native evidence and limits

Both applications use retained macOS arm64 runtime/plugins/desktop/frontend, with all 1006 tracked backend files overlaid. The frontend source/dependency inputs and ASAR are unchanged; this is not a fresh release build. Source hashes, ASAR hash and strict ad hoc signatures pass before/after the observations. Each run has a new unseeded profile and real public Binance USD-M traffic through the existing process-local proxy.

| Run | Product source | Scope and result |
| --- | --- | --- |
| `native-diagnostic` | `ba1691a3f` | Diagnostic-only bounded admission/lifecycle wrappers. Original first gate fails. All 11 owned processes exit. This is not performance qualification. |
| `native-dispatch-cold` | `b97628d26` | No diagnostic bootstrap; original complete joint driver, with live-data checks enabled. First 128-bar/marketReady gate fails; failure-state internal counts are **14/0/4/0**, all unready. All 11 owned processes exit. |

The candidate screenshot was inspected directly: available candles are visible with pending status, and empty charts retain loading. The first gate fails before canonical nine-field readback, consumer probes, live-frame qualification, soak, hide/restore, switch/recreate and saved restart. Enabling those later checks does not mean they ran.

The candidate observes zero API HTTP4xx/5xx and no recorded page errors. Its backfill snapshot records 194 fairness rotations, 387 submitted requests, 366 dedupes, 6 merges, 227 ready chunks and one running task. Physical fetch counters record six HTTP pages and 39,984 fetched bars, including archive work. Observed sidecar CPU is 206.67 seconds. These are one run's counters; different request windows, inputs, completed work and source waits prevent a paired comparison. No user-visible cold-load speedup, P50/P95/P99, total CPU/RSS/GC benefit or full product qualification is claimed.

The read-only diagnostic trace is bounded (256 entries per kind, 1024 per process). It preserves original admission results and lifecycle results/exceptions, but logs/imports add overhead and the trace can truncate later events. It records mostly ordinary startup admission ordering and one protected seed/catalog interaction; it does not establish a new quota-policy defect. The capacity defect is proved separately by the controlled regression.

## Reproduction and retention

`prepare-native.py` retains the verified frontend/runtime, asserts unchanged retained inputs and overlays the complete committed backend. `native.mjs` preserves the original joint flow and read-only HTTP summaries. Use the retained Playwright package, unused output/profile and exact executable through its existing environment overrides. Candidate qualification omits `CANDLESCOPE_QA_LOG_BOOTSTRAP`; the diagnostic run additionally supplies `bootstrap/` and package revision `ba1691a3f46f026826e219548436af7af30a2b1d`.

`verify-native.py` checks both applications, driver SHA256, diagnostic flag and full-process exits. `archive.py` retains finite terminal logs, XML, receipts, HTTP summaries, resource samples, bounded traces and screenshots. `evidence-index.json` includes source/archive SHA256 and byte counts; `redactions.json` records structured secret-field redactions. Profiles, databases, connection files, applications and plugin installations stay local. Outputs remain under `output/seed-admission-evidence-129-20261115/`; failures are retained.
