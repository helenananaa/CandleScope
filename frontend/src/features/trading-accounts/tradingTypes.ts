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

export interface Trade {
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
}

export interface TradeDetail extends Trade {
  entries: JournalEntry[];
  linkSuggestions: Array<{ id: string; kind: string; createdAtMs: number; symbol: string; tradeId: string | null }>;
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
  accountId: string;
  trade: Trade;
  interval: string;
}
