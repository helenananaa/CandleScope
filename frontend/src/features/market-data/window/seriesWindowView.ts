import type { SeriesWindowStore } from "./seriesWindowStore.js";
import type { WindowDelta } from "../klineContracts.js";

export interface WindowCommitState extends Readonly<Record<string, unknown>> {
  readonly windowId: string;
  readonly sessionEpoch: number;
  readonly seriesKey: string;
  readonly commitRevision: number;
  readonly dataRevision: number;
  readonly axisRevision: number;
  readonly bars: number;
  readonly firstTime: number | null;
  readonly lastTime: number | null;
}

/** Source-neutral synchronous reader shared by live, replay and static charts. */
export type SeriesWindowView = Readonly<Pick<SeriesWindowStore,
  "seriesKey" | "maxBars" | "intervalSeconds" | "version" | "axisRevision"
  | "rightTruncated" | "barCount" | "segments" | "isEmpty" | "snapshot"
  | "hasTime" | "getByTime" | "indexOfTime" | "first" | "last" | "coverage" | "describe" | "timeSet"
>> & {
  readonly commitState?: WindowCommitState;
  subscribe(listener: (delta: WindowDelta, reader: SeriesWindowView) => void): () => boolean;
};
