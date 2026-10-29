import type { JournalApi } from "../trading-accounts/journalApi.js";
import type { JournalEntry, Trade, TradeDetail } from "../trading-accounts/tradingTypes.js";
import { accountErrorHelp } from "./accountErrors.js";
import { t } from "../../i18n/index.js";
import { AccountApiError, accountRequest, record } from "./accountApi.js";
import { reconciliationReasons, type ReconciliationReason } from "./reconciliationApi.js";

export interface ReviewListing {
  trades: Trade[];
  excluded: { positionId: string; instrument: string; reason: ReconciliationReason }[];
  current: boolean;
  truncated: boolean;
  unmatchedFills?: number;
  readError?: string;
  coverage: { kind: string; start_ms: number; end_ms: number }[];
  gaps: { kind: string; start_ms: number; end_ms: number; reason: string }[];
  stats: { currency: "USDT"; count: number; wins: number; realizedPnl: string; fees: string;
    funding: string; netPnl: string; cachedCount: number; rCount: number; averageR: null };
}
const amount = (v: unknown) => typeof v === "string" && v.length <= 200 && /^-?\d+(\.\d+)?$/.test(v);
const str = (v: unknown) => typeof v === "string" && v.length <= 128;
const time = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const fields = (r: Record<string, unknown>, keys: string[], check: (v: unknown) => boolean) => keys.every((key) => check(r[key]));
function invalid(): never { throw new AccountApiError("ACCOUNT_RESPONSE_INVALID"); }

export function parseReviewTrade(value: unknown): Trade {
  if (!record(value) || !fields(value, ["id", "accountId", "symbol"], str)
    || value.exchange !== "okx" || value.marketType !== "futures" || value.status !== "closed"
    || !["long", "short"].includes(String(value.direction)) || !time(value.openedAtMs) || !time(value.closedAtMs)
    || !fields(value, ["openQty", "maxQty", "entryQty", "exitQty", "avgEntryPrice", "avgExitPrice", "realizedPnl", "fees", "netPnl"], amount)
    || !Array.isArray(value.legs) || value.legs.length === 0 || !value.legs.every((leg: unknown) => record(leg)
      && str(leg.fillId) && ["buy", "sell"].includes(String(leg.side)) && ["open", "add", "reduce", "close"].includes(String(leg.role))
      && fields(leg, ["qty", "price", "fee"], amount) && time(leg.tsMs))
    || !record(value.readonlySource)) return invalid();
  const source = value.readonlySource;
  if (source.venue !== "okx" || source.product !== "SWAP" || source.currency !== "USDT"
    || !fields(source, ["accountUid", "instrument", "positionId", "marginMode"], str)
    || typeof source.version !== "string" || !/^[0-9a-f]{64}$/.test(source.version) || !time(source.verifiedAtMs)
    || !amount(source.funding) || (source.current !== undefined && typeof source.current !== "boolean")
    || !Array.isArray(source.fills) || source.fills.length !== value.legs.length
    || !source.fills.every((fill: unknown) => record(fill) && fields(fill, ["fillId", "tradeId"], str)
      && fields(fill, ["contracts", "contractValue", "realizedPnl"], amount) && time(fill.tsMs))
    || !Array.isArray(source.fundingEvents) || !source.fundingEvents.every((event: unknown) => record(event)
      && str(event.billId) && amount(event.amount) && time(event.eventTimeMs))) return invalid();
  return value as unknown as Trade;
}

export function parseReviewListing(value: unknown): ReviewListing {
  if (!record(value) || !Array.isArray(value.trades) || !Array.isArray(value.excluded)
    || typeof value.current !== "boolean" || typeof value.truncated !== "boolean" || !record(value.stats)
    || !Array.isArray(value.coverage) || !Array.isArray(value.gaps)
    || ![value.coverage, value.gaps].every((ranges: unknown[]) => ranges.every((range: unknown) => record(range) && str(range.kind)
      && time(range.start_ms) && time(range.end_ms)))
    || !value.excluded.every((row: unknown) => record(row) && str(row.positionId) && str(row.instrument)
      && reconciliationReasons.includes(row.reason as ReconciliationReason))
    || value.stats.currency !== "USDT" || !fields(value.stats, ["count", "wins", "cachedCount", "rCount"], time)
    || !fields(value.stats, ["realizedPnl", "fees", "funding", "netPnl"], amount) || value.stats.averageR !== null) return invalid();
  value.trades.forEach(parseReviewTrade);
  return value as unknown as ReviewListing;
}
export async function getReviewTrades(signal?: AbortSignal): Promise<ReviewListing> {
  return parseReviewListing(await accountRequest("/review/trades", "GET", undefined, signal));
}

function entry(value: unknown): JournalEntry {
  if (!record(value) || !str(value.id) || !str(value.accountId) || !record(value.fields)
    || !Array.isArray(value.snapshots) || !Array.isArray(value.tags) || !time(value.revisionCount)) return invalid();
  return value as unknown as JournalEntry;
}

async function reviewRequest(path: string, method = "GET", payload?: unknown): Promise<unknown> {
  try { return await accountRequest(path, method, payload); }
  catch (cause) {
    if (cause instanceof AccountApiError) throw new Error(cause.code === "TRADING_JOURNAL_CONFLICT"
      ? t("trading.journal.draftChanged") : accountErrorHelp(cause.code));
    throw cause;
  }
}

/** Bound to an immutable financial version; journal revisions remain append-only. */
export function reviewJournalApi(trade: Trade): JournalApi {
  const version = trade.readonlySource?.version;
  if (!version) return invalid();
  const id = encodeURIComponent;
  const journal = (entryId: string) => `/review/journal/${id(entryId)}`;
  return {
    async trade(accountId, tradeId) {
      const value = await reviewRequest(`/review/accounts/${id(accountId)}/trades/${id(tradeId)}?version=${id(version)}`);
      parseReviewTrade(value);
      if (!record(value) || !Array.isArray(value.entries) || !Array.isArray(value.linkSuggestions)) return invalid();
      value.entries.forEach(entry);
      return value as unknown as TradeDetail;
    },
    async excursion() { return { available: false } as Awaited<ReturnType<JournalApi["excursion"]>>; },
    async entry(entryId) { return entry(await reviewRequest(journal(entryId))); },
    async createEntry(accountId, body) { return entry(await reviewRequest(`/review/accounts/${id(accountId)}/journal`, "POST", body)); },
    async saveEntry(entryId, body) { return entry(await reviewRequest(journal(entryId), "POST", body)); },
    async linkEntry(entryId, tradeId) { return entry(await reviewRequest(`${journal(entryId)}/link`, "POST", { tradeId })); },
    async addSnapshot(entryId, body) { return entry(await reviewRequest(`${journal(entryId)}/snapshots`, "POST", body)); },
    async snapshotImageUrl(snapshotId) {
      const value = await reviewRequest(`/review/snapshots/${id(snapshotId)}/image`);
      if (!record(value) || typeof value.image !== "string" || !value.image.startsWith("data:image/png;base64,")) return invalid();
      return value.image;
    },
  };
}
