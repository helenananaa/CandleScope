import PreparationJobsPanel from "../../data-preparation/PreparationJobsPanel.js";
import { useState } from "react";
import ReplayRawTradeRetentionPanel from "./ReplayRawTradeRetentionPanel.js";
import { Badge, Button, Checkbox, Dialog, Disclosure, EmptyState, Field, InlineAlert, Input, Select } from "../../../components/ui/index.js";

import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type {
  ReplayStorageCategoryName,
  ReplayStorageGcProtocol,
  ReplayStorageObjectCategory,
  ReplayStorageObjectItem,
} from "../replayStorageModel.js";
import type { TrainingHubRuntime } from "../useTrainingHub.js";


const GIB = 1024 * 1024 * 1024;
const MIB = 1024 * 1024;

const CATEGORY_NAMES = [
  "segments",
  "historical_books",
  "account_history",
  "review_evidence",
] as const satisfies readonly ReplayStorageCategoryName[];

function categoryLabel(name: ReplayStorageCategoryName): string {
  switch (name) {
    case "segments":
      return t("replay.storage.segments");
    case "historical_books":
      return t("replay.storage.books");
    case "account_history":
      return t("replay.storage.accountHistory");
    case "review_evidence":
      return t("replay.storage.reviewEvidence");
  }
}

const GC_CATEGORIES = [
  "segments",
  "historical_books",
  "account_history",
] as const;

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < MIB) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < GIB) return `${(value / MIB).toFixed(1)} MiB`;
  return `${(value / GIB).toFixed(2)} GiB`;
}

function identityLabel(item: ReplayStorageObjectItem): string {
  return [
    item.identity.exchange,
    item.identity.market_type,
    item.identity.symbol,
    item.identity.base_interval,
  ].filter((value): value is string => typeof value === "string").join(" · ");
}

function StorageObjectRows({
  category,
  protocol,
  runtime,
}: {
  readonly category: ReplayStorageObjectCategory;
  readonly protocol: ReplayStorageGcProtocol;
  readonly runtime: TrainingHubRuntime;
}) {
  useLocale();
  if (category.items.length === 0) return <p className="replay-storage-note">{t("replay.storage.empty")}</p>;
  return (
    <ul className="replay-storage-object-list">
      {category.items.map((item) => (
        <li key={item.object_id} data-storage-object={item.object_id}>
          <div className="replay-storage-object-head">
            <strong>{identityLabel(item)}</strong>
            <Badge tone={item.health === "READY" ? "neutral" : "warning"} data-storage-health={item.health}>{item.health}</Badge>
          </div>
          <dl className="replay-storage-object-facts">
            <div><dt>{t("replay.storage.objects")}</dt><dd><code>{item.object_id}</code></dd></div>
            <div><dt>{t("replay.storage.size")}</dt><dd>{formatBytes(item.byte_size)}</dd></div>
            <div><dt>{t("replay.storage.refs")}</dt><dd>{item.active_ref_count}</dd></div>
            <div><dt>{t("replay.storage.recover")}</dt><dd>{item.recoverability}</dd></div>
          </dl>
          <p className="replay-storage-note">
            {item.protection_reasons.length === 0
              ? t("replay.storage.noProtect")
              : t("replay.storage.protect", { reasons: item.protection_reasons.join(" · ") })}
          </p>
          {item.health !== "READY" && item.rehydration_available && (
            <Button
              size="sm"
              disabled={runtime.operation !== null}
              onClick={() => void runtime.actions.rehydrateStorageObject(
                protocol,
                item.object_id,
              )}
            >
              {t("replay.storage.rehydrate")}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function ReplayStorageGovernancePanel({
  runtime,
}: {
  readonly runtime: TrainingHubRuntime;
}) {
  useLocale();
  const [gcCategory, setGcCategory] = useState<(typeof GC_CATEGORIES)[number]>(
    "segments",
  );
  const [targetMiB, setTargetMiB] = useState(256);
  const [maxObjects, setMaxObjects] = useState(100);
  if (!runtime.storageOpen) return null;
  const inventory = runtime.storageInventory;
  const selected = inventory?.categories[gcCategory] ?? null;
  const busy = runtime.operation?.startsWith("storage-") ?? false;
  const targetBytes = Number.isSafeInteger(targetMiB) && targetMiB > 0
    ? targetMiB * MIB
    : 0;
  const validRequest = Number.isSafeInteger(targetBytes)
    && targetBytes >= 1
    && targetBytes <= 1_000_000_000_000
    && Number.isSafeInteger(maxObjects)
    && maxObjects >= 1
    && maxObjects <= 10_000;

  const pressure = (bps: number) => `${(bps / 100).toFixed(1)}%`;
  const alertTone = (severity: "INFO" | "WARNING" | "CRITICAL") => (severity === "CRITICAL" ? "danger" : severity === "WARNING" ? "warning" : "info");

  return (
    <Dialog
      open
      size="lg"
      className="replay-storage-governance"
      title={t("replay.storage.title")}
      description={t("replay.storage.hint")}
      onClose={runtime.actions.closeStorage}
      footer={<>
        <Button disabled={busy} onClick={() => void runtime.actions.refreshStorage()}>{t("replay.storage.refresh")}</Button>
        <Button onClick={runtime.actions.closeStorage}>{t("replay.hub.close")}</Button>
      </>}
    >
      <div className="replay-storage-body" aria-label={t("replay.storage.aria")} data-replay-storage-phase={runtime.operation ?? "ready"}>
        {inventory === null ? (
          <EmptyState compact icon={<span className="replay-loading-spinner" />} title={t("replay.storage.loading")} />
        ) : (
          <>
            <div className="replay-storage-status" data-release-decision={inventory.decision.state}>
              <InlineAlert tone={inventory.decision.state === "ENABLE" ? "success" : "warning"} title={t("replay.storage.decision", { state: inventory.decision.state })}>
                {t("replay.storage.defaultFlags", { value: inventory.decision.default_flags_enabled ? "ON" : "OFF" })}
                {inventory.decision.reason_codes.length > 0 && <> · <span className="replay-storage-codes">{inventory.decision.reason_codes.join(" · ")}</span></>}
              </InlineAlert>
              {inventory.alerts.length > 0 && (
                <div className="replay-storage-alerts" aria-label={t("replay.storage.alerts")}>
                  {inventory.alerts.map((alert) => (
                    <InlineAlert key={`${alert.category}:${alert.code}`} tone={alertTone(alert.severity)} title={`${alert.severity} · ${alert.code}`}>
                      {alert.message}
                    </InlineAlert>
                  ))}
                </div>
              )}
            </div>

            <section className="replay-storage-section" aria-labelledby="replay-storage-data-title">
              <h3 id="replay-storage-data-title">{t("replay.storage.dataTitle")}</h3>
              <div className="replay-storage-categories">
                {CATEGORY_NAMES.map((name) => {
                  const category = inventory.categories[name];
                  return (
                    <article key={name} className="replay-storage-category" data-storage-category={name}>
                      <div className="replay-storage-category-head">
                        <strong>{categoryLabel(name)}</strong>
                        <span>{formatBytes(category.summary.local_bytes)} / {formatBytes(category.summary.max_bytes)}</span>
                        <span className="replay-storage-figure">{pressure(category.summary.pressure_bps)}</span>
                      </div>
                      <Disclosure summary={t("replay.storage.details")}>
                        <dl className="replay-storage-counts">
                          <div><dt>{t("replay.storage.objects")}</dt><dd>{category.summary.object_count}</dd></div>
                          <div><dt>{t("replay.storage.ready")}</dt><dd>{category.summary.ready_count}</dd></div>
                          <div><dt>{t("replay.storage.evicted")}</dt><dd>{category.summary.evicted_count}</dd></div>
                          <div><dt>{t("replay.storage.isolated")}</dt><dd>{category.summary.quarantined_count}</dd></div>
                          <div><dt>{t("replay.storage.protected")}</dt><dd>{category.summary.pinned_count}</dd></div>
                        </dl>
                        {name === "review_evidence" ? (
                          <>
                            <p className="replay-storage-note">{t("replay.storage.archivePinned")}</p>
                            <ul className="replay-storage-object-list">
                              {inventory.categories.review_evidence.items.map((item) => (
                                <li key={item.run_id} data-review-storage-run={item.run_id}>
                                  <div className="replay-storage-object-head">
                                    <strong><code>{item.run_id}</code></strong>
                                    <Badge>{item.run_state}</Badge>
                                  </div>
                                  <p className="replay-storage-note">
                                    {t("replay.storage.anchorBytes", { used: formatBytes(item.anchor_bytes), limit: formatBytes(item.anchor_limit_bytes) })}
                                    {" · "}
                                    {t("replay.storage.artifactBytes", { used: formatBytes(item.artifact_bytes), limit: formatBytes(item.artifact_limit_bytes) })}
                                  </p>
                                  <p className="replay-storage-note replay-storage-codes">{item.protection_reasons.join(" · ")}</p>
                                </li>
                              ))}
                            </ul>
                          </>
                        ) : (
                          <StorageObjectRows
                            category={category as ReplayStorageObjectCategory}
                            protocol={(category as ReplayStorageObjectCategory).gc_protocol}
                            runtime={runtime}
                          />
                        )}
                      </Disclosure>
                    </article>
                  );
                })}
              </div>
            </section>

            <section className="replay-storage-section" aria-label={t("replay.storage.gc")}>
              <h3>{t("replay.storage.gcTitle")}</h3>
              <p className="replay-storage-hint">{t("replay.storage.gcHint")}</p>
              <div className="replay-storage-form">
                <Field label={t("replay.storage.category")}>
                  <Select
                    value={gcCategory}
                    disabled={busy}
                    onChange={(event) => setGcCategory(event.target.value as (typeof GC_CATEGORIES)[number])}
                  >
                    {GC_CATEGORIES.map((name) => (
                      <option key={name} value={name}>{categoryLabel(name)}</option>
                    ))}
                  </Select>
                </Field>
                <Field label={t("replay.storage.targetMib")}>
                  <Input type="number" min={1} max={953_674} value={targetMiB} disabled={busy}
                    onChange={(event) => setTargetMiB(Number(event.target.value))} />
                </Field>
                <Field label={t("replay.storage.maxObjects")}>
                  <Input type="number" min={1} max={10_000} value={maxObjects} disabled={busy}
                    onChange={(event) => setMaxObjects(Number(event.target.value))} />
                </Field>
                <Button
                  disabled={busy || selected === null || !validRequest}
                  onClick={() => {
                    if (selected === null) return;
                    void runtime.actions.planStorageGc(selected.gc_protocol, targetBytes, maxObjects);
                  }}
                >
                  {runtime.operation === "storage-plan" ? t("replay.storage.planning") : t("replay.storage.plan")}
                </Button>
              </div>

              {runtime.storagePlan !== null && (
                <div className="replay-storage-plan" data-storage-plan-hash={runtime.storagePlan.plan_hash}>
                  <p><strong>{t("replay.storage.planLabel")}</strong> <code>{runtime.storagePlan.plan_hash}</code></p>
                  <p>
                    {t("replay.storage.candidatesPlan", {
                      count: runtime.storagePlan.candidates.length,
                      bytes: formatBytes(runtime.storagePlan.estimated_reclaim_bytes),
                      protected: runtime.storagePlan.protected.length,
                    })}
                  </p>
                  <ul>
                    {runtime.storagePlan.candidates.map((item) => (
                      <li key={item.object_id}><code>{item.object_id}</code> · {formatBytes(item.byte_size)}</li>
                    ))}
                    {runtime.storagePlan.protected.map((item) => (
                      <li key={`protected:${item.object_id}`}>
                        {t("replay.storage.keep", { id: item.object_id, reasons: item.protection_reasons.join(" / ") })}
                      </li>
                    ))}
                  </ul>
                  <Checkbox
                    label={t("replay.storage.confirmHash")}
                    checked={runtime.storagePlanConfirmed}
                    disabled={busy}
                    onChange={(event) => runtime.actions.confirmStoragePlan(event.target.checked)}
                  />
                  <div>
                    <Button
                      variant="danger"
                      disabled={busy || !runtime.storagePlanConfirmed || runtime.storagePlan.candidates.length === 0}
                      onClick={() => void runtime.actions.runStorageGc()}
                    >
                      {runtime.operation === "storage-run" ? t("replay.storage.running") : t("replay.storage.run")}
                    </Button>
                  </div>
                </div>
              )}

              {runtime.storageResult !== null && (
                <InlineAlert tone="success">
                  {t("replay.storage.reclaimed", {
                    bytes: formatBytes(runtime.storageResult.reclaimed_bytes),
                    reclaimed: runtime.storageResult.reclaimed.length,
                    skipped: runtime.storageResult.skipped.length,
                  })}
                </InlineAlert>
              )}
            </section>
          </>
        )}

        <ReplayRawTradeRetentionPanel disabled={busy} formatBytes={formatBytes} />
        <PreparationJobsPanel />

        {inventory !== null && (
          <Disclosure className="replay-storage-support" summary={t("replay.storage.supportTitle")}>
            <ul className="replay-storage-object-list" aria-label={t("replay.storage.support")}>
              {inventory.support_matrix.map((support) => (
                <li key={support.mode} data-storage-support={support.mode}>
                  <div className="replay-storage-object-head">
                    <strong>{support.mode}</strong>
                    <Badge tone={support.production_readiness === "ENABLE" ? "success" : "warning"}>{support.production_readiness}</Badge>
                  </div>
                  <p className="replay-storage-note replay-storage-codes">
                    {[support.source_contract, support.declared_scope, support.fidelity].join(" · ")}
                  </p>
                  <p className="replay-storage-note">
                    {t("replay.storage.queueExact")} · {t("replay.storage.identities", { count: support.observed_identities.length })}
                  </p>
                  {support.reason_codes.length > 0 && <p className="replay-storage-note replay-storage-codes">{support.reason_codes.join(" · ")}</p>}
                </li>
              ))}
            </ul>
          </Disclosure>
        )}
      </div>
    </Dialog>
  );
}
