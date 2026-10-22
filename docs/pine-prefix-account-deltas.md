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
