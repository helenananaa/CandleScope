/**
 * Replay training saves each chart's drawings into its run record, and that
 * record's backend schema has no drawing groups yet: style keys are
 * allow-listed per kind in backend/app/replay/training/review.py, so a
 * `groupId` fails the save (422 REVIEW_DRAWING_INVALID) and stops replay
 * drawing saves for the session. Until the backend accepts it, replay scopes
 * cannot hold groups. The prefixes are the replay scope bases: workspace cells
 * (plain and linked) under `replay:<run>`, and the training page's run and
 * review scopes.
 */
const REPLAY_TRAINING_SCOPE = /^(?:workspace:replay:|workspace-link:replay%3A|replay-run:|replay-review:)/;

export function drawingScopeAllowsGroups(scopeKey: string): boolean {
  return !REPLAY_TRAINING_SCOPE.test(scopeKey);
}
