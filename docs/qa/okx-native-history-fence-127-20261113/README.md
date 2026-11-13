# Source-backed OKX native history progress — #127/#126/#129

Base `dd5002d38eb3e1b6c1ddbe3713b90f5ae665d750` (the #389 product tree).
Initial patch/measurements `c67d2a2d5ce9978b4937a9aa5225f8bb2ec8769d`;
final product `ef03074d8e94936c5fe662b9ce2f226fc33e9e7a`.

## Reproduction and correction

The earlier native record in component-byte-native-126-20261113 stopped at
203/202 native 1m/5m rows while live frames increased. Each source journal held
300 selected unprojected historical heads. A real BackfillEngine/SQLite test now
reproduces the cause for both intervals: a disjoint live-tail canonical write
during REST makes the family-wide acquisition check reject the old historical
page. before.log preserves both failures on the complete unchanged backend.

OKX spot native repairs now use the existing bounded optimistic range view.
Capture is before network acquisition, with the same total 8192-slot / 32-window
limits. Only the default semantic identity and a resolver-proven native interval
qualify. The writer transaction requires every row's exact current closed REST
source receipt, then checks the canonical range fingerprint and deletion floor.
It does not grant permission to derived, stale, unreceipted, websocket, foreign
identity, futures, out-of-range or oversized work. No new log/cache/subscription,
limit increase or deletion is introduced. Caller-supplied history-ack markers are
removed and reconstructed only from validated current source heads.

Native range commits also register their own changes with the existing warmup
owner. Without that handoff, a subsequent derived write mistakes this task's own
source insertions for an external correction. warmup-before.log records this
real initial-patch failure; the final fix retains rejection of intervening source
corrections/deletions. Range permission does not renew a persistent job's old
deletion permission or grant unrelated family writes.

Final focused selection: **170 passed**. Final combined aggregation, journal,
cache/revision, history/query/warmup, retention, fork source and Pyne removal
selection: **1936 passed, 6 warnings**. Architecture passes. Source fingerprints
and compressed raw logs/XML are included. Counts from earlier overlapping runs
are not summed. expanded.log includes a test-harness error: the fetcher correctly
returns no FetchedBar for a forming source; the corrected storage-boundary test
uses that source's actual normalized fields. focused-final2 names a nonexistent
test file and ran no tests; focused-final3 is the successful final selection.

```sh
CANDLE_DATA_DIR="$PWD/output/okx-native-fence-tests" PYTHONPATH=backend python docs/qa/okx-native-history-fence-127-20261113/run-regression.py
python backend/scripts/check_architecture.py
```

## Native package evidence

Both revisions ran the original 500-row readiness gate with fresh empty profiles
and real public OKX BTC-USDT spot, no seeded history/response substitution. Each
package is an APFS clone of the retained macOS arm64 bundle, all 1000 tracked
backend/app files overlaid, then ad-hoc sealed. Frontend/runtime/plugins are
unchanged from base build ef8f0e0fa6df299a823f4460b701eb1c3c98361f. All backend
hashes and app.asar match before/after; deep strict signature verification passes.
This is assembled-backend qualification, not a clean frontend/release build.

| Revision | Initial 45m/90m comparisons | Recreated | Saved/restarted | Total |
| --- | --- | --- | --- | ---: |
| c67 initial patch | 533 / 533 | 533 / 533 | 628 / 500 | 3260 |
| ef030 final | 628 / 533 | 628 / 533 | 628 / 500 | 3450 |

All comparisons check closed OHLCV plus the four enhanced fields under the
existing numeric/unknown-field contract. Both workflows explicitly fetch deeper
history, switch to 1m/5m, recreate custom targets, save, fully quit and relaunch
the same workspace. Checkpoints show saved IndexedDB state; no page errors.
Final run exits all 9 then 10 owned processes. Its persisted canonical 1m/5m row
counts are 501/500 and no selected history receipt remains unacknowledged.

The extended driver requires actual frames for 1m/15m/30m/45m/90m at initial,
recreated and restarted checkpoints; all pass on the final revision. This proves
frames at those checkpoints, not long-duration freshness or endurance. Historical
crosshairs are visible in restored screenshots, so header/last-price differences
alone do not establish a forming-price bug; no forming-price assertion is claimed.

The initial package's warning log exposed the missing warmup ownership handoff.
Final logs retain **29 warning/error lines**, including two custom-write fence
errors and materialized-query competition; the database also retains pending/
partial ledger work. The observed workflow passed despite those retries, and
they are remaining concurrency/scheduling evidence, not a clean-log or complete
history-ledger acceptance. Raw receipts, traffic, signatures, screenshots, process
logs and read-only database summaries for both revisions are included. Original
apps/profiles/databases remain in output. Only ephemeral contextToken strings
are redacted; numeric active_read_tokens are preserved.

The existing 127.0.0.1:7897 proxy was set only for these isolated processes, with
the unchanged 8-second timeout. Logging bootstrap only configures WARNING
logging. No system network settings were changed. assemble-native.py preserves
earlier apps; native.mjs uses the retained control driver/value probe and accepts
the same environment variables documented in the earlier native record.

## Correctness cost and remaining acceptance

Fresh process, Python 3.12.15/macOS arm64, full baseline versus c67, source setup
outside timing, two warm plus seven measured writes, no live conflict/network:

| Rows | Capture + commit CPU median µs, baseline → product |
| ---: | ---: |
| 1 | 2775 → 4643 |
| 300 | 18771 → 24714 |
| 1000 | 59785 → 74090 |

All final nine-field hashes match. This is additional validation work to allow
safe progress under concurrency, not a performance improvement. The final
ownership fix only affects calls with a warmup view; these measurements have
none and are explicitly attributed to c67. Costs/samples are in cost JSON/logs.
No stable latency, RSS, Windows/Intel or application endurance pass is claimed.

#126/#127/#129 retain their original uncompleted resource, streaming, shared
history/realtime initialization, retention/rebuild, demand-preview and runtime
matrices. A native two-chart pass and green tests do not complete those issues.
