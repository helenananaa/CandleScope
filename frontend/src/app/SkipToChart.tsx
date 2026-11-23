import { Button } from "../components/ui/index.js";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";

/** The active chart cell (market and replay workspaces); it takes focus. */
const ACTIVE_CHART_SELECTOR = ".multi-chart-cell.active";

/**
 * First stop on a chart page: shown when it has keyboard focus, it moves focus past the header and
 * the drawing toolbar to the active chart, where the arrow keys move between charts.
 */
export default function SkipToChart() {
  useLocale();
  return (
    <Button variant="primary" size="sm" className="skip-to-chart"
      onClick={() => document.querySelector<HTMLElement>(ACTIVE_CHART_SELECTOR)?.focus()}>
      {t("shell.skipToChart")}
    </Button>
  );
}
