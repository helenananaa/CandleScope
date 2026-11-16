# SourceWindow preview coalescing and quiet-tail delivery

Baseline: main `a21289fd027a7825e01b0fd54362ec03dde8c094` / PR #402, whose runtime is `f3c3d5ff4`. Current runtime/package: `3045325ca7630096e41694868e221d27aa255bf9`; subsequent commits add an actual-deadline contract and QA only. This batch contributes to #129 and consumes the existing #126/#127/#130 interfaces. The parent issues retain their original acceptance criteria.

## Behavior

SourceWindow builders previously bypassed the existing deferred preview scheduler. Every forming input projected its retained closed summary and overlay even when the original publisher throttled the event. After the last quiet forming update, no pending deadline existed to publish the latest accepted input.

The qualified default path now uses the original scheduler for one forming tail plus up to 127 readonly closed overlay leaves inside the exact selected SourceWindow proof. It requires the same fixed source grid, identity, fields and eligible builtin finalizers. Multiple forming holes, closed leaves outside the captured proof, oversized values, custom validators/strategies and every-update consumers keep eager processing. Close/correction inputs retain their semantic barriers and durable writer checks.

Every incoming source prefix is still validated by the original recovery reader. Only K130 summary/projection work is deferred; SourceJournal admission, prefix validation and required consumer work are not skipped. Accepted input, computed and published versions remain separate. A quiet tail is delivered by the existing deadline without requiring another source message.

## Ownership and proof

No new timer, queue, cache, writer, revision ledger or subscription is added. The original 128-entry / 16KiB-per-entry scheduler and original history-query/realtime-state owners remain in use. Physical preview validation retains the immutable source receipt and frozen leaves under its existing work reservation until the worker finishes, including cancel/detach.

The original read owner exposes an ephemeral qualified binding. Storage owns the concrete validator check; the aggregator imports no storage implementation. Reader epoch, storage/revision-store/journal, capabilities, strategies, target and input versions fence asynchronous publication. Custom source-window/leaf validators conservatively retain eager behavior.

One pinned SQLite preview view checks the original SourceWindow content/canonical/delete proof and actual leaf references/values. A closed source-only leaf inside that exact proof may lack native canonical data; any present native value must agree. This does not make arbitrary closed raw leaves authoritative. Source permission stays an original lower bound; no new read or preview renews it. The durable close/correction writer remains unchanged.

## Contracts and failures

The 16 new plain contracts cover both forming and closed-correction reconstruction triggers, every-update consumers, actual values/events/close delivery, source-prefix/tail supersession, both delete scopes, reader epoch/capability changes, physical cancel/detach, custom validators and the original quiet-tail deadline. The actual-deadline case uses no explicit drain/wake/new input or alternate timer.

A complete archived #402 backend fails the quiet-tail actual-consumer wait after the original five-second test bound; only the diagnostic internal-pending assertion is omitted in that old-backend probe. Current code passes. The earlier source-only reproduction also shows eager computation when preview coalescing is expected. Fixtures and failed product records are retained separately.

Current runtime passed the complete **2362-test integration / 66 warnings, 360.63s** before the additional actual-deadline test was added. That additional test passed independently; exact final-head CI must include all 16 new cases. The owner/boundary focused set passed **76 tests** and architecture/undefined-name checks pass. Overlapping selections are not added together.

An earlier candidate imported the concrete storage adapter from the aggregator: **1 boundary failure / 2361 passes**. The qualification check was moved behind the existing read owner and storage interface; the original boundary test was retained. Earlier local runs interrupted after code/test changes, the initial unknown-enhancement expectation (None is correct for incomplete coverage), and cold-recursion acquisition-count fixture errors remain archived. They are not represented as product regressions.

## Same-input cost

Three alternating independent whole-backend process pairs run 500 forming updates at 2048m/10007m, with the original scheduler and 250ms publisher throttle. Prefix seeding is outside timed work; final deadline validation/publication is included. Pre-loop GC is reported separately and automatic GC stays enabled. This task's other tests/native apps were stopped during these measurements. Ambient machine load is not controlled; this is not percentile/whole-application RSS qualification.

| Source slots | Aggregate CPU ms baseline → current | Journal admission + aggregation CPU ms | Projection calculations per trial | Deferred inputs |
| --- | --- | --- | --- | --- |
| 2048 | 3068.083 → 3073.556 | 3859.109 → 3865.640 | 502 → 7 | 497 |
| 10007 | 3050.094 → 3086.380 | 3835.881 → 3877.309 | 502 → 7 | 497 |

All six paired samples match final forming projection, actual consumer event and three-watermark hashes. The hot JSON retains the historical key `canonical_sha256`, but it hashes the forming projection: both native and target canonical tables are explicitly empty here. Actual authoritative canonical close is checked separately by the contracts. All quiescent work reservations are zero. Calculations decrease, but **no overall CPU reduction is established**. The #402 source-validation CPU premium and #129's broader resource/performance acceptance remain open.

Reproduce with `hot-cost.py` / `run-hot-pairs.py`; they use independent full backends, real SQLite/default DataManager/bus and normalized SourceJournal admission, without network or external SDK parsing. The small 250-update smoke is a script/contract probe, not a performance qualification.

## Package qualification

The package is assembled from the retained #397 frontend/runtime/plugins with all 1005 current backend app files, then strictly signed and source-hashed. This is backend package qualification, not a fresh frontend/release build. The final current-package ordinary profile passes 4360 closed chart/canonical nine-field comparisons, deep history, switching/recreation, save/quit/restart and preview observations. Both exits remove all ten owned processes; observed API 5xx and sidecar ERROR/WARNING/Traceback lines are zero. Its one durable delivery contains no SourceWindow proof, so this desktop workflow does not qualify the source-only branch by itself.

The final witness profile also passes: **6620** closed nine-field comparisons, an actual 2m close and original timer compaction of two components. Its two exits each remove all ten owned processes. SourceWindow durable receipts remain zero in both profiles (one/eleven total durable deliveries). Both API-5xx audits are empty and both sidecar logs contain no ERROR/WARNING/Traceback. All seven final screenshots were directly inspected; visible order-book reconnect/resync states are outside this bar-aggregation qualification. After both runs, all **1005** backend hashes and app.asar still match and strict/deep signature verification passes. Final archive command: `archive.py --candidate native-qualified --ordinary-profile ordinary --witness-profile witness`. The earlier `native-preview` package at `855da04b2` passed an ordinary workflow but belongs to the boundary-failing candidate and does not qualify the final runtime.

## Remaining scope

This implements a qualified SourceWindow preview consumer and fixes quiet-tail delivery. It does not complete all #129 preview demands/barriers, cross-target sharing, total CPU/RSS/GC/resource matrices or #126/#127's original cross-path requirements. Exact delivered-head/base CI is required before merging. All old apps/profiles/databases, original failures and #402's terminal CI logs remain preserved.
