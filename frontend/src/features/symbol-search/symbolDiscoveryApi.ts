import { API_BASE } from "../../services/apiConfig.js";
import { request } from "../../services/api.js";
import { enrichSymbols } from "./symbolCatalogRuntime.js";
import type { SymbolSearchItem } from "./symbolSearchTypes.js";

export interface DiscoveryQuery {
  search: string; source: string; asset_class: string; market_type: string;
  venue: string; quote: string; preferred_source: string;
  favorites: string[]; recent: string[]; scope: "all" | "favorites" | "recent";
}
export interface DiscoveryFacet { key: string; count: number }
export interface DiscoveryResult {
  symbols: SymbolSearchItem[]; total: number; revision: string; nextOffset: number | null;
  facets: { assetClasses: DiscoveryFacet[]; markets: DiscoveryFacet[]; venues: DiscoveryFacet[]; quotes: DiscoveryFacet[] };
  sources: Array<{ id: string; status: string }>; partial: boolean;
}
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
export function parseDiscoveryResult(value: unknown): DiscoveryResult {
  if (!record(value) || !Array.isArray(value.symbols) || !record(value.facets)
    || !Array.isArray(value.sources) || !count(value.total) || typeof value.revision !== "string"
    || (value.nextOffset !== null && (!count(value.nextOffset) || value.nextOffset === 0 || value.nextOffset >= value.total)) || typeof value.partial !== "boolean") {
    throw new Error("Invalid symbol search response");
  }
  if (value.symbols.some((item: unknown) => !record(item)
    || ["symbol", "exchange", "marketType", "seriesKey"].some((key) => typeof item[key] !== "string" || !item[key])
    || ["providerId", "venue", "assetClass", "seriesVariant", "priceAdjustment", "sessionVariant", "volumeSemantics"].some((key) => item[key] != null && typeof item[key] !== "string"))) {
    throw new Error("Invalid symbol search identity");
  }
  const facets = (key: string): DiscoveryFacet[] => {
    const items = (value.facets as Record<string, unknown>)[key];
    if (!Array.isArray(items) || items.some((item: unknown) => !record(item) || typeof item.key !== "string" || !count(item.count))) {
      throw new Error("Invalid symbol search facets");
    }
    return items as DiscoveryFacet[];
  };
  if (value.sources.some((item: unknown) => !record(item) || typeof item.id !== "string" || typeof item.status !== "string")) {
    throw new Error("Invalid symbol source status");
  }
  return {
    symbols: enrichSymbols(value.symbols), total: value.total, revision: value.revision,
    nextOffset: value.nextOffset, partial: value.partial,
    facets: { assetClasses: facets("assetClasses"), markets: facets("markets"), venues: facets("venues"), quotes: facets("quotes") },
    sources: value.sources as DiscoveryResult["sources"],
  };
}
export async function fetchSymbolDiscovery(query: DiscoveryQuery, signal: AbortSignal, offset = 0, revision = "", loadSources: string[] = []): Promise<DiscoveryResult> {
  return parseDiscoveryResult(await request(`${API_BASE}/symbols/search`, {
    method: "POST", signal, body: { ...query, offset, revision, load_sources: loadSources, limit: 100 },
  }));
}
