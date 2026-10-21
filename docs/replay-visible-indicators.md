# Replay display indicators

Replay charts opt into `display_math: "viewport-v1"` on the existing
`indicator-compute` endpoint. Omitted policy retains the full-origin canonical
contract. Execution, strategy inputs, matching, clocks and account indicators
do not use this display policy.

The client requests the visible range plus the live chart's padding, falling
back to a bounded recent window before the chart reports its viewport. Only
builtin display jobs use this selection. Caller-provided script inputs retain
their existing full bounded window.

The server uses the same warmup budgets as live display: period minus one for
MA/BOLL, three periods for RSI/ATR, five for EMA, and five slow periods plus
three signal periods for MACD. This is a versioned display initialization
contract; it does not promise the state obtained by replaying an asset's entire
listing history. No execution indicator's initialization is changed.

## Stable overlapping windows

`display_indicator_anchors` is a derived table in the existing indicator-cache
sidecar. It is separate from legacy canonical checkpoints and financial data.
An unseen window starts with bounded warmup. Mathematical states are retained
at the window's beginning, every 128 rendered bars and its last closed boundary.
An overlapping request restores those immutable states instead of replacing
them with a new left-edge seed. When extending left, an encountered retained
state wins; previously displayed values therefore keep their original seed.

Keys bind the frozen source/epoch, training/track, display interval, builtin
implementation and mathematical parameters. Colors affect presentation only.
Monthly boundaries use the calendar grid. Declared gaps reset state. Forming
bars are evaluated transiently and never publish an after-bar anchor.
Cancellation drains the bounded read without publishing incomplete math.

Anchors persist across process exit and period round trips. They are not
silently evicted: the table has a 100,000-entry ceiling and rejects new work at
that limit rather than reinitializing previously displayed windows. Explicit
removal of the derived sidecar causes display initialization to start again;
it does not alter account or strategy state. Any future change to initialization
or anchor semantics requires a new display policy version.

Per-chart JavaScript forward-state shortcuts are not used for this policy:
they cannot observe anchors established by sibling charts. The bounded server
path reuses the shared display states instead. Playback samples retain the
input rows together with their selected time/source sequence; delayed work
cannot read a newer mutable chart window under an older observation.

## Validation

Regression coverage compares a cold window against the ordinary live builtin
formula with its bounded warmup, checks exact overlapping values across pan,
zoom, period/calendar round trips and reopen, checks forming tails/gaps/cancel,
and confirms the legacy checkpoint table and account snapshot remain unchanged.
Real HTTP/Node probes exercise both legacy full-origin and display clients.
The owned Chromium fixture covers real React lifecycles, continuous playback,
rewind cancellation, controlled multi-chart restore and script-input isolation.
Normal packaged-app cold preparation and complete-exit/restart qualification
are recorded separately from component/browser checks.
