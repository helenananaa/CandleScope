import { captureStableSeries } from "../market-data/window/stableSeriesSnapshot.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { SeriesWindowView } from "../market-data/window/seriesWindowView.js";
import { INDICATOR_HISTORY_LIMIT } from "./indicatorComputeRuntime.js";

/** Sample the source contract, whose O(1) tick deliberately retains array identity.
 * Never publish a new tick generation while bounded compute is still running:
 * otherwise a continuous feed could cancel every attempt before its timeout.
 */
export function useFrontendScriptWindow(
  source: SeriesWindowView | null,
  enabled: boolean,
  contextKey: string,
) {
  const capture = useCallback(() => {
    if (!source) return null;
    const input = captureStableSeries(source, { limit: INDICATOR_HISTORY_LIMIT });
    // Consumers only read this frozen array; retain the legacy mutable TS
    // signature at the controller boundary, without retaining a live alias.
    return { source, contextKey, version: input.version, input, rows: input.rows as KlineBar[] };
  }, [contextKey, source]);
  const initial = useMemo(() => enabled ? capture() : null, [capture, enabled]);
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
        && previous.version === source.version ? previous : capture());
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
      if (delta.type === "tick" && delta.appended !== true && delta.bar?.is_closed !== true) {
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
  }, [capture, contextKey, enabled, source]);

  const selected = sample?.source === source && sample.contextKey === contextKey ? sample : initial;
  return { rows: enabled ? selected?.rows : undefined, inputSnapshot: enabled ? selected?.input : undefined, onComputePendingChange };
}
