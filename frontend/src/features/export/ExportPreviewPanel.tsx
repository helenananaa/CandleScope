import { memo, useState } from "react";
import { Icon } from "../../components/icons/Icon.js";
import { Button, IconButton } from "../../components/ui/Button.js";
import { SegmentedControl } from "../../components/ui/Choice.js";
import { InlineAlert } from "../../components/ui/Display.js";
import { EmptyState } from "../../components/ui/EmptyState.js";
import { getDateTimeLocale, t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";

type PreviewZoomMode = "fit" | "50" | "100";

const ZOOM_OPTIONS: ReadonlyArray<{ value: PreviewZoomMode; labelKey?: "export.fit"; label?: string }> = [
  { value: "fit", labelKey: "export.fit" },
  { value: "50", label: "50%" },
  { value: "100", label: "100%" },
];

type PreviewTone = "muted" | "accent" | "success" | "warning";

export interface ExportPreviewPanelProps {
  previewUrl?: string | null;
  filename?: string;
  width?: number;
  height?: number;
  mimeType?: string;
  generatedAt?: number | null;
  loading?: boolean;
  error?: string | null;
  isCurrent?: boolean;
  onRefresh?: () => unknown;
}

function formatGeneratedAt(value: number | null | undefined): string {
  if (!value) return t("export.notGenerated");
  try {
    return new Date(value).toLocaleTimeString(getDateTimeLocale(), { hour12: false });
  } catch {
    return t("export.justNow");
  }
}

function formatMime(mimeType: string, filename: string | undefined): string {
  if (mimeType) return mimeType.replace("image/", "").toUpperCase();
  const ext = String(filename || "").split(".").pop();
  return ext ? ext.toUpperCase() : "--";
}

const ExportPreviewPanel = memo(function ExportPreviewPanel({
  previewUrl,
  filename,
  width = 0,
  height = 0,
  mimeType = "",
  generatedAt = null,
  loading = false,
  error = null,
  isCurrent = false,
  onRefresh,
}: ExportPreviewPanelProps) {
  useLocale();
  const [zoomMode, setZoomMode] = useState<PreviewZoomMode>("fit");
  const hasPreview = Boolean(previewUrl);
  const formatLabel = formatMime(mimeType, filename);
  const [statusText, statusTone]: [string, PreviewTone] = loading
    ? [hasPreview ? t("export.updating") : t("export.creating"), "accent"]
    : hasPreview && isCurrent ? [t("export.saveIsThis"), "success"]
      : hasPreview ? [t("export.configChanged"), "warning"] : [t("export.waitPreview"), "muted"];
  const details = hasPreview
    ? [formatLabel, width && height ? `${width} × ${height}` : null, `${t("export.generated")} ${formatGeneratedAt(generatedAt)}`].filter(Boolean)
    : [];

  return (
    <section className="export-preview-panel export-exclude" aria-label={t("export.previewAria")}>
      <div className="export-preview-header">
        <div className="export-preview-heading">
          <h3 className="export-preview-title">{t("export.previewTitle")}</h3>
          <p className="export-preview-meta">
            <span className="export-preview-status" data-tone={statusTone}>{statusText}</span>
            {details.map((detail) => <span key={detail}>{detail}</span>)}
          </p>
        </div>
        <SegmentedControl size="sm" label={t("export.zoom")} value={zoomMode}
          options={ZOOM_OPTIONS.map((item) => ({ value: item.value, label: item.labelKey ? t(item.labelKey) : item.label }))}
          onChange={setZoomMode} />
        <IconButton
          size="sm"
          variant="secondary"
          className="export-preview-refresh"
          onClick={onRefresh}
          disabled={loading}
          label={t("export.refreshPreview")}
          icon={<Icon name="refresh" size={14} />}
        />
      </div>

      <div className={`export-preview-frame ${loading ? "loading" : ""} ${!isCurrent && hasPreview ? "stale" : ""}`} data-zoom={zoomMode}>
        {hasPreview && (
          <img
            src={previewUrl || undefined}
            alt={t("export.previewAlt")}
            className="export-preview-image"
          />
        )}

        {!hasPreview && loading && (
          <EmptyState compact icon={<Icon name="camera" size={24} />} title={t("export.firstPreview")} />
        )}

        {!hasPreview && !loading && !error && (
          <EmptyState compact icon={<Icon name="camera" size={24} />} title={t("export.clickRefresh")} />
        )}

        {loading && hasPreview && (
          <div className="export-preview-overlay">{t("export.updating")}</div>
        )}

        {error && !loading && (
          <InlineAlert tone="danger" className="export-preview-error" title={t("export.previewFailed")}
            action={<Button size="sm" onClick={onRefresh}>{t("export.regenerate")}</Button>}>
            {error}
          </InlineAlert>
        )}
      </div>
    </section>
  );
});

export default ExportPreviewPanel;
