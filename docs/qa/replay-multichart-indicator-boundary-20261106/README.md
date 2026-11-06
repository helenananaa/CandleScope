# Imported multi-chart replay: actual MA5 and revealed boundaries

This adds Native indicator evidence on the exact already-qualified #264 product `58fb675dd2b750bd32c8cf503afb9f454e633ef7`. The earlier 44-stage acceptance remains unchanged. This new run passed 55 recorded stages, with two real imported BAR sources, independent BTC 5m / ETH 1m charts, actual notes/PNG/fill links, historical Review and same-profile full application restart. Only QA files change.

## Independent result

Both complete 6,000-row CSVs were imported through the packaged app's real local library. Their distant future prices rise to one and two million. MA(5) was added separately to each actual replay chart through the production provided-bars control command. Adding indicators left the complete parent actor snapshots unchanged. The driver observed settled computation, nonempty output and the real chart legend, rather than treating the command receipt as computation success.

The new stdlib-only `audit_indicators.py` reads the actual CSV files, captured HTTP requests/responses and rendered legends. It imports no application calculation code. It independently aggregates only closed one-minute source bars revealed by each selected virtual time, retaining the partially formed current 5m display bucket, then computes MA5 using Decimal.

- All **28** actual canonical compute request/response pairs matched the correct session, track, dataset epoch, symbol and display interval. **1,186 input rows** matched independent OHLCV aggregation and source component bounds. **1,110 output points** matched independent MA5 to less than `1e-9`.
- **13** input rows were partially formed display candles. Their display close time remained in the future, while their final contributing one-minute source close was already revealed. Their OHLCV and MA used only that revealed prefix, rather than the final larger candle.
- **22 actual rendered observations** matched independently computed OHLC and MA values, covering initial 1m/1m, different 5m/1m periods, old/new immutable Review times for both tracks, and the same observations after full restart. The later values were BTC `107.2000` and ETH `512.0000`; at the earlier Review time they were BTC `110.8000` and ETH `518.0000`. Those earlier views did not retain the later value or include the distant CSV price extreme.
- The existing independent financial/link oracle also passed on this new run: exactly two order POSTs; equity `9999.963756980`, margin `20.13333334`, available equity `9979.830423640`. Identical broker-local fill IDs remained scoped to the correct track, price and distinct PNG. Indicator operations did not add orders.

The actual before-exit screenshot was visually inspected: both independently labelled periods, both MA lines, the selected track's note and read-only Review account were visible. All original note/version/PNG/parent isolation assertions in the prior driver remain in this new driver.

## Process, network and artifact identity

Normal full exits took 517 ms and 536 ms. All ten observed owned PIDs were independently absent after completion. The same fresh profile was restarted; no process was force killed. Health checks reported LOCAL_OFFLINE, an installed loopback-only network guard and zero blocked attempts; captured HTTP/WS URLs were loopback, and the renderer error list was empty. The isolated profile remains preserved at the receipt's absolute path.

This reuses the retained immutable arm64 app used by #264; no second large runtime was assembled. Its source/package verification passed before and after: **4,134 recorded source/build input files** matched the current checkout, backend/frontend/packages Git trees matched the qualified source, **1,063 packaged source files / 164 built files / 9 plugin assets / 76 plugin sources** matched the original manifests, and strict deep signature verification passed.

A fresh build on the QA-only head completed, but Vite embeds Git HEAD and dirty state. Its dist filenames therefore differ from the older qualified artifact. The first prelaunch attempt to use the old workspace-dist verifier stopped with a missing old dist asset; no application launched. The new artifact-reuse verifier explicitly checks all 4,134 recorded source inputs, source Git trees, the immutable app's original built-byte hashes, installed plugin source and signature. It does not claim that the QA-head build is byte-identical to the retained build, change the old verifier, mutate the app, or re-sign it. Both the build log and prelaunch classification are preserved.

## Reproduction and archives

The driver imports the unchanged helper from `../replay-imported-multimarket-20261106/native-driver.mjs`. Use the same checkout/product trees, an unchanged previously verified #264 app, and a fresh output root. Copy its original `source-package-manifest.json` to that root while retaining the immutable app path; never copy or overwrite an existing profile.

```sh
CANDLESCOPE_BATCH1_QA_ROOT=/absolute/fresh-root \
CANDLESCOPE_PLAYWRIGHT_PACKAGE=/absolute/playwright-core-1.56.1/package.json \
  node docs/qa/replay-multichart-indicator-boundary-20261106/native.mjs

python3 -B docs/qa/replay-multichart-indicator-boundary-20261106/audit_indicators.py /absolute/fresh-root
python3 -B docs/qa/replay-imported-multimarket-20261106/audit_receipt.py /absolute/fresh-root
```

`receipt.json` inventories the helpers and compressed raw evidence by hash. To audit without launching an app, decompress the `.gz` files in `evidence/` to their original basenames in a fresh directory, then run the two independent audit scripts there. The raw CSVs, requests, complete responses and all 55 observations are included; no SQLite profile or large app is committed.

This qualifies MA5 on these imported sources and periods only. It does not qualify Pine/Python/custom indicators, all indicator warmup/late-response/gap scenarios, all overlays or linked configurations, market-trade imports, public feeds or Windows, and does not close all of #166/#181. Source tests and CI remain the separate #264 evidence; they are not rerun or counted as new passes by this QA delivery.
