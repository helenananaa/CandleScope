import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Icon } from "../../components/icons/Icon.js";
import { Button } from "../../components/ui/Button.js";
import { Badge, Disclosure, InlineAlert } from "../../components/ui/Display.js";
import { EmptyState } from "../../components/ui/EmptyState.js";
import { Field, Input } from "../../components/ui/Field.js";
import { confirmAction } from "../../components/ui/overlay/overlayApi.js";
import { t, type MessageKey } from "../../i18n/index.js";
import { getDateTimeLocale, getNumberLocale } from "../../i18n/formatting.js";
import { useLocale } from "../../i18n/useLocale.js";
import {
  DataSourceApiError,
  checkDataSource,
  dataSourceSession,
  getDataSources,
  maskedKey,
  removeDataSourceKey,
  saveDataSourceKey,
  type CreditUsage,
  type DataSourceCheck,
  type DataSourceField,
  type DataSourceStatus,
  type DataSourcesStatus,
} from "./dataSourcesApi.js";
import { dataSourceErrorKey, validKeyInput } from "./dataSourceErrors.js";

const DESCRIPTIONS: Record<string, MessageKey> = {
  twelvedata: "dataSources.twelvedata.description",
};
const SIGNUP_SITES: Record<string, string> = {
  twelvedata: "twelvedata.com",
};

function errorCode(error: unknown): string {
  return error instanceof DataSourceApiError ? error.code : "DATA_SOURCES_UNAVAILABLE";
}

function time(ms: number | null): string {
  return typeof ms === "number" ? new Date(ms).toLocaleString(getDateTimeLocale()) : "";
}

function number(value: number): string {
  return value.toLocaleString(getNumberLocale());
}

function ErrorAlert({ code, source }: { code: string; source: string }) {
  return <InlineAlert tone="danger">
    {t(dataSourceErrorKey(code), { source })}
    <Disclosure summary={t("plugin.techDetails")}><code>{code}</code></Disclosure>
  </InlineAlert>;
}

function credits(value: CreditUsage): string {
  return value.used === null
    ? t("dataSources.creditsLimit", { limit: number(value.limit) })
    : t("dataSources.creditsUsed", { used: number(value.used), limit: number(value.limit) });
}

function CheckResult({ result }: { result: DataSourceCheck }) {
  const { usage } = result;
  return <InlineAlert tone="success" title={t("dataSources.checkOk")}>
    <dl className="st-kv">
      {usage.plan && <><dt>{t("dataSources.plan")}</dt><dd>{usage.plan}</dd></>}
      <dt>{t("dataSources.minuteCredits")}</dt><dd>{credits(usage.minuteCredits)}</dd>
      {usage.dailyCredits && <><dt>{t("dataSources.dailyCredits")}</dt><dd>{credits(usage.dailyCredits)}</dd></>}
      <dt>{t("dataSources.websocketSymbols")}</dt><dd>{number(usage.websocketSymbols)}</dd>
      <dt>{t("dataSources.checkedAt")}</dt><dd>{time(result.checkedAtMs)}</dd>
    </dl>
  </InlineAlert>;
}

function stateBadge(field: DataSourceField) {
  if (field.active === "saved") return <Badge tone="success">{t("dataSources.state.saved")}</Badge>;
  if (field.savedError) return <Badge tone="warning">{t("dataSources.state.unreadable")}</Badge>;
  if (field.active === "environment") return <Badge tone="accent">{t("dataSources.state.environment")}</Badge>;
  return <Badge>{t("dataSources.state.none")}</Badge>;
}

export interface SourceProps {
  source: DataSourceStatus;
  vaultAvailable: boolean;
  onStatus(status: DataSourcesStatus): void;
}

/** One source's key: what is in use, and save / test / remove. */
export function DataSourceSection({ source, vaultAvailable, onStatus }: SourceProps) {
  const field = source.fields[0];
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"save" | "check" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<"saved" | "removed" | null>(null);
  const [result, setResult] = useState<DataSourceCheck | null>(null);
  if (!field) return null;
  const name = source.name;
  const site = SIGNUP_SITES[source.id];
  const description = DESCRIPTIONS[source.id];

  async function check() {
    setBusy("check"); setError(null); setResult(null);
    try { setResult(await checkDataSource(source.id)); }
    catch (failure) { setError(errorCode(failure)); }
    finally { setBusy(null); }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!field) return;
    const value = draft.trim();
    setNotice(null); setResult(null);
    if (!validKeyInput(value)) { setError("CREDENTIAL_VALUE_INVALID"); return; }
    setBusy("save"); setError(null);
    try {
      onStatus(await saveDataSourceKey(source.id, field.id, value));
      setDraft("");
      setNotice("saved");
    } catch (failure) {
      setError(errorCode(failure));
      setBusy(null);
      return;
    }
    // A saved key is tested right away, so a wrong key shows up here and not on a chart.
    await check();
  }

  async function remove() {
    if (!field) return;
    const confirmed = await confirmAction({
      title: t("dataSources.removeTitle", { source: name }),
      message: t(field.environmentSet ? "dataSources.removeMessageEnvironment" : "dataSources.removeMessage", { source: name }),
      confirmLabel: t("dataSources.removeConfirm"),
      tone: "danger",
    });
    if (!confirmed) return;
    setBusy("remove"); setError(null); setNotice(null); setResult(null);
    try {
      onStatus(await removeDataSourceKey(source.id, field.id));
      setNotice("removed");
    } catch (failure) { setError(errorCode(failure)); }
    finally { setBusy(null); }
  }

  const inputId = `data-source-${source.id}-${field.id}`;
  return <section className="st-group" aria-labelledby={`${inputId}-title`}>
    <div className="st-source-head">
      <div className="st-group-title" id={`${inputId}-title`}>{name}</div>
      <span role="status">{stateBadge(field)}</span>
    </div>
    {description && <div className="st-group-desc">{t(description, { site: site ?? "" })}</div>}
    <dl className="st-kv">
      <dt>{t("dataSources.savedKey")}</dt>
      <dd>{field.saved
        ? t("dataSources.savedKeyValue", { masked: maskedKey(field.savedHint), time: time(field.savedAtMs) })
        : t("dataSources.notSaved")}</dd>
      <dt>{t("dataSources.environmentVariable")}</dt>
      <dd><code>{field.environmentVariable}</code> · {field.environmentSet
        ? t("dataSources.environmentSet", { masked: maskedKey(field.active === "environment" ? field.activeHint : null) })
        : t("dataSources.environmentNotSet")}</dd>
    </dl>
    {field.active === "environment" && <div className="st-group-desc">{t("dataSources.environmentActive")}</div>}
    {field.active === "saved" && field.environmentSet && <div className="st-group-desc">{t("dataSources.environmentShadowed")}</div>}
    {field.savedError && <InlineAlert tone="warning">
      {t("dataSources.savedUnreadable")}
      <Disclosure summary={t("plugin.techDetails")}><code>{field.savedError}</code></Disclosure>
    </InlineAlert>}
    {vaultAvailable && <form onSubmit={(event) => { void save(event); }} autoComplete="off">
      <Field label={t("dataSources.keyLabel")}>
        <Input id={inputId} size="sm" type="password" autoComplete="off" spellCheck={false} maxLength={256}
          value={draft} disabled={busy !== null}
          placeholder={t(field.saved ? "dataSources.keyPlaceholderReplace" : "dataSources.keyPlaceholder", { source: name })}
          onChange={(event) => { setDraft(event.target.value); if (error === "CREDENTIAL_VALUE_INVALID") setError(null); }} />
      </Field>
      <div className="st-form-actions">
        <Button type="submit" variant="primary" disabled={busy !== null || !draft.trim()}>
          {t(busy === "save" ? "dataSources.saving" : field.saved ? "dataSources.replace" : "dataSources.save")}
        </Button>
        <Button disabled={busy !== null || !field.active} onClick={() => { void check(); }}>
          {t(busy === "check" ? "dataSources.checking" : "dataSources.check")}
        </Button>
        {field.saved && <Button variant="ghost" disabled={busy !== null} onClick={() => { void remove(); }}>
          {t(busy === "remove" ? "dataSources.removing" : "dataSources.remove")}
        </Button>}
      </div>
    </form>}
    {!vaultAvailable && field.active && <div className="st-form-actions">
      <Button disabled={busy !== null} onClick={() => { void check(); }}>
        {t(busy === "check" ? "dataSources.checking" : "dataSources.check")}
      </Button>
    </div>}
    {notice && <div className="st-group-desc" role="status">
      {t(notice === "saved" ? "dataSources.saved" : "dataSources.removed")} {t("dataSources.reopenCharts", { source: name })}
    </div>}
    {error && <ErrorAlert code={error} source={name} />}
    {result && <CheckResult result={result} />}
  </section>;
}

/** Settings → Data sources: the user's own keys for built-in sources (desktop app only). */
export default function DataSourcesSettingsPanel() {
  useLocale();
  const [status, setStatus] = useState<DataSourcesStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const alive = useRef(true);
  const available = dataSourceSession() !== null;

  const load = useCallback(async () => {
    try {
      const next = await getDataSources();
      if (alive.current) { setStatus(next); setLoadError(null); }
      return next;
    } catch (failure) {
      if (alive.current) setLoadError(errorCode(failure));
      return null;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!available) return () => { alive.current = false; };
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    // Saved keys may still be loading just after startup (a Keychain prompt can hold them).
    const poll = async () => {
      const next = await load();
      if (alive.current && next && !next.loaded && polls++ < 30) timer = setTimeout(() => { void poll(); }, 1000);
    };
    void poll();
    return () => { alive.current = false; if (timer) clearTimeout(timer); };
  }, [available, load]);

  if (!available) {
    return <EmptyState icon={<Icon name="lock" size={22} />} title={t("dataSources.desktopOnly")} description={t("dataSources.intro")} />;
  }
  return <div className="st-sources">
    <div className="st-group-desc">{t("dataSources.intro")}</div>
    {loadError && <ErrorAlert code={loadError} source="" />}
    {!status && !loadError && <div className="st-group-desc" role="status">{t("dataSources.loading")}</div>}
    {status && !status.vaultAvailable && <InlineAlert tone="warning">{t("dataSources.vaultUnavailable")}</InlineAlert>}
    {status?.error && status.vaultAvailable && <InlineAlert tone="warning">
      {t(dataSourceErrorKey(status.error))}
      <Disclosure summary={t("plugin.techDetails")}><code>{status.error}</code></Disclosure>
    </InlineAlert>}
    {status?.deletionPending && <div className="st-group-desc">{t("dataSources.deletionPending")}</div>}
    {status?.sources.map((source) => <DataSourceSection key={source.id} source={source}
      vaultAvailable={status.vaultAvailable} onStatus={setStatus} />)}
  </div>;
}
