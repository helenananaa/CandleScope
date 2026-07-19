use super::RuntimeSnapshotFixture;

pub(crate) const STRATEGY_MARGIN_RUNTIME_SNAPSHOT_FIXTURES: &[RuntimeSnapshotFixture] = &[
    (
        "runtime_strategy_margin_capital_held_long.json",
        "tests/fixtures/runtime/strategy_margin_capital_held_long.pine",
    ),
    (
        "runtime_strategy_margin_entry_affordability.json",
        "tests/fixtures/runtime/strategy_margin_entry_affordability_long.pine",
    ),
    (
        "runtime_strategy_margin_call_long.json",
        "tests/fixtures/runtime/strategy_margin_call_long.pine",
    ),
    (
        "runtime_strategy_trade_outcome_counts.json",
        "tests/fixtures/runtime/strategy_trade_outcome_counts.pine",
    ),
    (
        "runtime_strategy_exit_trade_counts.json",
        "tests/fixtures/runtime/strategy_exit_trade_counts.pine",
    ),
];
