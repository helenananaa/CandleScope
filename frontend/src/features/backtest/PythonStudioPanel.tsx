import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Button, Checkbox, Field, InlineAlert, Select, Textarea } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { BacktestApiClient, BacktestSnapshot, StrategyRevisionRecord } from "./backtestApi.js";
import { isPythonTrustedLocalEnabled } from "./backtestFlags.js";
import { useControlCommands } from "../app-control/useControlCommands.js";
import { command } from "../app-control/commandRegistry.js";
import { array, bool, choice, empty, object, record, text } from "../app-control/commandSchema.js";
import { readControlFile } from "../app-control/controlFiles.js";
import {
  PYTHON_TEMPLATES,
  PYTHON_UNSUPPORTED,
  TRUSTED_LOCAL_FACT_KEYS,
  trustedLocalConfirmLabel,
  assessCoverage,
  assertRequiredBundleFiles,
  canStartTrustedLocal,
  filesFromInput,
  generatedManifestPreview,
  hostOwnsOrdersCopy,
  mapStudioFailure,
  templateById,
  warmupRowsFromSchema,
  zipFilesToBase64,
  type PythonBundleFileMap,
  type PythonBundleIdentity,
  type PythonRuntimeMode,
  type PythonStudioGate,
  type StudioFailure,
} from "./pythonStudio.js";

interface PythonStudioPanelProps {
  api: BacktestApiClient;
  loading: boolean;
  snapshot: BacktestSnapshot | null;
  datasetId: string;
  startTimeMs: number;
  endTimeMs: number;
  schemaParameters: Record<string, string | number | boolean>;
  selectedRevisionId: string;
  restored?: {
    revisionId: string | null;
    bundleIdentity: PythonBundleIdentity | null;
    smokePassed: boolean;
    runtimeMode: PythonRuntimeMode;
    trustedConfirmed: boolean;
  } | null;
  trustedFlagEnabled?: boolean;
  onLoading: (loading: boolean) => void;
  onNotice: (notice: string | null) => void;
  onError: (error: string | null) => void;
  onRevisionReady: (revision: StrategyRevisionRecord, identity: PythonBundleIdentity) => void;
  onGateChange: (gate: PythonStudioGate) => void;
}

export default function PythonStudioPanel({
  api,
  loading,
  snapshot,
  datasetId,
  startTimeMs,
  endTimeMs,
  schemaParameters,
  selectedRevisionId,
  restored,
  trustedFlagEnabled = isPythonTrustedLocalEnabled(),
  onLoading,
  onNotice,
  onError,
  onRevisionReady,
  onGateChange,
}: PythonStudioPanelProps) {
  const locale = useLocale();
  const defaultTemplate = PYTHON_TEMPLATES[0]!;
  const [templateId, setTemplateId] = useState(defaultTemplate.id);
  const [files, setFiles] = useState<PythonBundleFileMap>(defaultTemplate.files);
  const [inspectResult, setInspectResult] = useState<Record<string, unknown> | null>(null);
  const [bundleIdentity, setBundleIdentity] = useState<PythonBundleIdentity | null>(restored?.bundleIdentity ?? null);
  const [smokePassed, setSmokePassed] = useState(Boolean(restored?.smokePassed));
  const [runtimeMode, setRuntimeMode] = useState<PythonRuntimeMode>(restored?.runtimeMode ?? "SANDBOXED_LOCAL");
  const [trustedConfirmed, setTrustedConfirmed] = useState(Boolean(restored?.trustedConfirmed));
  const [showManifest, setShowManifest] = useState(false);
  const [failure, setFailure] = useState<StudioFailure | null>(null);
  const template = templateById(templateId);
  const missing = assertRequiredBundleFiles(files);
  const inspectedParameters = (inspectResult?.manifest as { parameters?: Array<Record<string, unknown>> } | undefined)?.parameters;
  const warmupRows = warmupRowsFromSchema(
    Array.isArray(inspectedParameters)
      ? inspectedParameters
      : Object.entries(schemaParameters).map(([name, value]) => ({ name, default: value })),
    schemaParameters,
  );
  const coverage = assessCoverage({
    snapshotRows: snapshot?.row_count ?? 0,
    startTimeMs,
    endTimeMs,
    warmupRows,
  });
  const trustedReady = runtimeMode !== "TRUSTED_LOCAL"
    || canStartTrustedLocal({ trustedFlagEnabled, confirmed: trustedConfirmed });
  const canCreateRun = Boolean(selectedRevisionId) && smokePassed && coverage.ready && trustedReady;

  useEffect(() => {
    onGateChange({
      revisionId: selectedRevisionId || null,
      bundleIdentity,
      smokePassed,
      runtimeMode,
      trustedConfirmed,
      coverageReady: coverage.ready,
      coverageReason: coverage.reason,
      canCreateRun,
    });
  }, [
    bundleIdentity,
    canCreateRun,
    coverage.ready,
    coverage.reason,
    onGateChange,
    runtimeMode,
    selectedRevisionId,
    smokePassed,
    trustedConfirmed,
  ]);

  const reportFailure = useCallback((reason: unknown) => {
    const mapped = mapStudioFailure(reason);
    setFailure(mapped);
    onError(`${mapped.code}: ${mapped.message} · ${mapped.nextStep}`);
  }, [onError]);

  const applyFiles = useCallback((next: PythonBundleFileMap) => {
    setFiles(next);
    setInspectResult(null);
    setSmokePassed(false);
    setFailure(null);
  }, []);

  const handleTemplate = useCallback(() => {
    const next = templateById(templateId);
    if (!next) return;
    applyFiles(next.files);
    onNotice(t("python.notice.template", { label: next.label }));
  }, [applyFiles, onNotice, templateId]);

  const handleImport = useCallback(async (list: FileList | null) => {
    if (!list || list.length === 0) return;
    try {
      const next = await filesFromInput(list);
      const absent = assertRequiredBundleFiles(next);
      if (absent.length) {
        throw new Error(`BUNDLE_INCOMPLETE: missing ${absent.join(", ")}`);
      }
      applyFiles(next);
      onNotice(t("python.notice.imported"));
    } catch (reason) {
      reportFailure(reason);
    }
  }, [applyFiles, onNotice, reportFailure]);

  const handleInspect = useCallback(async () => {
    onLoading(true);
    onError(null);
    setFailure(null);
    try {
      const inspected = await api.inspectPythonBundle(zipFilesToBase64(files));
      setInspectResult(inspected);
      onNotice(t("python.notice.inspected"));
    } catch (reason) {
      reportFailure(reason);
    } finally {
      onLoading(false);
    }
  }, [api, files, onError, onLoading, onNotice, reportFailure]);

  const handleFreeze = useCallback(async () => {
    onLoading(true);
    onError(null);
    setFailure(null);
    try {
      const created = await api.createPythonBundle(zipFilesToBase64(files));
      const revision = await api.createPythonRevision(String(created.bundle_id));
      const identity: PythonBundleIdentity = {
        bundle_id: String(created.bundle_id),
        bundle_hash: String(created.bundle_hash),
        manifest_hash: String(created.manifest_hash),
        source_hash: String(created.source_hash),
      };
      if (created.sdk_hash) identity.sdk_hash = String(created.sdk_hash);
      if (created.requirements_lock_hash) {
        identity.requirements_lock_hash = String(created.requirements_lock_hash);
      }
      setBundleIdentity(identity);
      setSmokePassed(false);
      onRevisionReady(revision, identity);
      onNotice(t("python.notice.frozen", {
        bundle: identity.bundle_id ?? "",
        revision: revision.revision_id,
      }));
    } catch (reason) {
      reportFailure(reason);
    } finally {
      onLoading(false);
    }
  }, [api, files, onError, onLoading, onNotice, onRevisionReady, reportFailure]);

  const handleSmoke = useCallback(async () => {
    if (!snapshot || !selectedRevisionId) return;
    onLoading(true);
    onError(null);
    setFailure(null);
    try {
      const maxWindow = Math.min(endTimeMs, startTimeMs + 7 * 86_400_000);
      await api.smokeStrategyRevision(selectedRevisionId, {
        dataset_id: datasetId,
        snapshot_hash: snapshot.snapshot_hash,
        start_time_ms: startTimeMs,
        end_time_ms: maxWindow,
        parameters: schemaParameters,
        python_runtime_mode: runtimeMode,
        python_trusted_confirmed: runtimeMode === "TRUSTED_LOCAL" && trustedConfirmed,
      });
      setSmokePassed(true);
      onNotice(t("python.notice.smoke"));
    } catch (reason) {
      setSmokePassed(false);
      reportFailure(reason);
    } finally {
      onLoading(false);
    }
  }, [
    api,
    datasetId,
    endTimeMs,
    onError,
    onLoading,
    onNotice,
    reportFailure,
    runtimeMode,
    schemaParameters,
    selectedRevisionId,
    snapshot,
    startTimeMs,
    trustedConfirmed,
  ]);

  const inspectHashes = useMemo(() => {
    if (!inspectResult && !bundleIdentity) return null;
    return {
      bundle: String(inspectResult?.bundle_hash ?? bundleIdentity?.bundle_hash ?? ""),
      source: String(inspectResult?.source_hash ?? bundleIdentity?.source_hash ?? ""),
      manifest: String(inspectResult?.manifest_hash ?? bundleIdentity?.manifest_hash ?? ""),
    };
  }, [bundleIdentity, inspectResult]);
  useControlCommands(() => ({ id: "python-studio", title: "Python bundle editing, inspection and trust", context: () => ({ files, selectedRevisionId, runtimeMode, trustedConfirmed, loading }),
    snapshot: () => ({ files, templateId, missing, inspectResult, bundleIdentity, smokePassed, runtimeMode, trustedConfirmed, trustedFlagEnabled, requiredAcknowledgements: TRUSTED_LOCAL_FACT_KEYS, coverage, canCreateRun, failure }), commands: [
      command("template", "Apply an existing Python strategy template.", object({ id: choice(["sma_cross", "rsi_reversion", "breakout"]) }), ({ id }) => { const next = templateById(id); if (!next) throw new Error("TEMPLATE_UNAVAILABLE"); setTemplateId(id); applyFiles(next.files); }, { available: () => !loading }),
      command("files", "Edit a typed bundle file map. The existing bundle service validates its paths, format and capability contract before freezing.", object({ files: record }), ({ files }) => {
        if (Object.keys(files).length > 128 || Object.entries(files).some(([path, value]) => typeof value !== "string" || !path || path.length > 256 || path.startsWith("/") || path.includes("\\") || path.includes(":") || path.split("/").includes(".."))) throw new Error("BUNDLE_FILES_INVALID");
        applyFiles(files as PythonBundleFileMap);
      }, { available: () => !loading }),
      command("importZip", "Import a staged Python bundle ZIP using the existing filesFromInput validation.", object({ fileRef: text(96) }), async ({ fileRef }) => { const next = await filesFromInput([await readControlFile(fileRef)]); if (assertRequiredBundleFiles(next).length) throw new Error("BUNDLE_INCOMPLETE"); applyFiles(next); }, { available: () => !loading }),
      command("inspectBundle", "Inspect the current bundle through the existing backend.", empty, () => handleInspect(), { available: () => !loading && !missing.length }),
      command("freeze", "Freeze an inspected bundle and create its immutable revision.", empty, () => handleFreeze(), { available: () => !loading && !!inspectResult }),
      command("smoke", "Run the existing guarded Python smoke workflow with the current revision, snapshot and trust gate.", empty, () => handleSmoke(), { available: () => !loading && !!selectedRevisionId && !!snapshot && trustedReady }),
      command("sandbox", "Use sandboxed local Python and revoke the trusted confirmation.", empty, () => { setRuntimeMode("SANDBOXED_LOCAL"); setTrustedConfirmed(false); }),
      command("trustedLocal", "Select trusted local Python only with explicit app.trust launch scope, the existing feature flag, and all listed facts acknowledged.", object({ confirmed: bool, acknowledgements: array(choice(TRUSTED_LOCAL_FACT_KEYS), 5) }), ({ confirmed, acknowledgements }) => {
        if (confirmed && (new Set(acknowledgements).size !== TRUSTED_LOCAL_FACT_KEYS.length || !TRUSTED_LOCAL_FACT_KEYS.every((key) => acknowledgements.includes(key)))) throw new Error("TRUST_ACKNOWLEDGEMENTS_REQUIRED");
        setRuntimeMode("TRUSTED_LOCAL"); setTrustedConfirmed(confirmed);
      }, { requiredScope: "app.trust", available: () => trustedFlagEnabled && !loading }),
    ] }));

  return (
    <div className="python-studio" data-testid="python-strategy-studio">
      <h4>{t("backtest.pythonStudio")}</h4>
      <p className="research-panel-copy" data-testid="python-host-owns-report">{hostOwnsOrdersCopy()}</p>
      <div className="python-studio-row">
        <Field label={t("backtest.template")}>
          <Select size="sm" value={templateId} onChange={(event) => setTemplateId(event.target.value as typeof templateId)}>
            {PYTHON_TEMPLATES.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </Select>
        </Field>
        <Button size="sm" disabled={loading} onClick={handleTemplate} data-testid="python-template-create">
          {t("backtest.fromTemplate")}
        </Button>
      </div>
      {template && <p className="research-panel-copy">{t(template.descriptionKey, {}, locale)}</p>}
      <label className="research-file-field">
        <span>{t("backtest.importZip")}</span>
        <input
          type="file"
          accept=".zip,application/zip"
          data-testid="python-import-zip"
          onChange={(event) => void handleImport(event.target.files)}
        />
      </label>
      <label className="research-file-field">
        <span>{t("backtest.importDir")}</span>
        <input
          type="file"
          data-testid="python-import-directory"
          multiple
          ref={(node) => {
            if (node) node.setAttribute("webkitdirectory", "");
          }}
          onChange={(event) => void handleImport(event.target.files)}
        />
      </label>
      {missing.length > 0 && <InlineAlert tone="warning">{t("backtest.missingFiles", { list: missing.join("、") })}</InlineAlert>}
      <Checkbox label={t("backtest.viewManifest")} checked={showManifest} onChange={(event) => setShowManifest(event.target.checked)} />
      {showManifest && (
        <Textarea
          className="research-json-editor"
          rows={8}
          readOnly
          value={generatedManifestPreview(files)}
          data-testid="python-generated-manifest"
        />
      )}
      <div className="research-button-row">
        <Button size="sm" disabled={loading || missing.length > 0} onClick={() => void handleInspect()}>
          {t("backtest.inspect")}
        </Button>
        <Button size="sm" disabled={loading || !inspectResult} onClick={() => void handleFreeze()}>
          {t("backtest.freeze")}
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={loading || !selectedRevisionId || !snapshot || !trustedReady}
          onClick={() => void handleSmoke()}
          data-testid="python-smoke"
        >
          {smokePassed ? t("backtest.smokeOk") : t("backtest.smokeRun")}
        </Button>
      </div>
      {inspectHashes && (
        <div className="python-evidence" data-testid="python-bundle-identity">
          <strong>{t("backtest.bundleHash", { hash: `${inspectHashes.bundle.slice(0, 18)}…` })}</strong>
          <span>{t("backtest.sourceManifestHashes", {
            source: `${inspectHashes.source.slice(0, 18)}…`,
            manifest: `${inspectHashes.manifest.slice(0, 18)}…`,
          })}</span>
          <span>{t("backtest.unsupportedList", { list: PYTHON_UNSUPPORTED.join("；") })}</span>
        </div>
      )}
      <div className="python-evidence" data-testid="python-runtime-mode">
        <strong>{t("backtest.runtimeIso")}</strong>
        <div className="python-runtime-options" role="radiogroup" aria-label={t("backtest.runtimeIso")}>
          {(["SANDBOXED_LOCAL", "TRUSTED_LOCAL"] as const).map((mode) => (
            <label key={mode}>
              <input
                type="radio"
                name="python-runtime-mode"
                checked={runtimeMode === mode}
                onChange={() => {
                  setRuntimeMode(mode);
                  if (mode === "SANDBOXED_LOCAL") setTrustedConfirmed(false);
                }}
              />
              <span>{mode === "SANDBOXED_LOCAL" ? t("backtest.sandboxed") : t("backtest.trusted")}</span>
            </label>
          ))}
        </div>
        {runtimeMode === "TRUSTED_LOCAL" && (
          <div className="python-trusted-facts" data-testid="python-trusted-facts">
            <ul>
              {TRUSTED_LOCAL_FACT_KEYS.map((key) => <li key={key}>{t(key, {}, locale)}</li>)}
            </ul>
            <small>{t("backtest.flagState", { state: trustedFlagEnabled ? t("backtest.flagOn") : t("backtest.flagOff") })}</small>
            <Checkbox
              label={trustedLocalConfirmLabel()}
              checked={trustedConfirmed}
              onChange={(event) => setTrustedConfirmed(event.target.checked)}
              data-testid="python-trusted-confirm"
            />
          </div>
        )}
      </div>
      <div className="python-coverage" data-testid="python-coverage">
        <Badge tone={coverage.ready ? "success" : "warning"}>{coverage.ready ? t("backtest.coverOk") : t("backtest.coverNo")}</Badge>
        <div>
          <strong>{t("backtest.coverageRows", { rows: coverage.snapshotRows, warmup: coverage.warmupRows })}</strong>
          <small>{coverage.reason}</small>
        </div>
      </div>
      {failure && (
        <InlineAlert tone="danger" title={`${failure.code}${failure.line ? ` · ${failure.line}:${failure.column}` : ""}`}>
          <span data-testid="python-smoke-failure">{failure.message}</span>
          <small className="python-next-step">{t("backtest.nextStep", { step: failure.nextStep })}</small>
        </InlineAlert>
      )}
    </div>
  );
}
