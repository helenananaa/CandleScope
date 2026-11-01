import { useEffect, useRef, useState, type ReactNode } from "react";
import { createReplayMarketDataManager, ReplayDataContext } from "./replayDataContext.js";

export function ReplayDataProvider({ children }: { children: ReactNode }) {
  const [manager] = useState(createReplayMarketDataManager);
  const leases = useRef(0);
  useEffect(() => {
    leases.current += 1;
    const global = window as typeof window & { __CANDLESCOPE_REPLAY_DATA__?: { snapshot(): object } };
    const handle = { snapshot: () => manager.diagnostics() };
    global.__CANDLESCOPE_REPLAY_DATA__ = handle;
    return () => {
      if (global.__CANDLESCOPE_REPLAY_DATA__ === handle) delete global.__CANDLESCOPE_REPLAY_DATA__;
      leases.current -= 1;
      queueMicrotask(() => { if (!leases.current) manager.closeAll(); });
    };
  }, [manager]);
  return <ReplayDataContext.Provider value={manager}>{children}</ReplayDataContext.Provider>;
}
