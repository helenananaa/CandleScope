import { Button } from "../../components/ui/Button.js";
import { Tabs } from "../../components/ui/Choice.js";
import { tabId, tabPanelId } from "../../components/ui/helpers.js";
import { Badge, InlineAlert } from "../../components/ui/Display.js";
import { useId, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { PermissionRows, ProviderRows, PaperRows, TrustRequestMatrix, TrustModeControl } from "./PluginManagementSections.js";
import { pluginStatus } from "./pluginCenterModel.js";
import type { PluginCatalogPlugin, PluginManagementDetail, PluginPlatformRuntime, PluginProviderContribution, PluginPaperContribution } from "./pluginPlatformTypes.js";
import { sandboxStatusLabel, trustModeLabel } from "./pluginLabels.js";
export default function PluginDetail({ selected, detail, loading, error, runtime, reload, onBack, onDiscover }: {
  selected: PluginCatalogPlugin; detail: PluginManagementDetail | null; loading: boolean; error: string | null;
  runtime: PluginPlatformRuntime; reload(): Promise<void>; onBack(): void; onDiscover(): void;
}) {
  useLocale();
  const [page, setPage] = useState("overview");
  const tabsId = useId();
  // The page shown below the tabs is their tab panel.
  const panel = { role: "tabpanel", id: tabPanelId(tabsId, page), "aria-labelledby": tabId(tabsId, page) } as const;
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<"uninstall" | "rollback" | null>(null);
  const settings = runtime.view.registries.settings.filter((item) => item.pluginId === selected.id);
  const status = pluginStatus(selected);
  const retired = selected.unavailableReason === "PLUGIN_PLATFORM_PACKAGE_UPDATE_REQUIRED";
  const mutate = async (action: "enable" | "disable" | "rollback" | "uninstall") => {
    if (pending || !runtime.view.managementAvailable) return;
    setPending(true);
    try {
      await runtime.actions.changeState(selected.id, action);
      setConfirmation(null);
      if (action !== "uninstall") await reload();
    } catch { /* The host publishes the operation error. */ }
    finally { setPending(false); }
  };
  return <section className="pc-detail" aria-label={selected.name} aria-busy={pending}>
    <Button variant="ghost" size="sm" className="pc-back" onClick={onBack}>{t("pc.back")}</Button>
    <header className="pc-detail-header">
      <div className="pc-monogram" aria-hidden="true">{selected.name.slice(0, 1).toUpperCase()}</div>
      <div><h3>{selected.name}</h3><p>{selected.publisher} · {selected.version}</p></div>
      <Badge tone={status === "active" ? "success" : status === "attention" ? "warning" : "neutral"}>{t(`pc.${status}`)}</Badge>
    </header>
    {retired ? <InlineAlert action={<Button size="sm" onClick={onDiscover}>{t("pc.discover")}</Button>}>
      {t("unified.legacyUpgrade")}
    </InlineAlert> : <div className="plugin-action-row pc-detail-actions">
      {selected.state === "active"
        ? <Button disabled={pending || !runtime.view.managementAvailable} onClick={() => void mutate("disable")}>{t("plugin.disable")}</Button>
        : selected.permissions.activationReady
          ? <Button variant="primary" disabled={pending || !runtime.view.managementAvailable} onClick={() => void mutate("enable")}>{t("plugin.enable")}</Button>
          : <Button variant="primary" onClick={() => setPage("permissions")}>{t("plugin.permissions")}</Button>}
      {pending && <span role="status">{t("pc.working")}</span>}
      <details className="pc-more"><summary>{t("pc.more")}</summary><div>
        <Button disabled={pending || !runtime.view.managementAvailable || !detail?.rollback.available} onClick={() => setConfirmation("rollback")}>{t("plugin.rollback")}</Button>
        <Button disabled={pending || !runtime.view.managementAvailable} onClick={() => setConfirmation("uninstall")}>{t("plugin.uninstall")}</Button>
      </div></details>
    </div>}
    {!retired && confirmation && <section className="pc-confirm" aria-label={t(`plugin.${confirmation}`)}>
      <strong>{t(`plugin.${confirmation}`)} · {selected.name}</strong>
      <p>{confirmation === "uninstall" ? t("plugin.host.uninstallConfirm", { name: selected.name }) : t("plugin.rollbackAvailable", { target: detail?.rollback.target?.version ?? detail?.rollback.target?.state ?? t("plugin.previousActive") })}</p>
      <p>{t("plugin.dataRetentionHint")}</p>
      <div className="plugin-action-row"><Button disabled={pending} onClick={() => setConfirmation(null)}>{t("workspace.cancel")}</Button><Button variant="danger" disabled={pending || !runtime.view.managementAvailable} onClick={() => void mutate(confirmation)}>{t(`plugin.${confirmation}`)}</Button></div>
    </section>}
    <Tabs id={tabsId} className="pc-detail-tabs" label={selected.name} value={page} onChange={setPage}
      tabs={(["overview", ...(settings.length ? ["configure"] : []), "permissions", "diagnostics"] as const).map((key) => ({
        value: key,
        label: t(key === "permissions" ? "plugin.trustRuntime" : key === "diagnostics" ? "pc.diagnostics" : key === "configure" ? "pc.configure" : "pc.overview"),
      }))} />
    {loading && <p role="status">{t("plugin.loadingDetail")}</p>}
    {error && <InlineAlert tone="danger" action={<Button size="sm" onClick={() => void reload()}>{t("shell.retry")}</Button>}>{error}</InlineAlert>}
    {page === "overview" && <div className="pc-detail-body" {...panel}>
      {/* The badge above states the plugin's status; the overview adds only an active plugin's health. */}
      {!retired && detail && selected.state === "active" && <p>{detail.health.available ? t("plugin.available") : t("plugin.unavailableReason", { reason: detail.health.unavailableReason ?? t("plugin.unknownReason") })}</p>}
      {!retired && !selected.permissions.activationReady && <InlineAlert tone="warning">{t("plugin.host.grantEveryPermission")}</InlineAlert>}
      <div className="pc-contributions">{selected.contributions.map((item) => <article key={item.id}><strong>{item.title}</strong><small>{item.kind === "command/1" ? t("plugin.host.commands") : item.kind === "settings/1" ? t("pc.configure") : item.kind}</small></article>)}</div>
                    <ProviderRows providers={selected.contributions.filter(
                      (item): item is PluginProviderContribution => (
                        item.kind === "symbol-provider/1" || item.kind === "market-data-provider/1"
                      ),
                    )} />
                    <PaperRows
                      contributions={selected.contributions.filter(
                        (item): item is PluginPaperContribution => (
                          item.kind === "account-provider/1" || item.kind === "order-executor/1"
                        ),
                      )}
                      detail={detail}
                      runtime={runtime}
                      reload={reload}
                    />

    </div>}
    {page === "configure" && <div className="pc-detail-body" {...panel}>{settings.map((item) => <Button key={item.id} disabled={!runtime.view.managementAvailable} onClick={() => runtime.actions.openSettings(item.id)}>{item.title}</Button>)}</div>}
    {page === "permissions" && <div className="pc-detail-body" {...panel}>
                    {(detail?.trust ?? selected.trust) && (() => {
                      const trust = (detail?.trust ?? selected.trust)!;
                      return (
                        <section className="plugin-trust-installed-summary" data-trust-mode={trust.mode}>
                          <h4>{t("plugin.trustRuntime")}</h4>
                          <p>
                            {t("plugin.sourceLine", { source: trust.source.source, identity: trust.source.publisherIdentity })}
                            {trust.source.signatureRoot ? t("plugin.signedRoot", { root: trust.source.signatureRoot }) : t("plugin.unsignedLocal")}
                          </p>
                          <p>
                            {t("plugin.modeSandbox", { mode: trustModeLabel(trust.mode), status: sandboxStatusLabel(trust.authorization.sandbox.status) })}
                            {` · ${trust.decisionRecorded ? t("plugin.hasDecision") : t("plugin.defaultPolicy")}`}
                          </p>
                          {trust.authorization.entrypoints.map((item) => (
                            <div className="plugin-trust-runtime" key={item.entrypointId}>
                              <strong>{item.entrypointId}</strong>
                              <span>{item.runtimeKind} · {item.runtimeId} · {item.supplySource}</span>
                              <small>{item.hostManaged ? t("plugin.host.hostManaged") : t("plugin.bundledRuntime")} · {item.profile.profileId}</small>
                            </div>
                          ))}
                          <TrustRequestMatrix trust={trust.requests} />
                          <small>{t("plugin.authorityHint")}</small>
                          {trust.changeAllowed && runtime.view.managementAvailable && (
                            <TrustModeControl runtime={runtime} pluginId={selected.id} trust={trust} onComplete={reload} />
                          )}
                        </section>
                      );
                    })()}
      {!retired && detail && <PermissionRows runtime={runtime} detail={detail} reload={reload} />}
    </div>}
    {page === "diagnostics" && <div className="pc-detail-body" {...panel}>
      <p>{selected.id} · {selected.trust?.mode ?? selected.trustLevel}</p>
                    {detail && (
                      <>
                        {detail.health.entrypoints.some((item) => item.runtimeSupply !== undefined) && (
                          <>
                            <h4>{t("plugin.runtimeSupply")}</h4>
                            {detail.health.entrypoints.filter((item) => item.runtimeSupply !== undefined).map((item) => {
                              const supply = item.runtimeSupply!;
                              return (
                                <p key={item.entrypointId} data-runtime-supply={supply.source}>
                                  {item.entrypointId} · {supply.runtimeId} {supply.version} · {supply.source}
                                  · {supply.verificationStatus} · {supply.reproducible ? t("plugin.reproducible") : t("plugin.unreproducible")}
                                </p>
                              );
                            })}
                          </>
                        )}
                        <h4>{t("plugin.health")}</h4>
                        <p>{detail.health.available ? t("plugin.available") : t("plugin.unavailableReason", { reason: detail.health.unavailableReason ?? t("plugin.unknownReason") })}</p>
                        <h4>{t("plugin.updateRollback")}</h4>
                        <p>
                          {t("plugin.updateSource")}
                          {detail.update.latest ? t("plugin.verifiedAvailable", { version: detail.update.latest.version }) : ""}
                          {detail.update.reason ? ` · ${detail.update.reason}` : ""}
                        </p>
                        {detail.update.candidate && <p>{t("plugin.candidate", { version: detail.update.candidate.version, phase: detail.update.candidate.phase })}</p>}
                        <p>{detail.rollback.available
                          ? t("plugin.rollbackAvailable", { target: detail.rollback.target?.version ?? detail.rollback.target?.state ?? t("plugin.previousActive") })
                          : t("plugin.rollbackUnavailable", { reason: detail.rollback.reason ?? t("plugin.unavailable") })}</p>
                        <h4>{t("plugin.dataRetention")}</h4>
                        <p>{t("plugin.dataRetentionHint")}</p>
                        <pre>{JSON.stringify(detail.dataRetention.storage, null, 2)}</pre>

                      </>
                    )}
      <Button onClick={onDiscover}>{t("pc.discover")}</Button>
    </div>}
  </section>;
}
