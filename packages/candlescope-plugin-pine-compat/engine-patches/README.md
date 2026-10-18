# Renko event-series candidate

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
