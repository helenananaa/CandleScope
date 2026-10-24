# Shared market input and display projection qualification

Baseline: `6399665212c89db8b30f61d108230b74fd443c3e` (#87).
Local evidence directory: `output/replay-shared-projection-20261024/`.
The original 157 acceptance IDs remain the scope; Windows is independent.

## The original 4.75-second request

The captured native LTC 90-minute RSI request contained 93 rendered bars and
42 warm-up bars. Its 4746.305 ms total included 4744.441 ms waiting for the
backend and less than 2 ms browser admission. Three missing daily objects were
prepared during the simultaneous MA/RSI requests. RSI's two sequential daily
preparation waits were 1555 ms and 2837 ms. These durable job intervals include
scheduling, acquisition, validation and publication; they are not isolated
socket-download timings.

Visible-history requests were classified as background PREFETCH. The existing
two-worker service admitted only `workers - 1` such jobs, serializing them.
The context reader additionally waited for each day before submitting the next.
Once inputs were resident, repeated decode/coverage checks and rebuilding a
mutable BAR builder for display aggregation remained measurable costs.

`original-attribution.json`, the original HAR, cloned-input traces and baseline
source snapshots preserve the evidence. Reproduction includes the preceding
one-bar MA/RSI requests: their recursive anchor affects the forming RSI bar in
the subsequent 93-bar request. The complete sequence reproduces all payloads.

## Architecture and invariants

- The BAR acquisition adapter owns one immutable market cache shared by its
  consumers: 64 MiB conservatively charged retained data, 4096 entries, at most
  eight simultaneous owners. Same-key readers share work; exceptions can be
  retried, eviction is bounded, and cleared generations cannot republish old
  work. Oversized objects remain readable without being retained.
- Decoded daily objects bind content receipts, provenance and file identity.
  Legacy consumers receive detached dictionaries. Immutable archive fragments
  at the prepared-history seam bind source fingerprint, revision and range.
- Aggregates bind actual source buckets, interval/grid, source identities,
  exact closed/partial endpoint and Decimal policy. Public/blind time mapping
  happens after lookup. Positions, orders, valuations and indicator state are
  excluded. An earlier partial request cannot reuse a later completed bucket.
- Pure display aggregation avoids mutable per-minute builder states and chain
  hashes. Existing validation remains; calendar, partial-left-edge and synthetic
  cases retain the general BAR builder. Decimal order and nullable columns match
  that builder.
- Display-history preparation can use the existing two foreground worker slots.
  Background prefetch still reserves capacity. Daily observers are batched at
  eight, share one deadline and drain on cancellation; source generation and
  revealed-boundary checks remain in place. Host acquisition/rate-limit policy,
  execution, matching, funding and account reducers are unchanged.

## Fixed-input measurements

Nearest-rank P95, 40 observations per version/phase in alternating process
blocks, with no concurrent functional tests or builds. Existing immutable disk
inputs are preserved; derived state is reset according to each phase. All
captured indicator payloads match exactly.

| Workload | Baseline P95 | Candidate P95 |
| --- | ---: | ---: |
| 90m, 93-bar MA/RSI pair, cold derived state | 201.7 ms | 152.5 ms |
| Complete one-bar → 93-bar sequence, cold derived state | 388.2 ms | 276.2 ms |
| Same complete sequence, shared input retained and math reset | 380.4 ms | 64.8 ms |
| 93-bar pair, warm math anchors | 15.5 ms | 15.0 ms |
| Three missing daily inputs, controlled 150 ms provider | 811.3 ms | 643.8 ms |

The last row uses exactly two configured workers in both versions; observed
acquisition concurrency changes from one to two. It is a controlled scheduling
regression. Live upstream latency and native frame presentation require their
own observations. The drawing gate stays at 1 ms; its isolated local P95 is
0.091 ms.

## Regression and sustained-load procedure

Related backend coverage is 671 distinct cases, including preparation,
interrupted-write recovery, HEDGE/multi-market risk, history/tape boundaries and
indicators. A negative-price leap-month fixture was corrected to a later leap
year and all 30 shared-market tests were rerun. Frontend replay: 608 passed.
The macOS ARM64/x64 workflow runs shared-market and preparation tests with the
bundled Python after packaging, in addition to its existing checks.

`backend/scripts/benchmark_replay_market_history.py` accepts a closed native
data directory and captured `{label, session, payload}` requests. It clones the
data, starts no acquisition/inventory runner, records source hashes, compares
payload digests to a baseline and leaves the source untouched. A mounted-chart
event subscription remains active during the load. Math checkpoints reset every
cycle; market state resets every 20 cycles, the byte budget is reduced to 2 MiB
every 50 cycles, and cancelled observers are joined before reuse. Raw latency,
RSS and cache observations stream to disk so telemetry does not accumulate in
the measured process. Final checks compare both session snapshots and shared
portfolios and require zero remaining cache/executor work.

The local workload contains 34 LTC/DOGE requests across 1m/7m/90m, four offset
chart windows, MA/RSI and 1m EMA200. Run at least 1800 seconds with `--seconds
1800 --cycles 40 --reference <baseline-reference.json>`. The authoritative
completion receipt is `soak-30m-subscribed/summary.json`; resource stability is
assessed from its `resources.jsonl`. Short preflight runs are kept separately.

After review, CI and this load gate pass, merge and build one normal package
from the merged revision. Native preparation, rendered charts, controls,
paper-account preservation and a complete quit/restart are recorded separately
in the local closeout and the original acceptance matrix. Broader catalog,
strategy and unmeasured native performance cases remain explicit gaps.
