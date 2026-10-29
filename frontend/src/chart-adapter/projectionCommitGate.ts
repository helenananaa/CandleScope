/** A bounded viewport intent waits for a successful projection commit, not an
 * arbitrary frame after source admission. Hidden or budget-delayed work may
 * require several frames; a failed render must not acknowledge the source. */
export function createProjectionCommitGate<Owner extends object>() {
  let committed: { owner: Owner; version: number } | null = null;
  let pending: { owner: Owner; version: number; apply: () => void } | null = null;
  const flush = () => {
    if (!pending || committed?.owner !== pending.owner || committed.version < pending.version) return;
    const intent = pending;
    pending = null;
    intent.apply();
  };
  return {
    request(owner: Owner, version: number, apply: () => void) {
      pending = { owner, version, apply };
      flush();
    },
    didCommit(owner: Owner, version: number) {
      committed = { owner, version };
      flush();
    },
    cancel() { pending = null; },
    reset() { pending = null; committed = null; },
  };
}
