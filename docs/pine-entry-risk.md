# Pine entry risk integration

The chart `ORDER_INTENT` path implements `strategy.risk.allow_entry_in` and
`strategy.risk.max_position_size` through `candlescope.pine-entry-risk/1`.
It requires an interpreter exposing declarative risk configuration schema 1.
Both the compiled revision and the evaluator request carry the capability
handshake. Legacy target-position and Workbench external-account callers remain
unavailable for scripts containing these rules.

The interpreter discovers declarations independently of branch execution and
resolves inputs against the actual chart context. The Host freezes the resolved
configuration and records it with order ownership in checkpoints and reports.
Changed or missing configurations reject instead of changing past decisions.
Multiple position limits use the smallest cap; direction declarations intersect.

The Host applies these constraints to `strategy.entry` at translation and again
before matching against the actual ledger position. Pending orders cannot each
fill to the full cap from the same stale position. An entry in a forbidden
direction closes an opposite position with a market order, including when the
original entry specified prices. It cannot open or increase that direction.
`strategy.order` bypasses these two entry constraints; ordinary Host/account
admission, ownership, OCA and liquidity rules still apply.

The current quantity profile uses the Host's admitted quantity representation.
The current core resolver accepts positive finite limits and a bounded set of
immutable simple expressions. Zero-limit boundary semantics and other valid
simple expressions outside that resolver remain additional core work.
General arbitrary lot-step/minimum-contract rounding remains a separate metadata
and execution gap. This does not establish TradingView fill/lot/alert equivalence.
Risk alert text is retained as configuration metadata; delivery is not implemented.

The entry-only contract still rejects `max_drawdown`, `max_intraday_loss`,
`max_intraday_filled_orders` and `max_cons_loss_days`. The chart adapter's separate
[stop contract](pine-risk-stops.md) now connects those rules through market/fill
observations and authoritative cancel/flatten scheduling, with explicit calendar
and liquidity boundaries. Native risk registration/aggregation and Workbench
risk integration remain separate work.

Semantics were checked against the official
[strategy risk-management documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#risk-management).
This is documentation alignment plus controlled Host execution evidence, not a
fresh TradingView output oracle or packaged-app acceptance.

The retained default task environment still uses the earlier closing-tick wheel.
The entry-risk candidate is installed separately under the core repository's
`.local/host-completion/risk-preview-venv`, selected by the task-local
`output/pine-host/phase3/risk-preview-runtime-registry.json`. No global runtime
registration or release promotion is implied by these development capabilities.

Qualification evidence is retained under `output/pine-host/phase3/`:

- The 69-case focused group covers queued matching, independent cost scenarios,
  pending-order restore, unconfirmed fill callback recovery and closing ticks.
- The installed-wheel broader Pine group passed 282 cases. Two legacy tests
  still loaded old assertions before their source was corrected: one expected
  the core to reject combined exit families rather than Host admission, and one
  expected Host-account replay creation to be unavailable. Both controls,
  together with the updated risk-rejection control and per-engine capability
  probe, passed in the separate six-case corrected-control run. Production
  execution sources did not change during this test reconciliation. The raw
  broader run retains its two failures; it is not reported as an all-green run.
- The earlier broader run retains eight failures: three legacy assertions and
  five cases depending on the absent Pyne adapter. Pyne-specific cases are
  excluded from the isolated Pine candidate's final scope.
- The bridge group passed 72 cases with 12 optional Renko-extension skips. All
  16 installed bridge source files match the current source bytes. The core
  passed 7,912 Rust, 1,731 Python and 172 tooling tests; its installed candidate
  independently passed the 1,731-case Python group.

The retained 20b67788 checkpoint contained a 19-case four-stop state component.
Its later chart execution integration and current boundaries are documented in
[pine-risk-stops.md](pine-risk-stops.md); the older receipt is not rewritten to
claim that the execution hooks existed at that checkpoint.
