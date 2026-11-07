import { useEffect, useRef, useState } from "react";
import { defaultBacktestApi } from "../backtest/backtestApi.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { projectSelectedVersion, saveResearchReturn, type ResearchReturnReference } from "./researchSelectedVersion.js";
import { researchReturnError } from "./researchReturnError.js";
/** Mount per selected run, so a history selection invalidates an in-flight click. */
export default function ResearchReturnButton({ runId, origin }: { runId: string; origin: ResearchReturnReference["origin"] }) {
  useLocale();
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [runId]);
  async function select() {
    if (pending.current) return;
    const controller = new AbortController(); pending.current = controller; setBusy(true); setError(null);
    try {
      const version = await defaultBacktestApi.getSelectedVersion!(runId, controller.signal);
      projectSelectedVersion(version);
      if (controller.signal.aborted) return;
      const href = await saveResearchReturn({ schema: 1, runId, versionHash: version.version_hash, origin });
      if (!controller.signal.aborted) window.location.assign(href);
    } catch (failure) { if (!controller.signal.aborted) setError(researchReturnError(failure)); }
    finally { if (!controller.signal.aborted) { pending.current = null; setBusy(false); } }
  }
  return <div data-research-return>
    <button type="button" className="ui-control" disabled={busy} onClick={() => { void select(); }}>{t(busy ? "researchReturn.loading" : "researchReturn.select")}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}
