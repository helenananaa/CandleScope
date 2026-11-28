import { record, type AccountStatus } from "./accountApi.js";

/** Funding account data (#575 PL-6), kept apart from the trading account's. */
export interface FundingBalance { currency: string; total: string; available: string; frozen: string }
export type FundingState = "pending" | "completed" | "failed" | "canceled" | "held" | "unknown";
export type TransferAccount = "funding" | "trading" | "other";

export type FundingRow =
  | { kind: "deposit"; id: string; currency: string; amount: string; chain: string; state: FundingState; eventTimeMs: number }
  | { kind: "withdrawal"; id: string; currency: string; amount: string; chain: string; state: FundingState;
      fee: string | null; feeCurrency: string; eventTimeMs: number }
  /** direction is the trading account's side: "in" when the trading account received the amount. */
  | { kind: "transfer"; id: string; currency: string; amount: string; direction: "in" | "out";
      from: TransferAccount; to: TransferAccount; eventTimeMs: number };

export interface FundingHistory { rows: FundingRow[]; complete: boolean; fromMs: number | null; receivedMs: number | null }

const AMOUNT = /^(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{1,36})?$/;
const STATES: readonly FundingState[] = ["pending", "completed", "failed", "canceled", "held", "unknown"];
const ACCOUNTS: readonly TransferAccount[] = ["funding", "trading", "other"];

const text = (value: unknown, max = 128): string | null => typeof value === "string" && value.length <= max ? value : null;
const amount = (value: unknown): string | null => typeof value === "string" && AMOUNT.test(value) ? value : null;
const time = (value: unknown): number | null => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
const state = (value: unknown): FundingState => STATES.includes(value as FundingState) ? value as FundingState : "unknown";
const account = (value: unknown): TransferAccount => ACCOUNTS.includes(value as TransferAccount) ? value as TransferAccount : "other";

/** Why the last read of a funding snapshot failed, or null. */
export function fundingReadError(snapshots: AccountStatus["snapshots"], kind: "funding_balances" | "funding_history"): string | null {
  const data = snapshots[`${kind}_state`]?.data;
  return record(data) && typeof data.error === "string" ? data.error : null;
}

/** Funding balances from the last successful read, or null if never read. Malformed rows are dropped. */
export function fundingBalances(snapshots: AccountStatus["snapshots"]): { balances: FundingBalance[]; receivedMs: number } | null {
  const saved = snapshots.funding_balances;
  if (!saved || !record(saved.data) || !Array.isArray(saved.data.balances)) return null;
  const balances = saved.data.balances.flatMap((row: unknown) => {
    if (!record(row)) return [];
    const currency = text(row.currency), total = amount(row.total), available = amount(row.available), frozen = amount(row.frozen);
    return currency && total && available && frozen ? [{ currency, total, available, frozen }] : [];
  });
  return { balances, receivedMs: saved.receivedMs };
}

function rows(value: unknown, kind: FundingRow["kind"]): FundingRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((row: unknown): FundingRow[] => {
    if (!record(row)) return [];
    const id = text(row.id), currency = text(row.currency), size = amount(row.amount), at = time(row.eventTimeMs);
    if (!id || !currency || !size || at === null) return [];
    if (kind === "transfer") {
      if (row.direction !== "in" && row.direction !== "out") return [];
      return [{ kind, id, currency, amount: size, direction: row.direction, from: account(row.from), to: account(row.to), eventTimeMs: at }];
    }
    const chain = text(row.chain, 64) ?? "";
    if (kind === "deposit") return [{ kind, id, currency, amount: size, chain, state: state(row.state), eventTimeMs: at }];
    return [{ kind, id, currency, amount: size, chain, state: state(row.state), fee: amount(row.fee),
      feeCurrency: text(row.feeCurrency) ?? currency, eventTimeMs: at }];
  });
}

/** Deposits, withdrawals and transfers from GET /funding-history, newest first. */
export function fundingHistory(value: unknown): FundingHistory | null {
  if (!record(value) || !record(value.data)) return null;
  const data = value.data;
  const merged = [...rows(data.deposits, "deposit"), ...rows(data.withdrawals, "withdrawal"), ...rows(data.transfers, "transfer")]
    .sort((a, b) => b.eventTimeMs - a.eventTimeMs || a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id));
  return { rows: merged, complete: data.complete === true, fromMs: time(data.fromMs), receivedMs: time(value.receivedMs) };
}

/**
 * The amount as the row shows it: deposits "+", withdrawals "−". A transfer's
 * sign depends on which side you look from, so it shows the bare amount and its
 * from → to route says the way it went.
 */
export function shownAmount(row: FundingRow): string {
  if (row.kind === "transfer") return row.amount;
  return `${row.kind === "withdrawal" ? "−" : "+"}${row.amount}`;
}
