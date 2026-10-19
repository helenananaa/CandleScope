# Explicit Pine execution contexts: core foundation

The subsequent [Host transport phase](pine-external-schedule-transport.md) connects
this core API through the two bridges and chart-provider reconstruction. The
qualification and limitations below describe the original foundation checkpoint.

The development core now exposes `EXTERNAL_SCHEDULE_SCHEMA_VERSION == 1` in
Rust/Python. Its specification is `docs/EXTERNAL_SCHEDULE_V1.md` in
`E:\projects\pine-interpreter`. This removes the core contract's coupling of
script confirmation with the final market observation, identified by
`pine-bar-tick-preflight.md`.

Qualified core commit: `02fdbebffd9baa1cb80b0aa2454cecf3b7b3207d` on
`codex/pine-host-completion`. The Host source remains at the Workbench control
implementation from `2207a777f0876572e99d2268455dbf3dc00fb2a4`; this Host phase
updates documentation only.

## Implemented core contract

An evaluation supplies market/account feedback and a context with historical
or realtime state, execution trigger and opening-update status. Historical fill
callbacks can keep Pine's confirmed historical state while the observation
remains open. Realtime ticks require the corresponding strategy declaration.
Closing fills retain the existing explicit opt-in and immutable observation
checks. Legacy pass admission remains unchanged.

Rollback covers ordinary bindings, TA state, arrays/slices, maps, matrices,
UDT fields and drawings, preserving varip state through the existing object
transfer semantics. Stateful price/volume builtins recompute each external
observation from the previous bar. Accounts remain Host-owned; this path never
creates a second native broker ledger. Historical/realtime boundary checks,
incremental mode guards and Python error behavior are specified in the core.

The installed candidate lives in `output/pine-host/phase3/schedule-context-venv`
with its own `schedule-context-runtime-registry.json`. It retains the qualified
Workbench bridge and SDK unchanged. The new core wheel retains version 0.3.2;
identify this candidate by wheel/binary hash and the phase receipt. The default,
risk-stop and Workbench candidate environments are retained separately.

Wheel SHA256:
`3e5da987c307f3a0176a9ef803acc464e1e0d4a6f5fb6e23c77620f1dc43ad64`.
Installed binary SHA256:
`b3762e5dc0df0eff47751b28b1cb66717b51aadb200bd412f71b72503586ba89`.
The new Host worker uses Python 3.12.7; the standalone core binding gate uses
Python 3.10.11. Both installed binaries and the unchanged bridge/SDK files were
reconciled against their artifacts. Retained default, risk-stop and Workbench
binary hashes were checked independently.

## Qualification

The final source freeze contains 10,292 core repository files. The complete
Windows gate passes 7,921 Rust tests, 1,753 installed-wheel Python tests, 172
tooling tests, formatting, Clippy, structural limits, host-parity assertions and
actual generated WASM/Node execution. The new Python schedule group has 22 tests.

Existing actual Host worker regressions pass 30 chart/causal-fill cases and 37
Workbench risk/closing cases. Bridge tests pass 75 with 12 optional Renko
extension cases skipped. Workbench's initial 37 skips were rerun with the
required native-plugin test switch and all passed. These are regressions of
existing Host paths with the new core, not a new connected BAR scheduler. Test
groups overlap and counts are not additive.

The first full Rust attempt ended in a compiler access violation. The retained
failure was followed by a successful complete build/test with one build job.
Pre-fix heap/drawing and price-flow failures remain available. Ordinary arrays
previously retained discarded tick mutations, speculative lines accumulated,
and cumulative volume indicators counted observations more than once. New
regressions verify corrected commits and varip retention; UDT fixtures first
commit their object identities before checking field-level intrabar updates.

Phase receipt: `output/pine-host/phase3/schedule-context-candidate-receipt.json`.
The core retains the corresponding receipt, source freeze, build/test logs and
installed proof under `.local/host-completion/schedule-context-v1-*`.

## Remaining Host and core work

This is a prerequisite, not a connected CandleScope BAR/tick execution model.
At that checkpoint the chart and Workbench adapters still sent legacy `execution_passes`;
they did not negotiate or forward the new explicit schedule. Existing admission
diagnostics therefore remain appropriate until matching, replay and transport
are implemented together.

Next, connect explicit contexts through both adapters and prefix/reconstruction
transport. Add a separately identified historical BAR matcher and clock rather
than relabel the existing worst-case `BAR_APPROX` results. Historical fill-only
callbacks must receive the appropriate final OHLCV; evolving historical ticks
require their own setting and scheduler. Ordinary observed trade ticks retain
their actual event/visibility clock.

`calc_on_every_history_tick` still needs declaration, metadata, native execution
and external-trigger support. Lower-timeframe detail, scalable requested-prefix
updates, native conditional/duplicate risk semantics, richer symbol/session/lot
metadata and the other items in `pine-host-completion-goal.md` remain active.

Core/binding tests and regressions of existing actual Host workers do not prove
a new Host clock, TradingView output parity, a packaged-app release or official
broker-emulator equivalence. Qualification evidence is recorded independently
for each installed candidate; previous failures and environments are retained.
