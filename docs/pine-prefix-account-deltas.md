# Pine prefix account transport

`candlescope.pine-prefix/2` retains full seed/rebase inputs and immutable prefix
checks. Negotiated append messages may contain `account_deltas`: each dictionary
updates the immediately preceding complete account frame. Explicit nulls clear
optional fields. Unknown fields, a missing seed, mixed full/delta payloads and
row-count mismatches reject before changing the input prefix. The reconstructed
full account still goes through Core validation; this transport performs no
account calculations or matching.

The Host uses deltas only for complete known frame shapes and compares both
Python type and value, so `False` cannot silently replace numeric zero. Other
frames use full transport. Known v1 workers retain their existing full-account
append route. Historical corrections still send a full rebase. A new capability
value advertises v2 without adding more repeated identity fields.

This repairs a retained full-gate IPC budget failure after additional runtime
capabilities enlarged every envelope. The original 30-percent input-byte gate
is unchanged. Targeted actual-worker checks cover both clocks, changing equity,
positions, average-price nulls, malformed feedback, full correction, schedules
and requested updates. These checks do not replace the combined Host gate or
long-session resource qualification.

`candlescope.session-identity/1` additionally bounds the identity envelope as
capabilities grow. Each evaluator or historical-session process first validates
the full installed-code identity. Only subsequent messages may reference its
canonical UTF-8 JSON SHA-256. The worker restores the full identity before
dispatch, and the Host restores it in the public response. Request and response
references must match the same process binding. Unbound, unnegotiated, changed
or mixed full/reference identities terminate the worker. Legacy workers retain
full identity exchanges; stateless calls never accept a reference. Account and
prefix comparison, execution results and correction rebases remain unchanged.

The realtime event capability expansion exposed the same fixed-envelope cost:
the retained managed full gate passed 1,001 cases before failing at 76,243 input
bytes versus 244,420 full-prefix bytes. An actual Core 0.3.3 CI binary separately
reproduces that failure. The original 30-percent budget remains in force.

## Per-request cost

The Host keeps the prefix it last sent by reference rather than as a deep copy.
Rows still sent as the same objects are matched by identity; values are compared
only from the first row the caller rebuilt, and the newest row of each list is
kept as a detached snapshot. A caller corrects an earlier bar, frame or pass
group by replacing it; an in-place change to the newest row is still detected.
Either change resends the full prefix, as before.

`candlescope.pine-prefix-reply/1` bounds the response. A request may carry
`prefix_reply: {"contract": ..., "intent_base": n}` with the number of intents
the Host already holds. The evaluator then omits `graphics` and `raw_output` and
returns only the intents after `intent_base`, when its retained session vouches
for exactly those `n` intents; otherwise it answers with `intent_base: 0` and
every intent, and the Host's full causality check applies. The field belongs to
one request and never enters the retained prefix. Workbench runs request it for
every bar except the last, so published results, checkpoints and the replayed
`last_request` remain complete. The chart strategy provider never reads chart
output and requests it on every frame. With a Core exposing
`EXTERNAL_COMPACT_APPEND_SCHEMA_VERSION == 1`, the evaluator also skips building
the cumulative output and reads diagnostics directly; older Cores return the
same replies at a higher Core cost.
