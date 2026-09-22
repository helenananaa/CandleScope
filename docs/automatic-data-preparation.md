# Automatic history preparation

Approved scope: all four phases of the 2026-09-21 proposal. Status below records
implemented and verified work, not intended capabilities. Existing replay and
strategy execution/accounting semantics remain authoritative.

Current delivery status (2026-09-22): stage checkpoint, not full four-phase
acceptance. The full-application native preparation that previously waited on
rate limiting has completed; see the final checkpoint below. Earlier sections
are chronological evidence and may describe limitations subsequently addressed.

Checked items have implementation and the focused evidence described below.
They do not replace the cross-phase browser/live-provider acceptance. In particular,
the complete four-phase goal remains open while unchecked items remain.

## Phase 1 — automatic preparation and launch

- [x] Durable bounded preparation jobs, exact frozen ranges, idempotency and API.
- [x] Fetch missing BAR history through BackfillCoordinator; validate and publish.
- [x] K-line launcher: empty inventory to prepared archive to playable training.
- [x] Strategy FAST/BAR: prepare immutable input then run the submitted revision.
- [ ] Progress, cancellation, retry and reopening jobs without losing drafts.

## Phase 2 — sharing and recovery

- [x] Shared immutable chunk coverage and consumer manifests.
- [x] Overlapping requests share work; cancellation releases only its own demand.
- [x] Restart recovery, atomic publication, retry-safe consumer launch.
- [ ] Retained input references and bounded storage cleanup.

## Phase 3 — precise and dependent inputs

- [x] Supported trade archive acquisition and pinned trade snapshots.
- [ ] Multi-interval/multi-symbol dependency planning and warmup.
- [ ] Required funding/rules/mark/account roles through capability-aware providers.
- [x] Unsupported/unavailable inputs fail explicitly without fidelity downgrade.

## Phase 4 — progressive preparation and cache management

- [x] BAR prefix readiness and immutable extension without premature completion.
- [x] Pause at unavailable boundary and resume safely when data arrives.
- [x] Low-priority bounded recent-history prefetch, subordinate to foreground work.
- [ ] Download/storage budgets and reference-aware cache controls.

## Acceptance

Use actual adapters in isolated storage. Verify empty and partially populated
inventory, reuse, overlapping consumers, cancel, restart, failed publication,
offline profile, changed user intent and no duplicate launch. Browser acceptance
must cover starting BAR training and a strategy run without visiting the data
workbench. Track acquisition, publication, opening and first advancement
separately. Mocked tests do not establish live provider availability or UI latency.

No remote push or release publication is part of this implementation request.

## Implementation checkpoint — 2026-09-21

Implemented (qualification is still in progress):

- `app/data_preparation`: SQLite journal, frozen requests, half-open day fragments,
  shared acquisition observers, process ownership, retry, cancel and restart.
- BAR acquisition uses existing BackfillCoordinator demand leases and trusted
  finality; complete replay archives are checked before mutable host storage.
- Atomic compressed acquisition objects, referenced cache cleanup, existing
  replay archive and LocalDatasetService publication adapters.
- `/data-preparations/replay` prepares missing history, creates an idempotent
  training run and initializes the submitted market. `/strategy` freezes the
  submitted strategy revision, parameters and execution settings, prepares an
  immutable context, validates it and queues the strategy through the existing
  worker. Leaving the page does not prevent this launch.
- Replay task progress/list/retry/cancel/open UI; leaving preparation stops the
  observer, not the backend job. The strategy context is frozen before execution.
- `AUTO_HISTORY_PREPARATION_ENABLED=0` prevents new jobs/retries and recovery
  execution while leaving existing task/cache metadata readable.

Evidence so far: 15 focused backend tests including real archive publication and
readback, real strategy snapshot/resampling, empty-archive training creation and
initial market attachment, restart ownership, partial-overlap reuse, atomic cache
reservations and reference-aware cache cleanup. Expanded backend regression:
66 passed (system Python `D:/anaconda/python.exe`); frontend regression: 51 passed.
The older `backend/venv.bak` can run focused tests but lacks ccxt,
exchange_calendars and orjson for the application-level suite. Typecheck and
i18n key completeness
passes across 30 locales; new copy outside Simplified Chinese/English currently
uses English and needs localization review.

## Second implementation checkpoint — 2026-09-21

- Official Binance USD-M futures trade acquisition reuses the existing checksum
  importer and engine archive. Independent selections in the same UTC day share
  one import. Verified daily coverage is required; a last observed trade is not
  treated as proof of complete time coverage. Download bodies are capped at
  256 MiB; open UTC days and unsupported sources fail explicitly. Checksums do
  not trigger automatic retry; transient transfers may retry.
- BAR and AGG_TRADE replay launch, FAST and PRECISE strategy preparation use the
  same durable service. Tape replay also prepares the BAR catalog/warmup input.
  Engine-owned trade objects are retained when acquisition receipts are cleaned.
- Strategy launch is idempotent by preparation ID. The STARTING barrier persists
  the exact resolution; recovery reuses it instead of selecting a new dataset.
  Existing complete immutable strategy snapshots can bypass downloads. Original
  strategy submissions are retained for idempotency across resolution-token and
  local-inventory changes. Generic job submission cannot inject strategy launch
  authorization; the dedicated route applies the existing operator policy.
- Warmup planning uses the registered builtin declaration and frozen parameters,
  the actual chart-Pyne compiler lookback, and supported Python bundle warmup
  declarations. Calendar months use the interval policy's real month boundaries.
  Explicit windows acquire a warmup prefix; ALL_AVAILABLE uses its first bars as
  warmup instead of requesting history before listing. The execution receives the
  warmup count and prepared range. Native multi-symbol work is detailed below.
- Replay creation loads preparation capabilities and keeps manual/existing
  paths for unavailable or unsupported account modes. The client observes the
  backend-created strategy run without issuing a duplicate create request.
- Persistent preparation cache allowance, reference release and bounded cleanup
  are available in the task panel, also accessible in strategy history. The
  allowance currently accounts acquisition receipts conservatively, not every
  physical copy in the engine stores. The UI describes this as an input allowance.
- Opt-in prefetch considers markets used at least twice in the last week, prepares
  at most one additional historical day, excludes tape/auxiliary inputs, and
  reserves a foreground worker slot. Prefetch receipts remain reusable but do not
  hold permanent task references. Turning the option off cancels pending prefetch.

Current tests additionally cover checksum rejection, shared disjoint trade-day
imports, real trade replay startup, precise strategy snapshots, backend strategy
launch and duplicate suppression, frozen-launch recovery, calendar and compiled
warmup, cached strategy reuse, persistent settings and foreground/prefetch
scheduling. These use real archive/snapshot/engine code with controlled source
responses; they do not establish browser qualification.

Expanded regression at this checkpoint: 89 backend tests passed (including
application lifecycle, offline profile, existing replay creation and the official
trade importer), 53 frontend tests passed, and i18n completeness passed across 30
locales / 4429 keys. Existing FastAPI `on_event` deprecation warnings remain.

A bounded live-source smoke also passed: official Binance USD-M LTCUSDT
2020-03-01 daily package, 2 MiB download ceiling, selected first hour containing
1602 rows, selected archive objects 1534866 bytes, 6.763 seconds for first import
and validation. Receipt and repeatable script are under ignored
`local_docs/automatic-preparation-qualification/`; dataset epoch is
`sha256:16331f141b2dfc6a0f48734292dbb0d170cf0610520a6a036c7745e786a45a47`.
This single archived day is not evidence of every market/date's availability.

Native dependency checkpoint: `/data-preparations/native-strategy` now prepares
minute inputs shared across multiple symbols and display intervals, freezes each
context, and starts the existing native plugin run idempotently. Literal
`request.security` and `request.security_lower_tf` contexts are discovered in
source and supplied libraries; dynamic requests require explicit declarations.
Calendar dependencies include the preceding completed bar. This is not a claim
of arbitrary script lookback inference or complete warmup for every requested
expression. Minute-or-coarser dependencies are supported; subminute requests fail.
The native chart panel offers a UTC date range and automatically observes the
durable preparation. Imported datasets and manually selected advanced inputs keep
their existing paths; automatic Magnifier selection is still pending.

Eight new backend tests cover parsing, calendar ranges and a real multi-symbol
snapshot/native-run lifecycle with only plugin IPC replaced by a controlled
runner. They verify native account authority, duplicate suppression and separation
from host strategy runs. The focused preparation suites passed 37 tests, and
24 native/chart-request frontend regressions passed. Typecheck and targeted lint
passed; localization completeness now covers 4431 keys across 30 locales. Browser interaction and
actual plugin execution for this new entry point remain unverified.

Cache GC now commits coverage removal and a durable deletion journal before
unlinking bytes. Restart drains pending deletions before workers run; an interrupted
unlink cannot leave deleted coverage visible. Pending bytes retain their allowance
until deletion completes. Objects adopted by a new acquisition are retained.
Cleanup defers while preparation jobs are queued/running to protect the gap between
physical object writing and receipt publication. Three fault-injection cases cover
interruption before/after unlink and re-adoption by a new owner. The combined cache,
prefetch, native and trade suites passed 37 tests after this change.
Expanded backend regression including application lifecycle and replay paths now
passes 100 tests, with four pre-existing FastAPI lifecycle deprecation warnings.

Exact-account dependency checkpoint: automatic replay preparation now runs the
existing account archive planner before BAR/tape acquisition. It selects verified
historical mark/rule/funding inputs, persists their immutable reference at the
STARTING barrier and passes that reference to initial market binding. Missing
inputs stop the task with `AUXILIARY_HISTORY_UNAVAILABLE` before downloading BARs;
the account and funding modes are preserved. The launcher advertises this path
only when the exact-account manager is enabled, with a fixed manual start and
book mode OFF. This is automatic reuse of verified operator captures, not a new
remote auxiliary archive provider. Existing source requirements and engine checks
still apply; public funding rates alone do not constitute an exact account archive.

Real archive/engine fixture tests cover automatic exact binding and missing-input
failure; the focused backend preparation/native/trade suite passes 36 tests and
the replay hub frontend suite passes 32, including retained exact funding mode.

Progressive source foundation: `replay/progressive_history.py` persists a fixed
minute-bar horizon and an append-only directory of verified archive revisions.
Publication validates a bounded segment outside the writer transaction, then
atomically advances the contiguous ready boundary. Existing segments cannot be
replaced; missing pages raise `DATASET_PENDING` without exposing actual times.
`ProgressiveBarReplaySource` uses that directory with independent cursors and a
stable source identity. Pending data does not mean cursor exhaustion. Tests use
real immutable archives and verify restart, append, changed-horizon rejection,
holes, cursor stability, independent forks and final source equivalence.

This source is not yet connected to training creation, checkpoint restoration,
archive retention, or actor/UI waiting transitions. Automatic preparation still
advertises `progressive: false`; no end-to-end progressive capability is claimed.

Actor waiting checkpoint: autonomous playback now commits a `data_pending` pause
when the next immutable page is not published. It retains the clock at the last
committed event and does not finalize the account. Availability is checked on a
bounded timer; publication commits `data_ready` and resumes playback. Explicit
pause or controller loss clears that resume intent. PLAY/STEP attempted too early
fail without moving the cursor or reducer state. Actor checkpoint restoration at
the pending boundary is supported and remains paused after restart. Tests cover
automatic continuation, explicit stop, and restart without duplicate events.
Training-level creation/restoration, archive retention and UI integration are
still pending; the public progressive capability remains off.

Session integration checkpoint: ReplayService can create a progressive session
with the original full horizon and a verified initial snapshot. Its persisted
paging manifest has a distinct schema and restores the same durable feed through
the existing SQLite session path. Hidden-time sessions shift page timestamps into
their synthetic timeline. Real service tests exercise prefix playback, pending
STEP, shutdown/restart, immutable extension and full-horizon completion in both
ordinary and blind modes.

Archive GC now retains every revision in the managed progressive directory, even
after a newer catalog becomes current. Publication and GC share the archive
mutation lock. Progressive directories must live in their owning archive so GC
cannot silently miss them. A real GC test verifies both bound revisions remain
readable. Feed-reference release on training deletion still needs lifecycle wiring;
retention is currently conservative. The training preparation producer and UI
still do not activate progressive playback.
The expanded session/progressive/archive regression passes 55 tests; targeted
Ruff checks pass. This does not qualify the pending training/producer/UI wiring.

Training prefix integration checkpoint (2026-09-22): the internal training
creation path now persists the original full request plus a progressive feed ID
and the initial prefix length in its durable selection. Materialization reads that
saved immutable selection, preserves TOUCH_OR_TAPE execution, and writes the full
requested end to the session/training records while keeping only verified prefix
rows in the initial dataset. Recovery uses the saved plan, including when the
archive catalog advances after a failed attempt. Real service tests cover ordinary
and hidden-time execution-mode restoration, successful prefix-only training
creation, and interrupted creation followed by durable retry. The preparation
producer and empty-run market admission do not invoke this path yet.

Focused progressive service tests pass 6 cases; targeted Ruff and diff checks
pass. The expanded training/session run passed 59 cases and found one unrelated
existing failure in test_replay_v2_training_phase1.py: its obsolete-schema matrix
includes version 22, whereas current schema.py migrates version 22. Neither file
was changed by this work. The fixture creates only a version column and migration
then fails on missing applied_at_ms; this failure is recorded rather than hidden.

Progressive producer/UI checkpoint (2026-09-22): empty-run creation and initial
market admission can use a published prefix while storing the full original
setup. Automatic BAR preparation now plans a deterministic 256-minute prefix
(or the full horizon when shorter), publishes immutable contiguous feed segments,
creates the training once at the prefix barrier, and continues its durable job
through the remaining day fragments. Recovery no longer marks a launched
progressive task complete prematurely. Retry and cancellation retain the existing
run result; cancelled tail work leaves its already-published history readable.

The replay preparation endpoint accepts progressive=true; capability advertises
it when BAR import is available. The hub selects it only for MANUAL BAR,
ONE_WAY, APPROX_PROXY, book OFF. Other model requirements retain complete-input
preparation and are not silently downgraded. The replay observer opens a committed
run while the job is RUNNING; ordinary strategy observers still wait for READY.
The task panel already links an available run regardless of download completion.

A real API/SQLite/archive/training test, with controlled provider responses,
proves prefix-time launch and BASE_BAR advancement, followed by tail publication
and advancement to the complete horizon. Four cases cover normal completion,
preparation-service restart, failed-tail retry and cancellation. The restart/retry
cases retain one run and do not download the prefix twice. This is not yet live
provider or browser qualification. Progressive training/service coverage now has
8 cases, including empty-run creation and stored-prefix retry. Frontend observer
and hub tests pass 35 cases. The expanded backend suite passes 90 tests; frontend typecheck, targeted ESLint,
Ruff and diff checks pass. Advancing beyond the available prefix returns a pending
error and preserves the source cursor without marking the training ended.

Progressive revealed-history and ordered-playback checkpoint (2026-09-22):
qualification found that duration-mode history still used only the initial
snapshot after the source advanced into a later segment. History pages now query
the original pre-start revision plus each committed feed segment through a
bounded repository adapter. Existing durable-cursor checks remain authoritative;
a later download does not reveal future rows. Tests read minute/two-minute pages
across the prefix boundary and reread an older revealed boundary after completion.

Qualification also found a mailbox deadlock: a read-only source plan reaching an
unpublished segment terminated the actor without answering its dequeued request.
Pending source-plan/goal-scan requests now return DATASET_PENDING without stopping
the actor. The global training playback loop treats that condition as a bounded
wait, resets elapsed wall time, and resumes after publication. Explicit pause
clears play intent. Pending preflight no longer marks a required track failed.
The API/training test matrix now passes 12 cases spanning manual/automatic/paused
playback and normal/restart/retry/cancelled preparation. The existing dense-tape
playback regressions pass 2 cases; the broader history/control/progressive suite
passes 53 tests. Targeted Ruff and diff checks pass.

Progressive source-grid/held-position checkpoint (2026-09-22): source-aligned
viewer projection now uses the progressive segment reader as well as history
pages. It streams bounded minute pages into exchange-grid bucket summaries before
mapping public time, including forming buckets and calendar months. Progressive
sessions bypass unrelated native-display archive selection and remain bound to
the exact minute revisions used for execution. Ordinary sessions retain their
existing native-display selection path. Reader initialization is lazy, so ordinary
history requests do not create a progressive index.

Eight comparisons (2m/3m/5m/monthly, closed-only/forming) match the complete
archive source-bucket projection, with nonempty monthly forming-bucket coverage.
The preparation journey now opens and holds a position across segment boundaries
on a changing-price series. Its account and position match a separate complete-
input training at the same final cursor. Manual, automatic and explicitly paused
playback work with normal/restarted/retried/cancelled preparation; three additional
cases cover ALL_AVAILABLE history. Minute/coarse history and source-aligned
projection include later segments and keep earlier reveal boundaries. Browser,
live-network, short-position/funding and larger calendar-range performance
qualification remain outstanding; these fixture checks do not substitute for them.
The combined progressive/history/archive/native-seam suite passes 77 tests;
targeted Ruff and diff checks pass.

Outstanding: real provider/browser qualification and performance/rollback evidence;
physical-size accounting including publication copies; dynamic dependency UI and
complete native warmup/Magnifier planning; funding/rules/mark/account providers;
progressive broader financial scenarios (short/funding/multiple tracks),
large-range performance and feed-reference release. The public
progressive flow is connected for the supported BAR mode; its browser experience
and the remaining phase acceptance checks are not yet qualified.
No phase is declared fully accepted by these checkpoints.

Browser checkpoint (2026-09-22): a separate localhost FastAPI service uses the
real preparation API, SQLite stores, immutable archive, training service and
WebSocket routers, with a controlled BAR coordinator. In the real frontend,
an initially empty archive accepted automatic preparation and navigated to
`prepared-4e751b2ec47e4895a82f05c90ef70879`. After connection setup, 200 warmup
bars and the initial 00:06:00 clock were visible. Six 50-base-bar advances reached
05:05:59, beyond the 256-minute initial publication; switching to 5m displayed
61 bars at the same clock. This verifies navigation, continued execution and
coarse projection with controlled data, not live-network throughput or first-chart
latency. The fixture initially omitted the stream router and used a warmup limit
below the UI default; those fixture settings were corrected before these checks.

The fixture's 64-source-event command cap rejected a 300-bar command with HTTP
413. Its error previously disappeared when a successful viewer refresh cleared
the shared error state. The control bar now retains its own command failure until
the next control attempt or run change; the browser confirms the rejection stays
visible without advancing the clock. Automatic creation copy now describes market
selection and automatic preparation instead of the old post-creation picker flow.
The related 62 frontend tests, TypeScript checks, targeted ESLint, i18n check
(30 locales, 4432 keys) and diff check pass. Batch advancement's displayed 1m bar
count grew less than the source cursor; this needs a separate continuity check
before claiming chart completeness. Progressive waiting before tail publication,
native strategy UI, live BAR acquisition and the outstanding lifecycle/budget
items above remain unqualified.

Browser continuity follow-up (2026-09-22): the incomplete 1m count was a viewer
notification-coalescing bug, not missing archive rows. A frame with many APPEND
notifications retained only the last changed range, so the tail projector skipped
earlier appends. Coalescing now retains all changed ranges, including the prior
bar's closing TICK, and tail projection starts at their earliest time. This keeps
the existing incremental rendering path without adding a history request per tick.
A sequence-based regression closes a forming bar and appends fifty bars in one
frame, then compares every projected row against the complete source projection.
All 26 projection tests and 59 related series/history/workspace tests pass,
as do TypeScript, targeted ESLint and diff checks. In the running browser, the
recovered 1m view displayed 456 bars at 05:05:59; one 50-base-bar advance displayed
506 bars at 05:55:59. The earlier batch-continuity concern is resolved for this
controlled-provider path. Remaining live-provider, lifecycle, budget and other
phase acceptance items above are unchanged.

Progressive reference lifecycle checkpoint (2026-09-22): new feeds have durable
preparation-owner references, and new sessions/forks acquire their own reference
before persistence. Creation compensation releases a reference only after any
durable session compensation succeeds. The fenced deletion path releases session
references only after confirming that the corresponding durable row is gone.
READY/CANCELLED preparation cache release also releases the producer reference;
FAILED jobs retain it because they remain retryable. GC now retains progressive
revisions through remaining owners, with old indexes protected by an atomic,
archive-lock-guarded migration that installs conservative legacy references.

The 37 progressive/history/service/preparation tests pass, including restart,
independent consumers, cache-release API followed by continued held-position
execution, and deletion of the final session. Ruff and diff checks pass. An
additional GC assertion verifies that a superseded catalog manifest becomes
collectible after the last owner releases it. Current catalogs retain their
objects under existing archive policy; this is not a claim that every released
feed immediately frees its physical data bytes. Legacy-reference reconciliation,
crash-orphan reference cleanup and complete physical-budget accounting remain
outstanding before lifecycle/storage acceptance.

Crash-orphan reference checkpoint (2026-09-22): session owners now include a hash
of the owning replay database path. Before startup recovery, the service loads
all durable session IDs (including ended/degraded sessions) and removes only
absent owners in that database's scope. Unknown, legacy and other-database
references remain protected. The check reads lightweight IDs, not full dataset
objects. This covers a process interruption after acquiring an archive reference
but before persisting a session, and interruption after deletion but before
releasing its reference. Moving a database preserves the old unknown scope
conservatively; it does not authorize deleting that scope's references.

The 38 progressive/history/service/preparation cases and 16 existing service
regressions pass. Tests inject an interrupted-creation owner before restart,
preserve other databases and legacy owners, restart an ended session and verify
its data remains pinned until explicit deletion. Ruff and diff checks pass.
Unscoped legacy-owner attribution and full physical storage budgeting still
require completion; this does not claim every historical orphan was reclaimed.

Live BAR qualification (2026-09-22): a fresh isolated K-line database and replay
archive ran the actual BackfillCoordinator, BackfillEngine, TransportLayer,
sync/async KlinesRepo adapters and preparation API. BTCUSDT Binance spot at
2024-03-01 00:00 UTC requested 20 warmup minutes plus a 120-minute horizon.
The task downloaded, published and automatically created a replay run. The first
run reached READY in 4.544 seconds. A second fresh directory added explicit row
and transport evidence: 140 rows, exact minute continuity/close times, all with
backfill provenance, two plugin transport requests sent and two successful.
It reached READY in 3.558 seconds and produced the same data epoch as the first
run (`sha256:2feec2429bc810e56f62de8d12087d4bf5cbee37ef3a5009598680919f62a501`).

The reproducible local script and latest receipt are
`local_docs/automatic-preparation-qualification/live_bar_smoke.py` and
`local_docs/automatic-preparation-qualification/live-bar-smoke.json` (ignored
qualification artifacts). Existing application data was untouched. This is
actual provider-to-run evidence for a small spot BAR request; it does not establish
large-range throughput, progressive early entry before a long tail, futures BAR
or strategy/plugin execution qualification. These timings are individual smoke
runs, not a latency benchmark. The remaining acceptance items retain their scope.

Cache physical-object accounting checkpoint (2026-09-22): the acquisition storage
view now counts a shared immutable receipt once across coverage records and
pending deletion. Reference bytes and engine-owned receipt bytes use the same
deduplication, so overlapping logical coverage no longer consumes multiple copies
of the cache budget. View migration is transactional. Tests retain a shared object
until both owners release it and verify that reclamation charges exactly one file.

Before workers start, the BAR adapter reconciles its acquisition directory under
the preparation lease and a directory ownership lock. An atomically published
owner marker binds it to one preparation database; a different database cannot
start a competing writer in that directory. Unreferenced canonical cache objects
and interrupted UUID temporary files are removed, while recorded inputs, unknown
filenames and files present when an older directory is first adopted are retained.
Cleanup drains its storage thread before releasing the lease on cancellation.
The 50 preparation/prefetch/progressive/native tests and targeted Ruff checks pass.
This improves acquisition-cache accounting/recovery only: publication copies,
legacy retained files and complete physical-budget enforcement remain outstanding.

Publication accounting checkpoint (2026-09-22): the preparation journal now
registers published files by canonical path and charges each once in the same
storage-budget view as acquisition objects. BAR publication registers its Parquet
objects, shared market indexes and catalog metadata. Strategy publication registers
the frozen dataset directory and resolved standard/native dependency snapshots.
Each publication unit checks the measured budget before progressing further or
launching its consumer. Later requests also include registered publication bytes
in admission. The cache panel displays registered publication usage separately.
Startup and explicit cache cleanup refresh known file sizes; a physically removed
file stops consuming the measured budget. Refresh uses the registered file list,
not a full archive scan on every UI poll.

The 51 preparation/progressive/native/prefetch tests pass, including physical
path deduplication, over-budget rejection, external file removal reconciliation
and real BAR/index/catalog registration through progressive launch. Targeted Ruff,
ESLint, i18n (30 locales, 4433 keys) and diff checks pass. A publication can reach
its bounded write boundary before its actual size is known; this is not a hard
filesystem quota. A process interruption before registration can leave uncharged
publication files, and existing legacy files/session-object copies/trade-import
temporary files still need complete accounting and reservation integration.
Consequently full physical storage acceptance remains open.

Publication crash-reconciliation checkpoint (2026-09-22): configured BAR archive,
replay session-input object storage and strategy dataset directories are now
registered durably before workers run. A cancellable background inventory finds
files that survived a crash before per-file registration, including retained
legacy files and staging files inside those scopes. Overlapping scopes still
charge each canonical file path once. Directory symlinks/junctions are not walked.
Preparation waits for successful inventory before acquisition; service startup
does not wait for the directory walk. Completed/failed publishing jobs request a
coalesced background refresh, and shutdown signals the scan to stop and drains it.
Inventory state is visible in the cache panel; incomplete scans cannot silently
authorize a preparation run, and retry performs a new scan.

The combined 56 preparation/storage-inventory/progressive/native/prefetch tests
pass, as do typecheck, targeted Ruff/ESLint, i18n (30 locales, 4435 keys) and diff
checks. New cases cover unjournaled/staging bytes, overlapping scope deduplication,
cancelled inventory, nonblocking startup, cancellation while waiting and retry
after failed inventory. The storage journey initially hit its inherited one-second
controller lease during restart work; it now uses the existing production default
of ten seconds. No production controller policy or expiry gate was changed.
Trade-import staging outside these scopes, shared mutable host-history storage,
reservation/peak enforcement and old owner attribution still need final accounting
work; full storage acceptance is not yet declared.

Live automatic-launch checkpoint (2026-09-22): isolated empty host storage now
qualifies both Binance spot BAR replay preparation and Binance USD-M futures
FAST strategy preparation through the actual BackfillCoordinator, engine,
transport, immutable publication and consumer services. The spot sample fetched
140 one-minute rows, opened its prepared training run and matched the same epoch
across two fresh runs. Its 120-minute horizon fits the first progressive prefix;
this is not evidence of early entry during a long remaining download.

The futures sample fetched BTCUSDT for 2024-03-01 00:00–02:00 UTC plus four
five-minute warmup bars. All 140 downloaded one-minute rows were compared against
the immutable snapshot: exact timestamps, closed status and Decimal OHLCV values
match. Resolution produced 28 five-minute bars. The built-in RSI strategy worker
completed with nine simulated fills, accepted quality and zero missing, duplicate,
invalid or out-of-order rows. Report dataset/epoch/snapshot/config/strategy identity
matches the created run; no fill precedes the requested trading start. Reposting
the same request retained exactly one run. Funding is OFF and contract data is
LEGACY_FIXED_V1; this does not qualify native Pine/Pyne plugins or exact historical
contract execution.

The futures sample measured 2.424 seconds to preparation readiness and 5.215
seconds including execution and shutdown, with two successful provider requests.
These small API smoke timings exclude browser rendering and are not benchmarks.
Receipts, a report and an offline snapshot/report verifier are retained under
ignored local_docs/automatic-preparation-qualification (live-strategy-smoke.json,
verify_live_strategy.py and live-bar-875b08f5fb/qualified-report.json). The reusable
live script now fails qualification unless execution completes and report identity,
quality, fill trace and trading-start boundaries pass. Remaining cross-phase
acceptance includes strategy/browser reopening, long-tail progressive browser
waiting/resume, native plugin dependencies, auxiliary providers and full physical
storage accounting/reservation.

Trade physical-accounting checkpoint (2026-09-22): the background inventory now
includes the configured raw-trade archive, including manifests, indexes,
quarantine and preparation download staging. Official automatic imports place
scratch directories under that archive instead of the system temporary directory;
the standalone importer's default scratch policy is unchanged. Successful and
failed trade preparations request a post-job inventory even for PREFETCH consumers.

A durable receipt-to-file mapping replaces aggregate trade receipt charges only
after every referenced object appears in the file inventory. Disjoint selections
sharing Parquet objects therefore charge their physical paths once. Partial
inventory retains the old conservative receipt charge. Referenced bytes use the
same physical mapping. Forgetting preparation receipts never reports engine-owned
archive files as reclaimed, and their physical charge survives cache GC and restart.
No archive data is deleted by acquisition cache cleanup.

The combined 73 preparation, trade-import, inventory, progressive, native and
prefetch tests pass. New cases cover shared files, legacy receipt migration,
incomplete multi-object inventory, restart, receipt GC and interrupted download
files; the actual controlled official importer verifies its scratch directory is
inside the registered archive. This is physical inventory accounting, not a hard
write quota: shared mutable Host history, peak reservations and enforcement during
publication still require completion. Directory scans are background and bounded
by cancellation checkpoints; they do not establish constant-time storage work.

Shared Host storage checkpoint (2026-09-22): application wiring now supplies the
actual KLINES_DB_PATH to preparation. Inventory persists exact file scopes for
the database and its WAL, SHM and rollback journal, including sidecars that do not
exist yet. It never inventories the database parent directory. A later WAL is
counted; after checkpoint/close its removed bytes disappear from the ledger.
BAR acquisition refreshes only these four file entries after download and checks
the measured budget before writing acquisition cache or publishing a snapshot.
All preparations, including BAR prefetch, request a coalesced post-job inventory.
Shared Host files are measured but never deleted by preparation cache cleanup.

The cache panel identifies shared market-history usage and describes the expanded
archive/storage allowance. Its budget input now starts from the persisted value;
toggling prefetch preserves the saved budget instead of resetting it to 2048 MiB
or submitting an unsaved edit. Only the Save settings action applies a budget edit.

The 66 preparation/storage/progressive/native/prefetch/trade tests and eight
application-lifecycle/offline-profile tests pass. New tests use a real SQLite WAL,
check late sidecar creation and checkpoint removal, exclude an unrelated sibling
file, and verify that download-induced database growth blocks snapshot publication
while retaining the downloaded data. Targeted Ruff/ESLint and i18n completeness
(30 locales, 4436 keys) pass; existing FastAPI lifecycle deprecation warnings remain.
This measures the whole shared database, including previously acquired market
history; a large existing database can require increasing the stored allowance.
It is still a sampled physical budget, not a hard concurrent-writer quota or a
complete peak-reservation proof. Those enforcement requirements remain open.
Frontend TypeScript checks also passed for the shared-usage and budget controls.

Acquisition write-reservation checkpoint (2026-09-22): compressed BAR cache writes
now reserve their exact compressed byte size in the preparation journal before
opening a temporary file. The budget check and reservation use BEGIN IMMEDIATE,
so concurrent writers cannot each spend the same remaining capacity. Existing
receipts and pending writes share the receipt-deduplicated storage view. Publishing
a chunk converts its pending write charge to the normal cache charge in one
transaction, with no uncharged window and no duplicate charge for reuse.

Failed writes remove their temporary file before releasing the reservation.
Cancellation after atomic file replacement can leave a charged, recoverable write;
idle cache cleanup reclaims that orphan, while active jobs fence cleanup. Restart
removes owned orphan files and only releases reservations once their byte objects
are gone. Startup now checks directory ownership before pending-write deletion,
so a misconfigured second preparation database cannot clean another owner's cache.
No acquisition-cache path bypasses these reservations when run by the service.

The 72 preparation/cache-write/storage/progressive/native/prefetch/trade tests
passed before the additional startup-order regression; the final targeted cache,
preparation and inventory suite is recorded below. Cases cover two concurrent
writers, exact compressed size, atomic promotion, same-object reuse, failed replace,
interruption before/after file replacement, idle cleanup and a conflicting directory
owner. Ruff and diff checks pass. This closes the BAR acquisition-file write gap;
archive/snapshot publication and official-import expansion still need their own
peak reservation boundaries. It does not impose a hard quota on independent live
writers to the shared Host database.
Final targeted verification after the startup-order fix: 39 tests passed.

Publication working-space checkpoint (2026-09-22): each bounded replay archive
fragment and primary strategy snapshot now reserves working space before invoking
its writer. The estimate uses serialized source bytes, per-row SQLite/index
headroom, fixed temporary/metadata space and the current replay catalog size.
Reservations are admitted transactionally against occupied storage, so concurrent
publications cannot spend the same capacity. Successful registration of the final
files and release of the working-space reservation share one SQLite transaction.
Actual file sizes remain authoritative after publication. These are conservative
working-space estimates, not a hard upper-bound proof for every writer or an OS
filesystem quota.

An exception marks the reservation abandoned without releasing it immediately.
Recovery first inventories the registered directories, including files that were
renamed successfully before the failure, and only then releases abandoned holds.
Inventory snapshots the abandoned IDs before scanning; a publication that fails
after its directory was scanned remains reserved until a later complete scan.
Startup marks the previous process's active holds abandoned under the service lease.
Cancelled/failed inventory cannot discard a hold. Normal BAR/strategy publication
can retry the same job after the user increases the allowance, reusing acquisition
inputs and without writing the snapshot/archive while storage-blocked.

The broad 78 preparation/publication/cache/storage/progressive/native/prefetch/trade
tests pass, followed by six focused publication tests including an injected failure
after a real strategy snapshot rename. Those cases cover concurrent admission,
atomic settlement, interruption, late abandonment during inventory, replay/strategy
rejection before writing and successful retry. Targeted Ruff and diff checks pass.
Inspection of chart-context resolution confirms native multi-context binding uses
already-frozen inputs; it does not call the separate materialization writer.
Official trade-package expansion and replay session-input copies still need their
peak reservation boundaries. Shared Host writers remain independently managed.

Official trade-import working-space checkpoint (2026-09-22): automatic imports
now reserve download/checksum/quarantine working space before the first request.
The transfer ceiling adapts to remaining measured allowance, up to the existing
256 MiB provider-transfer cap. A quota-limited transfer reports STORAGE_BUDGET
rather than a provider failure. Reservation admission is transactional even when
two markets import concurrently.

The official importer exposes an optional callback after checksum/schema/row
verification and before archive import. Preparation uses verified CSV member size,
row count and downloaded ZIP size to resize its working-space estimate; it checks
free disk space as well. CSV remains streamed from the ZIP, with no full extracted
copy. If expansion does not fit, no Parquet is written. The existing failure path
retains quarantined download evidence; its hold remains charged until successful
inventory replaces it with measured files. Successful per-day archive registration
and hold release are atomic, and the acquisition receipt is mapped to those files
before chunk publication to avoid a temporary double charge. Existing verified
archives still bypass download. Standalone callers retain the importer defaults.

The 26 trade-preparation, official-import and publication-space tests pass. New
cases verify rejection before network access, expansion rejection after real CSV
verification but before any Parquet, retained quarantine accounting, quota-limited
error classification, increased-budget retry and no duplicate physical charge.
Ruff and diff checks pass. The expansion allowance is a conservative estimate,
not a proof of a strict filesystem maximum. Replay session-input copies and final
cross-phase acceptance remain outstanding.

Replay session-input checkpoint (2026-09-22): automatic launch now scopes an
optional storage policy through task-local context to replay's object writer.
The policy propagates through the existing persistence task and to_thread worker,
without changing concurrent manual launches or coupling the replay store to the
preparation implementation. New session snapshots reserve their exact compressed
size before opening the temporary object. Atomic replacement is followed by
transactional measured-file registration and reservation release. Existing shared
objects need no additional reservation. Failures retain an abandoned hold until
inventory reconciles the object, including failure after a successful rename.

The end-to-end space-block test initially exposed blind replay wrapping the budget
exception as a generic creation failure. The preparation adapter now recognizes
its own chained STORAGE_BUDGET error and returns a data-free actionable message;
the engine's blind error contract is unchanged. Raising the allowance and retrying
the same preparation successfully attaches one session to the same training run,
without a duplicate run or an object written during the rejected attempt.

The 29 session-object/preparation tests pass after that fix. Expanded object-store,
recovery, progressive and trade regression passes 62 tests; Ruff and diff checks
pass. Tests cover exact compressed accounting, duplicate reuse at zero remaining
space, task/worker context isolation, failed registration after rename and the
real API retry journey. This closes the replay input-object publication boundary;
it is not a quota on training journals, financial history or independent writers.
The original goal remains open: native dependency lookback/declarations, auxiliary
history providers, browser draft/reopen and long-tail progressive interaction still
need implementation or final qualification, as recorded in the phase checklist.

Native requested-context warmup checkpoint (2026-09-22): automatic planning now
analyzes a bounded set of finite requested expressions without executing source.
Supported history indexes, finite rolling windows, nested windows, crosses and
stateless arithmetic compose their prior-bar requirements. A requested context
also includes the previous completed observation, so a ten-period hourly SMA
gets ten preceding hourly bars even when the main chart starts exactly on an
hour boundary. Calendar lookback uses real prior month boundaries. Physical minute
acquisition remains deduplicated across overlapping contexts.

Recursive, dynamic-length and user-defined expressions do not silently receive
one prior bar: the API requires an explicit warmup_bars declaration (0–5000),
while preserving any larger statically inferred requirement. Dynamic symbols can
also use these declarations. The native panel now exposes automatic-download
context declarations, interval, optional script binding and prior-bar count;
these fields persist with the source/parameter draft. Ordinary literal contexts
still require no user entry. Invalid saved declarations are ignored on restore.
The main native chart/trading range is unchanged. The current plugin protocol
has no separate nontrading main-chart pre-roll, so this change does not pretend
that moving the main start is safe. Declared recursive lookback is a user-selected
truncation policy, not a convergence guarantee.

The 53 native/dependency/preparation backend tests and eight frontend input/API
checks pass, together with final typecheck, targeted Ruff/ESLint, diff checks and
i18n completeness (30 locales, 4443 keys). New API cases exercise hourly SMA,
nested SMA, explicit EMA history, missing-declaration rejection before acquisition,
calendar history and preservation of the main start. Initial lint errors in draft
restoration were fixed by separating the typed draft helper from the component.

An additional installed Pine 0.3.0rc1 execution smoke compared planned history
against a longer 30-hour baseline. close, close[5], ten-period SMA and nested SMA
all match every plotted value across twelve main-chart bars; required preceding
hourly bars are respectively 1, 6, 10 and 6. The script and receipt are retained
under ignored local_docs/automatic-preparation-qualification as
native_warmup_engine_smoke.py and native-warmup-engine-smoke.json. This is actual
Pine engine evidence, not an installed-plugin or browser end-to-end claim; Pyne
is not installed in the system Python used by this smoke. Native primary pre-roll,
auxiliary acquisition and remaining product/browser qualification stay open.

## Reopening native results and persisted replay drafts — 2026-09-22

- Preparation task history now exposes native Pine/Pyne run results as well as
  ordinary strategy and replay results. The native viewer fetches the existing
  engine-owned run, observes nonterminal state, stops after completion/unmount,
  and provides a retry for failed reads. It preserves native export/replay/report
  authority and never writes an editor draft or creates a replacement run.
- Replay creation drafts persist across page reloads, scoped separately for the
  direct hub and a chart market/interval. Restored values are structurally checked
  and evaluated against current capabilities. Corrupt, incompatible, or denied
  browser storage does not prevent creation; persistence is unavailable when
  browser storage cannot be written.
- An uncertain automatic submission retains its frozen request identity and
  idempotency key across reloads. Changed conditions obtain another key; a
  successfully observed launch clears the pending key. This does not implement
  cross-device draft synchronization.
- Verification: 35 replay hub/draft tests and four preparation/native declaration
  tests passed; frontend typecheck, focused ESLint, i18n (30 locales, 4443 keys)
  and diff whitespace checks passed. Browser controlled-response qualification
  exercised native read failure/retry, completion, stable terminal request count,
  correct native export route and closing the report. This is UI evidence, not a
  real installed-plugin execution claim. On the actual replay page backed by the
  isolated API/SQLite fixture, reload/reopen retained both the edited training
  name and initial equity; console errors were empty. Receipt and fixture are in
  ignored local_docs/automatic-preparation-qualification.
- Auxiliary investigation confirmed exact-account preparation currently selects
  a verified local account archive before BAR acquisition. Full required roles
  include versioned historical contract rules; partial funding or mark data must
  not be represented as that complete input. Remote auxiliary acquisition remains
  open, as do the other unchecked acceptance items above.

## Legacy cache accounting and native date drafts — 2026-09-22

- First adoption of an unclassified acquisition directory now registers retained
  legacy files/directories for background physical inventory. Unknown data is
  preserved, contributes to storage admission, and stays accounted after restart.
  Cache ownership markers are excluded; symlinks/junctions are not adopted.
- If an inventoried legacy BAR object is reused, its receipt maps to that file,
  avoiding a second charge. Cache GC clears its physical ledger entry in the same
  database transaction as receipt cleanup. Recreating a deleted mapped object
  requires a fresh reservation, so zero-byte stale mappings cannot bypass budget
  admission. Engine-owned archives retain their existing deletion authority.
- The initial test run caught a duplicate charge on adoption and nested SQLite
  writes during GC. Both were corrected. The final focused regression covering
  preparation, inventory, cache writes, publication reservations, trade inputs
  and replay object copies passed 62 tests; Ruff and diff whitespace checks passed.
- Native strategy drafts now retain automatic download start/end dates together
  with source, parameters and dependency declarations. Empty date edits survive;
  invalid stored calendar dates fall back to defaults. Two focused restoration
  tests and focused ESLint passed. This is not yet browser qualification of the
  complete native preparation/installed-plugin flow.
- Generated backend/data/prepared-inputs is ignored alongside other runtime data.
  No runtime history files were removed as part of this change.
- Frontend typecheck also completed successfully after these changes.

## Full application browser run and rate-limit disclosure — 2026-09-22

- Started the full application, not the reduced replay fixture, with isolated
  Host/replay/backtest/local-data/archive paths on backend 18083 and frontend
  15176. The existing developer configuration referenced an absent remote trade
  origin; the qualification launcher explicitly uses local isolated archives.
- Through the real market-page native strategy panel, created a Pine preparation
  for Binance spot BTCUSDT, 2024-03-01 through 2024-03-02 UTC. The durable request
  confirms exactly that half-open range and one day fragment. An earlier default
  range task was cancelled through the UI and its persisted CANCELLED state
  verified. Browser automation's whole-value fill did not change native date
  controls; segmented keyboard input plus DOM readback established the range.
  This was a tool interaction issue, not evidence of a product date-state defect.
- The real download is waiting on the shared spot request-weight circuit breaker.
  Its gap ledger records rate_limit_deferred and next_retry_at=1790047319419.
  No limiter reset or bypass was used. The process and durable job remain live;
  full-app-browser-progress.json records this unfinished end-to-end attempt.
- Implemented preparation waiting metadata from the coordinator's in-memory
  progress snapshots. Each observer receives a persisted RATE_LIMIT retry time;
  shared physical work and demand leases remain unchanged. Waiting does not
  become a failed job or trigger extra provider retries. It clears on resumed
  progress, terminal state, cancellation, and restart pending reconfirmation.
- Replay creation, native preparation and preparation history now display the
  localized waiting explanation and scheduled retry time. Provider bucket details
  are not surfaced as user copy. 44 backend tests passed (including shared wait,
  cancellation isolation, restart, adapter filtering and progressive regression),
  plus four frontend observation/render tests. Typecheck, focused ESLint, Ruff,
  i18n (30 locales, 4444 keys), and diff whitespace checks passed.
- The running full-app backend predates the new waiting metadata implementation;
  it has deliberately not been restarted to interfere with the live rate-limit
  wait. The new disclosure has unit/render coverage; its actual backend/browser
  rollout and the pending native result still require follow-up verification.

## Local commit checkpoint — 2026-09-22

The full-application Binance spot BTCUSDT request for 2024-03-01 UTC completed
at 2026-09-22 11:22:05.976 Asia/Shanghai. Live API and read-only SQLite checks
confirm preparation `004c855e702c4d899884b160be6ce828` is READY, with 1/1 day
fragment and no error. The acquired compressed receipt accounts for 87,343 bytes;
this is not the total physical size of every published copy.

The installed Pine plugin run `native_b86b46c92f994da9bee215d8708cd99b` is
COMPLETED with `ok=true`, 24 hourly bars and no execution error. The test strategy
produced no orders because its entry size exceeded available equity; two
E_STRATEGY_MARGIN diagnostics are preserved. This establishes real acquisition,
immutable publication and installed-plugin execution after a browser submission.
The final report was not reopened in the browser during this verification.
The other preparation was intentionally CANCELLED; no active or failed jobs
remain in this isolated service. The local full-app-browser-progress.json receipt
now records completion and preserves the former rate-limit wait as history.

This evidence belongs to the isolated backend on port 18083. The main backend
on port 18080 was not running. The isolated process still predates the waiting
metadata change, so final backend/browser verification of that disclosure remains
open. No running service was restarted for this checkpoint.

Final-tree checks: 175 preparation/progressive/archive/import backend tests and
81 related frontend tests passed. Frontend TypeScript, ESLint on changed files,
i18n completeness (30 locales, 4444 keys), Ruff on changed Python files and diff
whitespace checks passed. Expanded lifecycle/history regression found the old
schema-22 obsolete-version test mismatch already documented above. The test now
classifies version 22 as migratable and verifies creation of the multi-interval
index plus idempotent migration. Production migration behavior is unchanged.
The existing backtest router import was moved above router construction for Ruff.
The final expanded lifecycle/history/native-preparation run passed 72 tests with
four existing FastAPI on_event deprecation warnings. Its native-preparation tests
use controlled runners. The separate installed-engine suite was not configured
with NATIVE_TEST_PYTHON and skipped 14 cases; the real Pine completion above is
separate evidence and does not qualify that skipped suite or Pyne execution.

Remaining delivery work includes remote historical funding/mark/versioned-rule
acquisition; native main-chart pre-roll and automatic Magnifier planning; broader
financial and multi-track progressive cases; large-range performance and rollback
qualification; and the remaining storage/lifecycle and browser acceptance gates.
The implementation is not declared fully accepted or release-qualified. New
automatic jobs default on in the LIVE profile; AUTO_HISTORY_PREPARATION_ENABLED=0
is the existing preparation disable switch. No remote push or release publication
is included in this local stage commit.
