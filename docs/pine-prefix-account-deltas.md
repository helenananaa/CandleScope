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
