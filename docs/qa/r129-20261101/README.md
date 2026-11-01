# 129-A development acceptance and #120 execution baseline — 2026-11-01

Base: main `a4dc6e5374a719a98e9a8e8d797170f4448279aa`, after merging
[#174](https://github.com/helenananaa/CandleScope/pull/174) and
[#183](https://github.com/helenananaa/CandleScope/pull/183).
This delivery implements **129-A only**, and records **120-P0** execution
measurements. It does not close #129 or implement #120's execution isolation.

## Prior merges

#174 merged as `9d043c9b6fcfb0181b1e2de6181342a05848c92f` after checking the exact
head's backend/arm64/x64 CI and existing native acceptance. Its merge tree
matched the previously qualified latest-main candidate `533b0a07` exactly.
#183 was retargeted from the B130 branch to main, then merged as `a4dc6e53`.
Its three exact-head CI jobs passed. The actual merge tree
`3165625d435b2f2a1100b7f710aa76932e714b57` passed 2,049 local regression tests
in 154.04 seconds and the H127 public-recording check (104 blocks / 936 fields).
The backend tree matched H127's tested head and frontend matched main.

## 129-A result

The [contract](../../architecture/REALTIME_COMPONENT_INCREMENTAL_R129.md)
describes a compact prefix forest and replaceable tail, using existing K130
math/finality and the existing state owner. Historical corrections rebuild;
no second cache, source owner or persistent writer is added. Public snapshots
drop the mutable execution index. New index bytes are reported by the existing
aggregator memory owner.

The tests include per-step comparison with batch reduction, 10,007-component
tail work bounds, shuffled/overlapping/missing input, authoritative corrections,
source-revision rejection, fields becoming unknown, calendar/cap fallback,
copy/reseed, removal and the actual publisher close/amend sequence.
An existing raw-None enhancement rounding failure was corrected in the common
projection; published unknown fields remain None. Final test counts and product
source hashes are recorded in [checks.json](checks.json).

The final joint regression passed **2,103 tests across 119 test modules**, with
27 existing warnings, in **157.28 seconds**. This includes all **54 new 129-A
tests** and the 2,049-test H127/B130 integration selection. Python syntax parsing
and `git diff --check` also passed. This is the selected backend integration
suite, not a claim that every repository test or native flow was exercised.

### Controlled performance evidence

[benchmark.json](benchmark.json) records three alternating trials per executor,
the same accepted initial state and trace, field/coverage/event parity, index
bytes, and a separate public-pipeline measurement. Setup is excluded from warm
update timings. Values below are medians of the three trial medians.

| 10007m state-executor operation | Batch | Incremental |
| --- | ---: | ---: |
| Current component replacement | 23.324 ms | 0.047 ms |
| Forward append | 23.505 ms | 0.074 ms |
| Earlier historical correction | 23.902 ms | 16.485 ms |

The 89m/97m/101m cases also preserve values. Their earlier-correction times are
roughly unchanged (for example 89m: 0.215 → 0.216 ms); the slow path has no
universal improvement guarantee. The first implementation's per-leaf rebuild
allocation regressed corrections; the final batch-run rebuild removes that
implementation. Only the final source's receipt is used here.

The actual `ingest_bar_input` → lifecycle/finalizer → publisher callback path
measures **19.791 → 1.308 ms** for 10007m tail updates. Both sides publish all
32 events per trial, with throttling disabled equally and matching values.
This includes detached publication snapshots, but excludes provider/network,
SQLite delivery, frontend rendering and native UI. It is not an application
speedup claim. Publication still copies the component dictionary.

Measured retained size reachable from the 10007m index is **8,100 bytes**;
this includes its shared tail references and is not an incremental unique-heap
delta. The original component storage remains. Conservative index accounting
exceeds this measurement; the common retained-size walker deduplicates shared
objects across owner roots. Full runtime/RSS retention and window reduction
remain 129-C work.

The independent public-recording probe consumes the existing H127 public OKX
fixture, on actual epoch-aligned 17d boundaries: **30 closed buckets**, all nine
fields checked, **90 unknown field results preserved**. OHLC/base-volume errors
are zero. Maximum quote-volume absolute error is `3.0517578125e-5`, within the
unchanged `rel_tol=1e-12 / abs_tol=1e-8` contract at these magnitudes. The oracle
uses Decimal sums of individually normalized input values, not the application
reducer.

## #120 execution baseline

[indicator-baseline.json](indicator-baseline.json) measures the existing real
DataManager/EventBus/indicator bridge and built-in EMA/RSI/BOLL engines. There
is no synthetic sleep inside a computation, no network or account activity.
Each case seeds 600 bars, sends 100 preview/close pairs at 2ms producer pacing,
and checks final values against complete recomputation, expected notification
counts, no drops/recovery, and complete subscription cleanup. The history case
adds two 12,000-row BOLL tasks through the existing bounded indicator executor.

| Active instances | History jobs | Close computation P95 | Event-loop lag P95 / P99 |
| --- | ---: | ---: | ---: |
| 1 | 0 | 0.085 ms | 0.432 / 0.783 ms |
| 16 | 0 | 0.682 ms | 0.661 / 0.883 ms |
| 64 | 0 | 2.699 ms | 0.946 / 1.388 ms |
| 64 | 2 | 3.700 ms | 32.100 / 40.944 ms |

All 800 realtime bridge callbacks execute on the event-loop thread. History
tasks execute on worker threads. Queue/run/ready percentiles are recorded
separately for preview and close. All four cases match full recomputation;
no input/output event is skipped. Process peak RSS for the whole probe is
79,904,768 bytes, not a per-case delta or a leak test.

This is one controlled run on local arm64 Python 3.12.15, not a production
latency SLA. It establishes placement and a repeatable contention scenario;
it does not attribute every delay to GIL or prove that adding threads fixes it.
The producer is paced on the same loop; queue/ready times start at emit, not
exchange arrival. Sustained external ingress and backpressure capacity are
not qualified by this probe.
Pine/Python runtimes, backtests, real multi-chart/native workloads and recovery
remain unmeasured #120 baseline extensions. No indicator execution code changed.
The next #120 implementation should move all accesses to one instance behind
a bounded serial owner and preserve initialization/preview/close/correction/
generation boundaries, then repeat these cases and add recovery/overload tests.

## Reproduction and remaining scope

Using the project Python environment with pinned dependencies:

```sh
.venv/bin/python docs/qa/r129-20261101/run_backend.py
.venv/bin/python docs/qa/r129-20261101/benchmark.py
.venv/bin/python docs/qa/r129-20261101/indicator_baseline.py
```

Run timing probes separately from tests/other heavy tasks. They write receipts
under output/r129-20261101; the regression writes XML under
output/r129-reproduction. None accesses production credentials or mutates user
databases. The input fixture is already versioned in the H127 QA directory.

129-B shared source state and demand-driven preview, 129-C bounded retained
composition/rebuild, and 129-D/J historical-prefix/live-overlay handoff remain
open. This PR does not consume H127 for initialization yet. Default-path native
save/full-exit/restart and fresh main integration must be qualified before
merging this new behavior to main. Development delivery does not wait for CI.
