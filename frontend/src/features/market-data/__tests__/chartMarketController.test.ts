import assert from "node:assert/strict";
import test from "node:test";
import { ChartMarketController } from "../manager/chartMarketController.js";
import type { MarketDataService } from "../marketDataService.js";
import type { MarketSeries } from "../marketDataTypes.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
function harness() {
  const events: string[] = [], timers = new Map<number, { work: () => void; delay: number }>();
  let sequence = 0;
  const data = {
    warm: (series: MarketSeries) => {
      events.push(`warm:${series.symbol}`);
      return { done: Promise.resolve("warmed"), release: () => events.push(`cancel:${series.symbol}`) };
    },
    prepareForeground: (series: MarketSeries) => {
      events.push(`promote:${series.symbol}`);
      return { release: () => events.push(`release:${series.symbol}`) };
    },
  } as unknown as MarketDataService;
  const controller = new ChartMarketController({ data, owner: "chart-a",
    schedule: (work, delay) => { const id = ++sequence; timers.set(id, { work, delay }); return id; },
    cancel: timer => { timers.delete(Number(timer)); },
  });
  return { controller, events, timers, fire: (delay: number) => {
    for (const [id, timer] of [...timers]) if (timer.delay === delay) { timers.delete(id); timer.work(); }
  } };
}

test("a brief hover makes no demand and a stable hover is transferred before its lease is released", () => {
  const h = harness();
  h.controller.preview(series, ["1m"]); h.controller.cancelPreview(); h.fire(150);
  assert.deepEqual(h.events, []);
  h.controller.preview(series, ["1m"]); h.fire(150);
  h.controller.activate(series);
  assert.deepEqual(h.events, ["warm:BTCUSDT", "promote:BTCUSDT", "cancel:BTCUSDT"]);
  h.fire(5_000);
  assert.equal(h.events.at(-1), "release:BTCUSDT");
  assert.equal(h.timers.size, 0);
});

test("A to B to C invalidates old selection tokens and cancelled hover callbacks", () => {
  const h = harness();
  const first = h.controller.activate(series);
  h.controller.preview({ ...series, symbol: "ETHUSDT" }, ["1m"]);
  const lateHover = [...h.timers.values()].find(timer => timer.delay === 150)!.work;
  const second = h.controller.activate({ ...series, symbol: "ETHUSDT" });
  const third = h.controller.activate({ ...series, symbol: "SOLUSDT" });
  lateHover();
  assert.equal(first.isCurrent(), false); assert.equal(second.isCurrent(), false); assert.equal(third.isCurrent(), true);
  assert.equal(h.events.some(event => event.startsWith("warm:")), false);
  h.controller.releaseAll(); assert.equal(third.isCurrent(), false); assert.equal(h.timers.size, 0);
});

test("StrictMode cleanup releases all owned demand but the next mounted lifecycle remains usable", () => {
  const h = harness();
  h.controller.preview(series, ["1m"]); h.fire(150); h.controller.releaseAll();
  h.controller.preview({ ...series, symbol: "ETHUSDT" }, ["1m"]); h.fire(150);
  assert.deepEqual(h.events, ["warm:BTCUSDT", "cancel:BTCUSDT", "warm:ETHUSDT"]);
  h.controller.releaseAll();
});
