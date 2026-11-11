import { useEffect, useId, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { ContinuousAutoRepairPolicy } from "./continuousTypes.js";

export default function ContinuousAutoRepairSetting({ manager, runId, canEnable }: {
  manager: ContinuousStrategyDataManager;
  runId: string;
  canEnable: boolean;
}) {
  useLocale();
  const hint = useId();
  const [policy, setPolicy] = useState<ContinuousAutoRepairPolicy | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const write = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void manager.autoRepair(runId, controller.signal).then(({ policy }) => {
      if (!controller.signal.aborted) setPolicy(policy);
    }).catch((failure: Error) => {
      if (!controller.signal.aborted) setError(failure.message);
    });
    return () => { controller.abort(); write.current?.abort(); };
  }, [manager, runId, reload]);

  async function update(enabled: boolean) {
    if (!policy || write.current || (enabled && !canEnable)) return;
    const controller = new AbortController();
    write.current = controller;
    setSaving(true);
    setError(null);
    try {
      const result = await manager.setAutoRepair(runId, {
        enabled, expected_version: policy.version,
      }, controller.signal);
      if (!controller.signal.aborted) setPolicy(result.policy);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : String(failure));
        setPolicy(null);
        setReload(value => value + 1);
      }
    } finally {
      write.current = null;
      if (!controller.signal.aborted) setSaving(false);
    }
  }

  return <div className="continuous-repair" data-continuous-auto-repair>
    <label><input type="checkbox" aria-describedby={hint} checked={policy?.enabled ?? false}
      disabled={!policy || saving || (!policy.enabled && !canEnable)}
      onChange={event => void update(event.target.checked)} />{t("repair.auto")}</label>
    <p id={hint}>{t("repair.autoHint")}</p>
    {error && <p role="alert">{error} {!policy && <button type="button" onClick={() => {
      setError(null); setReload(value => value + 1);
    }}>{t("repair.autoReload")}</button>}</p>}
  </div>;
}
