import { useCallback } from "react";
import { useExchangeCatalog } from "../chart-session/exchangeCatalogRuntime.js";
import type { RoleSource } from "./capabilityRoles.js";

/** Each venue's capability document, or `undefined` until the exchange catalog is ready. */
export function useVenueRoles(): (exchange: string) => RoleSource {
  const { exchangeCatalog, exchangeCatalogStatus } = useExchangeCatalog();
  return useCallback((exchange: string) => (
    exchangeCatalogStatus === "ready" ? exchangeCatalog[exchange.toLowerCase()]?.raw ?? null : undefined
  ), [exchangeCatalog, exchangeCatalogStatus]);
}
