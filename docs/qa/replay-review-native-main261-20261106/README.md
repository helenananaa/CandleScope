# Native graphical Review on current main

This closes the previously unqualified macOS graphical Review part of the formal replay note work in #166. Product source is exactly main `0de39f37f2389b09a35fc91e3a6d8d5844137da8` (after #261). This branch changes QA evidence and drivers only. It does not close all of #166.

## Observed result

The packaged macOS app passed 51 recorded stages using a fresh isolated profile and LOCAL_OFFLINE. The real native local library imported 6,000 closed one-minute BAR rows, with a distant future price extreme after row 4,500. Formal training used the imported dataset, without a public archive or a substituted backend response.

- Created a plan with an actual chart PNG. Advanced the formal replay, bought and closed a simulated position, then saved a later version with a different PNG and both FILL and TRADE links.
- Added immutable markers through the interface. Started read-only Review, selected persistent events and clicked Jump, Previous and Next. The original plan was visible at its time, its later edit and links were hidden there, and the earlier marker showed no note. The later event showed the edit and both links.
- Opened version history in Review: one revision at the original marker, two at the later marker. Opened actual screenshot dialogs and compared their data URLs byte for byte with the original captured PNGs.
- Added a retrospective supplement at the earlier Review event. It carried the supplement label, selected market time and a later actual save timestamp. It did not rewrite the plan and was hidden before its associated market time.
- Observed the actual rendered Review chart's selected cursor, last displayed closed BAR and accessible OHLC. Its last BAR closed at or before the selected cursor; observed highs were 102 or 104. The read-only account rail came from the selected event.
- Compared the complete parent session snapshot across Review navigation and note operations within each application session. Parent cursor, config and financial components also matched across restart. Normal controller reacquisition changed controller/revision/checkpoint metadata across restart; both snapshots are preserved rather than treating that metadata as an unchanged identity.
- Requested two normal full application exits (489 ms and 468 ms). Independently checked that all ten observed owned PIDs were absent. Restarted the same profile, explicitly re-entered Review, and repeated the old/new/hidden note, PNG, link and history checks. This does not claim automatic restoration of Review mode itself.
- Both health checks reported the LOCAL_OFFLINE network guard installed and zero blocked attempts. Captured HTTP/WS URLs were all loopback. No renderer errors were recorded.

The exact source/package verifier passed before and after: 1,063 source files, 164 built files, nine plugin assets, 76 plugin source files, no mismatches, strict deep signature verification passed. The runtime was reused from an existing signed candidate; backend and SDK files were replaced with this exact source, frontend was repacked from source-matched dist, and reused plugin wheels were checked against current source. This is a local acceptance candidate, not a newly published release artifact.

## Evidence and reproduction

`evidence/acceptance.json.gz` is the full staged receipt. The directory also contains actual request/WS observations, marker and note identities, package manifests, verification output, screenshots and hashes in `receipt.json`. Original profiles and uncompressed evidence remain under the absolute paths in that receipt.

The first launched attempt omitted the collapsed notes toggle. Another reached restart but compared controller metadata across restarts. Their complete receipts, classifications and original profiles were retained. A prelaunch verifier path error was also retained locally; no app launched in that attempt. The final driver fixes these harness issues and keeps the functional expectations.

Use a fresh QA root; never overwrite an existing profile:

```sh
CANDLESCOPE_BATCH1_QA_ROOT=/absolute/fresh-root \
CANDLESCOPE_QA_RUNTIME_SOURCE=/absolute/verified/CandleScope.app \
CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1 \
  /absolute/qualified/python -B docs/qa/replay-review-native-main261-20261106/assemble.py

CANDLESCOPE_BATCH1_QA_ROOT=/absolute/fresh-root \
CANDLESCOPE_PLAYWRIGHT_PACKAGE=/absolute/playwright-core-1.56.1/package.json \
  node docs/qa/replay-review-native-main261-20261106/native-acceptance.mjs
```

Build `frontend/dist` from the target source before assembly. Additional fresh profile roots may copy the original `source-package-manifest.json` while keeping its verified `app` path, sharing the same immutable installed app. The plugin verifier and launcher both follow that manifest. The final acceptance used this sharing to avoid duplicating the large runtime.

## Remaining qualification

This does not qualify Windows, public network/live feeds, multiple tracks, AGG_TRADE replay, automatic Review restoration, forks, or the wider original #166 roadmap. It does not advance the Native gates for #227, #223, #218 or #249. Those remain source-specific. No CI was awaited and no main merge was performed for this QA delivery.
