# B130 evidence and reproduction

Product commit: `2182ead34e93047c1fcb10f0cfd3332ed78a6583`.
This evidence branch changes only QA documents/scripts/data relative to that
commit. Product PR #174 remains at the tested source, so recording receipts
does not invalidate CI with an additional product commit.

- `source-identity.json`, `merge-proof.json`, `package-proof.json`: immutable
  source, #173 merge, byte identity and signing provenance.
- `checks.json`, `joint-files.json`, `ci.json`: local and cloud regression receipts.
- `ci-*-tests.json`: downloaded CI JUnit counts, skip reasons and artifact hashes.
- `bundled-revision.json`: actual packaged Python/backend, separate SQLite fixture,
  cross-target reuse, external-process amendment, deletion, old-view rejection,
  and shutdown resource release.
- `native.json`, `native-live.json`, screenshots and diagnostics: actual native
  production app, save/complete exit/restart, 6d/8d range API sharing, 4d/5d UI
  switches, Pine, changing forming tails and successive live order-book snapshots.
- `native-parity.json`, `parity-inputs.json.gz`, captured `*bars-*.json`: independent
  closed-bar Decimal oracle and exported public market inputs. No user/profile,
  account database, control connection tokens or credentials are published.
- `benchmark.json`: seven alternating warm trials and a bounded 2,000-operation
  retention probe. This is not an end-to-end speedup or RSS guarantee.
- `index.json`: SHA256 and byte length for this evidence and the report, excluding
  the index itself.

The checkout needs the normal isolated Python test environment and pinned CCXT
fork. From a checkout containing these QA files:

```sh
.venv/bin/python docs/qa/b130-20261031/run_backend.py
.venv/bin/python docs/qa/b130-20261031/benchmark.py
python3 docs/qa/b130-20261031/native_parity.py docs/qa/b130-20261031 --replay
python3 docs/qa/b130-20261031/package_proof.py /path/to/clean-product-checkout
```

The parity replay needs only the standard library and exported inputs; it does
not open an app or database. The package proof requires a clean product checkout
and candidate `.app` built from its production frontend/backend.

For native reproduction, build macOS arm64 using the repository packaging
workflow and retain `.venv` for PID inspection. Set `CANDLE_NATIVE_REPO` if the
built product and QA checkout differ, and `CANDLE_JOINT_NATIVE_OUTPUT` to a fresh
isolated output directory. Run `node docs/qa/b130-20261031/native_acceptance.mjs`,
then `node docs/qa/b130-20261031/native_live_reopen.mjs` with the same directory.
The first refuses to overwrite a profile; the second requires the saved profile.
Both use live public OKX inputs without response stubs. Run
`python3 docs/qa/b130-20261031/native_parity.py <native-output>` to export only
chart/source public market rows from the isolated read-only SQLite database.

Run `bundled_revision_probe.py <fresh-output>` with the candidate's bundled
`Contents/Resources/python-runtime/python/bin/python3`; set `PYTHONPATH` to that
candidate's `Contents/Resources/backend` and `python-runtime/site-packages`, and
set `PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1`. It creates its own fixture,
checks the imported B130 module is inside the app, and never modifies the native
UI profile or user data.

The candidate is ad-hoc signed, not installed, notarized or released. H127,
R129 and J remain separate stages; this is not full 157-item release acceptance.
