# Research draft isolation on main261

Source `0e50ecb57a58758fbf36cd457e4eb36be9f9828d` merges prior `f84f6b1082ab53ab968fb3f5d3f7e06028880c2a` with saved-reader dependency `bec611d0ff85c536d4d7f397ea2ff298a5228e32`
without conflicts, including main261 `0de39f37f2389b09a35fc91e3a6d8d5844137da8`. Chart-to-research independent
draft semantics remain as described in the parent README.

Current full TypeScript and focused real Store/handoff/chart-tester tests passed:
**160 passed / zero skipped**. Exact commands and changed source hashes are
adjacent. Backend and packages trees are byte-identical to qualified #259, so its
backend evidence is inherited explicitly; no duplicate backend run is claimed.
Final research-return layer will run the full frontend check independently.

No new real-browser, package/Native full-quit/restart, Windows or live-market
qualification is claimed. Prior browser evidence retains its own source identity.
Keep Draft; development continues without waiting for CI; main merges require
final-head/current-base checks and corresponding product evidence.
