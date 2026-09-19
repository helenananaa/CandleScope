# Replay product and performance priorities

Replay is a local, open-source trading practice and review tool. There is no
leaderboard or requirement to prevent a user from editing their own local data.

- Preserve execution ordering, financial calculations, event stop times, useful
  review history, and recovery from interrupted writes.
- Keep the training UI from revealing future market data during an exercise.
  This is a training feature, not an adversarial anti-cheat boundary.
- Do not add synchronous hashes, proofs, repeated validation, or eager history
  materialization solely to prevent local tampering. Validate imported or loaded
  data for corruption and mismatched inputs at the appropriate boundary.
- Derived valuations and intermediate snapshots may be cached, summarized, or
  reconstructed. Preserve path-dependent statistics with suitable summaries or
  an exact fallback; final price alone is insufficient.
- Existing hash and ledger byte equality is useful regression evidence, not a
  product requirement for a versioned storage redesign. When representation
  changes, verify financial outcomes, review reconstruction and recovery, and
  define compatibility explicitly.
- Measure actual work and latency. Fewer commits or hashes do not establish
  constant-time advancement or a browser responsiveness improvement.
- A prepared large BAR jump must not call the account reducer once per skipped
  base event. Measure preparation, warm advancement, deferred curve reads and
  browser updates separately.
- Prepared display queries must preserve revision binding, source bucket grids
  and revealed boundaries. Use the original history path on cache misses.
- Market range indexes belong to immutable history objects and are shared across
  training runs. Keep positions, orders and account valuations out of them.
  Opening an indexed run must not precompute future per-minute account states.
- Shared interval commands and checkpoint anchors are versioned separately from
  legacy per-event chains. Verify financial outcomes, event boundaries, useful
  review and recovery; do not reintroduce a full scan to reproduce legacy hash
  bytes for the new representation.
- Measure one-time data indexing, opening, the first large step and deferred
  curve reads separately. Backfill only already-local objects in a cancellable
  background lane; filesystem inventory must not delay the foreground query.
- Ordinary bar and trade apply must not re-sort or re-balance the immutable
  ledger history. Check the new posting at post time, keep running totals and a
  verified-through watermark on the same object that clone/commit/rollback
  copies, and leave full chain-and-balance audit for load, restore, and explicit
  checks.
- Snapshot encodings of orders, fills, closed trades, warnings, and the ledger
  are reused until that component mutates. A mark-only price update must not
  re-serialize prior fills or ledger entries.
- Committed broker collections use copy-on-write. Never modify their shared
  order maps or history lists in place. Internal snapshot components are readonly
  JSON trees; public broker snapshots remain detached. Open-order indexes follow
  map identity only because every order mutation replaces the committed map.
- Compose/hash canonical snapshots from immutable byte fragments rather than
  repeatedly concatenating whole histories. Preserve exact canonical bytes and
  arbitrary-size integers with or without the optional native JSON encoder.
- Curve reads select a global bucket window across deferred intervals and cached
  samples before valuation. Persist interval start/end sequence and time so
  planning can stop at the store entry without loading every pending curve body.
  Reuse matching sequence/revision samples and count actual distinct buckets for
  AUTO; event counts are not coarse bucket counts.
- Run deferred curve planning and valuation outside both the event loop and the
  writer transaction. Verify writer availability during preparation. Each curve
  resolution is independently requested; reading EVENT need not populate others.
- Actor and review exports remain self-contained v1 checkpoint bytes. SQLite
  may store a versioned delta referring directly to a retained full base. Base
  publication, reference insertion and pruning share the checkpoint transaction.
  Never prune referenced bases or create delta-to-delta recovery chains. Include
  full-base bytes when measuring storage savings; encoding is still history-sized.
- Fresh codec output may carry an immutable, in-process logical receipt to avoid
  decoding it again during delta construction. Imported/disk bytes still undergo
  normal verification. Base reuse must match exact bytes, survive rollback/id
  reuse, and be bounded by raw JSON size rather than compressed size.
- Legacy BAR preparation reads market rows once and defers builder and account
  work until advance or query. Old per-event chain bytes stay on an explicit
  compatibility path; new archives use range hashes.
- Multi-track and tape execution use the production global-time/account-event
  coordinator, not event-count batching of independent brokers. Reuse immutable
  book data/validation only: every new close command must still execute.
- Tape batching follows the existing optimization switch. Flat ONE_WAY accounts
  may screen resting orders up to the first interaction. Held ONE_WAY positions
  may batch a locally checked constant-valuation prefix only without funding,
  historical-account or book dependencies. Price changes/interactions still run
  individually through the global risk/event barrier. Unequal grids retain exact
  event timestamps, source counts, equal-time cohorts and deferred terminals.
- Curve interval bounds can exclude old ranges but cannot prove every bucket
  is occupied. Count actual endpoints across gaps when selecting AUTO or deciding
  which curve bodies are necessary.
- Large curve reads evaluate account values at selected offsets with chunked
  market-block reads. Do not walk every source bar, and do not drop range
  extrema by arbitrary sampling.
- Multi-market BAR intervals use a portfolio envelope and one SQLite commit for
  all actor candidates. Removing single-track guards is not a portfolio proof.
  No actor may publish before that shared commit; cancellation drains it before
  releasing leases. Track-1 alone owns legacy HEDGE compatibility rows.
- Portfolio extrema must follow the reference global time/cohort order. A sum
  of independently timed market extrema is only a conservative risk bound, not
  a historical portfolio peak or drawdown. Multi-interval acceleration defaults
  on by explicit user direction (2026-09-13); retain the explicit off switch and
  exact eligibility/risk fallbacks. Default enablement does not establish browser
  performance qualification; report those measurements separately.
- Multi-interval projection inputs are scoped to one SQL phase and reloaded at
  the next phase. Refresh shared equity after all tracks receive their pinned
  marks; retain the lowpoint and endpoint review frames separately. Pass the
  interval price bounds into the trade projection once. Review anchor budget
  accounting is append-local so rollback cannot retain a stale cached budget.
- Vectorized portfolio valuation may share readonly market-price deltas, never
  account-value arrays. Bind each range's first mark to the supplied account
  basis, observe only complete equal-time cohorts, and prove signed-integer
  intermediate and drawdown bounds before batching; retain the exact fallback.
- A prepared advance's final single-BAR cohort may share one durable actor/risk
  checkpoint. Preserve ordinary STEP execution and publish only after commit.
  Previously settled marks may join that checkpoint; new account/input phases,
  unequal next BAR times, and incomplete cohorts keep the ordered fallback.
  The command boundary is independent of a rebased market index's last row.
