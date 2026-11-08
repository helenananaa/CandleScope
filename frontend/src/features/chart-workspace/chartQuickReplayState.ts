import { parseIntervalSeconds } from "../../utils/intervals.js";

export interface ChartQuickReplayState {
  /** A live chart can keep its own last selected trade for a mode-link resume. */
  active?: boolean;
  accountId: string;
  tradeId: string;
  readonlyVersion?: string;
  interval: string;
  step?: string;
  cursorSec?: number;
}

export type QuickReplayChange = "local" | "mode" | "cursor";

export type UpdateChartQuickReplay = (current: ChartQuickReplayState | undefined) => ChartQuickReplayState | undefined;

function validIdentifier(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= 256;
}

export function normalizeChartQuickReplay(value: unknown): ChartQuickReplayState | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { active, accountId, tradeId, readonlyVersion, interval, step, cursorSec } = value as Record<string, unknown>;
  if (!validIdentifier(accountId) || !validIdentifier(tradeId)
    || (readonlyVersion !== undefined && !validIdentifier(readonlyVersion))
    || typeof interval !== "string" || parseIntervalSeconds(interval) === null) return undefined;
  return {
    ...(active === false ? { active: false } : {}), accountId, tradeId, ...(readonlyVersion === undefined ? {} : { readonlyVersion }), interval,
    ...(typeof step === "string" && parseIntervalSeconds(step) !== null ? { step } : {}),
    ...(typeof cursorSec === "number" && Number.isSafeInteger(cursorSec) && cursorSec >= 0 && cursorSec <= 253402300799 ? { cursorSec } : {}),
  };
}

export function chartQuickReplayKey(state: ChartQuickReplayState): string {
  return JSON.stringify([state.accountId, state.tradeId, state.readonlyVersion ?? null, state.interval]);
}
