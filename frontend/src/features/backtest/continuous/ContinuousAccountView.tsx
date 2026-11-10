import React, { useMemo } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { ContinuousView } from "./continuousView.js";

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
const text = (value: unknown): string => typeof value === "number" || typeof value === "string" ? String(value) : "—";
function time(value: unknown): string {
  const number = Number(value);
  return value !== undefined && Number.isFinite(number) && Math.abs(number) <= 8640000000000000
    ? new Date(number).toISOString().replace("T", " ").replace(".000Z", " UTC") : "—";
}

/** Render only the Manager's complete committed financial identity. */
export default function ContinuousAccountView({ manager, view }: { manager: ContinuousStrategyDataManager; view: ContinuousView }) {
  useLocale();
  const fills = useMemo(() => manager.rows(view.identity.id, "fills", view.identity, 100), [manager, view]);
  const equity = useMemo(() => manager.rows(view.identity.id, "equity_curve", view.identity, 200), [manager, view]);
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
      <tbody>{fills.map((value, index) => { const row = object(value); return <tr key={index}><td>{time(row.event_time_ms)}</td><td>{text(row.side)}</td><td>{text(row.qty)}</td><td>{text(row.price)}</td></tr>; })}</tbody></table>
  </section>;
}
