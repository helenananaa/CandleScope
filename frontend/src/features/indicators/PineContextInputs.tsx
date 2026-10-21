import { useState } from "react";
import { t } from "../../i18n/index.js";

import { parsePineContexts } from "./pineContextModel.js";

export function PineContextInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <details><summary>{t("indicator.pine.contexts")}</summary>
    <p>{t("indicator.pine.contextsHelp")}</p>
    <textarea aria-label={t("indicator.pine.contexts")} rows={4} value={value} readOnly={readOnly}
      placeholder={'[{"symbol":"OKX:BTC-USDT","timeframe":"60","marketType":"spot"}]'}
      style={{ width: "100%", fontFamily: "monospace", background: "var(--bg-primary)", color: "var(--text-primary)" }}
      onChange={(event) => { onChange(event.target.value); try { parsePineContexts(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
    {error && <p role="alert">{error}</p>}
  </details>;
}
