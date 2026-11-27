import { useEffect, useRef, useState } from "react";
import { Button, InlineAlert } from "../../components/ui/index.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { useStrategyDataManager } from "../market-data/useStrategyDataManager.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { projectSelectedVersion, saveResearchReturn, type ResearchReturnReference } from "./researchSelectedVersion.js";
import { researchReturnError } from "./researchReturnError.js";
import { useVenueRoles } from "../exchange-support/useVenueRoles.js";
/** Mount per selected run, so a history selection invalidates an in-flight click. */
export default function ResearchReturnButton({ runId, origin, manager: explicitManager }: {
  runId: string; origin: ResearchReturnReference["origin"]; manager?: StrategyDataManager | null;
}) {
  useLocale();
  const manager = useStrategyDataManager(explicitManager);
  const venueRoles = useVenueRoles();
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [runId]);
  async function select() {
    if (pending.current || !manager) return;
    const controller = new AbortController(); pending.current = controller; setBusy(true); setError(null);
    try {
      const version = await manager.loadSelectedRunVersion(runId, controller.signal);
      projectSelectedVersion(version, venueRoles(String(version.configuration.exchange)));
      if (controller.signal.aborted) return;
      const href = await saveResearchReturn({ schema: 1, runId, versionHash: version.version_hash, origin }, manager);
      if (!controller.signal.aborted) window.location.assign(href);
    } catch (failure) { if (!controller.signal.aborted) setError(researchReturnError(failure)); }
    finally { if (!controller.signal.aborted) { pending.current = null; setBusy(false); } }
  }
  return <div className="research-return" data-research-return>
    <Button size="sm" disabled={busy || !manager} onClick={() => { void select(); }}>{t(busy ? "researchReturn.loading" : "researchReturn.select")}</Button>
    {error && <InlineAlert tone="danger">{error}</InlineAlert>}
  </div>;
}
