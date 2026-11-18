import { useEffect, useState, useSyncExternalStore } from "react";
import type { UnifiedIdentity, UnifiedManifest, UnifiedItem } from "../../../desktop/unified-entry-lifecycle.mjs";
import { Badge, Button, Checkbox, Field, FileDrop, InlineAlert, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { OpaquePluginFrame } from "../plugins/SandboxPluginFrame.js";
import { pluginManagementAvailable, stageUnifiedPackage, unifiedAssetBase, unifiedManagementRequest } from "../plugins/pluginPlatformApi.js";
import { getUnifiedState, subscribeUnified, refreshUnified, reportUnifiedView } from "./unifiedRuntime.js";

interface Review { packageSha256: string; manifest: UnifiedManifest; registryRevision: number; publisherVerified: false }
const appearanceKinds = ["theme", "layout"] as const;
type AppearanceKind = typeof appearanceKinds[number];
interface LegacyExtension { id: string; name: string; version: string | null; digest: string; error: string | null; appearanceOnly: boolean }
interface Catalog {
  revision: number; safeMode: boolean; errors: Record<string,string>; appearance?: Partial<Record<AppearanceKind, string | null>>;
  orphaned?: {pluginId:string;entryId:string;state:string}[];
  plugins: { id: string; manifest?: UnifiedManifest; error?: string; desired: {enabled:boolean;packageSha256:string;history:string[]};
    entries: {id:string;kind:string; observed:{state:string;identity:UnifiedIdentity;instanceId:string}[]}[] }[];
}

function SandboxView({ item }: {item: UnifiedItem}) {
  useEffect(() => () => reportUnifiedView(item, "ready"), [item]);
  return <OpaquePluginFrame title={item.manifest.name} src={`${unifiedAssetBase(item.assetBase)}${item.entry.path}`}
    onLoad={() => reportUnifiedView(item, "running")} />;
}

export default function UnifiedPluginManager({ onCountChange, query = "", filter = "all", showAppearance = false }: {
  onCountChange?: (count: number) => void; query?: string; filter?: string; showAppearance?: boolean;
}) {
  useLocale();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [legacy, setLegacy] = useState<LegacyExtension[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const state = useSyncExternalStore(subscribeUnified, getUnifiedState, getUnifiedState);
  const available = pluginManagementAvailable();
  useEffect(() => { onCountChange?.(catalog?.plugins.length ?? 0); }, [catalog?.plugins.length, onCountChange]);
  async function reload() { setCatalog(await unifiedManagementRequest("") as Catalog); }
  useEffect(() => {
    if (!available) return;
    let mounted = true;
    const read = () => { void unifiedManagementRequest("").then((value) => { if (mounted) setCatalog(value as Catalog); })
      .catch((failure: unknown) => { if (mounted) setError(String(failure)); }); };
    read();
    const timer = window.setInterval(read, 5000);
    return () => { mounted = false; clearInterval(timer); };
  }, [available]);
  useEffect(() => {
    if (!available || !showAppearance) return;
    let mounted = true;
    void unifiedManagementRequest("/legacy-extensions").then((value) => {
      if (mounted) setLegacy(value as LegacyExtension[]);
    }).catch((failure: unknown) => { if (mounted) setError(String(failure)); });
    return () => { mounted = false; };
  }, [available, showAppearance]);
  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); await refreshUnified(); await reload(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  async function openReview(digest: string) {
    setAccepted(false);
    setReview(await unifiedManagementRequest("/review", { digest }) as Review);
  }
  const statuses: Record<string,string> = {
    running: t("extensions.status.running"), ready: t("plugin.available"), stopped: t("extensions.status.stopped"),
    "pending-start": t("extensions.status.pendingStart"), "pending-restart": t("unified.restart"), failed: t("extensions.status.failed"),
    "pending-stop": t("extensions.status.pendingStop"), unavailable: t("extensions.status.unavailable"),
  };
  const realmNames: Record<string,string> = { frontend: t("extensions.realm.frontend"), backend: t("extensions.realm.backend"), desktop: t("extensions.realm.desktop") };
  const visible = catalog?.plugins.filter((plugin) => {
    if (!`${plugin.manifest?.name ?? ""} ${plugin.id} ${plugin.manifest?.version ?? ""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) return false;
    if (filter === "disabled") return !plugin.desired.enabled;
    if (filter === "active") return plugin.entries.some((entry) => entry.observed.some((value) => value.state === "running"));
    if (filter === "attention") return !!plugin.error || plugin.entries.some((entry) => entry.observed.some((value) => ["failed", "pending-stop", "pending-restart", "unavailable"].includes(value.state)));
    return true;
  }) ?? [];
  return <section className="extension-manager" aria-label={t("unified.title")} aria-busy={busy}>
    <header className="extension-manager-head"><h3>{t("unified.title")}</h3>
      <Button size="sm" disabled={!available || busy} onClick={() => void run(reload)}>{t("extensions.refresh")}</Button></header>
    {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    {Object.values(catalog?.errors ?? {}).map((message, i) => <InlineAlert key={i} tone="danger">{message}</InlineAlert>)}
    {state.restartRequired && <InlineAlert action={<Button size="sm" onClick={() => location.reload()}>{t("extensions.reload")}</Button>}>{t("unified.restart")}</InlineAlert>}
    {catalog?.safeMode && <InlineAlert>{t("extensions.safeMode")}</InlineAlert>}
    {!!catalog?.orphaned?.length && <InlineAlert>{t("extensions.orphanRunning")}</InlineAlert>}
    <FileDrop compact label={t("pc.install")} accept=".cspkg" disabled={!available || busy}
      onFiles={([file]) => { if (file) void run(async () => { setAccepted(false); setReview(await stageUnifiedPackage(file) as Review); }); }} />
    {showAppearance && catalog && <div className="extension-toolbar">
      {appearanceKinds.map((kind) => <Field label={t(`extensions.${kind}`)} key={kind}>
        <Select aria-label={t(`extensions.${kind}`)} value={catalog.appearance?.[kind] ?? ""} disabled={!available || busy}
          onChange={(event) => {
            const id = event.currentTarget.value || null;
            void run(() => unifiedManagementRequest("/change", {
              action: "select-appearance", kind, id, revision: catalog.revision,
            }));
          }}>
          <option value="">{t("extensions.appDefault")}</option>
          {catalog.plugins.filter((plugin) => plugin.desired.enabled && plugin.entries.some((entry) => entry.kind === "data" && entry.id === kind))
            .map((plugin) => <option key={plugin.id} value={plugin.id}>{plugin.manifest?.name ?? plugin.id}</option>)}
        </Select>
      </Field>)}
    </div>}
    {showAppearance && legacy.filter((item) => !catalog?.plugins.some((plugin) => plugin.id === item.id)).map((item) => <article className="extension-item" key={item.id}>
      <header><strong>{item.name} {item.version}</strong></header>
      {item.error && <InlineAlert tone="warning">{item.error}</InlineAlert>}
      {item.appearanceOnly
        ? <Button size="sm" disabled={!available || busy} onClick={() => void run(async () => {
          setAccepted(false);
          setReview(await unifiedManagementRequest("/stage-appearance", { digest: item.digest }) as Review);
        })}>{t("unified.migrateAppearance")}</Button>
        : <p>{t("unified.legacyUpgrade")}</p>}
    </article>)}
    {review && <div className="extension-review">
      <strong>{review.manifest.name} · {review.manifest.version}</strong>
      <InlineAlert tone={review.manifest.trust === "full-trust" ? "warning" : "info"}>{review.manifest.trust === "full-trust" ? t("extensions.fullTrust") : t("unified.restricted")}</InlineAlert>
      <p>{t("extensions.localImport")}</p>
      <details><summary>{t("plugin.techDetails")}</summary><code className="extension-detail">{review.packageSha256}</code>
        <ul>{review.manifest.entries.map((entry) => <li key={entry.id}>{entry.id} · {entry.kind}</li>)}</ul></details>
      <Checkbox checked={accepted} onChange={(event) => setAccepted(event.target.checked)} label={t("extensions.accept")} />
      <Button size="sm" variant="primary" disabled={!accepted || busy} onClick={() => void run(async () => {
        await unifiedManagementRequest("/change", { action: "activate", digest: review.packageSha256,
          revision: review.registryRevision, acknowledgement: `${review.manifest.trust}:${review.packageSha256}` });
        setReview(null); setAccepted(false);
      })}>{t("extensions.confirm")}</Button>
      <Button size="sm" variant="ghost" onClick={() => setReview(null)}>{t("common.cancel")}</Button>
    </div>}
    {!!catalog?.plugins.length && !visible.length && <p role="status">{t("pc.noResults")}</p>}
    {visible.map((plugin) => <article className="extension-item" key={plugin.id}>
      <header><strong>{plugin.manifest?.name ?? plugin.id} · {plugin.manifest?.version}</strong>
        <Badge tone={plugin.desired.enabled ? "success" : "neutral"}>{t(plugin.desired.enabled ? "extensions.enabled" : "extensions.disabled")}</Badge></header>
      {plugin.error && <InlineAlert tone="danger">{plugin.error}</InlineAlert>}
      <dl className="extension-realms">{plugin.entries.map((entry) => <div key={entry.id}>
        <dt>{realmNames[entry.kind] ?? (entry.kind === "sandbox-view" ? t("plugin.host.sandboxOpaque") : t("plugin.runtime"))}</dt>
        <dd>{entry.observed.length ? entry.observed.map((item) => `${statuses[item.state] ?? item.state} · ${item.identity.version}`).join(" / ")
          : t(plugin.desired.enabled ? "extensions.status.pendingStart" : "extensions.status.stopped")}</dd>
      </div>)}</dl>
      <div className="extension-actions">
        <Button size="sm" disabled={busy} onClick={() => void run(() => plugin.desired.enabled
          ? unifiedManagementRequest("/change", { action: "disable", id: plugin.id, revision: catalog!.revision })
          : openReview(plugin.desired.packageSha256))}>{t(plugin.desired.enabled ? "extensions.disable" : "extensions.enable")}</Button>
        <Button size="sm" disabled={busy} onClick={() => void run(() => unifiedManagementRequest("/change", { action: "uninstall", id: plugin.id, revision: catalog!.revision }))}>{t("extensions.uninstall")}</Button>
        {plugin.desired.history.map((digest) => <Button key={digest} size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => openReview(digest))}>{t("extensions.reviewPrevious")}</Button>)}
      </div>
    </article>)}
    {state.views.map((item) => <SandboxView key={item.instanceId} item={item} />)}
  </section>;
}
