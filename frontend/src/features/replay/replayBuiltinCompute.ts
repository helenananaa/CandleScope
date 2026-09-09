import { computeIndicatorBatch } from "../../services/indicatorApi.js";
import { recordPerfEvent } from "../../runtime/performance/perfMarks.js";
import type { IndicatorComputeBatchExecutor } from "../indicators/indicatorComputeController.js";
import type { IndicatorColorPoint, IndicatorComputeRequest, IndicatorOhlcvBar, IndicatorPayloadEnvelope, IndicatorValuePoint } from "../indicators/indicatorTypes.js";

type State = { count: number; fastSum: number; slowSum: number; signalSum: number;
  fast: number | null; slow: number | null; signal: number | null; signalCount: number };
const initial = (): State => ({ count: 0, fastSum: 0, slowSum: 0, signalSum: 0,
  fast: null, slow: null, signal: null, signalCount: 0 });
const field = (bar: IndicatorOhlcvBar, source: string): number => {
  if (source === "hl2") return (bar.high + bar.low) / 2;
  if (source === "hlc3") return (bar.high + bar.low + bar.close) / 3;
  if (source === "ohlc4") return (bar.open + bar.high + bar.low + bar.close) / 4;
  return Number(bar[source as "open" | "high" | "low" | "close"]);
};
const outputKey = (title: string) => ({ DIF: 0, DEA: 1, "MACD Hist": 2, VOL: 0 })[title];
function sameBar(a: IndicatorOhlcvBar, b: IndicatorOhlcvBar): boolean {
  return a.time === b.time && a.open === b.open && a.high === b.high
    && a.low === b.low && a.close === b.close && a.volume === b.volume && a.is_closed === b.is_closed;
}
function prefixLength(points: readonly { time: number }[], before: number): number {
  let low = 0, high = points.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (points[middle]!.time < before) low = middle + 1;
    else high = middle;
  }
  return low;
}
const floatBits = new DataView(new ArrayBuffer(8));
/** Python's round(float, 8), including ties-to-even on the exact binary value. */
export function roundBuiltinValue(value: number): number {
  if (!Number.isFinite(value) || Math.abs(value) >= 1e21) return value;
  floatBits.setFloat64(0, Math.abs(value));
  const bits = floatBits.getBigUint64(0);
  const exponent = Number((bits >> 52n) & 2047n);
  const significand = (bits & ((1n << 52n) - 1n)) | (exponent === 0 ? 0n : 1n << 52n);
  const shift = (exponent === 0 ? -1022 : exponent - 1023) - 52;
  const numerator = significand * 100_000_000n;
  const denominator = shift < 0 ? 1n << BigInt(-shift) : 1n;
  const scaled = shift < 0 ? numerator : numerator << BigInt(shift);
  let rounded = scaled / denominator;
  const remainder = scaled % denominator;
  if (2n * remainder > denominator || (2n * remainder === denominator && rounded % 2n !== 0n)) rounded++;
  return Number(`${value < 0 ? "-" : ""}${rounded}e-8`);
}

/** Bounded per-view state; SMA seeds and histogram convention match the Python builtins.
 * A server result seeds/validates each context. Unknown implementations stay remote.
 */
export class ReplayBuiltinState {
  private rows: IndicatorOhlcvBar[] = [];
  private states: State[] = [initial()];
  private values: (number | null)[][] = [];
  private outputs: IndicatorValuePoint[][] = [[], [], []];
  private outputColors: IndicatorColorPoint[][] = [[], [], []];
  constructor(private readonly request: IndicatorComputeRequest) {}

  static supports(request: IndicatorComputeRequest): boolean {
    if (request.mode !== "builtin" || !["MACD", "VOL"].includes(request.name ?? "")) return false;
    const params = request.params ?? {};
    if (request.name === "MACD") {
      if (!["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"].includes(String(params.source ?? "close"))) return false;
      if (![params.fast ?? 12, params.slow ?? 26, params.signal ?? 9].every(p => Number.isSafeInteger(Number(p)) && Number(p) >= 1 && Number(p) <= 200)) return false;
    }
    return request.ohlcv.length <= 10_000 && request.ohlcv.every((bar, index, rows) => (
      [bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite)
      && (index === 0 || bar.time > rows[index - 1]!.time)
    ));
  }

  advance(rows: IndicatorOhlcvBar[]): boolean {
    if (rows.length < this.rows.length) return false;
    const stable = Math.max(0, this.rows.length - 1);
    for (let i = 0; i < stable; i++) {
      if (!sameBar(rows[i]!, this.rows[i]!)) return false;
    }
    this.values.length = stable;
    this.states.length = stable + 1;
    this.rows.length = stable;
    const replaceFrom = rows[stable]?.time ?? Infinity;
    for (const points of [...this.outputs, ...this.outputColors]) points.length = prefixLength(points, replaceFrom);
    const p = this.request.params ?? {};
    const fast = Number(p.fast ?? 12), slow = Number(p.slow ?? 26), signal = Number(p.signal ?? 9);
    for (let i = stable; i < rows.length; i++) {
      const bar = rows[i]!;
      const s = { ...this.states.at(-1)! };
      s.count++;
      if (this.request.name === "VOL") this.values.push([bar.volume]);
      else {
        const value = field(bar, String(p.source ?? "close"));
        if (s.count <= fast) { s.fastSum += value; if (s.count === fast) s.fast = s.fastSum / fast; }
        else s.fast = 2 / (fast + 1) * value + (1 - 2 / (fast + 1)) * s.fast!;
        if (s.count <= slow) { s.slowSum += value; if (s.count === slow) s.slow = s.slowSum / slow; }
        else s.slow = 2 / (slow + 1) * value + (1 - 2 / (slow + 1)) * s.slow!;
        let dif: number | null = null, dea: number | null = null, hist: number | null = null;
        if (s.fast !== null && s.slow !== null) {
          dif = s.fast - s.slow;
          s.signalCount++;
          if (s.signalCount <= signal) { s.signalSum += dif; if (s.signalCount === signal) s.signal = s.signalSum / signal; }
          else s.signal = 2 / (signal + 1) * dif + (1 - 2 / (signal + 1)) * s.signal!;
          dea = s.signal;
          if (dea !== null) hist = 2 * (dif - dea);
        }
        this.values.push([dif, dea, hist]);
      }
      this.states.push(s);
      this.rows.push({ ...bar });
      this.values.at(-1)!.forEach((value, output) => {
        if (value === null) return;
        this.outputs[output]!.push(Object.freeze({ time: bar.time, value: roundBuiltinValue(value) }));
        if (this.request.name === "VOL" || output === 2) {
          const up = this.request.name === "VOL" ? bar.close >= bar.open : value >= 0;
          const color = String(this.request.name === "VOL"
            ? (up ? p.up_color ?? "#22c55e" : p.down_color ?? "#ef4444")
            : (up ? p.hist_up_color ?? "#22c55e" : p.hist_down_color ?? "#ef4444"));
          this.outputColors[output]!.push(Object.freeze({ time: bar.time, color }));
        }
      });
    }
    return true;
  }

  points(title: string): IndicatorValuePoint[] {
    const key = outputKey(title);
    if (key === undefined) return [];
    return this.outputs[key]!.slice();
  }

  matches(payload: IndicatorPayloadEnvelope): boolean {
    const lines = payload.lines;
    return payload.ok === true && lines.length === (this.request.name === "VOL" ? 1 : 3)
      && payload.series.every(series => outputKey(series.style.title) !== undefined)
      && lines.every(line => {
        const title = line.name ?? line.title ?? "";
        if (outputKey(title) === undefined) return false;
        const points = this.points(title);
        return points.length === line.data.length && points.every((point, i) => (
          point.time === line.data[i]!.time
          && Math.abs(point.value - line.data[i]!.value) <= 1e-10 * Math.max(1, Math.abs(point.value))
        ));
      });
  }

  project(template: IndicatorPayloadEnvelope): IndicatorPayloadEnvelope {
    const pointsByTitle = new Map<string, IndicatorValuePoint[]>();
    const points = (title: string) => {
      if (!pointsByTitle.has(title)) pointsByTitle.set(title, this.points(title));
      return pointsByTitle.get(title)!;
    };
    const colors = (title: string) => this.outputColors[outputKey(title) ?? 0]!.slice();
    return {
      ...template,
      lines: template.lines.map(line => { const title = line.name ?? line.title ?? ""; return {
        ...line, data: points(title), ...(["VOL", "MACD Hist"].includes(title) ? { colorData: colors(title) } : {}),
      }; }),
      series: template.series.map(series => ({ ...series, data: points(series.style.title),
        style: { ...series.style, ...(["VOL", "MACD Hist"].includes(series.style.title) ? { colorData: colors(series.style.title) } : {}) },
      })),
    };
  }
}

export function createReplayBuiltinCompute(remote: IndicatorComputeBatchExecutor = computeIndicatorBatch): IndicatorComputeBatchExecutor {
  const cache = new Map<string, { state: ReplayBuiltinState; template: IndicatorPayloadEnvelope }>();
  return async ({ jobs, signal }) => {
    signal?.throwIfAborted();
    const results = [];
    const pending = [];
    const keyFor = (request: IndicatorComputeRequest) => JSON.stringify([
      request.exchange, request.marketType, request.symbol, request.interval, request.name, request.params,
    ]);
    for (const job of jobs) {
      const started = performance.now();
      const key = keyFor(job.request);
      const entry = cache.get(key);
      if (ReplayBuiltinState.supports(job.request) && entry && entry.state.advance(job.request.ohlcv)) {
        results.push({ clientId: job.clientId, jobKey: job.jobKey, payload: entry.state.project(entry.template) });
        recordPerfEvent("replay.indicator.local", { indicatorId: job.clientId, bars: job.request.ohlcv.length, durationMs: performance.now() - started });
      } else pending.push(job);
    }
    if (pending.length) {
      const response = await remote({ jobs: pending, ...(signal ? { signal } : {}) });
      signal?.throwIfAborted();
      for (const item of response.results) {
        const job = pending.find(job => job.jobKey === item.jobKey);
        if (job && ReplayBuiltinState.supports(job.request)) {
          const state = new ReplayBuiltinState(job.request);
          state.advance(job.request.ohlcv);
          const key = keyFor(job.request);
          cache.delete(key);
          if (state.matches(item.payload)) cache.set(key, { state, template: item.payload });
          while (cache.size > 32) cache.delete(cache.keys().next().value!);
        }
        results.push(item);
      }
    }
    return { ok: results.every(item => item.payload.ok === true), results };
  };
}
