import { getDateTimeLocale, t } from "../../../i18n/index.js";

/**
 * What a chart cell says about the live run that keeps its result current (ADR-BACKTEST-015 P4c).
 *
 * - `connecting`: the cell holds a FOLLOW run that has not caught up yet; the fixed result is shown.
 * - `live`: the shown result has applied every closed bar so far.
 * - `recalculating`: bars it had applied were revised; it starts over and the last result stays shown.
 * - `waiting`: the source has not supplied the next closed bar in time.
 * - `stopped`: the live run ended (it failed, or no chart holds it); the last result stays shown.
 * - `unavailable`: the backend refused to follow this result (too long, or settings it cannot continue).
 */
export type ChartFollowState = "connecting" | "live" | "recalculating" | "waiting" | "stopped" | "unavailable";

export interface ChartFollowStatus {
  state: ChartFollowState;
  /** Open time of the newest bar the shown result applied, when known. */
  latestBarMs: number | null;
}

/** The status frames of the shown live run: its own phase and the close time of its newest applied bar. */
export interface ChartFollowLive {
  sourceState: string;
  throughMs: number | null;
}

export function chartFollowStatus({ following, refused, shown, live, intervalMs }: {
  /** The cell asked to follow the shown fixed result. */
  following: boolean;
  /** The backend refused to follow it. */
  refused: boolean;
  /** The chart shows the FOLLOW run's result (it caught up once). */
  shown: boolean;
  live: ChartFollowLive | null;
  intervalMs: number | null;
}): ChartFollowStatus | null {
  if (!following) return null;
  if (refused) return { state: "unavailable", latestBarMs: null };
  if (!shown || live === null) return { state: "connecting", latestBarMs: null };
  const latestBarMs = live.throughMs !== null && live.throughMs > 0 && intervalMs !== null
    ? live.throughMs + 1 - intervalMs : null;
  switch (live.sourceState) {
    case "LIVE": return { state: latestBarMs === null ? "connecting" : "live", latestBarMs };
    case "CATCHING_UP": return { state: "recalculating", latestBarMs };
    case "WAITING_DATA": return { state: "waiting", latestBarMs };
    default: return { state: "stopped", latestBarMs };
  }
}

function barTime(ms: number | null): string {
  if (ms === null) return "—";
  return new Date(ms).toLocaleString(getDateTimeLocale(), {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  });
}

export function chartFollowStatusLabel(status: ChartFollowStatus): string {
  const time = barTime(status.latestBarMs);
  switch (status.state) {
    case "connecting": return t("strategyFollow.connecting");
    case "live": return t("strategyFollow.live", { time });
    case "recalculating": return t("strategyFollow.recalculating");
    case "waiting": return t("strategyFollow.waiting", { time });
    case "stopped": return t("strategyFollow.stopped", { time });
    case "unavailable": return t("strategyFollow.unavailable");
  }
}

/** The dock's status-dot tone for each state (`strategy-run-status[data-status]`). */
export function chartFollowStatusTone(state: ChartFollowState): string {
  switch (state) {
    case "connecting": case "recalculating": return "running";
    case "live": return "live";
    case "waiting": case "stopped": return "stale";
    case "unavailable": return "idle";
  }
}
