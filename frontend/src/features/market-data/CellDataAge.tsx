import { memo, useEffect, useState } from "react";
import { getDateTimeLocale, t } from "../../i18n/index.js";
import type { SeriesWindowStore } from "./window/seriesWindowStore.js";
import { dataAgeLevel, formatDataAge, LIVE_DELTA_TYPES } from "./cellDataAgeModel.js";

/**
 * Quiet freshness badge for one chart cell. Owns its own clock so only this
 * badge re-renders each second, not the chart cell around it.
 */
function CellDataAge({ store }: { store: SeriesWindowStore | null }) {
  const [lastLiveAt, setLastLiveAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!store) return undefined;
    setLastLiveAt(store.isEmpty() ? null : Date.now());
    const unsubscribe = store.subscribe((delta) => {
      if (delta.changed && LIVE_DELTA_TYPES.has(delta.type)) setLastLiveAt(Date.now());
    });
    return () => {
      unsubscribe();
    };
  }, [store]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (lastLiveAt === null) return null;
  const ageSeconds = Math.max(0, (now - lastLiveAt) / 1000);
  const level = dataAgeLevel(ageSeconds);
  if (level === "fresh") return null;
  const stale = level === "stale";
  const received = new Date(lastLiveAt).toLocaleTimeString(getDateTimeLocale(), { hour12: false });
  return (
    <span
      className={`cell-data-age${stale ? " is-stale" : ""}`}
      title={`${t("orderBook.lastReceived")} ${received}`}
    >
      {formatDataAge(ageSeconds)}
    </span>
  );
}

export default memo(CellDataAge);
