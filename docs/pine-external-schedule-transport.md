# Explicit Pine schedule transport (development contract 1)

The chart and Workbench bridges can now carry the core schedule API through
actual isolated workers. This follows the core foundation from
`02fdbebffd9baa1cb80b0aa2454cecf3b7b3207d`; the core binary is unchanged in this
phase. A matching clock still has to supply truthful contexts and actual account
feedback. Transport support does not implement a new BAR/tick matching model.

## Negotiation and units

The new identities are `pine-chart/5` and `pine-external/9`. When the installed
core exposes schedule schema 1, they advertise:

```json
{
  "execution_schedule_contract": "candlescope.pine-execution-schedule/1",
  "prefix_schedule": "candlescope.pine-prefix-schedule/1"
}
```

An explicit execution request must contain that exact
`execution_schedule_contract` and an `execution_schedule` list. The list has one
nonempty group per chart bar, at most 65 evaluations per group. An item contains
`evaluation` and `context`, matching the core schema. The bridge converts bar,
account and requested-stream timestamps from chart seconds to core milliseconds;
`event_time_ms` remains an exact integer in milliseconds. Contexts and event
clocks are not inferred from the date or from observed prices.

Successful explicit responses acknowledge the same contract. The Host rejects
an unnegotiated request or a missing acknowledgement instead of accepting a
legacy evaluation. Missing/wrong contracts, mixed legacy passes and explicit
schedules, malformed envelopes and coerced boolean/time values reject. Legacy
requests retain their existing profile and do not acquire an explicit context.
The current core validates context enums, declarations and execution semantics.

Workbench adapters also advertise `external_replay=candlescope.external-replay/1`.
Availability discovery, persistent evaluation and replay admission use one Host
capability policy. New Pine adapter versions require the replay contract,
compatible prefix transport and a supported order schema. Known legacy adapters
retain their existing compatibility path; legacy Pine versions 1–4 do not gain
a persistent replay capability. The policy is included in the Host runtime code
hash so a changed admission implementation cannot silently resume a frozen job.

## Prefixes, rebuilding and chart checkpoints

The persistent worker negotiates prefix transport independently. Only an
unchanged prefix whose final observations are committed may use an append
suffix. An evolving final group, changed earlier market/account/context data,
or changed static inputs goes through full reconstruction. Both sides own their
cached input lists; mutating a caller's earlier dictionary cannot change the
frozen comparison. A worker error closes that worker; reconstruction uses the
authoritative Host transcript rather than a partially failed worker cache.

A controlled comparison against the prior Host commit reproduces the old alias
bug: changing a previously sent account's equity in place caused an append
instead of reconstruction. The new method requests reconstruction. This
component receipt is `schedule-transport-prefix-alias-before-after.json`; it is
separate from the real-worker qualification described below.

The chart provider accepts the internal context option
`pineExecutionScheduleContract` only when the compiled source envelope and
runtime identity both advertise the same contract, and output is `ORDER_INTENT`.
Each observation then requires both `pineExecutionPass` (bar index and observation
confirmation) and `pineExecutionContext` (script state, trigger and `is_new`).
Its checkpoint stores the full `execution_schedule`; the decision state hash
includes the explicit context. Restore must retain the mode and contexts. The
existing source/runtime identity checks still require recompilation when an
installed bridge changes. A snapshot owns its nested transcript, so later steps
do not mutate the saved checkpoint.

Explicit provider reports use `EXPLICIT_HOST_EXECUTION_SCHEDULE` and count fill
callbacks from their declared trigger. They do not label every uncommitted tick
as an order fill. Existing callback and closed-bar profiles retain their names.

## Candidate and evidence

The corrected candidate is `output/pine-host/phase3/schedule-transport-admission-venv`, using
`schedule-transport-admission-runtime-registry.json`. Its bridge wheel SHA256 is
`fe726dee0f4cb2703c0e0d8999947e5d91839173d9868ec6df0a2b749c81ce00`.
The prior default, risk-stop,
Workbench and schedule-foundation environments remain retained. Package version
stays 0.3.2; use source/artifact hashes and the phase receipt to identify a build.

Focused tests run both bridge routes through real IPC, append and reconstruction,
forming-to-close replacement and worker restart. A chart-provider test restores
an uncommitted historical fill group while preserving script confirmation,
contexts and the decision hash. Another test sends core intents through the
actual Host trade matcher and feeds two real fills back into the core, verifying
position/profit and absence of a native broker result. These fixtures explicitly
drive the schedule; they are not evidence of automatic BAR/tick scheduling.

Final installed-candidate qualification: 446 Host cases passed, with 41 mixed or
non-Pine profiles explicitly deselected. Bridge qualification passed 90 cases;
12 optional Renko-extension cases were skipped. The capability/recovery group
passed 54 cases. These groups overlap and their counts are not additive. Static
checks passed with the repository's existing per-path style exclusions.

The first full gate retained 13 failures and 421 passes. Three Host consumers
still checked old adapter-version lists, so the new bridge was not advertised
as available and did not receive persistent replay workers. The capability
policy above fixes that integration. All former failures pass in the recovery
group and the complete rerun. The failed candidate, log, source hashes and 214
byte-preserved source/test files remain under `schedule-transport-before-admission`.
The corrected source freeze has 215 files. The core was not changed or rebuilt
for this Host phase; its previous qualification is inherited by exact binary hash.

Receipt: `output/pine-host/phase3/schedule-transport-candidate-receipt.json`.

## Remaining work

Normal chart and Workbench service clocks still build the legacy execution
profile. They do not automatically select or generate this explicit mode.
Public admission of `calc_on_every_tick` remains restricted until its real Host
clock, replay identity and recovery are connected. No new realtime behavior is
advertised by the high-level provider's capability descriptor.
The chart provider also retains observed-watermark filtering for requested
contexts. A historical BAR clock needs an explicit requested-data visibility
policy and corresponding tests as part of its integration.

Next connect a separately identified historical BAR matcher and the observed
tick scheduler, then their durable recovery and cost-sensitivity paths. Keep
final-OHLCV historical fill callbacks distinct from evolving historical ticks.
`calc_on_every_history_tick` declaration, metadata and native scheduling remain
core work. The full remaining scope in `pine-host-completion-goal.md` stays active,
including scalable requested prefixes, richer metadata and native risk semantics.
This phase provides no TradingView output oracle, packaged-app acceptance or
official broker-emulator equivalence.
