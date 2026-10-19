import { useState } from "react";
import { t } from "../../i18n/index.js";
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
export function PineLibraryInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <details><summary>{t("native.inputs.libraries")}</summary>
    <textarea aria-label={t("native.inputs.libraries")} value={value} readOnly={readOnly} rows={5}
      placeholder={JSON.stringify({ "Author/Library/1": '//@version=6\nlibrary("Library")\nexport twice(float x) => x * 2' }, null, 2)}
      style={{ width: "100%", fontFamily: "monospace", background: "var(--bg-primary)", color: "var(--text-primary)" }}
      onChange={(event) => { onChange(event.target.value); try { parsePineLibraries(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
    {error && <p role="alert">{error}</p>}
  </details>;
}
export function pineLibraryParams(params: IndicatorParams | undefined, value: string): IndicatorParams {
  const libraries = parsePineLibraries(value);
  const result = { ...params };
  delete result.__pineLibraries;
  return Object.keys(libraries).length ? { ...result, __pineLibraries: libraries } : result;
}
