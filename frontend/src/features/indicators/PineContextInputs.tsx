import { useState } from "react";
import { t } from "../../i18n/index.js";
import { Disclosure } from "../../components/ui/Display.js";
import { Textarea } from "../../components/ui/Field.js";

import { parsePineContexts } from "./pineContextModel.js";

export function PineContextInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <Disclosure summary={t("indicator.pine.contexts")}>
    <div className="indicator-editor-advanced-body">
      <p className="indicator-editor-hint">{t("indicator.pine.contextsHelp")}</p>
      <Textarea className="indicator-editor-json" aria-label={t("indicator.pine.contexts")} aria-invalid={error ? true : undefined} value={value} readOnly={readOnly} rows={4} spellCheck={false}
        placeholder={'[{"symbol":"OKX:BTC-USDT","timeframe":"60","marketType":"spot"}]'}
        onChange={(event) => { onChange(event.target.value); try { parsePineContexts(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
      {error && <p className="ui-field-error" role="alert">{error}</p>}
    </div>
  </Disclosure>;
}
