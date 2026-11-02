import type { ChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { command, type ControlCommandGroup } from "../app-control/commandRegistry.js";
import { choice, empty, nullable, number, object } from "../app-control/commandSchema.js";
import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import type { HistoryStudyDataManager } from "./historyStudyDataManager.js";

export function historyStudyCommands(input: {
  cellId: string; playback: HistoryStudyPlayback; revision: number; busy: boolean; playing: boolean;
  renderedVersion: number; indicators: IndicatorRuntime; surface: ChartSurfaceRuntime;
  data: HistoryStudyDataManager; move(cursorMs: number, active?: boolean): Promise<boolean>; play(value: boolean): void;
  signal?(): AbortSignal | null;
}): ControlCommandGroup {
  const { playback, surface, indicators } = input;
  const current = () => input.renderedVersion === Number(playback.store.version);
  const outputReady = () => current() && !input.busy && !indicators.status.computing;
  const boundedTime = (seconds: number) => {
    const first = playback.store.first()?.time, last = playback.store.last()?.time;
    if (first === undefined || last === undefined || seconds < first || seconds > last) throw new Error("STUDY_TIME_NOT_REVEALED");
  };
  const move = async (target: number, active = true) => {
    if (target < playback.minimumMs || target > playback.maximumMs) throw new Error("STUDY_TIME_OUTSIDE_CAPTURE");
    input.play(false);
    if (!await input.move(target, active)) throw new Error("STUDY_COMMIT_FAILED");
    return { studyId: playback.input.id, cursorMs: playback.cursorMs, active };
  };
  return {
    id: `study:${input.cellId}`, title: `Historical study ${input.cellId}: revealed data and committed cursor`,
    context: () => ({ mode: "history-study", studyId: playback.input.id, series: playback.input.series,
      sourceSeries: playback.input.sourceSeries ?? playback.input.series,
      cursorMs: playback.cursorMs, revision: input.revision, version: Number(playback.store.version),
      ready: outputReady(), playing: input.playing }),
    snapshot: () => ({ mode: "history-study", studyId: playback.input.id, series: playback.input.series,
      sourceSeries: playback.input.sourceSeries ?? playback.input.series, missingBuckets: playback.missingBuckets,
      cursorMs: playback.cursorMs, revision: input.revision, capturedAtMs: playback.input.capturedAtMs,
      barCount: playback.store.barCount, firstTime: playback.store.first()?.time ?? null, lastTime: playback.store.last()?.time ?? null,
      boundsMs: { from: playback.minimumMs, to: playback.maximumMs }, busy: input.busy,
      computing: !outputReady(), playing: input.playing, visibleRange: surface.actions.getVisibleRange(),
      indicators: indicators.view.activeIndicators.map(({ id, name, error, lines }) => ({ id, name, error,
        outputPoints: outputReady() ? lines?.reduce((n, line) => n + line.data.filter(point => point.time <= (playback.store.last()?.time ?? -1)).length, 0) ?? 0 : 0 })) }),
    commands: [
      command("bars", "Read a bounded tail of revealed study candles only; never the retained future input or live source.",
        object({ limit: number(1, 500, true) }), ({ limit }) => playback.store.snapshot().slice(-limit), { readOnly: true }),
      command("indicatorOutputs", "Read bounded output from the committed revealed prefix. Wait for computing=false after a cursor change.",
        object({ limit: number(1, 500, true) }), ({ limit }) => {
          if (!outputReady()) throw new Error("STUDY_INDICATORS_PENDING");
          const cut = playback.store.last()?.time ?? -1;
          return indicators.view.activeIndicators.map(item => ({ id: item.id, error: item.error,
            lines: item.lines?.map(line => ({ ...line, data: line.data.filter(point => point.time <= cut).slice(-limit) })) ?? [] }));
        }, { readOnly: true, available: outputReady }),
      command("notes", "Read review annotations at the committed study cursor. A rewind rejects a late response.", empty, async () => {
        const cursor = playback.cursorMs, version = Number(playback.store.version);
        const signal = input.signal?.();
        if (signal === null) throw new Error("STUDY_UNAVAILABLE");
        const result = await input.data.notes(playback.input.id, cursor, signal);
        if (cursor !== playback.cursorMs || version !== Number(playback.store.version)
          || signal?.aborted || signal !== input.signal?.()) throw new Error("STUDY_CONTEXT_CHANGED");
        return result;
      }, { readOnly: true }),
      command("seekCursor", "Change replay time in epoch milliseconds, commit it, then recompute chart/indicators/notes. This is not viewport navigation.",
        object({ timeMs: number(0, Number.MAX_SAFE_INTEGER, true) }), ({ timeMs }) => move(timeMs), { available: () => !input.busy }),
      command("step", "Advance or rewind to the next/previous saved candle close through the same durable action as the UI.",
        object({ direction: choice(["backward", "forward"]) }), ({ direction }) => move(playback.stepTarget(direction === "forward" ? 1 : -1)), { available: () => !input.busy }),
      command("play", "Start this study's local playback; restarting the application remains paused at the saved cursor.", empty, () => input.play(true), { available: () => !input.busy }),
      command("pause", "Pause only this study.", empty, () => input.play(false)),
      command("exit", "Save and exit this study, releasing its view resources and restoring this chart's live commands.", empty, () => move(playback.cursorMs, false), { available: () => !input.busy }),
      command("visibleTimeRange", "Move only the study viewport within revealed history; leave its cursor unchanged. Bounds are epoch seconds.",
        object({ from: number(0), to: number(0) }), ({ from, to }) => {
          boundedTime(from); boundedTime(to);
          if (from >= to || !surface.actions.setLinkedVisibleTimeRange({ from, to })) throw new Error("VIEWPORT_UNAVAILABLE");
        }),
      command("timeAnchor", "Center the visible study viewport on a revealed epoch-second timestamp without changing replay time.",
        object({ time: number(0) }), ({ time }) => {
          boundedTime(time);
          if (!surface.actions.centerVisibleTime(time, surface.actions.getVisibleRange() ?? undefined)) throw new Error("VIEWPORT_UNAVAILABLE");
        }),
      command("crosshair", "Set or clear the crosshair within revealed study data, using epoch seconds.",
        object({ time: nullable(number(0)) }), ({ time }) => {
          if (time !== null) boundedTime(time);
          return surface.actions.setLinkedCrosshairTime(time);
        }),
    ],
  };
}
