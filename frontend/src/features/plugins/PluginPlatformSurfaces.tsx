import { describeError } from "../../i18n/serverErrors.js";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { PluginNativeField } from "./PluginNativeFields.js";
import SandboxPluginFrame from "./SandboxPluginFrame.js";
import { defaultForPluginSchema } from "./pluginSchemaDefaults.js";
import { formatPluginValue } from "./pluginViewFormatting.js";
import type {
  JsonValue,
  PluginCommandContribution,
  PluginCommandFileInput,
  PluginDeclarativeViewContribution,
  PluginJsonSchema,
  PluginPlatformRuntime,
  PluginSandboxViewContribution,
  PluginSettingsContribution,
  PluginViewContribution,
  PluginViewProjection,
} from "./pluginPlatformTypes.js";
import { Icon } from "../../components/icons/Icon.js";

export { PluginSettingsPanel } from "./PluginCenter.js";

function isSandboxView(
  contribution: PluginViewContribution,
): contribution is PluginSandboxViewContribution {
  return contribution.configuration.renderer === "sandbox";
}

export class PluginUiErrorBoundary extends React.Component<
  React.PropsWithChildren,
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error): void {
    console.error("Plugin UI failed safely", error);
  }

  render() {
    return this.state.failed
      ? <div className="plugin-ui-fallback" role="alert">{t("plugin.host.uiUnavailable")}</div>
      : this.props.children;
  }
}

function objectDefault(command: PluginCommandContribution): Record<string, JsonValue> {
  const schema = command.configuration.inputSchema;
  if (!schema) return {};
  const value = defaultForPluginSchema(schema);
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

interface NativeSaveDestination {
  createWritable(): Promise<{
    write(value: Blob): Promise<void>;
    close(): Promise<void>;
    abort?(): Promise<void>;
  }>;
}

type NativeSavePicker = (options: { suggestedName: string }) => Promise<NativeSaveDestination>;

interface FileDownloadReceipt {
  downloadId: string;
  name: string;
  mediaType: string;
  size: number;
  sha256: string;
}

function commandNativeSchema(command: PluginCommandContribution): PluginJsonSchema | null {
  const schema = command.configuration.inputSchema;
  if (!schema || schema.type !== "object") return schema ?? null;
  const hidden = new Set((command.configuration.fileInputs ?? []).map((item) => item.field));
  const properties = Object.fromEntries(
    Object.entries(schema.properties ?? {}).filter(([key]) => !hidden.has(key)),
  );
  if (!Object.keys(properties).length) return null;
  return {
    ...schema,
    properties,
    required: (schema.required ?? []).filter((key) => !hidden.has(key)),
  };
}

function fileDownloadReceipt(value: JsonValue): FileDownloadReceipt | null {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value.fileDownload;
  if (candidate == null || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  if (
    Object.keys(candidate).sort().join(",") !== "downloadId,mediaType,name,sha256,size"
    || typeof candidate.downloadId !== "string"
    || !/^ufd_[A-Za-z0-9_-]{40,128}$/.test(candidate.downloadId)
    || typeof candidate.name !== "string"
    || !/^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$/.test(candidate.name)
    || typeof candidate.mediaType !== "string"
    || !/^[a-z0-9][a-z0-9.+-]{0,63}\/[a-z0-9][a-z0-9.+-]{0,63}$/.test(candidate.mediaType)
    || typeof candidate.size !== "number"
    || !Number.isSafeInteger(candidate.size)
    || candidate.size < 0
    || candidate.size > 128 * 1024
    || typeof candidate.sha256 !== "string"
    || !/^sha256:[0-9a-f]{64}$/.test(candidate.sha256)
  ) throw new Error("Plugin returned an invalid file download receipt");
  return candidate as unknown as FileDownloadReceipt;
}

async function writeSelectedDestination(
  runtime: PluginPlatformRuntime,
  pluginId: string,
  config: PluginCommandFileInput,
  destination: NativeSaveDestination,
  receipt: FileDownloadReceipt,
): Promise<void> {
  if (
    config.mode !== "save"
    || receipt.name !== config.suggestedName
    || !config.accept.includes(receipt.mediaType)
    || receipt.size > config.maxBytes
  ) throw new Error(t("plugin.host.fileDownloadContract"));
  const blob = await runtime.actions.downloadUserFile(pluginId, receipt.downloadId);
  if (blob.size !== receipt.size || blob.size > config.maxBytes) {
    throw new Error(t("plugin.host.fileReceiptMismatch"));
  }
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()));
  const actual = `sha256:${[...digest].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
  if (actual !== receipt.sha256) throw new Error(t("plugin.host.fileIntegrityFailed"));
  const writable = await destination.createWritable();
  try {
    await writable.write(blob);
    await writable.close();
  } catch (error) {
    await writable.abort?.().catch(() => undefined);
    throw error;
  }
}

function Modal({ title, onClose, children, testId }: React.PropsWithChildren<{
  title: string;
  onClose(): void;
  testId: string;
}>) {
  const element = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    element.current?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return (
    <div className="plugin-modal-overlay" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="plugin-modal" role="dialog" aria-modal="true" aria-label={title} data-testid={testId} ref={element} tabIndex={-1} onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); onClose(); }
        if (event.key !== "Tab") return;
        const controls = Array.from(element.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]') ?? []).filter((control) => control.getClientRects().length > 0);
        const first = controls[0]; const last = controls.at(-1);
        if (event.shiftKey && (document.activeElement === first || document.activeElement === element.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === element.current)) { event.preventDefault(); first?.focus(); }
      }}>
        <header><h2>{title}</h2><button type="button" aria-label={t("plugin.host.close")} onClick={onClose}><Icon name="close" size={14} /></button></header>
        <div className="plugin-modal-body">{children}</div>
      </section>
    </div>
  );
}

function CommandPalette({ runtime }: { runtime: PluginPlatformRuntime }) {
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [input, setInput] = useState<Record<string, JsonValue>>({});
  const [running, setRunning] = useState(false);
  const [fileBusy, setFileBusy] = useState<string | null>(null);
  const [fileStatus, setFileStatus] = useState<Record<string, string>>({});
  const saveDestinations = useRef(new Map<string, NativeSaveDestination>());
  const commands = runtime.view.registries.commandPalette.filter((item) => item.title.toLowerCase().includes(query.toLowerCase()));
  const selected = runtime.view.registries.commandPalette.find((item) => item.id === selectedId) ?? null;
  useEffect(() => {
    if (!runtime.view.paletteOpen) {
      setQuery("");
      setSelectedId(null);
      setFileBusy(null);
      setFileStatus({});
      saveDestinations.current.clear();
    }
  }, [runtime.view.paletteOpen]);
  if (!runtime.view.paletteOpen) return null;
  const fileInputs = selected?.configuration.fileInputs ?? [];
  const nativeSchema = selected ? commandNativeSchema(selected) : null;
  const filesReady = fileInputs.every((item) => typeof input[item.field] === "string" && String(input[item.field]).length > 0);
  return (
    <Modal title={t("plugin.host.paletteTitle")} onClose={runtime.actions.closePalette} testId="plugin-command-palette">
      <input autoFocus className="plugin-command-search" placeholder={t("plugin.host.searchCommands")} value={query} onChange={(event) => setQuery(event.target.value)} />
      <div className="plugin-command-layout">
        <nav>
          {commands.map((command) => (
            <button
              type="button"
              key={command.id}
              className={selectedId === command.id ? "active" : ""}
              onClick={() => {
                setSelectedId(command.id);
                setInput(objectDefault(command));
                setFileBusy(null);
                setFileStatus({});
                saveDestinations.current.clear();
              }}
            >
              <strong>{command.title}</strong><small>{command.id}</small>
            </button>
          ))}
        </nav>
        <div className="plugin-command-form">
          {!selected && <p>{t("plugin.host.selectCommand")}</p>}
          {selected && (
            <>
              {nativeSchema && (
                <PluginNativeField
                  name="root"
                  schema={nativeSchema}
                  value={input}
                  locale={locale}
                  onChange={(value) => {
                    if (value && typeof value === "object" && !Array.isArray(value)) setInput(value);
                  }}
                />
              )}
              {fileInputs.map((fileInput) => (
                <div className="plugin-command-file" key={fileInput.field} data-plugin-file-mode={fileInput.mode}>
                  <strong>{fileInput.mode === "open" ? t("plugin.host.selectInputFile") : t("plugin.host.selectSaveDestination")}</strong>
                  <small>{t("plugin.host.fileContract", { types: fileInput.accept.join(", "), bytes: fileInput.maxBytes })}</small>
                  {fileInput.mode === "open" ? (
                    <input
                      type="file"
                      accept={fileInput.accept.join(",")}
                      disabled={fileBusy !== null || running}
                      onChange={async (event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (!file) return;
                        if (!fileInput.accept.includes(file.type) || file.size < 1 || file.size > fileInput.maxBytes) {
                          setFileStatus((current) => ({ ...current, [fileInput.field]: t("plugin.host.fileOutOfScope") }));
                          return;
                        }
                        setFileBusy(fileInput.field);
                        try {
                          const selection = await runtime.actions.stageUserFile(selected.id, fileInput.field, file);
                          setInput((current) => ({ ...current, [fileInput.field]: selection.handle }));
                          setFileStatus((current) => ({ ...current, [fileInput.field]: t("plugin.host.fileSelectedRead", { name: selection.name }) }));
                        } catch (error) {
                          setFileStatus((current) => ({ ...current, [fileInput.field]: error instanceof Error ? describeError(error, error.message) : t("plugin.host.fileSelectionFailed") }));
                        } finally {
                          setFileBusy(null);
                        }
                      }}
                    />
                  ) : (
                    <button
                      type="button"
                      disabled={fileBusy !== null || running}
                      onClick={async () => {
                        const picker = (window as unknown as { showSaveFilePicker?: NativeSavePicker }).showSaveFilePicker;
                        if (!picker || !fileInput.suggestedName) {
                          setFileStatus((current) => ({ ...current, [fileInput.field]: t("plugin.host.nativeSaveRequired") }));
                          return;
                        }
                        setFileBusy(fileInput.field);
                        try {
                          const destination = await picker.call(window, { suggestedName: fileInput.suggestedName });
                          const selection = await runtime.actions.prepareUserFileSave(selected.id, fileInput.field);
                          saveDestinations.current.set(fileInput.field, destination);
                          setInput((current) => ({ ...current, [fileInput.field]: selection.handle }));
                          setFileStatus((current) => ({ ...current, [fileInput.field]: t("plugin.host.fileSelectedWrite", { name: selection.name }) }));
                        } catch (error) {
                          setFileStatus((current) => ({ ...current, [fileInput.field]: error instanceof Error ? describeError(error, error.message) : t("plugin.host.saveNotSelected") }));
                        } finally {
                          setFileBusy(null);
                        }
                      }}
                    >
                      {t("plugin.host.chooseDestination")}
                    </button>
                  )}
                  {fileStatus[fileInput.field] && <span role="status">{fileStatus[fileInput.field]}</span>}
                </div>
              ))}
              <button
                type="button"
                disabled={!runtime.view.managementAvailable || running || fileBusy !== null || !filesReady}
                onClick={async () => {
                  setRunning(true);
                  let commandInvoked = false;
                  try {
                    const result = await runtime.actions.invokeCommand(selected.id, input);
                    commandInvoked = true;
                    const receipt = fileDownloadReceipt(result);
                    const output = fileInputs.find((item) => item.mode === "save");
                    if (output && !receipt) throw new Error("Plugin did not return the selected file output");
                    if (receipt) {
                      const destination = output ? saveDestinations.current.get(output.field) : undefined;
                      if (!output || !destination) throw new Error("Plugin returned a file without a selected destination");
                      await writeSelectedDestination(runtime, selected.pluginId, output, destination, receipt);
                    }
                    runtime.actions.closePalette();
                  } catch (error) {
                    if (commandInvoked) runtime.actions.clearNotice();
                    const statusField = fileInputs.find((item) => item.mode === "save")?.field
                      ?? fileInputs[0]?.field;
                    if (statusField) {
                      setFileStatus((current) => ({
                        ...current,
                        [statusField]: error instanceof Error
                          ? error.message
                          : t("plugin.host.commandFileFailed"),
                      }));
                    }
                    setInput((current) => {
                      const next = { ...current };
                      for (const item of fileInputs) delete next[item.field];
                      return next;
                    });
                    saveDestinations.current.clear();
                  } finally {
                    setRunning(false);
                  }
                }}
              >
                {running ? t("plugin.host.running") : t("plugin.host.runCommand")}
              </button>
              {!runtime.view.managementAvailable && <small>{t("plugin.host.managementRequired")}</small>}
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

export function SettingsSurface({ runtime, contribution }: {
  runtime: PluginPlatformRuntime;
  contribution: PluginSettingsContribution;
}) {
  const locale = useLocale();
  const [value, setValue] = useState<Record<string, JsonValue>>(contribution.configuration.defaults);
  const [loading, setLoading] = useState(runtime.view.managementAvailable);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const readSettings = runtime.actions.readSettings;
  useEffect(() => {
    let active = true;
    if (!runtime.view.managementAvailable) return () => { active = false; };
    setLoading(true);
    setLoadError(null);
    readSettings(contribution.id)
      .then((next) => { if (active) setValue(next); })
      .catch(() => { if (active) setLoadError(t("plugin.host.settingsLoadFailed")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [contribution.id, readSettings, runtime.view.managementAvailable]);
  return (
    <Modal title={contribution.title} onClose={runtime.actions.closeSettings} testId="plugin-settings">
      {!runtime.view.managementAvailable && <p>{t("plugin.host.settingsReadonly")}</p>}
      {loadError && <p role="alert">{loadError}</p>}
      {loading ? <p>{t("plugin.host.settingsLoading")}</p> : (
        <PluginNativeField
          name="root"
          schema={contribution.configuration.schema}
          value={value}
          locale={locale}
          onChange={(next) => {
            if (next && typeof next === "object" && !Array.isArray(next)) setValue(next);
          }}
        />
      )}
      <button
        type="button"
        disabled={!runtime.view.managementAvailable || loading || saving || loadError !== null}
        onClick={async () => {
          setSaving(true);
          try { setValue(await runtime.actions.writeSettings(contribution.id, value)); } catch { /* notice published */ }
          finally { setSaving(false); }
        }}
      >
        {saving ? t("plugin.host.saving") : t("plugin.host.saveSettings")}
      </button>
    </Modal>
  );
}

function ViewContent({ contribution, projection }: {
  contribution: PluginDeclarativeViewContribution;
  projection: PluginViewProjection | undefined;
}) {
  if (!projection || projection.state === "empty") return <p>{contribution.configuration.emptyState}</p>;
  if (projection.state === "error") return <p role="alert">{t("plugin.host.viewInvalid")}</p>;
  if ("rows" in projection.data) {
    if (contribution.configuration.renderer === "list") {
      return (
        <ul className="plugin-native-list">
          {projection.data.rows.map((row, index) => (
            <li key={index}>{contribution.configuration.fields.map((field) => (
              <span key={field.field}><strong>{field.label}</strong> {formatPluginValue(row[field.field], field.format)}</span>
            ))}</li>
          ))}
        </ul>
      );
    }
    return (
      <div className="plugin-native-table-wrap">
        <table className="plugin-native-table">
          <thead><tr>{contribution.configuration.fields.map((field) => <th key={field.field}>{field.label}</th>)}</tr></thead>
          <tbody>{projection.data.rows.map((row, index) => (
            <tr key={index}>{contribution.configuration.fields.map((field) => <td key={field.field}>{formatPluginValue(row[field.field], field.format)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    );
  }
  const values = projection.data.values;
  return (
    <dl className="plugin-native-detail">
      {contribution.configuration.fields.map((field) => (
        <React.Fragment key={field.field}>
          <dt>{field.label}</dt><dd>{formatPluginValue(values[field.field], field.format)}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function ViewSurface({ runtime, contribution }: {
  runtime: PluginPlatformRuntime;
  contribution: PluginViewContribution;
}) {
  if (isSandboxView(contribution)) {
    return (
      <aside
        className={`plugin-view-surface plugin-view-${contribution.configuration.slot}`}
        data-plugin-slot={contribution.configuration.slot}
        data-plugin-view={contribution.id}
        data-plugin-renderer="sandbox"
        aria-label={contribution.title}
      >
        <header><h2>{contribution.title}</h2><button type="button" aria-label={t("plugin.host.close")} onClick={runtime.actions.closeView}><Icon name="close" size={14} /></button></header>
        <PluginUiErrorBoundary>
          <SandboxPluginFrame runtime={runtime} contribution={contribution} />
        </PluginUiErrorBoundary>
      </aside>
    );
  }
  const candidate = runtime.view.snapshot?.views.find((item) => item.id === contribution.id);
  const projection = candidate
    && candidate.pluginId === contribution.pluginId
    && candidate.slot === contribution.configuration.slot
    && candidate.renderer === contribution.configuration.renderer
    ? candidate
    : undefined;
  const projectionMismatch = candidate !== undefined && projection === undefined;
  const primaryCommand = contribution.configuration.primaryCommand
    ? runtime.view.registries.commandPalette.find((item) => item.pluginId === contribution.pluginId && item.localId === contribution.configuration.primaryCommand)
      ?? runtime.view.registries.topToolbar.find((item) => item.pluginId === contribution.pluginId && item.localId === contribution.configuration.primaryCommand)
      ?? runtime.view.registries.chartContextMenu.find((item) => item.pluginId === contribution.pluginId && item.localId === contribution.configuration.primaryCommand)
    : null;
  return (
    <aside
      className={`plugin-view-surface plugin-view-${contribution.configuration.slot}`}
      data-plugin-slot={contribution.configuration.slot}
      data-plugin-view={contribution.id}
      aria-label={contribution.title}
    >
      <header><h2>{contribution.title}</h2><button type="button" aria-label={t("plugin.host.close")} onClick={runtime.actions.closeView}><Icon name="close" size={14} /></button></header>
      <PluginUiErrorBoundary>
        {projectionMismatch
          ? <p role="alert">{t("plugin.host.viewMetadataMismatch")}</p>
          : <ViewContent contribution={contribution} projection={projection} />}
      </PluginUiErrorBoundary>
      {primaryCommand && (
        <button
          type="button"
          data-plugin-primary-command={primaryCommand.id}
          disabled={!runtime.view.managementAvailable}
          onClick={() => void runtime.actions.invokeCommand(primaryCommand.id, {}).catch(() => undefined)}
        >
          {primaryCommand.title}
        </button>
      )}
    </aside>
  );
}

export default function PluginPlatformSurfaces({ runtime }: { runtime: PluginPlatformRuntime }) {
  useLocale();
  const openView = useMemo(
    () => [...runtime.view.registries.sidePanel, ...runtime.view.registries.bottomPanel].find((item) => item.id === runtime.view.openViewId) ?? null,
    [runtime.view.openViewId, runtime.view.registries.bottomPanel, runtime.view.registries.sidePanel],
  );
  const openSettings = runtime.view.registries.settings.find((item) => item.id === runtime.view.openSettingsId) ?? null;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "p" && runtime.view.registries.commandPalette.length) {
        event.preventDefault();
        runtime.actions.openPalette();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [runtime.actions, runtime.view.registries.commandPalette.length]);
  const platformError = runtime.view.error ? t("plugin.host.platformUnavailable", { error: runtime.view.error }) : null;
  return (
    <PluginUiErrorBoundary>
      <CommandPalette runtime={runtime} />
      {openSettings && <SettingsSurface runtime={runtime} contribution={openSettings} />}
      {openView && <ViewSurface key={openView.id} runtime={runtime} contribution={openView} />}
      {platformError && <div className="plugin-platform-notice plugin-platform-error" role="alert" title={platformError}>{platformError}</div>}
      {runtime.view.notice && (
        <button type="button" className="plugin-platform-notice" title={runtime.view.notice} onClick={runtime.actions.clearNotice}>{runtime.view.notice}</button>
      )}
    </PluginUiErrorBoundary>
  );
}
