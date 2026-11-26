import { Badge } from "../../components/ui/Display.js";
import { t } from "../../i18n/index.js";
import { useVenueContractUnderlying, type MarketSymbolRef, type VenueContractLookup } from "./venueContractLookup.js";

interface ContractPriceProps {
  market: MarketSymbolRef | null | undefined;
  /** Tests pass their own; the app shares one. */
  lookup?: VenueContractLookup | undefined;
}

/**
 * "Contract price": the series is an exchange contract on a traditional market
 * (gold, oil, a stock), so its prices are the contract's, not that market's
 * quotes (ADR-DATA-002 Q2).
 */
export function ContractPriceTag() {
  return <Badge tone="warning" className="contract-price-tag" title={t("search.contractPriceHint")}>{t("search.contractPrice")}</Badge>;
}

/** The tag for a chart, report or account row, once the symbol is known to be such a contract. */
export function ContractPriceBadge({ market, lookup }: ContractPriceProps) {
  return useVenueContractUnderlying(market, lookup) ? <ContractPriceTag /> : null;
}

/** The tag with its explanation spelled out, for reports that are read away from the chart. */
export function ContractPriceNotice({ market, lookup }: ContractPriceProps) {
  if (!useVenueContractUnderlying(market, lookup)) return null;
  return (
    <p className="contract-price-notice">
      <ContractPriceTag />
      <span>{t("search.contractPriceHint")}</span>
    </p>
  );
}
