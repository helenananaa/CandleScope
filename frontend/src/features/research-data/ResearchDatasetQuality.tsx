import { Badge, Stat } from "../../components/ui/index.js";
import { getLocale, t } from "../../i18n/index.js";
import type { LocalDatasetManifest, LocalRevisionDetails } from "./researchDataApi.js";
import { formatQualityStatus, formatResearchRows } from "./researchDataFormat.js";

export function ResearchDatasetQuality({
  manifest,
  details,
  revisionCount,
}: {
  manifest: LocalDatasetManifest;
  details: LocalRevisionDetails | null;
  revisionCount: number;
}) {
  const status = details?.quality.status;
  return (
    <section className="research-dataset-quality" data-testid="research-dataset-quality">
      <div className="research-dataset-quality-head">
        <h4>{t("local.quality")}</h4>
        <Badge tone={status === undefined ? "neutral" : status === "accepted" ? "success" : "warning"}>
          {status === undefined ? t("local.reading") : formatQualityStatus(status)}
        </Badge>
      </div>
      <div className="research-dataset-stats">
        <Stat label={t("local.rowsLabel")} value={formatResearchRows(details?.quality.rows ?? manifest.rows)} />
        <Stat label={t("local.gapsLabel")} value={details?.quality.excluded_ranges.length ?? manifest.excluded_range_count} />
        <Stat label={t("local.noVolume")} value={formatResearchRows(details?.quality.missing_volume_rows ?? 0)} />
        <Stat label={t("local.revisions")} value={manifest.revision_count ?? revisionCount} />
      </div>
      {(details?.quality.excluded_ranges.length ?? 0) > 0 && (
        <ul className="research-dataset-gaps">{details?.quality.excluded_ranges.slice(0, 3).map((gap) => (
          <li key={`${gap.start_ms}-${gap.end_ms}`}>{t("local.gapBars", { time: new Date(gap.start_ms).toLocaleString(getLocale()), count: gap.missing_bars })}</li>
        ))}</ul>
      )}
    </section>
  );
}
