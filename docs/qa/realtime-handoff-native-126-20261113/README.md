# Current backend native attempts: not accepted

Refs #126 / #127 / #129. This records failed native attempts for product backend
`b3564b16f4ac63dd26dd7c2942c26a1dcc17a806` (PR #384, including merged #377).
It does **not** replace the successful earlier #376 receipts or claim that this
changed backend passed native/cold/persistence qualification.

## Package provenance

The signed macOS arm64 standalone app used for #376 was cloned and all 999 tracked
backend app files overlaid from the product revision, removing stale bytecode.
Frontend/packages were unchanged from base build
`ef8f0e0fa6df299a823f4460b701eb1c3c98361f`; bundled Python/dependencies/plugins were
retained. The clone was ad-hoc signed. All 999 app hashes and app.asar matched the
manifest after execution, and deep strict signature verification passed before
and after. This is a source-equivalent backend assembly, not a new frontend or
dependency build, and it establishes no Windows/Intel qualification.

## Attempts retained

| Run | Input / instrumentation | Observed result |
| --- | --- | --- |
| native-cold1 | Empty isolated profile; unchanged original driver | First 45m/90m viewport timed out; screenshot remained loading, canonical rows 0; owned process tree exited. |
| native-cold2 | Empty isolated profile; added request/process/failure-state capture | Same first-viewport timeout, both cells 0 rows and marketReady=false; no browser page errors; workspace saved, process tree exited. |
| diagnostic1 | Empty profile, 30-second diagnostic window after configure | Some source requests recovered: 45m/90m reached 129 rows and OKX catalog eventually returned 1228 symbols. Support logs include warm-start warnings and backfill/write errors. This shortened diagnostic does not run the acceptance workflow. |
| diagnostic2 | Empty profile; diagnostic-only logging bootstrap | Captured RequestTimeout for actual CCXT OKX public instruments requests in kline/depth/catalog routes. Catalog API exposed retryable unavailability. No native acceptance claim. |
| native-warm1 | Explicit earlier public-data SQLite seed | Harness failed before app launch because this checkout lacks .venv/bin/python. Corrected driver accepts CANDLESCOPE_QA_PYTHON; failure retained. |
| native-warm2 | Fresh profile, SQLite backup of earlier real public-data QA only; corrected Python path | Existing history rendered, but first viewport had 125/126 rows, marketReady=false and no received source bars. Original 128-row gate timed out; full workflow did not reach deep verification/switch/save-exit-restart. Owned process tree exited. |

The cold/warm acceptance gate, >=500 deep-history requirement, strict nine-field
readback and source truth were not weakened. A saved workspace or visible old
candles alone is not accepted as a live chart or completed persistence workflow.
No failed profile was relabeled as a cold pass or reused for an empty-profile run.

## Diagnostic limits

An isolated bundled-Python aiohttp probe briefly read OKX time and 1232 public
instrument records successfully. A later bundled CCXT public request timed out;
subsequent plain and CCXT session reads also timed out while reading bodies.
`transport-compare.log.gz` retains that lower-level comparison. These observations
show intermittent upstream/transport availability during these attempts; they do
not establish one exclusive root cause or excuse possible application recovery
issues. The diagnostic shortened flow did see source recovery while the full
flows did not meet their gate. Backfill/write errors still need reproduction with
available source inputs before attribution.

`logging-diagnostic.mjs` appends an isolated `logging-bootstrap` directory to the
sidecar PYTHONPATH solely to install a WARNING stream handler via sitecustomize.
The exact bootstrap is retained as `logging-sitecustomize.py`; no shipped app file
or callback/source behavior was modified for that probe. It is diagnostic evidence,
not the uninstrumented acceptance run. The ordinary native driver has no such
bootstrap. All tests use public market data and isolated profiles; no response
substitution, canonical-row invention or account synchronization was used.

Original databases/profiles and raw logs remain in the isolated worktree output.
Committed receipts contain no authentication values; `active_read_tokens` is a
count and is retained. Manifest, signatures, raw receipts/logs, failures and
screenshots are indexed beside this report. The currently valid conclusion is
**native qualification still pending for this changed backend**. Original issue
requirements remain open; these failures are not converted into completion.

```sh
CANDLESCOPE_PLAYWRIGHT_PACKAGE=/path/to/tooling/package.json \
CANDLESCOPE_AGGREGATION_NATIVE_OUTPUT="$PWD/output/native-empty-next" \
CANDLESCOPE_AGGREGATION_DEEP_HISTORY=true \
node docs/qa/realtime-handoff-native-126-20261113/native.mjs
```
