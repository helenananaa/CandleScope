# Workbench retry identity across optional-default upgrades

The V2 Workbench profile added seven optional fields to host-matched requests:
account model, leverage, funding mode, account data, execution-model revision,
participation rate and BAR path scenario. The later independent-cost profile adds
an eighth reviewed default, `cost_sensitivity_mode="AUTO"`. Pydantic includes their defaults in
new request dictionaries. An old durable job or run stored before that change
can therefore reject the same user request with an idempotency conflict.

Retry comparison now treats only those reviewed defaults as equivalent to
absence. Automatic preparation compares its execution envelope; frozen external
preparation compares its run envelope; existing host-account native records use
the same rule. Numeric parameter types, sources, requested contexts, unknown
fields and nondefault account/capacity values retain their original identity.
Native-account requests keep exact comparison.

The original record, config, frozen wire, hashes and preparation fingerprint
remain intact. A successful retry returns the existing job/run before acquiring
inputs, resolving a worker or starting another run. The NativeBacktests fallback
also verifies the stored config against its original stored hash before allowing
a default-field alias. The normal exact-hash path remains unchanged.

This is a comparison rule for additive defaults, not a migration or a replay
compatibility waiver. A frozen historical run still has to satisfy its Host and
interpreter runtime identity before replay. No old report is recalculated under
new accounting code merely because a retry retrieves it successfully.

Regressions cover actual HTTP endpoints, reopening real preparation databases,
SQLite run records, preservation of fingerprints and records, source changes,
every nondefault new field, corrupt stored hashes, number-type changes, native
mode and unreviewed future fields. These tests use isolated historical records;
they do not modify a user's production database or qualify a packaged upgrade.
