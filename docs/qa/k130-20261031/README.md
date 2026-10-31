# K130 evidence and reproduction

Product commit: `323061a655fa4f7ebdd18fcdde660a5e3043ca13`.
This evidence branch changes only QA documents/scripts/data relative to that
commit. The PR itself remains at the tested product commit, so recording CI
results does not invalidate them with another source update.

- `source-identity.json`, `merge-proof.json`, `package-proof.json`: immutable
  source, prior-PR merge, candidate-byte and signing provenance.
- `checks.json`, `joint-files.json`, `ci.json`: local and cloud check receipts.
- `ci-*-tests.json`: downloaded CI JUnit counts and platform-specific skip
  details, with the GitHub artifact and downloaded archive SHA256 identities.
- `regression-*.json`: five known failures before K130 and their repaired outcomes.
- `native.json`, `native-live.json`, screenshots and diagnostics: fresh-profile
  native save/exit/restart, subsequent live updates, and process cleanup.
- `native-parity.json`, `parity-inputs.json.gz`: independent closed-bar numeric
  oracle and exported public-market inputs. No user/account database is included.
- `benchmark-*.json`: bounded microbenchmarks, not a performance improvement or
  RSS/retention guarantee. See the report for the measured scope and overhead.
- `index.json`: SHA256 and byte length for this evidence set and the report;
  the index itself is excluded from the list.

The product checkout needs its usual isolated Python test environment and
pinned CCXT fork. From a checkout containing these QA files:

```sh
.venv/bin/python docs/qa/k130-20261031/run_backend.py
.venv/bin/python docs/qa/k130-20261031/regression_probe.py /path/to/product-checkout
.venv/bin/python docs/qa/k130-20261031/benchmark.py /path/to/product-checkout
.venv/bin/python docs/qa/k130-20261031/native_parity.py docs/qa/k130-20261031 --replay
```

The last command needs only the Python standard library and writes `parity.json`
beside the exported inputs; it does not open an application or a database.

For native reproduction, build a macOS arm64 candidate using the repository's
desktop packaging workflow, retain the `.venv` needed for PID inspection, and
use a **fresh** output directory for `native_acceptance.mjs`. Set
`CANDLE_NATIVE_REPO` when the built product and QA checkout are separate, and
`CANDLE_JOINT_NATIVE_OUTPUT` to the isolated output directory. The native runner
uses public OKX data without response stubs and refuses to overwrite an existing
profile. `native_live_reopen.mjs` then requires that same existing profile and
verifies four changing forming tails plus successive valid order-book snapshots.
`native_parity.py <native-output>` exports only the chart/source public-market
rows needed by its independent oracle from the isolated read-only SQLite data.

The candidate was not installed over `/Applications/CandleScope.app`. Production
acceptance remains scoped to these scenarios; B130, H127/R129/J and broader
source/long-run qualification remain separate stages.
