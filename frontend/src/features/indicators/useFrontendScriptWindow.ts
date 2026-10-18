import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { INDICATOR_HISTORY_LIMIT } from "./indicatorComputeRuntime.js";

/** Sample the source contract, whose O(1) tick deliberately retains array identity.
 * Never publish a new tick generation while bounded compute is still running:
 * otherwise a continuous feed could cancel every attempt before its timeout.
 */
export function useFrontendScriptWindow(
  source: SeriesWindowStore | null,
  enabled: boolean,
  contextKey: string,
) {
  const initial = useMemo(() => enabled && source ? {
    source, contextKey, version: source.version,
    rows: source.snapshot().slice(-INDICATOR_HISTORY_LIMIT),
  } : null, [contextKey, enabled, source]);
  const [sample, setSample] = useState(initial);
  const pending = useRef(0);
  const wake = useRef<(() => void) | null>(null);
  const onComputePendingChange = useCallback((delta: 1 | -1) => {
    pending.current = Math.max(0, pending.current + delta);
    if (!pending.current) wake.current?.();
  }, []);

  useLayoutEffect(() => {
    if (!enabled || !source) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let dirty = false;
    const publish = () => {
      dirty = false;
      setSample(previous => previous?.source === source && previous.contextKey === contextKey
        && previous.version === source.version ? previous : {
          source, contextKey, version: source.version,
          rows: source.snapshot().slice(-INDICATOR_HISTORY_LIMIT),
        });
    };
    const schedule = () => {
      if (!dirty || timer !== undefined || pending.current) return;
      timer = setTimeout(() => {
        timer = undefined;
        if (!pending.current && dirty) publish();
      }, 250);
    };
    wake.current = schedule;
    const unsubscribe = source.subscribe(delta => {
      if (delta.type === "tick" && delta.appended !== true) {
        dirty = true;
        schedule();
      } else {
        // Source replacement, history correction and a new candle are real
        // ownership changes; fence old work immediately even if it is busy.
        if (timer !== undefined) clearTimeout(timer);
        timer = undefined;
        publish();
      }
    });
    publish();
    return () => {
      unsubscribe();
      if (timer !== undefined) clearTimeout(timer);
      if (wake.current === schedule) wake.current = null;
    };
  }, [contextKey, enabled, source]);

  const selected = sample?.source === source && sample.contextKey === contextKey ? sample : initial;
  return { rows: enabled ? selected?.rows : undefined, onComputePendingChange };
}
