/**
 * `candlescope.run-result/1`: the one result shape every strategy run is served in
 * (ADR-BACKTEST-015 §3.7, step P1). The backend projects each engine's own report;
 * this module only validates the wire value and never recomputes money.
 *
 * Times are milliseconds. `bar_time_ms` is the open time of the bar a fill, trade
 * end or equity point belongs to, which is what chart markers anchor to.
 * Money and quantities are canonical decimal strings.
 */

export const RUN_RESULT_SCHEMA = "candlescope.run-result/1";

/** Which run family served the result; each has its own endpoint until the P2 Run facade. */
export type RunResultFamily = "host" | "native" | "external";
export type RunResultAuthority = "HOST" | "SCRIPT";
export type RunResultSource = "host-kernel" | "native-pine" | "external-pine";

export interface RunResultFill {
  time_ms: number;
  bar_time_ms: number | null;
  side: "BUY" | "SELL";
  qty: string;
  price: string;
  fee: string | null;
  order_id: string | null;
  tag: string | null;
  /** Decision-time evidence (`TradeExplanationV1`), only when the run recorded it. */
  explanation: Record<string, unknown> | null;
}

export interface RunResultRejection {
  time_ms: number | null;
  bar_time_ms: number | null;
  side: string | null;
  reason: string;
  order_id: string | null;
  explanation: Record<string, unknown> | null;
}

export interface RunResultTrade {
  id: string;
  side: "LONG" | "SHORT";
  qty: string;
  entry_time_ms: number;
  entry_bar_time_ms: number | null;
  entry_price: string;
  exit_time_ms: number;
  exit_bar_time_ms: number | null;
  exit_price: string;
  fees: string | null;
  net_pnl: string | null;
  /** Decision-time evidence for the entry and exit, when the run recorded it. */
  entry_explanation: Record<string, unknown> | null;
  exit_explanation: Record<string, unknown> | null;
}

export interface RunResultPosition {
  side: "LONG" | "SHORT";
  qty: string;
  avg_price: string | null;
}

export interface RunResultPendingOrder {
  order_id: string;
  side: string;
  type: string;
  qty: string | null;
  limit_price: string | null;
  stop_price: string | null;
  tag: string | null;
}

export interface RunResultEquityPoint {
  time_ms: number;
  bar_time_ms: number | null;
  equity: string | null;
}

export interface RunResultPlot {
  id: string;
  title: string | null;
  kind: "line";
  pane: string;
  /** `[bar open time ms, value]`; `null` marks a gap. */
  points: Array<[number, number | null]>;
}

export interface RunResultSummary {
  initial_equity: string | null;
  final_equity: string | null;
  net_profit: string | null;
  fill_count: number;
  trade_count: number;
  winning_trades: number;
}

export interface RunResult {
  schema: typeof RUN_RESULT_SCHEMA;
  source: RunResultSource;
  authority: RunResultAuthority;
  clock_policy: "FIXED" | "FOLLOW" | "FORWARD";
  fidelity: string | null;
  interval: string;
  fills: RunResultFill[];
  trades: RunResultTrade[];
  open_position: RunResultPosition | null;
  pending_orders: RunResultPendingOrder[];
  rejections: RunResultRejection[];
  equity: RunResultEquityPoint[];
  plots: RunResultPlot[];
  summary: RunResultSummary;
}

/** The (source, authority) each family must serve; a mismatch means a misrouted result. */
export const RUN_RESULT_FAMILY_IDENTITY: Readonly<Record<RunResultFamily, { source: RunResultSource; authority: RunResultAuthority }>> = {
  host: { source: "host-kernel", authority: "HOST" },
  native: { source: "native-pine", authority: "SCRIPT" },
  external: { source: "external-pine", authority: "HOST" },
};

export class RunResultContractError extends Error {
  constructor(readonly path: string, message: string) {
    super(`run-result ${path}: ${message}`);
    this.name = "RunResultContractError";
  }
}

const DECIMAL = /^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$/;

type Row = Record<string, unknown>;

function fail(path: string, message: string): never {
  throw new RunResultContractError(path, message);
}

function row(value: unknown, path: string): Row {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(path, "must be an object");
  return value as Row;
}

function list(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(path, "must be an array");
  return value;
}

function time(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) fail(path, "must be integer milliseconds");
  return value;
}

function optionalTime(value: unknown, path: string): number | null {
  return value === null ? null : time(value, path);
}

function decimal(value: unknown, path: string): string {
  if (typeof value !== "string" || !DECIMAL.test(value)) fail(path, "must be a canonical decimal string");
  return value;
}

function optionalDecimal(value: unknown, path: string): string | null {
  return value === null ? null : decimal(value, path);
}

function optionalText(value: unknown, path: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") fail(path, "must be a string or null");
  return value;
}

function optionalObject(value: unknown, path: string): Record<string, unknown> | null {
  return value === null || value === undefined ? null : row(value, path);
}

function choice<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) fail(path, `must be one of ${allowed.join(", ")}`);
  return value as T;
}

function count(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) fail(path, "must be a non-negative integer");
  return value;
}

/** Validate a served `candlescope.run-result/1` value. Throws `RunResultContractError`. */
export function parseRunResult(value: unknown): RunResult {
  const body = row(value, "$");
  if (body.schema !== RUN_RESULT_SCHEMA) fail("schema", `must be ${RUN_RESULT_SCHEMA}`);
  const fills = list(body.fills, "fills").map((item, index): RunResultFill => {
    const fill = row(item, `fills[${index}]`), at = `fills[${index}]`;
    return {
      time_ms: time(fill.time_ms, `${at}.time_ms`), bar_time_ms: optionalTime(fill.bar_time_ms, `${at}.bar_time_ms`),
      side: choice(fill.side, ["BUY", "SELL"] as const, `${at}.side`), qty: decimal(fill.qty, `${at}.qty`),
      price: decimal(fill.price, `${at}.price`), fee: optionalDecimal(fill.fee, `${at}.fee`),
      order_id: optionalText(fill.order_id, `${at}.order_id`), tag: optionalText(fill.tag, `${at}.tag`),
      explanation: optionalObject(fill.explanation, `${at}.explanation`),
    };
  });
  const rejections = list(body.rejections, "rejections").map((item, index): RunResultRejection => {
    const rejection = row(item, `rejections[${index}]`), at = `rejections[${index}]`;
    return {
      time_ms: optionalTime(rejection.time_ms ?? null, `${at}.time_ms`),
      bar_time_ms: optionalTime(rejection.bar_time_ms ?? null, `${at}.bar_time_ms`),
      side: optionalText(rejection.side, `${at}.side`),
      reason: optionalText(rejection.reason, `${at}.reason`) ?? fail(`${at}.reason`, "is required"),
      order_id: optionalText(rejection.order_id, `${at}.order_id`),
      explanation: optionalObject(rejection.explanation, `${at}.explanation`),
    };
  });
  const trades = list(body.trades, "trades").map((item, index): RunResultTrade => {
    const trade = row(item, `trades[${index}]`), at = `trades[${index}]`;
    return {
      id: optionalText(trade.id, `${at}.id`) ?? fail(`${at}.id`, "is required"),
      side: choice(trade.side, ["LONG", "SHORT"] as const, `${at}.side`), qty: decimal(trade.qty, `${at}.qty`),
      entry_time_ms: time(trade.entry_time_ms, `${at}.entry_time_ms`),
      entry_bar_time_ms: optionalTime(trade.entry_bar_time_ms, `${at}.entry_bar_time_ms`),
      entry_price: decimal(trade.entry_price, `${at}.entry_price`),
      exit_time_ms: time(trade.exit_time_ms, `${at}.exit_time_ms`),
      exit_bar_time_ms: optionalTime(trade.exit_bar_time_ms, `${at}.exit_bar_time_ms`),
      exit_price: decimal(trade.exit_price, `${at}.exit_price`),
      fees: optionalDecimal(trade.fees, `${at}.fees`), net_pnl: optionalDecimal(trade.net_pnl, `${at}.net_pnl`),
      entry_explanation: optionalObject(trade.entry_explanation, `${at}.entry_explanation`),
      exit_explanation: optionalObject(trade.exit_explanation, `${at}.exit_explanation`),
    };
  });
  const position = body.open_position === null ? null : row(body.open_position, "open_position");
  const pending = list(body.pending_orders, "pending_orders").map((item, index): RunResultPendingOrder => {
    const order = row(item, `pending_orders[${index}]`), at = `pending_orders[${index}]`;
    return {
      order_id: optionalText(order.order_id, `${at}.order_id`) ?? fail(`${at}.order_id`, "is required"),
      side: optionalText(order.side, `${at}.side`) ?? fail(`${at}.side`, "is required"),
      type: optionalText(order.type, `${at}.type`) ?? fail(`${at}.type`, "is required"),
      qty: optionalDecimal(order.qty, `${at}.qty`), limit_price: optionalDecimal(order.limit_price, `${at}.limit_price`),
      stop_price: optionalDecimal(order.stop_price, `${at}.stop_price`), tag: optionalText(order.tag, `${at}.tag`),
    };
  });
  const equity = list(body.equity, "equity").map((item, index): RunResultEquityPoint => {
    const point = row(item, `equity[${index}]`), at = `equity[${index}]`;
    return { time_ms: time(point.time_ms, `${at}.time_ms`), bar_time_ms: optionalTime(point.bar_time_ms, `${at}.bar_time_ms`),
      equity: optionalDecimal(point.equity, `${at}.equity`) };
  });
  const plots = list(body.plots, "plots").map((item, index): RunResultPlot => {
    const plot = row(item, `plots[${index}]`), at = `plots[${index}]`;
    return {
      id: optionalText(plot.id, `${at}.id`) ?? fail(`${at}.id`, "is required"),
      title: optionalText(plot.title, `${at}.title`), kind: choice(plot.kind, ["line"] as const, `${at}.kind`),
      pane: optionalText(plot.pane, `${at}.pane`) ?? "main",
      points: list(plot.points, `${at}.points`).map((pair, point): [number, number | null] => {
        const entry = list(pair, `${at}.points[${point}]`);
        const value = entry[1];
        if (entry.length !== 2 || (value !== null && (typeof value !== "number" || !Number.isFinite(value)))) {
          fail(`${at}.points[${point}]`, "must be [time, finite number | null]");
        }
        return [time(entry[0], `${at}.points[${point}][0]`), value as number | null];
      }),
    };
  });
  const summary = row(body.summary, "summary");
  return {
    schema: RUN_RESULT_SCHEMA,
    source: choice(body.source, ["host-kernel", "native-pine", "external-pine"] as const, "source"),
    authority: choice(body.authority, ["HOST", "SCRIPT"] as const, "authority"),
    clock_policy: choice(body.clock_policy, ["FIXED", "FOLLOW", "FORWARD"] as const, "clock_policy"),
    fidelity: optionalText(body.fidelity, "fidelity"),
    interval: optionalText(body.interval, "interval") ?? fail("interval", "is required"),
    fills, trades, pending_orders: pending, rejections, equity, plots,
    open_position: position === null ? null : {
      side: choice(position.side, ["LONG", "SHORT"] as const, "open_position.side"),
      qty: decimal(position.qty, "open_position.qty"),
      avg_price: optionalDecimal(position.avg_price, "open_position.avg_price"),
    },
    summary: {
      initial_equity: optionalDecimal(summary.initial_equity, "summary.initial_equity"),
      final_equity: optionalDecimal(summary.final_equity, "summary.final_equity"),
      net_profit: optionalDecimal(summary.net_profit, "summary.net_profit"),
      fill_count: count(summary.fill_count, "summary.fill_count"),
      trade_count: count(summary.trade_count, "summary.trade_count"),
      winning_trades: count(summary.winning_trades, "summary.winning_trades"),
    },
  };
}
