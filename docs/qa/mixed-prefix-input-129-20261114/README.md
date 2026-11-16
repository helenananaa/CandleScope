# Default identity aliases share one repair owner

Runtime fix: `ba1691a3f46f026826e219548436af7af30a2b1d`, based on main `330a831540a50a204262b34f0df70e6da0523d04`. Scope: the shared repair owner used by #126/#127/#129. The original parent completion definitions remain unmet.

## Confirmed defect and change

Native diagnostics showed the same default Binance series using two scheduler keys: a four-part key for HTTP chart history, and an eleven-part key when WebSocket warm-start supplied the explicit default identity. The existing ledger/audit helper already treats these as the same durable series; `RepairRequest.series_key` did not.

The request now uses `repair_series_key` and `repair_series_order`. Default aliases can use the existing per-series queue, covering-request merge, coverage and execution ownership. Non-default provider, venue, asset class, series variant, price adjustment, session and volume semantics retain every dimension. Range, stronger-finality, hydration-lane, generation, cancellation and persistent-interest rules are unchanged; independent requests required by those rules remain legitimate.

This change does not alter aggregation arithmetic, source eligibility, deletion or acquisition fencing, resource limits, concurrency, warmup or readiness thresholds. No new cache, writer, revision ledger or scheduler is added.

## Controlled and engineering evidence

The new real-coordinator tests fail on the original source in both submission orders: ordinary history cannot join an active explicit-default warm repair, and the reverse also fails. Seven semantic-isolation cases already pass on that source. With the fix, both alias orders join the same request ID/future, use one coordinator execution and finish under the existing cleanup path; all seven distinct identity dimensions remain separate.

- Original source: **2 failed / 7 passed** in the targeted regression.
- Fixed coordinator and identity suites: **125 passed**.
- Complete composed backend integration: **2461 passed**, 66 warnings, 400.37 seconds.
- Architecture check: passed, no migration allowlist entries.

These coordinator-owner tests use a controlled engine. Their execution counts are not a measured reduction in real HTTP traffic. The complete integration includes the existing actual SQLite, source/writer, mixed-history, transport, finality, revision, delivery and lifecycle contracts.

## Retained native observations

All runs use a new unseeded macOS arm64 profile and real public Binance USD-M traffic through the existing process-local proxy. No local pytest/benchmark runner overlaps them. Baseline product source `02bbf13ca` has identical backend/frontend product code to main `330a83154`; candidate product source is `ba1691a3f`. These are retained runtime/plugins/desktop/frontend packages with the complete tracked backend overlaid, not fresh release builds.

| Run | Final internal counts: 89m / 97m / 101m / 10007m | Evidence and limit |
| --- | --- | --- |
| `native-baseline-cold` | 16 / 8 / 10 / 0 | Four-chart timed diagnostic; all marketReady values false. First HTTP summary driver read a nonexistent `metadata` field instead of API `cache`, so it proves return counts/timing but not cache reasons. |
| `native-budget-diagnostic` | 6 / 2 / 4 / 0 | Correct API cache summaries plus storage/backfill/public-admission diagnostics. Six 10-second sampling delays; diagnostic API waits add time, so this is not a measured 60-second performance window. |
| `native-identity-cold` | 22 / 7 / 4 / 0 | Original complete joint driver fails the first 128-bar/marketReady gate. Screenshot inspected directly. The explicit-default eleven-part duplicate namespace is absent; separate ranges/contracts can still have separate pending requests. |

All three runs observe zero API HTTP4xx/5xx and no recorded page errors. All 11 owned processes exit in each run. Before/after source hashes for 1006 backend files, unchanged frontend ASAR and strict ad hoc signatures match for both retained applications.

Baseline physical diagnostics show available USD-M request weight without cooldown, local `critical_demand`/endpoint deferrals and persistent seed interests. This does not by itself prove every protected interest is executable or identify a further admission-policy defect. Incomplete mixed inputs and source-revision invalidations remain visible. Those observations motivated the owner audit; the alias defect is established independently by the controlled regression.

The first joint gate remains failed. Canonical nine-field native readback, consumer probes, soak, hide/restore, switch/recreate and saved restart are not reached. These fresh-profile observations are unpaired; no cold-latency speedup, P50/P95/P99, total CPU/RSS/GC benefit or full user-flow qualification is claimed.

## Evidence and reproduction

`evidence-index.json` records finite logs, XML, native receipts, HTTP summaries, resources, package manifests and screenshot hashes. `redactions.json` records structured secret-field redactions. Profiles, databases, applications, plugin installations and connection files stay local; all failures remain retained.

`prepare-native.py` asserts unchanged frontend/desktop/dependency inputs before retaining that verified ASAR and overlays every tracked backend file. `native-baseline-first.mjs` and `native.mjs` preserve the two as-run diagnostic drivers. `native-candidate.mjs` retains the original full joint driver and enriches read-only HTTP summaries. `verify-native.py` verifies both applications and all three full-process exits; `archive.py` archives terminal receipts.

Outputs remain under `output/mixed-prefix-input-129-20261114/`. The native drivers require the retained Playwright QA package, an unused profile/output path, and the exact assembled executable via their existing environment overrides. The two baseline drivers also set package revision `02bbf13ca7521e384c36aacf42884c0016a2f6f7`; candidate uses its own manifest head.
