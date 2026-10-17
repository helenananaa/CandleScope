import { t } from "../../i18n/index.js";
import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type { IndicatorSubPane } from "../indicators/indicatorPaneProjection.js";
import { getBuiltinIndicatorName } from "../indicators/indicatorPayloadRuntime.js";
import type { ReplayIndicatorPreparation } from "./replayCanonicalIndicators.js";

// These are the built-in output contracts. Script placement belongs to its
// returned output, not to a catalog default or a user-editable display name.
const BUILTIN_PANES: Readonly<Record<string, string>> = { RSI: "separate", ATR: "separate", MACD: "separate", VOL: "volume" };

export function replayIndicatorPresentation(view: IndicatorRuntime["view"], preparation: ReplayIndicatorPreparation, computingNow: boolean) {
  const visible = view.activeIndicators.filter(indicator => indicator.visible !== false);
  const pending = visible.some(indicator => !indicator.lines?.length && !indicator.error
    && (computingNow || Boolean(getBuiltinIndicatorName(indicator))));
  const fraction = preparation.active === 1 && visible.length === 1 ? preparation.fraction : null;
  const computing = t("indicator.computing") + (typeof fraction === "number" && Number.isFinite(fraction)
    && fraction >= 0 && fraction < 1 ? ` ${Math.floor(fraction * 100)}%` : "");
  const preparing = pending || preparation.active > 0;
  const errors = visible.filter(indicator => indicator.error).map(indicator => `${indicator.name || indicator.id}: ${indicator.error}`);
  const statusText = errors.length ? errors.join(" · ") : preparing ? computing : null;
  const panes: IndicatorSubPane[] = [];
  const used = new Set<string>();
  for (const indicator of visible) {
    const owned = view.subPanes.filter(pane => pane.owner?.kind === "indicator" && pane.owner.id === indicator.id);
    for (const pane of owned) {
      used.add(pane.id);
      const ownPending = preparation.pendingIds?.includes(indicator.id)
        ?? (preparation.active > 0 && !indicator.lines?.length);
      panes.push({ ...pane, statusText: indicator.error || (ownPending ? computing : pane.statusText ?? null) });
    }
    const target = BUILTIN_PANES[getBuiltinIndicatorName(indicator)];
    if (!owned.length && !indicator.lines?.length && target) {
      panes.push({ id: `${target}-${indicator.id}`, label: indicator.name || indicator.id, lines: [],
        owner: { kind: "indicator", id: indicator.id }, statusText: indicator.error || computing });
    }
  }
  // Preserve auxiliary panes whose ownership is outside the indicator runtime.
  panes.push(...view.subPanes.filter(pane => !used.has(pane.id) && pane.owner?.kind !== "indicator"));
  return { view: { ...view, subPanes: panes }, statusText };
}
