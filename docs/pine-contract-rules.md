# Linear contract metadata and quantity rules

Development checkpoint, 2026-10-22. This is phase 2 of the active completion
Goal; it is not release qualification or TradingView numerical equivalence.

The core candidate adds `CONTRACT_METADATA_SCHEMA_VERSION = 1` and requirements
schema 4. `pointValue` is a finite positive linear contract multiplier.
`quantityStep` is an exact positive decimal string, independent of `minContract`.
Quantity transport is bounded to 18 fractional places and a u64 coefficient;
values whose shortest floating representation changes the supplied decimal are
rejected. Existing decimal-power `quantityPrecision` remains supported, with a
consistency check when a step is also supplied. Inverse accounting remains outside
this linear contract.

Host chart and requested-symbol metadata carry the new fields. Workbench V2
binds initial rules from account events already effective at the opening chart
observation. Chart strategies receive the rules actually applied to their account
before evaluation. Explicit contradictory metadata is rejected. V1 uses frozen
explicit metadata for its synthetic account. Spot cash requires unit point value.
Historical runs currently require a constant Pine contract profile; changing
metadata must not cause recomputation of earlier decisions using future rules.
Growing request and metadata updates remain part of the next causal-update work.

Both BAR and print admission apply actual min/max quantities and contract-valued
minimum notional. V1 fees, V1 account checkpoints, V2 rules/checkpoints, default
cash/equity sizing and native-account valuation now use the contract multiplier.
Each new fill records its effective multiplier, including account liquidation;
reports and CSV exports retain it. Net-position episodes, FIFO trade reports,
turnover and slippage accounting use that receipt, rather than the last account
rule applied at the end of a run. Entry and exit prices stay in quote-price units.

The frontend preserves point value, exact step and minimum in drafts and main/
requested-market submissions, with shared contract validation and translated
inputs. Historical account inputs remain authoritative for V2.

Ordinary chart indicators and native strategies now obtain these same fields
from the symbol catalog, including foreign request contexts. Native Binance
spot/USD-M, OKX and generic CCXT adapters preserve their actual units through
the Provider V2 SDK and catalog. Binance base-unit quantities use multiplier 1;
OKX linear valuation uses `ctVal`; CCXT uses `contractSize` and the declared
precision mode. Minimum quantity remains independent of the increment. Known
inverse models, significant-digit precision, nonzero-offset grids and missing
physical contract rules cannot silently enter the native linear broker. Plain
indicator metadata does not promise an executable account for those models.

These mappings follow the primary [Binance USD-M definitions](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/common-definition),
[OKX instrument/account documentation](https://www.okx.com/docs-v5/en/), and
[CCXT manual](https://github.com/ccxt/ccxt/wiki/Manual).

Controlled evidence retained under
`output/pine-host/completion-goal/contract-spec-20261021/`:

- The original worker preflight failure on legacy quantity-precision admission
  and the real report failure (10.625 versus account profit 623.125 at point
  value 50) are retained. Candidate 02 rebuilt the bridge and uses a separate
  pure worker environment; the earlier worker was preserved.
- `candidate-02/chart-and-recovery-second.log`: 33 passed. Twelve actual-worker
  chart cases and twelve Workbench cases cover point values 50 and .01, explicit,
  cash and percent-equity sizing, V1/V2 fees and final reports. Two Workbench
  cases restore a checkpoint and reproduce the complete result. The point-value
  50 explicit chart cases independently reexecute cost scenarios.
- `account-wide-first.log`: 121 passed; `legacy-rules-first.log`: 5 passed.
- `bridge-suite-second.log`: 93 passed, 12 skipped because this core candidate
  does not advertise the separate Renko event-series candidate contract.
- Frontend contract checks: 19 passed; typecheck and 30-locale i18n checks passed.
- `report-export-first.log`: 6 passed, including effective per-fill multiplier
  preservation in CSV, net-position/FIFO PnL, turnover and slippage valuation.
- `historical-01/receipt.json`: retained failed broad attempt, 103 passed and
  one stale pre-feature test that expected a valid constant multiplier of 5 to
  be rejected. Source/runtime/registry fingerprints all stayed unchanged.
  `invalid-contract-inputs-second.log` passes nine corrected admission cases,
  including zero multiplier, changing multiplier and conflicting metadata.

The first full Rust attempt additionally found nine native exit-reservation
regressions: rounding had replaced requested quantity with the current reserved
remainder. The correction keeps those separate and passes all 337 broker unit
checks without changing old assertions. The prior worker wheel predates this
native-broker correction; its controlled external-account results retain their
own identity. Candidate 03 now uses the corrected core; the earlier worker and failures
retain their original identities.

Core commit `3ef79760d` passes the complete Windows gates: 7,960 Rust tests,
1,916 fresh-wheel Python tests, 172 tooling tests, strict Clippy, formatting,
structure, host parity and generated WASM/Node checks. Core candidate 02 wheel
SHA-256 is `595c72a99cc452fc699525dfa0d9c4bae7096d49c4dd14e2f77b9adbcb13a87a`.
Host `historical-02/receipt.json` passes all 528 tests with unchanged source,
runtime and registry fingerprints in 1,160.281 seconds. It predates the catalog
follow-up and uses the older core wheel. The catalog follow-up passes 217
source checks, while the bridge source suite passes 100 with 12 optional Renko
skips. Candidate 03 installs the corrected core plus rebuilt SDK and bridge
wheels in a new pure worker.

Candidate 03's `historical-03/receipt.json` passes all 570 selected cases across
39 modules, with zero skips and unchanged source/runtime/registry fingerprints
in 1142.313 seconds. It uses the corrected core wheel plus freshly built
SDK and bridge wheels; exact installed files and hashes are retained in the receipt.

Formal bundle/application validation,
resource acceptance, fresh TradingView reference capture, dynamic requested-data
updates, V2 print/book combinations and later tick schedules remain incomplete.
