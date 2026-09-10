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
