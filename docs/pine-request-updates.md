# Causal requested-data updates

Phase 3 controlled qualification completed on 2026-10-22. Core commit
`207e4fa714c67da2c2d364f52f538720882b902f` and the installed worker share
the same native bytes. Phase 2 receipts retain their original source and worker
identities. Workload, official-reference and application release qualification
remain open.

The Host negotiates `candlescope.pine-request-updates/1` only when the compiled
script and installed bridge advertise support. Known legacy profiles retain
their old input format. Synthetic event-series requests retain their separate
legacy path. The pure interpreter exposes external request-update schema 1;
data loading, frozen source identity, observation cursors and durable transcripts
are owned here in CandleScope.

Pinned requested streams are loaded once. Inclusive close timestamps and
monotonic observation cursors select only newly observed confirmed bars. Initial
worker contexts register empty streams with frozen metadata. Each update owns
exact symbol/timeframe selectors, its OHLCV observation and its availability
timestamp. Main/requested bar opens cross the bridge in seconds and are converted
to integer milliseconds exactly once; availability and observation clocks remain
milliseconds. An early or future observation cannot enter the script.

Ordinary close-only evaluations carry one update group per chart bar. The bridge
uses an implicit historical close schedule while retaining public bar-only
intent coordinates. Explicit historical BAR and observed-print callbacks carry
their own immutable per-pass deltas. Historical fill paths observe the complete
canonical chart bar independently of interpolated fill timestamps; physical
print observations keep their causal cutoff. Closing-fill callbacks introduce
no additional requested market data.

Both bridges acknowledge the contract. The Host rejects a missing acknowledgement
and reaps the failed worker. Immutable completed prefixes can use suffix transport;
forming/corrected prefixes rebuild from their recorded observation transcript.
Any bridge error discards the process-local session and prefix. Cursor snapshots
bind the complete frozen source, including metadata, and replay validates every
recorded delta before accepting its final cursor. Workbench validates that
transcript before restoring an authoritative ledger. Restart reconstruction
reexecutes the evaluator without rematching existing account fills.

Controlled development evidence under
`output/pine-host/completion-goal/request-incremental-20261022/` includes 17 real
IPC/chart checks and four actual requested-data replay/historical-callback cases.
The callbacks' first retained stale assertions expected the older full-snapshot
shape. Their replacements verify exact emitted rows, availability cutoffs and
cursor counts; financial and complete-result recovery assertions remain.
Source bridge checks pass 107 cases with 12 optional Renko skips. The final
installed worker also passes 26 additional chart-callback, print-feedback and
requested-data checks (16 Pyne cases excluded). The lookahead control retains a
legacy noncausal-prefix rejection test; the new transcript instead delays the
first eligible requested observation and intent until its availability clock.
This is a causal Host contract, not historical TradingView lookahead parity.

A deterministic 512-bar transport recipe uses the actual SessionWorker encoder:
legacy request prefixes encode 34,819,850 input bytes and 131,328 requested rows;
causal deltas encode 915,663 bytes and 512 rows, with 511 append messages. These
are encoded input sizes only: the recipe does not execute broker runs or measure
time, output bytes, process capacity or end-to-end throughput.

The immutable-source installed-worker gate passes all 615 selected cases across
44 modules, with zero failures, errors or skips, in 1,404.578 seconds. All 3,667
frozen source files, installed runtime files and registry bytes remained stable.
The receipt is `historical-01/receipt.json` under the evidence directory above.
Only the subsequent documentation summary changes are recorded separately.

Workloads and release acceptance remain pending. These observations do not
establish TradingView equivalence, arbitrary
context/calendar support, live requested feeds or end-to-end throughput. Library,
endpoint-sensitive and nested-expression fallback work, full-prefix comparisons
and whole-output serialization retain separate costs; tail feed updates alone
do not remove them.
