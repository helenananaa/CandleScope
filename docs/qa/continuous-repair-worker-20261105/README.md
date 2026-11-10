# Confirmed history repair owner

Application: `00d7efde`, on #255 `cf8308b7`. This adds controller-owned repair
execution and restoration; HTTP/WS, Manager transport and frontend confirmation
are still absent. It does not close the wider strategy requirements.

The backend previews the real dirty range and retained anchor. Up to eight
previews live for five minutes. Confirmation requires its full original account
identity, fingerprint, explicit confirmation and resume intent. Source changes
invalidate consent; unrelated symbols advancing the global storage clock do not.
The accepted plan/cutoff is durable, and uncertain retries do not create another
account or reset the completed result. Original code/configuration remain fixed.

Creation and repair share one serial preparation executor with zero pending
work. One repair reserves its execution capacity. It subscribes before demand
and queries; missing coverage waits for actual Manager events, with no periodic
SQL retry loop. Strategy work consumes at most 1,000 closed BARs per batch.
Source protection can extend beyond the anchor across an unchanged immutable
initial tail without acknowledging those BARs as financially executed.

Repair financial stores live only in marked profile/epoch directories, with
512MiB total, 256MiB per-stage and 64MiB minimum free disk defaults. Symlinks,
Windows reparse points, foreign receipts, unknown files and unmarked data are
rejected. Full reinitialization re-freezes changed initial input; prefix repair
restores the true checkpoint. Staging uses the existing source and financial
engines; it does not copy a guessed balance or run a second evaluator.

Cancellation is durably recorded before draining physical work. The publication
CAS rejects cancelled intent and preserves the old account. Graceful application
shutdown drains provider/thread/store/leases and retains accepted pending intent.
Restart resumes the actual private financial checkpoint or READY publication at
the original confirmed cutoff. Resume-after then advances that same account on
newly closed input. A generic pause cannot remove REPAIR_REQUIRED protection.

After publication, the old watch is retired through a durable cleanup receipt;
after abandonment, only the never-adopted projection/checkpoint/new watch and
owned temporary financial copy are collected. Old financial results and pinned
initial inputs remain retained. Reserved revisions increase across abandoned
requests; defensive source-owner checks prevent an old cleanup from deleting a
later prepared checkpoint. Reclamation reads checkpoint source metadata once at
final deletion, not once per result page. Foreign artifact cleanup is recorded
for retry without blocking app exit after physical resources have exited;
physical lease/provider cleanup failure keeps the store/profile lease until retry.

Final local regression: **337 passed, five existing deprecation warnings**.
Evidence includes real builtin/SDK Python all-from-start and suffix repairs
matching a fresh corrected account, retained old input, absent old watch,
idempotent confirmation, rejected stale consent, disconnected caller, shared
admission, source gap wakeup, shutdown at PREPARING/READY, durable cancellation,
quota failure, preserved foreign directory/symlink, explicit resume to later BARs,
physical cleanup retry, and 1,020 suffix BARs in exactly 1,000+20 batches with old
results unchanged until publication. A different backend PID restores the actual
accepted Python staging account and publishes the exact account/provider state.

`process.log.gz` preserves an early failed test oracle: it demanded the same
provider fencing generation after another Host restore (actual 3, reference 2).
The financial and provider state already matched. The corrected assertion
requires exactly one generation increment and exact equality of every other
provider snapshot field. No product restore tolerance was changed. Prior focused
and intermediate combined logs are retained; counts overlap and are not summed.

Final backend architecture is byte-identical to the existing ten findings, not
a clean architecture gate. No frontend code changed. macOS CI includes the new
repair tests. Windows worker CI now also selects continuous controller/provider/
epochs/repair/source tests; workflow YAML parses, but this local run did not
execute those Windows jobs or qualify the installed Windows application.

No public feeds or native app launched here. The separate public 418 gate remains
`2026-11-05T07:59:57.081Z`; #200 restart-value investigation remains unresolved.
Next work is the default Manager API and bounded user confirmation/progress path,
then actual installed-package and independent Windows acceptance.
