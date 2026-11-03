import { useCallback, useEffect, useRef, useState } from "react";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartLinkCoordinator } from "../chart-workspace/chartLinkCoordinator.js";
import type { MarketDataRuntimeContract } from "./marketDataRuntimeContract.js";
import type { ChartTimeSeekResult } from "./chartTimeNavigation.js";

export function useChartTimeNavigation({
  active, enabled, cellId, workspaceId, sessionKey, marketData, surface, links,
}: {
  active: boolean; enabled: boolean; cellId: string; workspaceId: string; sessionKey: string;
  marketData: { actions: Pick<MarketDataRuntimeContract["actions"], "seekToTime"> }; surface: ChartSurfaceActions; links: ChartLinkCoordinator;
}) {
  const [open, setOpen] = useState(false);
  const sequence = useRef(0);
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
    if (!enabled || !seek) return undefined;
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
  const submit = useCallback((timeMs: number) => links.seekToTime(cellId, timeMs), [cellId, links]);
  return { open: open && active && enabled, setOpen, submit, available: enabled && !!seek };
}
