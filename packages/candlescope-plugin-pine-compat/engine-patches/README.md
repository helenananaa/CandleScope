# Renko event-series candidate

The current desktop/release recipe uses `host-contracts-v1.patch`, which combines
the two historical candidates below and versions the downstream engine as
`0.3.2+cs.1`. The originals remain as historical evidence. The combined patch
applies directly to `28ecae3c645e9269e2099d27cc9abbb1f52ee9ea`, without applying
either original first. Its exact digest is in `frontend/scripts/desktop-plugin-sources.json`.
Native release qualification is run by `scripts/qualify_host_contracts.py`.

`renko-event-rows-v1.patch` applies to the official Pine runtime source at
`28ecae3c645e9269e2099d27cc9abbb1f52ee9ea` (v0.3.2). It preserves every
confirmed brick in a timestamp cohort, uses list order for synthetic history,
and aligns the last confirmed brick to its source market bar. Standard request
streams still reject duplicate times. The host remains responsible for causal
construction, frozen market data and real-price execution.

Build against the pinned source, using the target Python interpreter:

```sh
git checkout 28ecae3c645e9269e2099d27cc9abbb1f52ee9ea
git apply /absolute/path/to/renko-event-rows-v1.patch
uv run --no-project --with maturin maturin build --release --interpreter /absolute/path/to/python --out /absolute/path/to/wheels
```

Run `python/tests/test_renko_event_requests.py` against the produced wheel, then
the CandleScope adapter's `tests/test_event_strategy.py`. Those tests require
the `renko-event-rows/1` engine constant; upstream wheels skip the candidate-only
tests instead of claiming support.

The local candidate retains the upstream package version but has a different
wheel digest. Use a separate lock with `releaseStatus` set to
`local-remediation-candidate-unpublished`, the exact generated wheel SHA-256,
the source commit and patch SHA-256. Build it using `scripts/build_bundle.py`.
Do not substitute its digest into the official published release locks or
claim that this candidate is the upstream release. Preserve the official
bundle for rollback. Publishing a separately versioned engine/plugin release
and platform qualification remain release work.

The strategy adapter supports `ticker.renko(..., "Traditional", size)` and
`ticker.renko(..., "ATR", length)` with close-source confirmation. ATR uses a
causal Wilder series and never recomputes old bricks from future volatility.
This differs intentionally from a display-only chart that fixes its brick
height from the currently loaded window. No claim of tick/wick Renko or exact
TradingView construction is made. Requested markets/timeframes must be the
primary frozen market context or another explicitly frozen context.

# Host candle boundary candidate (issue 117)

`host-bar-boundaries-v1.patch` applies independently to the same official
v0.3.2 source commit `28ecae3c645e9269e2099d27cc9abbb1f52ee9ea`.
It adds `BAR_BOUNDARY_SCHEMA = "host-bar-boundaries/1"` and a reserved
`request_bars["$boundaries"]` dictionary keyed by `SYMBOL:TIMEFRAME`. Each
entry contains a stable `id` and ordered nonoverlapping `[open_ms,end_ms]`
windows. The core remains host-neutral; CandleScope freezes its versioned
rules outside the engine. No host timezone, network or database is consulted.

Actual closes, aliases (`D`/`1D`), `time`/`time_close` offsets,
`timeframe.change`, security alignment and native sessions consume these
windows. Missing windows, malformed ranges and unsupported custom sessions
fail explicitly. The host supplies requested contexts and future/past windows;
the engine does not synthesize another timezone schedule from a nominal label.

In a separate checkout of the pinned source:

```sh
git apply /absolute/path/to/host-bar-boundaries-v1.patch
cargo test -p pine-runtime --lib
uv run --no-project --with maturin maturin build --release --interpreter /absolute/path/to/python --out /absolute/path/to/wheels
# Install the produced wheel into an isolated environment with pytest.
python -m pytest python/tests/test_host_bar_boundaries.py python/tests/test_realtime_session.py
```

In CandleScope, install its current SDK and Pine bridge into that isolated
environment, then run with the normal backend test interpreter:

```sh
NATIVE_CALENDAR_TEST=1 NATIVE_TEST_PYTHON=/absolute/path/to/candidate/python PYTHONPATH=backend python -m pytest backend/tests/test_native_calendar_basis.py
```

This is an **unpublished local candidate**, retaining the upstream package
version but with a different digest. Keep official release locks unchanged.
Source commit, patch and wheel SHA-256 are recorded in the issue 117 QA receipt.
This patch is qualified independently from the Renko patch above; combining
both needs a separate integration/release qualification. No claim of a
published engine upgrade or desktop acceptance is made.
