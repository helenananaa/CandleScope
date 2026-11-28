import type { SubscriptionRefreshState } from "../../services/api.js";

/** Hours between automatic subscription checks; 0 turns them off. Matches the backend. */
export const REFRESH_INTERVALS = [0, 6, 12, 24] as const;

export type RefreshLine =
  | { key: "settings.proxy.refreshPending"; values: Record<string, never> }
  | { key: "settings.proxy.refreshChecked" | "settings.proxy.refreshFailed"; values: { time: string } }
  | { key: "settings.proxy.refreshUpdated"; values: { count: number; time: string } }
  | { key: "settings.proxy.refreshMissing"; values: { count: number } };

const time = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : 0;

/** What the last automatic check of one subscription found, newest first. */
export function refreshLines(state: SubscriptionRefreshState | undefined, date: (ms: number) => string): RefreshLine[] {
  const attempt = time(state?.last_attempt_ms);
  if (!state || attempt === null) return [{ key: "settings.proxy.refreshPending", values: {} }];
  const lines: RefreshLine[] = [];
  const success = time(state.last_success_ms);
  if (typeof state.error === "string" && state.error) lines.push({ key: "settings.proxy.refreshFailed", values: { time: date(attempt) } });
  else if (success !== null) lines.push({ key: "settings.proxy.refreshChecked", values: { time: date(success) } });
  const changed = time(state.last_change_ms);
  if (changed !== null && count(state.updated)) {
    lines.push({ key: "settings.proxy.refreshUpdated", values: { count: count(state.updated), time: date(changed) } });
  }
  if (!state.error && count(state.missing)) lines.push({ key: "settings.proxy.refreshMissing", values: { count: count(state.missing) } });
  return lines;
}
