# Issue #123 P2: quality admission and recovery ownership

This slice builds on P1's per-window writer and P2's consumer recovery. HTTP/WS
transport sharing, consumer leases and series identity remain in their existing
coordinators. There is no persisted-data migration.

## Boundaries

| Boundary | Responsibility |
| --- | --- |
| `apiPayloadParsers` + `klineEndpointDecoder` | Validate wire values, normalize seconds and decode endpoint proof fields; missing proof stays missing |
| `klineDomainPolicy` | Finite OHLCV, ordered high/low enclosure, non-negative total volume and supported optional quantities; negative prices and signed flow are valid |
| `klineQualityPolicy` | Separate coverage, finality, availability and completion; HTTP/realtime conflict decisions; quote/freshness eligibility |
| `SeriesDataFeed` | Request fences, epoch checks, paging/repair orchestration and response-scoped evidence |
| `MarketWindowSession` | Atomically validate a whole input batch, preserve finality, mutate the owned window and publish evidence with its data revision |
| `BackfillRecoveryQueue` | Generation-owned readback queue, overlapping-chunk coalescing, event deduplication and cancellation-safe cleanup |
| React runtime adapters | Translate domain recovery progress into presentation state; Feed no longer receives React-style setters |

History, before, range/repair and latest/poll responses carry their endpoint and
response quality through active/cache commits. Snapshot navigation carries that
same evidence into replacement/forward commands. WS, cache and shared/watchlist
seed inputs reach the same owned domain guard. A rejected batch changes no rows
or data revision, invalidates local history proof, and records its field/reason.
A valid replacement or verified response covering the rejected range clears that
quarantine. Warm seed provenance never establishes local history completeness.

`admission.inputQuality` describes the response that was admitted, not the entire
merged window. `commitState` seals window ID, selection epoch, commit/data/axis
revisions and proof before notifications. Older request epochs and revoked
window selections still lose write permission immediately before commit.

## Quality and conflict policy

- History/before may omit `truncated` when uncapped; range recovery requires
  explicit `truncated: false`. Latest and seeds never prove complete history.
- Exhaustion may stop retries without proving completeness. Explicit retry
  deadlines schedule probes; new availability evidence permits re-reading. Neither an ACK nor
  a non-pending response establishes freshness. Completion-event hints require
  HTTP readback; they cannot release loading by themselves.
- Verified continuity can include a forming tail. Complete final history also
  requires explicit finality and no contradictory forming row in the response.
- A forming row cannot reopen a held final row through any owned write command.
  A final amendment can update a historical candle, but cannot change the current
  quote or refresh stream freshness. A changed held amendment schedules bounded
  consumer readback; equal duplicates do not add work.
- HTTP/WS envelopes currently define no comparable source revision. Opaque
  `source_revision` fields cannot outrank a request fence. During an outstanding
  request, observed final realtime rows win; a trusted final HTTP row may promote
  a forming row. Later readback reconciles amendments without inventing server
  ordering semantics.
- Queue cleanup owns a particular generation object. An old request that ignores
  cancellation may finish, but cannot erase or deduplicate the successor queue.
  Pending left pages retain their original `before` boundary.

## Validation and limits

The added tests cover OHLCV rejection and valid negative prices, endpoint proof
absence/contradictions, atomic quarantine, final/forming conflict across all
commands, evidence/revision coherence, historical amendment effects, cancellation
while old reads are outstanding, duplicate/coalesced completion events, and
unverified readbacks. Existing dual-window, transport lease, pending-page and
consumer recovery regressions remain required. The core policy/queue tests run
under Node without a React renderer.

Run `npm run check` from `frontend`. Native/browser evidence, exact revision,
profile and fixed-input performance comparison are recorded on the delivery PR
and issue #123; a passing build alone is not functional acceptance.

P3 scheduling/admission-render separation, secondary-window latency, all async
indicator consumers, OS sleep, long outages/soak and every provider/asset-class
combination require their own evidence. This slice does not establish a new
source-revision protocol or installed-release acceptance on every platform.
