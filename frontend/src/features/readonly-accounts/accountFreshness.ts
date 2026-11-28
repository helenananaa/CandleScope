import type { AccountStatus } from "./accountApi.js";

/** A healthy sync re-reads positions, open orders and balances about every 30 s
 * (one reconcile round plus its requests). Past this age a value is out of date
 * even while the sync says it is running. */
export const ACCOUNT_STALE_AFTER_MS = 2 * 60_000;

export const ACCOUNT_SNAPSHOT_KINDS = ["positions", "open_orders", "balances"] as const;
export type AccountSnapshotKind = typeof ACCOUNT_SNAPSHOT_KINDS[number];

/**
 * Why displayed account values may no longer match the exchange.
 * - `localService`: the panel lost its connection to the local service; it shows
 *   the last state it received.
 * - `service`: the account service itself is unavailable.
 * - `paused`: sync is paused or the credentials were removed.
 * - `error`: sync failed and has not refreshed the values within the limit.
 * - `slow`: sync reports no failure but has not refreshed within the limit.
 */
export type AccountStaleReason = "localService" | "service" | "paused" | "error" | "slow";

export interface SnapshotFreshness {
  receivedMs: number | null;
  ageMs: number | null;
  stale: boolean;
}

export interface AccountFreshness {
  /** Any displayed snapshot is out of date. */
  stale: boolean;
  reason: AccountStaleReason | null;
  /** The oldest displayed snapshot: the worst case for the panel's values. */
  oldestMs: number | null;
  ageMs: number | null;
  snapshots: Record<AccountSnapshotKind, SnapshotFreshness>;
}

function stoppedReason(status: AccountStatus, localError: string | null): AccountStaleReason | null {
  if (localError) return "localService";
  if (status.serviceError) return "service";
  if (status.account && (!status.account.enabled || status.account.status === "disconnected")) return "paused";
  return null;
}

/**
 * Freshness of the values the account panel shows. Values that can no longer
 * update (paused, service or local connection lost) are out of date at once;
 * values a running sync should refresh become out of date after
 * {@link ACCOUNT_STALE_AFTER_MS}. Returns null when no account is connected.
 */
export function accountFreshness(status: AccountStatus | null, localError: string | null, nowMs: number,
  staleAfterMs = ACCOUNT_STALE_AFTER_MS): AccountFreshness | null {
  if (!status?.account) return null;
  const stopped = stoppedReason(status, localError);
  const snapshots = {} as Record<AccountSnapshotKind, SnapshotFreshness>;
  let oldestMs: number | null = null;
  for (const kind of ACCOUNT_SNAPSHOT_KINDS) {
    const receivedMs = status.snapshots[kind]?.receivedMs ?? null;
    const ageMs = receivedMs === null ? null : Math.max(0, nowMs - receivedMs);
    const late = ageMs !== null && ageMs > staleAfterMs;
    snapshots[kind] = { receivedMs, ageMs, stale: receivedMs !== null && (stopped !== null || late) };
    if (receivedMs !== null && (oldestMs === null || receivedMs < oldestMs)) oldestMs = receivedMs;
  }
  const stale = ACCOUNT_SNAPSHOT_KINDS.some((kind) => snapshots[kind].stale);
  // Not stopped and stale means a value is overdue.
  const reason = !stale ? null : stopped ?? (status.account.status === "error" ? "error" : "slow");
  return { stale, reason, oldestMs, ageMs: oldestMs === null ? null : Math.max(0, nowMs - oldestMs), snapshots };
}

const UNITS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400_000], ["hour", 3_600_000], ["minute", 60_000], ["second", 1000],
];

/** "2 minutes ago", in the given locale. Seconds round down to tens so a
 * ticking panel does not rewrite the text every second. Ages are elapsed time,
 * never calendar words such as "yesterday". */
export function formatAccountAge(ageMs: number, locale: string): string {
  const age = Math.max(0, ageMs);
  if (age < 10_000) return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(0, "second");
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "always" });
  for (const [unit, size] of UNITS) {
    if (unit === "second") return format.format(-Math.floor(age / 10_000) * 10, "second");
    if (age >= size) return format.format(-Math.floor(age / size), unit);
  }
  return format.format(0, "second");
}
