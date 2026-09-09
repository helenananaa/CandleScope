# Replay server latency follow-up — 2026-09-09

This change follows `0f51201d`. It targets server work inside the remaining single DISPLAY_BAR request; it does not claim that all browser frame latency is eliminated.

## Findings and changes

1. The coordinator sends `v2multi-*` internal fast-forward commands, but the review recorder excluded their types only under `v2part-*`. An ordinary advance therefore built a review projection, scanned artifact budgets and produced an internal-command review record/anchor. The existing exclusion now covers both fast-forward types under both internal prefixes. Durable command/source logs and genuine order/fill/funding/risk review events remain supported; existing review history is not rewritten.
2. Snapshot hashes repeatedly encode large canonical trees. The real component snapshot was 665,781 bytes. Byte encoding now uses the existing pinned orjson dependency after the same strict canonical validation, with the Python encoder retained for unsupported values and minimal installations. Arbitrary-size integers, Decimal normalization, Unicode, enums/dataclasses and float rejection retain their contract. Primitive validation also avoids allocating a type set per visited value.
3. Command responses expose `Server-Timing` for `replay_queue`, `replay_advance` and `replay_display`. These are transport diagnostics, not new fields in persisted command results. Advance includes its persistence work; the phase durations must not be added to nested profiler timings as if they were disjoint.

## Isolated real-service measurements

The profiler copied the **configured** `REPLAY_SETTINGS.db_path` (the active replay-current database), its dataset objects and database-relative HEDGE/account/book inputs. It advanced only these copies, using the actual archived BAR run. Do not substitute the legacy `backend/data/replay.db` when reproducing this experiment.

- Original warmed service commands: approximately 148–163ms.
- After the internal-review fix: approximately 87–96ms.
- Review work inside the original write transaction: approximately 55–87ms per ordinary advance; the corrected exclusion avoids that work.
- Paired encoding of the same component state: Python 8.73/8.86ms; accelerated 4.97/4.88ms. Output length was identical.
- Five corresponding command cursors and state hashes were identical before the review change and after both changes. Review timeline contents intentionally omit the redundant internal events going forward.

Per-method timings are inclusive. Different isolated runs experienced different host load; the encoding comparison was paired within one process. Raw records and the profiling script are in `output/replay-latency-20260909/service-profile-*.json`, `encoder-paired.log`, and `profile_service.py`.

## Chrome verification

Same development frontend, same 15m BAR run, MACD/VOL and account sidebar, with the real-time market page open (10 indicators and full order book):

- Before restart, warmed command HTTP samples: **702, 390, 340ms**.
- After restart, cold first sample: **1541ms** HTTP; **1554ms** to K-line update.
- Subsequent command HTTP samples: **111, 132, 124, 131ms**.
- Server phase samples after warm-up: queue **0.014–0.025ms**, advance **73–103ms**, display tail **12–30ms**.
- Corresponding click-to-K-line update: **347, 348, 329, 319ms**.
- Corresponding click-to-VOL update: **605, 641, 609, 580ms**.

These are small sequential samples across different bars, not a p95 claim. Earlier before-samples collected while validation was running were much slower and are retained separately; they are not used for the warm comparison. UI measurements use the application update events, not compositor paint timestamps. The remaining browser-side scheduling/rendering delay and cold-start delay are visible in the results and have not been hidden behind the server improvement.

Evidence: `stage-before-warm-network.json`, `stage-before-warm-ui.json`, `stage-after-network.json`, `stage-after-server-timing.json`, `stage-after-ui.json`, `stage-after-summary.json`, and `stage-after.png` in the same output directory. Browser validation advanced the active run from 607 to 619 displayed bars and left it paused at 2023-02-18 05:29:59; the isolated profiling commands did not advance the active run.

## Validation

- Broad backend replay suite: 1001 passed, one test hit an H:/E: alias mismatch in the determinism auditor's `Path.relative_to` call.
- Rerunning the affected quality-gate file and API tests from the physical E: workspace: 39 passed, including the failed cross-process golden-session test and the new Server-Timing assertion.
- Focused canonical/review/API tests: 52 passed. Randomized canonical trees and optional-encoder fallback match the reference bytes.
- Ruff and `git diff --check`: passed.
- Browser command responses were successful and no browser console errors were captured.

No frontend implementation changed in this follow-up. Backend source was restarted using the previous process environment after backing up the configured active replay database and dataset objects.
