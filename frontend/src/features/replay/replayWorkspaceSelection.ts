import { intervalsSemanticallyEquivalent } from "../../utils/intervals.js";
import { canProjectReplayDisplayInterval } from "./replayIntervalPolicy.js";

interface ViewerSelection {
  selected_track_id: string | null;
  display_interval: string;
}

/** Synchronize only the active chart with the authoritative stepping target. */
export function replayWorkspaceSelectionCommand(
  viewer: ViewerSelection | null,
  trackId: string | undefined,
  interval: string,
): { type: "select_track" | "set_display_interval"; value: string; key: string } | null {
  if (!viewer || !trackId) return null;
  const key = JSON.stringify([trackId, interval]);
  if (viewer.selected_track_id !== trackId) return { type: "select_track", value: trackId, key };
  if (!intervalsSemanticallyEquivalent(viewer.display_interval, interval)) {
    return { type: "set_display_interval", value: interval, key };
  }
  return null;
}

export function replayDisplayIntervalOptions(base: string, current: string): string[] {
  return [...new Set([base, current, "1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M", "12M"])]
    .filter((interval) => canProjectReplayDisplayInterval(base, interval));
}
