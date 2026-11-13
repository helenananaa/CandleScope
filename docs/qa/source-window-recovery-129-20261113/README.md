# SourceJournal-only cold recovery and permissions

Product baseline: `2e39b7e17ecd0a8e7d7abeaf347c674a2588a2c7` (#397). Product head is recorded in the final package/source manifests. This batch implements part of R129 window reconstruction and consumes the existing D126 permissions/budget/writer and H127 lifecycle; #126/#127/#129 remain open under their original acceptance criteria.

## Behavior and ownership

Previously a cold COMPONENT builder restored all selected SourceJournal rows into a full Python list, per-target snapshot/ref indexes and durable payload. The qualified default path now folds a pinned SQLite read view in pages of at most 128 rows, retaining up to 32 chronological closed runs / 32 KiB plus a replaceable live overlay of at most 128 rows. The initial incoming leaf remains explicit; sparse interior forming holes retain chronological open/close semantics. First forming input can reconstruct confirmed source-only history. Native canonical rows may be absent: this path does not make H127 canonical history mandatory.

The same journal still selects source heads and owns audit/retention. No second writer, cache, revision ledger, timer, subscription or network request is introduced. Fold work uses the existing storage executor, original H127 task capacity and history-query budget; retained receipts and old publication graphs are included in the existing realtime-state owner. Staging retains 80 KiB; a separate 4 MiB page/decode work reservation exists only during the physical fold. Cancellation drains physical work before release. Unsupported modes retain their existing paths; existing source-recovery owners refuse incompatible input rather than mixing domains.

A SourceWindowVersion records closed count, sum of monotonic selected-head semantic revisions, canonical read acquisition, and original deletion permission. These domains are separate from observation IDs/watermarks. D126's existing finite mutation footprints detect canonical changes inside the selected prefix without invalidating disjoint tail writes. Actual row equality is checked wherever native canonical rows exist. The original durable transaction rechecks selected proof and permissions before canonical mutation/publication. Same-count/opposite corrections, source-only history and SQLite rollback have explicit tests.

Original source deletion permission is additive metadata of the existing observations/heads. Legacy and unscoped REST observations retain floor zero. New semantic WS admission uses the original active permission (or current D126 head at durable admission); identical WS metadata/replay cannot renew it. REST confirmation can renew identical selected content only with an actual original pre-I/O permission; renewed read revisions with an old delete floor cannot. Concurrent stale selection can confirm matching content permission without reselecting an old value or advancing the semantic revision. Pending replay carries this permission through real fork normalization/router/state and the original writer; content freshness keeps its independent original clock. Explicit delete permissions use the original delete-permission table, not automatic dependent projection invalidations.

Every subsequent receipted forming/correction input validates the accepted prefix. Superseded source heads refold before projection, unchanged duplicate tails can publish a changed prefix, and contradictory canonical content fails explicitly. Storage owner epoch, capabilities, config/strategy/input, target generation, lifecycle and pre-adoption state are fenced. Warm-start preserves a valid selected-source owner when canonical history is empty/partial, using the original backfill trigger for missing confirmations. A complete compatible H127 prefix may take over atomically; partial canonical history cannot discard selected-source coverage.

## Validation records

The pre-final `0916837` backend passed 2295 tests but failed two subsequently added stale-forming-prefix regressions; it is not qualified as final. All intermediate failures/logs are preserved. There are 70 new plain contracts and two real pinned fork contracts. The final focused set has **100 passed / 5 warnings** in 23.13s, covering the new plain contracts, real pinned Binance fork, source-revision pipeline and enrichment CLI. Backend architecture and undefined-name checks passed.

Final complete integration, measured cost and current-package receipts are recorded below after completion. Existing #397 receipts are not reused as qualification for this product.

## Reproduce

- `cost.py --source <whole checkout/backend snapshot root> --mode base|enabled --output <json>` runs independent whole-backend processes, identical source-only inputs, cold correction followed by another correction, original default DataManager/SQLite/durable bus, no network. Seeds are outside timed sections. Each size has five trials: warmup, three untraced samples and one traced allocation sample. Report CPU and wall time separately; no application RSS/steady-state claim.
- `prepare-native.py` copies the retained #397 frontend/runtime/plugins and overlays every tracked product backend app file, records hashes and signs the isolated macOS arm64 application. This is an assembled backend qualification, not a fresh frontend/release build.
- `native.mjs` runs the original deep-history/recreate/save-exit/restart flow in two fresh isolated profiles with real public OKX; explicit left pagination reaches the original 500-bar threshold. The optional witness waits for an actual source close and original timer. Read-only diagnostics and chart/canonical nine-field comparisons are recorded; no injected seed/source/response or production timeout/limit change.
- `archive.py` retains successful and failed logs/receipts, verifies product/package/source/asar/signature and archives evidence with an index. Original profiles/apps/databases remain in output. Only ephemeral contextToken strings are redacted from copies.

## Remaining qualification

This batch does not establish all writer/read/cache/archive paths, the entire mixed-history scheduler, shared-state/resource steady state, multi-target percentile latency/RSS/GC qualification, all providers/platform native acceptance, indicators/strategies or full issue completion. Sparse/excessively fragmented/unqualified recovery has explicit refusal/fallback semantics; 65536 source slots, 128-row pages/overlay, 32 runs/32 KiB summary, existing budgets and dispatcher timeouts are unchanged or newly finite at this entry. Per-target cold folds still have measured CPU cost and are not claimed to be shared B130 source work.

Rollback is a code rollback retaining original journal observations, permission columns, canonical revisions/delete permissions and delivery audit. Old code ignores additive source permission metadata and lacks this recovery qualification; it must not be used to claim safe replay after explicit deletion. No user data or historical evidence is removed.

## Concurrent migration candidate failure

Product `bc9da6ecf1a460772bd9f9c49a14c084c917b3d1` passed the complete 2317-test integration (66 warnings, 515.69s), but native log inspection found a subscription-sync HTTP 500: simultaneous startup ingestion tried to add the same permission column. Its two original driver receipts reported completion (4450/6801 closed comparisons) because that driver checked page errors and values, not all HTTP 5xx responses. Those candidates are not clean final qualification; their profiles/apps/logs remain untouched. The deterministic two-thread legacy-schema regression reproduces the duplicate-column error on bc9da6 (one failed / one transaction-preservation test passed).

The fix defines permission columns at original table creation; old-schema migration rechecks under SQLite's original IMMEDIATE writer lock and commits only a transaction owned by that migration, preserving caller rollback. No parallel migration owner/cache is introduced. The final driver additionally records and rejects every observed API HTTP 5xx response. Both fresh profiles and the complete backend suite must run against the new immutable product before final claims.

## Consumer event comparison candidate failure

The first 15 paired cost trials at product `77a4c813b` produced identical canonical rows, nine-field values and watermarks, but the actual DataEventBus hash differed: source_window proof metadata, absent from canonical SQL columns, was incorrectly treated as a superseded candle. A first CLOSED became AMENDED despite the aggregator callback being correct. Three newly strengthened default-manager consumer assertions reproduce this at 2/2048/10007 components. Original cost JSON/logs and failed regressions are retained. The original durable dispatcher now excludes source_window proof metadata from candle-content comparison, as it already did for raw source_refs; actual canonical content/source differences still reconcile as corrections. The final cost script additionally asserts the real updated/closed/amended sequence.

## Final same-input controlled cost

Product `cfabd84370cb5250bccdd420a90c6d82cf961dee`, compared with a full archived backend at main #397 `2e39b7e17ecd0a8e7d7abeaf347c674a2588a2c7`. All **15 paired trials** match final canonical nine-field/time/source hashes, actual consumer event hashes and input/computed/published watermarks. Each trial has a source-only cold correction and then a second historical correction; there are no native 1m canonical rows. Seeding is outside timed work. Three untraced samples determine each CPU median; the fifth trial separately measures tracemalloc peak. Two sequential processes ran without this task's backend tests/native apps running. Ambient machine load is not controlled, so these are phase measurements, not stable latency percentiles.

| Source rows | Cold CPU ms old → new | Next correction CPU ms old → new | Retained state graph bytes old → new | Largest durable payload bytes old → new | Cold allocation peak bytes old → new |
| --- | --- | --- | --- | --- | --- |
| 2 | 22.280 → 35.765 | 20.729 → 37.082 | 8482 → 6275 | 943 → 1097 | 91161 → 112872 |
| 2048 | 320.885 → 186.698 | 41.506 → 190.159 | 3998989 → 6602 | 189415 → 1145 | 11680194 → 929772 |
| 10007 | 1609.561 → 992.556 | 126.511 → 1032.289 | 19422747 → 6603 | 929611 → 1156 | 53915170 → 937924 |

The large source-only builder/payload/window allocation is bounded, but subsequent corrections refold selected history and are substantially more expensive than an already retained old raw index (about 8.2x CPU at 10007 rows). The combined two-phase CPU sample also increases there. The small two-row case costs more CPU/payload. This is a correctness and bounded-reconstruction delivery, not complete high-frequency CPU/RSS/resource qualification. The report includes the full budget owners and traced current/peak values; state graph bytes do not stand for application RSS. No history/consumer work was dropped to obtain the smaller graph.

## Final product integration and transport candidate

Final product `cfabd84370cb5250bccdd420a90c6d82cf961dee` passed **2319 tests / 66 warnings** in 473.68s; the focused writer/source set passed 164 tests, architecture passed, and all 15 paired final cost trials match canonical/event/watermark hashes. Final package contains 1005 source-matched app files.

Its first fresh native profile (`native-final/ordinary`) failed the original 120s live-frame gate: all five required streams had zero frames, both charts were empty/pending, no source-recovery adoption or durable publication occurred, and metadata requests repeatedly had no HTTP response status. Independent calls through the same isolated proxy confirmed an instruments request timed out after 12s with zero bytes, while a two-candle request needed 10.088611s (HTTP 200). This is retained as failed current-product native evidence; it is not replaced by the earlier candidate's value receipts. Production/native request limits and timeouts, system network settings and profiles are unchanged.

A second untouched fresh profile (`native-final/ordinary-retry1`) failed the same 120s gate with empty charts and zero required source frames. Both failure screenshots were directly inspected. The 1005 backend files, app.asar and strict signature match the final checkout/package after these runs. Direct and compressed proxy instrument probes also received only partial response bodies before the original eight-second probe cap. These current failures and all earlier candidate failures remain archived. The code can be reviewed independently; clean current-product native qualification remains pending, and no issue-completion claim follows from local tests.

Current archive command: `archive.py --candidates-only` (source/package/signature verification and failure preservation only; it deliberately makes no successful-native assertion). Default archive mode still requires two passing profiles and an empty observed API-5xx audit. No native gate or production behavior is relaxed.
