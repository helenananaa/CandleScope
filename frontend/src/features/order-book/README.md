# Order book feature

This feature owns the Binance Spot and USD-M Futures order-book subscription
lifecycle and UI.

- `useOrderBookRuntime` is the composition boundary. It opens one immutable P3 or P4 WebSocket subscription and closes it when identity, mode, frequency, depth, visibility, or component lifetime changes.
- `orderBookStreamController` validates handshakes and acknowledgements. P3 uses a client stale watchdog; P4 clears the visible book immediately on a backend stale/resync status.
- `orderBookStore` is a latest-only external store. Book updates are published at most once per animation frame so they do not enter the chart or application state tree.
- `OrderBookDock` renders only validated, live snapshots. It does not own WebSocket or local-storage effects.
- Price grouping is stored per mode. P3 groups only its bounded Top-N snapshot in the dock, caps auto grouping at `tick × 10`, and retains partial buckets with explicit lower-bound quantity labels. P4 sends `price_grouping` to the backend, where the full reconstructed projection is grouped before an optional independent percentage range and `output_limit` are applied. Raw best quotes and spread metrics remain unchanged.
- Rows use stable physical slot identities and the two depth scrollers disable browser scroll anchoring. When best prices advance, existing row slots update their values instead of the browser moving the viewport to preserve old price nodes.

The current backend scope is intentionally explicit: Binance Spot and USD-M
Futures live order books, with no historical replay. Spot supports the exchange
cadences of 100 ms and 1000 ms; USD-M Futures supports 100 ms, 250 ms, and
500 ms. P4 reconstructs each market with its native sequence contract and
fails closed while a gap is being resynchronized.

## Adaptive grouping

- Manual candidates in both modes follow 1–2–5 tick multiples through 1,000,000,000×. Automatic selection remains capped at 1000× (Top-N: 10×). Both sides share a price step; raw best quotes and spread retain their source values.
- Auto scores near-price occupancy against actual visible rows, with a 10 bps inspection horizon by default and at most 512 source levels per side. This is a bounded heuristic, not a claim about unseen liquidity. Thin books prefer raw precision; missing price levels are never filled in.
- A per-view state requires a score improvement of at least 0.25, sustained for 2 seconds, and a 5-second minimum interval between changes. Browsing either side away from the best quote holds the current auto step. Stale/reconnected books reset state.
- The negotiated `adaptive_grouping_control` capability accepts `display_options` on subscribe and `set_display_options` thereafter: `target_rows` (2–100), `range_bps` (0/5/10/25/50/100; 0 means uncapped), and `auto_frozen` (boolean). These affect presentation only and never change the upstream lease. Existing servers without the capability receive no new commands.
- Range is measured outward from each side's nearest grouped price. The shown −/+ percentages intersect the delivered outer prices with trusted source boundaries relative to the raw midpoint. Unknown boundaries suppress percentages; a wide bucket edge never implies data coverage. Output count no longer implicitly constrains price distance. Bounded-source incomplete buckets remain visible, including a sole bucket that spans beyond the known data.
- Stateful selection runs before projection cache lookup; the cache includes resolved step, target rows and range, so clients with different hysteresis histories cannot share the wrong projection. Source scanning and projection stay off the async event loop.

## Wide manual aggregation and coverage

- Multipliers are exact integer tick multiples. For tick 0.1, multiplier 100000 gives a 10000 quote-currency price interval; for tick 0.01 use multiplier 1000000. These are presentation choices, not requests for additional exchange history or liquidity.
- Aggregated bids show `[lower, upper)` and asks `(lower, upper]`. A zero bid lower boundary is valid only for aggregated full-book records; raw zero prices remain rejected.
- The reconstruction engine carries conservative `coverage_bid_min` / `coverage_ask_max` from the REST seed through immutable snapshots. Sparse delta updates outside the seed do not widen the bounds. Retention trimming can only shrink them, and resynchronization replaces them.
- The projection emits `incomplete_bid_prices` / `incomplete_ask_prices`. An absent boundary is unknown, not complete. Buckets touching a boundary are conservatively marked partial. Legacy records without these fields also display grouped amounts as unconfirmed.
- Partial quantities and cumulative amounts display `≥` with a localized explanation. The old `incomplete_outer_*_bucket_omitted` wire fields remain false for compatibility; no partial bucket is silently dropped. `full_projection` still means a complete projection of the local book, not exhaustive exchange depth.
- Far-away unknown levels are not synthesized as zero. Range controls and output limits still apply; wide manual grouping cannot manufacture thousands of dollars of additional source coverage.
