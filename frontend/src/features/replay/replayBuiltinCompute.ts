import { computeIndicatorBatch } from "../../services/indicatorApi.js";
import { recordPerfEvent } from "../../runtime/performance/perfMarks.js";
import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import type { IndicatorComputeBatchExecutor } from "../indicators/indicatorComputeController.js";
import type { IndicatorColorPoint, IndicatorComputeBatchItem, IndicatorComputeBatchJob, IndicatorComputeRequest, IndicatorOhlcvBar, IndicatorPayloadEnvelope, IndicatorValuePoint } from "../indicators/indicatorTypes.js";
import { replayWindowMean, replayWindowMoments } from "./replayWindowMath.js";

type State = { count: number; fastSum: number; slowSum: number; signalSum: number;
  fast: number | null; slow: number | null; signal: number | null; signalCount: number;
  previous: number | null; gain: number; loss: number; gainError: number; lossError: number };
export interface ReplayBuiltinSeed {
  schema: "replay.builtin-seed.v1";
  name: string;
  params: Record<string, unknown>;
  before_ms: number;
  state: Record<string, unknown>;
}
const initial = (): State => ({ count: 0, fastSum: 0, slowSum: 0, signalSum: 0,
  fast: null, slow: null, signal: null, signalCount: 0,
  previous: null, gain: 0, loss: 0, gainError: 0, lossError: 0 });
const field = (bar: IndicatorOhlcvBar, source: string): number => {
  if (source === "hl2") return (bar.high + bar.low) / 2;
  if (source === "hlc3") return (bar.high + bar.low + bar.close) / 3;
  if (source === "ohlc4") return (bar.open + bar.high + bar.low + bar.close) / 4;
  return Number(bar[source as "open" | "high" | "low" | "close"]);
};
// Python 3.12 sum(float[]) uses compensated addition for RSI's initial gains
// and losses. Keep the compensation until the seed is complete; subsequent
// Wilder updates deliberately use the builtin's ordinary floating arithmetic.
function addSeed(sum: number, correction: number, value: number): [number, number] {
  const next = sum + value;
  return [next, correction + (Math.abs(sum) >= Math.abs(value)
    ? (sum - next) + value : (value - next) + sum)];
}
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
  private seedWindow: number[] = [];
  constructor(private readonly request: IndicatorComputeRequest, seed?: ReplayBuiltinSeed) {
    if (seed !== undefined) this.states = [this.restoreSeed(seed)];
  }

  private restoreSeed(seed: ReplayBuiltinSeed): State {
    if (seed.schema !== "replay.builtin-seed.v1" || seed.name !== this.request.name
      || seed.before_ms !== Number(this.request.ohlcv[0]?.time) * 1000
      || !seed.state || !seed.params
      || Object.entries(this.request.params ?? {}).some(([key, value]) => seed.params[key] !== value)) {
      throw new TypeError("canonical builtin seed does not match its render window");
    }
    const number = (key: string): number => {
      const value = seed.state[key];
      if (typeof value !== "number" || !Number.isFinite(value)) throw new TypeError(`invalid builtin seed ${key}`);
      return value;
    };
    const nullable = (key: string): number | null => seed.state[key] === null ? null : number(key);
    const s = initial();
    s.count = number("_bar_count");
    if (!Number.isSafeInteger(s.count) || s.count < 0
      || (!["VOL", "MA", "BOLL"].includes(seed.name) && number("_count") !== s.count)) throw new TypeError("invalid builtin seed count");
    if (seed.name === "MA" || seed.name === "BOLL") {
      const window = seed.state._window, period = Number(this.request.params?.period ?? 20);
      if (!Array.isArray(window) || window.length !== Math.min(s.count, period)
        || !window.every(value => typeof value === "number" && Number.isFinite(value))) throw new TypeError("invalid builtin seed window");
      this.seedWindow = (window as number[]).slice();
      return s;
    }
    if (seed.name === "EMA") { s.fast = nullable("_ema"); s.fastSum = number("_sum"); }
    else if (seed.name === "ATR") {
      s.fast = nullable("_atr"); s.fastSum = number("_tr_sum"); s.previous = nullable("_prev_close");
    } else if (seed.name === "RSI") {
      s.previous = nullable("_prev_val");
      s.gain = number("_avg_gain"); s.loss = number("_avg_loss");
      const period = Number(this.request.params?.period ?? 14);
      if (s.count <= period) {
        const accumulate = (key: string): [number, number] => {
          const values = seed.state[key];
          if (!Array.isArray(values) || values.length !== Math.max(0, s.count - 1)
            || values.length > period || !values.every(v => typeof v === "number" && Number.isFinite(v) && v >= 0)) {
            throw new TypeError(`invalid builtin seed ${key}`);
          }
          return (values as number[]).reduce<[number, number]>(([sum, error], value) => addSeed(sum, error, value), [0, 0]);
        };
        [s.gain, s.gainError] = accumulate("_init_gains");
        [s.loss, s.lossError] = accumulate("_init_losses");
      }
    } else if (seed.name === "MACD") {
      s.fast = nullable("_fast_ema"); s.slow = nullable("_slow_ema"); s.signal = nullable("_signal_ema");
      s.fastSum = number("_fast_sum"); s.slowSum = number("_slow_sum"); s.signalSum = number("_signal_sum");
      s.signalCount = number("_signal_count");
      if (!Number.isSafeInteger(s.signalCount) || s.signalCount < 0 || s.signalCount > s.count) throw new TypeError("invalid builtin signal seed count");
    } else if (seed.name !== "VOL") throw new TypeError("unsupported local builtin seed");
    return s;
  }

  private outputKey(title: string): number | undefined {
    if (this.request.name === "MACD") return ({ DIF: 0, DEA: 1, "MACD Hist": 2 })[title];
    if (this.request.name === "VOL") return title === "VOL" ? 0 : undefined;
    const period = Number(this.request.params?.period ?? (["EMA", "MA", "BOLL"].includes(this.request.name ?? "") ? 20 : 14));
    if (this.request.name === "BOLL") return ({ [`BOLL Mid(${period})`]: 0, "BOLL Upper": 1, "BOLL Lower": 2 })[title];
    return title === `${this.request.name}(${period})` ? 0 : undefined;
  }

  static supports(request: IndicatorComputeRequest): boolean {
    if (request.mode !== "builtin" || !["MACD", "VOL", "EMA", "RSI", "ATR", "MA", "BOLL"].includes(request.name ?? "")) return false;
    const params = request.params ?? {};
    if (["MACD", "EMA", "RSI", "MA", "BOLL"].includes(request.name ?? "")
      && !["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"].includes(String(params.source ?? "close"))) return false;
    if (request.name === "MACD") {
      if (![params.fast ?? 12, params.slow ?? 26, params.signal ?? 9].every(p => Number.isSafeInteger(Number(p)) && Number(p) >= 1 && Number(p) <= 200)) return false;
    }
    if (["EMA", "RSI", "ATR", "MA", "BOLL"].includes(request.name ?? "")) {
      const period = Number(params.period ?? (["EMA", "MA", "BOLL"].includes(request.name ?? "") ? 20 : 14));
      if (!Number.isSafeInteger(period) || period < (["RSI", "BOLL"].includes(request.name ?? "") ? 2 : 1)
        || period > (["EMA", "MA"].includes(request.name ?? "") ? 500 : request.name === "BOLL" ? 200 : 100)) return false;
    }
    if (request.name === "BOLL" && (!Number.isFinite(Number(params.mult ?? 2))
      || Number(params.mult ?? 2) < 0.5 || Number(params.mult ?? 2) > 5)) return false;
    return request.ohlcv.length <= 10_000 && request.ohlcv.every((bar, index, rows) => (
      [bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite)
      && (index === 0 || bar.time > rows[index - 1]!.time)
    ));
  }

  advance(rows: IndicatorOhlcvBar[]): boolean {
    if (rows.length < this.rows.length) return false;
    const stable = Math.max(0, this.rows.length - 1);
    // Canonical history resets mathematics at declared gaps. A new gap cannot
    // be extended using the preceding uninterrupted seed; ask that authority.
    if (this.request.interval) {
      const timeline = createIntervalTimeline(this.request.interval);
      if (!timeline) return false;
      for (let i = Math.max(1, stable); i < rows.length; i++) {
        if (!timeline.isSuccessor(rows[i - 1]!.time, rows[i]!.time)) return false;
      }
    }
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
      else if (this.request.name === "MA" || this.request.name === "BOLL") {
        const period = Number(p.period ?? 20);
        const missing = Math.max(0, period - i - 1);
        const window = [
          ...(missing ? this.seedWindow.slice(-missing) : []),
          ...rows.slice(Math.max(0, i - period + 1), i + 1).map(row => field(row, String(p.source ?? "close"))),
        ];
        if (window.length < period) this.values.push(this.request.name === "MA" ? [null] : [null, null, null]);
        else if (this.request.name === "MA") this.values.push([replayWindowMean(window)]);
        else {
          const [mean, m2] = replayWindowMoments(window);
          const spread = Number(p.mult ?? 2) * Math.sqrt(Math.max(m2 / period, 0));
          this.values.push([mean, mean + spread, mean - spread]);
        }
      }
      else if (this.request.name === "MACD") {
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
      } else {
        const period = Number(p.period ?? (this.request.name === "EMA" ? 20 : 14));
        const value = field(bar, String(p.source ?? "close"));
        let output: number | null = null;
        if (this.request.name === "RSI") {
          if (s.previous !== null) {
            const change = value - s.previous;
            const gain = Math.max(change, 0), loss = Math.max(-change, 0);
            if (s.count <= period + 1) {
              [s.gain, s.gainError] = addSeed(s.gain, s.gainError, gain);
              [s.loss, s.lossError] = addSeed(s.loss, s.lossError, loss);
              if (s.count === period + 1) {
                s.gain = (s.gain + s.gainError) / period;
                s.loss = (s.loss + s.lossError) / period;
              }
            } else {
              s.gain = (s.gain * (period - 1) + gain) / period;
              s.loss = (s.loss * (period - 1) + loss) / period;
            }
            if (s.count >= period + 1) output = s.loss === 0 ? 100 : 100 - 100 / (1 + s.gain / s.loss);
          }
          s.previous = value;
        } else {
          const input = this.request.name === "ATR"
            ? Math.max(bar.high - bar.low, s.previous === null ? 0 : Math.abs(bar.high - s.previous),
              s.previous === null ? 0 : Math.abs(bar.low - s.previous))
            : value;
          if (s.count <= period) {
            s.fastSum += input;
            if (s.count === period) s.fast = s.fastSum / period;
          } else s.fast = this.request.name === "ATR"
            ? (s.fast! * (period - 1) + input) / period
            : 2 / (period + 1) * input + (1 - 2 / (period + 1)) * s.fast!;
          output = s.fast;
          s.previous = bar.close;
        }
        this.values.push([output]);
      }
      this.states.push(s);
      this.rows.push({ ...bar });
      this.values.at(-1)!.forEach((value, output) => {
        if (value === null) return;
        this.outputs[output]!.push(Object.freeze({ time: bar.time, value: roundBuiltinValue(value) }));
        if (this.request.name === "VOL" || (this.request.name === "MACD" && output === 2)) {
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
    const key = this.outputKey(title);
    if (key === undefined) return [];
    return this.outputs[key]!.slice();
  }

  matches(payload: IndicatorPayloadEnvelope): boolean {
    const lines = payload.lines;
    return payload.ok === true && lines.length === (["MACD", "BOLL"].includes(this.request.name ?? "") ? 3 : 1)
      && lines.every(line => line.data.length > 0)
      && payload.series.every(series => this.outputKey(series.style.title) !== undefined)
      && lines.every(line => {
        const title = line.name ?? line.title ?? "";
        if (this.outputKey(title) === undefined) return false;
        const points = this.points(title);
        return points.length === line.data.length && points.every((point, i) => (
          point.time === line.data[i]!.time
          && point.value === line.data[i]!.value
        ));
      });
  }

  project(template: IndicatorPayloadEnvelope): IndicatorPayloadEnvelope {
    const pointsByTitle = new Map<string, IndicatorValuePoint[]>();
    const points = (title: string) => {
      if (!pointsByTitle.has(title)) pointsByTitle.set(title, this.points(title));
      return pointsByTitle.get(title)!;
    };
    const colors = (title: string) => this.outputColors[this.outputKey(title) ?? 0]!.slice();
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

export function createReplayBuiltinCompute(remote: IndicatorComputeBatchExecutor = computeIndicatorBatch,
  options: { seedForPayload?: (payload: IndicatorPayloadEnvelope) => ReplayBuiltinSeed | undefined;
    sourceKey?: () => string } = {}): IndicatorComputeBatchExecutor {
  const cache = new Map<string, { state: ReplayBuiltinState; template: IndicatorPayloadEnvelope }>();
  return async ({ jobs, signal, onResults }) => {
    signal?.throwIfAborted();
    const results: IndicatorComputeBatchItem[] = [];
    const pending: IndicatorComputeBatchJob[] = [];
    const keyFor = (request: IndicatorComputeRequest) => JSON.stringify([
      options.sourceKey?.(), request.exchange, request.marketType, request.symbol, request.interval, request.name, request.params,
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
    if (results.length) onResults?.(results.slice());
    if (pending.length) {
      const published = new Set<string>();
      const accept: NonNullable<Parameters<IndicatorComputeBatchExecutor>[0]["onResults"]> = items => {
        if (signal?.aborted) return;
        const fresh = items.filter(item => !published.has(item.jobKey));
        for (const item of fresh) {
          published.add(item.jobKey);
          const job = pending.find(job => job.jobKey === item.jobKey);
          if (job && ReplayBuiltinState.supports(job.request)) {
            const key = keyFor(job.request);
            cache.delete(key);
            // A seed is accepted only after its complete rendered output agrees
            // with the authoritative Python result. Unknown versions stay remote.
            try {
              const state = new ReplayBuiltinState(job.request, options.seedForPayload?.(item.payload));
              state.advance(job.request.ohlcv);
              if (state.matches(item.payload)) cache.set(key, { state, template: item.payload });
            } catch (error) {
              if (!(error instanceof TypeError)) throw error;
            }
            while (cache.size > 32) cache.delete(cache.keys().next().value!);
          }
          results.push(item);
        }
        if (fresh.length) onResults?.(fresh);
      };
      const response = await remote({ jobs: pending, ...(signal ? { signal } : {}), onResults: accept });
      signal?.throwIfAborted();
      accept(response.results);
    }
    return { ok: results.every(item => item.payload.ok === true), results };
  };
}
