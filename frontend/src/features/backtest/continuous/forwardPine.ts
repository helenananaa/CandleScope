import { parsePineLibraries } from "../../indicators/pineLibraryModel.js";

/**
 * Which chart strategies a forward run accepts (backend `continuous_pine.py`, B-333b).
 *
 * Python runs as before. A Pine script runs as close-bar orders on the CandleScope bar
 * account at leverage 1, on its own chart's bars: never with a signal chart. Whether the
 * script itself stays in that subset (no fill callbacks, tick recalculation, closing
 * orders, stop rules or requested data) only the Pine compiler knows, so the backend
 * names any such feature when the run is created.
 */
export type ForwardSupport = { supported: true } | { supported: false; reason: "LANGUAGE" | "PINE_SIGNAL_CHART" };

export function forwardSupport(language: string | undefined, signalChart: unknown): ForwardSupport {
  if (language === "python") return { supported: true };
  if (language !== "pine") return { supported: false, reason: "LANGUAGE" };
  return signalChart ? { supported: false, reason: "PINE_SIGNAL_CHART" } : { supported: true };
}

/** The editor-only Pine fields an attachment keeps among its parameters. */
const PINE_EDITOR_FIELDS = ["__pineLibraries", "__pineLibrariesText", "__pineInputs"] as const;

/**
 * A Pine forward run's provider parameters and libraries, from the attachment's parameters,
 * read the way a fixed-history chart run reads them (`chartStrategyRunRequest.ts`).
 * Throws when the library text is not an import-path to source mapping.
 */
export function pineForwardInputs(parameters: Record<string, unknown>): { parameters: Record<string, unknown>; libraries: Record<string, string> } {
  const libraries = parsePineLibraries(typeof parameters.__pineLibrariesText === "string"
    ? parameters.__pineLibrariesText : JSON.stringify(parameters.__pineLibraries ?? {}));
  const rest = { ...parameters };
  for (const field of PINE_EDITOR_FIELDS) delete rest[field];
  return { parameters: rest, libraries };
}
