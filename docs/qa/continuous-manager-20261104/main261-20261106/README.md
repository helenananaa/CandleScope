# Manager ownership on current main261

Integration source `857479923650e36270d3887aa1383c3fd3630a88` merges the qualified #251 head
`0557b3ce1a611c640e6affbc306d3b659ac2b79f` into #252's prior
`80e554cb05a5ca6a215aaefc87624a378200e0a7`. No conflicts; actual merged main261 is
`0de39f37f2389b09a35fc91e3a6d8d5844137da8`. Existing Manager/app startup and shutdown binding
is preserved alongside main's source-continuity/basis/history changes.

Single combined regression: **351 passed / 2 Windows-specific skips / 5 existing
warnings**. In addition to current result/financial/source/accounting/controller
coverage, this includes actual application ownership, setup cancellation,
failed-close retry and dependency ordering, default continuous owner admission,
LOCAL_OFFLINE read availability and disabled execution, and source/manager gate
identity. The two explicit skips are Windows AppContainer and ACL lifecycle;
macOS passing results are not a Windows claim. Tests use the preserved qualified
launcher with repository SDK/backtest SDK paths and isolated synthetic data.

The actual main261 architecture baseline and this source both return the same10
findings byte-for-byte. No architecture-clean claim is made. The exact command,
environment, test list and file fingerprints are in source-manifest.json.
Earlier standalone/main250/source records retain their original qualification.

No Native app, public feed or user profile was opened for these checks. New CI
is background work; only a main merge waits for exact-head/current-base checks.
The next layer is #253 API/control/stream subscription integration, followed by
UI, repair, saved-reader and immutable research-version return layers. Full
package/native restart and platform qualification remain independent.
