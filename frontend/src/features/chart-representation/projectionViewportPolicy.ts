const STRUCTURAL_VIEWPORT_DELTAS = new Set([
  "prepend",
  "mid-merge",
  "trim-left",
  "trim-right",
]);

function hasTrim(delta: ProjectionSourceDelta | null | undefined): boolean {
  return (Number(delta?.trimmedLeft) || 0) > 0
    || (Number(delta?.trimmedRight) || 0) > 0;
}

export function shouldPreserveProjectionViewport(delta: ProjectionSourceDelta | null | undefined, {
  hasDisplay = false,
  userInteracted = false,
}: {
  hasDisplay?: boolean;
  userInteracted?: boolean;
} = {}): boolean {
  if (!hasDisplay) return false;

  const type = delta?.type;
  if (type === "replace") return userInteracted;
  if (typeof type === "string" && STRUCTURAL_VIEWPORT_DELTAS.has(type)) return true;

  return (type === "tick" || type === "append") && hasTrim(delta);
}

/**
 * A live chart whose latest bar is on screen keeps the newest bar on screen
 * when a commit adds rows after it. The chart engine does this for a single
 * appended bar but not for a window commit, and a reopened chart receives the
 * bars it missed as window commits after it first paints its stored rows.
 * A jumped-to window (right edge not current), a view the user moved, and a
 * session whose first view is not placed yet keep their range.
 */
export function shouldFollowLiveTail({
  latestBarVisible = false,
  nextLastTime,
  previousLastTime,
  rightEdgeCurrent = false,
  sessionViewportPlaced = false,
  userInteracted = false,
}: {
  latestBarVisible?: boolean;
  nextLastTime?: number | null;
  previousLastTime?: number | null;
  rightEdgeCurrent?: boolean;
  sessionViewportPlaced?: boolean;
  userInteracted?: boolean;
} = {}): boolean {
  return latestBarVisible
    && rightEdgeCurrent
    && sessionViewportPlaced
    && !userInteracted
    && typeof previousLastTime === "number" && Number.isFinite(previousLastTime)
    && typeof nextLastTime === "number" && Number.isFinite(nextLastTime)
    && nextLastTime > previousLastTime;
}
import type { ProjectionSourceDelta } from "./chartRepresentationTypes.js";
