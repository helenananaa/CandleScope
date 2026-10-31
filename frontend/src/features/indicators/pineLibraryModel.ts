import type { IndicatorParams } from "./indicatorTypes.js";

export function parsePineLibraries(value: string): Record<string, string> {
  const parsed: unknown = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Expected an import-path to source mapping");
  const entries = Object.entries(parsed);
  if (entries.length > 64 || entries.some(([key, source]) => !/^[A-Za-z_][\w.-]*\/[A-Za-z_][\w.-]*\/[1-9][0-9]*$/.test(key) || typeof source !== "string" || !source.trim()))
    throw new Error("Use owner/name/version keys with nonempty Pine source text");
  if (new TextEncoder().encode(JSON.stringify(parsed)).length > 2_000_000) throw new Error("Library sources exceed 2 MB");
  return Object.fromEntries(entries) as Record<string, string>;
}
export function pineLibraryParams(params: IndicatorParams | undefined, value: string): IndicatorParams {
  const libraries = parsePineLibraries(value);
  const result = { ...params };
  delete result.__pineLibraries;
  return Object.keys(libraries).length ? { ...result, __pineLibraries: libraries } : result;
}
