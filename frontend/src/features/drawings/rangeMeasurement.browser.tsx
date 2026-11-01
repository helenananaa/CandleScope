import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { ChartSurfaceHandle } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { DrawingToolId } from "./drawingTypes.js";
import { exportDrawingDocument } from "./core/drawingCodec.js";
import { measureDrawingRange } from "./rangeMeasurement.js";
import "../../index.css";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const measurementColor = "#33aaee";

/** Real charts, pointer handlers and IndexedDB; no replacement drawing engine. */
export async function checkRangeMeasurements() {
  const controls = document.createElement("div");
  controls.className = "chart-cell-drawing-controls";
  controls.style.cssText = "width:500px;height:28px;display:flex";
  document.body.append(controls);
  const host = document.createElement("div");
  host.style.cssText = "width:1000px;height:420px;position:relative;display:flex";
  document.body.append(host);
  let root = createRoot(host);
  const left = createRef<ChartSurfaceHandle>(), right = createRef<ChartSurfaceHandle>();
  let tool: DrawingToolId | null = "measure-price-time";
  let interval: "1m" | "5m" = "1m";
  const key = `qa-ruler-${crypto.randomUUID()}`;
  const store = new SeriesWindowStore({ seriesKey: key, intervalSeconds: 60 });
  const rows: KlineBar[] = Array.from({ length: 500 }, (_, i) => ({
    time: (1800000000 + i * 60) as KlineBar["time"], open: 100 + i / 10,
    high: 101 + i / 10, low: 99 + i / 10, close: 100.5 + i / 10, volume: 10,
  }));
  store.replace(rows);
  const coarse = new SeriesWindowStore({ seriesKey: `${key}:5m`, intervalSeconds: 300 });
  coarse.replace(Array.from({ length: 100 }, (_, i) => {
    const group = rows.slice(i * 5, i * 5 + 5);
    return { ...group[0]!, high: Math.max(...group.map((bar) => bar.high!)), low: Math.min(...group.map((bar) => bar.low!)), close: group[4]!.close, volume: 50 };
  }));
  const settle = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 100)); }); };
  const until = async (check: () => boolean, message: string) => {
    for (let i = 0; i < 80; i++) { if (check()) return; await settle(); }
    throw new Error(message);
  };
  const api = () => left.current?.getDrawingPaneApis?.().get("main");
  const objects = () => api()?.objects?.getObjectDocument();
  const render = () => root.render(<>
    <div data-qa="left" style={{ width: 500, height: 420, position: "relative", display: "flex" }}><SingleChartPanes ref={left}
      drawingControlsHost={controls}
      seriesStore={interval === "1m" ? store : coarse} symbol="FIXTURE" drawingKeyBase={`${key}:left`} interval={interval} datasetKey={`${key}:${interval}`}
      theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000" subPanes={[]}
      drawingTool={tool} onDrawingToolChange={(value) => { tool = value; render(); }} drawingSnapEnabled={false} /></div>
    <div data-qa="right" style={{ width: 500, height: 420, position: "relative", display: "flex" }}><SingleChartPanes ref={right}
      seriesStore={store} symbol="FIXTURE" drawingKeyBase={`${key}:right`} interval="1m" datasetKey={key}
      theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000" subPanes={[]} drawingTool="measure-time" /></div>
  </>);
  const pointer = async (kind: string, x: number, y: number, buttons = 0) => {
    const box = host.querySelector('[data-qa="left"] .chart-pane')!.getBoundingClientRect();
    const clientX = box.left + x, clientY = box.top + y;
    const target = document.elementFromPoint(clientX, clientY);
    assert(target, "Missing chart pointer target");
    await act(async () => target.dispatchEvent(new PointerEvent(kind, { bubbles: true, cancelable: true, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0, buttons, clientX, clientY })));
    await settle();
  };
  const click = async (x: number, y: number) => { await pointer("pointermove", x, y); await pointer("pointerdown", x, y, 1); await pointer("pointerup", x, y); };
  try {
    await act(async () => render());
    await until(() => !!api()?.control?.isReady(), "Drawing control not ready");
    await click(180, 220); await click(340, 120);
    await until(() => objects()?.entities.size === 1, "Two clicks did not create a ruler");
    const trigger = controls.querySelector<HTMLButtonElement>(".drawing-object-trigger");
    assert(trigger, "Drawing objects were not mounted in the owning header");
    assert(trigger.getBoundingClientRect().bottom <= host.getBoundingClientRect().top, "Permanent object control overlaps the plot");
    assert(!host.querySelector('[data-qa="left"] .drawing-object-trigger'), "Duplicate object control remains over the plot");
    await act(async () => trigger.click()); await settle();
    assert(controls.querySelector("dialog")?.open, "Portalled object list did not open");
    await act(async () => controls.querySelector<HTMLButtonElement>(".drawing-properties-header button")!.click()); await settle();
    assert(globalThis.document.activeElement === trigger, "Object list did not restore keyboard focus to header");
    let document = objects()!;
    const created = exportDrawingDocument(document)!;
    const drawing = created[0]; assert(drawing?.type === "range-measure", "Wrong saved drawing kind");
    const measurement = measureDrawingRange(drawing.dataPoints); assert(measurement, "Missing source measurement");
    assert(right.current?.getDrawingPaneApis?.().get("main")?.objects?.getObjectDocument().entities.size === 0, "Ruler leaked to sibling chart");
    await act(async () => { assert(api()?.control?.history("undo"), "Undo rejected"); }); await settle();
    assert(objects()?.entities.size === 0, "Undo did not remove ruler");
    await act(async () => { assert(api()?.control?.history("redo"), "Redo rejected"); }); await settle();
    assert(JSON.stringify(exportDrawingDocument(objects()!)) === JSON.stringify(created), "Redo changed source anchors");
    await act(async () => { assert(api()?.objects?.updateObject(drawing.id!, { color: measurementColor, locked: true }), "Style/lock rejected"); }); await settle();
    const saved = exportDrawingDocument(objects()!)!;
    assert(saved[0]?.locked === true, "Lock did not persist");
    // Geometry locking must also hold through the actual pointer handlers.
    tool = "measure-price-time"; await act(async () => render()); await settle();
    await pointer("pointerdown", 180, 220, 1); await pointer("pointermove", 200, 240, 1); await pointer("pointerup", 200, 240);
    assert(JSON.stringify(exportDrawingDocument(objects()!)) === JSON.stringify(saved), "Pointer movement changed a locked ruler");
    interval = "5m"; await act(async () => render()); await settle();
    await until(() => !!api()?.control?.isReady(), "Interval switch did not settle");
    assert(JSON.stringify(exportDrawingDocument(objects()!)) === JSON.stringify(saved), "Interval switch altered source coordinates");
    await act(async () => root.unmount()); await settle();
    root = createRoot(host); await act(async () => render());
    await until(() => objects()?.entities.size === 1 && !!api()?.control?.isReady(), "Remount did not restore saved ruler");
    document = objects()!;
    assert(JSON.stringify(exportDrawingDocument(document)) === JSON.stringify(saved), "Restored ruler differs from saved source");
    const exported = await left.current!.prepareExport();
    assert(exported, "Drawing export could not synchronize the ruler");
    await exported.restore();
    await act(async () => { assert(api()?.objects?.deleteObject(drawing.id!), "Delete rejected"); }); await settle();
    assert(objects()?.entities.size === 0, "Delete did not remove ruler");
    return { status: "PASS", created, saved, measurement, scope: "Real Chromium pointer creation, document history, style/lock, interval switch, IndexedDB remount, export and delete" };
  } finally { await act(async () => root.unmount()); host.remove(); controls.remove(); }
}
