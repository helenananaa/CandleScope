import assert from "node:assert/strict";
import test from "node:test";
import {
  ensurePanePlaceholderSeries,
  resolvePaneHeightLayout,
  trimPanePlaceholderSeries,
  type PanePlaceholderState,
} from "../singleChartPaneLayout.js";
import { buildPaneDescriptors } from "../singleChartIndicatorPanes.js";
import {
  applyPanePriceScaleOptions,
  resolvePanePriceScaleMenu,
  type PriceScaleOptionsPatch,
} from "../panePriceScaleMenuModel.js";
import { buildPanePointerLayout } from "../panePointerModel.js";
import type { AxisTime } from "../../features/chart-representation/chartRepresentationTypes.js";
import { mustBeDefined, structuralMock } from "../../test/testHelpers.js";

type AdapterChart = NonNullable<Parameters<typeof ensurePanePlaceholderSeries>[0]>;

function placeholderFixture() {
  const series: { paneIndex: number; data: { time: AxisTime; value: number }[][] }[] = [];
  const removed: unknown[] = [];
  const chart = structuralMock<AdapterChart>({
    panes: () => [{}, {}, {}],
    addSeries: (_kind: unknown, _options: unknown, paneIndex: number) => {
      const entry = {
        paneIndex,
        data: [] as { time: AxisTime; value: number }[][],
        getPane: () => ({ paneIndex: () => entry.paneIndex }),
        setData: (data: { time: AxisTime; value: number }[]) => entry.data.push(data),
      };
      series.push(entry);
      return entry;
    },
    removeSeries: (entry: unknown) => removed.push(entry),
  });
  const state: { current: PanePlaceholderState } = { current: { chart: null, seriesByPane: new Map() } };
  return { chart, state, series, removed };
}

test("placeholder anchors update their source lineage without rebuilding series", () => {
  const { chart, state, series } = placeholderFixture();
  const first = { order: 0, sourceTime: 10, sourceOrdinal: 0 };
  ensurePanePlaceholderSeries(chart, state, 2, first);
  ensurePanePlaceholderSeries(chart, state, 2, first);
  assert.equal(series.length, 2);
  assert.deepEqual(series.map((entry) => entry.data.length), [1, 1]);
  const next = { ...first, sourceTime: 20 };
  ensurePanePlaceholderSeries(chart, state, 2, next);
  assert.equal(series.length, 2);
  assert.deepEqual(series.map((entry) => entry.data.length), [2, 2]);
  assert.deepEqual(mustBeDefined(series[0]).data[1], [{ time: next, value: 0 }]);
});

test("placeholder ownership follows pane moves and removes only panes outside retention", () => {
  const { chart, state, series, removed } = placeholderFixture();
  ensurePanePlaceholderSeries(chart, state, 2, 10);
  mustBeDefined(series[0]).paneIndex = 0;
  mustBeDefined(series[1]).paneIndex = 1;
  ensurePanePlaceholderSeries(chart, state, 2, 10, { mainPaneIndex: 2 });
  assert.equal(series.length, 2);
  assert.deepEqual([...state.current.seriesByPane.keys()], [0, 1]);
  trimPanePlaceholderSeries(chart, state, 1);
  assert.deepEqual(removed, [series[1]]);
  assert.deepEqual([...state.current.seriesByPane.keys()], [0]);
  trimPanePlaceholderSeries(structuralMock<AdapterChart>({}), state, 0);
  assert.equal(removed.length, 1, "an outgoing chart must not remove the new chart's placeholders");
});

test("default pane layout assigns the main share to its current position", () => {
  assert.deepEqual(resolvePaneHeightLayout(null, 2, 1000, 2), [175, 175, 650]);
  assert.equal(resolvePaneHeightLayout(null, 0, 1000), null);
  assert.equal(resolvePaneHeightLayout(null, 2, 0), null);
});

function priceScaleFixture() {
  const updates: { paneIndex: number; options: PriceScaleOptionsPatch }[] = [];
  const chart = structuralMock<AdapterChart>({
    panes: () => [{}, {}],
    priceScale: (_side: string, paneIndex: number) => ({
      options: () => ({ autoScale: true, invertScale: paneIndex === 1, mode: 0 }),
      applyOptions: (options: PriceScaleOptionsPatch) => updates.push({ paneIndex, options }),
    }),
  });
  return { chart, updates };
}

test("price scale menu uses the pointed pane and keeps its menu inside chart bounds", () => {
  const { chart } = priceScaleFixture();
  const options = {
    chart,
    activePaneIds: ["main", "rsi"],
    layout: buildPanePointerLayout(["main", "rsi"], [400, 200], 10),
    rect: { left: 10, right: 1010, top: 10, bottom: 610 },
    clientX: 1000,
    clientY: 550,
  };
  assert.deepEqual(resolvePanePriceScaleMenu(options), {
    x: 782, y: 366, paneId: "rsi", paneIndex: 1,
    autoScale: true, invertScale: true, mode: 0,
  });
  assert.equal(resolvePanePriceScaleMenu({ ...options, clientX: 800 }), null);
  assert.equal(resolvePanePriceScaleMenu({ ...options, activePaneIds: ["rsi", "main"] }), null);
});

test("an open price scale menu resolves its pane id again after reorder or removal", () => {
  const { chart, updates } = priceScaleFixture();
  assert.equal(applyPanePriceScaleOptions(chart, ["rsi", "main"], "rsi", { mode: 1 }), true);
  assert.deepEqual(updates, [{ paneIndex: 0, options: { mode: 1 } }]);
  assert.equal(applyPanePriceScaleOptions(chart, ["main"], "rsi", { autoScale: false }), false);
  assert.equal(updates.length, 1);
});

test("indicator pane descriptors isolate same-named plots by indicator and preserve pane ordering", () => {
  const mainLine = { indicatorId: "main-owner", id: "top", data: [{ time: 10, value: 5 }] };
  const upper = { indicatorId: "a", id: "top", data: [{ time: 10, value: 3 }, { time: 30, value: 4 }] };
  const lower = { indicatorId: "a", id: "bottom", data: [{ time: 10, value: 2 }] };
  const fill = { indicatorId: "a", plot1_id: "top", plot2_id: "bottom" };
  const foreignFill = { indicatorId: "b", plot1_id: "top", plot2_id: "bottom" };
  const line = { indicatorId: "a", pane: "sub", price: 2 };
  const options = {
    dataTimeSet: new Set([10, 20]), intervalSeconds: 10,
    mainOverlayLines: [mainLine],
    paneOrder: ["sub-a", "main"],
    subPanes: [{ id: "sub-a", label: "A", lines: [upper, lower] }],
    indicatorMarkers: [
      { indicatorId: "a", pane: "sub", data: [{ time: 10, value: 3 }, { time: 30, value: 4 }] },
      { indicatorId: "b", pane: "sub", data: [{ time: 10, value: 8 }] },
    ],
    indicatorFills: [fill, foreignFill],
    indicatorHlines: [line, { indicatorId: "b", pane: "sub", price: 99 }],
    indicatorBgcolors: [],
  };
  const descriptors = buildPaneDescriptors(options);
  const sub = mustBeDefined(descriptors[0]);
  const main = mustBeDefined(descriptors[1]);
  assert.deepEqual(descriptors.map(({ id, paneIndex }) => [id, paneIndex]), [["sub-a", 0], ["main", 1]]);
  assert.deepEqual(sub.fills, [fill]);
  assert.deepEqual(main.fills, []);
  assert.deepEqual(sub.hlines, [line]);
  assert.deepEqual(main.hlines, []);
  assert.equal(sub.markers.length, 1);
  assert.deepEqual(sub.markers[0]?.data, [{ time: 10, value: 3 }]);
  assert.deepEqual(sub.lines[0]?.data, [{ time: 10, value: 3 }]);
  const repeat = buildPaneDescriptors(options);
  assert.equal(repeat[0]?.hlines, sub.hlines, "unchanged source collections retain their filtered identity");
});
