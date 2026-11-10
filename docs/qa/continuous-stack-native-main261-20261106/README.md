# Current stack: saved continuous account in a packaged app

This qualifies the **cold read-only saved-account entry** on the integrated #251–260/#262 stack. The installed arm64 app contains exact source `f1da4a74361e3777ef867d67ba620d84cb7bf465`; its product source is unchanged from `91af4c3cee3b6cbe8adb4454b93ca5d3b6d3f1d9`. This delivery changes QA evidence and a stale evidence descriptor only.

## Actual Native result

Eleven recorded stages passed in the packaged macOS app with a fresh isolated LOCAL_OFFLINE profile. Only a previously exited synthetic account database and its seed receipt were copied from the earlier account exercise. The original profile remained byte-identical. The app used its actual bundled backend, HTTP/WS and SQLite; no backend responses, feature masks or execution capabilities were substituted.

- Opened Strategy Research without a dataset, chart or editor program. Used the actual **保存的常驻账户** entry and selected the persisted account.
- Displayed equity `10003`, position `1` and `25` events, with `REPAIR_REQUIRED`, the latest `COMMITTED` repair, and the explanation that source history changed again after repair. No execution or repair controls appeared in this read-only dialog. LOCAL_OFFLINE execution capability remained false.
- Normally closed the whole app, checked that every observed owned process exited, and used the bundled Python for an immutable read-only SQLite witness. The complete run, active-epoch definition and checkpoint matched the original seed: saved-account SHA-256 `779de17a7cafacec0f0e90743ce29816bce8ffc697e3b37d8e535bec7e3b922c`. The witness itself did not change database bytes.
- Restarted the same profile and repeated the real account view, then normally closed it again and repeated the cold witness. All ten observed owned PIDs were also independently absent afterward. The recorded exit-and-witness observations were 659 ms and 621 ms; these include witness work and are not app-close performance measurements.
- Health checks after both launches and both account views reported the offline guard installed and zero blocked attempts. Captured HTTP/WS URLs were all loopback; the receipt contains no renderer errors or mutating continuous-account requests.

The before/after package checks covered 1,076 source files, 172 built files, nine plugin assets and 76 plugin source files, with zero mismatches and a strict deep signature pass. This is a locally assembled acceptance candidate reusing a previously signed runtime and source-verified plugin wheels, rather than a newly published standalone release build.

## Source and evidence identity

All 3,073 inherited source fingerprints and the `backend/app`, `frontend/src` and `packages` Git trees were independently matched. The earlier full source checks remain inherited, not rerun: 436 backend passed / two Windows AppContainer or ACL skips / five warnings; `npm run check` had 4,940 regular tests, one separate performance test and 130 desktop tests, with no frontend skips. A fresh frontend build at this Native target passed. Existing lint and bundle warnings remain recorded. The first build command used the wrong working directory and failed before building; that log is preserved separately.

The #262 source descriptor had stale PR259/reader branch labels copied into it. Only those PR/branch labels were corrected. The original compressed descriptor is preserved here. Source IDs, fingerprints, previous test results and previous `native: false` qualification were not relabelled. `source-inheritance-prelaunch.json.gz` intentionally records the prelaunch state; the new Native receipt is the authoritative result for this narrowly scoped acceptance.

`receipt.json` inventories compressed raw receipts, package manifests, cold witnesses, original-profile protection, both screenshots and reproduction helpers by hash. Original profiles and uncompressed evidence remain at its absolute paths. No profile database is committed.

## Reproduction

Build `frontend/dist` from the intended source. Use a new candidate root and an already verified compatible signed runtime; never overwrite an existing candidate or profile:

```sh
CANDLESCOPE_BATCH1_QA_ROOT=/absolute/fresh-root/candidate \
CANDLESCOPE_QA_RUNTIME_SOURCE=/absolute/verified/CandleScope.app \
CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1 \
  /absolute/qualified/python -B docs/qa/continuous-stack-native-main261-20261106/assemble.py
```

Copy only an exited **synthetic** account's `data/continuous-strategy.sqlite3` and `seed-receipt.json` into a fresh profile, checking that no nonempty WAL exists and preserving the originals. This is an explicit read-only persistence fixture, not a fresh strategy execution claim. Then run:

```sh
CANDLESCOPE_NATIVE_QA_ROOT=/absolute/fresh-root/candidate \
CANDLESCOPE_READER_NATIVE_PROFILE=/absolute/fresh-root/profile \
CANDLESCOPE_READER_NATIVE_OUT=/absolute/fresh-root/acceptance \
CANDLESCOPE_PLAYWRIGHT_PACKAGE=/absolute/playwright-core-1.56.1/package.json \
  node docs/qa/continuous-stack-native-main261-20261106/native.mjs
```

## Remaining gates and retained recovery

This does not qualify Native strategy initialization/execution, gap resume or repair on this source, the selected-research-version-to-chart Native flow, Windows, public feeds, or full #157/#158. The earlier browser execution fixture and earlier-source Native execution remain separate evidence. #262 stays Draft and its dependent stack is not merged by this QA delivery.

Separately, the failed intermediate imported-multimarket app (`bdeac1e…`, not a qualified release) was replaced locally with a 22,533,757-byte exact recovery overlay over the retained good `58fb675…` app. A real temporary restore matched all 18,698 tree entries and passed strict signature verification before removal of the failed executable. All original profiles, evidence and 191 protected files remained unchanged; no symlink consumers or active handles were found. Observed free space increased by 353,320,960 bytes during retirement and temporary-restore removal. This is not a claim that the app's 931 MB logical size was physically reclaimed. The overlay and its retained base must both remain available; their local paths and audit are included in the storage receipt.
