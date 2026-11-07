import { useCallback, useSyncExternalStore } from "react";

import { t } from "../../../i18n/index.js";
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import type { ContinuousView } from "./continuousView.js";

const emptyTail = () => "";
const utc = (value: number) => new Date(value).toISOString().replace("T", " ").replace("Z", " UTC");

export default function ContinuousBarBoundary({ marketWindow, view }: {
  marketWindow: SeriesWindowView | null;
  view: ContinuousView | null;
}) {
  const through = view && view.identity.sequence > 0 ? view.identity.event_time_ms : null;
  const canAdvance = !view?.stale && (view?.run.phase === "LIVE" || view?.run.phase === "CATCHING_UP");
  const subscribe = useCallback((change: () => void) => marketWindow?.subscribe(change) ?? (() => {}), [marketWindow]);
  const readTail = useCallback(() => {
    if (!marketWindow || marketWindow.intervalSeconds !== 60 || marketWindow.rightTruncated) return "";
    const bar = marketWindow.last();
    if (!bar || typeof bar.is_closed !== "boolean") return "";
    const open = Number(bar.time) * 1000;
    if (!Number.isSafeInteger(open) || open < 0 || open > 8640000000000000 - 60_000
      || (through !== null && open + 59_999 <= through)) return "";
    if (!bar.is_closed) return `forming:${open}`;
    return canAdvance ? `waiting:${open}` : "";
  }, [marketWindow, through, canAdvance]);
  // Only the boundary or finality changes this snapshot. Intrabar OHLCV
  // updates continue to paint on the chart without repainting this panel.
  const tail = useSyncExternalStore(subscribe, readTail, emptyTail);
  const [phase, open] = tail.split(":");
  return <section data-continuous-bar-boundary>
    {tail && <p data-continuous-market-bar={phase} data-open-ms={open}>{t(
      phase === "forming" ? "continuous.formingBar" : "continuous.waitingBar", { time: utc(Number(open)) },
    )}</p>}
    {through !== null && through <= 8640000000000000 && <p data-continuous-committed-through={through}>{t(
      view?.stale ? "continuous.previousClosedBar" : "continuous.committedClosedBar", { time: utc(through) },
    )}</p>}
  </section>;
}
