import { t } from "../../i18n/index.js";
import { formatDecimal } from "../../shared/formatDecimal.js";
import type { ReplayCatalogEntry } from "./replayTypes.js";
import type {
  ReplayV2IntegrityMode,
  ReplayV2RunState,
  ReplayV2SourceKind,
  ReplayV2TimeDisclosurePolicy,
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
