import { PineLibraryInputs } from "./PineLibraryInputs.js";
import { pineLibraryParams, parsePineLibraries } from "./pineLibraryModel.js";
import { PineContextInputs } from "./PineContextInputs.js";
import { pineContextParams, parsePineContexts } from "./pineContextModel.js";
import { PineCurrencyInputs } from "./PineCurrencyInputs.js";
import { pineCurrencyParams, parsePineCurrencyRates } from "./pineCurrencyModel.js";
/** Editor for hosted and frontend indicator scripts. */
import { describeError } from "../../i18n/serverErrors.js";
import { Icon } from "../../components/icons/Icon.js";
import { Button, IconButton } from "../../components/ui/Button.js";
import { Disclosure, InlineAlert } from "../../components/ui/Display.js";
import { Checkbox, Field, Input, Select, Textarea } from "../../components/ui/Field.js";
import { lazy, Suspense, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { useExtensionEditorTheme } from "../../editor/extensionTheme.js";
import type * as Monaco from "monaco-editor";
import {
  configurePineHostCapabilities,
  registerPineLanguageSupport,
} from "../../editor/pineLanguage";
import { registerScriptTheme, getScriptEditorOptions } from "../../editor/scriptTheme";
import { fetchScriptRuntimes } from "../../services/indicatorApi.js";
import { FRONTEND_SCRIPT_LANGUAGE, withFrontendScriptRuntime } from "./frontendScriptContract.js";
import {
  resolveAvailableScriptLanguage,
  resolveScriptEditorProfile,
  runtimeForScriptLanguage,
} from "./scriptRuntimeCatalog.js";
import { createScriptEditorDraft, editScriptEditorSource, scriptEditorSource, switchScriptEditorLanguage } from "./scriptEditorDraft.js";
import type { ChangeEvent, ReactNode } from "react";
import type {
  IndicatorDefinition,
  IndicatorParams,
  ScriptRuntimeCatalog,
} from "./indicatorTypes.js";

const Editor = lazy(() => import("../../editor/LocalMonacoEditor.js"));
/** Track whether Pine providers have been registered globally */
let pineRegistered = false;

function optionalRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export interface IndicatorEditorSource extends Omit<IndicatorDefinition, "id"> {
  id: string | null;
}

export interface IndicatorEditorValue extends Omit<IndicatorEditorSource, "name" | "script"> {
  id: string | null;
  name: string;
  script: string;
  params: IndicatorParams;
  language: string;
  securityMode?: string;
}

export interface IndicatorEditorPreviewState {
  id: string | null;
  error: string | null;
  visible: boolean;
  isComputing: boolean;
}

export interface IndicatorEditorProps {
  allowedScriptLanguages?: readonly string[];
  indicator: IndicatorEditorSource;
  onSave(value: IndicatorEditorValue): void | Promise<void>;
  onBack(): void;
  onPreview(value: IndicatorEditorValue): void;
  onForkBuiltin?: (value: IndicatorEditorValue) => void;
  readOnly?: boolean;
  previewState?: IndicatorEditorPreviewState | null;
  onToggleVisibility(id: string): void;
}

export default function IndicatorEditor({
  allowedScriptLanguages,
  indicator,
  onSave,
  onBack,
  onPreview,
  onForkBuiltin,
  readOnly = false,
  previewState, // { id: string | null, error: string | null, visible: boolean, isComputing: boolean }
  onToggleVisibility
}: IndicatorEditorProps) {
  useLocale();
  const extensionEditorTheme = useExtensionEditorTheme("");
  const [name, setName] = useState(indicator?.name || "My Indicator");
  const [draft, setDraft] = useState(() => createScriptEditorDraft(indicator.script, Boolean(indicator.id)));
  const modelId = useId();
  const [language, setLanguage] = useState(indicator?.language || "");
  const [libraryJson, setLibraryJson] = useState(() => JSON.stringify(indicator.params?.__pineLibraries || {}, null, 2));
  const [contextJson, setContextJson] = useState(() => JSON.stringify(indicator.params?.__pineContexts || [], null, 2));
  const [currencyJson, setCurrencyJson] = useState(() => indicator.params?.__pineCurrencyRates ? JSON.stringify(indicator.params.__pineCurrencyRates, null, 2) : "");
  const librariesValid = useMemo(() => { try { parsePineLibraries(libraryJson); parsePineContexts(contextJson); parsePineCurrencyRates(currencyJson); return true; } catch { return false; } }, [libraryJson, contextJson, currencyJson]);

  const [hostText, setHostText] = useState(() => JSON.stringify(indicator.params?.__pineHost || {}, null, 2));
  const [sessionEpoch, setSessionEpoch] = useState(() => String(indicator.params?.__pineSessionEpoch || "0"));
  const [pineAlerts, setPineAlerts] = useState(indicator.params?.__pineAlerts === true);
  const hostConfig = useMemo(() => {
    try {
      const value: unknown = JSON.parse(hostText);
      if (!optionalRecord(value)) throw new Error("Expected a JSON object");
      return { value, error: "" };
    } catch (error) { return { value: {}, error: String(error) }; }
  }, [hostText]);
  const hostParams = useMemo(() => ({ ...indicator.params,
    ...(language === "pine" ? { __pineHost: hostConfig.value, __pineSessionEpoch: sessionEpoch, __pineAlerts: pineAlerts } : {}),
  }), [indicator.params, language, hostConfig, sessionEpoch, pineAlerts]);
  const [runtimeCatalog, setRuntimeCatalog] = useState<ScriptRuntimeCatalog | null>(null);
  const [runtimeCatalogError, setRuntimeCatalogError] = useState<string | null>(null);
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const allowedRuntimeCatalog = useMemo(() => {
    if (!runtimeCatalog || allowedScriptLanguages === undefined) {
      return runtimeCatalog;
    }
    const allowed = new Set(
      allowedScriptLanguages.map((item) => item.trim().toLowerCase()),
    );
    return {
      ...runtimeCatalog,
      languages: runtimeCatalog.languages.filter(
        (descriptor) => allowed.has(descriptor.id.trim().toLowerCase()),
      ),
    };
  }, [allowedScriptLanguages, runtimeCatalog]);

  const selectedLanguage = useMemo(
    () => allowedRuntimeCatalog
      ? resolveAvailableScriptLanguage(
          allowedRuntimeCatalog,
          language || indicator?.language,
        )
      : null,
    [allowedRuntimeCatalog, indicator?.language, language],
  );
  const selectedRuntime = useMemo(
    () => allowedRuntimeCatalog && selectedLanguage
      ? runtimeForScriptLanguage(allowedRuntimeCatalog, selectedLanguage)
      : null,
    [allowedRuntimeCatalog, selectedLanguage],
  );
  const editorProfile = useMemo(
    () => allowedRuntimeCatalog && selectedLanguage
      ? resolveScriptEditorProfile(allowedRuntimeCatalog, selectedLanguage)
      : null,
    [allowedRuntimeCatalog, selectedLanguage],
  );
  const editorParams = useMemo(() => librariesValid && selectedLanguage?.id === "pine"
    ? pineCurrencyParams(pineContextParams(pineLibraryParams(hostParams, libraryJson), contextJson), currencyJson)
    : pineCurrencyParams(pineContextParams(pineLibraryParams(hostParams, "{}"), "[]"), ""),
  [hostParams, selectedLanguage?.id, libraryJson, contextJson, currencyJson, librariesValid]);
  const languageReady = Boolean(selectedLanguage?.available && editorProfile);
  const script = scriptEditorSource(draft, selectedLanguage?.id || language, editorProfile?.starterSource || "");
  const requestedLanguageId = (language || indicator?.language || "").trim();
  const requestedLanguage = allowedRuntimeCatalog?.languages.find(
    (candidate) => candidate.id === requestedLanguageId,
  ) ?? null;
  const displayedLanguage = selectedLanguage ?? requestedLanguage;
  const missingRequestedLanguage = Boolean(
    allowedRuntimeCatalog
      && requestedLanguageId
      && !requestedLanguage,
  );
  const pineHostCapabilities = useMemo(
    () => optionalRecord(selectedRuntime?.meta.hostCapabilities),
    [selectedRuntime],
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetchScriptRuntimes(controller.signal).then((catalog) => {
      setRuntimeCatalog(withFrontendScriptRuntime(catalog));
      setRuntimeCatalogError(null);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setRuntimeCatalog(withFrontendScriptRuntime({ schemaVersion: 1, defaultLanguage: FRONTEND_SCRIPT_LANGUAGE, languages: [], runtimes: [] }));
      setRuntimeCatalogError(
        error instanceof Error ? describeError(error, error.message) : String(error),
      );
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (editorProfile?.pineEnhancements) {
      configurePineHostCapabilities(pineHostCapabilities);
    }
  }, [editorProfile?.pineEnhancements, pineHostCapabilities]);

  const handlePreview = useCallback(() => {
    if (readOnly || !selectedLanguage || !editorProfile || (selectedLanguage.id === "pine" && (!librariesValid || Boolean(hostConfig.error)))) return;
    onPreview({
      id: indicator?.id || previewState?.id || null,
      name,
      script,
      params: editorParams,
      description: indicator?.description || "",
      language: selectedLanguage.id,
      isPreset: indicator?.isPreset || false,
    });
  }, [
    editorProfile,
    editorParams,
    librariesValid,
    indicator,
    name,
    onPreview,
    previewState,
    readOnly,
    script,
    selectedLanguage,
    hostConfig.error,
  ]);

  const handleSave = useCallback(() => {
    if (readOnly || !selectedLanguage || !editorProfile || (selectedLanguage.id === "pine" && (!librariesValid || Boolean(hostConfig.error)))) return;
    void onSave({
      id: indicator?.id || previewState?.id || null,
      name,
      script,
      params: editorParams,
      description: indicator?.description || "",
      language: selectedLanguage.id,
      isPreset: indicator?.isPreset || false,
    });
  }, [
    editorProfile,
    editorParams,
    librariesValid,
    indicator,
    name,
    onSave,
    previewState,
    readOnly,
    script,
    selectedLanguage,
    hostConfig.error,
  ]);

  const handleLanguageChange = useCallback((event: ChangeEvent<HTMLSelectElement>) => {
    const nextLanguageId = event.target.value;
    if (!allowedRuntimeCatalog) return;
    const nextLanguage = allowedRuntimeCatalog.languages.find(
      (candidate) => candidate.id === nextLanguageId && candidate.available,
    );
    if (!nextLanguage) return;
    const nextProfile = resolveScriptEditorProfile(
      allowedRuntimeCatalog,
      nextLanguage,
    );
    setDraft((current) => switchScriptEditorLanguage(
      current, selectedLanguage?.id || language, script,
      nextLanguage.id, nextProfile.starterSource,
    ));
    setLanguage(nextLanguage.id);
  }, [allowedRuntimeCatalog, language, script, selectedLanguage]);


  /**
   * Called before Monaco mounts — register theme so it's available
   * for the first render.
   */
  const handleBeforeMount = useCallback((monaco: typeof Monaco) => {
    registerScriptTheme(monaco);
    if (!pineRegistered) {
      registerPineLanguageSupport(monaco);
      pineRegistered = true;
    }
  }, []);

  /**
   * Called when Monaco mounts to attach editor actions.
   */
  const handleEditorMount = useCallback((
    editor: Monaco.editor.IStandaloneCodeEditor,
    monaco: typeof Monaco,
  ) => {
    editorRef.current = editor;


    if (!readOnly) {
      // Add Ctrl+Enter shortcut to run
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
        // Trigger preview via DOM click (simplest way to use latest state)
        document.querySelector<HTMLButtonElement>(".indicator-editor-run")?.click();
      });
    }

    // Focus the editor
    editor.focus();
  }, [readOnly]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Don't dispose global providers — they persist across editor instances
      editorRef.current = null;
    };
  }, []);

  const languageLabel = displayedLanguage?.name || requestedLanguageId || t("indicator.editor.fallbackLanguage");
  const actionsDisabled = !languageReady || (selectedLanguage?.id === "pine" && !librariesValid);
  // One status line under the editor; its tone colours the text.
  const status: { tone: "muted" | "danger" | "accent" | "success"; text: ReactNode } = readOnly
    ? { tone: "muted", text: t("indicator.editor.builtinHint") }
    : !languageReady
      ? { tone: "danger", text: runtimeCatalogError
        ? t("indicator.editor.noRuntime")
        : allowedRuntimeCatalog && requestedLanguageId
          ? t("indicator.editor.savedLangUnavailable", { language: requestedLanguageId })
          : allowedRuntimeCatalog
            ? t("indicator.editor.noRuntimeAvailable")
            : t("indicator.editor.discovering") }
      : previewState?.error
        ? { tone: "danger", text: previewState.error }
        : previewState?.isComputing
          ? { tone: "accent", text: t("indicator.editor.computingData") }
          : previewState?.id
            ? { tone: "success", text: t("indicator.editor.runOk") }
            : { tone: "muted", text: editorProfile?.pineEnhancements
              ? <>{t("indicator.editor.pineApiHint")} <code>ta.sma()</code> <code>plot()</code> <code>plotshape()</code> <code>input.int()</code></>
              : t("indicator.editor.communityRuntime", { language: selectedLanguage?.name || t("indicator.editor.fallbackLanguage"), runtime: selectedRuntime?.name || "plugin" }) };

  return (
    <div className="indicator-editor">
      <div className="indicator-editor-toolbar">
        <div className="indicator-editor-heading">
          <span className="indicator-editor-title">
            {readOnly ? t("indicator.editor.builtinRef") : t("indicator.editor.title", { language: languageLabel })}
          </span>
          <span className="indicator-editor-subtitle">{name}</span>
        </div>

        <div className="indicator-editor-toolbar-actions">
          {previewState?.id && !readOnly && (
            <IconButton
              size="sm"
              label={previewState.visible ? t("indicator.editor.hideOnChart") : t("indicator.editor.showOnChart")}
              icon={<Icon name={previewState.visible ? "eye" : "eye-off"} size={15} />}
              onClick={() => {
                if (previewState.id) onToggleVisibility(previewState.id);
              }}
            />
          )}
          {readOnly ? (
            <Button
              size="sm"
              variant="primary"
              className="indicator-editor-save"
              disabled={actionsDisabled}
              onClick={() => {
                if (!selectedLanguage || !editorProfile) return;
                onForkBuiltin?.({
                  ...indicator,
                  name,
                  script,
                  params: editorParams,
                  language: selectedLanguage.id,
                });
              }}
            >
              {t("indicator.editor.fork")}
            </Button>
          ) : (
            <>
              <Button size="sm" className="indicator-editor-run" disabled={actionsDisabled} onClick={handlePreview}>
                {previewState?.isComputing ? t("indicator.editor.computing") : t("indicator.editor.run")}
              </Button>
              <Button size="sm" variant="primary" className="indicator-editor-save" disabled={actionsDisabled} onClick={handleSave}>
                {t("indicator.editor.save")}
              </Button>
            </>
          )}
          <span className="indicator-editor-divider" aria-hidden="true" />
          <IconButton
            size="sm"
            label={t("indicator.editor.close")}
            icon={<Icon name="close" size={15} />}
            onClick={onBack}
          />
        </div>
      </div>

      <div className="indicator-editor-body">
        <Field label={t("indicator.editor.name")}>
          <Input
            value={name}
            onChange={(e) => {
              if (!readOnly) setName(e.target.value);
            }}
            readOnly={readOnly}
          />
        </Field>

        <div className="indicator-editor-script-head">
          <span className="indicator-editor-script-label">{t("indicator.editor.script", { language: languageLabel })}</span>
          {!readOnly && (
            <Select
              size="sm"
              aria-label={t("indicator.editor.language")}
              value={selectedLanguage?.id || requestedLanguageId}
              onChange={handleLanguageChange}
              disabled={!allowedRuntimeCatalog || allowedRuntimeCatalog.languages.length === 0}
            >
              {missingRequestedLanguage && (
                <option value={requestedLanguageId} disabled>
                  {t("indicator.editor.languageUnavailable", { language: requestedLanguageId })}
                </option>
              )}
              {allowedRuntimeCatalog?.languages.map((descriptor) => (
                <option
                  key={`${descriptor.runtimeId || "legacy"}:${descriptor.id}`}
                  value={descriptor.id}
                  disabled={!descriptor.available}
                >
                  {descriptor.name}
                </option>
              ))}
            </Select>
          )}
          {selectedRuntime && (
            <span className="indicator-editor-runtime">{selectedRuntime.name} {selectedRuntime.version}</span>
          )}
        </div>
        <p className="indicator-editor-hint">
          {editorProfile?.pineEnhancements
            ? <>{t("indicator.editor.hintPine")} <code>ta.</code> <code>timeframe.</code> {t("indicator.editor.hintComplete")} </>
            : selectedLanguage?.id === FRONTEND_SCRIPT_LANGUAGE ? null : <>{t("indicator.editor.hintPlugin")} </>}
          <kbd>Ctrl+Enter</kbd> {t("indicator.editor.runKbd")}
        </p>
        {selectedLanguage?.id === FRONTEND_SCRIPT_LANGUAGE && (
          <p className="indicator-editor-hint">{t("indicator.editor.frontendWindow")}</p>
        )}
        {!readOnly && allowedRuntimeCatalog && !languageReady && (
          <InlineAlert tone="warning">{t("indicator.editor.runtimeUnavailableHelp")} {t("native.platformHelp")}</InlineAlert>
        )}
        {runtimeCatalogError && (
          <InlineAlert tone="danger">{t("indicator.editor.runtimeMissing", { error: runtimeCatalogError })}</InlineAlert>
        )}

        {(language === "pine" || selectedLanguage?.id === "pine") && (
          <div className="indicator-editor-advanced">
            {language === "pine" && (
              <Disclosure summary={t("pine.host.title")}>
                <div className="indicator-editor-advanced-body">
                  <p className="indicator-editor-hint">{t("pine.host.hint")}</p>
                  <Field label={t("pine.host.json")} {...(hostConfig.error ? { error: hostConfig.error } : {})}>
                    <Textarea className="indicator-editor-json" value={hostText} readOnly={readOnly} spellCheck={false} rows={5}
                      onChange={(event) => setHostText(event.target.value)} />
                  </Field>
                  <div>
                    <Button size="sm" disabled={readOnly} onClick={() => setSessionEpoch(crypto.randomUUID())}>{t("pine.host.reset")}</Button>
                    <p className="indicator-editor-hint">{t("pine.host.resetHint")}</p>
                  </div>
                  <Checkbox label={t("pine.host.alerts")} description={t("pine.host.alertHint")} checked={pineAlerts} disabled={readOnly}
                    onChange={(event) => setPineAlerts(event.target.checked)} />
                </div>
              </Disclosure>
            )}
            {selectedLanguage?.id === "pine" && <PineLibraryInputs value={libraryJson} onChange={setLibraryJson} readOnly={readOnly} />}
            {selectedLanguage?.id === "pine" && <PineContextInputs value={contextJson} onChange={setContextJson} readOnly={readOnly} />}
            {selectedLanguage?.id === "pine" && <PineCurrencyInputs value={currencyJson} onChange={setCurrencyJson} readOnly={readOnly} />}
          </div>
        )}

        <div className="indicator-editor-code">
          <Suspense fallback={null}><Editor
            height="100%"
            path={`candlescope-indicator-${encodeURIComponent(modelId)}.${selectedLanguage?.id || "txt"}`}
            language={editorProfile?.monacoLanguage || "plaintext"}
            theme={extensionEditorTheme || editorProfile?.theme || "vs-dark"}
            value={script}
            onChange={(value) => {
              if (!readOnly) setDraft((current) => editScriptEditorSource(current, selectedLanguage?.id || language, value || ""));
            }}
            beforeMount={handleBeforeMount}
            onMount={handleEditorMount}
            options={getScriptEditorOptions(readOnly ? {
              readOnly: true,
              domReadOnly: true,
              quickSuggestions: false,
              suggestOnTriggerCharacters: false,
              cursorStyle: "line-thin",
            } : {})}
          /></Suspense>
        </div>
      </div>

      <div className="indicator-editor-console" data-tone={status.tone} role="status">
        {status.text}
      </div>
    </div>
  );
}
