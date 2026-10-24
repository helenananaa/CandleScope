import type { IndicatorDrawing } from "./indicatorTypes.js";

/** Older range responses cannot replace the state at a newer observation. */
export function reconcilePineScenes(previous: readonly IndicatorDrawing[] = [], incoming: readonly IndicatorDrawing[] = []): IndicatorDrawing[] {
  const newest = new Map(previous.map((scene) => [`${scene.indicatorId}:${scene.id}`, scene]));
  const result = incoming.map((scene) => {
    const old = newest.get(`${scene.indicatorId}:${scene.id}`);
    return old && old.asOf > scene.asOf ? old : scene;
  });
  // An incoming empty scene is a deletion; an absent scene removes a lane.
  return result;
}
