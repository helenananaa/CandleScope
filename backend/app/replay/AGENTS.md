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
- Exact tape phases may share one commit for up to 16 complete global cohorts
  across 2-8 ONE_WAY tracks without resting orders, funding, historical-account
  or book dependencies. Execute each cohort's reducers, account/risk and review
  writes in order; roll back the whole unpublished batch at a liquidation
  interaction and retry the scalar coordinator. Publish one contiguous terminal
  snapshot per actor after commit, and drain cancellation before releasing actors.
  Persist the parent intent and complete-track recovery bookmarks in that same
  transaction, including subsequent scalar fallback cohorts.
  Renew scan windows only for progressing durable tape jobs. Incomplete fallback
  cohorts are not recovery bookmarks: reject a mismatched fingerprint instead of
  resuming partial account state. Clock-only terminal checkpoints also bookmark
  the parent before its reply is saved.
  Plan at most 512 events per track. Before batching dense or mixed-price
  same-millisecond trades, screen the full price envelope against the current
  shared account, isolated balances and maintenance tiers under the writer lock.
  Failed bounds retain scalar risk handling; never infer safety from the final
  price. Candidate source processing can omit disposable public projections,
  and same-time, order-free trades may use candle/ordered-price summaries after
  this envelope proof. Preserve each source-chain event and every existing
  complete-cohort account/review anchor. Bound summary arithmetic to an exact
  Decimal domain; unusual precision retains the original final-state reducer.
  Price high/low alone cannot preserve drawdown: keep ordered maximum fall/rise
  and combine them with the preceding account peak. Cross-time summary jumps
  require a separate review/curve reconstruction contract.
- Actor command memory is a bounded cache only when durable command lookup and
  mutation persistence are both installed. Recheck evicted IDs inside the actor
  queue against SQLite; preserve successful replies, rejected replies and ID
  conflicts across eviction and restart. Standalone actors retain fail-closed
  capacity semantics.
- Tape interval jumps (approved 2026-09-19) supersede the per-cohort persistence
  requirement above for safe ONE_WAY ranges on 1-8 tracks. Plan at most 8192
  trades per track, screen the shared account under the writer lock, and halve
  unsafe ranges by complete timestamp cohorts before exact interaction fallback.
  Persist two complete-cohort anchors (portfolio trough when internal, otherwise
  midpoint, then endpoint), immutable revealed prices and account curve bases in
  the same transaction as every actor and the parent recovery bookmark.
  `multi-tape-interval.v1` reconstructs portfolio observations in global cohort
  order; `tape-curve.v1` values only requested selected-adapter samples. Preserve
  clock-only observations with repeated source sequences and fixed real phase
  revisions, so later account commands at the same sequence override history.
  Bind loaded curve time/sequence bounds to committed interval metadata. Forward
  each track's full interval price bounds to trade MAE/MFE projection. Prepare
  summaries outside the writer/event loop; do not cache account state globally.
  Legacy ADVANCE_BY actor/source checkpoints keep their existing v1 source chain
  in this compatibility path: measure the remaining linear decode/hash cost and
  do not claim constant-time advancement or a shared persistent tape range index.
- Tape preparation may retain a command-local immutable trade tuple and bounded
  page cursor forks. Reuse only with matching reader, public time/identity mapping,
  starting source cursor, actor revision and target. Derive prefix positions from
  validated page spans; never skip an unvalidated page or split a timestamp cohort.
  Ordinary sources retain preflight/consume fallback. Candidate source replacement
  stays inside atomic rollback, and terminal events retain exact handling.
  Portfolio phase summaries may reuse one set of complete-cohort equity values;
  preserve phase-local initial equity, peak, trough and drawdown. Never put those
  account-bound values in a shared market cache.
- Prepare tape global-event hashes and large interval/curve encodings in the
  candidate worker before acquiring the SQLite writer. Bind prepared values to
  the exact event tuple or interval plus run/command identity. The writer retains
  live risk, cursor, ordering and equity checks, and all rows still commit together.
  Preparation failure in either phase must roll back every unpublished actor.
  The singleton global-event encoder must retain canonical v1 bytes and keep
  the general iterable/non-native fallback; its small cache holds identifiers only.
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
