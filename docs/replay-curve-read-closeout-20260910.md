# Replay curve read closeout

Curve reads now evaluate only missing points in the requested global window.
The window includes both persisted samples and all deferred intervals; shared
bucket boundaries choose the latest source sequence and revision. A repeated
read reuses persisted versions and requires no curve write. A wider query or a
different resolution reconstructs the additional requested points.

Planning, source-index reads and account valuation run in the replay worker
executor, outside the event loop and the writer transaction. The database read
captures cached versions and immutable interval references. The final short
transaction retains the existing sequence/revision-guarded upsert, so an older
query cannot overwrite a newer persisted sample. No schema migration is needed.

AUTO counts distinct candidate buckets, including cached/deferred overlap, and
selects the finest resolution fitting the limit. It no longer adds raw event
counts to every coarse resolution. Indexed interval references remain available
for independent reconstruction of other resolutions. Full legacy records retire
only when all their rows are covered. Reading EVENT no longer eagerly fills the
other resolutions.

## Measurements

Run from `backend` with test dependencies installed:

```powershell
python -m scripts.replay_curve_read_benchmark --output ../output/replay-curve-closeout-20260910.json
```

The fixture uses a disposable service/database and a shared index of 96,000
synthetic minute bars, represented by 12 intervals. Its source object is a test
fixture, not a production Parquet capture. Every returned equity value is checked
against the scalar formula. User databases and replay cursors are not modified.

| Request | Returned points | Account evaluations | Observed latency |
| --- | ---: | ---: | ---: |
| First 1H, limit 12 | 12 | 12 | 24.446 ms |
| Same 1H query | 12 | 0 | 10.066 ms |
| First EVENT, limit 20 | 20 | 20 | 5.663 ms |
| Same EVENT query | 20 | 0 | 4.042 ms |
| AUTO, limit 2000 (selects 1H) | 1600 | 1588 | 1142.864 ms |

The repeated queries produced zero store write transactions. One-time synthetic
index construction took 2315.489 ms and is excluded from query latency. These
are individual service-call observations, not percentiles or click-to-paint
measurements. Large returned curves still require meaningful work; interval
metadata loading and planning are not constant time in the history length.

## Validation and remaining scope

Curve coverage includes full-reference equality at four resolutions and three
limits, interval boundaries inside buckets, cache reuse, larger windows, newer
persisted values, rollback after a failed write, schema upgrades, correct AUTO
selection, and a concurrent writer while curve preparation is deliberately held.
The existing full-history comparison now explicitly requests each resolution
before comparing all derived rows; financial equality checks remain intact.

Final validation: 21 indexed-interval tests passed in 87.80 seconds; 101 other
replay tests passed in 261.51 seconds. The final curve-only run passed 20 tests
in 2.44 seconds, including the newly added writer-availability case (the broader
run had collected the earlier 19 curve cases). This covers 123 distinct tests.
Ruff and `git diff --check` passed.

The first broad run exposed that old eager-materialization assumption and was
stopped after reproducing it. The isolated benchmark first completed its queries
but failed temporary-file cleanup because Windows short/long paths did not match
the connection cleanup scope; resolving the temporary root fixed the rerun.

The existing working-tree changes to incremental ledger totals, lightweight
valuation keys, ordinary dual-leg ranges and reusable index connections remain
part of the validation scope. Multi-track, tape and historical-book fast-path
coverage is unchanged. This closeout does not bypass financial event boundaries
or qualify new execution modes. No running service restart or browser latency
qualification is included.
