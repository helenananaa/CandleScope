# Optional native V1 row adapter

This extension accelerates the existing Python SDK BAR path. It does not inspect strategy source, require a pure-market declaration, change the V1 transcript, or execute future rows. User callbacks remain sequential, including execution feedback.

The current validated host is Windows x64, CPython 3.12.7 (Anaconda), MSVC 14.44. This uses the executing CPython ABI, including its type lookup API; it is not an abi3 binary. The runtime checks `ROW_PROTOCOL_ABI == 1` and falls back when the extension is absent or incompatible.

## Build in the active backend checkout

From the backend directory, using the same Python as the backtest worker:

```powershell
python native/setup_native.py build_ext --inplace --build-temp ../output/native-build
python -c "from app.backtest.strategy import _native_rows; print(_native_rows.__file__, _native_rows.ROW_PROTOCOL_ABI)"
python -m pytest tests/test_generic_native_rows.py -q
```

The import probe is required for native qualification: the native test module intentionally skips when the optional extension is absent. Generated `.pyd`/`.so` files are ignored by Git and must be rebuilt or installed with the application. Installing an extension wheel into a different `app` package directory will not make it visible to this checkout; verify the actual module path.

To build distribution wheels:

```powershell
python -m pip wheel --no-deps ./native ../packages/candlescope-backtest-sdk -w ../output/native-wheels
```

Build dependencies may need the package index. Wheel installation and the isolated verification can then run without an index. `scripts/verify_native_installation.py` verifies an installed native wheel together with an installed SDK in a fresh target directory, without importing backend source code.

## Compatibility boundaries

- The host enables the adapter for owned `PythonHostProvider` / `LocalPythonRunner` instances inside the supervised TRUSTED_LOCAL BAR worker. It is not a sandbox or a replacement for process supervision.
- Any conforming user strategy can use the existing `prepare`, `warmup`, `step`, feedback, snapshot and restore methods. No new template or execution protocol is required.
- The native constructor handles bounded ASCII primitive rows with already canonical decimal spellings. Scientific notation, Unicode row values, unusual mappings, nonmatching SDK constructors/layouts and oversized values defer to the existing Python path. Rejection/normalization is not relaxed.
- Input JSON uses the old sorted ASCII escaping, including DEL and control characters. Output JSON is native only when its bytes also match the SDK's output hash rules; Unicode/DEL output payloads use the existing fallback.
- The SDK receives fresh objects and mutable dictionaries detached from receipt bytes. SDK class/member compatibility is checked, owned references survive Python calls, and bounded buffers are heap allocated.
- Both unbound streaming and bound V1 transcript chains preserve their byte content. No transcript version or Run identity changes are introduced.
- `BACKTEST_GENERIC_BAR_ENABLED=0` disables the generic adapter and native event-size counter for reference comparison. It does not disable earlier independent optimizations.
- `output_parts` additionally returns detached host constructor arguments with the sealed V1 bytes. `BACKTEST_FUSED_OUTPUT_ENABLED=0` selects the previous output chain. Older ABI-1 binaries without this optional method keep using `output_wire`; they do not receive the fused-output speedup. No protocol version changes.
- The whole-run worker also supports `BACKTEST_COMPACT_SPAWN_ENABLED=0` for comparing its compact MarketEvent transfer with ordinary spawn pickling. This transport optimization is independent of the native extension and preserves flat payload values, shared payload dictionaries and repeated events. Unsupported event/payload shapes keep ordinary pickling.
- `BACKTEST_HOST_HOTPATH_ENABLED=0` disables the subsequent successful-receipt/empty-decision acceleration and BAR host record/diagnostic fast paths. Optional `record_success` emits the same V1 bytes without an intermediate response allocation; `empty_decision_hash` preserves the existing chained JSON and SHA256. Older ABI-1 extensions lacking either method continue on the corresponding Python path. The BAR service supplies the native hash function to the generic simulation kernel; the simulation package does not import the backtest adapter.
- Optional `execute` joins construction, one current-row callback, output conversion and V1 recording when native SDK field conversion is available. `BACKTEST_NATIVE_ENTRY_ENABLED=0` selects Python orchestration. Planner/risk and process supervision remain outside this call; the original provider deadline still covers the complete callback.
- Optional `bind_outputs` / `object_output` read exact standard SDK output objects under `NATIVE_OUTPUT_LAYOUT=1`. Class replacements, method replacements, changed slot descriptors, subclasses and unqualified values defer to normal output conversion without repeating the user callback. `BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED=0` disables this route independently. Older SDKs without the layout marker use normal conversion.
- The separate host flags `BACKTEST_SPECIALIZED_BAR_ENABLED` and `BACKTEST_INCREMENTAL_CHECKPOINT_ENABLED` control configuration-selected BAR loops and durable terminal-history chunks. See `docs/strategy-four-paths-performance-20260913.md` for schema v8 migration and offline rollback; disabling a flag does not downgrade a database.
- The subsequent report-parts storage advances the database to schema v9. See `docs/strategy-policy-optimization-20260913.md` for the current report/checkpoint policies and v9 rollback. The specialized BAR loop remains disabled by default.

`rows.c` uses CPython's [Unicode API](https://docs.python.org/3.12/c-api/unicode.html) and [tuple ownership rules](https://docs.python.org/3.12/c-api/tuple.html). Native changes require the byte-equivalence, ownership, fallback, and actual-worker regression tests, not just a throughput check.
