import { useCallback, useEffect, useState } from "react";

/** Per-chart holds never occupy the transport gate shared by other charts. */
export function useHistoryHydrationHolds(): readonly [boolean, () => () => void] {
  const [holds, setHolds] = useState(0);
  const acquire = useCallback(() => {
    let released = false;
    setHolds(count => count + 1);
    return () => {
      if (released) return;
      released = true;
      setHolds(count => Math.max(0, count - 1));
    };
  }, []);
  return [holds > 0, acquire];
}

/** Finish the current visible indicator window before requesting a deeper one. */
export function useIndicatorHistoryPreparation(
  historyPreparing: boolean,
  indicatorComputing: boolean,
  holdHydration: (() => () => void) | undefined,
): void {
  useEffect(() => {
    if (!historyPreparing || !indicatorComputing) return undefined;
    // A foreground indicator range request can still supply missing warmup
    // bars. Only hydration/speculative work waits for this lease.
    return holdHydration?.();
  }, [historyPreparing, indicatorComputing, holdHydration]);
}
