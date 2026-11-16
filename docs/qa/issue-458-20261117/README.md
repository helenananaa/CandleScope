# Issue #458: bounded target reuse and local reconstruction

This delivers A's implementation and focused acceptance on top of #460/#461
(PRs #464/#465). It closes independently under the split-task rule. Overall
cold net readiness <=3 seconds, separately recorded actual total time, and the
final four-chart/native lifecycle matrix remain #463. #447 stays open. Review,
merge, CI and release qualification are reported separately.

Product backend: `7aaf4b7d1516f87773735bf7d750f0f4098dbe42`, based on
`27592b1e28f43fcebb3da82d13e09e07575f39de`.

## Reproduced defects and resulting behavior

Three real-SQLite regressions fail on the base candidate (`baseline.xml.gz`):
small latest pages re-read closed inputs despite a valid cached preview;
a missing preview falls back over the whole closed prefix; and 64 discrete
holes with unavailable local sources perform 64 count probes. The initial
fix makes those scoped reproductions pass. Further integration retains the
same established target/source/deletion and cache-generation contracts.

The existing canonical closed-target proof now applies to all qualified pages
up to 512 targets, including small pages. Trusted closed values are read and
rechecked before adoption without repeating their sources. Unsupported
identity/calendar/composition, invalid rows, empty cold pages and limits keep
the existing conservative acquisition route. No new cache, downloader or
persistent writer is introduced. Read proofs grant no write authority.

A valid current cached bar remains forming and uses its original cache
incarnation fence. If absent, the verified closed prefix stays useful. Within
the same 2,048-row allowance (including existing source padding), the ordinary
reducer may read **only the current bucket**, with no network admission.
Larger or unavailable overlays remain pending with the existing warm-start/live
owner. They never become a final target gap or a fake final row. Current
optional enhanced fields remain absent when not proven, rather than being
invented as zero. Tests cover current-only numerical values, no persistent
forming writes, and recovery on the ordinary subsequent live cache frame.
This does not replace E/#462's source-gap recovery protocol.

Sparse repair retains the original target history request. It reconstructs
only missing contiguous/discrete windows, caps count probes at 8 per request,
reserves source padding within 2,048 rows, and retains all unhandled holes.
The existing scheduler admission cap and materialization owner remain in
force; a competing query does not wait for the local repair lock or duplicate
its physical reconstruction. Remaining work is explicit pending work, not
coverage fabricated from counts. Count probes only admit an attempt; trusted
source rows, actual finality and durable write fences still authorize output.

Local reconstruction binds its existing target-writer callback to the storage,
consumer/cache, config, resolver, history policy and query service that began
the operation. Rebinding (including public setter A->B->A) is rechecked before
write and after reduction. Late values cannot write through a replacement
storage or remain loaded into the old cache. The existing SQLite acquisition
and original deletion floor still govern the actual transaction. The private
context proof and repair lock are released on normal return, exception and
cancellation. Failure to re-prove the target after a local write returns
pending instead of starting a second full source acquisition budget.

Per-request diagnostics include target range, target/sourced read counts and
rows, local source dependency ranges, consumed/reserved work, count-probe cap,
contention, pending preview and scalar qualification/fallback reasons.
Directional fallback now includes its attempted canonical snapshot I/O.
These are logical storage-adapter/decode and count-probe counters; they are
not a claim to count every SQL statement/fingerprint row inside durable fences.
Actual wall time includes all of that work. Existing `base_storage_reads/rows`
fields remain available on the new fast path, including zero-source hits.
No unbounded request history or market payload is added to diagnostics.

## Focused acceptance

The final related integration selection passes **665/665**, no skips or
failures, in 165.44s. It includes **18 new cases**, closed-target read proofs,
streaming/batch equivalence, listing/calendar/identity boundaries, custom
materialization ownership, cancelled leases, source/cache/publication revisions,
bounded retry, archive routing, mixed planning/transport and #461's fences.
`run-tests.sh` contains the exact selection and sets child `PYTHONPATH`.

An earlier 662-case selection passed 652 and failed ten because the new small
fast path omitted the existing zero-valued `base_storage_reads` metadata key.
That compatibility regression was fixed and the final complete selection
passes. The old forming-row assertion was updated to check the stricter new
behavior: the invalid current final value is excluded, the valid closed prefix
is returned, and current preview remains pending. Invalid/untrusted/truncated
closed rows still decline. Earlier failures remain in the retained reports.

| A contract | Evidence |
| --- | --- |
| Persisted page, base-only history, empty market DB | 15 actual-public-data replay scenarios; fresh isolated SQLite per case; native cold profile separately |
| Necessary latest tail, forming/missingness/write limits | New latest/preview matrix for 89m/97m/101m/10007m; current-only reducer and live-frame recovery cases |
| Contiguous/discrete gaps and bounded work | Existing sparse/withdrawn page tests plus capped-probe regression and real sparse replay |
| Shared owner, late result, rebind and cancel | Existing two-reader/lease tests; new storage rebind/ABA, cancellation cleanup and post-repair proof failure cases |
| Revision/delete/finer-source and enhanced fields | Closed snapshot, cache fencing, source revision, mixed precedence, native/derived/warmup fence integration; independent real-data numeric oracle |
| B/C/E interfaces | Mixed default query, planner, cold budget, CCXT transport, archive routing, stream engine and query-path integration; final joint lifecycle remains #463 |

## Same-input public-data replay

`replay-real-data.py` opens #461's stopped Binance USD-M canonical database
read-only. It copies real rows into isolated disposable databases in five
states for each of 89m/97m/101m: materialized, two discrete holes, base-only,
empty market storage, and materialized history without current preview.
The last scenario freezes replay time to the next bucket, retaining complete
closed minute history and an empty current source bucket. It never relabels
old input as a new live event. This is replay/source evidence, not an actual
exchange session or a native cold-load pass.

The identical script/data run against base #465 and this candidate records
all ranges, adapter reads, rows, fallback metadata and total query time.
The base's contract failures are retained, not suppressed. All 15 candidate
scenarios pass. Every returned closed target is independently compared with
raw complete 1m inputs using first/last, min/max and `math.fsum`, including all
nine OHLCV/enhanced fields; zero mismatches. Empty storage remains pending and
unmaterialized; QueryEngine's pure source read does not itself own network
submission. Actual empty-profile download/queue behavior is observed separately
in the native driver through the normal DataManager/coordinator owners.

| Scenario: source rows decoded | 89m base -> candidate | 97m base -> candidate | 101m base -> candidate |
| --- | ---: | ---: | ---: |
| 32-target page, two missing targets | 2,848 -> 178 | 3,104 -> 194 | 3,232 -> 202 |
| Same history, current preview absent | 2,848 -> 0 | 3,104 -> 0 | 3,232 -> 0 |
| Base history only, 16 targets | 1,424 -> 1,424 | 1,552 -> 1,552 | 1,616 -> 1,616 |
| Fully persisted targets | 0 -> 0 | 0 -> 0 | 0 -> 0 |

In this replay the current bucket has no rows, so candidate source work is
one bounded current-only read returning zero rows. This does not mean every
live preview costs zero reads. Base materialized-only first queries also
returned conservative `storage_revision_conflict` pending results after the
recent seed commits; the new existing canonical proof returns the verified
32 targets without renewing deletion permission. Old/current outputs are not
mixed to create a success receipt.

These are same-input work-count comparisons, not certified speedups. Query
wall times include lazy local initialization: the candidate's first
materialized replay query was 4,799.432ms, subsequent recorded materialized
queries 10.282/11.354ms. Every raw duration is retained; no 3-second claim is
made from these observations. Native startup and demand timing are separate.

## Native evidence boundary

The inherited diagnostic driver is run with issue 458, a new empty profile,
real public Binance USD-M, 89m/97m/101m/10007m, EMA20/60 and frontend-JS close.
It uses a strictly signed retained integrated macOS arm64 frontend/runtime/
plugins with the complete committed backend overlay, not a fresh release.
The existing loopback QA proxy is process-local; OS settings are unchanged.
No market seed or response substitution is used. Original profiles/apps and
control credentials stay local; compressed timelines/logs/traffic, package
hashes, receipts and compact summaries are retained with SHA-256 indexes.

The observation is bounded, not a readiness pass threshold. Exact external
critical-path blocking is not certified, so net readiness stays unknown;
cumulative request durations are never subtracted from actual wall time.
Full same-candidate 128/127-bar numerical/consumer qualification, ten-minute
updates, hide/restore, switching and saved restart continue under #463.
The source regressions, real-data replay and packaged native observation are
reported independently; none is described as Windows or release qualification.

## Native retained result

On Apple M1 MacBook Air / 16 GiB / macOS 26.6.2, the new empty-profile run
observed **734** K-line responses, **582** using the canonical snapshot path.
Across those captured responses, the maximum reserved local source work was
**404 rows <=2,048**, and maximum count probes **8**; **543** decoded zero base
rows. Actual nonzero tail work and all target/source ranges remain in
`native-queries.json.gz`, rather than being hidden behind the zero-source count.
One genuine native input-window mutation rejection remains active.

The independent stopped-database oracle (`../issue-461-20261117/check-canonical.py`)
compares **61 + 59 + 67 = 187** persisted closed 89m/97m/101m targets with their
complete trusted-final minute inputs: all nine fields and boundaries match.
Missing/untrusted/current windows are explicitly outside that oracle's
qualification. No native 10007m numeric/indicator qualification is claimed.
The package's 1,010 backend hashes, unchanged ASAR and strict signature verify
again after execution. The owned process tree exited in **7,636ms**.

Demand starts at `1794838928663`, observation stops at `1794839135295`:
**206,632ms actual wall time**, censored before full four-chart readiness.
Displayed counts at stop are **62 / 60 / 68 / 49**, with loading still pending.
Exact startup duration was not instrumented and belongs to the separate
pre-demand phase. Net readiness is unknown/unqualified. No complete readiness,
continued live-update, consumer numerics or saved-restart pass is asserted.
Unlike the prior development iteration, the final native observation began
after the integration tests and source replays finished; it is still not a
paired performance comparison with earlier candidates.

The run also retains **seven traceback terminal lines** for
`BlockRevisionChanged: history target generation expired` (these are repeated
stack traces, not seven independently established causes). The first cluster
includes the aggregator timeout loop, 10007m dispatch and source delivery;
feed control switches to HTTP polling. The existing
`history_prefix_runtime.hold()` rejects a noncurrent target token. Whether its
recovery completes is unproven. This is handed to E/#462 (with #452's broader
history/live owner boundary) for diagnosis and F/#463 for final live evidence;
it is not erased, called harmless, or used to assert continuous updates.
No root cause or causal independence from this candidate is claimed from the
stack alone. A's qualified read/reconstruction/commit contracts pass the scoped
matrix; the wider realtime recovery remains explicitly open.
