/**
 * Drawing groups (PL-4). A group is the shared `groupId` style flag on its
 * members, stored in the canonical document like `hidden` and `locked`, so
 * grouping is an ordinary undoable style command with no parallel store.
 */
const GROUP_ID_PATTERN = /^grp_[A-Za-z0-9_-]{1,64}$/;

export function isDrawingGroupId(value: unknown): value is string {
  return typeof value === "string" && GROUP_ID_PATTERN.test(value);
}

let groupSequence = 0;

/** A new group id, unique within this window and across restarts. */
export function nextDrawingGroupId(now = Date.now()): string {
  groupSequence = (groupSequence + 1) % 1_000_000;
  const random = Math.random().toString(36).slice(2, 8);
  return `grp_${now.toString(36)}_${groupSequence.toString(36)}_${random}`;
}
