# Source-only preview continuity after source-minute close

Baseline: main `fa58dd83597a4cfc0f77aad2d4c1ecf00e0a161b` (PR #405). Runtime implementation: `e9b8f68ffe9dc0b1dc9ce271e4d39216404a9932`. Commit `d242cd793` adds the longer compaction/next-bucket contract without changing runtime code. This batch contributes to #129 and the existing #126 delete fence; the original parent acceptance criteria remain in force.

## Reproduction and behavior

After a recovered SourceWindow prefix, a source minute can close outside that captured prefix. The next forming minute previously exited the qualified preview path because the closed overlay leaf was outside the captured proof. Its last throttled update then had no pending deadline. Against the complete old backend, an actual consumer wait fails (coalescing mode); the every-update control passes. The test keeps the original five-second bound and uses no manual drain, wake or new input to deliver the quiet tail.

The existing scheduler now accepts the finite closed overlay before the one forming tail, on the same fixed grid and inside the target bucket. Its original 128-leaf qualification and work reservations remain. The existing source reader still validates each input and refreshes the captured prefix at its original compaction threshold. No new timer, cache, writer, revision ledger, subscription or HTTP request is introduced.

One pinned SQLite view revalidates the original prefix and each actual overlay reference/value. Closed source-only overlay leaves may lack native canonical rows; present canonical rows must agree. Width, phase, uniqueness, target bounds and closed-before-forming order are checked. Close and correction retain the original finality and durable writer barriers.

The preview read also retains the minimum original prefix, source and canonical-recovery delete permission. A newer read revision or same-value prefix permission upgrade cannot authorize an older tail after a target/source delete. The bridge checks that permission again after its physical read. Legacy heads without a permission column remain unknown (zero) without a read-side schema migration. This changes the deferred preview validator; it does not claim to qualify every eager or writer path.

## Contracts

The 15 new contracts use the original default DataManager, temporary SQLite SourceJournal, real event bus and existing scheduler:

- Coalesced and every-update consumers across a minute close, quiet delivery, one authoritative target close and canonical result.
- Two closed overlay leaves beyond the original prefix: unchanged publication, superseding correction, conflicting native canonical value, target/source delete and legacy metadata without ALTER during the read.
- Fresh prefix permission with old/unknown/fresh tail permission, plus an unrelated-symbol revision control. On the old backend the two affected old/unknown-tail validator cases incorrectly return `current`; the fresh-tail and unrelated controls remain valid.
- A 137m bucket across 130 source-minute closes, original 128-leaf compaction, actual quiet deadline, all nine canonical fields at close, next-target-bucket delivery and unchanged prior canonical history. Work reservations return to zero.

Fourteen new cases pass together in 4.50s; the additional long contract passes in 8.36s. The earlier focused aggregation/source/preview selection passes 193 cases (before the final four additions); overlapping selections are not added together. Architecture and undefined-name checks pass. The complete pinned-fork integration on runtime `e9b8f68ff` passes **2377 tests / 66 warnings, 353.56s**. The later long contract adds one independently passing case; final delivered-head CI must include all 2378. Exact-head/base backend, frontend and four-platform host CI is required before merge and linked from the PR.

Failures are retained in the evidence index. The first canonical-conflict fixture was rejected by the existing source projection writer and therefore created no conflict; the corrected test first writes a matching row, then changes the canonical value directly. The first long-contract observer used the wrong BarData timestamp attribute; its callback failure is a fixture error, corrected to the public seconds-based `time`. A full run accidentally started after the first fixture failure was interrupted and is not a qualification pass.

## Acceptance boundary

| Original criterion | Evidence added here | Remaining scope |
| --- | --- | --- |
| #129 9.1 source-minute/target-bucket continuity | Quiet preview, original compaction, nine-field close, next bucket | Other providers/calendars/modes retain their existing contracts; this batch is the qualified default fixed-grid path |
| #129 9.4 preview deadline/barriers | Actual deadline after source close, every-update control, supersession/deletion rejection | Complete demand/hide/refresh/resource-pressure matrix remains governed by the original issue |
| #126 7.2 old acquisition cannot borrow fresh delete permission | Actual SQLite prefix upgrade, old/unknown/fresh tail and unrelated revision controls | This is a preview-validator qualification, not an all-writer/read audit |
| #129 9.5 overall performance/resources and #127 sharing/cold loading | No new qualification claim | Same-input total CPU, heap/RSS/GC, cross-target physical work and full native/indicator/strategy matrices remain open |

This batch runs component/integration and packaged host contracts; prior #405 desktop results qualify its own runtime only. No current desktop acceptance or overall CPU improvement is inferred from them. Parent issues stay open until their remaining original requirements are evidenced.
