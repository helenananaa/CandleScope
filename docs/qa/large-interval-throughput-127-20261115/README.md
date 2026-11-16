# Large mixed-interval history throughput (#126 / #127 / #129)

This branch composes Claude's #420, #424, #426, #427 and #433, the #431
history-query allowance, and #416's dispatch-capacity guard. It ports Claude's local-burst
scheduler work with a two-second bound and tests.
No issue is closed by this document.

## Final verified result

Product/test source: `4529ff51d337697c52102962fa32ee39f871d0b5`.
Native run: `native-four-cold-13`, **passed**, 2026-11-15 09:39--09:56 UTC.

- Empty-profile cold stage: **231,417 ms**; independently compared closed bars
  **89m 221 / 97m 203 / 101m 196 / 10007m 128**.
- Ten minutes of live running, EMA20/EMA60 plus frontend-JS close input,
  actual minimize/restore, native 1m/5m/15m/1h controls, prime-chart recreation,
  historical anchors, saved workspace exit and restart all passed. 10007m had
  128 closed comparisons in every prime stage, including after restart.
- The 10007m strict canonical reads took 77 ms at cold verification, 26 ms
  after recreation once repair completed, and 132 ms after restart. Recreation
  first returned pending twice (10,063 and 10,897 ms) before the successful
  read; no pending result is represented as complete. See the retained strict
  HTTP response records.
- Page errors and HTTP 5xx: **zero**. Both owned process trees fully exited.
- Backend regression: **1,324 passed / 58 modules**, 232.03 seconds. Native
  product code matches those tests. All **1,010** packaged backend file hashes,
  retained frontend/dependency parity and post-run strict signature verified.
- Additive roundoff is retained per field/stage. Maximum accepted absolute
  difference was `0.0000152587890625`, relative below `4e-16`; OHLC, timestamps,
  integer trade counts and missingness stayed exact.

The whole cold stage did **not** meet a global 180-second four-chart goal; the
unchanged gate is per cell. This is native **functional lifecycle** acceptance
of the retained-runtime macOS candidate, not a fresh release/Windows result.

Resource sampling is **not a memory acceptance pass**: peak summed owned RSS
was **7,216.03 MiB (7.05 GiB)** with 80 processes at 09:44:23.958 UTC; shared
pages can be counted repeatedly. A middle-run sample was 1,592.88 MiB with 12
processes and the final sample 1,232.88 MiB with 10. These are neither PSS nor a
paired baseline/GC/allocation study. The transient process/RSS peak and broader
#129 performance/endurance qualification remain open.

Product changes:

- Both backfill and ingestion configure the physical Binance USD-M admission
  limit (default three). The existing shared IP quota, feedback/cooldown and
  public priority owner remain authoritative. Fetch tasks wait on the endpoint
  semaphore instead of repeatedly competing for one physical slot.
- Binance fixed-grid page limits reflect remaining slots. Calendar-month
  pagination retains the provider's original behavior.
- Explicitly qualified composition requests may use up to sixteen targets per
  chunk. Unqualified requests retain the old source-bound sizing. The ordinary
  mixed planner still bounds source rows, tasks, memory and search work.
- Qualified source requests can share a bounded HTTP envelope across gaps.
  Only their exact original REST source windows are committed; unused read-ahead
  rows do not create canonical data, new precedence or derived invalidations.
  The full and receipt paths follow the same rule.
- The source cost comparison also covers partially populated multi-target
  windows, leaving room for mandatory existing fine canonical inputs.
- Planned native REST writes use unchanged-content/deletion range proofs.
  Mixed target reductions additionally fence all declared precedence sources
  and their target using complete D126 change receipts between canonical reads
  and the final writer transaction. Changed inputs, deletions and missing
  receipt continuity reject publication. Unrelated live tails may proceed.
- A planning work-limit deferral cannot become a larger base query or a new
  market-gap/download demand when the query allowance is raised. Large
  complete/nearly complete base windows use the bounded paged base path.
- Partial multi-gap chunks resume with mandatory finer canonical inputs. If
  they exceed source/search bounds before acquisition, the existing parent
  queue refines them into smaller chunks, keeping leases, cancellation, quota
  ownership, deletion floor and final verification. No second queue is added.
- Periodic gap auditing preserves sparse auxiliary input grids used by qualified
  large composed targets; live-tail checks and explicit/manual audits retain
  their contracts. This prevents an unrelated background scan from turning a
  sparse 10007m source cover into months of dense minute demand.

## Validation

See the retained run receipts for exact product hashes and outcomes. Each
native run uses a fresh profile, real public Binance USD-M BTCUSDT history,
89m/97m/101m/10007m, EMA20/EMA60, the unchanged 128-bar viewport readiness and 180-second wait **per cell**.
The driver compares at least 127 closed bars because a viewport may also
contain a forming bar; the recorded 10007m cold checks here compared 128
closed bars.
After readiness the driver performs canonical and consumer checks, ten minutes
of live running, hide/restore, native-interval switching, recreation, complete
exit and restart. The per-cell timeout is not a global four-chart 180-second
latency requirement.

The candidates use a cloned, retained macOS arm64 runtime/plugin/frontend
package and overlay all current tracked backend sources. Backend hashes,
frontend/dependency source parity and a strict ad-hoc signature are verified.
These are packaged-app executions, not fresh release builds, and do not supply
Windows or endurance acceptance.

Failed attempts remain under `output/large-interval-throughput-127-20261115/`:

- `native-four-cold`: cold gate failed; UI counts 110/197/58/2. The largest
  target's first multi-target chunk was still downloading, including HTTP
  timeouts. Ordinary native seed REST still suffered family-fence rejection.
- `native-four-cold-2`: cold gate failed; UI counts 6/199/5/2. HTTP read-ahead
  was committed as canonical data and invalidated other derived targets.
  The following commit removes that side effect in both payload modes.

- `native-four-cold-3`: cold gate failed; UI counts 214/197/196/17. Mixed
  planning still performed a family-wide check, and archive REST fallback
  intersections had no captured REST permission.
- `native-four-cold-4`: cold gate failed; UI counts 37/204/16/49. The mixed
  cost model did not price merged HTTP envelopes, and optional mixed planning
  delayed complete/nearly complete minute-source windows.
- `native-four-cold-5`: first three charts ready at 222/204/196; the fourth
  was ready only for its small staged viewport (45 bars) and failed the
  unchanged 128-bar driver condition. Archive REST slices retained their
  parent's exact selection ranges; the next commit clips those ranges.

- `native-four-cold-6`: cold gate failed; counts 223/204/196/34. A partially
  populated chunk produced multiple gaps and lost the qualified mixed route;
  periodic audits also tried to densify intentionally sparse source grids.
- `native-four-cold-7`: cold gate failed; UI counts 804/738/708/33 after the
  partial route was restored. Existing fine canonical rows made a sixteen-target
  chunk exceed its bounded source budget. The next commit adds adaptive refinement before acquisition.

A native source-only run may finish independent unchanged windows after an
amendment to an already completed window. A deletion still withdraws all old
series permission. An amendment inside an uncommitted/partly consumed window
rejects that window. The receipt regression suite pins all three cases, rather
than relying on the former incidental family-wide refusal.

Do not infer qualification from unit tests or partial chart counts.

The eighth attempt reached 221/203/195/128 closed comparisons in 217,617 ms
and passed the cold indicator/live checks. After ten minutes its bitwise
turnover comparison failed: `79060615711.7157` versus
`79060615711.71571` for the last closed 10007m bar, an absolute difference
`0.0000152587890625` (relative below `2e-16`). It is retained as a failed
full-lifecycle attempt, not a pass.

K130 already specifies `1e-8` absolute or `1e-12` relative tolerance for
different floating-point groupings (`docs/architecture/AGGREGATION_K130.md`).
The final driver uses the tighter `max(1e-8, 4*Number.EPSILON*scale)` only for
additive fields and records every accepted nonzero difference. OHLC, timestamps,
integer trade counts and missingness remain exact; tests reject larger
differences and nonfinite values. This corrects the numeric oracle, with no
change to the 128-bar/per-cell timeout or lifecycle gates.

The ninth attempt repeated cold readiness in 199,293 ms with
221/203/195/128 closed comparisons. Steady and hidden/restored checks passed
without any accepted rounding difference. Warm recreation failed its unchanged
strict canonical-read deadline: three target rows were missing after native
5m/15m controls introduced finer authoritative inputs. Generic initial-history
repairs were still allowed to fall from an oversized partial mixed proposal
to dense 1m archive work, repeatedly invalidating the targets being rebuilt.
An isolated offline copy of its database reproduced the three real gaps; no
market data was edited in the failed run.

The next product commit (`95af148f9`) qualifies automatic large closed repairs
under the already-enabled provider contract before submitting them to the
existing queue. They inherit the same bounded splitting as composed HTTP
demands. Explicit contracts, custom reducers/mappings, other identities and
calendars, shifted alignment, forming bars and disabled mixed work retain their
contracts. Local-only standard reductions now capture source/target range
proofs from their retained canonical source windows too. The focused regression
covering these changes passed 246 tests before the next native run.

The tenth attempt exposed an archive amplification failure during cold load.
A nominally page-bounded 89m source task imported 134,276 rows (134,036
mutations) from its parent minute-grid archives in a 298,672 ms engine run.
The first chart fell back to two target rows while adjacent charts rebuilt
more than a thousand bars. Object-count limits did not bound native rows or
the time envelope, and broad parent metadata could disqualify a small target
proof. This attempt remains failed evidence.

The following change bounds Binance USD-M archive selection before resolution,
download or CSV parsing: at most 8,192 native slots per object and 32,768
slots for the route and its enclosing time span. Oversized minute-month objects
and distant parent prefetch fall back to ordinary bounded REST pages; useful
coarse monthly objects remain eligible. Existing cached ZIPs and stored market
data are preserved. Standard target proofs start with the actual source tasks
and extend only to the bounded archive/REST windows selected before acquisition,
rather than the entire potentially multi-month parent demand. A source change
inside that computation range still rejects the write; an unrelated tail may
proceed with complete receipts.

## Reproduction and evidence boundaries

The native launcher requires the retained source app and local Playwright
tooling paths recorded in `prepare-native.py` / `run-native.sh`. Prepare a new
candidate and use a new output name; existing candidates and profiles are never
replaced. For example:

```sh
python3 docs/qa/large-interval-throughput-127-20261115/prepare-native.py candidate-recheck
CANDLESCOPE_QA_APP_CANDIDATE=candidate-recheck sh docs/qa/large-interval-throughput-127-20261115/run-native.sh native-recheck
node --test docs/qa/large-interval-throughput-127-20261115/numeric.test.mjs
```

The run process alone selects the existing local HTTP proxy. It does not change
OS networking, seed market data, install bootstrap hooks or replace exchange
responses. Failed raw runs, databases, traffic captures and candidate apps stay
under `output/large-interval-throughput-127-20261115/`. The small retained
`evidence/` artifacts have source SHA-256 entries in `index.json`; large runtime
bundles and user profiles are not committed.

A ten-minute basic run does not establish long-term endurance, Windows behavior
or strategy qualification. Original #126/#127/#129 requirements remain open
outside the specific scenarios recorded here. Cloud workflow skips are not
passing CI evidence.

The eleventh attempt passed cold readiness (245,436 ms; 221/203/195/128
closed comparisons), ten minutes, indicators, hide/restore and native controls.
Warm strict reads still failed after the bounded repairs filled all 128 target
rows. Its final HTTP responses reported `revision_unavailable` after 30--56
seconds, while an isolated copy of the exact database returned all 128 rows
complete in about 5 ms. Diagnostic-only seeded and fresh runs retain explicit
bootstrap/steady-window flags; neither is acceptance. The fresh trace identified
B130 input-version changes during repeated mixed-source recomputation.

The final product reads a bounded, complete, trusted, already-persisted closed
target page directly from one canonical transaction. It neither uses an
unpersisted cache result nor reconstructs source data. Before adopting it, the
reader verifies the current target contents, identity/storage/output binding,
monotonic head and the original explicit-deletion permission. An intersecting
source mutation invalidates those canonical targets through the existing
writer trigger. Changed/deleted/reinserted targets are rejected. Incomplete,
untrusted, malformed, forming or over-limit pages retain their original paths;
actual mixed reductions keep their strict input-view fence. All query/decode
work, including declined snapshot probes, remains in I/O diagnostics.

The final affected-backend regression on `4529ff51d337697c52102962fa32ee39f871d0b5`
passed **1,324 tests in 58 modules** (232.03 seconds). The earlier broad run's
preview-continuation race is retained: a published input-version marker preceded
the expected field event. Its test now waits for both within the same original
five-second bound; the exact expected preview/final values remain unchanged.
The complete rerun passed. Architecture checks passed; the native candidate is
built from this same product/test source commit.
