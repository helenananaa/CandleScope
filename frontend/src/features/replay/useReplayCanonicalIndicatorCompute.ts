import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { createReplayBuiltinCompute } from "./replayBuiltinCompute.js";
import { ReplayCanonicalIndicators, type ReplayCanonicalBinding, type ReplayIndicatorPreparation } from "./replayCanonicalIndicators.js";

const idle: ReplayIndicatorPreparation = { active: 0, phase: null, prepared: null, target: null };

export function useReplayCanonicalIndicatorCompute(scope: string, store: SeriesWindowStore, binding: ReplayCanonicalBinding | null) {
  const latest = useRef(binding);
  const activeScope = useRef<object | null>(null);
  useLayoutEffect(() => { latest.current = binding; }, [binding]);
  const [status, setStatus] = useState<{ scope: object; value: ReplayIndicatorPreparation } | null>(null);
  const context = useMemo(() => {
    const token = { scope };
    const source = new ReplayCanonicalIndicators(store, () => latest.current,
      value => { if (activeScope.current === token) setStatus({ scope: token, value }); });
    const compute = createReplayBuiltinCompute(source.compute,
      { seedForPayload: source.seedForPayload, sourceKey: source.sourceKey });
    return { token, source, compute };
  }, [scope, store]);
  useEffect(() => {
    activeScope.current = context.token;
    const unsubscribe = context.source.connect();
    return () => { if (activeScope.current === context.token) activeScope.current = null; unsubscribe(); };
  }, [context]);
  return { compute: context.compute, sourceKey: context.source.sourceKey(),
    preparation: status?.scope === context.token ? status.value : idle };
}
