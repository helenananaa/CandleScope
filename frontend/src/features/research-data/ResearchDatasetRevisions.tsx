import { t } from "../../i18n/index.js";
import { Badge, Button, InlineAlert } from "../../components/ui/index.js";
import { confirmAction } from "../../components/ui/overlay/overlayApi.js";
import type {
  LocalDatasetManifest,
  LocalDatasetRevision,
  LocalRevisionComparison,
} from "./researchDataApi.js";
import { formatResearchDate, formatResearchRows } from "./researchDataFormat.js";

export function ResearchDatasetRevisions({
  revisions,
  comparison,
  busy,
  onCompare,
  onActivate,
}: {
  manifest: LocalDatasetManifest;
  revisions: LocalDatasetRevision[];
  comparison: LocalRevisionComparison | null;
  busy: string | null;
  onCompare(dataEpoch: string): void;
  onActivate(dataEpoch: string): void;
}) {
  return (
    <div className="local-revisions">
      <h4>{t("local.revisionHistory")}</h4>
      <ul className="local-revision-list" data-testid="research-dataset-revisions">
        {revisions.map((revision) => (
          <li key={revision.data_epoch} data-current={revision.current ? "true" : undefined}>
            <span>
              <code>{revision.data_epoch.slice(7, 17)}</code>
              <small>{t("local.revisionRows", { date: formatResearchDate(revision.imported_at), rows: formatResearchRows(revision.rows), status: revision.quality_status })}</small>
            </span>
            {revision.current ? <Badge tone="accent">{t("local.current")}</Badge> : <span className="local-revision-actions">
              <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => onCompare(revision.data_epoch)}>{t("local.compare")}</Button>
              <Button size="sm" disabled={busy !== null} onClick={() => void (async () => {
                if (!(await confirmAction({ title: t("local.switchConfirm"), confirmLabel: t("local.switchRevision") }))) return;
                onActivate(revision.data_epoch);
              })()}>{t("local.switchRevision")}</Button>
            </span>}
          </li>
        ))}
      </ul>
      {comparison !== null && (
        <InlineAlert title={t("local.diff")}>
          {t("local.diffStats", { added: comparison.added, removed: comparison.removed, changed: comparison.changed, unchanged: comparison.unchanged })}
        </InlineAlert>
      )}
    </div>
  );
}
