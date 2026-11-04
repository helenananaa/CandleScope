import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { renderExportImage } from "../export/exportService.js";
import type { ReplayNoteCaptureSave, ReplayNoteContext } from "./replayNotes.js";
import { t } from "../../i18n/index.js";

export interface ReplayNoteChartState {
  ready: boolean; seriesKey: string; sourceVersion: number; interval: string; chartType: string;
  contextKey: string;
}
const same = (a: ReplayNoteChartState, b: ReplayNoteChartState) => a.ready && b.ready && a.seriesKey === b.seriesKey
  && a.sourceVersion === b.sourceVersion && a.interval === b.interval && a.chartType === b.chartType && a.contextKey === b.contextKey;
const frame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
export async function captureReplayNoteChart(surface: Pick<ChartSurfaceActions, "prepareExport" | "getExportSnapshot">,
  context: ReplayNoteContext, current: () => ReplayNoteChartState): Promise<Omit<ReplayNoteCaptureSave, "id" | "context">> {
  const initial = current();
  const invalid = () => new Error(t("replay.notes.captureRequiresReady"));
  if (!initial.ready) throw invalid();
  await frame(); await frame();
  if (!same(initial, current())) throw invalid();
  let lease = await surface.prepareExport({ hideDrawings: false });
  try {
    if (!same(initial, current())) throw invalid();
    const snapshot = surface.getExportSnapshot(), source = snapshot?.sourceWindow;
    if (!snapshot?.rootElement || !source?.current || source.seriesKey !== initial.seriesKey
      || source.version !== initial.sourceVersion || !snapshot.rootElement.querySelector("canvas")) throw invalid();
    const result = await renderExportImage(snapshot, { scope: "chart", format: "png", scale: 1,
      hideDrawings: false, includeContext: false, watermarkEnabled: false }, {
      afterCapture: async () => {
        if (lease) {
          if (!await lease.revalidate()) throw invalid();
          await lease.restore(); lease = null;
        }
        if (!same(initial, current())) throw invalid();
      },
    });
    if (!same(initial, current()) || result.blob.size > 2 * 1024 * 1024 || result.width > 4096 || result.height > 4096 || result.mimeType !== "image/png") throw invalid();
    const image = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error ?? invalid());
      reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(invalid());
      reader.readAsDataURL(result.blob);
    });
    if (!same(initial, current())) throw invalid();
    return { image, capturedContext: { ...context }, chart: { interval: initial.interval, chartType: initial.chartType,
      seriesKey: initial.seriesKey, sourceVersion: initial.sourceVersion } };
  } finally { await lease?.restore(); }
}
