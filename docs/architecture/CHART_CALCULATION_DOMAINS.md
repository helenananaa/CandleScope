# Chart calculation domains, version 1

A chart's current script projection has an explicit calculation origin, source
generation and publication sequence. HTTP and WS use the same application-owned
runtime. Reading a small displayed range does not execute that range as a new
script history. The existing `/indicators/range` and `/range/batch` contracts
remain independent historical calculations, including their no-future input
boundaries, warmup and historyLimit cache identities.

The DTOs and registry are language neutral. The currently admitted binding is
the registered Pine sidecar, requiring negotiated output patches and explicit
stream release. This backend contract is opt-in; frontend adoption and Native
qualification are separate remaining work.

## HTTP

`POST /indicators/calculations` accepts the existing script range definition
plus required integer `schemaVersion: 1`. The server validates the same input
budget and queries authoritative closed bars without starting backfill. The
actual first admitted warmup bar fixes the origin. Each open creates a fresh
opaque domain id; an orphaned/cancelled open stays bounded by registry capacity
and idle collection. Source, parameters, security policy and full series identity
are frozen for that domain. Saved scripts are not calculation checkpoints.

The response is a complete `indicator.snapshot`, with this additional position:

```json
{
  "calculation": {
    "schemaVersion": 1,
    "domainId": "0123456789abcdef0123456789abcdef",
    "generation": 1,
    "sequence": 1,
    "view": "current-projection",
    "origin": 1700000000,
    "observedThrough": 1700029940,
    "closedThrough": 1700029940,
    "inputRevision": "server:0:delivery:0"
  }
}
```

`POST /indicators/calculations/{domainId}/range` accepts `clientId`, inclusive
`start`/`end` chart bar openings, and a `calculation` reference containing exactly
the first four position fields (`schemaVersion`, `domainId`, `generation`,
`sequence`). Wire values are strict; booleans/coerced integers, extra reference
fields and unsupported versions are rejected. The URL and body domain must match.

The reference is an exact compare-and-set position. A stale caller receives
`INDICATOR_CALCULATION_CHANGED` and the current position; it cannot regress or
replay the owner. A covering current projection is read without market queries,
execution, alerts or IPC. Its historical displayed values may include effects
of later already-admitted observations; it is explicitly not an as-of result.

A right catchup reads from the last admitted confirmed bar, which is a physical
overlap anchor for the retained runtime. It never supplies a shorter mathematical
origin or invents a finite warmup equivalence. An unavailable requested bar gives
`INDICATOR_RANGE_NOT_READY` without advancing or executing an old prefix.

Source correction or a source-delivery gap rebuilds from the fixed origin with
a fresh runtime epoch and increments generation. The entire new projection is
published atomically. Caller `rebuild: true` explicitly recovers a lost output
or worker from the same origin. Ordinary reads never start a worker. Expanding
left of origin requires opening/replacing the domain, not merging two origins.

`DELETE /indicators/calculations/{domainId}` drains and releases that explicit
owner idempotently. It also detaches an idle live subscriber and releases its
market/input leases and durable sidecar session. Other domains and saved user
scripts/data remain independent.

## WS and publication

A script `subscribe` may include the same four-field calculation reference.
Its resolved definition must match the frozen domain. Exactly one live writer
is admitted; a second writer is rejected before execution. Older references may
join the current owner, but future positions cannot. The server registers data
subscriptions before catching up any closed prefix admitted between HTTP and WS,
then sends an ACK and complete current snapshot before queued updates.

The WS lifetime holds the domain against idle expiry; individual commands still
borrow it separately. The idle hold cannot block explicit retirement. HTTP reads
and live/correction commands are serialized through a bounded owner. Pending
stream events coalesce to one frontier/barrier rather than an unbounded task
chain. The existing connection-level correction fanout serves both subscription
paths and preserves parent backfill barriers.

Parent repair state belongs to the domain, so a concurrent HTTP range read
cannot bypass a WS repair wait. It returns `INDICATOR_RANGE_NOT_READY` until
the same parent is verified. WS waits are cancellable outside admitted math
commands/borrows; closing an owner cancels only its source waiter and can
finish while the parent repair remains pending. Duplicate completions do not
replay the calculation.

Normal live output uses the existing `render.update-range/1` metadata and
`indicator.replace_range` serialization, including negative offsets, deletion,
markers/bgcolors and whole drawing-scene replacement. Generation changes use a
complete snapshot. Every result carries its domain/generation/sequence and the
source revision captured for that execution. A source fence also runs after
serialization; a stale candidate cannot be relabelled with a newer revision or
reach the alert observer. A cancelled waiter cannot release admitted physical
work. Shutdown drains it before releasing global dependencies.

Frontend consumers must bind results to the expected domain, reject decreasing
generations/sequences and delayed prior-domain HTTP/WS responses, and replace
the whole projection on a new generation. This backend step does not yet wire
those checks into the chart hook or establish renderer/package/Native evidence.

## Transactional source provenance

The opt-in chart owner registers a bounded source-family prefix through
`DataManager.bars.prefixes` before its first query. The family keeps the full
semantic series identity and covers intervals used by lazy derivation, including
base candles before a custom target has been materialized. Existing exact-series
strategy receipts and their serialized schema are unchanged. An active chart
owns at most two watch receipts while replacing a generation; it owns no extra
OHLCV or output history.

Every input query carries the acquired canonical storage revision as
`min_revision`, forcing the existing revision-aware cache reader to synchronize.
A derived query may materialize its own unprocessed target rows. Its final
version-checked storage head can prove those writes, but cannot rebase an
acknowledged prefix, roll back progress, or accept changes after that query.
Unannounced physical writes and deletions dirty overlapping watches in the same
SQLite transaction; they therefore cover separate writers and the HTTP-to-WS gap
without relying on a transport revision or callback being delivered.

The runtime cursor and each prepared output publication pass a short synchronous
source commit guard. Script execution, source reads and serialization stay
outside the SQLite write fence. A private DataManager amendment cursor also
fences cache-only correction delivery; ordinary forming, append and duplicate
backfill notifications do not reset mathematical history. Its generation/epoch
changes fail closed after bounded clock eviction or reset, without changing the
existing stream wire schema. Changes to a processed source prefix rebuild from
the fixed origin; changes during execution or serialization reject the result.
Read-only projection requests inspect source metadata but still query no market
rows and execute no script.

Failed source cleanup retains application capacity until retry succeeds. A watch
which has already disappeared owns no resource to delete; a different incarnation
is never released as the missing owner's replacement. Registry reservation
precedes asynchronous registration/query so a failed initialization can retain
and drain its resources. The existing compiler diagnostic survives failed open.

These source guarantees are qualified with actual DataManager/cache/SQLite,
HTTP/WS, repository SDK/sidecar and the pinned Pine core. Feed callbacks are
controlled. They do not establish renderer, public exchange, installed-package,
macOS save/full quit/restart or Windows acceptance; those remain separate gates.
