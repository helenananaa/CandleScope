# PR integration acceptance — 2026-11-17

This candidate composes the latest #436 product with main after #442 and #443.
The macOS arm64 runtime/plugins come from the verified main CI artifact at be8ae299; all tracked backend application files and a freshly built current frontend are overlaid on a new copy and strictly signed. This is retained-runtime native evidence, not a fresh release or Windows acceptance.

The driver uses an empty isolated profile, real public Binance USD-M history, unchanged 128-bar / 180-second per-cell readiness, independent market and EMA checks, ten minutes of actual renderer updates, native hide/restore, interval switching, reconstruction and saved exit/restart. No market seed, response substitution or diagnostic bootstrap is enabled. Each minute must produce a distinct rendered tail state for every chart.

Result: **FAIL** on product `ee8071fbe6dfcc8b562cf315133dfb644800d2e8`, in `cold-four-prime`. At timeout the 89m/97m/101m/10007m cells contained 25/28/23/2 bars; all were still loading and none was market-ready. The required minimum was not reduced. The 803 captured renderer HTTP responses were 200 and live streams were active. Backend logs also contained stale-acquisition write rejections and bounded storage requery warnings; these are observations, not a confirmed root cause. The run never reached numerical, ten-minute renderer continuity, hide/restore, reconstruction or restart acceptance. Owned packaged processes exited in 6.883 seconds.

The compact immutable receipt is `history-native-failure.json`. Complete receipt, traffic, process/resources logs, screenshot and isolated profile remain under `output/merge-acceptance-20261117/native-history-1`; the candidate and its exact file manifest remain in the sibling `candidate` directory. No historical pass qualifies this product. #436 and its constituent source PRs remain unmerged/open.

Offline validation of this integration: full frontend check/build passed (5250 functional, one isolated performance and 137 desktop tests). The backend history selection initially passed 1328 tests with ten subprocess import failures in the test environment; after configuring the isolated test virtualenv, the exact ten selectors passed. This covers all 1338 selected tests, and is not described as one clean full-suite run. It does not replace the failed native gate.
