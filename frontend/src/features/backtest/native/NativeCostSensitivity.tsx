import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";

export interface NativeCostMatrix {
  status: string;
  baseline_reexecution_verified: boolean;
  scenarios: Array<{ name: string; status: string; executed: boolean;
    metrics: { fill_count: number; fee_total: string; ending_equity: string; ending_position: string } }>;
}

export function NativeCostSensitivity({ matrix }: { matrix: NativeCostMatrix | undefined }) {
  const locale = useLocale();
  if (!matrix) return null;
  if (matrix.status === "SKIPPED_BY_REQUEST") return <p className="native-report-caption">{t("native.cost.skipped")}</p>;
  if (matrix.status !== "COMPLETED" || !matrix.baseline_reexecution_verified || !Array.isArray(matrix.scenarios)) return null;
  const labels: Record<string, Parameters<typeof t>[0]> = { BASELINE: "native.cost.baseline", COSTS_PLUS_25_PERCENT: "native.cost.plus25",
    COSTS_PLUS_50_PERCENT: "native.cost.plus50", LATENCY_PLUS_ONE_TIER: "native.cost.latency", PARTICIPATION_DOWN_ONE_TIER: "native.cost.participation" };
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 8 });
  const display = (value: unknown) => value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : number.format(Number(value));
  return <details className="native-report-disclosure native-cost-matrix" open>
    <summary>{t("native.cost.title")}</summary><p>{t("native.cost.help")}</p>
    <div className="native-table"><table><thead><tr><th>{t("backtest.scenario")}</th><th>{t("native.cost.fills")}</th>
      <th>{t("native.cost.fees")}</th><th>{t("native.cost.equity")}</th><th>{t("native.cost.position")}</th><th>{t("native.cost.status")}</th></tr></thead>
      <tbody>{matrix.scenarios.map((row) => { const complete = row.status === "COMPLETED" && row.executed;
        return <tr key={row.name}><th scope="row">{t(Object.hasOwn(labels, row.name) ? labels[row.name]! : "native.cost.unknown")}</th>
          <td>{complete ? display(row.metrics?.fill_count) : "—"}</td><td>{complete ? display(row.metrics?.fee_total) : "—"}</td>
          <td>{complete ? display(row.metrics?.ending_equity) : "—"}</td><td>{complete ? display(row.metrics?.ending_position) : "—"}</td>
          <td>{t(complete ? "native.cost.executed" : "native.cost.notApplicable")}</td></tr>; })}</tbody></table></div>
  </details>;
}
