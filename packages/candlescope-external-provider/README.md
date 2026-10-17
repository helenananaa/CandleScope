# CandleScope external provider client

This standalone, dependency-free Python client connects an independently run
model to a local CandleScope Host. It is separate from the network-free
`candlescope-backtest-sdk`. The Host owns market snapshots, watermarks, order
validation, matching, accounts and reports.

The feature is in development and defaults off. No external runtime has been
certified deterministic: the Host records actual outputs with the explicit
`RECORDED_OUTPUT_ONLY` qualification.

Install this directory with `python -m pip install .`, or add its `src` directory
to `PYTHONPATH`. Python 3.11 or later is required; no model framework is required.

```sh
python -m candlescope_external_provider --manifest
python -m candlescope_external_provider --connection /absolute/private/epc_ID.json
```

The first command prints the supplied example model manifest. Freeze that
manifest as an `EXTERNAL_PROVIDER` revision in CandleScope, select an immutable
dataset snapshot and create its connection. The second command explicitly reads
the private connection file and runs the example outside the Host. Connect the
client before running the actual smoke, then Run. Keep the client running through
the backtest. Host restart changes the endpoint and fences old responses; the
client reconnects using the same private file. Revoking the connection invalidates
its credential and cancels linked active Runs.

The file contains a capability credential. Do not publish it or paste it into
the manifest, model state, a report or an issue. On Unix the Host creates it with
mode 0600. The SDK never follows redirects, uses environment HTTP proxies or
connects to a non-loopback address. It does not read Host databases.

For your own model, supply a model factory and frozen manifest to
`candlescope_external_provider.client.ExternalClient`. Each model implements
`prepare`, `warmup`, `step`, `on_execution_report`, `snapshot`, `restore` and
`close`. State must be bounded JSON. Decisions are `{sequence, kind, payload}`;
only evaluation steps can emit them. Model decisions may be SIGNAL or
TARGET_POSITION; only a strategy manifest may declare ORDER_INTENT.
`targetExposure` means absolute base-asset quantity under the existing Host
contract. Order prices use `limit_price` / `stop_price`; Host owns order IDs,
eligibility, risk checks and fills.

The supplied example keeps three past closes and emits a small long target when
the current close exceeds their mean, otherwise zero. Its artifact hash is the
actual example source file hash, and runtime identity includes this SDK and the
running Python version. These are frozen declarations, not Host attestation of
external code, training data, network behavior or hardware.

The desktop bundle also carries `run_example.py`, the SDK source and the data-only
example manifest under `Resources/packages/candlescope-external-provider`.
The Research workbench can register that exact example, bind a connection to the
selected dataset snapshot and show a quoted launch command. Run that command in
a separate terminal; it uses the bundled Python with `-I -S -B` and needs no pip
installation or Host imports. The Host only reads the example identity; it never
imports or runs the model. Other models must load within the existing Host
prepare/step budgets; pre-load large weights before connecting when appropriate.

Each request hash binds run, cursor, operation, payload and the preceding model
state hash. The Host exposes a paginated, read-only decision trace for completed
Runs, including after connection revocation or revision archival. It omits raw
model state and credentials. The SDK retires model instances whose Host sessions
are no longer active. Idle delivery polling reads a consistent snapshot and only
renews a lease when needed, instead of taking a SQLite writer on every poll.

Wire JSON sorts object keys, uses compact separators, ASCII escaping and UTF-8,
rejects duplicate keys, non-finite values and oversized/deep structures, and
uses SHA-256. Host computes state/output hashes. No model may write an account,
fill, ledger, report or Host database.
