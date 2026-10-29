# Issue #123 P3: admission, display and asynchronous inputs

P3 is based on PR #136 (`f0b4d58b`). Shared HTTP/WS transports, their request
leases and per-window write ownership remain in place. This document describes
the implemented contract; measured acceptance evidence is recorded separately.

## Ownership and scheduling

`useKlineStreamRuntime` synchronously submits every validated event through the
existing owned transaction. It cannot import the display scheduler. There is
no second writer, hidden-write queue, or authoritative-commit bypass API in the
display scheduler. Final/amendment/reset semantics remain admission policies.

`createChartDisplaySubscription` subscribes to accepted commits. Main price
projection and its React legend share one display notification/version. Repeated
same-tail changes occupy one slot and retain incremental `series.update`.
When more than one structural change is skipped, the slot requests a projection
rebuild over the accepted reader, including deletions and viewport compensation.
It never applies only the last structural delta to an older display.

Hidden/minimized slots retain dirty state without scheduling RAF. Visibility
restoration schedules them even with no new market event. Final unsubscribe or
cell teardown cancels the slot; scheduler generation identity prevents an older
flush from deleting a replacement. Initial mounting and explicit chart type
changes still construct their projection directly.

The default frame runs at most two jobs, stops starting jobs after an 8 ms work
budget, and inserts no empty frame. A single callback cannot be preempted. Candle
display precedes preview work; an aged secondary slot gets precedence over fresh
focused work. `pendingFrames` includes retained hidden slots; `runnableFrames`
counts eligible work. `authoritativeCommits` counts valid final WS submissions at
the owned writer, including accepted no-ops; `displayCommits` counts display jobs.

## Stable asynchronous input

`captureStableSeries` returns a frozen range/limit snapshot, version, commit state
and `isCurrent` predicate. Live captures share already immutable rows and copy
only the selected array. The predicate also checks the captured session selection,
entry identity and owner liveness, so a retained reader cannot authorize an old
result after selection ABA, eviction or close. Mutable replay/static readers use
deep copies and exact version checks; their writers must maintain the version
contract.

Policies are explicit:

- `exact`: any data-version change invalidates the result.
- `forming-preview`: only updates of the same open tail may pass. A close, new
  candle, changed captured history, axis change or owner change invalidates it.
  This lets bounded previews finish under continuous input; it does not claim
  that the preview includes the latest forming price.
- `range`: every captured row must still exist unchanged and contiguously in the
  reader. Unrelated forming changes do not invalidate a closed-range result.

Local indicator sampling captures at most 2000 rows. It is used for both frontend
JavaScript and explicitly local indicators. Results, shared-cache writes,
deferred React updates and errors check the input fence in addition to lifecycle
and parameter identity. Hosted range requests retain server revision fencing and
also capture the locally held closed prefix. Empty or unavailable local history
does not prove the server's historical input; remote provenance still depends on
the server contract. Range apply may reject with `false`; settlement remains
retryable. An asynchronous apply receives `isCurrent` and must check it just
before publication; the scheduler also rechecks before recording success.

Synchronous readers still use live `snapshot()`/delta access. Export/freeze paths
must capture before their first await. These APIs do not turn a live array into a
stable asynchronous input merely by retaining its reference.

## Regression and rollback boundary

Tests cover immediate independent owner admission, dual-frame scheduling,
hidden/minimized recovery without a new tick, structural deletion after skipped
deltas, teardown, bounded/fair frame work, immutable capture, exact versus preview
policies, owner ABA/close, delayed correction and asynchronous apply supersession.
Architecture checks reject display scheduling imports at the WS/writer boundary.

Rollback is a source/build rollback to #136. Do not enable both implementations
or introduce a dual-writer feature flag. The same isolated QA profile can be
reopened on the parent and then on P3; no persisted market-data schema changed.
Keep P0/P1/P2 evidence and the retired-Pyne rejection checks intact.

## Acceptance status

Native results, fixed-input comparison, source/build hashes and remaining gaps
will be added after the final candidate is exercised. Unit tests alone do not
close the issue's full multi-window/long-history/soak acceptance matrix.
