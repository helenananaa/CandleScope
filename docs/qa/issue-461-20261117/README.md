# Issue #461: bounded warmup revision proofs

This is the D subtask's implementation and focused acceptance. Overall cold
net readiness <=3 seconds, separately recorded actual total time, and the final
four-chart/native lifecycle qualification remain #463; #447 stays open.
PR review, merge and release qualification are separate from scoped closure.

## Reproduced failure and fix

The retained #460 run-2 backend log reports run `ae510a3b1809`: 1,511 fetched
minute rows, 1,500 committed, no generated targets, followed by
`warmup change receipts do not cover the acquisition`. Its 21,744ms reconcile
report includes waits and is not a certified local critical-path duration.
The raw original log and routing receipts remain in
`../issue-460-20261117/evidence/`; they do not expose the original acquisition
revision, so the exact revision arithmetic below is a deterministic
reconstruction, not a claimed measurement of that historic run.

`test_second_native_batch_survives_own_large_commit_after_disjoint_live_tail`
captures acquisition revision 0, then writes a disjoint live tail (revision 1),
then commits 1,500 owned rows (head 1,501). Its owned interval starts at 1 rather
than 0. The next 11-row batch previously demanded global receipts 0..1,501,
while the existing journal retains only 1,024 changes. It failed despite an
unchanged, captured native range. The new path checks that same native range
fingerprint under SQLite's writer transaction, checks affected targets and the
original source AND target deletion floor, then records owned revisions and
adopts digests only after successful commit. It does not enlarge the journal,
renew deletion permission, weaken nondefault identities, or add retries.

A second reproduction uses the actual built-in Reconciler. Between canonical
read/reduction and target SQL commit, a disjoint same-source tail plus 1,100
unrelated ETH updates evicts the mixed-computation receipt suffix. The original
code rejected valid closed BTC targets. For the qualified default Binance
USD-M built-in fixed 1m reducer only, a complete dense input window of at most
8,192 rows now retains the digest of the exact rows actually consumed. The
writer rechecks that digest, the target digest and original deletion floor.
It never captures a fresh post-compute digest that could bless stale output.
Sparse/partial, off-grid, larger and true mixed-grid computations keep their
existing conservative receipt proof. A custom reducer or dedup hook cannot
obtain this input permission.

The reducer's storage/config/hook binding is checked after CPU work and again
inside the actual SQL writer transaction. Hook setters increment a binding
revision so A->B->A rebinding cannot revive late work. Existing planner,
materialization lease, cache adoption and publication generation fences remain
in force. No new downloader, durable market writer, source cache or retry loop
is introduced. Additional diagnostics are capped at 12 flat scalar fields per
existing bounded failure entry; no payload, callback or owner object escapes.
Deletion rejections include acquisition revision, original deletion floor and
observed deletion revision. Other rejections include proof head/range and,
where applicable, actual overlapping change range/receipt limit.

## Scoped acceptance map

| Contract | Focused evidence |
| --- | --- |
| Own 1,500+11 writes with independent live tail | New regression; original failure reproduced before fix |
| Closed canonical read/compute/commit under journal overrun | Real SQLite + Reconciler, write batch sizes 1 and 500; no reacquire/retry |
| Real correction, delete+restore, empty-range delete, target correction | New negative matrix and existing native/derived/mixed fence suites |
| Transaction rollback | Injected SQLite trigger; digest and owned receipts remain unchanged; retry succeeds after trigger removal |
| Late owner and A->B->A hook rebind | Mutation while awaiting actual target upsert; all stale writes rejected |
| Sparse/partial/off-grid/multi-grid/oversized input | No consumed-input permission granted |
| Source identity and finer-source precedence | Native/OKX/derived range, mixed precedence and mixed planner regressions |
| Query/reconcile overlap and cancel/resubscribe | Materialization ownership, cold budget, cache fencing and revision-contract regressions |
| Durable commit before cache/publication, old notifications, bounded conflicts | Source revision pipeline, revision-contract and query-cache fencing regressions |
| Independent numerical oracle and idempotence | New varying OHLCV/enhanced-field test uses direct groups and `math.fsum`; second commit does not advance durable revision |
| A/B/C/E interface integration | Default mixed query, pipeline, CCXT transport, cold budget, archive routing and history-fetch stream regressions |

The broader initial run passed 381 tests and failed one because its spawned
Python process could not import `app` without `PYTHONPATH=backend`. That failed
report is preserved. The final selection uses the correct environment and
includes the added negative qualification tests plus cache/planner integration.
This is a focused selection, not a repository-wide pass.

## Native evidence boundary

The source-routing native driver is reused with
`CANDLESCOPE_QA_DIAGNOSTIC_ISSUE=461`. It launches the retained integrated macOS
arm64 frontend/runtime/plugins with a complete committed backend overlay,
strictly signed and hash-verified; it is not a fresh release build. It starts
with an isolated empty profile and real public Binance USD-M sources through
the existing local QA proxy. Startup is separate from demand observation.
The driver records actual wall time, source/commit diagnostics, traffic and
owned resources, then exits the owned process tree. Its bounded observation
window is not a readiness pass gate. Net readiness stays unknown unless exact
external critical-path blocking can be certified; cumulative request times are
never subtracted from wall time.

`check-canonical.py` reads the stopped native SQLite database in read-only mode.
For 89m/97m/101m it independently verifies persisted closed targets whose full
dense trusted-final 1m input set is present, including all nine OHLCV/enhanced
fields and time boundaries. It explicitly reports missing/untrusted/current
windows as skipped. It does not prove missing targets, mixed 10007m composition,
chart/indicator adoption, ten-minute updates or saved restart; those remain
#463. Raw profiles/apps/control credentials are not published.

## Recorded results

Product backend: `9a5ec8d152633149b3acc47bd09776a37c97f7c6`, stacked on
#464's `360831809da3db8235b258ba1804c5f3435377e8`.
The package's 1,010 tracked backend hashes, unchanged ASAR hash and strict
signature all verify again after execution. Hardware: Apple M1 MacBook Air,
16 GiB RAM, 8 logical CPUs; macOS 26.6.2 (25G83). No Windows qualification.

The new scoped matrix passes **20/20**. Both original reproductions fail before
the fix and pass afterward; `baseline.xml.gz` retains the exact errors. The
initial 136-test fence/ownership/mixed selection passed. All earlier failure
reports are retained rather than replaced by later successful checks.

The native run's shared demand observation starts at `1794837119097` and stops
at `1794837325766`: **206,669ms actual wall time**, censored because the full
four-chart readiness condition was not reached. At stop, displayed counts were
46 / 42 / 39 / 2 for 89m / 97m / 101m / 10007m. Startup was a separate phase;
its exact duration was not instrumented. Four exact-input snapshots covered
4,308 consumed rows. Neither `warmup change receipts do not cover the acquisition`
nor `mixed computation receipt suffix is unavailable` occurs in the retained
backend log. One genuine `mixed target changed during acquisition` is still
rejected; the exact-target fingerprint check remains active. Nine sampled
reconcile runs wrote 5,444 source bars and reported one revision conflict;
these cumulative counters are observations, not per-chart latency or throughput.
The owned process tree exited in 12,865ms.

After exit the direct SQL/math oracle checked **45 + 41 + 39 = 125** persisted
closed targets against their complete trusted-final minute inputs, including
all nine OHLCV/enhanced fields and grid boundaries: **zero mismatches**. These
are all stored qualified 89m/97m/101m targets in that stopped database, not a
claim that the required 128-per-chart history is present. No native 10007m
numerical or consumer/lifecycle qualification is claimed.

This native diagnostic ran concurrently with the broader test selection, so
its timing/resource data also include competing local test activity. It is not
a performance comparison. Net readiness remains unknown/unqualified and #463
continues to own the complete final-candidate matrix. The run's raw `passed:false`
reflects that broader readiness boundary, not a replacement D461 closure gate.

One concurrent integration run passed 416 tests and observed an intermittent
extra CCXT loopback request (six instead of five) in `full-32`; its completed
report and failure are retained in `final-integration.xml.gz`. The same transport
matrix passed in the earlier broader run. Final verification is run after the
native process exits, with `PYTHONPATH=backend` also supplied to child Python
processes. `run-tests.sh` records the exact focused selection.

The evidence directory retains compressed raw reports, native timeline, public
traffic, backend/process logs, package source manifest, numeric output and
compact summaries, indexed by SHA-256. Apps, SQLite profiles, plugin runtimes,
control connections and credentials stay in local output. No seed data,
response substitution, new retry loop or persistent authority was added.

Final post-native verification passes **417/417**, with no failures or skips
(`acceptance-tests.xml.gz`, 160.82s). No further product change was made.
The 20 new scoped tests also pass independently. The native manifest
metadata was corrected after the run to identify the new product tree rather
than inheriting its base tree; packaged bytes and their verification are unchanged.
