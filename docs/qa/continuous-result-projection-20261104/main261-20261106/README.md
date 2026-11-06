# Result projection on current main261

Source `484499a5ed3ab6728916922de33209a61393f3fc` merges main
`0de39f37f2389b09a35fc91e3a6d8d5844137da8` into #251's prior2ab8530a.
No conflicts; continuous backtest product code is byte-unchanged by this merge.
Current DataManager/source/basis/history paths from merged #200 and coherent
initial restoration state from #261 are present together with Schema3 results.

Single combined regression: **329 passed / 2 Windows-specific skips / 5 existing
warnings**. The two skips are existing Windows AppContainer and ACL lifecycle
cases in test_python_strategy_runtime.py, not skipped macOS source correctness.
Coverage includes Controller/creation journal, actual Python reconstruction,
source fences/SQL transactions, result migration/WAL/authorizer/paging/budgets,
Store/runtime/shutdown, accounting/active orders and rollback/determinism.
Exact launcher, source SDK/backtest SDK PYTHONPATH, test list and file fingerprints
are in source-manifest.json. The preserved qualified launcher is not resolved to
the system interpreter. No public feeds, Native app or user profile is opened.

Architecture returns10 existing findings, byte-identical to actual main261
extracted from Git and independently inspected; this is not an architecture-clean
claim. Existing319/270/171 records retain their original source/scope. No new
installed-package, Native, Windows or full strategy qualification is claimed.

The stack is being synchronized from the bottom so higher PR diffs do not absorb
unrelated main history. New head CI runs in the background; only a main merge
must wait for exact-head/current-base applicable checks. The bounded private
result reader/schema scope of #251 remains distinct from later Manager/API/UI/
repair/research-return layers.
