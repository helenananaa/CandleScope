# macOS seconds restart investigation, 2026-11-05

**Not qualified. #200 remains draft.** The existing arm64 candidate was reused
without cloning another runtime. Before and after each full exit, its 1,058
backend/SDK files, 164 frontend build files, nine plugin assets and 76 plugin
source files matched the manifest, and deep strict signature verification passed.
The application source commit remains `86c29e0a0a9025941a5de373763e44bf3ffb7629`.

The first public run used a new isolated profile and real Binance, Gate and
Upbit transports. Four charts (Binance 1s/7s, Gate 1s, Upbit 1s) reached exact
renderer/canonical OHLCV agreement, visible numerical MA5 checks, later closes,
and saved workspace. First full exit covered 11 owned processes in 15,227ms.
After restarting the same profile, current renderer/canonical checks passed,
but strict equality to saved values failed for Binance 1s at
`2026-11-05T03:39:50Z`: close `80704.78 -> 80704.79`, volume
`0.02445 -> 0.02745`. Numerical MA5 after restart was not reached. Final full
exit covered 11 processes in 15,180ms. No renderer errors were recorded;
backend shutdown includes an HTTP indicator-disconnect CancelledError.

Raw observations for that second, retained in `changed-source-observations.json.gz`:

| Observation | Received UTC | Trades | Close | Volume |
| --- | --- | --- | --- | --- |
| WS closed | 03:39:51.072 | 27 | 80704.79 | 0.02745 |
| REST | 03:39:51.822 | 26 | 80704.78 | 0.02445 |
| REST | 03:39:55.446 | 27 | 80704.79 | 0.02745 |
| REST after restart | 03:41:14.227 | 27 | 80704.79 | 0.02745 |

The post-exit read-only probe also identifies the corresponding Binance 7s
volume change `0.44908 -> 0.45208` at `03:39:48Z`; Gate and Upbit saved rows
match. These are source observations and persisted differences, **not proof
that restart lost data or that every source revision is correct**. The original
driver did not capture disk before the second launch. The failed profile and
full original diagnostics remain under
`output/seconds-contracts-20261102/native-qualified-20261105`.

The driver now adds a read-only SQLite checkpoint after the first full exit and
another after live restart, retaining source heads/observations and exact
full-series-identity OHLCV comparison. The original strict restart assertion is
unchanged. Two stdlib tests verify exact differences/missing rows, provider
isolation, unchanged database bytes and refusal to create a missing database.
An offline run against the original failed profile reproduces the three changed
fields above; its output explicitly says it is **after** the second launch.

The new witness run stopped before catalogs finished: Binance returned 418.
Both shared gate state files now record no public launch before
**2026-11-05T07:59:57.081Z** (15:59:57 Asia/Shanghai). All owned processes exited
and package/signature verification passed. Thus no cold-storage witness was
obtained in that run. Its isolated profile remains under
`output/seconds-contracts-20261102/native-cold-storage-20261105`.

Compressed evidence contains selected actual receipt steps, saved samples,
source observations and the read-only post-exit result. Full native profiles,
screenshots and traffic remain local. No product source changed, no assertion
tolerance was relaxed, and this provides no Windows or full release qualification.
