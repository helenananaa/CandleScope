# Pine Host delivery and acceptance

Active user goal, 2026-10-20: complete the interpreter's Host contracts and their
CandleScope integration in the order below. This is a delivery ledger, not a
claim of arbitrary TradingView equivalence. The interpreter stays independently
usable under `E:/projects/pine-interpreter/AGENTS.md`.

## Scope and evidence levels

The first acceptance scope is local historical strategies on time-based bars,
with fixed sizing, unit contract multiplier, spot cash or the declared linear
perpetual account models. CandleScope owns market data, matching, accounts,
workers and durable recovery. The interpreter owns Pine evaluation, state,
rollback and host-neutral input/output contracts.

Track five separate stages for every capability: language/runtime, Host
contract, execution integration, user entry, and packaged acceptance. `connected`
means source and controlled regression evidence exist. `partial` means listed
requirements remain open. Neither means released. Official-output comparison,
resource qualification and packaged acceptance are independent evidence levels.

Starting source baseline: CandleScope `60ae862906b44ed976ea67c951cfc0228a57b255`, branch
`codex/pine-host-adaptation`; core `02fdbebffd9baa1cb80b0aa2454cecf3b7b3207d`,
branch `codex/pine-host-completion`. The original main checkout is separately at
`83105c0f56c68a8e08f394b23b93a25c7b544a14`; this goal uses the isolated Pine tree.
Development package versions do not identify the source or native binary.

| Capability | Runtime | Contract | Execution | User entry | Packaged | Principal evidence / remaining scope |
| --- | --- | --- | --- | --- | --- | --- |
| Actual account feedback, clocks and requested symbols | connected | connected | connected | partial | open | `pine-host-inputs`, `chart_pine_requested_data`; metadata/calendar and per-expression admission gaps remain |
| Market/limit/stop/stop-limit, entry/exit/generic orders and OCA | connected | connected | connected | connected | open | `pine-chart-orders.md`, `pine-default-sizing.md`; external comments/alerts remain open |
| Historical BAR fill callbacks and simulated closing ticks | connected | connected | connected | connected | open | `pine-chart-bar-callbacks.md`, `pine-bar-path.md`; declared synthetic OHLC path, not physical liquidity |
| V2 historical marks/rules/funding, margin and shared BAR capacity | connected | connected | connected | connected | open | `pine-v2-bar-path.md`, `pine-workbench-v2-bar.md`, `pine-v2-margin-repricing.md`; unit multiplier and fixed opening tick only |
| Six risk rules through actual Host accounts | partial | connected | connected | connected | open | `pine-risk-stops.md`, `pine-workbench-controls.md`; bounded calendars/expressions, positive limits; native rule aggregation remains open |
| Actual account liquidation feedback and ownership | partial | connected | connected | partial | open | `pine-account-liquidation.md`; declared mark-settlement model, no venue/official liquidation qualification |
| Replay snapshot, seek, restart and transaction recovery | connected | connected | connected | connected | open | `pine-workbench-replay.md`; source/implementation identity must match frozen inputs |
| Independent cost scenarios and unavailable-model disclosures | connected | connected | connected | connected | open | `pine-workbench-costs.md`; independent account and strategy runs, shared deadline, AUTO/SKIP |
| Automatic BAR preparation, account-file lifecycle and retry identity | connected | connected | connected | connected | open | `test_pine_workbench_preparation.py`, `workbenchAccountInputs.test.ts`, `pine-workbench-default-upgrade.md` |
| Fixed/cash/equity defaults from authoritative Host accounts | connected | connected | connected | connected | open | `pine-default-sizing.md`; final 392-case installed-worker profile and controlled entry evidence |
| Order comments, leg-specific alert information and alert-disable flags | connected | connected | connected | connected | open | `pine-order-metadata.md`; explicit negotiation, actual-fill binding and restore; no external notification delivery |
| Nonunit multipliers | partial | partial | open | open | open | Stage 3; native support must not be mistaken for external-profile admission |
| Incremental requested-context growth | partial | partial | partial | partial | open | Base external sessions retain state; growing request providers still rebase and lack scalable qualification |
| V2 historical-account trade/book combination | connected | partial | open | open | open | Stage 4; legacy trade/book execution exists separately, V2 BAR options currently reject there |
| Realtime and every-history-tick strategy scheduling | partial | partial | open | open | open | `pine-external-schedule-foundation.md`; explicit context foundation exists, concrete schedulers remain open |
| Official output, large-history resources and final packaged delivery | partial | partial | partial | partial | open | Stage 5; historical named evidence cannot qualify the current complete stack |

## Ordered delivery gates

1. Keep this matrix current, with an explicit limitation and a runnable test or
   probe for each row. Capability failures stay visible at admission; no silent
   fidelity downgrade or fabricated account/market input.
2. Close the historical BAR scope across chart and Workbench, direct and
   automatic preparation, spot and perpetual accounts, risk/fill/closing
   callbacks, cancellation, failure cleanup, durable snapshot/seek/restart and
   independent cost scenarios. First establish one complete installed-worker
   regression run, then a reproducible actual-entry acceptance fixture. Packaged
   acceptance remains open until a freshly built application exercises it.
3. Address external default sizing, order metadata, unit/contract accounting and
   growing requested inputs from reproducible failing cases. Implement Pine
   semantics in the core and concrete execution/data supply in CandleScope.
4. Add historical-account trade/book combinations, then realtime and historical
   tick scheduling. Freeze the causal data and account observations for each
   mode before enabling it in the UI.
5. Compare the same frozen scripts/data/parameters at order, fill, position,
   fees, funding and equity levels. Freeze workload-specific latency/memory
   budgets before resource qualification; cover interruption and restart. Use
   actual official reference outputs when available and state missing reference
   access explicitly. Never label a local synthetic fixture an official oracle.

Each capability is delivered through all applicable stages. A new feature is
not complete merely because its core test or backend endpoint passes. A control
must preserve draft/import semantics and stale-result detection, and a failed
or cancelled run must not publish a completed partial report.

## Reproducible historical regression

Use a backend test Python and an isolated worker installed from the chosen core
and bridge revisions. Supply the matching isolated plugin registry; global
plugin activation and release catalogs are not changed by this command:

```powershell
python backend/scripts/qualify_pine_host.py `
  --runtime-python <isolated-worker-python> `
  --runtime-registry <isolated-registry.json> `
  --output <new-receipt-directory>
```

The script checks required runtime schemas and launcher identity, records source,
bridge/binary and registry fingerprints, and runs the named installed-worker
profile. Its JUnit receipt rejects missing tests, skips, failures and source or
runtime drift. The profile includes legacy trade/book recovery and control
regressions where they share BAR code. Pyne cases are explicitly outside this
Pine profile. This gate does not include the entire repository, browser actions,
packaging, performance or official-output comparisons.

On 2026-10-20 the preceding cost checkpoint had 236 frontend backtest tests and
targeted backend checks pass. Its interrupted broad run is retained separately;
it is not a complete passing Host regression. Restored-account match guards,
instrumented request-test waits and pause-runner cleanup were corrected in
`60ae8629`. A new complete historical-profile result must name its own sources,
runtime and receipt rather than inheriting an earlier count.

The first repeatable historical profile on `730fcf85` subsequently passed all
305 cases, with no skipped cases and unchanged source/runtime/registry files.
Controlled entry work and the preparation market-identity defect are recorded
in [the entry acceptance procedure](pine-host-entry-acceptance.md). The latter's
74-case boundary regression belongs to the later source containing that fix;
it does not replace the full historical profile or packaged acceptance. The
complete post-fix profile at `e0ab1718` then passed all 307 cases with zero skips
and stable source/runtime/registry fingerprints. The subsequent legacy lookup
repair adds six frozen-identity/restart cases to the repeatable profile and passed
83 preparation/context/qualification checks in the fresh managed install. Isolated
candidate plugin installation/protocol and exact payload identity also passed;
complete application packaging remains open.

The first full managed-candidate attempt stopped at one provider timeout after
85 passes while a release compiler was active. Three isolated repeats passed
after compilation, with the original budget; the cause remains unproven. See
the retained failure/recheck scopes in the entry procedure. This candidate's
complete repeat under the unchanged budget subsequently passed all 313 cases,
zero failures/errors/skips, with stable source/runtime/registry fingerprints.
Its receipt is `output/pine-host/completion-goal/historical-20261020-04/receipt.json`
at Host `5d44bbf5`; the earlier timeout and cause uncertainty remain retained.

Stage 3 core checkpoint `de91ea5dc` now honors explicit quantities despite
cash/equity declarations and treats explicit/fixed-default zero quantities as
no-ops. It passed 33 focused Rust checks and 164 checks against a fresh Python
wheel. Its source/binary identity is separate from the historical Host worker.
The later default-sizing implementation adopts sizing schema 1 in both Host
routes, freezes its declaration and uses actual Host account equity. The core
passed 7,929 Rust workspace and 1,838 fresh-wheel Python checks. All 12 real
chart/Workbench account combinations passed, plus production-panel cash/equity
runs and stale-result disclosure. See `pine-default-sizing.md` for exact scope
and artifact identity. The historical runner now also requires sizing schema 1
and includes the new sizing modules; the final annotation-worker profile below
provides complete expanded qualification without relabeling the earlier wheel.
At that checkpoint, order metadata, nonunit multipliers, growing requests,
later schedulers and complete packaged application acceptance remained open.

The 2026-10-21 annotation checkpoint now connects evaluated order metadata
through chart/Workbench actual fills, report tables and saved-prefix replay.
Its SDK repair makes native JSON IPC explicitly UTF-8 on Windows. See
`pine-order-metadata.md` for precise checks and source/artifact identities.
The interrupted default-sizing profile is retained without a passing claim;
the final 26-module profile at Host `236f24c0` passed all 392 cases, zero
failures/errors/skips, with unchanged source/runtime/registry fingerprints.
Its receipt is `output/pine-host/completion-goal/historical-20261021-closeout/receipt.json`.
Nonunit multipliers, growing requests, scheduling and packaged/reference/resource
gates remain separate work.
