# Numeric alerts on current main261

Product source `5ce6357be99c87b419d7153bff0b99d8ffc2b1a3` follows conflict-free
integration `0251a70127d024167b7f2036699a9b6b52ece7ff`, joining actual main261
`0de39f37f2389b09a35fc91e3a6d8d5844137da8` above prior #249
`2fe53985961444d20c65deefd99ba6988f2e66f6`. Since #200 is merged, retarget this
successor of #204 from the old seconds branch to main. Original #204 refs and
historical evidence remain preserved.

## Cancelled numeric close defect and correction

The old subscription set closed=true before awaiting GC-protected unsubscribe.
Cancelling that wait stranded the actual registered event-bus callback and its
stream claim; retries, including NumericIndicatorService.close(), silently
returned because the flag was already true. Two pre-fix GC-lock/canonical SQLite/
actual event-bus counterexamples fail: the cancelled closer abandons cleanup,
and retry leaves the real callback registered. Two existing self/concurrent-
callback close cases pass on that old source and remain regression guards.
Only the external public stream lease is a counted fixture port; no network runs.

A retained close task now owns unsubscribe, active callbacks and stream release
until physically complete. The existing cancellation-safe cleanup helper waits
through repeated caller cancellation before propagating it. Concurrent close
joins the same task. An active callback already being drained does not join its
closer from its finally block, preventing a dependency cycle. DataManager and
EventBus optionally carry the originating task so a delegated self-unsubscribe
preserves the original callback's normal completion. Default unsubscribe callers
retain their original call shape and semantics. Numeric calculations, alert
expressions, evaluation cursors, trigger counts and notification actions did not
change.

## Current source checks and inherited frontend

One current combination: **432 backend passed / zero skipped /5 existing
warnings**. Includes the4 new cases, numeric public worker/SQLite/fencing, all
alert/Outbox/delivery/lifecycle/API tests, actual event-bus/GC protection,
subscriptions, seconds/source/controller/profile and executor regressions.
The earlier24-test focused run overlaps this combination and is not summed;
the final combination covers the default-call-shape/doc cleanup as well.

The ENTIRE frontend tree is exactly `c1b14e1cd2ff8f04ed44358e4718289437e4538c`,
equal to prior checked source `e2c01dd9e57dbd04e7cff887460a990c0ddb848f` and main261.
The committed earlier full `npm run check` log is retained byte-for-byte:
**4888 regular/1 performance/130 desktop tests, zero skipped**, plus types,
lint/i18n/architecture/build. This full run is inherited, **not rerun or renamed
as a new run**. Current `npm run build` exited0 and rebuilt the candidate frontend.
Existing SingleChartPanes lint and large-chunk build warnings remain.

Backend architecture has10 existing findings. Raw reports are NOT byte-equal:
2 existing history_worker HTTP imports move33→45 because of numeric worker
imports. Normalized dependency findings are equal; both raw lists/location
pairs are in architecture.json. This is not architecture-clean qualification.

## Prepared but unlaunched Native candidate

The local arm64 APFS clone reuses a verified main250 runtime; current backend/SDK,
newly built frontend/desktop and updated ASAR/ad-hoc signature are verified.
**1068 source files,164 built files,9 plugin assets,76 plugin source files
match; zero mismatches; deep strict signature passes.** Packages/dependency locks
are unchanged; source-verified wheels/core are reused, not rebuilt. This is not
a full standalone runtime rebuild or original CI artifact. No profile exists and
no Native instance has been launched for this source.

The original22-stage driver and byte-identical independent legacy numeric oracle
are copied with only QA path references adjusted. Source/sample comparisons,
rule disable/background continuation, cursor/no-duplicate recovery, three complete
owned exits and stopped-history restoration assertions remain. Only syntax was
checked this round. Old source2c08dced's22-stage public Native pass remains tied
to that source and cannot qualify this new source.

Prepare with fresh CANDLESCOPE_BATCH1_QA_ROOT, the verified old app in
CANDLESCOPE_QA_RUNTIME_SOURCE and CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1; run
assemble.py with the qualified retained Python launcher and node verify.mjs.
Actual retry needs a new profile, no owned Native app, retained Playwright tooling
and the unchanged global public gate: **not before2026-11-06T10:12:49.286Z**.
All current source/helper/tree/command/environment hashes and raw logs are in
source-manifest.json.gz and adjacent evidence. The original single dirty native
script and its checked-out local branch remain byte-identical and untouched.

Keep Draft. Current Native/save/full-owned-quit/restart, Windows, arbitrary
indicator parameters, Pine/Python alerts, wider155/157 and exactly-once external
delivery remain independently open. This qualification sends no external
notifications. Development does not wait for CI; main merging requires exact
final head/current base checks and corresponding product evidence. During the
public gate, continue the separately pending LOCAL_OFFLINE native graphical
Review/backtracking qualification for replay notes/imported BARs.
