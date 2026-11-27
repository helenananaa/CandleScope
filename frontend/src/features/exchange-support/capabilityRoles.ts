import type { ExchangeCapabilityPayload } from "../../services/apiPayloadParsers.js";

/**
 * Named data roles a venue declares (ADR-DATA-002 D3), mirroring the backend
 * `app/exchanges/roles.py`. Features ask for a role and its contract, never for
 * an exchange name.
 */
export const TRADES_HISTORY_ARCHIVE = "trades.history.archive";
export const BINANCE_USDM_AGG_TRADES_ARCHIVE = "binance.public-data.um-agg-trades.daily/1";
export const HEDGE_PUBLIC_HISTORY = "hedge.public_history";
/** Futures contract rules continuous runs simulate: base-unit quantity, linear. */
export const CONTRACT_RULES = "contract_rules";
export const BINANCE_USDM_LINEAR_BASE_QUANTITY = "BINANCE_USDM_LINEAR_BASE_QUANTITY";

/** Funding between settlements rebuilt from the minute premium index. */
export const FUNDING_HYBRID_HISTORY = "funding.hybrid_history";
export const BINANCE_PREMIUM_INDEX_CUMAVG = "binance-premium-index-cumavg-v2";
/** Open-interest history on a fixed sample grid. */
export const OPEN_INTEREST_NATIVE_GRID = "open_interest.native_grid";
/** The grid that covers every chart period (Gate's `gate-oi-grid-v1` covers only 5m). */
export const BINANCE_OI_GRID = "binance-oi-grid-v2";

/** A venue's capability document; `undefined` while the exchange catalog is unknown. */
export type RoleSource = Pick<ExchangeCapabilityPayload, "roles"> | null | undefined;

/** The contract that supplies `role` for this market, or null when the venue declares none. */
export function capabilityRoleContract(capability: RoleSource, marketType: string, role: string): string | null {
  const market = marketType.trim().toLowerCase();
  const roles: unknown = capability?.roles;
  if (!Array.isArray(roles)) return null;
  const found = roles.find((item) => (
    item?.role === role && Array.isArray(item.market_types)
    && item.market_types.some((value: unknown) => String(value).toLowerCase() === market)
  ));
  return typeof found?.contract === "string" ? found.contract : null;
}

/**
 * Continuous runs simulate spot cash or base-quantity linear futures. While the
 * venue's roles are unknown the backend decides when the run is created.
 */
export function continuousMarketSupported(venue: RoleSource, marketType: string): boolean {
  if (marketType === "spot") return true;
  if (marketType !== "futures") return false;
  return venue === undefined
    || capabilityRoleContract(venue, marketType, CONTRACT_RULES) === BINANCE_USDM_LINEAR_BASE_QUANTITY;
}
