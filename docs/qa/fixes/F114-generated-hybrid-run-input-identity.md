# F114: generated HEDGE inputs must belong to the new run configuration

A new HEDGE run at the same market/time could reuse an earlier generated hybrid
archive solely because its coverage matched and its object sorted first. After a
5x run, a new 200x model run was created and advertised as compatible, but market
selection failed with HTTP 422: the flat 200x position encountered the older 5x
versioned rule. The failed native run retained no market track or orders.

For generated hybrid input fallback, derive the current request's local seed and
pin both object identities returned by generation. The planner filters its public
and simulation selections to those identities. Explicit immutable references are
also respected. Complete historical/exact inputs and required-L2 paths retain
existing admission; the versioned leverage check remains enforced. No historical
archive, existing run, account calculation or matching policy is rewritten.

Validation:

- Native failure on official de20 package; a disposable AGG_TRADE service fixture
  reproduces 5x success followed by `leverage exceeds the versioned rule` at 200x.
- Regression covers successive higher/lower leverage, changed fees and initial
  equity, independent new input pairs, stable repeated configuration, original
  bindings/fund state, and explicit references without regeneration.
- 82 related hybrid/input/margin/order/cohort/liquidation-fork/run-creation tests
  pass. Ruff has no added diagnostics; 11 existing diagnostics in these files
  remain and are not described as a clean full-file lint run.

Production candidate qualification is pending. The native risk sample must first
admit the actual current rule, fees, mark timeline and bindings, then verify one
isolated leg liquidation, the other leg, fees/insurance, and complete exit/restart.
The 200x sample tests the declared application simulation and does not claim
historical exchange leverage or queue-exact execution.
