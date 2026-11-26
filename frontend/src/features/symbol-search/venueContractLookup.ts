import { useEffect, useState } from "react";
import { fetchSymbolDiscovery } from "./symbolDiscoveryApi.js";
import { venueContractUnderlying, type VenueContractUnderlying } from "./symbolSearchFilter.js";
import type { SymbolSearchItem } from "./symbolSearchTypes.js";

/** Where a price series comes from: enough to find its catalog row. */
export interface MarketSymbolRef {
  exchange: string;
  marketType: string;
  symbol: string;
}

/** Catalog rows for one symbol; `settled` is false when the catalog could not answer yet. */
export interface VenueContractSearch {
  rows: readonly SymbolSearchItem[];
  settled: boolean;
}

export type VenueContractSearcher = (ref: MarketSymbolRef) => Promise<VenueContractSearch>;

const MAX_REMEMBERED = 256;
// Charts, reports and account rows show the label a moment later rather than
// adding a request to chart startup.
const LOOKUP_DELAY_MS = 1_000;

function normalized(ref: MarketSymbolRef): MarketSymbolRef {
  return {
    exchange: ref.exchange.trim().toLowerCase(),
    marketType: ref.marketType.trim().toLowerCase(),
    symbol: ref.symbol.trim().toUpperCase(),
  };
}

function lookupKey(ref: MarketSymbolRef): string {
  return `${ref.exchange}:${ref.marketType}:${ref.symbol}`;
}

/**
 * Venue contracts on a traditional underlying (ADR-DATA-002 D0) are derivatives;
 * spot rows never carry one, so they need no lookup.
 */
function eligible(ref: MarketSymbolRef): boolean {
  return !!ref.exchange && !!ref.symbol && !!ref.marketType && ref.marketType !== "spot";
}

/** Finds whether a chart's symbol is a venue contract on a traditional underlying. */
export class VenueContractLookup {
  private readonly answers = new Map<string, VenueContractUnderlying | null>();
  private readonly pending = new Map<string, Promise<VenueContractUnderlying | null>>();

  constructor(private readonly search: VenueContractSearcher) {}

  /** The remembered answer, or `undefined` when it still needs a lookup. */
  known(input: MarketSymbolRef): VenueContractUnderlying | null | undefined {
    const ref = normalized(input);
    if (!eligible(ref)) return null;
    return this.answers.get(lookupKey(ref));
  }

  resolve(input: MarketSymbolRef): Promise<VenueContractUnderlying | null> {
    const ref = normalized(input);
    if (!eligible(ref)) return Promise.resolve(null);
    const key = lookupKey(ref);
    if (this.answers.has(key)) return Promise.resolve(this.answers.get(key) ?? null);
    const running = this.pending.get(key);
    if (running) return running;
    const promise = this.search(ref)
      .then(({ rows, settled }) => {
        const row = rows.find((item) => (
          item.exchange.toLowerCase() === ref.exchange
          && item.marketType.toLowerCase() === ref.marketType
          && item.symbol.toUpperCase() === ref.symbol
        ));
        const answer = row ? venueContractUnderlying(row) : null;
        // A missing row only counts once the catalog has answered.
        if (row || settled) this.remember(key, answer);
        return answer;
      })
      .finally(() => { this.pending.delete(key); });
    this.pending.set(key, promise);
    return promise;
  }

  private remember(key: string, answer: VenueContractUnderlying | null): void {
    this.answers.delete(key);
    this.answers.set(key, answer);
    while (this.answers.size > MAX_REMEMBERED) {
      const oldest = this.answers.keys().next().value as string | undefined;
      if (oldest === undefined) break;
      this.answers.delete(oldest);
    }
  }
}

async function searchDiscovery(ref: MarketSymbolRef): Promise<VenueContractSearch> {
  const result = await fetchSymbolDiscovery({
    search: ref.symbol, source: ref.exchange, asset_class: "", market_type: ref.marketType,
    venue: "", quote: "", preferred_source: "", favorites: [], recent: [], scope: "all",
  }, new AbortController().signal);
  const status = result.sources.find((source) => source.id === ref.exchange)?.status;
  return { rows: result.symbols, settled: !result.partial && (status === "ready" || status === "stale") };
}

export const sharedVenueContractLookup = new VenueContractLookup(searchDiscovery);

/** What the series' contract tracks, when it is a venue contract on a traditional market. */
export function useVenueContractUnderlying(
  market: MarketSymbolRef | null | undefined,
  lookup: VenueContractLookup = sharedVenueContractLookup,
): VenueContractUnderlying | null {
  const exchange = market?.exchange ?? "";
  const marketType = market?.marketType ?? "";
  const symbol = market?.symbol ?? "";
  const [answer, setAnswer] = useState<VenueContractUnderlying | null>(
    () => lookup.known({ exchange, marketType, symbol }) ?? null,
  );
  useEffect(() => {
    const ref = { exchange, marketType, symbol };
    const known = lookup.known(ref);
    setAnswer(known ?? null);
    if (known !== undefined) return undefined;
    let cancelled = false;
    const timer = setTimeout(() => {
      lookup.resolve(ref).then(
        (value) => { if (!cancelled) setAnswer(value); },
        // No label is the safe fallback; the next chart or report asks again.
        () => undefined,
      );
    }, LOOKUP_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [exchange, marketType, symbol, lookup]);
  return answer;
}
