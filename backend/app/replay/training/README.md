# Training replay ownership

`TrainingRunService` is the application entry point. It owns lifecycle,
command serialization, controller preparation and command recovery. Its explicit
delegates keep existing callers stable; implementations live in their owners.

| Owner | Responsibility |
| --- | --- |
| `admission_service.py` | Market eligibility, committed start time, catalog and track plans |
| `order_service.py` | Order preview, capacity and current historical-book checks |
| `display_service.py` | Revealed history, display grids, display pins and control translation |
| `advance_service.py` | Period-summary preparation and eligibility, durable target scans, progress and cancellation |
| `review_service.py` | Reports and training results, disclosed time projections, annotations and ReviewMode navigation |
| `ordered_playback.py` | Global-time progression, complete timestamp cohorts, account/input barriers and liquidation recovery |
| `*_rules.py`, `service_validation.py`, `command_projection.py` | Pure policy, validation and public result projections |
| `storage.py` | Cross-domain mutation writers, actor/account phases, fork/attach transactions and lazy recorded review context |
| `repositories/` | Runs, markets, reviews, advances, liquidations and deferred curves using the same `ReplaySQLiteStore` |
| `persistence/` | Connection-local SQL and account/portfolio/ledger projections; no independent transaction lifecycle |

The service passes its existing run-actor map, advance-job map and display/admission
caches to the relevant components. These are per-service objects. Shutdown,
command serialization and playback use the same actors and jobs. Immutable market
indexes remain separate from account-specific state. There is no second database
or executor behind the repositories.

`TrainingAdvanceService` owns its summary-build guard. Its actor and advance-job
maps are the same objects used by the facade and ordered playback, so progress,
cancellation and shutdown cannot observe separate task registries. Planning and
liquidation reconciliation are explicit callbacks to the existing coordinator;
command admission, serialization and durable recovery dispatch stay in the
facade. The scan keeps its original commit, publication and cancellation order.

`TrainingReviewService` receives account audit and global-clock readers as
explicit callbacks. Reports retain public-time disclosure and historical-account
audit behavior; ReviewMode still requires the original run to be paused or ended.
It does not advance an actor or acquire an independent storage transaction.

## Atomic writes and publication

1. Prepare a candidate outside the writer when the existing path supports it.
2. Use the original SQLite owner and its existing write callback. Connection-local
   operations may compose inside this callback but cannot commit or roll back.
3. Persist all participating actor states, ledger/risk/review effects and the
   parent command bookmark in the original transaction.
4. Publish after the shared commit. Cancellation drains physical writes before
   releasing the actor leases; failure rolls back every unpublished candidate.

The global-time coordinator retains ordered source/input phases, complete
equal-time cohorts, acceleration qualification and exact scalar fallback.
`RecordedReviewContext` describes the recorder's lazy transaction-local inputs;
the recorder does not import the storage coordinator. Deferred curve planning
and valuation remain outside the event loop and writer transaction.

## Compatibility and checks

This extraction does not version the database, actor checkpoints, durable command
results, review anchors or account calculations. Existing SQLite migrations and
recovery paths remain authoritative. Python imports of private implementation
helpers moved to their owning modules; callers and fault-injection tests should
target that owner. This is not an external plugin compatibility shim.

From `backend`:

```sh
python -B scripts/check_architecture.py
python -B -m pytest -p no:cacheprovider -q tests/test_replay_dependency_boundaries.py
```

The static gate rejects reverse imports, hidden re-exports and common ways to
create independent SQLite transactions or workers in lower layers. It does not
prove arbitrary dynamic code safe. Financial equivalence, cohort ordering,
publication, cancellation and restart behavior require the replay regression
tests. File sizes are not performance evidence.
