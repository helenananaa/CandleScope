# Repair Manager and wire boundary

Application commit `b57c01c2`, above #256. The default StrategyDataManager exposes
repair preview, confirmation, cancellation and bounded status, using the existing
profile-owned Controller. Reads never create/adopt an owner or execute a provider.
**The product confirmation/progress interface is not connected yet.**

Preview returns the observed full account identity, original/dirty/recompute
range, reused sequence, BAR count, explicit full-reinitialization reason, resume
intent and expiring fingerprint. It excludes provider source, definitions,
private watch receipts/owners and immutable dataset paths. Confirmation requires
strict fields, true consent, a stable Idempotency-Key and trusted local operator
origin because it can re-execute previously saved Python code. Cancellation uses
the accepted base identity. All work goes through bounded Manager operations;
LOCAL_OFFLINE exposes saved metadata/results but denies these mutations.

The existing continuous.v1 account WebSocket includes bounded repair metadata.
Progress without a financial commit sends an ordinary empty-row update at the
same full financial identity. New financial generations still reset and publish
only complete result groups. There is no second polling loop or unbounded stream
queue. SQL projections extract only permitted journal fields; an authorizer test
denies checkpoint, definition and private source/initial-input columns for repair
GET/catalog/status/WS reads. Response pagination reserves 32KiB for the run,
creation and repair envelope, preserving the 1MiB transport bound.

Frontend typed transport and StrategyDataManager carry this status independently
of financial rows. Records are validated, copied/frozen and merged monotonically:
a late HTTP admission cannot rewind newer socket progress, a terminal repair or
a later request. Temporary repair progress never replaces an account balance.

Final backend combination: **346 passed, five existing deprecation warnings**.
Nine new ASGI scenarios use real Manager/source/financial SQLite, immutable input,
builtin and SDK Python providers. Full and suffix HTTP/WS results equal a fresh
corrected reference; old cursors reconnect to the complete new generation,
uncertain confirmation is idempotent, invalid origin/identity/consent/extra fields
do not reserve work, metadata-only READY and cancellation travel on the same
socket without changing old financial rows, offline reads remain read-only, an
actually cancelled ASGI task leaves the durable job alive, and metadata reads
remain independent of recovery checkpoints/private definitions.

Full npm check passes: **4,906 regular + one isolated performance + 130 desktop**
tests, types, lint, plugin/i18n/frontend architecture and build. Focused 26 tests
are included in that count. Backend architecture remains byte-identical to the
existing ten findings; it is not a clean architecture gate. Existing Vite large
chunk warnings remain. macOS and Windows worker CI lists include repair ASGI cases.

Failure logs are retained. `focused.log.gz` contains seven fixture setup errors
because the imported API fixture's storage fixture was not registered in the new
module; the explicit fixture import fixes this. `focused-second.log.gz` has one
incorrect oracle: a source price correction need not change a builtin's financial
decisions. The final check demands exact equality to a separate full corrected
execution instead, rather than requiring an arbitrary difference. No financial
comparison tolerance or source-revision guard was relaxed. Earlier/focused counts
overlap the final combination and must not be summed.

No native app or public feed launched here. The Windows private tunnel returned
connection-layer 429 before its read-only inventory command executed; this is not
a Windows execution result. See `windows-connectivity.json`. The separate public
418 gate stays `2026-11-05T07:59:57.081Z`; #200 restart-value investigation remains
unresolved. Installed macOS and Windows product repair acceptance remain required.

Separately, #246 was rechecked and merged after final-head arm64/x64/CCXT success,
no review blockers, the same tested base tree and exact AST equality of its 26
extracted financial checks. `definition246-premerge.json` records this source
check; it does not qualify the wider strategy issue or replace native acceptance.
