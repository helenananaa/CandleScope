# Strategy Internal Stage 10 Active-Entry Bracket Audit

Status: closed on 2026-06-05 for the documented active pending-entry
relative bracket subset.

Stage 10 widened same-calculation `strategy.exit` bracket attachment for
matching active pending long entries without changing the public CLI, Python,
or WASM strategy result schema. The implemented subset is limited to
one-downside plus one-upside brackets whose unresolved relative legs can be
resolved from the actual entry fill price after the pending entry fills.

## Completed Surface

- Same-calculation `strategy.exit(..., stop=..., profit=...)` can target a
  matching active pending long entry. The absolute stop is kept from placement,
  and the profit limit resolves from the eventual entry fill price.
- Same-calculation `strategy.exit(..., loss=..., limit=...)` can target a
  matching active pending long entry. The loss stop resolves from the eventual
  entry fill price, and the absolute limit is kept from placement.
- Same-calculation `strategy.exit(..., loss=..., profit=...)` can target a
  matching active pending long entry. Both legs resolve atomically from the
  eventual entry fill price.
- Existing bracket timing remains in force after resolution: the bracket cannot
  fill before the entry fill, later-bar eligibility is preserved, and downside
  wins when both bracket legs are touched on one eligible bar.
- Existing `qty` and `qty_percent` validation resolve against the matching
  pending entry quantity before the deferred bracket resolves.
- Public `orders`, `trades`, `position`, `equity`, and `diagnostics` output
  fields remain unchanged.

`strategy.exit(..., stop=..., limit=...)` was already covered by the existing
absolute active-entry attachment path before Stage 10 and was not a new Stage
10 behavior target.

## Repository Evidence

- `crates/pine-runtime/src/strategy/broker/active_entry_brackets.rs` owns the
  active-entry bracket placement helpers for `stop + profit`, `loss + limit`,
  and `loss + profit`.
- `crates/pine-runtime/src/strategy/broker/exits.rs` resolves deferred bracket
  intent after a matching pending entry fills and then places the existing
  `PendingExitTrigger::Bracket { downside, upside }`.
- `crates/pine-runtime/src/builtins/strategy.rs` routes only the three planned
  active-entry relative bracket forms while keeping same-side pairs, 3+
  triggers, missing-entry forms, and invalid trailing combinations outside the
  supported runtime path.
- Broker tests cover deferred bracket storage plus fill-time resolution:
  `pending_exit_book_stores_and_takes_deferred_relative_bracket_attachments`,
  `pending_market_entry_resolves_stop_profit_bracket_attachment_after_fill`,
  `pending_market_entry_resolves_loss_limit_bracket_attachment_after_fill`, and
  `pending_market_entry_resolves_loss_profit_bracket_attachment_after_fill`.
- Runtime fixtures and golden snapshots cover one representative public
  contract for each Stage 10 form:
  `strategy_exit_active_entry_stop_profit_bracket.pine`,
  `strategy_exit_active_entry_loss_limit_bracket.pine`, and
  `strategy_exit_active_entry_loss_profit_bracket.pine`.
- Python bindings cover the same three fixtures through
  `test_run_script_returns_strategy_exit_active_entry_stop_profit_bracket_contract`,
  `test_run_script_returns_strategy_exit_active_entry_loss_limit_bracket_contract`,
  and
  `test_run_script_returns_strategy_exit_active_entry_loss_profit_bracket_contract`.
- WASM tests cover the same public JSON shape through the corresponding
  `runs_strategy_exit_active_entry_*_bracket_from_csv_to_public_strategy_json`
  tests.
- Incremental runtime replay includes the three fixtures through
  `runtime_fixtures_match_incremental_append_execution`.
- `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` name the
  supported active-entry `stop+profit`, `loss+limit`, and `loss+profit`
  bracket subset while preserving the broader unsupported strategy boundary.

## Verification

The closeout slice used the canonical release gate:

```text
scripts/verify.sh
```

Before the closeout, each behavior slice also ran targeted runtime, CLI,
Python, WASM, incremental, conformance, matrix, clippy, and structure checks.

## Still Unsupported

- Same-side bracket pairs: `stop + loss` and `limit + profit`.
- Three-or-more trigger combinations.
- Trailing-plus-bracket combinations and invalid trailing parameter mixes.
- Missing-entry future binding for exits whose `from_entry` does not match an
  active pending entry or current open position.
- Pyramiding, short entries, reversals, multiple open trades, and generic
  `strategy.order()`.
- Public pending-order output, public bracket-leg output, public reservation
  output, OCA fields, or other strategy result schema expansion.
- Tick-level, bar-magnifier, or intrabar ordering behavior beyond the current
  historical bar model.

## Next Direction Boundary

Stage 10 should stop here. The active-entry relative bracket subset is now
fixture-backed across the broker, runtime snapshots, conformance, matrix,
Python, and WASM.

The next internal strategy stage should be selected from a fresh repo-grounded
gap audit. Do not infer broader active-entry persistence, same-side brackets,
pyramiding, shorts, or public pending-order support from the Stage 10 bracket
implementation.
