import { useCallback, useEffect, useRef, useState } from "react";
import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { intervalTiles } from "../../utils/intervals.js";
import { resolveKlineSeriesIdentity } from "../market-data/klineSeriesIdentity.js";
import type { MarketDataManager } from "../market-data/manager/marketDataManager.js";
import type { MarketSeries } from "../market-data/marketDataTypes.js";
import { createManagedReplayHistoryReader, loadReplayBars } from "../trading-accounts/quickReplayData.js";
import { commitStudyView } from "./historyStudyCommit.js";
import { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import type { HistoryStudyView } from "./historyStudyTypes.js";

const hintKey = (owner: string) => `candlescope.history-study-active.v1:${owner}`;
function activeHint(owner: string) { try { return localStorage.getItem(hintKey(owner)) === "true"; } catch { return true; } }
function hint(owner: string, active: boolean) { localStorage.setItem(hintKey(owner), String(active)); }
type State = { owner: string; view: HistoryStudyView | null; playback: HistoryStudyPlayback | null; loading: boolean; busy: boolean; readRequired: boolean; error: unknown };

/** Publish only durably committed cursor changes. This keeps the visible
 * cursor recoverable even if the host exits during a pending write. Rapid
 * navigation is serialized and the last queued target wins; old responses
 * never paint an intermediate future prefix over a requested rewind. */
export function useHistoryStudy(owner: string, manager: MarketDataManager | null) {
  const [state, setState] = useState<State>(() => ({ owner, view: null, playback: null, loading: true, busy: false, readRequired: false, error: null }));
  const current = useRef(state);
  const epoch = useRef(0);
  const queue = useRef<{ cursorMs: number; active: boolean } | null>(null);
  const writing = useRef<Promise<boolean> | null>(null);
  const captures = useRef(new Set<AbortController>());
  const [reload, setReload] = useState(0);
  const publish = useCallback((update: Partial<State>) => {
    current.current = { ...current.current, ...update };
    setState(current.current);
  }, []);
  useEffect(() => {
    const token = ++epoch.current;
    const controller = new AbortController();
    const activeCaptures = captures.current;
    queue.current = null; writing.current = null;
    publish({ owner, view: null, playback: null, loading: true, busy: false, readRequired: false, error: null });
    if (!manager) { publish({ loading: false, readRequired: true }); return; }
    manager.historyStudy.read(owner, controller.signal).then(view => {
      if (token !== epoch.current) return;
      const playback = view.active && view.study && view.cursorMs !== null ? new HistoryStudyPlayback(view.study, view.cursorMs) : null;
      hint(owner, view.active);
      publish({ view, playback, loading: false });
    }).catch(error => { if (token === epoch.current && !controller.signal.aborted) publish({ error, loading: false, readRequired: true }); });
    return () => { epoch.current += 1; controller.abort(); queue.current = null;
      for (const request of activeCaptures) request.abort(); activeCaptures.clear(); };
  }, [manager, owner, publish, reload]);

  const move = useCallback((cursorMs: number, active = true): Promise<boolean> => {
    const state = current.current;
    if (!manager || !state.view?.study || !state.playback || state.owner !== owner || state.readRequired || state.loading
      || (state.busy && !writing.current)) return Promise.resolve(false);
    const token = epoch.current;
    const playback = state.playback!;
    queue.current = { cursorMs: Math.max(playback.minimumMs, Math.min(playback.maximumMs, cursorMs)), active };
    if (writing.current) return writing.current;
    publish({ busy: true, error: null });
    const task = Promise.resolve().then(async () => {
      try {
        while (queue.current && token === epoch.current) {
          const target = queue.current; queue.current = null;
          const view = current.current.view!;
          // Set the recovery mask before a durable mode transition can commit.
          if (target.active) hint(owner, true);
          const next = await commitStudyView({ before: view,
            write: async () => {
              const committed = await manager.historyStudy.move(owner, { studyId: view.study!.id,
                expectedRevision: view.revision, ...target });
              if (committed.studyId !== view.study!.id) throw new Error("Invalid study cursor response");
              return { ...view, revision: committed.revision, cursorMs: committed.cursorMs, active: committed.active };
            },
            read: () => manager.historyStudy.read(owner),
            matches: next => next.study?.id === view.study!.id
              && next.cursorMs === target.cursorMs && next.active === target.active,
            uncertain: () => publish({ readRequired: true }), current: () => token === epoch.current });
          if (token !== epoch.current) return false;
          current.current = { ...current.current, view: next };
          if (!queue.current) {
            playback.seek(next.cursorMs!);
            hint(owner, next.active);
            publish({ view: next, playback: next.active ? playback : null, readRequired: false, error: null });
          }
        }
        return true;
      } catch (error) {
        if (token === epoch.current) publish({ error, readRequired: true });
        return false;
      } finally {
        if (token === epoch.current) { writing.current = null; publish({ busy: false }); }
      }
    });
    writing.current = task;
    return task;
  }, [manager, owner, publish]);

  const capture = useCallback(async (series: MarketSeries, startMs: number, endMs: number, cursorMs: number, sourceInterval = series.interval) => {
    if (!manager || current.current.owner !== owner || current.current.loading || current.current.busy || current.current.readRequired) return false;
    const token = epoch.current, view = current.current.view;
    if (!view) { publish({ error: new Error("study_unavailable") }); return false; }
    const timeline = createIntervalTimeline(sourceInterval);
    const from = timeline?.floor(startMs / 1000), to = timeline?.floor((endMs - 1) / 1000);
    if (!timeline || !intervalTiles(sourceInterval, series.interval) || from == null || to == null || from > to || endMs > Date.now()) {
      publish({ error: new Error("study_range_invalid") }); return false;
    }
    let count = 0;
    for (let time = from; time <= to; time = timeline.next(time) ?? Infinity) {
      if (++count > 5000) { publish({ error: new Error("study_range_too_large") }); return false; }
    }
    const seriesWithIdentity = { exchange: series.exchange, marketType: series.marketType,
      symbol: series.symbol, interval: series.interval, ...resolveKlineSeriesIdentity(series.exchange, series) };
    const sourceSeries = { ...seriesWithIdentity, interval: sourceInterval };
    const retain = manager.cache.retain(sourceSeries, { from, to });
    const controller = new AbortController();
    captures.current.add(controller);
    publish({ busy: true, error: null });
    try {
      const reader = createManagedReplayHistoryReader(manager);
      const result = await loadReplayBars(sourceSeries, from, to, controller.signal, reader);
      if (token !== epoch.current) return false;
      // The common cache admits whole responses atomically. Capture one current
      // verified range, rather than stitching detached pages of different reads.
      const snapshot = manager.read(sourceSeries, { from, to, finalOnly: true });
      if (result.truncated || !snapshot.complete || !snapshot.rows.length || snapshot.rows.length > 5000) throw new Error("study_history_pending");
      const rows = snapshot.rows.map(row => ({ time: Number(row.time), open: row.open, high: row.high,
        low: row.low, close: row.close, volume: row.volume,
        ...Object.fromEntries(["quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "order_flow"]
          .filter(key => row[key] !== undefined).map(key => [key, row[key]])) }));
      hint(owner, true);
      const input = { id: `hs_${crypto.randomUUID().replaceAll("-", "")}`,
        series: seriesWithIdentity, ...(sourceInterval === series.interval ? {} : { sourceSeries }), rows, cursorMs: Math.max(rows[0]!.time * 1000,
          Math.min(timeline.next(rows.at(-1)!.time)! * 1000, cursorMs)), expectedRevision: view.revision };
      publish({ readRequired: true });
      const next = await commitStudyView({ before: view,
        write: () => manager.historyStudy.capture(owner, input, controller.signal),
        read: () => manager.historyStudy.read(owner, controller.signal),
        matches: next => next.active && next.study?.id === input.id && next.cursorMs === input.cursorMs,
        uncertain: () => publish({ readRequired: true }), current: () => token === epoch.current });
      if (token !== epoch.current) return false;
      publish({ view: next, playback: new HistoryStudyPlayback(next.study!, next.cursorMs!), busy: false, readRequired: false });
      return true;
    } catch (error) {
      if (token === epoch.current) publish({ error, busy: false });
      return false;
    } finally { retain.release(); controller.abort(); captures.current.delete(controller); }
  }, [manager, owner, publish]);

  const select = useCallback(async (studyId: string, action: "activate" | "remove") => {
    const view = current.current.view;
    if (!manager || !view || current.current.busy || current.current.readRequired || current.current.loading || current.current.owner !== owner) return false;
    const token = epoch.current;
    publish({ busy: true, readRequired: true, error: null });
    try {
      if (action === "activate") hint(owner, true);
      const write = () => manager.historyStudy.select(owner, action, { studyId, expectedRevision: view.revision });
      // A view read cannot prove that a non-current library item was deleted.
      // Unknown deletion acknowledgements therefore require an explicit reload.
      const next = action === "remove" ? await write() : await commitStudyView({ before: view, write,
        read: () => manager.historyStudy.read(owner),
        matches: next => next.active && next.study?.id === studyId,
        uncertain: () => publish({ readRequired: true }), current: () => token === epoch.current });
      if (token !== epoch.current) return false;
      hint(owner, next.active);
      publish({ view: next, playback: next.active && next.study ? new HistoryStudyPlayback(next.study, next.cursorMs!) : null, busy: false, readRequired: false });
      return true;
    } catch (error) { if (token === epoch.current) publish({ error, busy: false }); return false; }
  }, [manager, owner, publish]);

  const own = state.owner === owner ? state : null;
  return { ...own, playback: own?.readRequired ? null : own?.playback ?? null, capture, move, select, retry: () => setReload(value => value + 1),
    masked: Boolean(!own || own.loading || own.readRequired || own.view?.active || (!own.view && activeHint(owner))),
    active: Boolean(own?.view?.active), pending: !own || own.loading || own.readRequired, error: own?.error ?? null };
}
