import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { BacktestFillRecord } from "../backtestTypes.js";
import type { ContinuousView } from "./continuousView.js";

const emptyRows = { fills: [], equity: [] };

export function readContinuousAccountRows(manager: ContinuousStrategyDataManager, view: ContinuousView | null) {
  if (!view) return emptyRows;
  const { id } = view.identity;
  const fills = manager.rows(id, "fills", view.identity, 100).filter(
    (row): row is BacktestFillRecord => row !== null && typeof row === "object" && !Array.isArray(row),
  );
  return { fills, equity: manager.rows(id, "equity_curve", view.identity, 200) };
}

export function continuousFillTimeMs(row: BacktestFillRecord): number | null {
  const raw = row.event_time_ms;
  if (typeof raw !== "number" && (typeof raw !== "string" || !/^\d+$/.test(raw))) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 && value <= 8640000000000000 ? value : null;
}
