import { t, type MessageKey } from "../../i18n/index.js";
import { formatDecimal } from "../../shared/formatDecimal.js";
import type { ReplayCatalogEntry } from "./replayTypes.js";
import type {
  ReplayV2IntegrityMode,
  ReplayV2RunState,
  ReplayV2SourceKind,
  ReplayV2TimeDisclosurePolicy,
  TrainingRunCard,
  TrainingRunCompatibility,
} from "./replayV2Types.js";

export function trainingRunStateLabel(state: ReplayV2RunState): string {
  switch (state) {
    case "AWAITING_MARKET":
      return t("replay.state.awaiting");
    case "PAUSED":
      return t("replay.state.paused");
    case "PLAYING":
      return t("replay.state.playing");
    case "ADVANCING":
      return t("replay.state.advancing");
    case "ENDED":
      return t("replay.state.ended");
    case "ERROR":
      return t("replay.state.error");
  }
}

/**
 * A run's status line. The server sends a status code with a Simplified Chinese message; known codes
 * show the catalog's message in the reader's language, and an unknown code shows the server's text.
 * An ended run is described by whether its review can open, whatever its stored status says.
 */
export function trainingRunStatusLabel(card: Pick<TrainingRunCard, "state" | "resume_action" | "status">): string {
  if (card.state === "ENDED") {
    return card.resume_action === "UNAVAILABLE" ? t("replay.hub.endedUnavailable") : t("replay.hub.endedReviewable");
  }
  switch (card.status.code) {
    case "READY":
      return t("replay.hub.statusReady");
    case "AWAITING_MARKET":
      return t("replay.hub.statusAwaitingMarket");
    case "UNAVAILABLE":
      return t("replay.hub.statusUnavailable");
    case "HEDGE_INPUT_RECOVERY_REQUIRED":
      return t("replay.hub.statusHedgeRecovery");
    default:
      return card.status.message;
  }
}

export function trainingIntegrityLabel(mode: ReplayV2IntegrityMode): string {
  switch (mode) {
    case "CHALLENGE":
      return t("replay.hub.challenge");
    case "PRACTICE":
      return t("replay.hub.practice");
    case "SANDBOX":
      return t("replay.hub.sandbox");
  }
}

export function trainingSourceKindLabel(kind: ReplayV2SourceKind): string {
  return kind === "AGG_TRADE" ? t("replay.source.agg") : t("replay.source.bar");
}

export function trainingTimeDisclosureLabel(
  policy: ReplayV2TimeDisclosurePolicy,
): string {
  switch (policy) {
    case "NONE":
      return t("replay.time.none");
    case "HIDE_YEAR":
      return t("replay.time.hideYear");
    case "HIDE_MONTH":
      return t("replay.time.hideMonth");
    case "HIDE_DAY":
      return t("replay.time.hideDay");
    case "HIDE_HOUR":
      return t("replay.time.hideHour");
    case "HIDE_MINUTE":
      return t("replay.time.hideMinute");
    case "HIDE_ALL":
      return t("replay.time.hideAll");
  }
}

export function trainingCompatibilityLabel(
  value: TrainingRunCompatibility,
): string {
  return value === "READY" ? t("replay.compat.ready") : t("replay.compat.blocked");
}

export function trainingMarketTypeLabel(marketType: string): string {
  switch (marketType) {
    case "futures":
      return t("replay.market.futures");
    case "spot":
      return t("replay.market.spot");
    case "margin":
      return t("replay.market.margin");
    default:
      return marketType;
  }
}

export function trainingExchangeLabel(exchange: string): string {
  switch (exchange) {
    case "binance":
      return "Binance";
    case "okx":
      return "OKX";
    default:
      return exchange;
  }
}

export function trainingVenueLabel(entry: Pick<ReplayCatalogEntry, "identity">): string {
  return `${trainingExchangeLabel(entry.identity.exchange)} · ${trainingMarketTypeLabel(entry.identity.market_type)}`;
}

export function trainingMarketKey(entry: Pick<ReplayCatalogEntry, "identity">): string {
  return `${entry.identity.exchange}:${entry.identity.market_type}:${entry.identity.symbol}`;
}

export function isReplayInitialMarketAvailable(entry: ReplayCatalogEntry): boolean {
  return entry.selected_base_interval !== null
    && entry.start_compatibility?.state === "READY";
}

function padUtc(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatReplayUtcDate(ms: number): string {
  const instant = new Date(ms);
  return `${instant.getUTCFullYear()}-${padUtc(instant.getUTCMonth() + 1)}-${padUtc(instant.getUTCDate())}`;
}

export function formatReplayUtcDateTime(ms: number): string {
  const instant = new Date(ms);
  return `${formatReplayUtcDate(ms)} ${padUtc(instant.getUTCHours())}:${padUtc(instant.getUTCMinutes())} UTC`;
}

export function formatTrainingEquity(value: string, maximumFractionDigits = 2): string {
  return formatDecimal(value, maximumFractionDigits);
}

export function formatReplayMarketCoverage(
  entry: ReplayCatalogEntry,
  blind: boolean,
): string {
  if (blind) return t("replay.coverage.hidden");
  const bounds = entry.bounds;
  if (bounds === null) return t("replay.coverage.pending");
  return `${formatReplayUtcDate(bounds.earliest_open_ms)} – ${formatReplayUtcDate(bounds.latest_closed_open_ms)}`;
}

/** A run's or session's state for the status bar; loading phases read as opening, unknown values as-is. */
export function replayStateLabel(state: string | null | undefined): string {
  switch (state) {
    case "AWAITING_MARKET": return t("replay.state.awaiting");
    case "PAUSED": return t("replay.state.paused");
    case "PLAYING": return t("replay.state.playing");
    case "ADVANCING": return t("replay.state.advancing");
    case "ENDED":
    case "STOPPED": return t("replay.state.ended");
    case "ERROR":
    case "ENTRY_ERROR": return t("replay.state.error");
    case "INITIALIZING":
    case "IDLE":
    case "LOADING_CAPABILITIES":
    case "VALIDATING_SESSION":
    case "CONNECTING_SESSION":
    case "ACTIVE":
    case null:
    case undefined: return t("replay.opening");
    default: return state;
  }
}

/** How faithful the run's history is: exact or approximate. */
export function replayQualityLabel(mode: string | null | undefined): string {
  return mode === "best_effort" ? t("replay.capability.approx") : t("replay.capability.exact");
}

/** A capability's level: exact, approximate, or not available. */
export function replayCapabilityStateLabel(state: string): string {
  if (state === "AVAILABLE_EXACT") return t("replay.capability.exact");
  if (state === "AVAILABLE_APPROX") return t("replay.capability.approx");
  return t("replay.capability.unsupported");
}

const MUTATION_KEYS: Readonly<Record<string, MessageKey>> = {
  deposit: "replay.mutation.deposit",
  withdraw: "replay.mutation.withdraw",
  change_fee_policy: "replay.mutation.changeFeePolicy",
  change_leverage_cap: "replay.mutation.changeLeverageCap",
  change_funding_policy: "replay.mutation.changeFundingPolicy",
  reveal_time: "replay.mutation.revealTime",
};

/** A practice change that can be allowed (deposit, change fees…); unknown ids stay as they are. */
export function replayMutationLabel(mutation: string): string {
  const key = MUTATION_KEYS[mutation];
  return key ? t(key) : mutation;
}

const REVISION_KIND_KEYS: Readonly<Record<string, MessageKey>> = {
  FEE_POLICY: "replay.revisionKind.feePolicy",
  LEVERAGE_CAP: "replay.revisionKind.leverageCap",
  FUNDING_POLICY: "replay.revisionKind.fundingPolicy",
};

export function replayRevisionKindLabel(kind: string): string {
  const key = REVISION_KIND_KEYS[kind];
  return key ? t(key) : kind;
}

const AUDIT_KEYS: Readonly<Record<string, MessageKey>> = {
  NOT_RUN: "replay.audit.notRun",
  PASS: "replay.audit.pass",
  FAIL: "replay.audit.fail",
  NOT_APPLICABLE: "replay.audit.notApplicable",
};

/** An account audit's result: passed, failed, not run. */
export function replayAuditStatusLabel(status: string): string {
  const key = AUDIT_KEYS[status];
  return key ? t(key) : status;
}

const ACCOUNT_MODE_KEYS: Readonly<Record<string, MessageKey>> = {
  HISTORICAL_EXACT: "replay.hub.accountData.historicalExact",
  APPROX_PROXY: "replay.hub.accountData.approxProxy",
  DETERMINISTIC_SIMULATION: "replay.hub.accountData.deterministicSimulation",
};

/** Where the modelled account's inputs come from (the same names as the create dialog). */
export function replayAccountModeLabel(mode: string): string {
  const key = ACCOUNT_MODE_KEYS[mode];
  return key ? t(key) : mode;
}

/** How faithful a liquidation channel is: exact inputs, approximate, or not available. */
export function replayLiquidationFidelityLabel(fidelity: string): string {
  if (fidelity === "UNSUPPORTED_NO_HISTORY") return t("replay.capability.unsupported");
  return fidelity.startsWith("HISTORICAL_EXACT") ? t("replay.capability.exact") : t("replay.capability.approx");
}

const LIQUIDATION_STATE_KEYS: Readonly<Record<string, MessageKey>> = {
  RISK_BREACH_DETECTED: "replay.liqState.riskBreach",
  CANCELING_ORDERS: "replay.liqState.cancelingOrders",
  CANCEL_ORDERS: "replay.liqState.cancelingOrders",
  RISK_RECHECK: "replay.liqState.riskRecheck",
  PARTIAL_LIQUIDATION: "replay.liqState.partial",
  FULL_LIQUIDATION: "replay.liqState.full",
  BANKRUPTCY_TRANSFER: "replay.liqState.bankruptcyTransfer",
  INSURANCE_FUND_SETTLEMENT: "replay.liqState.insuranceSettlement",
  ADL: "replay.liqState.adl",
  RECOVERED_AFTER_CANCEL: "replay.liqState.recoveredAfterCancel",
  COMPLETED: "replay.liqState.completed",
  COMPLETE: "replay.liqState.completed",
  BANKRUPT: "replay.liqState.bankrupt",
  FAILED_CLOSED: "replay.liqState.failedClosed",
  PENDING: "replay.liqState.pending",
  NEW: "replay.liqState.pending",
  APPLIED: "replay.liqState.applied",
  PARTIAL: "replay.liqState.partialLeg",
  CLOSED: "replay.liqState.closed",
  TRANSFERRED: "replay.liqState.transferred",
  FILLED: "replay.liqState.filled",
  PARTIALLY_FILLED: "replay.liqState.partiallyFilled",
  CANCELED: "replay.liqState.canceled",
};

/** A simulated liquidation's stage or state (case, step, leg, order, auto-deleveraging). */
export function replayLiquidationStateLabel(state: string): string {
  const key = LIQUIDATION_STATE_KEYS[state];
  return key ? t(key) : state;
}

export function replayPositionSideLabel(side: string): string {
  return side === "LONG" ? t("replay.wb.long") : side === "SHORT" ? t("replay.wb.short") : side;
}

export function replayOrderLabel(side: string, type: string): string {
  const sideLabel = side === "BUY" ? t("replay.paper.buy") : side === "SELL" ? t("replay.paper.sell") : side;
  const typeLabel = type === "MARKET" ? t("replay.paper.typeMarket") : type === "LIMIT" ? t("replay.paper.typeLimit") : type;
  return `${sideLabel} ${typeLabel}`;
}

export function replaySeverityLabel(severity: string): string {
  if (severity === "CRITICAL") return t("replay.severity.critical");
  if (severity === "WARNING") return t("replay.severity.warning");
  return t("replay.severity.info");
}
