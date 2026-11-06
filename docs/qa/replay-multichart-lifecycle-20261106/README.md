# Narrow pane legends and actual replay consumer lifetime

Three horizontal replay charts exposed an existing display defect: the medium/narrow legend rule reserved 220px for controls, leaving zero visible width in the two smaller ETH panes. The candles and MA lines existed, but their close and indicator legends were invisible. The actual source58 failure screenshot and receipt are preserved. The product fix changes only `frontend/src/index.css`: narrow legends reserve 24px instead, keeping their existing height limit and compact presentation.

Product source: `c6b9409a271f26fa6e9550bd586669136c26f592`. This follows the #264/#265 imported BAR deliveries, now merged into main. It does not relabel their earlier source58 acceptance as this new source.

## Actual result

The final packaged arm64 Native run passed **22 recorded stages** in LOCAL_OFFLINE, using a fresh copy of the previously exited synthetic two-track profile. Its original 203 files remained unchanged. The same horizontal split that failed before the fix was retained.

- Actual BTC 5m / ETH 1m / ETH 5m charts displayed close and MA legends. All three legends measured about 135px wide; the close-price and MA-number rectangles were fully inside their visible legend bounds. The screenshot was inspected: all three values were visible, without changing to a different layout or forcing visibility.
- Closing the ETH chart's last consumer closed its adapter WebSocket and removed its chart command groups. BTC's connection and chart remained. Reopening ETH restored exactly one current-process adapter connection.
- Copying ETH and changing only its duplicate to 5m produced two charts with independent 1m/5m periods but the **same single adapter connection**. Closing one retained that exact connection; closing the final ETH consumer closed it. The run retained both FULL account tracks and their original fills throughout.
- With every ETH chart closed, an explicit three-base-event step advanced both held tracks by three source events and 180,000ms to the same global time. It created no orders. Closing charts and changing periods preserved actor financial components, cursor and data epoch; controller/revision metadata is not treated as a permanent identity.
- After a normal full app exit, the same profile restored the single BTC chart and the advanced two-track account. ETH had no chart connection until explicitly reopened; reopening did not duplicate its account or fills. Both charts reached settled indicator output and actual legends, rather than accepting a command acknowledgement or spinner.

The independent stdlib-only `audit_lifecycle.py` verifies all nine recorded layout/account states from the raw socket, DOM, actor, CSV and portfolio observations. With ETH hidden, source closes became BTC `105` and ETH `505`. Independently computed equity was `10000.56375698`, margin `20.33333334` and available equity `9980.23042364`; those values survived full restart and reopening. Exactly two original orders/fills and three ledger entries remained, with **zero new order POSTs** during this exercise. No application calculation code is imported by the oracle.

Normal final-run full exits took **562ms and 550ms**. All ten observed owned PIDs were independently absent. The offline guard remained installed with zero blocked attempts, observed HTTP/WS URLs were loopback, and no renderer errors were recorded. Source/package verification passed before and after: **1,063 source files / 164 built files / nine plugin assets / 76 plugin source files**, zero mismatches and strict deep signature passed. This is a local source-matched acceptance candidate reusing a qualified runtime and source-verified plugin wheels, not a new published standalone runtime build.

An earlier successful 21-stage run on the same new product source is retained separately. The final fresh run added actual three-chart screenshot and clipping-bound checks. Their stage counts are not added together. Both runs shared the same immutable installed app.

## Source checks and preserved attempts

Fresh full `npm run check` passed on c6: **4,891 regular tests, one independent performance check and 130 desktop tests; no skips**. Existing SingleChartPanes lint and bundle warnings remain. Backend and packages Git trees equal qualified source58; its 131 backend passes / zero skips / one warning are inherited, not rerun. All 4,134 source/build input fingerprints were recorded and compared with the earlier qualified fingerprints: only the CSS file changed. A direct raw-Git-byte enrichment check encountered a CRLF working-tree example versus its canonical LF blob; normalized bytes and normal Git diff were clean. That check's classification is preserved; no source file was rewritten to conceal the difference.

Five pre-fix attempts remain preserved with their original profiles, receipts, logs and classifications. The first four exposed driver preconditions: a new chart inherits the active period; old-process socket observations must not count as current-process consumers; an already open watchlist must not be toggled closed; and a catalog button must be distinguished from the existing track's identical label. The fifth reproduced the real zero-width legend defect. The final driver retains the behavioral assertions, scopes socket counts to the actual current backend endpoint, makes immutable stage observations, selects the authoritative track row, and explicitly establishes the intended periods.

Command completion precedes the frontend's receipt of its committed portfolio projection. The driver observes that real projection becoming current and records readiness samples before checking financial values; it does not replace a response or force a reload. These samples are not an application performance qualification.

## Reproduction and evidence

`receipt.json` inventories the helpers, compressed raw receipts, source/package manifests, complete commands' logs, actual screenshots, independent oracle and preserved attempt classifications. The original absolute profile/output paths are retained there. No SQLite profile or large app is committed.

Build the target source and assemble a new candidate using the unchanged helpers in `../replay-imported-multimarket-20261106/`. Copy only a fully exited synthetic seed profile into a fresh root after checking the original files and empty WALs. Keep its original dataset identities/CSVs as `multimarket-identities.json`, `imported-replay.csv` and `second-replay.csv`. For a shared immutable app, copy its source/package manifest with its actual app path; never overwrite a prior profile or receipt.

```sh
CANDLESCOPE_BATCH1_QA_ROOT=/absolute/fresh-root \
CANDLESCOPE_PLAYWRIGHT_PACKAGE=/absolute/playwright-core-1.56.1/package.json \
  node docs/qa/replay-multichart-lifecycle-20261106/lifecycle.mjs

python3 -B docs/qa/replay-multichart-lifecycle-20261106/audit_lifecycle.py /absolute/fresh-root
```

For an archive-only audit, decompress `evidence/final-*.gz` to a fresh folder, removing the `final-` prefix and `.gz` suffix, then run the independent oracle. The receipt, source CSVs, identities and requests are sufficient; no app launch or original database is needed.

This covers one run, two imported BAR FULL tracks, three horizontal chart consumers and the recorded profile/restart. It does not qualify other indicator engines, all layouts/hover/overlay combinations, unrelated runs/windows, public feeds, Windows, or all of #166/#181. CI for the final delivery head is separate and must be checked before merging this fix into main.
