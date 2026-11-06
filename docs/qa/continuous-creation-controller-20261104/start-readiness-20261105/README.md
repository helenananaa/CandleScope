# Atomic initial readiness after crash-window restoration

PR251 exact-head fb12717a/main18cd6f34 arm64 CI job127105980416 failed the
committed-before-start restoration test: sequence0 instead of20 (1752 other
passes,3 skips,11 warnings). No full financial row/error was printed there.
A deterministic local scheduling counterexample establishes the cause: the
waiter reads PAUSED/revision1, the restore actor resumes, and a second readiness
query sees no pending initial launch. The waiter returned that old zero cursor.

The enhanced existing crash-window test holds resume until the summary is read,
then probes whether it can commit before the intent observation. It reproduces
0!=20 before the fix and passes after it; the same run/account remains unique.
The journal now reads cursor and launch intent under the same Store owner lock;
the intent lookup selects one run instead of materializing all launch IDs.
Controller waits on this coherent metadata pair. Source/financial commits,
checkpoint/index encoding and pause semantics are unchanged.

Focused counterexample1 passed; related Controller/journal/results/runtime/
Store/shutdown/BAR host/source/provider/definition regressions171 passed,
5 existing warnings. Architecture is byte-identical to the same existing10
findings, not an architecture-clean claim. No frontend/package/Native/Windows
qualification was added. CI for the new final head runs in the background;
exact final head/current base checks still gate main merge.
