# Accepted component byte accounting — #126

Base `e628fdf45aa5b3c6c034e869e804f73791b0b305`; final product
`04667fad927f20413add2475f12e42e94c3fc663`. Cost measurements and the first
native pass use `5d93d3037901980b64983b13f9276a876cd293aa`; the final product
additionally counts an empty proof mapping instead of treating it as absent.

The old 1024-byte component allowance underestimated large accepted source proofs.
ReadonlyFields now caches reference weights when freezing. ComponentSnapshots
maintains weights through its dictionary operations; immutable publication copies
reuse the frozen values and copy the index in C. Foreign mutable values preserve
their aliasing contract and use live graph traversal. ReadonlyFields subclasses
are captured into the plain immutable type rather than trusted as immutable.
The heap diagnostic also exposes the existing mapping proxies and the new private
counters. No extra source-value cache, data deletion or limit increase was added.

Final focused regression: **76 passed**. Final combined selection: **1763 passed,
6 warnings**. Baseline ownership probe fails both small/large proof cases and
the product passes. Empty-proof accounting initially failed; its failure and
corrected run are retained. Earlier invocations are separate, not summed.
Architecture and source fingerprints accompany the raw evidence.

```sh
CANDLE_DATA_DIR="$PWD/output/component-accounting-tests" PYTHONPATH=backend python docs/qa/component-byte-accounting-126-20261113/run-regression.py
python backend/scripts/check_architecture.py
```

## Controlled costs

Full baseline backend versus measurement head 5d93, same Python 3.12.15 on macOS
arm64, fresh processes, default DataManager registration, no network. The manager
is not started and its storage bridge is inactive in the publication probe.
Construction is outside publication timing. Payload and final hashes match.

| Held case | Estimated bytes, old → new | Visible reachable heap, old → new | CPU P50 µs, old → new |
| --- | ---: | ---: | ---: |
| 97-component pending | 101048 → 355379 | 152687 → 167511 | 539 → 514 |
| 10007-component pending | 10248888 → 36248385 | 15145562 → 16666706 | 55062 → 52823.5 |
| 10007-component callback | 30758112 → 77458056 | 10258477 → 11019109 | 1458 → 179 |

All publication probes release to 192 estimated / 432 visible bytes. The counter
adds real per-map memory; the diagnostic increase also includes previously omitted
mapping proxies. These are accounting and localized copy costs, not RSS savings
or an application speedup claim.

Input probe: previews disabled to isolate computation, closes retained, identical
shared-input feature setting on both versions. Single-target CPU P50/P95/P99
163/186/207 → 172/183/214 µs; near-tail 10007m/10009m/10037m/10039m
484/557/687 → 442/490/603 µs. Near-tail unique component values remain 10001,
preparation deferrals remain zero; estimates 41886298 → 104340318 bytes and
visible heap 13749549 → 14521857 bytes. See measurements.json for all samples,
hashes, GC, RSS scope and owner details. These are single-host instrumented
samples, not a stable latency, endurance, native or Windows qualification.

## Limits and native evidence

Weights count references and can overcount shared immutable keys/leaves. Accepted
source-proof hints do not bound arbitrary later mutations of a consumer's mutable
source_refs. Other admission, retained-state, native allocator and joint-resource
contracts remain separate work; this is not a hard heap/RSS cap or completion of
#126/#127/#129.

The companion [native record](../component-byte-native-126-20261113/README.md)
distinguishes a full 5d93 source-revision workflow pass from the final 04667
workflow failure during 1m/5m history initialization. Neither is hidden or used to
qualify sustained realtime after restart or forming-price correctness.
