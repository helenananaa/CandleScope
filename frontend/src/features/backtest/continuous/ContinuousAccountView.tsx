import React from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { continuousFillTimeMs, type readContinuousAccountRows } from "./continuousAccountRows.js";
import type { ContinuousView } from "./continuousView.js";

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
const text = (value: unknown): string => typeof value === "number" || typeof value === "string" ? String(value) : "—";
function time(value: unknown): string {
  const number = Number(value);
  return value !== undefined && Number.isFinite(number) && Math.abs(number) <= 8640000000000000
    ? new Date(number).toISOString().replace("T", " ").replace(".000Z", " UTC") : "—";
}

/** Read while publishing a committed Manager identity, then render the same snapshot. */
export default function ContinuousAccountView({ rows, view, onLocateTrade }: {
  rows: ReturnType<typeof readContinuousAccountRows>; view: ContinuousView; onLocateTrade?(timeMs: number): void;
}) {
  useLocale();
  const { fills, equity } = rows;
  const values = equity.map((row) => Number(object(row).equity)).filter(Number.isFinite);
  const low = Math.min(...values), high = Math.max(...values);
  const points = values.map((value, index) => `${index * 600 / Math.max(1, values.length - 1)},${80 - (value - low) * 75 / Math.max(1e-12, high - low)}`).join(" ");
  const valuation = object(view.summary.valuation), account = object(view.summary.account);
  return <section aria-label={t("continuous.account")} data-continuous-account={view.identity.id}>
    <dl className="continuous-account"><div><dt>{t("continuous.equity")}</dt><dd>{text(valuation.equity)}</dd></div>
      <div><dt>{t("continuous.position")}</dt><dd>{text(account.position_qty)}</dd></div>
      <div><dt>{t("continuous.sequence")}</dt><dd>{view.identity.sequence}</dd></div></dl>
    {values.length > 1 && <svg viewBox="0 0 600 90" role="img" aria-label={t("continuous.recentEquity")}><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" /></svg>}
    <h3>{t("continuous.fills")}</h3><table><thead><tr>{(["continuous.time", "continuous.side", "continuous.quantity", "continuous.price"] as const).map((key) => <th key={key}>{t(key)}</th>)}</tr></thead>
      <tbody>{fills.map((value, index) => { const at = continuousFillTimeMs(value);
        return <tr key={index}><td>{at !== null && at <= view.identity.event_time_ms && onLocateTrade && !view.stale
          ? <button type="button" className="strategy-dock-button" onClick={() => onLocateTrade(at)}>{time(at)}</button>
          : time(value.event_time_ms)}</td><td>{text(value.side)}</td><td>{text(value.qty)}</td><td>{text(value.price)}</td></tr>; })}</tbody></table>
  </section>;
}
