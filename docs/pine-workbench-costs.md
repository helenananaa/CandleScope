# Independent Workbench cost scenarios

`candlescope.workbench-cost/1` adds cost analysis to complete Pine runs using
CandleScope account authority. It covers the existing BAR, trade, assisted-book,
depth and sampled-book profiles. Native-account and Pyne execution remain their
own paths. This does not add V2 historical-account print/book admission.

`cost_sensitivity_mode` is `AUTO` by default or explicitly `SKIP`. The Workbench
checkbox persists in drafts, passes through direct and automatic preparation,
and invalidates a prior report when changed. SKIP executes only the primary
account and records `SKIPPED_BY_REQUEST`; it never claims a verified baseline.
The setting and analysis-contract version are frozen in the input. Matrix
contents are derived output, outside the primary input hash, and are included
in the final report hash.

AUTO first reexecutes the identical frozen input in a fresh Pine worker and
fresh Host account. The complete execution result must match the primary,
including fills, graphics, allocation, risk state and account feedback. It then
independently reruns fees/slippage at +25% and +50%, and halves volume
participation where the selected model has that capacity control. Every
executed scenario gets its own evaluator process; no primary intents or account
checkpoint are reused as its trading decisions.

BAR latency has no applicable physical clock. Existing legacy print/book
profiles have no admitted V2 latency/participation settings, and visible book
capacity is not replaced with invented volume. Their unsupported rows have
explicit `NOT_APPLICABLE_*` statuses and `executed=false`. The UI shows no
financial metrics for those rows. They are not counted as counterfactual fills.

Partial replay results omit the matrix. At the complete frozen endpoint,
restored Host execution must reproduce the original result and independently
computed matrix, including its final report hash. Future matrix results are
not attached to earlier replay prefixes. Account-event tapes remain Host data;
each strategy evaluation still sees only its actual causal account/context.

Primary matching and all scenarios share the same 120-second matching deadline.
Every downstream evaluator request is bounded by the remaining time. Baseline
drift, scenario failure, timeout or cancellation cannot publish a completed
partial matrix. Fresh scenario workers close on every path, and an aborted
complete batch does not publish the already-computed primary as a success.

Scenario summaries disclose assumptions, actual fill/fee/equity/position metrics,
decision/fill/ledger/allocation hashes and a complete execution hash. Summaries
and the matrix are individually hashed. Results are robustness checks, not a
parameter-ranking or tuning recommendation. Changing costs may change Pine
decisions, risk triggers, relative order prices and subsequent fills.

Controlled installed-worker regressions cover fee-dependent historical fill
callbacks, V2 gap repricing and volume reduction, spot cash, all four existing
print/book profiles, full replay recovery, fresh worker ownership, SKIP and
failure/cancellation cleanup. In one fixture a higher fee changes a bracket
exit into a market close, so its independently executed price changes too.
The actual Workbench controls and report component are also exercised through
an isolated real backend in a browser; table values, unavailable rows, mode
staleness and refresh preservation are checked.

Known default fields, including AUTO, can compare equal to absence in old
durable submissions (`pine-workbench-default-upgrade.md`). The old record and
report are returned unchanged; retrying it does not backfill a new matrix or
waive its frozen runtime identity. A new run is needed for new analysis.

The OHLC path, volume proxy and declared account/liquidation models retain
their existing limitations. Larger-history resource/performance qualification,
packaged-app acceptance, historical exchange-data acceptance and an official
TradingView output oracle remain separate work.
