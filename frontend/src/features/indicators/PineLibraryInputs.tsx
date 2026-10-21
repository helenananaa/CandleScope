import { useState } from "react";
import { t } from "../../i18n/index.js";

import { parsePineLibraries } from "./pineLibraryModel.js";

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
