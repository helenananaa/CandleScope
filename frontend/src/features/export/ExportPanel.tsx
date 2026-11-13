import { memo, useId, useMemo, type KeyboardEvent, type ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import ExportPreviewPanel from "./ExportPreviewPanel";
import { buildExportFilename } from "../../utils/exportFilename.js";
import type { ExportPreviewRuntime } from "./exportPreviewRuntime.js";
import type { ExportMetadata, ExportOptions } from "./exportTypes.js";
import { Button } from "../../components/ui/Button.js";
import { SegmentedControl } from "../../components/ui/Choice.js";
import { InlineAlert } from "../../components/ui/Display.js";
import { Checkbox, Field, Input, Select, Textarea } from "../../components/ui/Field.js";
import { Dialog } from "../../components/ui/Overlays.js";

const SCOPE_OPTIONS: ReadonlyArray<{
  value: ExportOptions["scope"];
  labelKey: "export.scope.chart" | "export.scope.main" | "export.scope.page";
  descKey: "export.scope.chartDesc" | "export.scope.mainDesc" | "export.scope.pageDesc";
}> = [
  { value: "chart", labelKey: "export.scope.chart", descKey: "export.scope.chartDesc" },
  { value: "main-pane", labelKey: "export.scope.main", descKey: "export.scope.mainDesc" },
  { value: "page", labelKey: "export.scope.page", descKey: "export.scope.pageDesc" },
];

const FORMAT_OPTIONS: ReadonlyArray<{
  value: ExportOptions["format"];
  label: string;
  descKey: "export.format.pngDesc" | "export.format.jpegDesc" | "export.format.webpDesc";
}> = [
  { value: "png", label: "PNG", descKey: "export.format.pngDesc" },
  { value: "jpeg", label: "JPEG", descKey: "export.format.jpegDesc" },
  { value: "webp", label: "WebP", descKey: "export.format.webpDesc" },
];

const SCALE_OPTIONS = ["1", "2", "3"] as const;

export interface ExportPanelProps {
  isOpen: boolean;
  options: ExportOptions;
  onOptionsChange(options: ExportOptions): void;
  onExport(options: ExportOptions): void | Promise<void>;
  onClose(): void;
  inProgress?: boolean;
  error?: string | null;
  notice?: string | null;
  metadata: ExportMetadata;
  loading?: boolean;
  indicatorComputing?: boolean;
  preview?: ExportPreviewRuntime | null;
}

function patchOptions(
  options: ExportOptions,
  onChange: (options: ExportOptions) => void,
  patch: Partial<ExportOptions>,
): void {
  const nextOptions = { ...options, ...patch };
  if (nextOptions.format === "jpeg" && nextOptions.backgroundColor === "transparent") {
    nextOptions.backgroundColor = "auto";
  }
  onChange(nextOptions);
}

/** A labelled choice with the selected option's description under it. Scripts find it by data-export-choice. */
function ExportChoice({ choice, label, hint, children }: { choice: string; label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="export-choice" data-export-choice={choice}>
      <span className="ui-field-label">{label}</span>
      {children}
      {hint ? <p className="ui-field-hint">{hint}</p> : null}
    </div>
  );
}

/** Keys typed in the dialog stay out of the page's shortcuts; Escape still reaches the overlay stack. */
function keepKeysInDialog(event: KeyboardEvent<HTMLElement>): void {
  if (event.key !== "Escape") event.stopPropagation();
}

export interface ExportSettingsProps {
  options: ExportOptions;
  onOptionsChange(options: ExportOptions): void;
  filename: string;
  error?: string | null;
  notice?: string | null;
  loading?: boolean;
  indicatorComputing?: boolean;
}

/** The settings column (exported for tests: the dialog itself renders in the overlay host). */
export function ExportSettings({ options, onOptionsChange, filename, error = null, notice = null, loading = false, indicatorComputing = false }: ExportSettingsProps) {
  const qualityId = useId();
  const patch = (next: Partial<ExportOptions>) => patchOptions(options, onOptionsChange, next);
  const scope = SCOPE_OPTIONS.find((item) => item.value === options.scope) ?? SCOPE_OPTIONS[0]!;
  const format = FORMAT_OPTIONS.find((item) => item.value === options.format) ?? FORMAT_OPTIONS[0]!;
  const quality = options.quality || 0.92;
  return (
    <div className="export-settings-panel">
      {(loading || indicatorComputing) && (
        <InlineAlert tone="warning">
          {loading ? t("export.chartLoading") : t("export.indicatorComputing")} {t("export.canContinue")}
        </InlineAlert>
      )}

      <ExportChoice choice="scope" label={t("export.scope")} hint={t(scope.descKey)}>
        <SegmentedControl fullWidth label={t("export.scope")} value={options.scope}
          options={SCOPE_OPTIONS.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
          onChange={(value) => patch({ scope: value })} />
      </ExportChoice>

      <ExportChoice choice="format" label={t("export.format")} hint={t(format.descKey)}>
        <SegmentedControl fullWidth label={t("export.format")} value={options.format}
          options={FORMAT_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
          onChange={(value) => patch({ format: value })} />
      </ExportChoice>

      <div className="export-settings-row">
        <ExportChoice choice="scale" label={t("export.scale")}>
          <SegmentedControl label={t("export.scale")} value={String(options.scale)}
            options={SCALE_OPTIONS.map((scale) => ({ value: scale, label: `${scale}x` }))}
            onChange={(value) => patch({ scale: Number(value) })} />
        </ExportChoice>
        <Field label={t("export.background")}>
          <Select
            data-export-option="background"
            value={options.backgroundColor || "auto"}
            onChange={(event) => patch({ backgroundColor: event.target.value })}
          >
            <option value="auto">{t("export.bg.auto")}</option>
            <option value="transparent" disabled={options.format === "jpeg"}>{t("export.bg.transparent")}</option>
            <option value="#0f172a">{t("export.bg.dark")}</option>
            <option value="#ffffff">{t("export.bg.white")}</option>
          </Select>
        </Field>
      </div>

      {options.format !== "png" && (
        <div className="ui-field">
          <label className="ui-field-label" htmlFor={qualityId}>{t("export.quality", { percent: Math.round(quality * 100) })}</label>
          <input
            id={qualityId}
            type="range"
            min="0.5"
            max="1"
            step="0.01"
            value={quality}
            className="export-range"
            onChange={(event) => patch({ quality: Number(event.target.value) })}
          />
        </div>
      )}

      <div className="export-checks">
        {options.scope !== "page" && (
          <Checkbox
            data-export-option="include-context"
            checked={options.includeContext}
            onChange={(event) => patch({ includeContext: event.target.checked })}
            label={t("export.includeContext")}
            description={t("export.includeContextDesc")}
          />
        )}
        <Checkbox
          data-export-option="hide-drawings"
          checked={!!options.hideDrawings}
          onChange={(event) => patch({ hideDrawings: event.target.checked })}
          label={t("export.hideDrawings")}
          description={t("export.hideDrawingsDesc")}
        />
        <Checkbox
          data-export-option="watermark-enabled"
          checked={!!options.watermarkEnabled}
          onChange={(event) => patch({ watermarkEnabled: event.target.checked })}
          label={t("export.watermark")}
          description={t("export.watermarkDesc")}
        />
      </div>

      {options.watermarkEnabled && (
        <Field label={t("export.watermarkText")}>
          <Textarea
            data-export-option="watermark-text"
            rows={2}
            placeholder={t("export.watermarkPlaceholder")}
            value={options.watermarkText || ""}
            onChange={(event) => patch({ watermarkText: event.target.value })}
          />
        </Field>
      )}

      <Field label={t("export.filename")} hint={<span className="export-filename">{filename}</span>}>
        <Input
          value={options.filenamePrefix || "candlescope"}
          onChange={(event) => patch({ filenamePrefix: event.target.value })}
        />
      </Field>

      {error && <InlineAlert tone="danger" className="export-panel-message">{error}</InlineAlert>}
      {notice && !error && <InlineAlert tone="success" className="export-panel-message">{notice}</InlineAlert>}
    </div>
  );
}

const ExportPanel = memo(function ExportPanel({
  isOpen,
  options,
  onOptionsChange,
  onExport,
  onClose,
  inProgress = false,
  error = null,
  notice = null,
  metadata,
  loading = false,
  indicatorComputing = false,
  preview = null,
}: ExportPanelProps) {
  useLocale();
  const filenamePreview = useMemo(() => buildExportFilename({
    prefix: options.filenamePrefix || "candlescope",
    ...(metadata.exchange === undefined ? {} : { exchange: metadata.exchange }),
    ...(metadata.marketType === undefined ? {} : { marketType: metadata.marketType }),
    ...(metadata.symbol === undefined ? {} : { symbol: metadata.symbol }),
    ...(metadata.interval === undefined ? {} : { interval: metadata.interval }),
    scope: options.scope,
    format: options.format,
  }), [metadata.exchange, metadata.interval, metadata.marketType, metadata.symbol, options.filenamePrefix, options.format, options.scope]);
  const previewIsCurrent = Boolean(preview?.url && preview?.optionsKey && preview?.optionsKey === preview?.currentOptionsKey);
  const canSavePreview = Boolean(preview?.blob && previewIsCurrent && !preview?.loading && !preview?.error);
  const saveDisabled = inProgress || preview?.loading || !canSavePreview;

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      title={t("export.title")}
      size="lg"
      dismissible={!inProgress}
      className="export-panel export-workspace export-exclude"
      onKeyDown={keepKeysInDialog}
      footer={<>
        <Button onClick={onClose} disabled={inProgress}>{t("export.closeBtn")}</Button>
        <Button
          variant="primary"
          data-export-action="save"
          onClick={() => onExport(options)}
          disabled={saveDisabled}
          title={preview?.loading ? t("export.previewLoadingTitle") : canSavePreview ? t("export.savePreview") : t("export.needPreview")}
        >
          {inProgress ? t("export.saving") : preview?.loading ? t("export.generating") : t("export.saveCurrent")}
        </Button>
      </>}
    >
      <div className="export-workspace-body">
        <ExportSettings options={options} onOptionsChange={onOptionsChange} filename={preview?.filename || filenamePreview}
          error={error} notice={notice} loading={loading} indicatorComputing={indicatorComputing} />

        <ExportPreviewPanel
          filename={preview?.filename || filenamePreview}
          isCurrent={previewIsCurrent}
          {...(preview === null ? {} : {
            previewUrl: preview.url,
            width: preview.width,
            height: preview.height,
            mimeType: preview.mimeType,
            generatedAt: preview.generatedAt,
            loading: preview.loading,
            error: preview.error,
            onRefresh: preview.refreshPreview,
          })}
        />
      </div>
    </Dialog>
  );
});

export default ExportPanel;
