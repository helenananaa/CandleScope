# Serialized aggregate volume

Source `9729de37edf9e5d55e816e196cc5f745e9756304`, based on actual main `7acba72e56dfafd3a25ee4ec861509f4e9dc6f96`. This PR is independent of catalog shutdown PR #268 and pending architecture PR #267.

The strict Kline reconstruction path passes decimal-string OHLCV rows into the shared field adapter. Its first raw-enhancement validation accepts strings, but the second pass called `round(volume, 8)` on the original string. `aggregate_kline_rows` caught the resulting TypeError as malformed input and returned an empty 5m/15m reference. Both existing trade parity failures reproduce on an isolated, unchanged main (2 failed / 6 passed).

Convert the accepted fallback volume to float before its second rounding, matching the existing numeric/BarData boundary. The fast numeric path, tolerances, field masking, rounding precision, closure/coverage admission, source identity, trade builder and financial calculations are unchanged. The new contract case covers decimal strings and Decimal values as well as unknown positive-volume/zero-quote enhancements.

Before the fix, the two parity cases plus the new normalizer case failed (3 failed / 25 passed). After the fix, **222 cases across 11 suites passed, zero skips**, including K130 cross-path/page/grouping/coverage, interval semantics/routing/admission and existing trade parity. Commands, environment and source SHA-256 values are in [`receipt.json`](receipt.json); original logs are retained compressed with hashes. The validation command ran with these exact file bytes before the product commit was recorded.

This is source/component evidence. There was no new Native or release build for this isolated helper correction, and it does not qualify Windows, public-market freshness or unrelated pending PR features. CI runs in the background; main merging requires a fresh exact-head/base/check audit.
