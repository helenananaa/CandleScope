import React, { useEffect, useState } from "react";
import { Button } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { StrategyDataManager } from "../../market-data/manager/strategyDataManager.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { ContinuousRun } from "./continuousTypes.js";
import ContinuousRunAccount from "./ContinuousRunAccount.js";

const SELECTION = "candlescope.continuous-reader.v1";
function remembered(): string {
  try { const value = localStorage.getItem(SELECTION); return value && value.length <= 128 ? value : ""; }
  catch { return ""; }
}

/** This independent view has no execution, source, editor or chart commands. */
export function SavedContinuousAccounts({ manager }: { manager: ContinuousStrategyDataManager }) {
  useLocale();
  const [runs, setRuns] = useState<ContinuousRun[]>([]), [selected, setSelected] = useState(remembered);
  const [error, setError] = useState<string | null>(null), [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const selectedExists = runs.some((run) => run.id === selected);
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError(null);
    void manager.catalog(abort.signal).then((catalog) => {
      if (abort.signal.aborted) return;
      setRuns(catalog.runs);
      setSelected((current) => catalog.runs.some((run) => run.id === current) ? current : catalog.runs[0]?.id ?? "");
    }).catch((failure: unknown) => {
      if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
    }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [manager, refresh]);
  return <section className="continuous-reader" data-continuous-reader>
    <p>{t("reader.readonly")}</p>
    <Button size="sm" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>{t("reader.refresh")}</Button>
    {loading && <p role="status">{t("reader.loading")}</p>}
    {!loading && !runs.length && !error && <p role="status">{t("reader.empty")}</p>}
    {runs.length > 0 && <label>{t("reader.select")}<select aria-label={t("reader.select")} value={selected} onChange={(event) => {
      setSelected(event.target.value);
      try { localStorage.setItem(SELECTION, event.target.value); }
      catch { setError(t("continuous.storage")); }
    }}>{runs.map((run) => <option key={run.id} value={run.id}>{run.id} · {run.phase}</option>)}</select></label>}
    {error && <p role="alert">{error}</p>}
    {selected && selectedExists && <ContinuousRunAccount key={selected} manager={manager} runId={selected} />}
  </section>;
}

export default function SavedContinuousAccountsHost() {
  const [manager, setManager] = useState<ContinuousStrategyDataManager | null>(null);
  useEffect(() => {
    // Effect ownership also handles React StrictMode's setup/cleanup/setup.
    const owner = new StrategyDataManager(); setManager(owner.continuous);
    return () => owner.dispose();
  }, []);
  return manager ? <SavedContinuousAccounts manager={manager} /> : <p>{t("reader.loading")}</p>;
}
