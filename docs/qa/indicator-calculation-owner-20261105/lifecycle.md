# Bounded calculation lifecycle and explicit stream release

Product/test source: `1f9ada60b62d971e706d76dc9be87349da630771`, on
main200 `a1302842a2a886d27025c73a1c5c151e07fe0fe1`. This extends the
earlier computation-owner foundation; it does **not** bind chart HTTP/WS or
the renderer. The original Native counter failure remains unresolved.

`IndicatorRuntimeService` now owns a registry with eight entries by default,
180 seconds idle lifetime and a 30-second collector. Creating, borrowed,
draining and cleanup-failed entries retain capacity. Opaque server-generated
ids join later transport borrows to the same existing calculation. Cancelling
a waiter cannot cancel an admitted creation or release physical execution;
shutdown rejects new work and drains these owners before global input cleanup.
The registry stores no market rows or additional output cache.

The source audit found a cleanup gap: releasing only Pine input dependencies
left durable sidecar sessions behind. The optional negotiated SDK feature
`runtime.release-stream/1` now supplies an idempotent `releaseStream` method.
Pine deletes only that owner's journal transaction, then its retained state and
window; the SDK, supervisor and indicator adapter drop their corresponding
patch/conversion bases after acknowledgement. A failed delete retains the
registry slot for retry. An explicit cleanup may recover a stopped registered
worker to delete its durable orphan; a read still never launches one. Existing
operations remain available without this optional feature, while new chart
owners require it before admission. This source candidate does not establish
that an older installed bridge/SDK wheel has the feature. No wheel was released
or Native bundle rebuilt in this step; final package identity/install evidence
is required before product qualification.

The existing architecture guard found the earlier owner imported supervisor
types directly. The immutable host-local projection references now live in a
neutral core contract, and the original guard passes without an exemption.

Validation on this source uses the retained copies-venv launcher, current
repository SDK/bridge sources and core **0.3.3+cs.1**:

- Backend combination: **145 passed / 5 existing warnings / zero skips**.
  Includes owners/registry, actual stream release, runtime service, supervisor,
  patch bases, original standalone range batch, script patch shapes, transport,
  main lifecycle, architecture, exchange seconds and shutdown failures.
- Complete SDK suite: **185 passed / zero skips**. The first collection attempt
  lacked `jsonschema`; no tests ran in that attempt. Dependencies were installed
  only into a dedicated temporary validation target, without changing the
  retained runtime. `lifecycle-test-dependencies.json` pins the actual versions.
- Complete Pine bridge suite: **240 passed / 1 existing skip**. The pinned core
  lacks compact external appends (`test_prefix_reply.py:122`); this is not a
  stream-release qualification and is not counted as passed.

`observe_lifecycle.py` separately exercises real registry/service/SDK/sidecar
calls. Cumulative chart A gives **500 → 501**, independent chart B gives **50**,
and ten reads after every admission do not add IPC requests. Before retirement
the journal holds two sessions/50,684 budget bytes; retiring A leaves exactly
B/5,472 bytes. Repeating release and six further create/retire rounds leave B
unchanged. Service shutdown reaches zero registry entries, sessions, budget
bytes and operations. The one owned worker exits normally (code 0) and its PID
is independently absent. These are component-process facts, not desktop quit
or Native acceptance.

The SQLite trigger regression deliberately aborts journal deletion. The failed
release preserves the entire journal/budget and host reference; dropping the
trigger and repeating that exact release deletes the session atomically. Other
tests cover cancelled creators/borrowers, pinned/idle/closing capacity, failed
cleanup retry, feature negotiation, bounded parameters and unsupported old
runtimes. All 39 pre-existing dirty QA files retain their exact hashes.

Evidence: `lifecycle-source-manifest.json`, `lifecycle-observation.json.gz`, the
three `lifecycle-*-regression.log.gz` files and the preserved architecture-failure
log. The manifest lists the exact test files; rerun using the same launcher with
`PYTHONPATH=backend` for backend, repository SDK source for SDK, and repository
SDK/bridge sources for Pine. Temporary DATA_DIR/basetemp paths must be isolated.
The observation command is:

```sh
output/issue-152-output-range-20261102/main226-native-test-env/bin/python -B \
  docs/qa/indicator-calculation-owner-20261105/observe_lifecycle.py \
  --source 1f9ada60b62d971e706d76dc9be87349da630771 --output /tmp/new-owned-lifecycle-observation
```

Next: versioned HTTP/WS domain and cursor acceptance, fixed-origin hydration
and correction, renderer generation/sequence ordering, final source-matched
package qualification and original Native save/full-quit/restart assertions.
Standalone/as-of history, existing historyLimit identities and original failed
Native evidence remain intact. Windows and broader #152 remain open. CI runs in
the background and gates only a proposed main merge.
