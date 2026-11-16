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
qualification remains #463. No issue is closed by a source regression or this
diagnostic driver. Raw output is retained under `output/issue-460-20261117`.
