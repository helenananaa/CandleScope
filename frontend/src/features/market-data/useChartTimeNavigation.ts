import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartLinkCoordinator } from "../chart-workspace/chartLinkCoordinator.js";
import type { MarketDataRuntimeContract } from "./marketDataRuntimeContract.js";
import type { ChartTimeSeekResult } from "./chartTimeNavigation.js";
import { relativeJumpTarget, visibleCenterTimeMs, type ChartTimeOutcomes, type ChartTimeShortcuts } from "./chartTimeShortcuts.js";

export function useChartTimeNavigation({
  active, enabled, cellId, workspaceId, sessionKey, marketData, surface, links,
}: {
  active: boolean; enabled: boolean; cellId: string; workspaceId: string; sessionKey: string;
  marketData: { actions: Pick<MarketDataRuntimeContract["actions"], "seekToTime"> }; surface: ChartSurfaceActions; links: ChartLinkCoordinator | null;
}) {
  const [open, setOpen] = useState(false);
  const sequence = useRef(0);
  // Where the view was before the last jump, for "Last viewed" (PL-8).
  const [lastViewedMs, setLastViewedMs] = useState<number | null>(null);
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
  useEffect(() => () => { sequence.current += 1; }, [sessionKey, enabled, workspaceId, cellId, seek, surface]);
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
  const submit = useCallback(async (timeMs: number): Promise<ChartTimeOutcomes> => {
    const before = centerTimeMs();
    const outcomes = await (links ? links.seekToTime(cellId, timeMs)
      : navigate(timeMs).then(result => [{ cellId, result }]));
    if (before !== null && outcomes.find((item) => item.cellId === cellId)?.result.status === "located") setLastViewedMs(before);
    return outcomes;
  }, [cellId, centerTimeMs, links, navigate]);
  // A new market or interval has its own history; an old position means nothing there.
  useEffect(() => { setLastViewedMs(null); }, [sessionKey, workspaceId, cellId]);
  const shortcuts = useMemo<ChartTimeShortcuts>(() => ({
    centerTimeMs,
    jumpBy: (seconds) => {
      const target = relativeJumpTarget(centerTimeMs(), seconds, Date.now());
      return target === null ? null : submit(target);
    },
    latest: () => {
      const before = centerTimeMs();
      const done = surface.returnToLatest();
      if (done && before !== null) setLastViewedMs(before);
      return done;
    },
    firstLoaded: () => {
      const before = centerTimeMs();
      const first = surface.showFirstLoadedBar();
      if (first === null) return null;
      if (before !== null) setLastViewedMs(before);
      return first * 1000;
    },
    lastViewedMs,
    jumpLastViewed: () => (lastViewedMs === null ? null : submit(lastViewedMs)),
  }), [centerTimeMs, lastViewedMs, submit, surface]);
  return { open: open && active && enabled, setOpen, submit, shortcuts, available: enabled && !!seek };
}
