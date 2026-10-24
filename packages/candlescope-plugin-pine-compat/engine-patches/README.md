# Renko event-series candidate

## Host completion candidate

`renko-event-rows-v2.patch` applies to runtime commit
`232b93dd109108d227a522ef3f3bcb32ed31a002`. Its SHA-256 is
`6998f47e967a3841f80f264d2cc9dfb78aea1cbe7f90899116510415e5c5f83e`.
The resulting source is commit `199aca438a150a436d6724ceee0afd4595a76b92`.
The parser moved into `request_input.rs`; the existing upper-bound alignment
already selects the final confirmed row in a same-time cohort. The patch keeps
Renko-only nondecreasing timestamps, rejects descending event rows and regular
duplicate timestamps, and maps a known empty Renko context to `na`.

The separate `release/release-lock.host-completion-candidate.windows-x86_64.json`
pins the actual Windows wheels, source base, patch and installed native digest.
It is an unpublished local candidate; it retains version 0.3.2 and must not be
substituted for the published upstream 0.3.2 release. Its managed bundle install,
full Host regression and desktop acceptance must be qualified separately.
Legacy Renko controls alone do not qualify every combination of duplicate event
timestamps, streaming request deltas and dynamically discovered request windows.

## Published 0.3.2 source candidate

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
