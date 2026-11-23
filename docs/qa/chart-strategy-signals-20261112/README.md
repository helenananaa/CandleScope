# Chart-type strategy signals / real-market matching

Scope: source implementation plus locally built Darwin arm64 plugin artifacts.
The default chart tester, imported/current research sources and continuing
Python accounts freeze the selected special chart as signal input. Pine special
charts select Host execution, whose account/matching prices remain real.
See [contracts](../../synthetic-series.md#strategy-signals-follow-chart-type-by-default).

The causal strategy contract is distinct from repaintable display-window ATR.
ATR uses only known bars; P&F/Kagi require reversal confirmation of their active
column/leg. No end-of-run flush manufactures a confirmed signal. Existing runs
retain their frozen chart configuration when appearance changes. Standard-symbol
Pine requests remain independent market contexts, while duplicate source clocks
retain individual chart ordinals. Ordinary candle entry points still reject them.

Validation (logs retained alongside this file; trailing whitespace normalized):

- `backend-regression.txt`: 202 checks across chart inputs, BAR/tape execution,
  continuing built-in/Python recovery, Host policy, original market replay,
  preparation/default upgrades and synthetic transforms.
- `cost-regression.txt`: 74 checks across real execution and cost sensitivity,
  including independent Pine chart-clock reexecution. Accepted orders from all
  bricks at one market sequence survive sensitivity replay.
- `exact-runtime.txt`: 37 checks using the exact exported engine/SDK/bridge
  wheels. Includes five chart types in both BAR and tape Host runs; checkpoint,
  seek/restore, final-account equivalence; and provider same-time ordinals.
- `engine-contract.txt`: the exported engine's explicit ordered-chart strategy
  test. Six bridge contract tests also run in `exact-runtime.txt`, including an
  explicit standard-symbol request which must not read synthetic prices.
- `final-host.txt`: 80 Host/recovery/preparation/default upgrade checks after
  the new cancellation/deadline control wiring. `pure-host.txt` adds the direct
  serial-admission assertion: successive bricks see projected positions 0,1,1,
  create one order, and do not fill before the next real source event.
- `research-contract.txt`: research-context round trips and retired Pyne checks.
- `frontend.txt`: 5,107 functional checks plus the isolated performance gate.
- `indicator-bridge.txt`, `indicator-rpc.txt`: nine bridge/indicator contract
  checks and one installed sidecar RPC check preserve displayed-series indicator
  behavior with the new engine.
- `typecheck.txt`, `eslint.txt`, `handoff-eslint.txt`, `architecture.txt`,
  `production-build.txt`: local source checks. Standard build chunk-size
  warnings and existing FastAPI deprecation warnings are retained.
- `plugin-build.txt`, `artifacts.json`: exact pinned-source build and artifact
  hashes. The recipe uses `host-contracts-v4.patch`, retaining the earlier
  indicator patch and adding explicit external-account ordered chart support.

The whole frontend suite is `cd frontend && npm test`; typechecks are
`npm run typecheck`. Backend commands use `.venv/bin/python -m pytest` from
repository root, with `NATIVE_TEST_PYTHON` and `NATIVE_TEST_PINE_PYTHON` set to
that environment's absolute executable. The native fixtures launch installed
plugins with `-I`, not an in-tree import override. The chart-provider suite also
uses the disposable `CANDLESCOPE_NATIVE_RUNTIME_REGISTRY` activation file in
`output/chart-signal-qa/native-registry.json`, pointing at the same interpreter.
No user plugin installation or activation registry was replaced.

Rebuild with:

```sh
.venv/bin/python frontend/scripts/prepare-desktop-plugins.py \
  --output output/chart-signal-plugin-build \
  --cache frontend/.desktop-runtime/plugin-build --qualification
uv pip install --python .venv/bin/python --force-reinstall --no-deps \
  output/chart-signal-plugin-build/*.whl
```

These tests do not establish native desktop save/exit/restart, signed/notarized
application acceptance, Windows, live-exchange integration or large-history
endurance/performance. The display-series API remains `strategy_qualified:false`:
strategy runs own a separate causal frozen-source cursor rather than trusting
browser replicas. Fill/every-tick schedules, endpoint-sensitive Workbench fixed
history and MARKET_BATCH_V1 with chart signals fail explicitly. Historical QA
records remain historical and are not updated to imply these new capabilities.
