# Special-chart fill and physical-tick strategy schedules

This change extends the preceding [close-source strategy qualification](../chart-strategy-signals-20261112/README.md).
The older evidence remains historical. HA, Renko, Point & Figure, Kagi and Line
Break now support Pine fill recalculation, actual trade-tick recalculation, and
both together. Chart Host runs, native external Host runs, independent cost
accounts and saved native replay use `candlescope.chart-signal-events/1`.

The contract is selected by the source execution settings without a feature flag.
A special-chart source's `calc_on_order_fills` also enables the effective native
fill setting without a second checkbox. Actual `calc_on_every_tick` requires
frozen physical trade/aggregate-trade data; BAR-only and historical pseudo-tick
requests reject that combination. Existing ordinary-chart schedules and the
special-chart close-only contract retain their behavior.

Input and execution semantics:

- Actual ticks advance the chart from observed prices and quantities. BAR fill
  callbacks use the existing visited OHLC path, explicitly reported as
  `OHLC_PATH_APPROXIMATION` with `LINEAR_TIME_PROXY` volume. BAR volume allocation
  is an estimate, never presented as actual tick volume.
- One shared cursor feeds fill and tick callbacks. It applies each physical price
  once, exposes actual account feedback, and serially admits plans from all
  confirmed crossing rows. Millisecond source clocks may repeat; row ordinals
  remain independent. Realtime preview rollback and `varip` persistence are
  exercised through the actual installed engine.
- HA confirms at source close; Renko/Line Break confirm observed crossings;
  P&F/Kagi confirm on reversal. Unfinished columns remain unfinished at the end.
  ATR uses only the known partial source range and earlier closes. Event-price
  history can differ from closed-time-bar reconstruction and display-window ATR.
- Real BAR/tape/book matching, eligibility, liquidity, marks, account liquidation,
  funding and closing-price ownership are retained. A synthetic crossing never
  creates a market execution event. Existing tape limits still fill at the order
  level after a real crossing; market/stop fills use the existing print policy.
- Checkpoints persist independent source, physical-event, chart, requested-input
  and evaluator cursors. Restoring evaluator state cannot replay market fills.
  Standard-symbol requests remain real frozen datasets with observed cutoffs.

Validation using the exact default exported engine/SDK/bridge wheels:

- `exact-runtime.txt`: **133 passed**. Includes five chart types across BAR fill,
  tape fill, tape tick and combined schedules; real V2 account/book modes;
  checkpoint/step/seek/restore and final-report equivalence; no-first-brick state;
  source default enablement; closing fills; millisecond timing; ordinary-variable
  rollback/`varip`; account-liquidation feedback without a new print; independent
  BAR cost baselines; requested real-symbol cutoff and restore; previous
  close-only and displayed-series indicator contracts; bridge and engine tests.
- `matching-eligibility.txt`: **2 passed** after the above suite. Renko crossing
  batches admit stop/limit orders, but only later qualifying real prints trigger
  them. An initial test expectation assumed price improvement for tape limits;
  it was corrected to assert the unchanged existing order-level fill policy.
- `backend-regression.txt`: **204 passed** across original callbacks, real ticks,
  BAR/V2/print Workbench, external replay, cost sensitivity, dual clocks, Host
  policy, close-source signals, requested data, closing and retired Pyne checks.
  These overlap the exact suite and must not be summed as unique checks.
- `plugin-build.txt`: default pinned-source recipe built and verified the Darwin
  arm64 bundles with **host-contracts-v5.patch**. `exact-install.txt` records the
  exact wheel installation into the task-owned environment. `artifacts.json`
  retains hashes, source recipe, manifest and lock details.
- `architecture.txt`, `plugin-architecture.txt`: both architecture gates pass.
  `preparation-atomicity.txt`: **4 passed**, preserving runtime promotion and
  existing activation on dependency/plugin build failure.

The backend/sidecar commands use `.venv/bin/python -m pytest` at repository root,
with `NATIVE_TEST_PYTHON`, `NATIVE_TEST_PINE_PYTHON` and the disposable
`CANDLESCOPE_NATIVE_RUNTIME_REGISTRY` pointing at the task-owned environment.
The native fixtures use isolated installed plugins, not an in-tree module path.
The exact suite names are the four new event suites plus
`test_chart_signal_native_runs.py`, `test_native_chart_indicator_input.py`,
bridge `test_ordered_chart_strategy.py`, `test_chart_indicator_input.py`,
`test_external_stream.py`, `test_request_updates.py`, and the exported engine's
`test_external_ordered_chart_contract.py` / `test_external_ordered_chart_events.py`.

Rebuild and install the exact task artifacts:

```sh
.venv/bin/python frontend/scripts/prepare-desktop-plugins.py \
  --output output/chart-event-plugin-build \
  --cache frontend/.desktop-runtime/plugin-build --qualification
uv pip install --python .venv/bin/python --force-reinstall --no-deps \
  output/chart-event-plugin-build/*.whl
```

No frontend rendering code changes in this increment; earlier frontend evidence
belongs to its recorded revision. The shipped default source recipe changes in
this increment. Source/local bundle checks do not establish installed macOS
save/exit/restart, notarization, Windows, live exchange or endurance/performance.
Pyne remains retired. Whole-market Python batch and special-chart close-only
endpoint-sensitive fixed-history programs remain unsupported. This contract does
not claim TradingView equivalence.
