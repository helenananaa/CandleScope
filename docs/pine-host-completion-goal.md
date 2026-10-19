# Pine host completion goal

Status: active. Continue the original user goal: CandleScope host gaps first,
then related interpreter work directly in `E:/projects/pine-interpreter`.
The mistakenly relayed scope-narrowing instruction was withdrawn by the user.

## Source and artifact identities

- Host worktree: `E:/CodexData/worktrees/pine-host-adaptation/CandleScope`,
  branch `codex/pine-host-adaptation`.
- Pre-alignment task checkpoint: `2a41db7e069c9c2a8c79d410a0820c2993f3993c`,
  retained at `refs/codex/checkpoints/pine-host-before-main`.
- Verified main: `7e34d54149f8fcb20753a54b9646f8982d336a33`, merged without
  conflicts at `e134d86742e6bcd32825e12bdb8600f8be0824b2`.
- Original main checkout remains at `1a2a0189` with its 19 existing local changes;
  this task did not modify that checkout.
- Core branch: `codex/pine-host-completion`, based on `b9200480e`, now committed
  at `0ec4e886e23009bda6c90f394c1075f843de12a5`.
- Final core wheel: `.local/host-completion/qualified-wheels/` in the core repo.
  SHA256: `1f9551d4d9ed06093208412fe05a8bf634f80a2e5c7a888213c7c82f3faf25ce`.
  It is installed only in the task's `output/pine-host/phase3/venv`.
- Package version remains `0.3.2`; use the artifact/source identity and
  `EXTERNAL_CLOCK_SCHEMA_VERSION == 1`, rather than the version alone.
- Final receipts and logs: `output/pine-host/phase3/`. Official runtime catalogs
  and global plugin activation remain unchanged.

## Implemented host work

- Complex drawing/plot output, indicator library imports and frozen dependency
  identities; chart strategy libraries and workbench imports use the same
  validated source graph. Renderer work includes native lines, labels, boxes,
  polylines, linefills, tables and additional plot families.
- Indicator requested data resolves inherited selectors, exact exchanges and
  declared finite dynamic/nested contexts, preserving explicit market types.
  Local confirmed auxiliary candles are bounded; missing data is diagnosed
  without automatic backfill or market substitution.
- Effective FX providers are validated and frozen into indicator/native inputs.
  Native batch/replay/seek tests cover effective times. Currency-dependent reads
  require actual quote metadata. Foreign-account conversion remains rejected by
  the authoritative CandleScope ledger, which does not implement it.
- Replay script fallback carries one captured session/track/data epoch, source
  sequence and inclusive revealed boundary. HTTP compute checks it against one
  durable metadata read per batch, supplies the virtual execution clock and
  clips requested data to that observation. Superseded replies are discarded.
- Forming-chart requested data now reaches the core's ordered confirmed intrabar
  feed: seed prior history, then deliver only observed confirmed intrabars.
  Both scalar security requests and lower-timeframe arrays use that feed.
- Chart market reductions support percentages of the actual host position and
  treat a close on an already flat account as a no-op. Provider restore retains
  actual account history and execution timestamps.
- Chart execution planners preserve explicit market type. Binance USDM/futures
  uses its perpetual `.P` identity; spot retains its identity. Indicator aliases
  follow the same rule and map back only to their proven storage instrument.
- Chart and workbench external evaluation accept explicit execution clocks.
  Prefix transport negotiates clock append support, rebases historical clock
  corrections and clips clock arrays with replay/feedback prefixes. Native
  replay uses its frozen clocks; scheduled fill passes retain their own times.

## Interpreter interface addition

Rust exposes `append_external_bars_with_execution_times`; Python adds optional
`execution_times` to `Program.run_external` and `ExternalSession.append`.
The caller supplies timestamps; the core does not access a host system clock or
CandleScope services. Batch/append equivalence, decoding failures, empty append,
feedback preservation and fill-pass clock precedence are tested.

## Validation

- Complete core gate passed: 7,901 Rust tests, 1,686 tests against a freshly built
  wheel, 172 tooling tests, formatting, Clippy, source structure, binding golden
  checks and generated WASM/Node execution. Focused external Python suite: 41.
- Before final-wheel replacement: combined host group 135 passed; rich Pine host
  group 34 passed; bridge plus host-input group 76 passed and 12 Renko-extension
  cases skipped. Chart/provider, workspace-M9 and chart-Pyne group: 38 passed.
- Final-wheel bridge suite: 65 passed, 12 Renko-extension cases skipped.
  Final-wheel combined backend integration: 174 passed, 46 deselected (mixed
  Pyne/plugin profiles excluded from the Pine candidate scope).
- Frontend replay: 594 passed; clock/API group: 31 passed. UI and Node typechecks
  passed. Existing 30-locale catalog check passed.
- Main's funding/cohort/advance regressions: 44 passed after main alignment.
- Controlled replay tests use durable SQLite and isolated installed Pine workers,
  with an auxiliary-market fixture containing past and future rows. Windows of
  1/128/628 bars, retry, restart and future market/FX append preserve past output.
- Playwright input-component harness checked explicit contexts, invalid JSON and
  correction, state updates and zero browser errors. Screenshot:
  `output/playwright/pine-goal-data-inputs.png`. Helpers were stopped. This is
  component validation; packaged-app acceptance remains separate.
- Ruff passes on changed paths with the existing `external.py` lambda-style
  warning excluded. Diff whitespace checks pass.

The first core gate reused a syntax-fixture executable containing the removed
`pine-external-incremental` worktree path. All 27 failures were missing fixture
files. After verifying the Cargo target lies inside the core workspace, only
`pine-syntax` rebuildable artifacts were cleared; 27/27 fixtures and the complete
rerun passed. The original failure log is retained. Backend and plugin suites run
in separate processes because their test helpers both import a `scripts` module;
the mixed collection failure is also retained.

## Remaining goal work

1. Chart strategy requested datasets, rich orders and intrabar scheduling through
   the authoritative host matcher. The rich workbench already covers selected
   limit/stop/bracket/fill callbacks; this does not qualify the chart path.
2. Workbench `CANDLESCOPE` account restoration into native replay remains
   explicitly unsupported. It needs a host-account recovery contract. Tested
   chart-provider restore and native-account replay are separate paths.
3. Remaining display destinations and symbol/session/chart metadata, keeping
   unsupported diagnostics until the real host capability is connected.
4. Re-audit current core gaps and implement selected missing language/request/
   account semantics. Current development core already provides FX conversion;
   nonunit contract multipliers remain unsupported.
5. Continue broader product and official-reference qualification. Current tests
   do not establish arbitrary TradingView script, pixel, broker-fill,
   protected-library or live-tick equivalence.
