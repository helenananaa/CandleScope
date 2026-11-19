import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { ChartSurfaceHandle } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { DrawingToolId, SavedDrawing } from "./drawingTypes.js";
import { exportDrawingDocument } from "./core/drawingCodec.js";
import "../../index.css";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }

/**
 * Real chart gestures, document history, export and IndexedDB for paths,
 * two-point arrows, parallel channels and rectangle zones.
 */
export async function checkAnnotationTools() {
  const host = document.createElement("div");
  host.style.cssText = "width:1000px;height:420px;position:relative;display:flex";
  document.body.append(host);
  let root = createRoot(host);
  const chart = createRef<ChartSurfaceHandle>();
  let tool: DrawingToolId | null = "line-arrow";
  let interval: "1m" | "5m" = "1m";
  const key = `qa-annotations-${crypto.randomUUID()}`;
  const store = new SeriesWindowStore({ seriesKey: key, intervalSeconds: 60 });
  const rows: KlineBar[] = Array.from({ length: 500 }, (_, i) => ({
    time: (1800000000 + i * 60) as KlineBar["time"], open: 100 + Math.sin(i / 9) * 4,
    high: 102 + Math.sin(i / 9) * 4, low: 98 + Math.sin(i / 9) * 4, close: 100.5 + Math.sin(i / 9) * 4, volume: 10,
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
  const api = () => chart.current?.getDrawingPaneApis?.().get("main");
  const saved = (): SavedDrawing[] => exportDrawingDocument(api()!.objects!.getObjectDocument()) ?? [];
  const byType = <T extends SavedDrawing["type"]>(type: T) => saved().find((item) => item.type === type) as Extract<SavedDrawing, { type: T }> | undefined;
  const render = () => root.render(<div data-qa="chart" style={{ width: 1000, height: 420, position: "relative", display: "flex" }}>
    <SingleChartPanes ref={chart}
      seriesStore={interval === "1m" ? store : coarse} symbol="FIXTURE" drawingKeyBase={key} interval={interval} datasetKey={`${key}:${interval}`}
      theme="dark" customBg="" upColor="#26a69a" downColor="#ef5350" subPanes={[]}
      drawingTool={tool} onDrawingToolChange={(value) => { tool = value; render(); }} drawingSnapEnabled={false} />
  </div>);
  const selectTool = async (next: DrawingToolId) => { tool = next; await act(async () => render()); await settle(); };
  const pointer = async (kind: string, x: number, y: number, buttons = 0) => {
    const box = host.querySelector('[data-qa="chart"] .chart-pane')!.getBoundingClientRect();
    const clientX = box.left + x, clientY = box.top + y;
    const target = document.elementFromPoint(clientX, clientY);
    assert(target, `Missing chart pointer target at ${x}, ${y}`);
    await act(async () => target.dispatchEvent(new PointerEvent(kind, { bubbles: true, cancelable: true, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0, buttons, clientX, clientY })));
    await settle();
  };
  const click = async (x: number, y: number) => { await pointer("pointermove", x, y); await pointer("pointerdown", x, y, 1); await pointer("pointerup", x, y); };
  try {
    await act(async () => render());
    await until(() => !!api()?.control?.isReady(), "Drawing control not ready");

    const press = async (key: string) => {
      await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });
      await settle();
    };
    await selectTool("path-line");
    await click(600, 240);
    await click(650, 215);
    await press("Escape");
    assert(saved().length === 0, "Esc committed a path draft");
    await selectTool("path-arrow");
    await click(600, 240);
    await click(600, 195);
    await click(675, 230);
    await press("Backspace");
    await click(450, 260);
    await click(450, 260);
    await pointer("dblclick", 450, 260);
    const path = byType("path");
    assert(path?.id && path.arrowEnd && path.dataPoints.length === 3, `Double-click must commit one terminal vertex: ${JSON.stringify(path)}, tool ${tool}`);
    const [a, b, c] = path.dataPoints;
    assert(a && b && c && a.time === b.time && a.price !== b.price && c.time! < b.time!, "Vertical and backward segments lost their source coordinates");
    const history = async (action: "undo" | "redo") => {
      await act(async () => { assert(api()?.control?.history(action), action + " rejected"); }); await settle();
    };
    await history("undo");
    assert(!byType("path"), "Creating a path must be one undo step");
    await history("redo");
    await selectTool("path-arrow");
    await pointer("pointerdown", 600, 195, 1);
    await pointer("pointermove", 620, 185, 1);
    await pointer("pointerup", 620, 185);
    const moved = byType("path")!;
    assert(moved.dataPoints[1]!.price !== b.price && moved.dataPoints[0]!.price === a.price && moved.dataPoints[2]!.price === c.price, "Dragging a vertex must only edit that vertex");
    await history("undo");
    assert(JSON.stringify(byType("path")) === JSON.stringify(path), "Undo did not restore the dragged vertex");
    const menuAction = async (x: number, y: number) => {
      await pointer("contextmenu", x, y);
      const item = document.querySelector<HTMLButtonElement>('[role="menu"] [role="menuitem"]');
      assert(item, "Missing path context menu");
      await act(async () => item.click()); await settle();
    };
    await menuAction(600, 218);
    assert(byType("path")?.dataPoints.length === 4, "Segment menu did not insert a vertex");
    await menuAction(600, 218);
    assert(JSON.stringify(byType("path")) === JSON.stringify(path), "Vertex menu did not remove the inserted vertex");
    await pointer("pointerdown", 525, 228, 1);
    await pointer("pointermove", 545, 244, 1);
    await pointer("pointerup", 545, 244);
    const translated = byType("path")!;
    assert(translated.dataPoints.every((p, i) => p.time !== path.dataPoints[i]?.time && p.price !== path.dataPoints[i]?.price),
      "Dragging a segment must translate every vertex");
    await history("undo");
    assert(JSON.stringify(byType("path")) === JSON.stringify(path), "Segment drag must undo in one step");
    await selectTool("path-line");
    await click(420, 265); await click(680, 295);
    await pointer("pointermove", 680, 240);
    await press("Enter");
    const plain = saved().filter(item => item.type === "path").find(item => item.id !== path.id);
    assert(plain?.type === "path" && !plain.arrowEnd && plain.dataPoints.length === 2, "Enter appended the hover or lost the plain variant");
    await pointer("contextmenu", 420, 265);
    assert(document.querySelector<HTMLButtonElement>('[role="menu"] [role="menuitem"]')?.disabled,
      "A two-point path must retain both endpoints");
    await press("Escape");
    await act(async () => { assert(api()?.objects?.updateObject(plain.id!, { arrowEnd: true }), "Arrow toggle rejected"); }); await settle();
    assert(saved().some(item => item.id === plain.id && item.type === "path" && item.arrowEnd), "Arrow style did not change");
    await selectTool("line-arrow");

    // Arrow: two clicks produce an ordinary segment with an arrowhead flag.
    await click(80, 330); await click(260, 250);
    await until(() => saved().length === 3, "Two clicks did not create an arrow");
    const arrow = byType("line");
    assert(arrow?.lineType === "line-segment" && arrow.arrowEnd === true, "Arrow was not saved as a flagged segment");

    // Channel: the second click must not commit; the third sets the width.
    await selectTool("channel-parallel");
    await click(320, 300); await click(700, 200);
    assert(saved().length === 3, "Channel committed after only two clicks");
    await click(510, 150);
    await until(() => saved().length === 4, "Third click did not create a channel");
    const channel = byType("channel");
    assert(channel?.dataPoints.length === 3, "Channel did not keep three anchors");
    const [start, end, through] = channel.dataPoints;
    assert(start && end && through && through.price > end.price, "Channel width anchor is not above the baseline");

    // Width handle: midpoint of the parallel line. Dragging it moves only anchor 2.
    const baselineYAtThrough = 300 + ((510 - 320) * (200 - 300)) / (700 - 320);
    const handle = { x: (320 + 700) / 2, y: (300 + 200) / 2 + (150 - baselineYAtThrough) };
    await selectTool("channel-parallel");
    await pointer("pointerdown", handle.x, handle.y, 1);
    await pointer("pointermove", handle.x, handle.y - 30, 1);
    await pointer("pointerup", handle.x, handle.y - 30);
    const widened = byType("channel");
    assert(widened && JSON.stringify(widened.dataPoints.slice(0, 2)) === JSON.stringify(channel.dataPoints.slice(0, 2)), "Width drag moved the baseline");
    assert(widened.dataPoints[2]!.price > through.price, "Width drag did not widen the channel");

    // Rectangle zone options go through the same property command path as the panel.
    await selectTool("shape-rectangle");
    await click(90, 60); await click(240, 140);
    await until(() => saved().length === 5, "Two clicks did not create a rectangle");
    const rectangle = byType("shape");
    assert(rectangle?.id, "Missing rectangle");
    await act(async () => { assert(api()?.objects?.updateObject(rectangle.id!, { extendRight: true, midline: true, priceLabels: true, label: "Demand" }), "Zone options rejected"); });
    await settle();
    const zone = byType("shape");
    assert(zone?.extendRight === true && zone.midline === true && zone.priceLabels === true && zone.label === "Demand", "Zone options did not persist");
    assert(JSON.stringify(zone.dataPoints) === JSON.stringify(rectangle.dataPoints), "Extending a zone rewrote its anchors");
    const before = saved();

    // Undo/redo, interval switch and IndexedDB remount must keep exact source payloads.
    await act(async () => { assert(api()?.control?.history("undo"), "Undo rejected"); }); await settle();
    assert(byType("shape")?.extendRight !== true, "Undo did not revert zone options");
    await act(async () => { assert(api()?.control?.history("redo"), "Redo rejected"); }); await settle();
    assert(JSON.stringify(saved()) === JSON.stringify(before), "Redo changed the drawings");
    await selectTool("cursor-default");
    interval = "5m"; await act(async () => render()); await settle();
    await until(() => !!api()?.control?.isReady(), "Interval switch did not settle");
    assert(JSON.stringify(saved()) === JSON.stringify(before), "Interval switch altered source coordinates");
    await act(async () => root.unmount()); await settle();
    root = createRoot(host); await act(async () => render());
    await until(() => saved().length === 5 && !!api()?.control?.isReady(), "Remount did not restore the drawings");
    assert(JSON.stringify(saved()) === JSON.stringify(before), "Restored drawings differ from saved source");
    const exported = await chart.current!.prepareExport();
    assert(exported, "Drawing export could not synchronize the new tools");
    await exported.restore();
    return { status: "PASS", saved: before, scope: "Real Chromium pointer creation (arrow, three-click channel, rectangle, plain/arrow paths), vertex edits, channel width drag, zone options, history, interval switch, IndexedDB remount and export" };
  } finally { await act(async () => root.unmount()); host.remove(); }
}
