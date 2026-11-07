# Real DataManager chart source qualification

Product/test source `71284f77bbe866168230d34e50e66d71f6dc1b5e`, based on `3a27a4a6`, still integrates main
`a1302842`. The exact command, environment and changed-file SHA256 map are in
`source-manifest.json`. Single combined regression: **378 passed / 5 existing
warnings / zero skips**. The compressed raw log and 21 case receipts are retained.
Earlier 268-test controlled-source evidence keeps its original source identity.

The chart now registers full-semantic-identity source-family watches before the
first query, forces DataManager's existing min_revision cache synchronization,
and guards runtime cursor adoption and post-serialization publication. It owns
at most active/candidate watch receipts, no extra OHLCV or script output history.
Derived queries prove their own unprocessed target materializations against the
final version-checked durable head; they cannot rebase committed input or accept
a later writer. Exact-series financial receipts and wire schemas are unchanged.

The actual ASGI/runtime tests now use real DataManager/cache/SQLite. A separate
SQLite process silently changes close+1 without a transport correction or cache
notification. Both HTTP reads and WS attachment rebuild at the same origin,
generation2, with cumulative close+1 while the coarse revision token stays the
same. A deliberately long cache poll interval proves forced synchronization.
Changes during actual runtime preparation and read serialization reject stale
results; no fenced execution reaches the observer. The 7m case begins with an
unmaterialized target and detects a later 1m child mutation. Existing forming
counter500/501/502/503, negative-offset deletion and scene assertions still pass.

Additional tests cover rollback/no-op and out-of-prefix appends without execution,
query-head/acquisition/committed-progress fences, family semantic isolation and
empty deletion, private amendment clock and eviction, failed source commit after
runtime advance (restored old cursor plus required rebuild), release failure
holding capacity until retry while preserving a foreign strategy watch, and
missing source continuity failing closed but allowing owned-domain deletion.
All 22 owned transport workers exit0 and are independently absent; subscriptions,
leases, registries and indicator source watches end at zero. The original 39
dirty QA files are byte-identical and excluded from these commits.

Feed callbacks remain controlled. This is source/runtime qualification, not a
renderer, installed package, public-exchange, macOS save/full-owned-quit/restart
or Windows result. The frontend hook remains unbound and the original Native
counter500-to202 failure remains unresolved. No SDK/bridge source, wheel or
installed package was changed. The initial missing fixture row fields and a
cleanup test's incorrect exception expectation are retained as scoped failure
logs, not product defects or passing results. A temporary test-directory setup
failure also remains in local logs; the final combined run is authoritative.

Next: bind chart lifetime/range scheduling/WS references and domain-generation-
sequence admission, then run source-matched renderer and original Native assertions.
