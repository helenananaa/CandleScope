import assert from "node:assert/strict";
import test from "node:test";
import { act, createElement, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { CommitChartData, KlineApi, KlineFetchResult } from "../klineContracts.js";
import type { KlineBar } from "../marketDataTypes.js";
import {
  planLoadMorePageSize,
  useChartLoadMoreLeft,
  type ChartLoadMoreLeftRuntime,
} from "../useChartLoadMoreLeft.js";
import { epochSeconds, partialMock } from "../../../test/testHelpers.js";

// RC item 16: Binance USD-M BTCUSDT 89m, composed from 1m, beside a live 1m
// chart. While a left page backfills 1m, the warmup revision fence refuses the
// 1m batches next to the page seam (StaleAcquisition), the backend answers the
// 89m page as pending with those buckets missing, and a coordinator retry
// writes them seconds later. The chart must not report that page as settled
// while the seam still has a hole.
const W = 89 * 60;
const SEAM = 336_001 * W; // 2026-11-09T17:29:00Z, the RC seam.
const INITIAL_BARS = 222;
const NATIVE = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"];
const SERIES = { exchange: "binance", marketType: "futures", symbol: "BTCUSDT", interval: "89m" };
const SEAM_HOLE_BARS = 7;

function bar(time: number): KlineBar {
  return { time: epochSeconds(time), open: 1, high: 2, low: 0.5, close: 1.5, volume: 1, is_closed: true };
}

function gaps(rows: readonly KlineBar[]): { from: number; to: number }[] {
  const found: { from: number; to: number }[] = [];
  for (let index = 1; index < rows.length; index += 1) {
    if (rows[index]!.time - rows[index - 1]!.time !== W) {
      found.push({ from: rows[index - 1]!.time, to: rows[index]!.time });
    }
  }
  return found;
}

/** The composed /klines/history/before and /klines/range contract for 89m. */
class ComposedBackend {
  readonly beforeRequests: number[] = [];
  private readonly pending = new Set<number>();

  refuseSeamWrites(seam: number): void {
    for (let index = 1; index <= SEAM_HOLE_BARS; index += 1) this.pending.add(seam - index * W);
  }

  retryLands(): void {
    this.pending.clear();
  }

  private answer(open: number[]): KlineFetchResult {
    const missing = open.filter((time) => this.pending.has(time));
    const data = open.filter((time) => !this.pending.has(time)).map(bar);
    const oldest = data[0]?.time;
    const common = { data, has_more: true, ...(oldest === undefined ? {} : { next_before_ms: oldest * 1_000 }) };
    if (missing.length) {
      return {
        ...common,
        history_state: "pending",
        complete: false,
        retryable: true,
        verified_contiguous: false,
        all_rows_final: true,
        missing_ranges: [{
          start_ms: Math.min(...missing) * 1_000,
          end_ms: (Math.max(...missing) + W) * 1_000 - 1,
          interval: "1m",
        }],
      };
    }
    return {
      ...common,
      history_state: "ready",
      complete: true,
      retryable: false,
      verified_contiguous: true,
      all_rows_final: true,
      has_tail_gap: false,
      truncated: false,
      missing_ranges: [],
    };
  }

  api(): KlineApi {
    return partialMock<KlineApi>({
      fetchKlinesBefore: async (_symbol, _interval, requested, bars) => {
        const before = requested ?? 0;
        this.beforeRequests.push(before);
        const open = Array.from({ length: bars }, (_, index) => before - (bars - index) * W);
        return { ...this.answer(open), endpoint: "before" };
      },
      fetchKlinesRange: async (_symbol, _interval, start, end) => {
        const first = Math.ceil(start / W) * W;
        const open: number[] = [];
        for (let time = first; time <= end; time += W) open.push(time);
        return { ...this.answer(open), endpoint: "range", start_ms: start * 1_000, end_ms: end * 1_000 };
      },
    });
  }
}

/** Mounts hooks with react-dom in node; the host renders nothing. */
async function mount(element: ReturnType<typeof createElement>) {
  const scope = globalThis as Record<string, unknown>;
  const shims: Record<string, unknown> = { window: globalThis, HTMLIFrameElement: class {}, IS_REACT_ACT_ENVIRONMENT: true };
  const previous = Object.keys(shims).map((name) => [name, name in scope, scope[name]] as const);
  for (const [name, value] of Object.entries(shims)) if (name === "IS_REACT_ACT_ENVIRONMENT" || !(name in scope)) scope[name] = value;
  const noop = () => {};
  const document: Record<string, unknown> = { nodeType: 9, nodeName: "#document", activeElement: null,
    addEventListener: noop, removeEventListener: noop };
  const container = { nodeType: 1, nodeName: "DIV", tagName: "DIV", namespaceURI: "http://www.w3.org/1999/xhtml",
    ownerDocument: document, addEventListener: noop, removeEventListener: noop };
  document.documentElement = container;
  document.body = container;
  const root = createRoot(container as unknown as Element);
  await act(async () => { root.render(element); });
  return async () => {
    await act(async () => { root.unmount(); });
    for (const [name, existed, value] of previous) {
      if (existed) scope[name] = value;
      else delete scope[name];
    }
  };
}

async function settle(): Promise<void> {
  await act(async () => {
    for (let turn = 0; turn < 5; turn += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test("a custom-interval left page keeps loading until the seam hole is filled, across two pages", async () => {
  const originalNow = Date.now;
  let now = originalNow();
  Date.now = () => now;
  const originalLog = console.log;
  console.log = () => {};
  const backend = new ComposedBackend();
  const initial = Array.from({ length: INITIAL_BARS }, (_, index) => bar(SEAM + index * W));
  const probe: {
    chart: KlineBar[];
    commit: CommitChartData;
    renders: number;
    runtime: ChartLoadMoreLeftRuntime | null;
  } = { chart: initial, commit: () => {}, renders: 0, runtime: null };
  const feed = new SeriesDataFeed({
    api: backend.api(),
    getActiveSeries: () => SERIES,
    commitMergedChartData: (...args) => probe.commit(...args),
  });

  function Host() {
    const [rows, setRows] = useState(initial);
    const commitRows = useCallback<CommitChartData>((_symbol, _interval, incoming) => {
      setRows((current) => {
        const byTime = new Map(current.map((row) => [row.time, row]));
        let added = false;
        for (const row of incoming) {
          if (!byTime.has(row.time)) added = true;
          byTime.set(row.time, row);
        }
        // Rows already held do not produce a new chart revision.
        if (!added) return current;
        return [...byTime.values()].sort((left, right) => left.time - right.time);
      });
    }, []);
    const runtime = useChartLoadMoreLeft({
      enabled: true,
      symbol: SERIES.symbol,
      exchange: SERIES.exchange,
      marketType: SERIES.marketType,
      interval: SERIES.interval,
      nativeIntervalValues: NATIVE,
      chartData: rows,
      loading: false,
      dataSource: "api",
      seriesDataFeed: feed,
      commitMergedChartData: commitRows,
    });
    useEffect(() => {
      probe.chart = rows;
      probe.commit = commitRows;
      probe.renders += 1;
      probe.runtime = runtime;
    });
    return null;
  }

  const pageSize = planLoadMorePageSize("89m", NATIVE);
  assert.ok(pageSize > SEAM_HOLE_BARS, "the plan must request more than the refused seam buckets");
  const hook = () => {
    assert.ok(probe.runtime);
    return probe.runtime;
  };
  // What the RC driver (and a user) relies on: once older history stops
  // loading, the bars it shows are continuous.
  const assertSettledChartIsContinuous = (step: string) => {
    if (!hook().loadingMoreLeft) assert.deepEqual(gaps(probe.chart), [], `${step}: settled chart has a seam hole`);
  };
  const unmount = await mount(createElement(Host));
  try {
    for (const [page, seam] of [[1, SEAM], [2, SEAM - pageSize * W]] as const) {
      backend.refuseSeamWrites(seam);
      now += 3_000; // the previous page's pending cooldown has elapsed
      await act(async () => { await hook().handleNeedMoreLeft(); });
      await settle();
      assert.equal(backend.beforeRequests.at(-1), seam, `page ${page} starts at the previous oldest bar`);
      assert.equal(probe.chart[0]!.time, seam - pageSize * W, `page ${page} committed its partial rows`);
      assert.deepEqual(gaps(probe.chart), [{ from: seam - (SEAM_HOLE_BARS + 1) * W, to: seam }],
        `page ${page} is partial: the bars at its seam are still missing`);
      assert.equal(hook().loadingMoreLeft, true, `page ${page} still owns unresolved older history`);
      assertSettledChartIsContinuous(`page ${page} partial`);

      // The RC driver keeps calling loadMoreLeft; the pending page must not
      // be skipped by an older cursor.
      const requests = backend.beforeRequests.length;
      await act(async () => { await hook().handleNeedMoreLeft(); });
      await settle();
      assert.equal(backend.beforeRequests.length, requests, `page ${page} joins its pending boundary`);
      assertSettledChartIsContinuous(`page ${page} repeated gesture`);

      backend.retryLands();
      if (page === 2) {
        // A gap-repair read can fill the hole before the page itself is
        // re-proven; the page stays loading until the feed settles it.
        await act(async () => {
          await feed.getRange(SERIES, { start: epochSeconds(seam - SEAM_HOLE_BARS * W), end: epochSeconds(seam - W) });
        });
        await settle();
        assert.deepEqual(gaps(probe.chart), []);
        assert.equal(hook().loadingMoreLeft, true, "the page is not settled by a side read");
      }
      const rendersBeforeProof = probe.renders;
      await act(async () => { await feed.pollPendingRepairs(SERIES, { force: true }); });
      await settle();
      if (page === 2) {
        assert.ok(probe.renders > rendersBeforeProof, "settling without new rows still releases the page");
      }
      assert.equal(feed.getPendingBeforePage(SERIES), null, `page ${page} was proven complete`);
      assert.equal(hook().loadingMoreLeft, false, `page ${page} settled`);
      assert.deepEqual(gaps(probe.chart), [], `page ${page} filled its seam`);
      assertSettledChartIsContinuous(`page ${page} settled`);
    }
    const secondSeam = SEAM - pageSize * W;
    assert.deepEqual(backend.beforeRequests, [SEAM, SEAM, secondSeam, secondSeam],
      "each page is requested and re-proven at its own seam; no cursor skips past a hole");
    assert.equal(probe.chart.length, INITIAL_BARS + 2 * pageSize);
    assert.equal(probe.chart[0]!.time, SEAM - 2 * pageSize * W);
  } finally {
    await unmount();
    Date.now = originalNow;
    console.log = originalLog;
  }
});
