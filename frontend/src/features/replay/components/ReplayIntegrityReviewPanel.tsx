import { useMemo, useState } from "react";
import { confirmAction } from "../../../components/ui/overlay/overlayApi.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { Icon } from "../../../components/icons/Icon.js";
import { Badge, Button, Disclosure, EmptyState, Field, IconButton, InlineAlert, Input, Select } from "../../../components/ui/index.js";
import { trainingIntegrityLabel, trainingTimeDisclosureLabel } from "../trainingHubLabels.js";

import { buildEquityPolyline } from "../replayIntegrityModel.js";
import { downloadReplayTrainingReport } from "../replayReportExport.js";
import { replayOwnsController } from "../replayUiModel.js";
import type { ReplayRuntime } from "../useReplayRuntime.js";
import type { ReplayIntegrityRuntime } from "../useReplayIntegrityRuntime.js";
import ReplayLiquidationTimeline from "./ReplayLiquidationTimeline.js";
import ReplayPortfolioCurve from "./ReplayPortfolioCurve.js";

export interface ReplayIntegrityReviewPanelProps {
  readonly runtime: ReplayRuntime;
  readonly integrityRuntime: ReplayIntegrityRuntime;
  readonly trainingState?: string | null;
  readonly onClose?: (() => void) | undefined;
}

function AuditValue({ value }: { readonly value: Readonly<Record<string, unknown>> }) {
  return <code>{JSON.stringify(value)}</code>;
}

export default function ReplayIntegrityReviewPanel({
  runtime,
  integrityRuntime,
  trainingState = null,
  onClose,
}: ReplayIntegrityReviewPanelProps) {
  useLocale();
  const [amount, setAmount] = useState("100");
  const [reason, setReason] = useState("training adjustment");
  const [makerFeeBps, setMakerFeeBps] = useState("");
  const [takerFeeBps, setTakerFeeBps] = useState("");
  const [maxLeverage, setMaxLeverage] = useState("");
  const [fundingMode, setFundingMode] = useState<"OFF" | "SANDBOX_FIXED">("OFF");
  const [fixedFundingRate, setFixedFundingRate] = useState("0.0001");
  const [fundingIntervalMs, setFundingIntervalMs] = useState("28800000");
  const [markerText, setMarkerText] = useState("");
  const [playbackRate, setPlaybackRate] = useState<"0.25" | "0.5" | "1" | "2" | "4" | "8">("1");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const integrity = integrityRuntime.integrity;
  const rules = integrityRuntime.rules;
  const review = integrityRuntime.review;
  const report = integrityRuntime.report;
  const ownsController = replayOwnsController(runtime.store, runtime.clientInstanceId);
  const busy = integrityRuntime.operation !== null;
  const equityPoints = useMemo(() => buildEquityPolyline(
    integrityRuntime.equity?.samples ?? [],
    420,
    112,
  ), [integrityRuntime.equity?.samples]);

  const header = (
    <header className="replay-drawer-head">
      <h2 id="replay-integrity-title">{t("replay.integrity.title")}</h2>
      <div className="replay-drawer-actions">
        {integrity !== null && (
          <IconButton size="sm" label={t("replay.hub.refresh")} icon={<Icon name="refresh" size={15} />} disabled={busy}
            onClick={() => void integrityRuntime.actions.refresh()} />
        )}
        {onClose !== undefined && (
          <IconButton size="sm" data-replay-action="close-integrity" label={t("replay.hub.close")} icon={<Icon name="close" size={15} />} onClick={onClose} />
        )}
      </div>
    </header>
  );

  if (integrity === null && integrityRuntime.error === null) {
    return (
      <section className="replay-drawer-panel" data-replay-panel="integrity" aria-labelledby="replay-integrity-title">
        {header}
        <div className="replay-drawer-body">
          <EmptyState compact icon={<span className="replay-loading-spinner" />} title={t("replay.integrity.loading")} />
        </div>
      </section>
    );
  }

  const allowed = new Set(integrity?.allowed_mutations ?? []);
  const effectiveSelectedEventId = review === null
    ? null
    : review.events.some((event) => event.event_id === selectedEventId)
      ? selectedEventId
      : review.selected_event_id;
  const canCapital = ownsController && !busy && runtime.store.state !== "ENDED"
    && review === null;
  const canMutateRules = ownsController && !busy && runtime.store.state !== "ENDED"
    && review === null;
  const fundingInterval = Number(fundingIntervalMs);
  const fundingPolicyValid = fundingMode === "OFF" || (
    integrity?.integrity_mode === "SANDBOX"
    && Number.isSafeInteger(fundingInterval)
    && fundingInterval >= 60_000
    && fundingInterval <= 30 * 86_400_000
    && fixedFundingRate.length > 0
  );
  const canReveal = ownsController && !busy && review === null
    && integrity !== null && !integrity.revealed
    && (runtime.store.state === "ENDED" || allowed.has("reveal_time"));
  const reviewOriginalState = trainingState ?? runtime.store.state;
  const reviewStartReady = reviewOriginalState === "PAUSED"
    || reviewOriginalState === "ENDED";
  const submitCapital = (kind: "deposit" | "withdraw") => {
    const action = kind === "deposit"
      ? integrityRuntime.actions.deposit
      : integrityRuntime.actions.withdraw;
    void action(amount, reason).catch(() => undefined);
  };
  const budget = review?.budget ?? integrityRuntime.budget;
  const budgetPressure = budget === null ? 0 : Math.max(
    budget.critical_events / budget.critical_event_limit,
    budget.viewport_samples / budget.viewport_sample_limit,
    budget.anchor_used_bytes / budget.anchor_limit_bytes,
    budget.artifact_used_bytes / budget.artifact_limit_bytes,
  );

  return (
    <section
      className="replay-drawer-panel"
      data-replay-panel="integrity"
      data-integrity-mode={integrity?.integrity_mode ?? "unavailable"}
      data-time-disclosure-policy={integrity?.effective_time_disclosure_policy ?? "unavailable"}
      data-result-label={integrity?.result_label ?? "unavailable"}
      aria-labelledby="replay-integrity-title"
    >
      {header}
      <div className="replay-drawer-body">
        {integrityRuntime.error !== null && (
          <div className="replay-command-error"><InlineAlert tone="danger">{integrityRuntime.error}</InlineAlert></div>
        )}

        {integrity !== null && (
          <>
            <dl className="replay-integrity-facts">
              <div><dt>{t("replay.integrity.mode")}</dt><dd><Badge tone="accent">{trainingIntegrityLabel(integrity.integrity_mode)}</Badge></dd></div>
              <div><dt>{t("replay.integrity.publicTime")}</dt><dd data-public-time-label>{integrity.public_time.label}</dd></div>
              <div><dt>{t("replay.integrity.disclosure")}</dt><dd>{trainingTimeDisclosureLabel(integrity.effective_time_disclosure_policy)}</dd></div>
              <div><dt>{t("replay.integrity.strict")}</dt><dd>{integrity.strict_eligible ? <Badge tone="success">ELIGIBLE</Badge> : <Badge>NOT STRICT</Badge>}</dd></div>
              <div><dt>{t("replay.integrity.startKnown")}</dt><dd>{integrity.start_time_known ? "YES" : "NO"}</dd></div>
              <div><dt>{t("replay.integrity.result")}</dt><dd><code>{integrity.result_label}</code></dd></div>
            </dl>

            <section className="replay-drawer-section" aria-labelledby="replay-equity-title">
              <div className="replay-drawer-section-head">
                <h3 id="replay-equity-title">{t("replay.integrity.equity")}</h3>
                <span>{t("replay.integrity.sampleCount", {
                  resolution: integrityRuntime.equity?.resolution ?? "--",
                  count: integrityRuntime.equity?.samples.length ?? 0,
                })}</span>
              </div>
              <svg
                className="replay-equity-chart"
                viewBox="0 0 420 112"
                role="img"
                aria-label={t("replay.integrity.equityAria")}
                preserveAspectRatio="none"
              >
                <polyline points={equityPoints} fill="none" vectorEffect="non-scaling-stroke" />
              </svg>
              <p className="replay-drawer-note">{t("replay.integrity.equityHint")}</p>
              <ReplayPortfolioCurve runId={integrityRuntime.runId} />
            </section>

            <section className="replay-drawer-section" aria-labelledby="replay-policy-title">
              <div className="replay-drawer-section-head">
                <h3 id="replay-policy-title">{t("replay.integrity.policy")}</h3>
                <span className="replay-drawer-codes">{integrity.allowed_mutations.length === 0 ? "LOCKED" : integrity.allowed_mutations.join(" · ")}</span>
              </div>
              {(allowed.has("deposit") || allowed.has("withdraw")) && (
                <div className="replay-drawer-form">
                  <Field label={t("replay.integrity.amount")}><Input value={amount} inputMode="decimal" onChange={(event) => setAmount(event.target.value)} /></Field>
                  <Field label={t("replay.integrity.reason")}><Input value={reason} maxLength={512} onChange={(event) => setReason(event.target.value)} /></Field>
                  <div className="replay-drawer-form-actions">
                    {allowed.has("deposit") && <Button disabled={!canCapital} onClick={() => submitCapital("deposit")}>{t("replay.integrity.deposit")}</Button>}
                    {allowed.has("withdraw") && <Button disabled={!canCapital} onClick={() => submitCapital("withdraw")}>{t("replay.integrity.withdraw")}</Button>}
                  </div>
                </div>
              )}
              {!integrity.revealed && (
                <div>
                  <Button
                    variant="danger"
                    size="sm"
                    data-replay-action="reveal-time"
                    disabled={!canReveal}
                    title={ownsController ? t("replay.integrity.revealTitle") : t("replay.integrity.needLease")}
                    onClick={() => void (async () => {
                      if (await confirmAction({ title: t("replay.integrity.revealConfirm"), confirmLabel: t("replay.integrity.reveal"), tone: "danger" })) {
                        void integrityRuntime.actions.revealTime(reason).catch(() => undefined);
                      }
                    })()}
                  >{t("replay.integrity.reveal")}</Button>
                </div>
              )}
              {integrity.revealed && <InlineAlert tone="info">{t("replay.integrity.revealed")}</InlineAlert>}
              <p className="replay-drawer-note">{t("replay.integrity.atomic")}</p>
            </section>

            <section className="replay-drawer-section" aria-labelledby="replay-run-rules-title">
              <div className="replay-drawer-section-head">
                <h3 id="replay-run-rules-title">{t("replay.integrity.rules")}</h3>
                <span>{rules === null ? t("replay.integrity.loading") : t("replay.integrity.revisions", { count: rules.history.length })}</span>
              </div>
              <p className="replay-drawer-note">{t("replay.integrity.rulesHint")}</p>
              {rules !== null && (
                <>
                  <dl className="replay-integrity-facts">
                    <div><dt>{t("replay.integrity.makerTaker")}</dt><dd>{rules.fee_policy.maker_fee_bps} / {rules.fee_policy.taker_fee_bps} bps</dd></div>
                    <div><dt>{t("replay.integrity.userLeverage")}</dt><dd>{rules.leverage_policy.max_leverage}×</dd></div>
                    <div><dt>{t("replay.integrity.funding")}</dt><dd>{rules.funding_policy.funding_mode}</dd></div>
                    <div><dt>{t("replay.integrity.exchangeRules")}</dt><dd>{t("replay.integrity.immutableRules", { count: rules.instrument_rules.length })}</dd></div>
                  </dl>
                  <Disclosure summary={t("replay.integrity.editRules")}>
                    <div className="replay-rule-forms">
                      <form className="replay-rule-form" onSubmit={(event) => {
                        event.preventDefault();
                        void integrityRuntime.actions.changeFeePolicy(
                          makerFeeBps || rules.fee_policy.maker_fee_bps,
                          takerFeeBps || rules.fee_policy.taker_fee_bps,
                          reason,
                        ).catch(() => undefined);
                      }}>
                        <strong>{t("replay.integrity.feeRev")}</strong>
                        <Field label={t("replay.integrity.makerBps")}><Input size="sm" inputMode="decimal" value={makerFeeBps} placeholder={rules.fee_policy.maker_fee_bps} onChange={(event) => setMakerFeeBps(event.target.value)} /></Field>
                        <Field label={t("replay.integrity.takerBps")}><Input size="sm" inputMode="decimal" value={takerFeeBps} placeholder={rules.fee_policy.taker_fee_bps} onChange={(event) => setTakerFeeBps(event.target.value)} /></Field>
                        <Button size="sm" type="submit" disabled={!canMutateRules || !allowed.has("change_fee_policy")}>{t("replay.integrity.submit")}</Button>
                      </form>
                      <form className="replay-rule-form" onSubmit={(event) => {
                        event.preventDefault();
                        void integrityRuntime.actions.changeLeverageCap(
                          maxLeverage || rules.leverage_policy.max_leverage,
                          reason,
                        ).catch(() => undefined);
                      }}>
                        <strong>{t("replay.integrity.leverageOverlay")}</strong>
                        <Field label={t("replay.integrity.maxMult")} hint={Object.entries(rules.effective_leverage_by_track).map(([track, value]) => `${track}=${value}×`).join(" · ")}>
                          <Input size="sm" inputMode="decimal" value={maxLeverage} placeholder={rules.leverage_policy.max_leverage} onChange={(event) => setMaxLeverage(event.target.value)} />
                        </Field>
                        <Button size="sm" type="submit" disabled={!canMutateRules || !allowed.has("change_leverage_cap")}>{t("replay.integrity.submit")}</Button>
                      </form>
                      <form className="replay-rule-form" onSubmit={(event) => {
                        event.preventDefault();
                        if (!fundingPolicyValid) return;
                        void integrityRuntime.actions.changeFundingPolicy(
                          fundingMode,
                          fundingMode === "OFF" ? null : fixedFundingRate,
                          fundingMode === "OFF" ? null : fundingInterval,
                          reason,
                        ).catch(() => undefined);
                      }}>
                        <strong>{t("replay.integrity.sandboxFunding")}</strong>
                        <Field label={t("replay.integrity.fundingMode")}>
                          <Select size="sm" value={fundingMode} onChange={(event) => setFundingMode(event.target.value as "OFF" | "SANDBOX_FIXED")}>
                            <option value="OFF">{t("replay.hub.modeOff")}</option><option value="SANDBOX_FIXED">{t("replay.integrity.sandboxFixed")}</option>
                          </Select>
                        </Field>
                        <Field label={t("replay.integrity.rate")}><Input size="sm" inputMode="decimal" disabled={fundingMode === "OFF"} value={fixedFundingRate} onChange={(event) => setFixedFundingRate(event.target.value)} /></Field>
                        <Field label={t("replay.integrity.intervalMs")}><Input size="sm" inputMode="numeric" disabled={fundingMode === "OFF"} value={fundingIntervalMs} onChange={(event) => setFundingIntervalMs(event.target.value)} /></Field>
                        <Button
                          size="sm"
                          type="submit"
                          title={fundingPolicyValid ? t("replay.integrity.submitRev") : t("replay.integrity.fundingSandboxOnly")}
                          disabled={!canMutateRules || !allowed.has("change_funding_policy") || !fundingPolicyValid}
                        >{t("replay.integrity.submit")}</Button>
                      </form>
                    </div>
                    <Field label={t("replay.integrity.changeReason")} className="replay-rule-reason">
                      <Input value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} />
                    </Field>
                  </Disclosure>
                  <Disclosure summary={`${t("replay.integrity.ruleHistory")} · ${rules.history.length}`}>
                    <ul className="replay-drawer-list" aria-label={t("replay.integrity.ruleHistory")}>
                      {rules.history.map((revision) => (
                        <li key={`${revision.kind}-${revision.revision}-${revision.policy_hash}`}>
                          <div className="replay-drawer-list-head"><strong>{revision.kind} r{revision.revision}</strong><span>{revision.public_time.label}</span></div>
                          <span>{revision.reason}</span>
                          <code>{revision.command_id ?? "creation"} · {revision.policy_hash}</code>
                        </li>
                      ))}
                    </ul>
                  </Disclosure>
                </>
              )}
            </section>

            <section className="replay-drawer-section" aria-labelledby="replay-review-budget-title" data-budget-warning={budgetPressure >= 0.85 ? "true" : "false"}>
              <div className="replay-drawer-section-head">
                <h3 id="replay-review-budget-title">{t("replay.integrity.budget")}</h3>
                <strong>{budget === null ? "--" : `${Math.round(budgetPressure * 100)}% peak`}</strong>
              </div>
              {budget !== null && (
                <p className="replay-drawer-note replay-budget-line">
                  <span>{t("replay.integrity.criticalEvents", { count: budget.critical_events, limit: budget.critical_event_limit })}</span>
                  <span>{t("replay.integrity.viewportBudget", { used: budget.viewport_samples, limit: budget.viewport_sample_limit })}</span>
                  <span>{t("replay.integrity.anchorBudget", { used: Math.round(budget.anchor_used_bytes / 1_048_576), limit: Math.round(budget.anchor_limit_bytes / 1_048_576) })}</span>
                  <span>{t("replay.integrity.artifactBudget", { used: Math.round(budget.artifact_used_bytes / 1_048_576), limit: Math.round(budget.artifact_limit_bytes / 1_048_576) })}</span>
                </p>
              )}
              {budgetPressure >= 0.85 && <InlineAlert tone="warning">{t("replay.integrity.budgetWarn")}</InlineAlert>}
            </section>

            <section className="replay-drawer-section" aria-labelledby="replay-audit-title">
              <div className="replay-drawer-section-head">
                <h3 id="replay-audit-title">{t("replay.integrity.audit")}</h3>
                <span>{integrity.mutations.length}</span>
              </div>
              {integrity.mutations.length === 0 ? <p className="replay-drawer-note">{t("replay.integrity.noMutations")}</p> : (
                <Disclosure summary={t("replay.storage.details")}>
                  <ul className="replay-drawer-list">
                    {integrity.mutations.slice(-20).map((mutation) => (
                      <li key={mutation.event_id} data-audit-event={mutation.event_type}>
                        <div className="replay-drawer-list-head"><strong>{mutation.event_type}</strong><span>{t("replay.integrity.ruleRevision", { time: mutation.public_time.label, revision: mutation.rule_revision })}</span></div>
                        <span>{mutation.reason}</span>
                        <span className="replay-audit-change"><AuditValue value={mutation.old_value} /> → <AuditValue value={mutation.new_value} /></span>
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              )}
            </section>

            {report !== null && (
              <section className="replay-drawer-section" data-replay-panel="report" aria-labelledby="replay-phase4-report-title">
                <div className="replay-drawer-section-head">
                  <h3 id="replay-phase4-report-title">{t("replay.integrity.report")}</h3>
                  <div className="replay-drawer-actions">
                    <Button size="sm" onClick={() => downloadReplayTrainingReport(report, "json")}>{t("replay.integrity.exportJson")}</Button>
                    <Button size="sm" onClick={() => downloadReplayTrainingReport(report, "csv")}>{t("replay.integrity.exportCsv")}</Button>
                  </div>
                </div>
                <code className="replay-drawer-codes">{report.report.report_hash}</code>
                <dl className="replay-integrity-facts">
                  <div><dt>{t("replay.integrity.finalEquity")}</dt><dd>{report.report.final_equity}</dd></div>
                  <div><dt>{t("replay.integrity.realizedPnl")}</dt><dd>{report.report.realized_pnl}</dd></div>
                  <div><dt>{t("replay.integrity.fees")}</dt><dd>{report.report.fees_paid}</dd></div>
                  <div><dt>{t("replay.integrity.trades")}</dt><dd>{report.report.trade_count}</dd></div>
                  {report.modelled_account.schema_version === "replay.training.portfolio.v2" && (
                    <>
                      <div><dt>{t("replay.integrity.accountInputs")}</dt><dd>{report.modelled_account.account_history.mode}</dd></div>
                      <div>
                        <dt>{t("replay.integrity.accountAudit")}</dt>
                        <dd data-account-auditor-status={report.modelled_account.account_history.auditor.status}>{report.modelled_account.account_history.auditor.status}</dd>
                      </div>
                      <div><dt>{t("replay.integrity.simLiq")}</dt><dd>{report.modelled_account.liquidations.length + report.modelled_account.liquidation_recoveries.length}</dd></div>
                      <div><dt>{t("replay.integrity.mktLiq")}</dt><dd>{report.modelled_account.liquidation_channels.historical_market.fidelity}</dd></div>
                    </>
                  )}
                </dl>
                {report.modelled_account.schema_version === "replay.training.portfolio.v2" && (
                  <section className="replay-report-liquidations" aria-label={t("replay.integrity.liqAria")}>
                    <h4>{t("replay.integrity.liqHeading")}</h4>
                    <ReplayLiquidationTimeline
                      cases={[
                        ...report.modelled_account.liquidation_recoveries,
                        ...report.modelled_account.liquidations,
                      ]}
                    />
                  </section>
                )}
                {report.account_audit !== null && (
                  <p className="replay-drawer-note">
                    {t("replay.integrity.accountAudit")}<strong>{report.account_audit.status}</strong>
                    {" · "}<code>{report.account_audit.proof_hash}</code>
                  </p>
                )}
              </section>
            )}

            <section className="replay-drawer-section" aria-labelledby="replay-review-title" data-review-read-only={String(review?.read_only ?? false)}>
              <div className="replay-drawer-section-head">
                <h3 id="replay-review-title">{t("replay.integrity.review")}</h3>
                <Button
                  size="sm"
                  variant={review === null ? "primary" : "secondary"}
                  disabled={busy || (review === null && !reviewStartReady)}
                  title={review === null && !reviewStartReady
                    ? t("replay.integrity.pauseFirst")
                    : t("replay.integrity.cursorOnly")}
                  onClick={() => {
                    if (review === null) void integrityRuntime.actions.startReview();
                    else integrityRuntime.actions.closeReview();
                  }}
                >
                  {review === null ? t("replay.integrity.startReview") : t("replay.integrity.exitReview")}
                </Button>
              </div>
              <p className="replay-drawer-note">{t("replay.integrity.reviewHint")}</p>
              {review === null && (
                <form className="replay-drawer-form" onSubmit={(event) => {
                  event.preventDefault();
                  void integrityRuntime.actions.addMarker(markerText).then(() => {
                    setMarkerText("");
                  }).catch(() => undefined);
                }}>
                  <Field label={t("replay.integrity.marker")}>
                    <Input value={markerText} maxLength={500} placeholder={t("replay.integrity.markerPh")} onChange={(event) => setMarkerText(event.target.value)} />
                  </Field>
                  <Button type="submit" disabled={busy || markerText.trim().length === 0}>{t("replay.integrity.record")}</Button>
                </form>
              )}
              {review !== null && (
                <>
                  <div className="replay-review-controls" role="group" aria-label={t("replay.integrity.reviewControls")}>
                    <Button size="sm" disabled={busy} onClick={() => void integrityRuntime.actions.controlReview("PREVIOUS")}>{t("replay.integrity.prev")}</Button>
                    <Button size="sm" disabled={busy} onClick={() => void integrityRuntime.actions.controlReview("NEXT")}>{t("replay.integrity.next")}</Button>
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={busy}
                      onClick={() => void integrityRuntime.actions.controlReview(
                        review.playback_state === "PLAYING" ? "PAUSE" : "PLAY",
                        { playbackRate },
                      )}
                    >{review.playback_state === "PLAYING" ? t("replay.integrity.pause") : t("replay.integrity.play")}</Button>
                    <label className="replay-speed-control">
                      <span>{t("replay.integrity.speed")}</span>
                      <Select size="sm" value={playbackRate} onChange={(event) => setPlaybackRate(event.target.value as typeof playbackRate)}>
                        {(["0.25", "0.5", "1", "2", "4", "8"] as const).map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
                      </Select>
                    </label>
                  </div>
                  <div className="replay-drawer-form">
                    <Field label={t("replay.integrity.event")}>
                      <Select size="sm" value={effectiveSelectedEventId ?? review.selected_event_id} onChange={(event) => setSelectedEventId(event.target.value)}>
                        {review.events.map((event) => (
                          <option key={event.event_id} value={event.event_id}>
                            #{event.timeline_sequence} · {event.public_time.label} · {event.category}/{event.event_type}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <div className="replay-drawer-form-actions">
                      <Button
                        size="sm"
                        disabled={busy || effectiveSelectedEventId === null}
                        onClick={() => effectiveSelectedEventId !== null && void integrityRuntime.actions.controlReview("JUMP", { eventId: effectiveSelectedEventId })}
                      >{t("replay.integrity.jump")}</Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy || effectiveSelectedEventId === null}
                        onClick={() => effectiveSelectedEventId !== null && void integrityRuntime.actions.forkReview(effectiveSelectedEventId)}
                      >{t("replay.integrity.fork")}</Button>
                    </div>
                  </div>
                  <dl className="replay-integrity-facts" aria-label={t("replay.integrity.projection")}>
                    <div><dt>{t("replay.integrity.timeline")}</dt><dd>{t("replay.integrity.timelineRevision", { sequence: review.selected_timeline_sequence, revision: review.cursor_revision })}</dd></div>
                    <div><dt>{t("replay.integrity.viewer")}</dt><dd>{String(review.projection.viewer_state.selected_track_id)} · {String(review.projection.viewer_state.display_interval)}</dd></div>
                    <div><dt>{t("replay.integrity.ordersFills")}</dt><dd>{review.projection.orders.length} / {review.projection.fills.length}</dd></div>
                    <div><dt>{t("replay.integrity.ledgerLiquidations")}</dt><dd>{review.projection.ledger.length} / {review.projection.liquidations.length}</dd></div>
                    <div><dt>{t("replay.integrity.rules")}</dt><dd>{t("replay.integrity.ruleRevisions", { fee: review.projection.rules.fee_policy.revision, leverage: review.projection.rules.leverage_policy.revision, funding: review.projection.rules.funding_policy.revision })}</dd></div>
                    <div><dt>{t("replay.integrity.drawing")}</dt><dd>{t("replay.integrity.drawingRevision", { revision: review.projection.drawing_revision, hash: review.projection.drawing_document_hash ?? t("replay.integrity.empty") })}</dd></div>
                  </dl>
                  <div className="replay-review-proof" data-review-verified={String(review.immutability_proof.verified)}>
                    <Disclosure summary={t("replay.integrity.unchanged")}>
                      <code>{t("replay.integrity.proofOriginal", { hash: review.original_state_hash })}</code>
                      <code>{t("replay.integrity.proofSelected", { hash: review.selected_state_hash })}</code>
                      <code>{t("replay.integrity.proofAccount", { hash: review.immutability_proof.original_account_hash })}</code>
                      <code>{t("replay.integrity.proofLedger", { hash: review.immutability_proof.original_ledger_tail_hash })}</code>
                    </Disclosure>
                  </div>
                  <section className="replay-review-liquidations" aria-label={t("replay.integrity.reviewLiq")}>
                    <h4>{t("replay.integrity.liqHeading")}</h4>
                    <ReplayLiquidationTimeline cases={review.projection.liquidations} />
                  </section>
                  <ul className="replay-drawer-list replay-review-timeline" aria-label={t("replay.integrity.timeline")}>
                    {review.events.map((event) => (
                      <li key={event.event_id}>
                        <button
                          type="button"
                          className="ui-menu-item replay-review-event"
                          aria-current={event.event_id === review.selected_event_id ? "true" : undefined}
                          data-review-event-category={event.category}
                          onClick={() => void integrityRuntime.actions.controlReview("JUMP", { eventId: event.event_id })}
                          disabled={busy}
                        >
                          <span className="ui-menu-label">
                            <strong>#{event.timeline_sequence} {event.event_type}</strong>
                            <span>{event.public_time.label} · {event.category}{event.detail?.text !== undefined ? ` · ${String(event.detail.text)}` : ""}</span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {integrityRuntime.forked !== null && (
                <InlineAlert
                  tone="success"
                  title={t("replay.integrity.forked")}
                  action={<a className="ui-btn ui-btn-sm" href={`/replay.html?run=${encodeURIComponent(integrityRuntime.forked.run.run_id)}`}>{t("replay.integrity.openChild")}</a>}
                >
                  <code>{integrityRuntime.forked.run.state_hash}</code>
                  {" · "}{t("replay.integrity.forkSummary", { tracks: integrityRuntime.forked.tracks.length, sequence: integrityRuntime.forked.parent_timeline_sequence })}
                  {integrityRuntime.forked.account_audit !== null && <> · {t("replay.integrity.exactAuditor", { status: String(integrityRuntime.forked.account_audit.status ?? "--") })}</>}
                </InlineAlert>
              )}
            </section>
          </>
        )}
      </div>
    </section>
  );
}
