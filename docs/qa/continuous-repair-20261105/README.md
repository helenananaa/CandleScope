# Continuous history repair foundation

Application commit: `d4cc90dd`. This is a private foundation above #254, not a
user-available repair workflow and not completion of the broader strategy issue.

Schema 4 retains the original creation definition/projection and stages a new
source epoch separately. Normal readers select their entire account and cursor
in one SQLite snapshot. Bounded result pages and the true recovery checkpoint
are prepared before the final source fence. Under that fence publication checks
the confirmed full financial identity and switches only bounded metadata. Old
source/financial history and original creation idempotency remain available.
Input GC considers original, staged and adopted immutable snapshots.

If a retained checkpoint precedes the earliest source revision, the private
staging account restores its real engine/provider/planner state and financial
sequence, binds a durably forked unchanged source prefix, and evaluates only the
remaining suffix. The test corrects BAR 13 after committing 25 BARs and verifies
that a checkpoint at BAR 10 evaluates only sequences 11..25; account/provider
snapshots equal a fresh full corrected run. Old/future/wrong-epoch anchors and
overwriting a nonempty staging store are rejected.

The read-only preview extracts one current source receipt and bounded retained
checkpoint metadata, without decoding engine/order history, starting a provider,
copying BARs or registering source work. Its fingerprint binds full account
identity, source observations, cutoff and explicit resume intent. It discloses
full reinitialization and its expanded range when no earlier checkpoint is
retained, source continuity cannot be proved, or the immutable initial snapshot
also contains revised input. Admission and workers must still recheck this plan.

Final regression: **316 passed, five existing deprecation warnings**, including
all continuous tests, canonical prefix/revision/cache fencing, Manager ownership,
shutdown failures and pinned local input. Ten repair cases cover suffix reuse,
old/new WAL readers, source amendments before publication, quota rollback,
incomplete/cancelled stages, crash after financial commit before source ack,
recovery and subsequent live batches, and preview behavior. An SQLite authorizer
rejects result-history and checkpoint-wire reads under the final source fence.
The macOS CI test list now includes repair epochs and source owner validation.

Backend architecture still reports the same **ten existing findings**, byte
identical to the retained Manager baseline; it is not a clean architecture gate.
The independent frontend architecture check passes. No frontend code changed.

Earlier failed logs are preserved: `revalidate.log.gz` has 117 fixture setup
errors because the newly reset `/tmp` parent did not exist; after creating it,
`revalidate-second.log.gz` has 118 passes. `seed-tests.log.gz` has two failures
from comparing JSON list series to a receipt tuple; normalized receipt comparison
fixes those and `seed-second.log.gz` has eight passes. Preview extends this to ten
and the final combined regression above. These are offline component/service
checks with real canonical and financial SQLite, not public exchange acceptance.

Still required: physically owned/bounded preparation storage and worker,
confirmed plan admission and journal recovery, startup/shutdown/cancel semantics,
retired source-watch recovery/cleanup, API/Manager transport and user interface.
Old account results must remain accessible throughout. No native or Windows
repair workflow was run. Public native launches also remain gated until at least
`2026-11-05T07:59:57.081Z` after the separate seconds candidate observed 418.
