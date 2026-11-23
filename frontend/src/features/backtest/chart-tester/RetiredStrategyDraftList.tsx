import { Badge, Button, InlineAlert } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import type { RetiredStrategyDraft } from "./retiredPyneStrategy.js";

/**
 * Pyne drafts from builds before PR #105. Each one is named and marked Retired; it cannot be
 * opened, edited or run, and the only action is the user's delete.
 */
export function RetiredStrategyDraftList({ drafts, locale, deleteFailed = false, onDelete }: {
  drafts: readonly RetiredStrategyDraft[];
  locale: string;
  deleteFailed?: boolean;
  onDelete(id: string): void;
}) {
  if (drafts.length === 0) return null;
  return <div className="chart-strategy-start-retired-list" data-testid="chart-strategy-retired-drafts">
    {drafts.map((record) => (
      <div key={record.id} className="chart-strategy-start-retired" data-retired="true" data-draft-id={record.id}>
        <div className="chart-strategy-start-retired-name">
          <strong>{record.displayName}</strong>
          <small>
            <Badge tone="warning">{t("strategyCollection.retiredBadge")}</Badge>
            {record.updatedAt !== null && (
              <time dateTime={new Date(record.updatedAt).toISOString()}>{new Date(record.updatedAt).toLocaleString(locale)}</time>
            )}
          </small>
        </div>
        <Button size="sm" variant="ghost" aria-label={t("chartTester.deleteRetiredDraft", { name: record.displayName })}
          onClick={() => onDelete(record.id)}>
          {t("chartTester.deleteDraft")}
        </Button>
      </div>
    ))}
    <p className="chart-strategy-start-retired-note">{t("strategyCollection.pyneRetired")}</p>
    {deleteFailed && <InlineAlert tone="danger">{t("chartTester.deleteRetiredDraftFailed")}</InlineAlert>}
  </div>;
}
