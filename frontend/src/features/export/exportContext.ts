import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import type { ExportMetadata, ExportOptions } from "./exportTypes.js";

/** Capture only public configuration, never script source or computed series. */
export function buildExportIndicatorContext(indicators: IndicatorDefinition[]): NonNullable<ExportMetadata["indicators"]> {
  return indicators.filter((indicator) => indicator.visible !== false).map((indicator) => {
    const params = Object.entries(indicator.params || {})
      .filter(([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean")
      .map(([key, value]) => `${key}=${String(value)}`);
    return {
      label: `${indicator.name || indicator.id}${params.length ? ` (${params.join(", ")})` : ""}`,
      mainPane: (indicator.lines || []).some((line) => line.visible !== false && (!line.pane || line.pane === "main")),
    };
  });
}

/** Page captures already contain their own headers and legends. */
export function buildExportContextLines(options: ExportOptions): string[] {
  if (!options.includeContext || options.scope === "page") return [];
  const metadata = options.metadata || {};
  const title = [metadata.exchange, metadata.marketType, metadata.symbol, metadata.interval].filter(Boolean).join(" · ");
  const indicators = (metadata.indicators || [])
    .filter((indicator) => options.scope !== "main-pane" || indicator.mainPane)
    .map((indicator) => indicator.label);
  return [title, ...indicators].filter(Boolean);
}

/** Wrap long symbols/parameters as well as ordinary words, without clipping. */
export function wrapExportContext(lines: string[], maxWidth: number, measure: (text: string) => number): string[] {
  return lines.flatMap((line) => {
    const wrapped: string[] = [];
    let current = "";
    for (const word of line.trim().split(/\s+/)) {
      const candidate = current ? `${current} ${word}` : word;
      if (measure(candidate) <= maxWidth) {
        current = candidate;
        continue;
      }
      if (current) {
        wrapped.push(current.trimEnd());
        current = "";
      }
      for (const character of word) {
        if (current && measure(current + character) > maxWidth) {
          wrapped.push(current);
          current = "";
        }
        current += character;
      }
    }
    if (current.trim()) wrapped.push(current.trim());
    return wrapped;
  });
}
