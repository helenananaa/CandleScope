import { request } from "../../services/api.js";
import { API_BASE } from "../../services/apiConfig.js";
import type {
  AccountSummary,
  AccountsResponse,
  Excursion,
  JournalEntry,
  PracticeOrder,
  Trade,
  TradeDetail,
  TradingAccount,
} from "./tradingTypes.js";

const BASE = `${API_BASE}/trading`;

function path(segment: string): string {
  return `${BASE}${segment}`;
}

function id(value: string): string {
  return encodeURIComponent(value);
}

export const tradingApi = {
  listAccounts: () => request(path("/accounts")) as Promise<AccountsResponse>,
  createAccount: (body: Record<string, unknown>) =>
    request(path("/accounts"), { method: "POST", body }) as Promise<TradingAccount>,
  updateAccount: (accountId: string, body: Record<string, unknown>) =>
    request(path(`/accounts/${id(accountId)}`), { method: "PATCH", body }) as Promise<TradingAccount>,
  resetAccount: (accountId: string) =>
    request(path(`/accounts/${id(accountId)}/reset`), { method: "POST" }) as Promise<AccountSummary>,
  summary: (accountId: string, signal?: AbortSignal) =>
    request(path(`/accounts/${id(accountId)}/summary`), signal ? { signal } : {}) as Promise<AccountSummary>,
  trades: (accountId: string, signal?: AbortSignal) =>
    request(path(`/accounts/${id(accountId)}/trades`), signal ? { signal } : {}) as Promise<{ trades: Trade[] }>,
  trade: (accountId: string, tradeId: string) =>
    request(path(`/accounts/${id(accountId)}/trades/${id(tradeId)}`)) as Promise<TradeDetail>,
  excursion: (accountId: string, tradeId: string) =>
    request(path(`/accounts/${id(accountId)}/trades/${id(tradeId)}/excursion`)) as Promise<Excursion>,
  placeOrder: (accountId: string, body: Record<string, unknown>) =>
    request(path(`/accounts/${id(accountId)}/orders`), { method: "POST", body }) as Promise<{
      order: PracticeOrder;
      priceSource: string;
      referencePrice: string;
    }>,
  cancelOrder: (accountId: string, orderId: string) =>
    request(path(`/accounts/${id(accountId)}/orders/${id(orderId)}/cancel`), { method: "POST" }) as Promise<{
      order: PracticeOrder;
    }>,
  addFill: (accountId: string, body: Record<string, unknown>) =>
    request(path(`/accounts/${id(accountId)}/fills`), { method: "POST", body }),
  deleteFill: (accountId: string, fillId: string) =>
    request(path(`/accounts/${id(accountId)}/fills/${id(fillId)}`), { method: "DELETE" }),
  journal: (accountId: string, signal?: AbortSignal) =>
    request(path(`/accounts/${id(accountId)}/journal`), signal ? { signal } : {}) as Promise<{
      entries: JournalEntry[];
    }>,
  createEntry: (accountId: string, body: Record<string, unknown>) =>
    request(path(`/accounts/${id(accountId)}/journal`), { method: "POST", body }) as Promise<JournalEntry>,
  entry: (entryId: string) => request(path(`/journal/${id(entryId)}`)) as Promise<JournalEntry>,
  saveEntry: (entryId: string, body: Record<string, unknown>) =>
    request(path(`/journal/${id(entryId)}`), { method: "PATCH", body }) as Promise<JournalEntry>,
  linkEntry: (entryId: string, tradeId: string | null) =>
    request(path(`/journal/${id(entryId)}/link`), { method: "PUT", body: { tradeId } }) as Promise<JournalEntry>,
  deleteEntry: (entryId: string) => request(path(`/journal/${id(entryId)}`), { method: "DELETE" }),
  addSnapshot: (entryId: string, body: Record<string, unknown>) =>
    request(path(`/journal/${id(entryId)}/snapshots`), { method: "POST", body }) as Promise<JournalEntry>,
  snapshotImageUrl: (snapshotId: string) => path(`/snapshots/${id(snapshotId)}/image`),
};
