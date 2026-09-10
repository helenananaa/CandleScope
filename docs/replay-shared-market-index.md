# Shared market indexes and on-demand replay advancement

This replaces session-specific preparation of the next 100,000 BAR account and
builder states on supported native-history runs. It follows
[the earlier first-preparation investigation](replay-first-preparation-work.md).

## Data ownership and execution

Immutable Parquet objects now have disposable `.shared-market.v1.sqlite`
sidecars. Import builds each index from the rows already owned by the writer;
reimport of the same indexed object reuses it. The index stores normalized rows
in compressed 256-row blocks and a tree of OHLCV, close extrema, and ordered
maximum upward/downward price changes. Positions, orders, balances and training
IDs are excluded. Different runs and processes reuse the same files.

Opening a supported run constructs a lightweight view over these objects. It
does not generate future per-minute account samples, future builder checkpoints
or a serial per-event hash chain. A price-envelope query screens orders and
the existing coordinator cuts at funding, simulation, rule and risk boundaries.
Potential interactions still execute through the original precise path.

Within a certified interval, account extrema are derived from the ordered price
summaries. A conservative precision check requires the affine calculations to
fit the original 60-digit context; unusual precision falls back to the original
scalar account formula. Flat accounts need no price evaluation. The final
builder reconstructs only its retained tail, bounded by its configured window,
rather than applying every skipped base bar. Validation checks the immutable
range against each expected contiguous source segment, including verified halts.

The existing displayed-bar query uses the same shared summaries with its
revision, calendar bucket, partial-bucket and revealed-boundary rules. Unsupported
combinations retain their prior path. Current fast-path scope remains one FULL
BAR/HEDGE track with the existing account/book/funding restrictions, and a
base-interval adapter. This does not broaden tape or historical-book execution.

## History, recovery and compatibility

New `_training_shared_indexed_interval` commands declare their own reference
semantics. Shared source ranges and builder prefixes use versioned range
references instead of pretending to reproduce the old serial hashes. Financial
values and execution ordering remain equivalent; legacy hash byte identity is
not asserted for these commands.

Actor checkpoint payload v4 includes a source anchor bound to the same immutable
snapshot. Recovery positions the source at that anchor and replays only any
ordinary tail. Legacy v2/v3 checkpoints and old indexed commands retain their
original interpretation. Rollback restores the source anchor along with the
broker and cursor. A recovered full weekly run was checked with source `next()`
forbidden: no old source events were replayed and its stored state hash matched.

Equity journals store shared object/range references plus the small account
basis. Detailed samples are reconstructed when requested. The first full curve
read still has linear expansion cost; the weekly benchmark measured about
1.2–1.4 seconds. It is separate from command acknowledgement and chart updates.

The SQL schema remains version 21, but old code cannot interpret shared commands
or v4 payloads. A code rollback after shared advancement must restore the
pre-update database backup. Sidecars can be removed and rebuilt from pinned
original objects; they are not the authority for trading history.

## Old data and background work

The current requested range is indexed first if an old object has no sidecar.
Remaining already-local objects in the same frozen catalog are queued in one
background lane, with upcoming objects first. File inventory also runs in that
lane. It does not download remote objects merely for background indexing.
Shutdown cancels the queue; builds observe cancellation between blocks and
publish atomically. Reader-registry locks are not held during reconstruction.

Missing or corrupt derived records rebuild from the checksum-bound original.
An unavailable index write path leaves the original archive usable through the
fallback. Original data corruption is still an error. Very first use of an old,
unindexed object can wait for its one-time upgrade; a normal newly imported or
already indexed object does not require that work on opening each training run.

## Evidence, 2026-09-10

All artifacts are under `output/replay-latency-sampling-20260909`.

| Scenario | Observed time |
| --- | ---: |
| Actual existing run, one-time old-data index build | 8.002 s |
| Same real data, new isolated process opening prepared range | 0.237 s |
| Normal backend, deployed build opening preparation for 100,000 events | 0.218 s |
| Isolated weekly fixture, opening preparation | 0.764 s |
| Immediately following first week advance | 0.392 s |
| Chrome-triggered opening preparation | 1.012 s |
| Chrome-triggered first week advance, including display tail | 0.596 s |
| Full-week recovery with no source-event replay | 0.380 s |

These are individual measurements, not latency percentile guarantees. The Chrome
numbers are HTTP operation durations, not click-to-paint timings. The page was
clicked normally and its rendered weekly candle was checked: O104/H107/L99/C103.5,
volume 100.80K, paused at 2024-03-17 23:59:59. Screenshot:
`shared-browser-week.png`. The synthetic fixture's pre-existing market-picker
setup warning remains outside this test's scope.

The weekly test skipped 10,046 of 10,079 source events, with 8 write transactions.
Its 3 actual cash postings and 6,984 retained equity samples match the preserved
independent per-event reference database. Source/state hashes intentionally
reflect the new representation. The real user's progress was never advanced;
all real-run preparation checks compared cursor, revision and state hashes.

An intermediate normal-backend opening measured 2.728 seconds. Subsequent work
moved inventory into the background, reused whole-object/root summaries and
avoided reader-cache churn; subsequent unprofiled openings measured 0.172 and
0.218 seconds. All measurements remain in the evidence.

Validation includes 161 broad replay scenarios, with one initial test-fixture
failure: its SQLite corruption writer was still open on Windows. Closing that
writer resolved the exact failure. Final focused coverage passed 47 cases,
followed by 8 range/background cases, 38 import/archive cases and 12 command/
display-tail cases, plus 10 final range/precision/schedule checks. Coverage includes exact financial outcomes, order/funding/
liquidation boundaries, hidden time, review forks, rollback, recovery, corruption
repair, read-only fallback and cancellable background work. Raw failed and
passing logs are retained; no failed invocation is labelled fully green.

The normal service is updated locally. No commit or push has been made for this
shared-index work or the preceding uncommitted preparation improvements.

Deployed backend: port 18080, observed PID 42712. The normal frontend remains on
15173; isolated UI servers on 18082/15175 were stopped. Pre-deployment backups
include `output/replay-latency-20260909/before-interval-replay-4600.db`,
`before-interval-replay-36276.db` and `before-interval-replay-1252.db`, with their
dataset object directories. The latest readiness receipt is
`cold-cache-live-shared-delivered.json`.
