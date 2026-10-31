import { captureStableSeries } from "../market-data/window/stableSeriesSnapshot.js";
import type { KlineBar, MarketSeries } from "../market-data/marketDataTypes.js";
import type { IndicatorInputRanges } from "./indicatorInputRanges.js";
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
  binding?: { inputs: IndicatorInputRanges; series: MarketSeries },
) {
  const capture = useCallback(() => {
    if (!source) return null;
    const window = captureStableSeries(source, { limit: INDICATOR_HISTORY_LIMIT });
    const first = window.rows[0], last = window.rows.at(-1);
    const range = first && last ? { from: Number(first.time), to: Number(last.time) } : undefined;
    const shared = binding && range ? binding.inputs.read(binding.series, range) : undefined;
    // The chart declares only its bounded input axis. Shared immutable facts
    // supply values, including corrections observed by another consumer.
    const completeAxis = !shared || (shared.rows.length === window.rows.length
      && shared.rows.every((row, i) => row.time === window.rows[i]!.time));
    const input = shared ? { ...shared, state: window.state,
      rows: completeAxis ? shared.rows : Object.freeze([]),
      isCurrent: (policy?: Parameters<typeof window.isCurrent>[0]) => completeAxis
        && window.isCurrent(policy) && shared.isCurrent(policy),
    } : window;
    // Consumers only read this frozen array; retain the legacy mutable TS
    // signature at the controller boundary, without retaining a live alias.
    return { source, contextKey, binding, range, windowVersion: window.version, version: input.version, input, rows: input.rows as KlineBar[] };
  }, [binding, contextKey, source]);
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
    let releaseRange: (() => void) | undefined;
    let rangeKey: string | undefined;
    const publish = () => {
      dirty = false;
      const next = capture();
      const nextKey = next?.range ? JSON.stringify(next.range) : undefined;
      if (nextKey !== rangeKey) {
        releaseRange?.();
        rangeKey = nextKey;
        releaseRange = binding && next?.range ? binding.inputs.subscribe(binding.series, next.range, change => {
          if (change.source === "realtime" && change.eventType === "bar.updated" && change.rows.every(row => row.is_closed === false)) {
            dirty = true; schedule();
          } else publish();
        }) : undefined;
      }
      setSample(previous => previous?.source === source && previous.contextKey === contextKey && previous.binding === binding
        && previous.windowVersion === next?.windowVersion && previous.version === next?.version
        && previous.input.isCurrent() ? previous : next);
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
      releaseRange?.();
      if (timer !== undefined) clearTimeout(timer);
      if (wake.current === schedule) wake.current = null;
    };
  }, [binding, capture, contextKey, enabled, source]);

  const selected = sample?.source === source && sample.contextKey === contextKey && sample.binding === binding ? sample : initial;
  return { rows: enabled ? selected?.rows : undefined, inputSnapshot: enabled ? selected?.input : undefined, onComputePendingChange };
}
