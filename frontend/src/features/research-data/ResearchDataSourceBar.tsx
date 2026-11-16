import { Button } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { ordinarySourceLabel } from "./researchDataSourceModel.js";
import type { ResearchSourceRefV1 } from "./researchDataTypes.js";

export function ResearchDataSourceBar({
  source,
  currentChartEnabled = true,
  onOpenLibrary,
  onSelectCurrentChart,
  sourceLabel,
}: {
  source: ResearchSourceRefV1 | null;
  currentChartEnabled?: boolean;
  onOpenLibrary(): void;
  onSelectCurrentChart?(): void;
  sourceLabel?: string;
}) {
  const label = source === null
    ? t("research.source.none")
    : ordinarySourceLabel(source.kind);
  return (
    <div className="research-data-source-bar" data-testid="research-data-source-bar">
      <span className="research-data-source-value" title={sourceLabel ?? label} data-empty={source === null ? "true" : undefined}>
        <small>{t("research.drawer.title")}</small>
        {sourceLabel ?? label}
      </span>
      {source?.kind !== "CURRENT_CHART" && currentChartEnabled && onSelectCurrentChart ? (
        <Button size="sm" data-testid="research-source-use-current-chart" onClick={onSelectCurrentChart}>
          {t("strategy.useCurrentChart")}
        </Button>
      ) : null}
      <Button size="sm" onClick={onOpenLibrary}>{t("research.source.openLibrary")}</Button>
    </div>
  );
}
