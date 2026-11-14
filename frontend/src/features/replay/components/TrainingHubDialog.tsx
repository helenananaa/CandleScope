import { useState, type ReactNode } from "react";
import {
  Badge, Button, Checkbox, ConfirmDialog, Dialog, Disclosure, EmptyState, Field, InlineAlert, Input, SegmentedControl, Select,
} from "../../../components/ui/index.js";
import { t, getDateTimeLocale, type MessageKey } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import UtcReplayStartInput from "./UtcReplayStartInput.js";
import type { TrainingRunDraft } from "../trainingHubModel.js";
import {
  REPLAY_POLICY_MUTATIONS,
  type ReplayPolicyMutation,
} from "../replayIntegrityModel.js";
import type {
  ReplayV2RunState,
  ReplayV2SourceKind,
  TrainingRunCard,
  TrainingRunCompatibility,
} from "../replayV2Types.js";
import type { TrainingHubRuntime } from "../useTrainingHub.js";
import {
  formatTrainingEquity,
  trainingCompatibilityLabel,
  trainingIntegrityLabel,
  trainingRunStateLabel,
  trainingSourceKindLabel,
  trainingTimeDisclosureLabel,
} from "../trainingHubLabels.js";
import ReplayStorageGovernancePanel from "./ReplayStorageGovernancePanel.js";
import { applyTrainingPreset } from "../trainingPresets.js";
import PreparationJobsPanel from "../../data-preparation/PreparationJobsPanel.js";
import PreparationWaiting from "../../data-preparation/PreparationWaiting.js";
import { preparationRequest } from "../../data-preparation/api.js";

export interface TrainingHubDialogProps {
  readonly runtime: TrainingHubRuntime;
  readonly presentation?: "page" | "modal";
  readonly onRequestClose?: () => void;
  readonly launchLabel?: string;
  readonly onPrepareData?: () => void;
}

function patchDraft(
  runtime: TrainingHubRuntime,
  patch: Partial<TrainingRunDraft>,
): void {
  if (runtime.draft === null) return;
  runtime.actions.setDraft({ ...runtime.draft, ...patch });
}

function trainingRunStatusMessage(card: TrainingRunCard): string {
  if (card.state !== "ENDED") return card.status.message;
  return card.resume_action === "UNAVAILABLE"
    ? t("replay.hub.endedUnavailable")
    : t("replay.hub.endedReviewable");
}

function trainingRunPrimaryActionLabel(card: TrainingRunCard): string {
  if (card.state === "AWAITING_MARKET") return t("replay.hub.selectMarket");
  return card.state === "ENDED" ? t("replay.hub.openReview") : t("replay.hub.continue");
}

export interface TrainingRunDeleteConfirmationProps {
  readonly card: TrainingRunCard;
  readonly busy: boolean;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
}

export function TrainingRunDeleteConfirmation({
  card,
  busy,
  onCancel,
  onConfirm,
}: TrainingRunDeleteConfirmationProps) {
  useLocale();
  return (
    <ConfirmDialog
      open
      tone="danger"
      busy={busy}
      title={t("replay.hub.deleteTitle")}
      message={<>{t("replay.hub.deleteDesc")} <strong>{card.name}</strong></>}
      cancelLabel={t("replay.hub.cancel")}
      confirmLabel={t("replay.hub.deleteConfirm")}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

/** A numbered part of the create form: heading, one line of what it sets, then its fields. */
function CreateSection({ id, number, title, hint, children }: {
  readonly id: string;
  readonly number: number;
  readonly title: string;
  readonly hint?: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <section className="training-hub-form-section" id={id} aria-labelledby={`${id}-title`}>
      <h3 className="training-hub-section-title" id={`${id}-title`}><span aria-hidden="true">{number}</span>{title}</h3>
      {hint ? <p className="training-hub-section-hint">{hint}</p> : null}
      <div className="training-hub-section-body">{children}</div>
    </section>
  );
}

/** A one-of choice with the chosen option's description under it. */
function CreateChoice<T extends string>({ label, value, options, onChange, hint, note }: {
  readonly label: string;
  readonly value: T;
  readonly options: readonly { value: T; label: string; disabled?: boolean }[];
  readonly onChange: (value: T) => void;
  readonly hint?: ReactNode;
  readonly note?: ReactNode;
}) {
  return (
    <div className="training-hub-choice">
      <span className="ui-field-label">{label}</span>
      <SegmentedControl fullWidth label={label} value={value} options={options} onChange={onChange} />
      {hint ? <p className="ui-field-hint">{hint}</p> : null}
      {note ? <p className="ui-field-hint">{note}</p> : null}
    </div>
  );
}

type StartChoice = "RANGE" | "MARKET" | "MANUAL";

function TrainingRunCreatePanel({ runtime, onPrepareData, launchLabel }: TrainingHubDialogProps) {
  useLocale();
  const { draft, evaluation } = runtime;
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [presetMode, setPresetMode] = useState<"practice" | "challenge" | "custom">("custom");
  if (!runtime.createOpen) return null;
  if (draft === null || evaluation === null) {
    return (
      <Dialog
        open
        size="sm"
        className="training-hub-create training-hub-create-loading"
        title={t("replay.hub.createTitle")}
        onClose={runtime.actions.closeCreate}
        footer={<Button onClick={runtime.actions.closeCreate}>{t("replay.hub.cancel")}</Button>}
      >
        <EmptyState compact icon={<span className="replay-loading-spinner" />} title={t("replay.hub.createLoading")} />
      </Dialog>
    );
  }
  const busy = runtime.operation === "create"
    || runtime.operation === "plan";
  const validatingCatalog = runtime.operation === "create-context";
  const canLeavePreparation = runtime.automaticPreparationAvailable && runtime.operation === "create";
  const preparationActive = runtime.preparationJob?.state === "RUNNING"
    || runtime.preparationJob?.state === "QUEUED";
  const preparationStatus = runtime.preparationJob?.state === "READY" ? "preparation.ready"
    : runtime.preparationJob?.state === "CANCELLED" ? "preparation.cancelled"
    : preparationActive ? "preparation.title" : "preparation.needsAttention";
  const busyLabel = runtime.operation === "create"
    ? t("replay.hub.creating")
    : runtime.operation === "create-context"
      ? t("replay.hub.validatingCatalog")
      : t("replay.hub.validatingData");
  const toggleMutation = (mutation: ReplayPolicyMutation, checked: boolean) => {
    const next = checked
      ? [...draft.allowedMutations, mutation]
      : draft.allowedMutations.filter((item) => item !== mutation);
    patchDraft(runtime, { allowedMutations: [...new Set(next)] });
  };
  const aggEnabled = Boolean(runtime.capabilities?.sources.agg_trade.enabled);
  const aggHint = t(
    !aggEnabled && runtime.capabilities?.sources.agg_trade.reason === "OFFICIAL_CATALOG_SYNCING"
      ? "replay.hub.catalogSyncing"
      : runtime.capabilities?.sources.agg_trade.fidelity === "USER_MARKET_TRADE_COVERAGE"
        ? "local.localOnly" : "replay.hub.aggHint",
  );
  const aggDisabled = busy || (!aggEnabled && !runtime.automaticTradePreparationAvailable);
  const marketRandomDisabled = busy || !runtime.automaticPreparationAvailable || draft.sourceKind !== "BAR";
  const startChoice: StartChoice = draft.startMode === "MANUAL" ? "MANUAL"
    : draft.randomScope === "MARKET" ? "MARKET" : "RANGE";
  const chooseStart = (choice: StartChoice) => {
    if (choice === "RANGE") patchDraft(runtime, { startMode: "RANDOM", randomScope: "RANGE", requestedStartMs: null });
    else if (choice === "MARKET") patchDraft(runtime, { startMode: "RANDOM", randomScope: "MARKET",
      requestedStartMs: null, randomRangeStartMs: null, randomRangeEndMs: null });
    else patchDraft(runtime, { startMode: "MANUAL", randomRangeStartMs: null, randomRangeEndMs: null });
  };
  const chooseIntegrity = (integrityMode: TrainingRunDraft["integrityMode"]) => patchDraft(runtime, {
    integrityMode,
    fundingMode: integrityMode === "SANDBOX" || draft.fundingMode !== "SANDBOX_FIXED"
      ? draft.fundingMode
      : "OFF",
    allowedMutations: integrityMode === "CHALLENGE"
      ? []
      : integrityMode === "SANDBOX"
        ? REPLAY_POLICY_MUTATIONS
        : ["deposit", "withdraw"],
  });
  const intro = t(runtime.automaticPreparationAvailable ? "preparation.replayIntro" : "replay.hub.createIntro");
  return (
    <Dialog
      open
      size="lg"
      className="training-hub-create"
      title={t("replay.hub.createTitle")}
      description={launchLabel ? <>{intro}<br />{launchLabel}</> : intro}
      dismissible={!busy || Boolean(canLeavePreparation)}
      onClose={runtime.actions.closeCreate}
      footer={<>
        <div className="training-hub-create-status">
          {runtime.preparationJob && <div role="status" aria-live="polite">
            <p>{t(preparationStatus)} · {runtime.preparationJob.completed}/{runtime.preparationJob.total}</p>
            <PreparationWaiting job={runtime.preparationJob} />
            {preparationActive && <p>{t("preparation.background")}</p>}
            {busy && preparationActive && <Button size="sm" disabled={runtime.preparationJob.cancel_requested || runtime.preparationJob.stage === "STARTING"}
              onClick={() => void preparationRequest(`/${runtime.preparationJob!.id}/cancel`, { method: "POST" }).catch(() => undefined)}>{t("preparation.cancel")}</Button>}
          </div>}
          {!runtime.automaticPreparationAvailable && <p>{t("replay.hub.submitNote")}</p>}
        </div>
        <Button onClick={runtime.actions.closeCreate} disabled={busy && !canLeavePreparation}>
          {canLeavePreparation ? t("replay.hub.close") : t("replay.hub.cancel")}
        </Button>
        <Button
          variant="primary"
          disabled={!evaluation.canSubmit || busy || validatingCatalog}
          onClick={() => void runtime.actions.createRun(draft)}
        >
          {busy || validatingCatalog ? busyLabel : t("replay.hub.submit")}
        </Button>
      </>}
    >
      <div className="training-hub-create-body">
        <div className="training-hub-create-main">
          {onPrepareData && !runtime.automaticPreparationAvailable && draft.sourceKind === "BAR" && runtime.catalog !== null
            && runtime.catalog.entries.every((entry) => entry.eligible_ranges.length === 0) && (
            <InlineAlert tone="warning" title={t("replay.hub.prepareDataTitle")}
              action={<Button size="sm" variant="primary" disabled={busy} onClick={onPrepareData}>{t("replay.hub.prepareDataAction")}</Button>}>
              {t("replay.hub.prepareDataHint")}
            </InlineAlert>
          )}
          <section className="training-presets" aria-label={t("ux.customPreset")}>
            <SegmentedControl
              fullWidth
              label={t("ux.customPreset")}
              value={presetMode}
              options={(["practice", "challenge", "custom"] as const).map((mode) => ({
                value: mode,
                disabled: busy,
                label: t(mode === "practice" ? "ux.practicePreset" : mode === "challenge" ? "ux.challengePreset" : "ux.customPreset"),
              }))}
              onChange={(mode) => {
                setPresetMode(mode); setAdvancedOpen(mode === "custom");
                if (mode !== "custom") runtime.actions.setDraft(applyTrainingPreset(draft, mode, runtime.catalog));
              }}
            />
            <p className="ui-field-hint">{t("ux.presetHint")}</p>
          </section>

          {/* With automatic preparation the dialog's description already says how the start works. */}
          <CreateSection id="training-hub-create-start" number={1} title={t("replay.hub.sectionStart")}
            hint={runtime.automaticPreparationAvailable ? undefined : t("replay.hub.startHint")}>
            {runtime.automaticPreparationAvailable && <div className="training-hub-field-grid training-hub-field-grid-three">
              <Field label={t("backtest.exchange")}>
                <Input disabled={busy} value={draft.exchange} onChange={(event) => patchDraft(runtime, { exchange: event.target.value.trim().toLowerCase() })} />
              </Field>
              <Field label={t("backtest.marketType")}>
                <Select disabled={busy} value={draft.marketType} onChange={(event) => patchDraft(runtime, { marketType: event.target.value })}>
                  <option value="spot">{t("market.spot")}</option><option value="futures">{t("market.futures")}</option>
                </Select>
              </Field>
              <Field label={t("replay.hub.symbol")}>
                <Input disabled={busy} value={draft.symbol} onChange={(event) => patchDraft(runtime, { symbol: event.target.value.trim().toUpperCase() })} />
              </Field>
              {(!runtime.preparationJob || preparationActive) && <p className="ui-field-hint training-hub-field-wide">{t("preparation.background")}</p>}
            </div>}
            <Field label={t("replay.hub.archiveName")}>
              <Input value={draft.name} maxLength={80} onChange={(event) => patchDraft(runtime, { name: event.target.value })} />
            </Field>
            <CreateChoice<ReplayV2SourceKind>
              label={t("replay.hub.sourceKind")}
              value={draft.sourceKind}
              options={[
                { value: "BAR", label: t("replay.source.bar"), disabled: busy },
                { value: "AGG_TRADE", label: t("replay.source.agg"), disabled: aggDisabled },
              ]}
              onChange={(sourceKind) => patchDraft(runtime, { sourceKind })}
              hint={draft.sourceKind === "BAR" ? t("replay.hub.barHint") : aggHint}
              note={draft.sourceKind === "BAR" && aggDisabled && !busy ? aggHint : null}
            />
            <CreateChoice<StartChoice>
              label={t("replay.hub.startMode")}
              value={startChoice}
              options={[
                { value: "RANGE", label: t("replay.hub.randomWindow"), disabled: busy },
                { value: "MARKET", label: t("replay.hub.marketRandom"), disabled: marketRandomDisabled },
                { value: "MANUAL", label: t("replay.hub.manualUtc"), disabled: busy },
              ]}
              onChange={chooseStart}
              hint={t(startChoice === "MANUAL" ? "replay.hub.manualHint" : startChoice === "MARKET" ? "replay.hub.marketRandomHint" : "replay.hub.randomHint")}
              note={marketRandomDisabled && !busy && startChoice !== "MARKET" ? t("replay.err.marketRandomUnsupported") : null}
            />
            {draft.startMode === "MANUAL" ? (
              <>
                <Field label={t("replay.hub.startUtc")}>
                  <UtcReplayStartInput
                    data-training-field="requested-start-utc"
                    disabled={busy}
                    value={draft.requestedStartMs}
                    onChange={(value) => patchDraft(runtime, { requestedStartMs: value })}
                  />
                </Field>
                <InlineAlert tone="warning">{t("replay.hub.manualWarning")}</InlineAlert>
              </>
            ) : draft.randomScope === "MARKET" ? (
              <p className="training-hub-field-note" role="note">{t("replay.hub.marketRandomRange")}</p>
            ) : (
              <div className="training-hub-field-grid">
                <Field label={t("replay.hub.randomStart")}>
                  <UtcReplayStartInput
                    disabled={busy}
                    value={draft.randomRangeStartMs}
                    onChange={(value) => patchDraft(runtime, { randomRangeStartMs: value })}
                  />
                </Field>
                <Field label={t("replay.hub.randomEnd")}>
                  <UtcReplayStartInput
                    disabled={busy}
                    value={draft.randomRangeEndMs}
                    onChange={(value) => patchDraft(runtime, { randomRangeEndMs: value })}
                  />
                </Field>
              </div>
            )}
            <p className="training-hub-field-note" role="note">{t("replay.hub.t0Note")}</p>
            {runtime.catalog !== null && (
              <p className="training-hub-field-note" data-tone="success" role="status">
                {t("replay.hub.catalogReady", { count: runtime.catalog.entries.length })}
              </p>
            )}
          </CreateSection>

          <CreateSection id="training-hub-create-rules" number={2} title={t("replay.hub.sectionRules")} hint={t("replay.hub.rulesHint")}>
            <CreateChoice<TrainingRunDraft["integrityMode"]>
              label={t("replay.hub.integrityMode")}
              value={draft.integrityMode}
              options={[
                { value: "CHALLENGE", label: t("replay.hub.challenge"), disabled: busy },
                { value: "PRACTICE", label: t("replay.hub.practice"), disabled: busy },
                { value: "SANDBOX", label: t("replay.hub.sandbox"), disabled: busy },
              ]}
              onChange={chooseIntegrity}
              hint={t(draft.integrityMode === "CHALLENGE" ? "replay.hub.challengeHint" : draft.integrityMode === "PRACTICE" ? "replay.hub.practiceHint" : "replay.hub.sandboxHint")}
            />
            <div className="training-hub-field-grid">
              <Field label={t("replay.hub.timeDisclosure")}>
                <Select
                  data-training-field="time-disclosure-policy"
                  value={draft.timeDisclosurePolicy}
                  onChange={(event) => patchDraft(runtime, {
                    timeDisclosurePolicy: event.target.value as TrainingRunDraft["timeDisclosurePolicy"],
                  })}
                >
                  <option value="NONE">{t("replay.hub.disclosureNone")}</option>
                  <option value="HIDE_YEAR">{t("replay.hub.disclosureYear")}</option>
                  <option value="HIDE_MONTH">{t("replay.hub.disclosureMonth")}</option>
                  <option value="HIDE_DAY">{t("replay.hub.disclosureDay")}</option>
                  <option value="HIDE_HOUR">{t("replay.hub.disclosureHour")}</option>
                  <option value="HIDE_MINUTE">{t("replay.hub.disclosureMinute")}</option>
                  <option value="HIDE_ALL">{t("replay.hub.disclosureAll")}</option>
                </Select>
              </Field>
            </div>
            <fieldset className="training-hub-mutation-policy" disabled={draft.integrityMode !== "PRACTICE" || busy}>
              <legend className="ui-field-label">{t("replay.hub.practiceWhitelist")}</legend>
              <div className="training-hub-mutation-list">
                {REPLAY_POLICY_MUTATIONS.map((mutation) => (
                  <Checkbox
                    key={mutation}
                    label={mutation}
                    checked={draft.allowedMutations.includes(mutation)}
                    onChange={(event) => toggleMutation(mutation, event.target.checked)}
                  />
                ))}
              </div>
              <p className="ui-field-hint">{t("replay.hub.practiceNote")}</p>
            </fieldset>
            <div className="training-hub-field-grid training-hub-field-grid-three">
              <Field label={t("replay.hub.initialEquity")}>
                <Input inputMode="decimal" value={draft.initialEquity} onChange={(event) => patchDraft(runtime, { initialEquity: event.target.value })} />
              </Field>
              <Field label={t("replay.hub.maxLeverage")}>
                <Input inputMode="decimal" value={draft.maxLeverage} onChange={(event) => patchDraft(runtime, { maxLeverage: event.target.value })} />
              </Field>
              <Field label={t("replay.hub.marginMode")}>
                <Select value={draft.marginMode} onChange={(event) => patchDraft(runtime, { marginMode: event.target.value as TrainingRunDraft["marginMode"] })}>
                  <option value="CROSS">{t("replay.hub.cross")}</option>
                  <option value="ISOLATED">{t("replay.hub.isolated")}</option>
                </Select>
              </Field>
            </div>
            <Field label={t("replay.hub.positionMode")} hint={t("replay.hub.hedgeNote")}>
              <Select
                value={draft.positionMode}
                onChange={(event) => {
                  const positionMode = event.target.value as TrainingRunDraft["positionMode"];
                  patchDraft(runtime, {
                    positionMode,
                    ...(positionMode === "HEDGE" ? {
                      accountDataMode: "DETERMINISTIC_SIMULATION",
                      fundingMode: "OFF",
                    } : draft.accountDataMode === "DETERMINISTIC_SIMULATION" ? {
                      accountDataMode: "APPROX_PROXY",
                      fundingMode: draft.fundingMode === "HISTORICAL_EXACT" ? "OFF" : draft.fundingMode,
                    } : {}),
                  });
                }}
              >
                <option value="ONE_WAY">{t("replay.hub.oneWay")}</option>
                <option value="HEDGE">{t("replay.hub.hedge")}</option>
              </Select>
            </Field>
            {!runtime.automaticPreparationAvailable && (
              <InlineAlert tone="info" title={t("replay.hub.marketInRun")}>
                <p>{t("replay.hub.marketInRunDesc")}</p>
                <p>{t("replay.hub.hedgeBind")}</p>
              </InlineAlert>
            )}
          </CreateSection>

          <Disclosure
            id="training-hub-create-advanced"
            className="training-hub-advanced"
            open={advancedOpen}
            onToggle={setAdvancedOpen}
            summary={t("replay.hub.advancedSummary")}
          >
            <CreateSection id="training-hub-create-history" number={3} title={t("replay.hub.historyWindow")} hint={t("replay.hub.historyHint")}>
              <div className="training-hub-field-grid training-hub-field-grid-three">
                <Field label={t("replay.hub.warmupBars")} hint={t("replay.hub.warmupHint")}>
                  <Input
                    type="number"
                    min={1}
                    value={draft.indicatorWarmupBars}
                    onChange={(event) => patchDraft(runtime, { indicatorWarmupBars: Number(event.target.value) })}
                  />
                </Field>
                <Field label={t("replay.hub.forwardCache")}>
                  <Input
                    data-training-field="forward-cache-ms"
                    type="number"
                    min={1}
                    value={draft.forwardCacheMs}
                    onChange={(event) => patchDraft(runtime, { forwardCacheMs: Number(event.target.value) })}
                  />
                </Field>
                <Field label={t("replay.hub.visibleHistory")}>
                  <Select
                    value={draft.visibleHistoryMode}
                    onChange={(event) => {
                      const mode = event.target.value as TrainingRunDraft["visibleHistoryMode"];
                      patchDraft(runtime, {
                        visibleHistoryMode: mode,
                        visibleHistoryLookbackMs: mode === "ALL_AVAILABLE"
                          ? null
                          : draft.visibleHistoryLookbackMs ?? draft.indicatorWarmupBars * 60 * 1_000,
                      });
                    }}
                  >
                    <option value="ALL_AVAILABLE">{t("replay.hub.allAvailable")}</option>
                    <option value="DURATION">{t("replay.hub.fixedDuration")}</option>
                  </Select>
                </Field>
              </div>
              {draft.visibleHistoryMode === "ALL_AVAILABLE" ? (
                <p className="training-hub-field-note">{t("replay.hub.pageLikeLive")}</p>
              ) : (
                <div className="training-hub-field-grid">
                  <Field label={t("replay.hub.visibleMs")} hint={t("replay.hub.visibleMsHint")}>
                    <Input
                      type="number"
                      min={60_000}
                      step={60_000}
                      value={draft.visibleHistoryLookbackMs ?? ""}
                      onChange={(event) => patchDraft(runtime, { visibleHistoryLookbackMs: Number(event.target.value) })}
                    />
                  </Field>
                </div>
              )}
            </CreateSection>

            <CreateSection id="training-hub-create-account" number={4} title={t("replay.hub.accountExec")} hint={t("replay.hub.accountExecHint")}>
              <div className="training-hub-field-grid">
                <Field label={t("replay.hub.accountData")} hint={t("replay.hub.hedgeAccountHint")}>
                  <Select
                    value={draft.accountDataMode}
                    onChange={(event) => {
                      const accountDataMode = event.target.value as TrainingRunDraft["accountDataMode"];
                      patchDraft(runtime, {
                        accountDataMode,
                        fundingMode: accountDataMode === "HISTORICAL_EXACT"
                          ? draft.fundingMode === "SANDBOX_FIXED" ? "OFF" : draft.fundingMode
                          : draft.fundingMode === "HISTORICAL_EXACT" ? "OFF" : draft.fundingMode,
                      });
                    }}
                  >
                    {draft.positionMode === "HEDGE" ? (
                      <option value="DETERMINISTIC_SIMULATION">{t("replay.hub.accountData.deterministicSimulation")}</option>
                    ) : (
                      <>
                        <option value="APPROX_PROXY">{t("replay.hub.accountData.approxProxy")}</option>
                        <option value="HISTORICAL_EXACT">{t("replay.hub.accountData.historicalExact")}</option>
                      </>
                    )}
                  </Select>
                </Field>
                <Field label={t("replay.hub.fundingMode")}>
                  <Select value={draft.fundingMode} onChange={(event) => patchDraft(runtime, { fundingMode: event.target.value as TrainingRunDraft["fundingMode"] })}>
                    <option value="OFF">{t("replay.hub.modeOff")}</option>
                    {draft.integrityMode === "SANDBOX" && <option value="SANDBOX_FIXED">{t("replay.hub.fundingMode.sandboxFixed")}</option>}
                    {(draft.accountDataMode === "HISTORICAL_EXACT" || draft.accountDataMode === "DETERMINISTIC_SIMULATION") && (
                      <option value="HISTORICAL_EXACT">{t("replay.hub.fundingMode.historicalExact")}</option>
                    )}
                  </Select>
                </Field>
                <Field label={t("replay.hub.bookMode")} hint={t("replay.hub.bookHint")}>
                  <Select value={draft.bookMode} onChange={(event) => patchDraft(runtime, { bookMode: event.target.value as TrainingRunDraft["bookMode"] })}>
                    <option value="OFF">{t("replay.hub.bookMode.off")}</option>
                    <option value="BOOK_ASSISTED_REQUIRED">{t("replay.hub.bookMode.assistedRequired")}</option>
                  </Select>
                </Field>
                {draft.fundingMode === "SANDBOX_FIXED" && (
                  <>
                    <Field label={t("replay.hub.fixedFunding")}>
                      <Input inputMode="decimal" value={draft.fixedFundingRate} onChange={(event) => patchDraft(runtime, { fixedFundingRate: event.target.value })} />
                    </Field>
                    <Field label={t("replay.hub.fundingInterval")}>
                      <Input type="number" min={60_000} max={30 * 86_400_000} value={draft.fundingIntervalMs} onChange={(event) => patchDraft(runtime, { fundingIntervalMs: Number(event.target.value) })} />
                    </Field>
                  </>
                )}
                <div className="ui-field">
                  <span className="ui-field-label">{t("replay.hub.makerTakerBps")}</span>
                  <span className="training-hub-inline-inputs">
                    <Input inputMode="decimal" value={draft.makerFeeBps} aria-label={t("replay.integrity.makerBps")} onChange={(event) => patchDraft(runtime, { makerFeeBps: event.target.value })} />
                    <Input inputMode="decimal" value={draft.takerFeeBps} aria-label={t("replay.integrity.takerBps")} onChange={(event) => patchDraft(runtime, { takerFeeBps: event.target.value })} />
                  </span>
                </div>
                <Field label={t("replay.hub.slippage")}>
                  <Input inputMode="decimal" value={draft.marketSlippageBps} onChange={(event) => patchDraft(runtime, { marketSlippageBps: event.target.value })} />
                </Field>
              </div>
            </CreateSection>
          </Disclosure>
        </div>

        <aside className="training-hub-create-side">
          <section className="training-hub-summary-card">
            <h3>{t("replay.hub.summary")}</h3>
            <strong>{draft.name || t("replay.hub.unnamed")}</strong>
            <dl>
              <div><dt>{t("replay.hub.sourceKind")}</dt><dd>{trainingSourceKindLabel(draft.sourceKind)}</dd></div>
              <div><dt>{t("replay.hub.start")}</dt><dd>{draft.startMode === "RANDOM" ? t(draft.randomScope === "MARKET" ? "replay.hub.marketRandom" : "replay.hub.randomStartMode") : t("replay.hub.manualStartMode")}</dd></div>
              <div><dt>{t("replay.hub.integrity")}</dt><dd>{trainingIntegrityLabel(draft.integrityMode)}</dd></div>
              <div><dt>{t("replay.hub.timeDisclosure")}</dt><dd>{trainingTimeDisclosureLabel(draft.timeDisclosurePolicy)}</dd></div>
              <div><dt>{t("replay.hub.equityLeverage")}</dt><dd>{draft.initialEquity} · {draft.maxLeverage}×</dd></div>
              <div><dt>{t("replay.hub.posMargin")}</dt><dd>{draft.positionMode === "HEDGE" ? t("replay.hub.hedgeShort") : t("replay.hub.oneWayShort")} · {draft.marginMode === "ISOLATED" ? t("replay.hub.isolatedShort") : t("replay.hub.crossShort")}</dd></div>
              <div><dt>{t("replay.hub.symbol")}</dt><dd>{runtime.automaticPreparationAvailable ? `${draft.exchange} · ${draft.symbol}` : t("replay.hub.pickAfterRun")}</dd></div>
            </dl>
          </section>
          <section className="training-hub-summary-card">
            <h3>{t("replay.hub.boundary")}</h3>
            <dl className="training-hub-boundary">
              <div><dt>{t("replay.hub.accountHistory")}</dt><dd>{evaluation.unsupported.account_history}</dd></div>
              <div><dt>{t("replay.hub.funding")}</dt><dd>{evaluation.unsupported.funding}</dd></div>
              <div><dt>{t("replay.hub.book")}</dt><dd>{evaluation.unsupported.historical_l2}</dd></div>
              <div><dt>{t("replay.hub.ruleChanges")}</dt><dd>{evaluation.unsupported.rule_changes}</dd></div>
              <div><dt>{t("replay.hub.isolatedMargin")}</dt><dd>{evaluation.unsupported.isolated_margin}</dd></div>
            </dl>
          </section>
          {evaluation.errors.length > 0 && (
            <InlineAlert tone="danger">
              <ul className="training-hub-error-list">{evaluation.errors.map((message) => <li key={message}>{message}</li>)}</ul>
            </InlineAlert>
          )}
        </aside>
      </div>
    </Dialog>
  );
}

const STATE_FILTERS = [
  ["all", null, "replay.hub.all"],
  ["AWAITING_MARKET", "AWAITING_MARKET", "replay.state.awaiting"],
  ["PAUSED", "PAUSED", "replay.hub.pausedChip"],
  ["PLAYING", "PLAYING", "replay.state.playing"],
  ["ENDED", "ENDED", "replay.state.ended"],
] as const satisfies readonly (readonly [string, ReplayV2RunState | null, MessageKey])[];
type StateFilterKey = (typeof STATE_FILTERS)[number][0];

function runStateTone(state: ReplayV2RunState): "neutral" | "accent" | "success" | "warning" | "danger" {
  switch (state) {
    case "PLAYING":
    case "ADVANCING":
      return "success";
    case "PAUSED":
    case "AWAITING_MARKET":
      return "warning";
    case "ERROR":
      return "danger";
    default:
      return "neutral";
  }
}

function TrainingRunRow({ card, busy, onContinue, onDelete }: {
  readonly card: TrainingRunCard;
  readonly busy: boolean;
  readonly onContinue: () => void;
  readonly onDelete: () => void;
}) {
  const noSymbol = card.state === "AWAITING_MARKET" || card.last_symbol === null;
  const updated = new Date(card.updated_at_ms);
  const details = [
    trainingIntegrityLabel(card.integrity_mode),
    `${card.last_symbol ?? t("replay.hub.unselected")}${card.subscribed_track_count > 0 ? t("replay.hub.activeTracks", { count: card.subscribed_track_count }) : ""}`,
    trainingSourceKindLabel(card.source_kind),
    ...(card.time_disclosure_policy === "NONE" ? [] : [trainingTimeDisclosureLabel(card.time_disclosure_policy)]),
  ];
  return (
    <article className="training-hub-card" data-state={card.state}>
      <div className="training-hub-card-main">
        <div className="training-hub-card-title">
          <h2>{card.name}</h2>
          <Badge tone={runStateTone(card.state)}>{trainingRunStateLabel(card.state)}</Badge>
          {card.compatibility !== "READY" && <Badge tone="danger">{trainingCompatibilityLabel(card.compatibility)}</Badge>}
        </div>
        <p className="training-hub-card-line">{details.join(" · ")}</p>
        <p className="training-hub-card-line training-hub-card-status">
          {trainingRunStatusMessage(card)} · {t("replay.hub.updated")} <time dateTime={updated.toISOString()}>{updated.toLocaleString(getDateTimeLocale())}</time>
        </p>
      </div>
      <div className="training-hub-card-equity">
        {noSymbol ? (
          <span>{t("replay.hub.noSymbol")}</span>
        ) : (
          <>
            <span>{t("replay.hub.equity")}</span>
            <strong title={card.equity_status === "CURRENT" ? card.equity ?? undefined : undefined}>
              {card.equity_status === "CURRENT" && card.equity !== null
                ? formatTrainingEquity(card.equity, /^(USD|USDT|USDC)$/i.test(card.settlement_asset) ? 2 : 8)
                : card.equity_status}
              {card.equity_status === "CURRENT" && <small>{card.settlement_asset}</small>}
            </strong>
          </>
        )}
      </div>
      <div className="training-hub-card-actions">
        <Button size="sm" variant="primary" disabled={busy || card.resume_action === "UNAVAILABLE"} onClick={onContinue}>
          {trainingRunPrimaryActionLabel(card)}
        </Button>
        <Button size="sm" variant="ghost" className="training-hub-delete-action" disabled={busy} onClick={onDelete}>
          {t("replay.hub.delete")}
        </Button>
      </div>
    </article>
  );
}

export default function TrainingHubDialog({
  runtime,
  presentation = "page",
  onRequestClose,
  launchLabel,
  onPrepareData,
}: TrainingHubDialogProps) {
  useLocale();
  const busy = runtime.operation !== null;
  const modal = presentation === "modal";
  const [deleteCandidate, setDeleteCandidate] = useState<TrainingRunCard | null>(
    null,
  );
  const recent = [...runtime.items].filter((card) => card.resume_action !== "UNAVAILABLE" && card.state !== "ENDED")
    .sort((a, b) => b.updated_at_ms - a.updated_at_ms)[0];
  const stateFilter: StateFilterKey = STATE_FILTERS.find(([, state]) => state === runtime.filters.state)?.[0] ?? "all";
  const filtered = runtime.filters.state !== null || runtime.filters.sourceKind !== null || runtime.filters.compatibility !== null;
  return (
    <main
      className={`training-hub-page ${modal ? "training-hub-modal-surface" : ""}`}
      role="dialog"
      aria-modal={modal}
      aria-labelledby="training-hub-title"
      data-training-hub-phase={runtime.phase}
      data-training-hub-presentation={presentation}
    >
      <section className="training-hub-shell training-hub-runs">
        <header className="training-hub-heading">
          <div>
            <h1 id="training-hub-title">{t("replay.hub.title")}</h1>
            <p>{t("replay.hub.welcome")}</p>
          </div>
          <div className="training-hub-heading-actions">
            <Button onClick={() => void runtime.actions.openStorage()} disabled={busy}>
              {t("replay.hub.storage")}
            </Button>
            {modal ? (
              <Button onClick={onRequestClose}>{t("replay.hub.close")}</Button>
            ) : (
              <a className="ui-btn ui-btn-ghost" href="/" target="_blank" rel="noopener noreferrer">{t("replay.hub.live")}</a>
            )}
            <Button onClick={runtime.actions.refresh} disabled={busy}>{t("replay.hub.refresh")}</Button>
            <Button variant="primary" onClick={() => void runtime.actions.openCreate()} disabled={busy}>
              {t("replay.hub.new")}
            </Button>
          </div>
        </header>

        <ReplayStorageGovernancePanel runtime={runtime} />
        {recent && <section className="training-hub-resume" aria-labelledby="training-hub-resume-title">
          <div>
            <span>{t("replay.hub.recent")}</span>
            <h2 id="training-hub-resume-title">{recent.name}</h2>
            <p>{recent.last_symbol ?? t("replay.hub.unselected")} · {trainingRunStateLabel(recent.state)}</p>
          </div>
          <Button variant="primary" disabled={busy}
            onClick={() => runtime.actions.continueRun(recent)}>{trainingRunPrimaryActionLabel(recent)}</Button>
        </section>}
        <PreparationJobsPanel summary onReady={runtime.actions.refresh} />

        {/* With no runs and no filter applied, filters have nothing to act on */}
        {(runtime.items.length > 0 || runtime.phase === "LOADING" || filtered) && (
        <div className="training-hub-toolbar">
          <SegmentedControl
            size="sm"
            label={t("replay.hub.filterStatus")}
            value={stateFilter}
            options={STATE_FILTERS.map(([key, , labelKey]) => ({ value: key, label: t(labelKey) }))}
            onChange={(key) => runtime.actions.setFilters({
              ...runtime.filters,
              state: STATE_FILTERS.find(([value]) => value === key)?.[1] ?? null,
            })}
          />
          <label className="training-hub-toolbar-field">
            <span>{t("replay.hub.filterSource")}</span>
            <Select
              size="sm"
              value={runtime.filters.sourceKind ?? ""}
              onChange={(event) => runtime.actions.setFilters({
                ...runtime.filters,
                sourceKind: event.target.value === "" ? null : event.target.value as ReplayV2SourceKind,
              })}
            >
              <option value="">{t("replay.hub.all")}</option>
              <option value="BAR">{t("replay.source.bar")}</option>
              <option value="AGG_TRADE">{t("replay.source.agg")}</option>
            </Select>
          </label>
          <label className="training-hub-toolbar-field">
            <span>{t("replay.hub.filterCompat")}</span>
            <Select
              size="sm"
              value={runtime.filters.compatibility ?? ""}
              onChange={(event) => runtime.actions.setFilters({
                ...runtime.filters,
                compatibility: event.target.value === ""
                  ? null
                  : event.target.value as TrainingRunCompatibility,
              })}
            >
              <option value="">{t("replay.hub.all")}</option>
              <option value="READY">{t("replay.compat.ready")}</option>
              <option value="UNAVAILABLE">{t("replay.compat.blocked")}</option>
            </Select>
          </label>
          <span className="training-hub-toolbar-meta">
            {t("replay.hub.loaded", { count: runtime.items.length })}{runtime.nextCursor !== null ? t("replay.hub.hasNext") : t("replay.hub.endOfList")}
          </span>
        </div>
        )}

        {runtime.error !== null && (
          <InlineAlert
            tone="danger"
            title={runtime.error.message}
            action={runtime.error.code === "CATALOG_EPOCH_MISMATCH"
              ? <Button size="sm" onClick={() => void runtime.actions.openCreate()}>{t("replay.hub.revalidate")}</Button>
              : undefined}
          >
            <code>{runtime.error.code}</code>
          </InlineAlert>
        )}

        {runtime.phase === "LOADING" && runtime.items.length === 0 ? (
          <EmptyState icon={<span className="replay-loading-spinner" />} title={t("replay.hub.loading")} />
        ) : runtime.items.length === 0 && filtered ? (
          <EmptyState
            title={t("replay.hub.filteredEmpty")}
            action={<Button onClick={() => runtime.actions.setFilters({ state: null, sourceKind: null, compatibility: null })}>{t("replay.hub.clearFilters")}</Button>}
          />
        ) : runtime.items.length === 0 ? (
          <EmptyState
            title={t("replay.hub.emptyTitle")}
            description={t("replay.hub.emptyHint")}
            action={<Button variant="primary" onClick={() => void runtime.actions.openCreate()} disabled={busy}>{t("replay.hub.emptyCreate")}</Button>}
          />
        ) : (
          <div className="training-hub-list" aria-label={t("replay.hub.list")}>
            {runtime.items.map((card) => (
              <TrainingRunRow
                key={card.run_id}
                card={card}
                busy={busy}
                onContinue={() => runtime.actions.continueRun(card)}
                onDelete={() => setDeleteCandidate(card)}
              />
            ))}
          </div>
        )}
        {runtime.nextCursor !== null && (
          <div className="training-hub-load-more">
            <Button disabled={busy} onClick={runtime.actions.loadNext}>{t("replay.hub.loadMore")}</Button>
          </div>
        )}
        <TrainingRunCreatePanel key={runtime.createOpen ? "open" : "closed"} runtime={runtime} {...(launchLabel ? { launchLabel } : {})} {...(onPrepareData ? { onPrepareData } : {})} />
      </section>
      {deleteCandidate !== null && (
        <TrainingRunDeleteConfirmation
          card={deleteCandidate}
          busy={busy}
          onCancel={() => setDeleteCandidate(null)}
          onConfirm={() => {
            const runId = deleteCandidate.run_id;
            setDeleteCandidate(null);
            void runtime.actions.deleteRun(runId);
          }}
        />
      )}
    </main>
  );
}
