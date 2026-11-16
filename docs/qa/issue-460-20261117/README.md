# Issue #460: bounded archive routing

Adjacent qualified and legacy native tasks previously entered one archive run.
The all-tasks qualification then became false and restored the legacy parent
ledger range for the qualified small task. The regression reproduces the defect
with either ordering. Source routing now separates bounded-page, exact-slot
composition and legacy contracts. A legacy neighbour also cannot erase the
required mixed route's amplification guard. Legacy parent prefill and the
required mixed route's own original envelope are preserved.

Route receipts correlate task/parent/decision/archive ranges, rejection counts,
physical REST pages, fetched rows and archive import rows/bytes. The fetcher
retains at most 64 scalar receipts, with monotonically increasing sequence IDs;
selected object details are capped at 32 with explicit truncation. Receipts are
also attached before completed siblings leave through quota deferral. These are
diagnostics, not market completeness or authority proofs.

The scoped native driver uses an empty profile and real Binance USD-M sources.
It retains actual total time and observes the four charts plus EMA20/60 and JS
close. Its 180-second observation window is a diagnostic stop, not a readiness
pass threshold. The required net readiness is <=3,000ms after only certified
external blocking time is excluded. Until exact dependency attribution is
available it reports net time as unknown and the gate as not passed; cumulative
request durations are never subtracted from wall time.

Full joint numeric, ten-minute live, hide/restore, switching and saved restart
qualification remains #463. Under the user's clarified 2026-11-17 split-task
policy, #458-#462 close independently when their own implementation and focused
validation are complete. #460 is complete on that basis: routing fixes, 63
focused tests and real-source range receipts. Overall <=3-second readiness is
not a prerequisite for its closure. PR review/merge/release status remains
separate. Raw output is retained under `output/issue-460-20261117`.

## Retained results

PR #464 is stacked on #436. The final selected source tests pass **63/63**;
`evidence/tests.json` records the validated backend hashes. A broader earlier
selection passed 92 and failed three. The exact three failures reproduce on
unmodified integration base `fd577a37c`: missing engine-test fixture contracts
and a replay archive timeout. This is not a clean repository-wide pass.

| Native run | Product | Demand observation | Bars at stop: 89m / 97m / 101m / 10007m | Ready |
| --- | --- | ---: | --- | --- |
| 1 | `6c46cabfc` | 206,589ms | 14 / 12 / 12 / 1 | No |
| 2 | `fbfabd5a3` | 207,021ms | 30 / 28 / 27 / 0 | No |

These are censored observations, not successful load latencies. App startup is
separate. Profiles were new and no market data was injected; run 2's first
storage-health sample, started immediately before demand, reports zero cached
archive objects. Both runs used the retained integrated frontend/CI runtime
and real public Binance USD-M sources. They are not a fresh release build.
The source-routing sampler is diagnostic work and does not certify production
performance. Numerical and ten-minute/lifecycle checks were not reached.

Observed bounded work kept the actual approximately 19-hour source envelope
rather than its approximately 14-day ledger parent: two REST pages, 1,157 rows,
no archive import. In run 2, the required 10007m composition also completed a
109-day native-source task: three monthly 1d archives imported 92 rows (4,185
ZIP bytes), two REST edges completed 109 rows in total, and archive parsing was
24ms. The 4,700ms fetch duration includes I/O and is not net readiness. This
is an example of legitimate mixed acquisition, not a paired comparison with
an older minute-source task. The native receipt stream has sequences 1–28
without sampled gaps.

Run 2 still records `mixed target changed during acquisition` and a 1m write
rejected with `warmup change receipts do not cover the acquisition`; the latter
report fetched 1,511 rows, committed 1,500, and generated no custom targets.
The broader acquisition/commit conflict remains #461's scope. The last sampled
reconciler metrics total 56,231ms across seven runs, including writes/waits;
that cumulative number is not the per-chart local critical path.

Net readiness is **unknown / not qualified**: exact external blocking
attribution is not certified, and cumulative public request durations are not
subtracted. Neither the <=3-second gate nor #463's full same-product matrix
passed. Those remain #463's acceptance work; **#460 is closed as scoped work
completed**, under the user's clarified split-task policy. Its implementation,
focused regression and actual routing evidence are delivered. Overall readiness
failure does not undo that delivery. Later joint runs must retain the original
data, numeric and lifecycle requirements rather than treating partial counts
as acceptance. Original run receipts saying "#460 cannot close" retain the old
interpretation as historical evidence, not the current closure rule.

After run 2, a diagnostic-only correction stopped defaulting an absent result
`history_lane` to `rest` for archive-routed results. New receipts expose
`reported_history_lane` and `history_sources` separately. The final source
selection was rerun successfully; no final-source native qualification is
claimed for that reporting change. Run 2's 1,010 backend file hashes and ASAR
match its manifest after execution, and strict code signing verifies. Owned
process trees exited in 14,480ms / 10,997ms.

Compressed receipts, timelines, traffic, logs and test reports are indexed by
SHA-256 in `evidence/index.json`. ZIP/runtime/profile data and failed candidates
remain in local output; control connection files and full profiles are not
published. Some run-1 source health was collected by a separate read-only local
observer after the original cache-only sampler omitted the engine. Run 2 uses
the corrected storage-health sampler directly.
