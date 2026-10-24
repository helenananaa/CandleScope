# Observed requested data in indicator sessions

The ordinary indicator acquisition route supplies
`pineRequestObservation={contract:"candlescope.pine-indicator-observations/1",observedAtMs:T}`
beside its already-local, closed requested rows. T is the inclusive effective
observation boundary, clipped by the revealed cursor and chart boundary. A row
closing at T plus one milliseconds first becomes available at T.

With Core `REALTIME_REQUEST_FEED_SCHEMA_VERSION=1`, source/settings, chart and
requested metadata and the exact requested registry form the immutable session
identity. Appending confirmed requested rows no longer replaces the current
realtime session. Confirmed requested prefixes remain immutable; corrections,
truncation, metadata changes and registry changes explicitly rebase. Stored
identities and prefixes are copied so caller mutation cannot amend them.

Provider-only transactions deliver new rows before each eligible chart
observation. Interval closes use Core's actual request calendar, rather than a
second timeframe implementation. Appended confirmed chart bars consume only
their eligible requested rows; the forming bar consumes the remaining observed
rows. Pine evaluates each chart observation once. Ordinary/varip state therefore
follows the existing native realtime lifecycle, including confirmation and the
next chart bar. Regressing clocks and unobserved future rows are rejected.

The reply acknowledges the observation contract and clock. Older Core builds
retain the legacy snapshot/rebuild route and do not acknowledge this contract.
The eight-session cache, eviction, history correction and failed-update cleanup
retain their existing lifecycle. This is not durable restoration of unrecorded
intrabar ticks, external-account same-bar streaming, or a new live strategy
execution product.

Preserved failures reproduce current-chart varip loss through both the isolated
session helper and complete acquisition/plugin route. A second control shows why
using the old auto-recalculating provider API would execute one combined event
twice. New controls cover lower/higher requested intervals, a higher-interval row
opening before the forming chart bar, unchanged snapshots, independent
subscriptions, confirmation, next-bar continuation, corrected/truncated prefixes
and invalid future input. The installed sidecar control uses the production SDK
JSON-RPC entry point and compares prefix-only delivery with a full transcript and
a restarted process.

Development outputs are separate from the previously qualified tick transport:
`output/pine-host/completion-goal/tick-schedule-20261022/candidate-03/`.
The immutable Host gate in `historical-03/` passes 691 cases across 52 modules,
zero failures/errors/skips, in 1004.156 seconds. All 3,682 source files, installed
runtime files and registry fingerprints remain unchanged. Core
`9e1f6cb5ed93fb1c574459ad57be4f71e04e1b7e` passes 7,986 Rust, 1,965 Python and
172 tooling checks, strict Clippy, formatting, structure, host parity and
generated WASM/Node checks. The isolated Host worker contains identical native
bytes (SHA-256 `dc78be5d6d274e6e3aa0c857763af958246dfe5ac1049d5e5ebfb40e06c3021f`).
Separate checks pass 118 bridge cases with 12 optional Renko skips, and 39 Host
input/sidecar/transport cases. The two post-gate documentation summaries retain
their own recorded delta. Workload resources and actual packaged acceptance
remain required; development wheels do not qualify released application pins.
