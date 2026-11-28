import { useEffect, useState } from "react";

import { t } from "../../../i18n/index.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { PineForwardSupport } from "./continuousTypes.js";

export type PineForwardCheck =
  | { state: "checking" }
  | { state: "ready"; support: PineForwardSupport }
  | { state: "failed"; message: string };

/**
 * Whether this Pine code stays in the forward subset (close-bar ORDER_INTENT, B-333b), compiled by the
 * backend as creating the run would compile it. Nothing is asked while disabled; edits wait 500 ms.
 */
export function usePineForwardSupport(manager: ContinuousStrategyDataManager | undefined, source: string,
  libraries: Record<string, string> | null, enabled: boolean): PineForwardCheck | null {
  const asked = enabled && !!manager && libraries !== null && source.trim().length > 0;
  const key = asked ? JSON.stringify([source, libraries]) : null;
  const [checked, setChecked] = useState<{ key: string; check: PineForwardCheck } | null>(null);
  useEffect(() => {
    if (!key || !manager || !libraries) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      void manager.pineSupport(source, libraries, abort.signal).then(
        (support) => { if (!abort.signal.aborted) setChecked({ key, check: { state: "ready", support } }); },
        (failure: unknown) => {
          if (!abort.signal.aborted) setChecked({ key, check: { state: "failed", message: failure instanceof Error ? failure.message : String(failure) } });
        },
      );
    }, 500);
    return () => { window.clearTimeout(timer); abort.abort(); };
  }, [key, manager, source, libraries]);
  if (!key) return null;
  return checked?.key === key ? checked.check : { state: "checking" };
}

/** Why the native list cannot track this Pine strategy forward yet, or null when it can. */
export function pineForwardRefusal(check: PineForwardCheck | null): string | null {
  if (!check || check.state === "checking") return t("strategyForward.pineChecking");
  if (check.state === "failed") return `${t("strategyForward.pineCheckFailed")} ${check.message}`.trim();
  return check.support.supported ? null : t("strategyForward.pineUnsupported", { uses: check.support.uses.join(", ") });
}
