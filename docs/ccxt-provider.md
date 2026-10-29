# CCXT connector and venue contracts

The registry owns one `CcxtProvider`. Its directory contains the 105 venues in
the pinned CCXT build. `CcxtVenueBinding` only selects a venue for existing
exchange-keyed consumers; it owns no clients, business queues or storage.
Third-party providers, including Twelve Data, retain the public plugin contract.

`GET /api/v1/exchanges/providers` exposes connector → venue routing. Existing
exchange capability responses include `connector: {id, venue}`. The persisted
`KlineSeriesIdentity.provider_id` still means **dataset vendor**. Neither it nor
venue, product, adjustment, volume units or BarBasis is renamed to `ccxt`.
Existing frontend exchange selections therefore remain valid. A separate
provider-first selector UI is not part of this migration.

## Ownership

- The provider owns venue contexts and REST pools. Pool identity includes venue,
  event loop and the live configuration object; the latter is retained strongly
  to prevent object-ID reuse. The pool further separates market and route state.
- Closing one venue/configuration does not close another. Existing stream
  runtimes retain their shared subscription, buffering and generation owners.
- `venue_strategies.py` supplies field/market/protocol policies. Acquisition is
  dispatched through the finite table in `venue_history.py`; persistence, CVD,
  aggregation, recovery scheduling and quality remain in the common engine.
- `generic.py` and `primary.py` retain import/factory compatibility only. They
  do not create independent primary/generic provider implementations.
- Unknown generic OHLCV extension fields survive projection and participate in
  revision detection. Preservation does not automatically grant an enhancement
  capability or invent a unit/finality guarantee.

## Remaining protocol strategies

| Strategy | Why retained | Exit condition |
| --- | --- | --- |
| Binance/OKX fork K-line method | Preserves raw decimal strings, 12/9-field evidence, close semantics, market-specific pagination and source receipts | An upstream or replacement unified method passes the same complete-field, concurrency, pagination and physical-attempt contracts |
| Raw K-line rollback (`INGESTION_CCXT_FORK_KLINE_ENABLED=0`) | Explicit rollback for the previously qualified source path | Remove only after the replacement release and rollback policy are deliberately retired; never silently switch after a contract error |
| Binance aggregate trades/full-depth/premium/funding/open-interest | These endpoints have distinct pagination, book or summary semantics | A unified API delivers the same protocol evidence and request-cost behavior |
| OKX funding/open-interest/mark/index summaries | Product mapping and field units remain venue contracts | Equivalent qualified unified behavior, including spot-derived index mapping |
| Raw WS profiles and strict-book strategies | Actual subscription channels, sequence/checksum and close evidence differ | Per-profile physical socket, control-message, correction and recovery qualification |
| Archive providers | ZIP format, publication cadence, checksum and object identity differ from REST | Replace a format strategy only after equivalent import/receipt/recovery qualification |

These are finite protocol adapters, not parallel business engines. Recovery and
book-policy generalization beyond current contracts remains tracked in #112,
#132 and #135. Directory membership alone is not production qualification.

## Release and rollback

`backend/requirements.txt` installs the hash-pinned downstream CCXT wheel from
[candlescope-4.5.60.1](https://github.com/helenananaa/ccxt/releases/tag/candlescope-4.5.60.1).
`backend/ccxt-fork.lock.json` records upstream and downstream commits, schema and
wheel digest. `backend/scripts/verify_ccxt_runtime.py` checks installed identity
and required methods; desktop preparation runs it before promoting a runtime.
The source extension is enabled by default. Unsupported builds fail explicitly.

Only the Python wheel is distributed here. Existing JS/PHP/C#/Go/Java source and
package qualification is retained as scoped historical evidence; this release
does not publish those packages to public language registries. Protocol changes
remain in the fork's TypeScript source and generated targets; upstream upgrades
must repeat source/field, pagination and physical-attempt tests, not merely bump
a version string. No private trading interface qualification is implied.

Calendar and Renko host contracts ship together in Pine bridge **0.3.3**, using
the separately versioned downstream engine **0.3.2+cs.1**. Four native platform
bundles, hashes and receipts are published in
[the plugin release](https://github.com/helenananaa/CandleScope/releases/tag/candlescope-plugin-pine-compat-v0.3.3).
The previous 0.3.2 platform locks/assets are preserved. An old engine rejects
unsupported calendar grids; it does not approximate them. Pyne stays retired.

Scheduling rollback preserves consumed quota, cooldowns and live permits. The
archive download switch stops new work while existing streams settle; no
rollback bypasses physical admission or erases import proof. Legacy data stays
in the migration quarantine until explicitly re-fetched and verified.
