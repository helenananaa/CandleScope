# Pyne source-close event candidate

`source-close-events-v1.patch` applies to official v0.4.1 commit
`2b7db79f26ee23472595f4e0e037d49480d45fe6`. It adds the generic optional request
metadata contract `event_series: "source-close-events/1"`. Providers supply
ordered OHLCV event rows with explicit exclusive `time_close` boundaries.
Equal timestamps retain list order; history expressions operate on event
ordinals, and projection selects the last confirmed event in a cohort.

The runtime does not construct Renko or import host modules. The CandleScope
adapter constructs causal close-source Traditional / Wilder ATR Renko from
frozen bars through `candlescope_plugin_sdk.synthetic_ohlcv`. Requested symbol
and timeframe must be explicitly frozen. Original market bars and prints
remain the execution inputs. Native Pyne retains its own fill semantics;
CANDLESCOPE mode emits intents to the host broker.

The event contract requires `lookahead_off`. Event arrays through
`security_lower_tf` are explicitly unsupported instead of projecting values
at their opening time. Ordinary request contexts retain existing alignment.
This opt-in extension leaves legacy snapshot semantics unchanged; the old
semantics-42 restoration fixtures and new event continuation/preview/seek
tests run alongside the standard request suite.

Build with a target Python interpreter after applying the patch:

```sh
git checkout 2b7db79f26ee23472595f4e0e037d49480d45fe6
git apply /absolute/path/to/source-close-events-v1.patch
python -m pytest tests/test_event_request_series.py tests/test_replay_alma_snapshot_compatibility.py
python -m pip wheel --no-deps --wheel-dir /absolute/path/to/wheels .
```

Build current SDK and Pyne bridge wheels as well, then use `scripts/build_bundle.py`
with a separate candidate lock containing all exact wheel hashes, source commit
and patch hash. The candidate retains the upstream package version with a
different digest. Do not replace the official release lock or imply it is a
published upstream release. Default distribution and platform qualification
must be validated separately.

Batch scripts use `ticker.renko(...)` and `request.security(..., "close[1]")`.
The upstream incremental namespace does not expose `ticker`; its explicit
descriptor form is `TEST?chart=renko&style=Traditional&param=1`, passed to
`ctx.request.security`. The fixed-history adapter is tested with that form.
