import { describeError } from "../../i18n/serverErrors.js";
import { useEffect, useMemo, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { JsonValue, PluginManagementDetail, PluginPlatformRuntime, PluginProviderContribution, PluginPaperContribution, PluginMarketplaceStatus, PluginRuntimeRegistryStatus, PluginTrustSummary, PluginLocalInstallCandidate, PluginTrustReview, PluginTrustChangeReview } from "./pluginPlatformTypes.js";
export function PermissionRows({ runtime, detail, reload }: {
  runtime: PluginPlatformRuntime;
  detail: PluginManagementDetail;
  reload(): Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const permissions = detail.permissions.flatMap((item) => item.permissions);
  const decide = async (
    permissionId: string,
    decision: "grant" | "deny" | "revoke",
    scope?: Record<string, JsonValue>,
  ) => {
    if (pending || !runtime.view.managementAvailable) return;
    setPending(true);
    try {
      await runtime.actions.decidePermission(detail.plugin.id, permissionId, decision, scope);
      await reload();
    } catch {
      // Runtime publishes a bounded notice and leaves the prior detail visible.
    } finally { setPending(false); }
  };
  if (!permissions.length) return <p>{t("plugin.host.noPermissions")}</p>;
  return (
    <div className="plugin-permissions">
      {permissions.map((permission) => (
        <article key={permission.permissionId}>
          <div><strong>{permission.permissionId}</strong><span>{permission.kind} · {permission.decision}</span></div>
          <pre>{JSON.stringify(permission.requestedScope, null, 2)}</pre>
          <div className="plugin-action-row">
            {permission.decision !== "granted" && <button type="button" disabled={pending || !runtime.view.managementAvailable} onClick={() => void decide(permission.permissionId, "grant", permission.requestedScope)}>{t("plugin.host.grantScope")}</button>}
            {permission.decision === "granted" && <button type="button" disabled={pending || !runtime.view.managementAvailable} onClick={() => void decide(permission.permissionId, "revoke")}>{t("plugin.host.revoke")}</button>}
            {permission.decision !== "denied" && <button type="button" disabled={pending || !runtime.view.managementAvailable} onClick={() => void decide(permission.permissionId, "deny")}>{t("plugin.host.deny")}</button>}
          </div>
        </article>
      ))}
    </div>
  );
}

export function ProviderRows({ providers }: { providers: PluginProviderContribution[] }) {
  if (!providers.length) return null;
  return (
    <>
      <h4>{t("plugin.host.providersTitle")}</h4>
      <p>{t("plugin.host.providersHint")}</p>
      <div className="plugin-provider-list">
        {providers.map((provider) => {
          if (provider.kind === "symbol-provider/1") {
            const config = provider.configuration;
            return (
              <article key={provider.id} data-plugin-provider-exchange={config.exchange}>
                <div><strong>{config.displayName}</strong><span>{t("plugin.host.exchangeSymbols", { exchange: config.exchange })}</span></div>
                <p>
                  {t("plugin.host.markets", { markets: config.marketTypes.map((item) => item.label).join(", ") })}
                  {` · ${t("plugin.host.providerBounds", { page: config.maxPageSize, seconds: config.cacheTtlSeconds })}`}
                </p>
              </article>
            );
          }
          const config = provider.configuration;
          return (
            <article key={provider.id} data-plugin-provider-exchange={config.exchange}>
              <div><strong>{t("plugin.host.exchangeMarketData", { exchange: config.exchange.toUpperCase() })}</strong><span>{config.dataPlane}</span></div>
              <p>
                {t("plugin.host.sourceFinality", { quality: config.sourceQuality.quality, finality: config.sourceQuality.finality })}
              </p>
              <ul>
                {config.channels.map((channel) => (
                  <li key={channel.kind}>
                    {channel.kind === "full_depth" ? t("plugin.host.fullDepth") : t("plugin.host.kline")}
                    {` · ${[channel.history && t("plugin.host.history"), channel.realtime && t("plugin.host.realtime")].filter(Boolean).join(" + ")}`}
                    {channel.intervals.length ? ` · ${channel.intervals.join(", ")}` : ""}
                    {` · ${channel.delivery} · ${channel.finality}`}
                    {channel.corrections ? ` · ${t("plugin.host.corrections")}` : ""}
                    {` · ${t("plugin.host.channelBounds", { rate: channel.ratePerMinute, concurrency: channel.maxConcurrent })}`}
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </>
  );
}

export function PaperRows({
  contributions,
  detail,
  runtime,
  reload,
}: {
  contributions: PluginPaperContribution[];
  detail: PluginManagementDetail | null;
  runtime: PluginPlatformRuntime;
  reload(): Promise<void>;
}) {
  if (!contributions.length) return null;
  const account = contributions.find((item) => item.kind === "account-provider/1");
  const executor = contributions.find((item) => item.kind === "order-executor/1");
  const paper = detail?.paperTrading;
  const toggleKillSwitch = async () => {
    if (!paper) return;
    const next = !paper.killSwitchEnabled;
    if (!next && !window.confirm(t("plugin.host.paperResumeConfirm"))) return;
    try {
      await runtime.actions.setPaperKillSwitch(next);
      await reload();
    } catch { /* notice published */ }
  };
  return (
    <section className="plugin-paper-panel" data-plugin-paper-only>
      <h4>{t("plugin.host.paperTitle")}</h4>
      <p>{t("plugin.host.paperHint")}</p>
      {account?.kind === "account-provider/1" && (
        <p>
          <strong>{account.configuration.displayName}</strong>
          {` · ${account.configuration.accounts.map((item) => `${item.label} (${item.baseCurrency})`).join(", ")}`}
        </p>
      )}
      {executor?.kind === "order-executor/1" && (
        <>
          <p>
            {executor.configuration.orderTypes.join(" + ")}
            {` · ${executor.configuration.symbols.map((item) => `${item.symbol}/${item.marketType}`).join(", ")}`}
          </p>
          <p>
            {`Order ≤ ${executor.configuration.limits.maxOrderNotional} · position ≤ ${executor.configuration.limits.maxPositionNotional}`}
            {` · ${executor.configuration.limits.maxOrdersPerMinute}/min · no short selling`}
          </p>
        </>
      )}
      {paper && (
        <div className="plugin-action-row">
          <strong data-paper-kill-switch-state>
            {t("plugin.host.globalKillSwitch", { state: paper.killSwitchEnabled ? "ON" : "OFF" })}
          </strong>
          <button
            type="button"
            data-paper-kill-switch
            disabled={!runtime.view.managementAvailable}
            onClick={() => void toggleKillSwitch()}
          >
            {paper.killSwitchEnabled ? t("plugin.host.resumePaperOrders") : t("plugin.host.stopPaperOrders")}
          </button>
        </div>
      )}
    </section>
  );
}

export function MarketplacePanel({
  runtime,
  status,
  busy,
  run,
  query = "",
}: {
  runtime: PluginPlatformRuntime;
  query?: string;
  status: PluginMarketplaceStatus | null;
  busy: string | null;
  run(key: string, operation: () => Promise<void>): Promise<void>;
}) {
  useLocale();
  const catalog = runtime.view.marketplaceCatalog;
  if (catalog === null) {
    return (
      <section className="plugin-marketplace-panel plugin-settings-card">
        <p>{t("plugin.market.loading")}</p>
      </section>
    );
  }
  const entries = catalog.plugins.filter((entry) => `${entry.pluginId} ${entry.publisher.displayName}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return (
    <section className="plugin-marketplace-panel plugin-settings-card" data-plugin-marketplace>
      <header className="plugin-settings-card-header">
        <div>
          <h3>{t("plugin.marketplace")}</h3>
          <p>{t("plugin.market.desc")}</p>
        </div>
        <span
          className={`plugin-state-pill ${catalog.enabled ? "is-ready" : "is-muted"}`}
          data-plugin-marketplace-state
        >
          {catalog.enabled ? t("plugin.on") : t("plugin.unconfigured")}
        </span>
      </header>
      {!catalog.enabled && !catalog.marketplaces.length && (
        <div className="plugin-empty-state plugin-marketplace-empty">
          <strong>{t("plugin.market.missing")}</strong>
          <p>{t("plugin.market.missingHint")}</p>
        </div>
      )}
      <details className="plugin-technical-details">
        <summary>{t("plugin.market.policy")}</summary>
        <p>{t("plugin.market.policyHint")}</p>
        {catalog.rollout && <p>{t("plugin.market.channel", { channel: catalog.rollout.channel })}</p>}
        {status?.telemetry && (
          <p data-marketplace-telemetry={status.telemetry.enabled ? "enabled" : "disabled"}>
            {t("plugin.market.telemetry", {
              state: status.telemetry.enabled ? t("plugin.market.telemetryOn") : t("plugin.market.telemetryOff"),
            })}
          </p>
        )}
      </details>
      <div className="plugin-marketplace-roots">
        {catalog.marketplaces.map((marketplace) => (
          <article key={marketplace.marketplaceId}>
            <div>
              <strong>{marketplace.marketplaceId}</strong>
              <small>
                {marketplace.cache.status === "valid"
                  ? t("plugin.market.cacheVerified", { sequence: marketplace.cache.sequence, expires: marketplace.cache.expiresAt })
                  : t("plugin.market.cacheUnavailable", { reason: marketplace.cache.reason ?? t("plugin.market.noVerifiedIndex") })}
              </small>
            </div>
            <button
              type="button"
              data-marketplace-refresh={marketplace.marketplaceId}
              disabled={!runtime.view.managementAvailable || !catalog.enabled || !marketplace.enabled || busy !== null}
              onClick={() => void run(
                `refresh:${marketplace.marketplaceId}`,
                () => runtime.actions.refreshMarketplace(marketplace.marketplaceId),
              )}
            >
              {busy === `refresh:${marketplace.marketplaceId}` ? t("plugin.market.verifying") : t("plugin.market.refreshIndex")}
            </button>
          </article>
        ))}
      </div>
      <div className="plugin-marketplace-list">
        {entries.map((entry) => {
          const candidate = status?.candidates.find((item) => item.pluginId === entry.pluginId) ?? null;
          const update = status?.updates.find((item) => item.pluginId === entry.pluginId) ?? null;
          const installed = runtime.view.catalog?.plugins.find((item) => item.id === entry.pluginId) ?? null;
          const prepareAvailable = entry.installedVersion === null || update?.available === true;
          const activationReady = installed?.permissions.activationReady === true;
          const selectedArtifact = entry.latest.artifacts?.find(
            (artifact) => artifact.artifactId === entry.assurances?.platform.artifactId,
          ) ?? entry.latest.artifact;
          return (
            <article key={entry.pluginId} data-marketplace-plugin={entry.pluginId}>
              <div className="plugin-marketplace-title">
                <div>
                  <strong>{entry.pluginId}</strong>
                  <small>{t("plugin.market.publisherKey", { publisher: entry.publisher.displayName, key: entry.publisher.keyId.slice(0, 24), boundary: t("plugin.market.notCodeSafety") })}</small>
                </div>
                <span>
                  {entry.latest.version} · {entry.latest.licenseExpression}
                  {entry.latest.revoked ? t("plugin.market.revokedSuffix") : ""}
                </span>
              </div>
              {entry.assurances && (
                <div className="plugin-marketplace-assurances" data-marketplace-assurances={entry.pluginId}>
                  <span data-marketplace-publisher-verified={entry.assurances.publisherVerified}>
                    {t("plugin.market.publisher", {
                      state: entry.assurances.publisherVerified ? t("plugin.market.verified") : t("plugin.market.unverified"),
                    })}
                  </span>
                  <span data-marketplace-official-maintained={entry.assurances.officialMaintained}>
                    {t("plugin.market.maintainer", {
                      who: entry.assurances.officialMaintained ? t("plugin.market.official") : t("plugin.market.community"),
                    })}
                  </span>
                  <span data-marketplace-sandbox-available={entry.assurances.sandbox.available}>
                    {t("plugin.market.sandbox", {
                      state: entry.assurances.sandbox.available ? t("plugin.market.sandboxLocal") : t("plugin.market.sandboxUnavailable"),
                    })}
                    {` · ${entry.assurances.sandbox.runtimeKinds.join(", ") || t("plugin.market.noRuntime")}`}
                  </span>
                  <span data-marketplace-rollout-stage={entry.assurances.rolloutStage}>
                    {t("plugin.market.stage", { stage: entry.assurances.rolloutStage })}
                  </span>
                  <details data-marketplace-permission-scope>
                    <summary>
                      {t("plugin.market.permScope", {
                        required: entry.assurances.permissions.required.length,
                        optional: entry.assurances.permissions.optional.length,
                      })}
                    </summary>
                    <pre>{JSON.stringify(entry.assurances.permissions, null, 2)}</pre>
                  </details>
                </div>
              )}
              <details className="plugin-technical-details"><summary>{t("plugin.techDetails")}</summary><p>{t("plugin.market.artifact", {
                sha: selectedArtifact.sha256,
                size: selectedArtifact.size,
                index: entry.latest.transparency.logIndex,
              })}</p></details>
              <p>
                {t("plugin.market.installed", { version: entry.installedVersion ?? t("plugin.market.notInstalled") })}
                {candidate ? t("plugin.market.candidate", { version: candidate.version, phase: candidate.phase }) : ""}
              </p>
              {candidate && (
                <div className="plugin-marketplace-candidate" data-marketplace-candidate-phase={candidate.phase}>
                  <p>
                    {t("plugin.market.compatibility", { host: candidate.compatibility.hostVersion, migration: candidate.migration.policy })}
                    {t("plugin.market.permissionConfirmation", { state: candidate.permissionDiff.requiresConfirmation ? t("plugin.market.required") : t("plugin.market.notRequired") })}
                    {candidate.compatibility.runtimeKinds ? ` · ${candidate.compatibility.runtimeKinds.join(", ")}` : ""}
                    {candidate.compatibility.cacheReuse === true ? t("plugin.market.offlineCache") : ""}
                  </p>
                  {candidate.permissionDiff.permissions.length > 0 && (
                    <ul>
                      {candidate.permissionDiff.permissions.map((permission) => (
                        <li key={permission.permissionId}>
                          {permission.permissionId} · {permission.change}
                          {permission.requiresConfirmation ? t("plugin.market.confirmationRequired") : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                  {candidate.observation.status !== "not-started" && (
                    <p>{t("plugin.market.healthObservation", { status: candidate.observation.status, detail: candidate.observation.detail ? ` · ${candidate.observation.detail}` : "" })}</p>
                  )}
                  {candidate.phase === "quarantined" && (
                    <p role="alert">{t("plugin.market.revoked")}</p>
                  )}
                </div>
              )}
              <div className="plugin-action-row">
                <button
                  type="button"
                  data-marketplace-prepare={entry.pluginId}
                  disabled={!runtime.view.managementAvailable || !catalog.enabled || !entry.installable || !prepareAvailable || busy !== null}
                  onClick={() => void run(
                    `prepare:${entry.pluginId}`,
                    () => runtime.actions.prepareMarketplaceRelease(entry.pluginId, entry.latest.version),
                  )}
                >
                  {busy === `prepare:${entry.pluginId}` ? t("plugin.market.downloading") : t("plugin.market.downloadStage")}
                </button>
                {candidate?.phase === "verified-staged" && (
                  <button
                    type="button"
                    data-marketplace-apply={entry.pluginId}
                    disabled={!runtime.view.managementAvailable || busy !== null}
                    onClick={() => void run(
                      `apply:${entry.pluginId}`,
                      () => runtime.actions.applyMarketplaceRelease(entry.pluginId),
                    )}
                  >
                    {busy === `apply:${entry.pluginId}` ? t("plugin.market.probing") : t("plugin.market.applyStaged")}
                  </button>
                )}
                {candidate?.phase === "activation-staged" && (
                  <button
                    type="button"
                    data-marketplace-activate={entry.pluginId}
                    disabled={!runtime.view.managementAvailable || !activationReady || busy !== null}
                    onClick={() => {
                      if (!window.confirm(t("plugin.market.activateConfirm", { plugin: entry.pluginId, version: candidate.version }))) return;
                      void run(
                        `activate:${entry.pluginId}`,
                        () => runtime.actions.activateMarketplaceRelease(entry.pluginId),
                      );
                    }}
                  >
                    {busy === `activate:${entry.pluginId}` ? t("plugin.market.activating") : t("plugin.market.activateObserve")}
                  </button>
                )}
              </div>
              {candidate?.phase === "activation-staged" && !activationReady && (
                <small>{t("plugin.host.grantEveryPermission")}</small>
              )}
            </article>
          );
        })}
        {status?.quarantine && status.quarantine.length > 0 && (
          <details className="plugin-technical-details" data-marketplace-quarantine>
            <summary>{t("plugin.market.quarantine", { count: status.quarantine.length })}</summary>
            {status.quarantine.map((item) => (
              <p key={`${item.bundleSha256}:${item.quarantinedAt}`}>
                {item.pluginId} {item.version} · {item.reason} · {item.quarantinedAt}
              </p>
            ))}
          </details>
        )}
        {query.trim() && catalog.plugins.length > 0 && !entries.length && <p role="status">{t("pc.noResults")}</p>}
        {catalog.enabled && !catalog.plugins.length && <p>{t("plugin.market.emptyIndex")}</p>}
      </div>
    </section>
  );
}

export function RuntimeRegistryPanel({ status }: { status: PluginRuntimeRegistryStatus }) {
  useLocale();
  const size = (value: number) => `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  return (
    <section className="plugin-settings-card plugin-runtime-registry-card" data-runtime-registry-revision={status.active.revision}>
      <header className="plugin-settings-card-header">
        <div>
          <h3>{t("plugin.runtime.hostManaged")}</h3>
          <p>
            {t("plugin.host.registryRevision", { id: status.active.registryId, revision: status.active.revision })} · {t("plugin.runtime.autoUpdateOff")}
          </p>
        </div>
        <span className="plugin-state-pill is-muted">{t("plugin.count", { count: status.runtimes.length })}</span>
      </header>
      {status.runtimes.map((item) => (
        <article key={`${item.runtimeId}:${item.kind}:${item.os}:${item.arch}`} className="plugin-runtime-registry-row">
          <strong>{item.runtimeId} · {item.version}</strong>
          <p>{item.kind} · {item.os}/{item.arch} · {size(item.size)} · {item.verificationStatus}</p>
          <small>
            {t("plugin.host.runtimeFingerprint", {
              owner: t("plugin.host.hostManaged"),
              license: item.license,
              refs: t("plugin.runtime.refs", { count: item.referenceCount }),
              hash: `${item.sha256.slice(7, 19)}…`,
            })}
          </small>
        </article>
      ))}
      {status.systemRuntimes.map((item) => (
        <article key={`${item.runtimeId}:${item.kind}`} className="plugin-runtime-registry-row is-system">
          <strong>{item.runtimeId} · {item.version}</strong>
          <p>{t("plugin.host.systemRuntime", { kind: item.kind, size: size(item.artifactSize), state: t("plugin.runtime.probed") })}</p>
          <small>{t("plugin.runtime.devLocal", { path: item.executable })}</small>
        </article>
      ))}
    </section>
  );
}

function changedLabel(changed: boolean): string {
  return t(changed ? "plugin.trust.changed" : "plugin.trust.same");
}

function trustAcknowledgementLabel(value: string): string {
  if (value === "execute-local-code") return t("plugin.ack.execute");
  if (value === "sandbox-status") return t("plugin.ack.sandbox");
  if (value === "live-authority-separate") return t("plugin.ack.authority");
  if (value.startsWith("runtime:")) {
    return t("plugin.ack.runtime", { runtime: value.slice("runtime:".length).replaceAll(":", " · ") });
  }
  if (value.startsWith("permission:")) {
    return t("plugin.ack.permission", { permission: value.slice("permission:".length) });
  }
  return value;
}

export function TrustRequestMatrix({ trust }: { trust: PluginTrustSummary["requests"] }) {
  useLocale();
  const rows = [
    [t("plugin.trust.network"), trust.network],
    [t("plugin.trust.files"), trust.files],
    [t("plugin.trust.secrets"), trust.secrets],
    [t("plugin.trust.accounts"), trust.accounts],
    [t("plugin.trust.trading"), trust.trading],
  ] as const;
  return (
    <div className="plugin-trust-risk-grid">
      {rows.map(([label, value]) => (
        <div key={label} data-requested={value.requested ? "true" : "false"}>
          <strong>{label}</strong>
          <span>{value.requested ? value.permissionIds.join("、") : t("plugin.trust.notRequested")}</span>
        </div>
      ))}
      <div data-requested="false">
        <strong>{t("plugin.trust.subprocess")}</strong>
        <span>{t("plugin.trust.subprocessLimit", { count: trust.subprocess.maxProcesses })}</span>
      </div>
    </div>
  );
}

export function LocalTrustInstallPanel({ runtime, onPendingChange }: { runtime: PluginPlatformRuntime; onPendingChange?(pending: boolean): void }) {
  useLocale();
  const [installed, setInstalled] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [candidate, setCandidate] = useState<PluginLocalInstallCandidate | null>(null);
  const [reason, setReason] = useState("");
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [review, setReview] = useState<PluginTrustReview | null>(null);
  const [busy, setBusy] = useState<"prepare" | "review" | "confirm" | null>(null);
  useEffect(() => { onPendingChange?.(busy !== null); }, [busy, onPendingChange]);

  const resetReview = () => setReview(null);
  const prepare = async (file: File) => {
    setBusy("prepare");
    setInstalled(false);
    setInstallError(null);
    setCandidate(null);
    setReason("");
    setAccepted(new Set());
    setReview(null);
    try { setCandidate(await runtime.actions.prepareLocalInstall(file)); } catch (error) { setInstallError(error instanceof Error ? describeError(error, error.message) : String(error)); }
    finally { setBusy(null); }
  };
  const required = candidate?.preview.requiredAcknowledgements ?? [];
  const allAccepted = required.length > 0 && required.every((item) => accepted.has(item));
  const firstConfirmation = async () => {
    if (!candidate || !allAccepted || busy || !runtime.view.managementAvailable) return;
    setBusy("review");
    setInstallError(null);
    try {
      setReview(await runtime.actions.reviewLocalInstall(
        candidate.candidateId,
        candidate.previewSha256,
        reason.trim(),
        [...accepted].sort(),
      ));
    } catch (error) { setReview(null); setInstallError(error instanceof Error ? describeError(error, error.message) : String(error)); }
    finally { setBusy(null); }
  };
  const secondConfirmation = async () => {
    if (!candidate || !review || busy || !runtime.view.managementAvailable) return;
    setBusy("confirm");
    setInstallError(null);
    try {
      await runtime.actions.confirmLocalInstall(
        candidate.candidateId,
        candidate.previewSha256,
        review.confirmationToken,
      );
      setInstalled(true);
      setCandidate(null);
      setReview(null);
      setAccepted(new Set());
      setReason("");
    } catch (error) { setReview(null); setInstallError(error instanceof Error ? describeError(error, error.message) : String(error)); }
    finally { setBusy(null); }
  };

  return (
    <section className="plugin-settings-card plugin-install-card plugin-trust-install-card" data-plugin-trust-flow="itemized-double-confirmation">
      <header className="plugin-settings-card-header">
        <div>
          <h3>{t("plugin.localInstall")}</h3>
          <p>{t("plugin.trust.localHint")}</p>
        </div>
        <span className="plugin-state-pill is-warn">{t("plugin.trust.localCode")}</span>
      </header>
      <ol className="pc-install-steps" aria-label={t("pc.install")}>
        <li aria-current={!candidate && !installed ? "step" : undefined}>{t("plugin.localInstall")}</li>
        <li aria-current={candidate && !review ? "step" : undefined}>{t("plugin.permissions")}</li>
        <li aria-current={review ? "step" : undefined}>{t("plugin.trust.secondInstall")}</li>
      </ol>
      {installError && <p role="alert">{installError}</p>}
      {installed && <p role="status">{t("plugin.installedHint")}</p>}
      <div className="plugin-install-row">
        <label className="plugin-install-button">
          <input
            type="file"
            accept=".cspkg,application/vnd.candlescope.plugin+zip"
            data-plugin-install-input
            disabled={!runtime.view.managementAvailable || busy !== null}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void prepare(file);
            }}
          />
          <span>{busy === "prepare" ? t("plugin.trust.verifying") : t("plugin.trust.pickReview")}</span>
        </label>
        <small>{t("plugin.trust.prepareHint")}</small>
      </div>
      {candidate && (
        <fieldset disabled={busy !== null || !runtime.view.managementAvailable} className="plugin-trust-review" data-preview-sha256={candidate.previewSha256}>
          <div className="plugin-trust-source">
            <strong>{candidate.preview.plugin.name} {candidate.preview.plugin.version}</strong>
            <span>{candidate.preview.plugin.publisher} · {candidate.preview.source.source}</span>
            <small>
              {t("plugin.trust.publisherId", { identity: candidate.preview.source.publisherIdentity })}
              {candidate.preview.source.signatureRoot
                ? t("plugin.signedRoot", { root: candidate.preview.source.signatureRoot })
                : t("plugin.unsignedLocal")}
            </small>
            <code>{candidate.preview.plugin.bundleSha256}</code>
          </div>
          <p className="plugin-trust-warning">{candidate.preview.warning}</p>
          <h4>{t("plugin.trust.whatRuns")}</h4>
          {candidate.preview.authorization.entrypoints.map((entrypoint) => (
            <div className="plugin-trust-runtime" key={entrypoint.entrypointId}>
              <strong>{entrypoint.entrypointId}</strong>
              <span>{entrypoint.runtimeKind} · {entrypoint.runtimeId} · {entrypoint.supplySource}</span>
              <small>
                  {entrypoint.hostManaged ? t("plugin.host.hostManaged") : t("plugin.bundledRuntime")}
                {` · ${entrypoint.profile.profileId} · maxProcesses=${entrypoint.profile.limits.maxProcesses}`}
              </small>
              {entrypoint.systemRuntimePath && <code>{entrypoint.systemRuntimePath}</code>}
            </div>
          ))}
          <p data-sandbox-status={candidate.preview.authorization.sandbox.status}>
            {t("plugin.trust.sandboxMode", {
              status: candidate.preview.authorization.sandbox.status,
              mode: candidate.preview.authorization.mode,
            })}
          </p>
          <TrustRequestMatrix trust={candidate.preview.requests} />
          <div className="plugin-trust-diffs">
            <div>
              <strong>{t("plugin.host.runtimeDiff")}</strong>
              <span>{candidate.preview.runtimeDiff.changed ? t("plugin.trust.changedMustConfirm") : t("plugin.trust.unchanged")}</span>
              <small>
                {t("plugin.host.kindOrId", { state: changedLabel(candidate.preview.runtimeDiff.kindOrIdChanged) })}
                {` · ${t("plugin.diff.sigRoot", { state: changedLabel(candidate.preview.runtimeDiff.signatureRootChanged) })}`}
                {` · ${t("plugin.diff.sysPath", { state: changedLabel(candidate.preview.runtimeDiff.systemRuntimePathChanged) })}`}
              </small>
            </div>
            <div>
              <strong>{t("plugin.host.permissionDiff")}</strong>
              <span>{candidate.preview.permissionDiff.requiresConfirmation ? t("plugin.trust.needReconfirm") : t("plugin.trust.noExpansion")}</span>
              <small>{candidate.preview.permissionDiff.permissions.map((item) => `${item.permissionId}: ${item.change}`).join(" · ") || t("plugin.trust.noHostApi")}</small>
            </div>
          </div>
          <label className="plugin-trust-reason">
            <span>{t("plugin.trust.reason")}</span>
            <textarea
              value={reason}
              maxLength={500}
              onChange={(event) => { setReason(event.target.value); resetReview(); }}
              placeholder={t("plugin.trust.reasonPh")}
            />
          </label>
          <fieldset className="plugin-trust-acknowledgements">
            <legend>{t("plugin.trust.itemized")}</legend>
            {required.map((item) => (
              <label key={item}>
                <input
                  type="checkbox"
                  checked={accepted.has(item)}
                  onChange={(event) => {
                    const next = new Set(accepted);
                    if (event.target.checked) next.add(item); else next.delete(item);
                    setAccepted(next);
                    resetReview();
                  }}
                />
                <span>{trustAcknowledgementLabel(item)}</span>
              </label>
            ))}
          </fieldset>
          <div className="plugin-action-row plugin-trust-confirmations">
            <button
              type="button"
              data-trust-confirmation-step="1"
              disabled={!allAccepted || reason.trim().length < 12 || busy !== null || review !== null}
              onClick={() => void firstConfirmation()}
            >
              {busy === "review" ? t("plugin.trust.recording") : t("plugin.trust.firstReview")}
            </button>
            <button
              type="button"
              data-trust-confirmation-step="2"
              className="is-danger"
              disabled={review === null || busy !== null}
              onClick={() => void secondConfirmation()}
            >
              {busy === "confirm" ? t("plugin.trust.installing") : t("plugin.trust.secondInstall")}
            </button>
          </div>
          {review && <small>{t("plugin.trust.firstRecorded", { expires: review.expiresAt })}</small>}
        </fieldset>
      )}
    </section>
  );
}

export function TrustModeControl({
  runtime,
  pluginId,
  trust,
  onComplete,
}: {
  runtime: PluginPlatformRuntime;
  pluginId: string;
  trust: PluginTrustSummary;
  onComplete: () => Promise<void>;
}) {
  useLocale();
  const target = trust.mode === "trusted-local" ? "marketplace-sandboxed" : "trusted-local";
  const acknowledgements = useMemo(() => {
    const values = new Set<string>(["execute-local-code", "sandbox-status", "live-authority-separate"]);
    trust.authorization.entrypoints.forEach((item) => values.add(`runtime:${item.entrypointId}:${item.runtimeKind}:${item.runtimeId}`));
    trust.requests.permissions.forEach((item) => values.add(`permission:${item.permissionId}`));
    return [...values].sort();
  }, [trust.authorization.entrypoints, trust.requests.permissions]);
  const [reason, setReason] = useState("");
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [review, setReview] = useState<PluginTrustChangeReview | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setReason(""); setAccepted(new Set()); setReview(null); }, [pluginId, trust.mode]);
  const allAccepted = acknowledgements.every((item) => accepted.has(item));
  const begin = async () => {
    setBusy(true);
    try { setReview(await runtime.actions.reviewTrustChange(pluginId, target, reason.trim(), [...accepted].sort())); }
    catch { setReview(null); }
    finally { setBusy(false); }
  };
  const confirm = async () => {
    if (!review) return;
    setBusy(true);
    try {
      await runtime.actions.confirmTrustChange(pluginId, review.changeId, review.previewSha256, review.confirmationToken);
      setReview(null);
      await onComplete();
    } catch { setReview(null); }
    finally { setBusy(false); }
  };
  return (
    <div className="plugin-trust-mode-control">
      <p className="plugin-trust-warning">{t("plugin.trust.signedWarning")}</p>
      <label className="plugin-trust-reason">
        <span>{t("plugin.trust.changeReason")}</span>
        <textarea value={reason} maxLength={500} onChange={(event) => { setReason(event.target.value); setReview(null); }} />
      </label>
      <fieldset className="plugin-trust-acknowledgements">
        <legend>{target === "trusted-local" ? t("plugin.trust.promote") : t("plugin.trust.revoke")}</legend>
        {acknowledgements.map((item) => (
          <label key={item}>
            <input type="checkbox" checked={accepted.has(item)} onChange={(event) => {
              const next = new Set(accepted);
              if (event.target.checked) next.add(item); else next.delete(item);
              setAccepted(next);
              setReview(null);
            }} />
            <span>{trustAcknowledgementLabel(item)}</span>
          </label>
        ))}
      </fieldset>
      {review && (
        <div className="plugin-trust-diffs" data-trust-change-preview={review.previewSha256}>
          <div>
            <strong>{t("plugin.trust.frozenBoundary")}</strong>
            <span>{review.preview.to.mode} · {review.preview.to.sandbox.status}</span>
            <small>
              {t("plugin.diff.runtime", { state: changedLabel(review.preview.runtimeDiff.changed) })}
              {` · kind/id ${changedLabel(review.preview.runtimeDiff.kindOrIdChanged)}`}
              {` · ${t("plugin.diff.sigRoot", { state: changedLabel(review.preview.runtimeDiff.signatureRootChanged) })}`}
              {` · ${t("plugin.diff.sysPath", { state: changedLabel(review.preview.runtimeDiff.systemRuntimePathChanged) })}`}
            </small>
          </div>
          <div>
            <strong>{t("plugin.trust.frozenDiff")}</strong>
            <span>{review.preview.permissionDiff.requiresConfirmation ? t("plugin.trust.noInherit") : t("plugin.trust.noAuthExpand")}</span>
            <small>
              {review.preview.permissionDiff.permissions.map((item) => `${item.permissionId}: ${item.change}`).join(" · ") || t("plugin.trust.noHostApi")}
            </small>
          </div>
        </div>
      )}
      <div className="plugin-action-row">
        <button type="button" disabled={busy || !allAccepted || reason.trim().length < 12 || review !== null} onClick={() => void begin()}>
          {t("plugin.trust.firstReviewTarget", { target })}
        </button>
        <button type="button" disabled={busy || review === null} onClick={() => void confirm()}>
          {t("plugin.trust.secondApply")}
        </button>
      </div>
    </div>
  );
}
