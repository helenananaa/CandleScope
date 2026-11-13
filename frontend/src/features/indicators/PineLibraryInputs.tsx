import { useState } from "react";
import { t } from "../../i18n/index.js";
import { Disclosure } from "../../components/ui/Display.js";
import { Textarea } from "../../components/ui/Field.js";

import { parsePineLibraries } from "./pineLibraryModel.js";

export function PineLibraryInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <Disclosure summary={t("native.inputs.libraries")}>
    <div className="indicator-editor-advanced-body">
      <Textarea className="indicator-editor-json" aria-label={t("native.inputs.libraries")} aria-invalid={error ? true : undefined} value={value} readOnly={readOnly} rows={5} spellCheck={false}
        placeholder={JSON.stringify({ "Author/Library/1": '//@version=6\nlibrary("Library")\nexport twice(float x) => x * 2' }, null, 2)}
        onChange={(event) => { onChange(event.target.value); try { parsePineLibraries(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
      {error && <p className="ui-field-error" role="alert">{error}</p>}
    </div>
  </Disclosure>;
}
