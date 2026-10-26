import type { JournalApi } from "./journalApi.js";
/** Wire contracts for `/api/v1/trading`. Decimals stay strings end to end. */

export type TradingAccountKind = "practice" | "manual";
export type PlannedAccountKind = "exchange_readonly" | "exchange_trading";
export type TradeStatus = "open" | "closed";
export type JournalStage = "pre" | "open" | "post";

export interface PracticeSettings {
  initialBalance: string;
  takerFeeRate: string;
  makerFeeRate: string;
  slippageBps: string;
  leverage: string;
}

export interface TradingAccount {
  id: string;
  kind: TradingAccountKind;
  name: string;
  quoteCurrency: string;
  settings: Partial<PracticeSettings>;
  createdAtMs: number;
  archived: boolean;
  capabilities: { placeOrders: boolean; manualFills: boolean; sync: boolean };
}

export interface AccountsResponse {
  accounts: TradingAccount[];
  kinds: TradingAccountKind[];
  plannedKinds: PlannedAccountKind[];
}

export interface TradeLeg {
  fillId: string;
  side: "buy" | "sell";
  role: "open" | "add" | "reduce" | "close";
  qty: string;
  price: string;
  fee: string;
  tsMs: number;
  liquidity: string;
  orderId: string | null;
}

export interface TradePlan {
  lockedAtMs: number;
  entryPrice: string | null;
  stopPrice: string | null;
  targetPrice: string | null;
  riskUsdt: string | null;
}

export interface TradeMetrics {
  riskUsdt: string | null;
  netR: string | null;
  plannedRewardRisk: string | null;
  entrySlippage: string | null;
}

export interface ReadonlyTradeSource {
  venue: "okx";
  accountUid: string;
  product: "SWAP";
  instrument: string;
  positionId: string;
  marginMode: string;
  currency: "USDT";
  version: string;
  verifiedAtMs: number;
  current?: boolean;
  funding: string;
  fills: { fillId: string; tradeId: string; orderId: string | null; contracts: string; contractValue: string; realizedPnl: string; tsMs: number }[];
  fundingEvents: { billId: string; amount: string; eventTimeMs: number }[];
}

export interface Trade {
  readonlySource?: ReadonlyTradeSource;
  id: string;
  accountId: string;
  exchange: string;
  marketType: string;
  symbol: string;
  direction: "long" | "short";
  status: TradeStatus;
  openedAtMs: number;
  closedAtMs: number | null;
  openQty: string;
  maxQty: string;
  entryQty: string;
  exitQty: string;
  avgEntryPrice: string | null;
  avgExitPrice: string | null;
  realizedPnl: string;
  fees: string;
  netPnl: string;
  markPrice: string | null;
  unrealizedPnl: string | null;
  legs: TradeLeg[];
  noteId?: string | null;
  entryCount?: number;
  needsReview?: boolean;
  plan?: TradePlan | null;
  metrics?: TradeMetrics;
  markAtMs?: number | null;
  markSource?: string;
}

export interface FieldTiming {
  firstWrittenMs: number;
  lastChangedMs: number;
  phase: JournalStage;
}

export interface JournalSnapshot {
  id: string;
  createdAtMs: number;
  hasImage: boolean;
  state: Record<string, unknown>;
}

export interface JournalEntry {
  id: string;
  accountId: string;
  exchange: string;
  marketType: string;
  symbol: string;
  kind: "note" | "quick";
  tradeId: string | null;
  createdAtMs: number;
  updatedAtMs: number;
  marketTimeMs: number | null;
  templateId: string | null;
  templateVersion: number | null;
  tags: string[];
  fields: Record<string, string>;
  body: string;
  revisionCount: number;
  stage: JournalStage;
  reviewNote: boolean;
  fieldTiming: Record<string, FieldTiming>;
  plan: TradePlan | null;
  snapshots: JournalSnapshot[];
  /** Included by trade detail; absent metadata must never mean latest = historical. */
  revisions?: JournalRevision[];
}

export interface JournalRevision {
  revision: number;
  savedAtMs: number;
  fields: Record<string, string>;
  body: string;
  historyComplete: boolean;
}

/** An unlinked plan near a trade, with its latest risk fields to tell plans apart. */
export interface LinkSuggestion {
  id: string;
  kind: string;
  createdAtMs: number;
  symbol: string;
  tradeId: string | null;
  entryPrice: string | null;
  stopPrice: string | null;
  targetPrice: string | null;
  riskUsdt: string | null;
  /** Implied by stop/target around entry; null when unclear. */
  direction: "long" | "short" | null;
}

export interface TradeDetail extends Trade {
  entries: JournalEntry[];
  linkSuggestions: LinkSuggestion[];
}

export interface PracticeOrder {
  id: string;
  accountId: string;
  exchange: string;
  marketType: string;
  symbol: string;
  side: "buy" | "sell";
  type: "market" | "limit" | "stop";
  qty: string;
  limitPrice: string | null;
  stopPrice: string | null;
  reduceOnly: boolean;
  tag: string | null;
  bracketStop: string | null;
  bracketTarget: string | null;
  status: "working" | "filled" | "cancelled" | "rejected";
  createdAtMs: number;
  fillPrice: string | null;
  filledAtMs: number | null;
  reason: string | null;
}

export interface PracticeFeed {
  exchange: string;
  marketType: string;
  symbol: string;
  status: string;
  detail: string;
  observedMs: number | null;
  lastPrice: string | null;
}

export interface AccountSummary {
  account: TradingAccount;
  balance: string;
  equity: string;
  unrealizedPnl: string;
  usedMargin: string;
  available: string;
  positions: Trade[];
  workingOrders: PracticeOrder[];
  feeds: PracticeFeed[];
  closedTrades: number;
}

export interface Excursion {
  available: boolean;
  interval: string;
  complete: boolean;
  bars?: number;
  mfePrice?: string;
  maePrice?: string;
  mfePct?: string;
  maePct?: string;
  mfeR?: string | null;
  maeR?: string | null;
}

/** The chart the rail is attached to: defaults for orders, notes and replay. */
export interface TradingChartContext {
  exchange: string;
  marketType: string;
  symbol: string;
  interval: string;
  lastPrice: number | null;
  /** PNG data URL of the current chart, or null when capture is unavailable. */
  captureImage?: () => Promise<string | null>;
  /** Visible range and indicator list for the snapshot's structured state. */
  describeChart?: () => Record<string, unknown>;
}

export interface QuickReplayRequest {
  api?: Pick<JournalApi, "trade" | "createEntry">;
  accountId: string;
  trade: Trade;
  interval: string;
}

/** R figures cover only trades whose risk was locked at the first fill. */
export interface TradingRStats {
  count: number;
  missing: number;
  /** count / trades, 0–1; null without trades. */
  coverage: string | null;
  winRate: string | null;
  /** Mean net R. */
  expectancyR: string | null;
  avgWinR: string | null;
  avgLossR: string | null;
  totalR: string | null;
  lowSample: boolean;
}

export interface TradingStatsCore {
  tradeCount: number;
  wins: number;
  losses: number;
  breakeven: number;
  winRate: string | null;
  avgWin: string | null;
  avgLoss: string | null;
  avgPnl: string | null;
  grossProfit: string;
  grossLoss: string;
  /** Null when there is no loss (∞ if there was profit) or no trade. */
  profitFactor: string | null;
  realizedPnl: string;
  fees: string;
  netPnl: string;
  lowSample: boolean;
  r: TradingRStats;
}

export type PlanTiming = "before" | "mixed" | "after" | "none";

export interface TradingStatsGroup<K extends string | null = string | null> extends TradingStatsCore {
  key: K;
}

export interface TradingRBucket {
  /** Null for the open-ended lowest bucket. */
  fromR: string | null;
  /** Null for the open-ended highest bucket. */
  toR: string | null;
  count: number;
}

export interface TradingStats extends TradingStatsCore {
  accountId: string;
  accountKind: TradingAccountKind;
  quoteCurrency: string;
  filters: { fromMs: number | null; toMs: number | null; tags: string[] };
  openTrades: number;
  lowSampleThreshold: number;
  maxDrawdown: { amount: string; peakAtMs: number | null; troughAtMs: number | null };
  rDistribution: TradingRBucket[];
  breakdowns: {
    planTiming: TradingStatsGroup<PlanTiming>[];
    direction: TradingStatsGroup<"long" | "short">[];
    /** A trade with several tags is in each of their groups; null = untagged. */
    tag: TradingStatsGroup<string | null>[];
  };
}

export interface TradingStatsQuery {
  fromMs?: number | null;
  toMs?: number | null;
  tags?: readonly string[];
}
