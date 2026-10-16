import { t } from "../../i18n/index.js";
import type { BacktestReport } from "./backtestTypes.js";

export default function BacktestRejections({ report }: { report: BacktestReport }) {
  const count = report.metrics.rejected_order_count;
  if (!count) return null;
  const reasons = report.rejected_orders ?? [];
  const cash = reasons.filter((row) => row.reason === "SPOT_INSUFFICIENT_CASH").length;
  const base = reasons.filter((row) => row.reason === "SPOT_INSUFFICIENT_BASE").length;
  return <p role="status" data-testid="chart-strategy-rejections">{t("chartTester.result.rejections", {
    count, cash, base, other: Math.max(0, count - cash - base),
  })}</p>;
}
