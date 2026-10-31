# Pine Workbench Host controls

Workbench `execution_mode=CANDLESCOPE` now negotiates
`candlescope.pine-workbench-control/1` with a capable Pine external adapter.
The Host freezes the script's execution settings and resolved risk declarations
before queueing a run. The metadata query carries no chart history, requested
bars or execution tape. Input overrides and explicit symbol metadata still
participate in declarative risk resolution. Runtime identity, run input hash and
Host implementation identity bind the resulting contract.

## Risk rules

The six declarative rules use the same Host allocator and risk controller as
chart order-intent strategies: entry direction, maximum position size, maximum
drawdown, intraday loss, intraday filled orders and consecutive loss days.
Declaration discovery is independent of branch execution. Prefix responses must
retain the frozen configuration; changed or missing settings reject.

Risk enforcement observes actual equity and actual fills, independently of
script scheduling. BAR, trade-tape, book-assisted, full-depth and sampled-book
paths feed the same controller. It cancels pending script orders and submits
one reducing market close, which must use a later eligible matching tick. A
stop triggered during a synthetic closing tick cannot immediately consume that
same tick. Partial quantities, ownership, queued closes, risk peaks, windows and
trip evidence remain part of Host recovery state.

Daily rules require the existing explicit Binance continuous UTC window
contract. Other calendars and multi-day BAR consecutive-loss reconstruction
remain unsupported. The first-positive-fill-per-order counting convention and
official partial-fill oracle boundary remain as described in `pine-risk-stops.md`.

## Closing execution

`process_orders_on_close=true` enables the existing explicit synthetic closing
contract when the installed adapter advertises it. BAR uses the revealed close;
trade-tape closing uses the declared Host approximation. Neither constructs a
physical exchange print or proves close-auction liquidity.

Book modes retain their actual liquidity restrictions at the synthetic close:

- Book-assisted execution uses current bid/ask and a remaining chart-volume
  proxy; quote-only data does not provide exchange depth.
- Full-depth execution walks remaining displayed levels, retains consumed
  liquidity and never advances a passive queue from a synthetic print.
- Sampled-book execution additionally requires a strictly prior fresh sample
  under the existing age limit. Same-millisecond, future and stale samples do
  not supply closing liquidity. Exhausted or unavailable quantity stays pending.

The report discloses the closing contract, price/capacity policy, synthetic
auction boundary and combined physical-print/explicit-close taker clock.
Closing fills use `PINE_BAR_CLOSE`; their actual prices in book modes remain
book-derived. Limits and stop activation do not consume the full revealed bar's
high/low as additional passive prints.

Trade/book fill callbacks still require both script `calc_on_order_fills=true`
and explicit `fill_recalculation=true`. Closing fills invoke the next pass on
the same immutable confirmed bar and timestamp with the actual updated Host
account. Ordinary rollback and `varip` behavior remain interpreter semantics.
BAR fill recalculation remains a separate unfinished Host clock requirement.

## Replay and development qualification

Replay snapshots retain the stop controller beside actual account, allocation,
pending orders, execution cursor, consumed book liquidity and interpreter
transcript. Restore rejects missing or mismatched stop configuration. Interpreter
reconstruction must reproduce the prior output before future matching resumes;
it cannot reopen a stopped account by losing the saved risk state.

Controlled installed-worker cases cover all six rules, all five matching modes,
nine supported mode/callback combinations, closing-before-next-tick stops, input
limits, session/calendar admission, stale sampled quotes and identical replay
endpoints after snapshot/restore. Pure-kernel checks also retain exhausted depth
across repeated closes and restore. These are development checks, without fresh
TradingView differential or packaged-Workbench UI qualification.

The candidate uses `output/pine-host/phase3/workbench-control-runtime-registry.json`
and `workbench-control-venv`, with an unchanged core binary from revision
`1b506560a`. The retained default, risk-stop and liquidation candidate environments
are preserved. Older adapters keep their existing explicit unsupported path;
no global runtime activation or release promotion is implied.

## Final development evidence

The complete final Host group passed 424 cases with 41 scoped exclusions.
Kernel/risk/contract checks passed 176 cases; bridge checks passed 75 with 12
optional Renko-extension skips. The 37 installed-Workbench control cases are
part of the Host group, and an additional book-assisted recovery probe covers
that closing/risk replay composition. Groups overlap and are not additive.

The first complete group retained one obsolete assertion that Workbench must
reject closing execution. It was replaced with actual account authority,
price/time and closing-fill assertions; a separate bridge case preserves the
unnegotiated-caller rejection. A fresh complete group then passed against frozen
production and test hashes. An earlier group was deliberately stopped after a
new test reproduced an inaccurate book taker-clock disclosure. Its process
identity, failure probe and source snapshot remain retained.

`output/pine-host/phase3/workbench-control-candidate-receipt.json` binds the local
commit, installed package/core checks, registry, source freeze and terminal logs.
The new bridge wheel SHA256 is
`ba8ba67871efaef73e8c4f47bab257548cde91bd251eeaa7920d1323f005c89c`;
all 16 installed bridge and 37 SDK source files match their qualified source.
The default core binary and previous candidate environment remain preserved.
