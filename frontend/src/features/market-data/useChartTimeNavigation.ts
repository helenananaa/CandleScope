import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartLinkCoordinator } from "../chart-workspace/chartLinkCoordinator.js";
import type { MarketDataRuntimeContract } from "./marketDataRuntimeContract.js";
import type { ChartTimeSeekResult } from "./chartTimeNavigation.js";
import {
  readLastViewed,
  relativeJumpTarget,
  RelativeJumpTracker,
  visibleCenterTimeMs,
  writeLastViewed,
  type ChartTimeOutcomes,
  type ChartTimeShortcuts,
} from "./chartTimeShortcuts.js";

const LATEST_ATTEMPTS = 10;
const LATEST_RETRY_MS = 300;

export function useChartTimeNavigation({
  active, enabled, cellId, workspaceId, sessionKey, marketData, surface, links, ceilingMs = null, lastViewedKey,
}: {
  active: boolean; enabled: boolean; cellId: string; workspaceId: string; sessionKey: string;
  marketData: { actions: Pick<MarketDataRuntimeContract["actions"], "seekToTime"> }; surface: ChartSurfaceActions; links: ChartLinkCoordinator | null;
  /** Latest time the shortcuts may reach, epoch ms; null means now. Replay passes its revealed boundary. */
  ceilingMs?: number | null;
  /** The series "Last viewed" belongs to; defaults to `sessionKey`. Replay leaves its moving clock out. */
  lastViewedKey?: string;
}) {
  const [open, setOpen] = useState(false);
  const sequence = useRef(0);
  const [tracker] = useState(() => new RelativeJumpTracker());
  // Where the view was before the last jump, for "Last viewed" (PL-8). Kept
  // across reloads for the same chart slot and series.
  const slot = `${workspaceId}\u0000${cellId}`;
  const viewKey = lastViewedKey ?? sessionKey;
  const [lastViewed, setLastViewed] = useState(() => ({ slot, key: viewKey, timeMs: readLastViewed(slot, viewKey) }));
  useEffect(() => {
    setLastViewed((current) => current.slot === slot && current.key === viewKey
      ? current : { slot, key: viewKey, timeMs: readLastViewed(slot, viewKey) });
  }, [slot, viewKey]);
  const lastViewedMs = lastViewed.slot === slot && lastViewed.key === viewKey ? lastViewed.timeMs : null;
  const remember = useCallback((timeMs: number | null) => {
    if (timeMs === null) return;
    writeLastViewed(slot, viewKey, timeMs);
    setLastViewed({ slot, key: viewKey, timeMs });
  }, [slot, viewKey]);
  const seek = marketData.actions.seekToTime;
  const navigate = useCallback(async (requestedTimeMs: number): Promise<ChartTimeSeekResult> => {
    const ticket = ++sequence.current;
    const viewport = surface.getVisibleRange() ?? undefined;
    if (!enabled || !seek) return { status: "unavailable", requestedTimeMs };
    const result = await seek(requestedTimeMs);
    if (result.status !== "located") return result;
    // A dense workspace may defer its display projection beyond the next frame.
    // The surface accepts centering only after it has painted this store version.
    return new Promise<ChartTimeSeekResult>((resolve) => {
      let settled = false, unsubscribe = () => {};
      const finish = (value: ChartTimeSeekResult) => {
        if (settled) return;
        settled = true; clearTimeout(timeout); unsubscribe(); resolve(value);
      };
      const timeout = setTimeout(() => finish({
        status: ticket === sequence.current ? "unavailable" : "superseded", requestedTimeMs,
      }), 3_000);
      const position = () => {
        if (ticket !== sequence.current) finish({ status: "superseded", requestedTimeMs });
        else if (surface.centerVisibleTime(result.actualTimeMs / 1_000, viewport)) finish(result);
      };
      unsubscribe = surface.subscribeLinkedViewportReady(position);
      if (settled) unsubscribe();
      else position();
    });
  }, [enabled, seek, surface]);
  useEffect(() => {
    if (!enabled || !seek || !links) return undefined;
    return links.registerTimeNavigator(cellId, navigate, workspaceId);
  }, [cellId, enabled, links, navigate, seek, workspaceId]);
  useEffect(() => () => { sequence.current += 1; tracker.reset(); }, [sessionKey, enabled, workspaceId, cellId, seek, surface, tracker]);
  useEffect(() => {
    if (!active || !enabled || !seek) return undefined;
    const keydown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat || event.isComposing || !event.altKey
        || event.ctrlKey || event.metaKey || event.shiftKey || event.code !== "KeyG") return;
      const element = event.target instanceof Element ? event.target : null;
      if (element?.closest("input,textarea,select,[contenteditable=true],[role=dialog]")) return;
      event.preventDefault(); setOpen(true);
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [active, enabled, seek]);
  const centerTimeMs = useCallback(() => visibleCenterTimeMs(surface.getVisibleRange()?.time as { from?: unknown; to?: unknown } | null), [surface]);
  const go = useCallback(async (timeMs: number): Promise<ChartTimeOutcomes> => {
    const before = centerTimeMs();
    const outcomes = await (links ? links.seekToTime(cellId, timeMs)
      : navigate(timeMs).then(result => [{ cellId, result }]));
    if (outcomes.find((item) => item.cellId === cellId)?.result.status === "located") remember(before);
    return outcomes;
  }, [cellId, centerTimeMs, links, navigate, remember]);
  const submit = useCallback((timeMs: number) => { tracker.reset(); return go(timeMs); }, [go, tracker]);
  const shortcuts = useMemo<ChartTimeShortcuts>(() => ({
    centerTimeMs,
    jumpBy: (seconds) => {
      const target = relativeJumpTarget(tracker.base(centerTimeMs()), seconds, ceilingMs ?? Date.now());
      if (target === null) return null;
      const settle = tracker.begin(target);
      const pending = go(target);
      void pending.then(settle, settle);
      return pending;
    },
    // The chart refuses to restore its latest window while it is loading
    // history (e.g. just after First loaded bar). Retry for a few seconds;
    // any newer navigation cancels.
    latest: async () => {
      tracker.reset();
      const ticket = ++sequence.current;
      const before = centerTimeMs();
      for (let attempt = 0; attempt < LATEST_ATTEMPTS; attempt += 1) {
        if (attempt > 0) await new Promise((resolve) => { setTimeout(resolve, LATEST_RETRY_MS); });
        if (ticket !== sequence.current) return null;
        if (await surface.returnToLatest()) {
          remember(before);
          return ceilingMs ?? Date.now();
        }
      }
      return null;
    },
    firstLoaded: () => {
      tracker.reset();
      sequence.current += 1;
      const before = centerTimeMs();
      const first = surface.showFirstLoadedBar();
      if (first === null) return null;
      remember(before);
      return first * 1000;
    },
    lastViewedMs,
    jumpLastViewed: () => (lastViewedMs === null ? null : submit(lastViewedMs)),
  }), [ceilingMs, centerTimeMs, go, lastViewedMs, remember, submit, surface, tracker]);
  return { open: open && active && enabled, setOpen, submit, shortcuts, available: enabled && !!seek };
}
