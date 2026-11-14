import { describeError } from "../../../i18n/serverErrors.js";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Dialog, Disclosure, Field, InlineAlert, Input, Select } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import {
  formatReplayPublicTime,
  replayEffectiveTrainingState,
  replayOwnsController,
} from "../replayUiModel.js";
import type {
  ReplayV2AdvanceBasis,
  ReplayV2Json,
} from "../replayV2Types.js";
import type { ReplayRuntime } from "../useReplayRuntime.js";
import type { ReplayPhase3ControlType, ReplayViewerRuntime } from "../useReplayViewerRuntime.js";
import { replayAdvanceIsCancelable } from "../useReplayViewerRuntime.js";
import {
  boundedReplayAdvanceAmount,
  SOURCE_EVENT_MAX_MANUAL_COUNT,
} from "../replayAdvanceLimits.js";
import { parseIntervalSeconds } from "../../../utils/intervals.js";
import { replayDisplayIntervalOptions } from "../replayWorkspaceSelection.js";

const PLAYBACK_RATES = [1, 2, 5, 10, 30, 60, 120, 600, 1_000, 10_000] as const;

function basisLabel(basis: ReplayV2AdvanceBasis): string {
  switch (basis) {
    case "DISPLAY_BAR":
      return t("replay.control.displayBar");
    case "BASE_BAR":
      return t("replay.control.baseBar");
    case "SOURCE_EVENT":
      return t("replay.control.sourceEvent");
    case "VIRTUAL_TIME":
      return t("replay.control.virtualTime");
  }
}

function fastForwardPlan(value: ReplayV2Json | undefined): {
  readonly mode: string;
  readonly explanation: string;
  readonly reasons: readonly string[];
  readonly equivalence: string;
  readonly summaryStatus: string | null;
} | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const plan = value as Readonly<Record<string, ReplayV2Json>>;
  const mode = typeof plan.plan === "string"
    ? plan.plan
    : typeof plan.mode === "string" ? plan.mode : null;
  if (mode === null) return null;
  const explanation = typeof plan.explanation === "string" ? plan.explanation : "";
  const reasons = Array.isArray(plan.reason_codes)
    ? plan.reason_codes.filter((reason): reason is string => typeof reason === "string")
    : [];
  const equivalenceValue = plan.equivalence;
  const equivalenceObject = equivalenceValue !== null
    && typeof equivalenceValue === "object"
    && !Array.isArray(equivalenceValue)
    ? equivalenceValue as Readonly<Record<string, ReplayV2Json>>
    : null;
  const equivalence = typeof equivalenceObject?.status === "string"
    ? equivalenceObject.status
    : "UNKNOWN";
  const summaryValue = plan.period_summary;
  const summaryObject = summaryValue !== null
    && typeof summaryValue === "object"
    && !Array.isArray(summaryValue)
    ? summaryValue as Readonly<Record<string, ReplayV2Json>>
    : null;
  const summaryStatus = typeof summaryObject?.status === "string"
    ? summaryObject.status
    : null;
  return { mode, explanation, reasons, equivalence, summaryStatus };
}

export interface ReplayControlBarProps {
  readonly runtime: ReplayRuntime;
  readonly viewer: ReplayViewerRuntime;
  readonly publicTimeLabel?: string | undefined;
  readonly independentCharts?: boolean;
}

export default function ReplayControlBar({ runtime, viewer, publicTimeLabel, independentCharts = false }: ReplayControlBarProps) {
  useLocale();
  const [showEnd, setShowEnd] = useState(false);
  const [openOrderDisposition, setOpenOrderDisposition] = useState<"expire" | "cancel" | "preserve">("expire");
  const [positionDisposition, setPositionDisposition] = useState<"keep" | "mark_close">("keep");
  const [requestedAdvanceBasis, setRequestedAdvanceBasis] = useState<ReplayV2AdvanceBasis | null>(null);
  const [advanceAmount, setAdvanceAmount] = useState(1);
  const [controlError, setControlError] = useState<string | null>(null);
  const [requestedPlaybackRate, setRequestedPlaybackRate] = useState<number | null>(null);
  const endCancelRef = useRef<HTMLButtonElement | null>(null);
  const store = runtime.store;
  const config = store.sessionConfig;
  const tradeTape = config?.source_kind === "agg_trade";
  const ownsController = replayOwnsController(store, runtime.clientInstanceId);
  const pending = runtime.pendingCommand?.type ?? null;
  const phase3Pending = viewer.controlPending?.type ?? null;
  const controllerActionPending = pending === "acquire_controller"
    || phase3Pending === "acquire_controller"
    || phase3Pending === "takeover_controller";
  const contractPortfolio = viewer.marketTracks?.portfolio.schema_version === "replay.training.portfolio.v2"
    ? viewer.marketTracks.portfolio
    : null;
  const effectiveState = replayEffectiveTrainingState(
    viewer.marketTracks?.global_clock?.state,
    store.state,
    store.controllerClientId,
  );
  const globalClock = viewer.marketTracks?.global_clock ?? null;
  const runId = viewer.viewerState?.run_id;
  useEffect(() => { setControlError(null); }, [runId]);
  const disabled = pending !== null || phase3Pending !== null
    || store.connectionState !== "connected" || !ownsController
    || viewer.viewerState === null || viewer.viewerPending;
  const displayAdvanceId = config?.source_kind === "bar"
    && viewer.controlPending?.type === "advance"
    && viewer.controlPending.payload.basis === "DISPLAY_BAR"
    ? viewer.controlPending.command_id : null;
  const [displayCancelReady, setDisplayCancelReady] = useState<string | null>(null);
  useEffect(() => {
    if (displayAdvanceId === null) return;
    const timer = setTimeout(() => setDisplayCancelReady(displayAdvanceId), 250);
    return () => clearTimeout(timer);
  }, [displayAdvanceId]);
  const cancelableAdvancePending = replayAdvanceIsCancelable(
    viewer.controlPending,
    config?.source_kind === "bar",
  ) && (displayAdvanceId === null || displayCancelReady === displayAdvanceId);
  const phase3Ratio = viewer.progress?.ratio_ppm;
  const visiblePlan = fastForwardPlan(viewer.progress?.plan);
  const advanceProgress = typeof phase3Ratio === "number" && Number.isSafeInteger(phase3Ratio)
    ? Math.min(1, Math.max(0, phase3Ratio / 1_000_000))
    : null;
  const baseIntervalMs = Math.max(1, (parseIntervalSeconds(config?.base_interval ?? "1m") ?? 60) * 1_000);
  const supportedBases = globalClock?.supported_bases ?? [];
  const playbackBases = globalClock?.playback_bases ?? [];
  const advanceBasis = requestedAdvanceBasis !== null
    && supportedBases.includes(requestedAdvanceBasis)
    ? requestedAdvanceBasis
    : globalClock?.basis ?? "BASE_BAR";
  const playbackRate = requestedPlaybackRate ?? globalClock?.rate ?? 1;
  const globalMaxAdvanceCount = globalClock?.max_count ?? 100_000;
  const maxAdvanceCount = advanceBasis === "SOURCE_EVENT"
    ? Math.min(globalMaxAdvanceCount, SOURCE_EVENT_MAX_MANUAL_COUNT)
    : globalMaxAdvanceCount;
  const boundedAdvanceAmount = boundedReplayAdvanceAmount(
    advanceAmount,
    advanceBasis,
    globalMaxAdvanceCount,
  );
  const virtualTimeQuantumMs = globalClock?.virtual_time_quantum_ms ?? baseIntervalMs;
  const basisCanPlay = playbackBases.includes(advanceBasis);
  const canonicalAdvancePending = phase3Pending === "advance";
  const fallbackPublicTime = formatReplayPublicTime(store.virtualTimeMs, {
    blindMode: config?.blind_mode ?? true,
    originMs: store.replayStartMs,
  });
  const publicTime = publicTimeLabel ?? fallbackPublicTime;
  const summaryBuild = viewer.periodSummary?.status.active_set
    ?? viewer.periodSummary?.status.latest_build
    ?? null;
  const phase3Command = (
    type: ReplayPhase3ControlType,
    payload: Readonly<Record<string, ReplayV2Json>> = {},
  ) => {
    setControlError(null);
    void viewer.actions.submitControl(type, payload).catch((cause: unknown) => {
      setControlError(cause instanceof Error ? describeError(cause, cause.message) : t("replay.rt.control"));
    });
  };
  const submitCanonicalAdvance = (
    basis: ReplayV2AdvanceBasis,
    amount: number,
  ) => {
    const bounded = Math.min(maxAdvanceCount, Math.max(1, Math.trunc(amount)));
    phase3Command("advance", basis === "VIRTUAL_TIME"
      ? { basis, duration_ms: bounded * virtualTimeQuantumMs }
      : { basis, count: bounded });
  };
  const canonicalPlaybackPayload = (): Readonly<Record<string, ReplayV2Json>> => ({
    basis: advanceBasis,
    rate: playbackRate,
  });

  const displayInterval = viewer.viewerState?.display_interval ?? null;
  // With the display interval equal to the base interval, "next display bar" and "next base bar" are the same step.
  const showBaseAdvance = supportedBases.includes("BASE_BAR")
    && !(supportedBases.includes("DISPLAY_BAR") && displayInterval !== null && displayInterval === config?.base_interval);
  const confirmEnd = () => {
    setShowEnd(false);
    void (async () => {
      const payload = {
        open_order_disposition: openOrderDisposition,
        position_disposition: positionDisposition,
      };
      if (effectiveState === "PLAYING") await viewer.actions.submitControl("pause", {});
      await viewer.actions.submitControl("end", payload);
    })().catch(() => undefined);
  };

  return (
    <section className="replay-control-stack" aria-label={t("replay.control.aria")}>
      {store.connectionState !== "connected" && (
        <div className="replay-recovery-banner">
          <InlineAlert tone="warning" action={<Button size="sm" onClick={() => runtime.actions.requestResync("manual recovery")}>{t("replay.control.resync")}</Button>}>
            {t("replay.control.connection", { state: store.connectionState })}
          </InlineAlert>
        </div>
      )}
      {!ownsController && (
        <div className="replay-controller-banner">
          <InlineAlert
            tone="info"
            action={<Button
              size="sm"
              variant="primary"
              data-replay-action="takeover-controller"
              disabled={pending !== null || phase3Pending !== null || store.connectionState !== "connected"}
              onClick={() => {
                if (store.controllerClientId === null) {
                  phase3Command("acquire_controller", { takeover: false });
                } else {
                  phase3Command("takeover_controller");
                }
              }}
            >
              {controllerActionPending
                ? store.controllerClientId ? t("replay.control.taking") : t("replay.control.restoring")
                : store.controllerClientId
                ? t("replay.control.take")
                : effectiveState === "ENDED" ? t("replay.control.takeReview") : t("replay.control.takeControl")}
            </Button>}
          >
            {store.controllerClientId
              ? t("replay.control.otherPage")
              : effectiveState === "ENDED"
                ? t("replay.control.ended")
                : controllerActionPending
                  ? t("replay.control.recovering")
                  : t("replay.control.readonly")}
          </InlineAlert>
        </div>
      )}
      {controlError && (
        <div className="replay-command-error" data-replay-control-error>
          <InlineAlert tone="danger">{controlError}</InlineAlert>
        </div>
      )}
      {(runtime.commandError || store.error) && (
        <div className="replay-command-error" data-replay-command-error={runtime.commandError?.code ?? store.error?.code}>
          <InlineAlert
            tone="danger"
            title={runtime.commandError?.message ?? store.error?.message}
            action={runtime.commandRecoveryPending ? (
              <Button
                size="sm"
                data-replay-action="reconcile-command"
                disabled={!runtime.commandRecoveryReady || runtime.commandRecoveryInFlight}
                onClick={() => void runtime.actions.retryPendingCommandRecovery().catch(() => undefined)}
              >{runtime.commandRecoveryInFlight ? t("replay.control.reconciling") : t("replay.control.reconcile")}</Button>
            ) : undefined}
          >
            <code>{runtime.commandError?.code ?? store.error?.code}</code>
            {(runtime.commandError?.details?.needs_resync === true) && <> · {t("replay.control.unknownResult")}</>}
            {(runtime.commandError?.code === "REVISION_CONFLICT") && <> · {t("replay.control.resyncWait")}</>}
          </InlineAlert>
        </div>
      )}
      <div className="replay-control-bar">
        <Button
          size="sm"
          variant="ghost"
          className="replay-control-end"
          data-replay-action="end"
          aria-haspopup="dialog"
          aria-expanded={showEnd}
          disabled={disabled || effectiveState === "ENDED"}
          onClick={() => setShowEnd(true)}
        >{t("replay.control.end")}</Button>
        <span className="replay-control-divider" aria-hidden="true" />
        <div className="replay-control-group">
          {supportedBases.includes("DISPLAY_BAR") && (
            <Button size="sm" title={t("replay.control.advanceDisplayTitle")} data-replay-action="advance-display" disabled={disabled || effectiveState !== "PAUSED"} onClick={() => submitCanonicalAdvance("DISPLAY_BAR", 1)}>
              {canonicalAdvancePending ? t("replay.control.advancing") : t("replay.control.nextDisplay", { interval: displayInterval ?? "--" })}
            </Button>
          )}
          {showBaseAdvance && (
            <Button size="sm" title={t("replay.control.advanceBaseTitle")} data-replay-action="advance-base" disabled={disabled || effectiveState !== "PAUSED"} onClick={() => submitCanonicalAdvance("BASE_BAR", 1)}>
              {canonicalAdvancePending ? t("replay.control.advancing") : t("replay.control.nextBase", { interval: config?.base_interval ?? "--" })}
            </Button>
          )}
          {supportedBases.includes("SOURCE_EVENT") && (
            <Button size="sm" data-replay-action="advance-source-event" disabled={disabled || effectiveState !== "PAUSED"} onClick={() => submitCanonicalAdvance("SOURCE_EVENT", 1)}>
              {canonicalAdvancePending ? t("replay.control.advancing") : tradeTape ? t("replay.control.nextAgg") : t("replay.control.nextSource")}
            </Button>
          )}
        </div>
        <Button
          size="sm"
          variant="primary"
          data-replay-action={effectiveState === "PLAYING" ? "pause" : "play"}
          disabled={
            disabled
            || !["PAUSED", "PLAYING"].includes(effectiveState ?? "")
            || (effectiveState !== "PLAYING" && !basisCanPlay)
          }
          title={!basisCanPlay ? t("replay.control.manualBasis") : undefined}
          onClick={() => {
            const type = effectiveState === "PLAYING" ? "pause" : "play";
            phase3Command(type, type === "play" ? canonicalPlaybackPayload() : {});
          }}
        >
          {pending === "pause" || phase3Pending === "pause" ? t("replay.control.pausing") : pending === "play" || phase3Pending === "play" ? t("replay.control.playing") : effectiveState === "PLAYING" ? t("replay.control.pause") : t("replay.control.play")}
        </Button>
        <span className="replay-control-divider" aria-hidden="true" />
        <label className="replay-speed-control">
          <span>{t("replay.control.basis")}</span>
          <Select
            size="sm"
            data-replay-action="advance-basis"
            value={advanceBasis}
            disabled={disabled || effectiveState === "PLAYING" || effectiveState === "ENDED"}
            onChange={(event) => setRequestedAdvanceBasis(event.target.value as ReplayV2AdvanceBasis)}
          >
            {supportedBases.map((basis) => (
              <option key={basis} value={basis}>
                {basis === "SOURCE_EVENT"
                  ? (tradeTape ? t("replay.control.aggSource") : t("replay.control.barSource"))
                  : basisLabel(basis)}
                {!playbackBases.includes(basis) ? t("replay.control.manualOnly") : ""}
              </option>
            ))}
          </Select>
        </label>
        {independentCharts && <label className="replay-speed-control">
          <span>{t("replay.control.displayBar")}</span>
          <Select size="sm" value={displayInterval ?? "1m"}
            disabled={disabled || effectiveState !== "PAUSED"}
            onChange={(event) => { void viewer.actions.setDisplayInterval(event.target.value)
              .catch((cause: unknown) => setControlError(String(cause))); }}>
            {replayDisplayIntervalOptions(config?.base_interval ?? "1m", displayInterval ?? "1m")
              .map((interval) => <option key={interval} value={interval}>{interval}</option>)}
          </Select>
        </label>}
        <label className="replay-speed-control">
          <span>{t("replay.control.amount")}</span>
          <Input
            size="sm"
            className="replay-control-amount"
            data-replay-action="advance-amount"
            type="number"
            min={1}
            max={maxAdvanceCount}
            step={1}
            value={boundedAdvanceAmount}
            disabled={disabled || effectiveState !== "PAUSED"}
            onChange={(event) => setAdvanceAmount(Math.min(
              maxAdvanceCount,
              Math.max(1, Math.trunc(Number(event.target.value) || 1)),
            ))}
          />
        </label>
        <Button
          size="sm"
          data-replay-action="advance"
          title={t("replay.control.advance", { count: `${boundedAdvanceAmount} ${basisLabel(advanceBasis)}` })}
          disabled={disabled || effectiveState !== "PAUSED"}
          onClick={() => submitCanonicalAdvance(advanceBasis, boundedAdvanceAmount)}
        >
          {canonicalAdvancePending ? t("replay.control.advancing") : t("replay.control.advance", { count: boundedAdvanceAmount })}
        </Button>
        {cancelableAdvancePending && (
          <Button
            size="sm"
            data-replay-action="cancel-advance"
            disabled={store.connectionState !== "connected" || !ownsController}
            onClick={() => void viewer.actions.cancelAdvance().catch(() => undefined)}
          >{t("replay.control.cancelAdvance")}</Button>
        )}
        <label className="replay-speed-control">
          <span>{t("replay.control.speed")}</span>
          <Select
            size="sm"
            data-replay-action="playback-rate"
            value={String(playbackRate)}
            disabled={disabled || effectiveState === "ENDED" || !basisCanPlay}
            onChange={(event) => {
              const rate = Number(event.target.value);
              setRequestedPlaybackRate(rate);
              phase3Command("set_speed", { basis: advanceBasis, rate });
            }}
          >
            {PLAYBACK_RATES.map((rate) => (
              <option key={rate} value={rate}>
                {advanceBasis === "VIRTUAL_TIME"
                  ? t("replay.control.rateTime", { rate })
                  : t("replay.control.rateUnit", {
                    rate,
                    unit: advanceBasis === "SOURCE_EVENT" && tradeTape ? t("replay.source.agg") : basisLabel(advanceBasis),
                  })}
              </option>
            ))}
          </Select>
        </label>
        <div
          className="replay-progress"
          data-replay-progress={cancelableAdvancePending
            ? advanceProgress === null ? "unknown" : advanceProgress.toFixed(4)
            : "hidden"}
          data-replay-grain={phase3Pending ?? "idle"}
        >
          <span className="replay-public-time">{publicTime}</span>
          {cancelableAdvancePending && (
            <span className="replay-advance-progress" data-replay-command-progress="active">
              <span>{t("replay.control.thisAdvance")}</span>
              <progress
                max={1}
                {...(advanceProgress === null ? {} : { value: advanceProgress })}
                aria-label={t("replay.control.advanceProgress")}
              />
              <span>{advanceProgress === null ? t("replay.control.preparing") : `${(advanceProgress * 100).toFixed(1)}%`}</span>
            </span>
          )}
        </div>
      </div>

      <Disclosure className="replay-control-diagnostics" summary={t("replay.control.diagnostics")}>
        <div className="replay-control-diagnostics-body">
          <div className="replay-fidelity-chips">
            <Badge>{tradeTape ? "AGG_TRADE" : `BAR_${config?.base_interval.toUpperCase() ?? "--"}`}</Badge>
            <Badge>{contractPortfolio?.execution_model ?? "--"}</Badge>
            <Badge>{tradeTape ? "VERIFIED_TAPE · APPROX_BARS" : "EXACT_BAR"}</Badge>
            <Badge>{contractPortfolio === null
              ? (tradeTape ? "AGG_TRADE_TAPE" : "BAR_CONSERVATIVE")
              : "NO_BOOK_QUEUE"}</Badge>
          </div>
          {visiblePlan !== null && (
            <div
              className="replay-fast-forward-plan"
              data-replay-fast-forward-plan={visiblePlan.mode}
              data-replay-equivalence={visiblePlan.equivalence}
            >
              <strong>{visiblePlan.mode}</strong>
              <span>{visiblePlan.explanation}</span>
              {visiblePlan.reasons.length > 0 && <code>{visiblePlan.reasons.join(" · ")}</code>}
              <span>{t("replay.control.equivalence", { value: visiblePlan.equivalence })}</span>
              {visiblePlan.summaryStatus !== null && (
                <span>{t("replay.control.summaryStatus", { value: visiblePlan.summaryStatus })}</span>
              )}
            </div>
          )}
          <div
            className="replay-period-summary-status"
            data-replay-period-summary={
              viewer.periodSummary?.enabled === false
                ? "DISABLED"
                : summaryBuild?.status ?? (viewer.summaryError === null ? "EMPTY" : "ERROR")
            }
          >
            <strong>{t("replay.control.summary")}</strong>
            {viewer.periodSummary?.enabled === false ? (
              <span>{t("replay.control.summaryDisabled")}</span>
            ) : summaryBuild === null ? (
              <span>{t("replay.control.summaryEmpty")}</span>
            ) : (
              <span>
                {t("replay.control.summaryStats", {
                  status: summaryBuild.status,
                  count: summaryBuild.candidate_count,
                  bytes: summaryBuild.compressed_bytes,
                  ms: summaryBuild.build_wall_ms,
                })}
              </span>
            )}
            {viewer.summaryError !== null && (
              <span role="alert" className="replay-period-summary-error">{viewer.summaryError}</span>
            )}
            <Button
              size="sm"
              data-replay-action="prepare-period-summaries"
              disabled={
                viewer.periodSummary?.enabled === false
                || viewer.summaryPreparing
                || viewer.controlPending !== null
                || viewer.viewerPending
                || effectiveState !== "PAUSED"
                || store.connectionState !== "connected"
              }
              onClick={() => void viewer.actions.preparePeriodSummaries().catch(() => undefined)}
            >
              {viewer.summaryPreparing
                ? t("replay.control.scanning")
                : summaryBuild?.status === "READY" ? t("replay.control.rebuildSummary") : t("replay.control.prepareSummary")}
            </Button>
          </div>
        </div>
      </Disclosure>

      <Dialog
        open={showEnd}
        size="sm"
        className="replay-end-dialog"
        title={t("replay.control.endTitle")}
        description={t("replay.control.endHint")}
        initialFocusRef={endCancelRef}
        onClose={() => setShowEnd(false)}
        footer={<>
          <Button ref={endCancelRef} data-replay-action="cancel-end" onClick={() => setShowEnd(false)}>{t("replay.control.cancel")}</Button>
          <Button variant="danger" data-replay-action="confirm-end" onClick={confirmEnd}>{t("replay.control.confirmEnd")}</Button>
        </>}
      >
        <div className="replay-end-fields">
          <Field label={t("replay.control.openOrders")}>
            <Select value={openOrderDisposition} onChange={(event) => setOpenOrderDisposition(event.target.value as typeof openOrderDisposition)}>
              <option value="expire">{t("replay.control.expire")}</option><option value="cancel">{t("replay.control.cancel")}</option><option value="preserve">{t("replay.control.preserve")}</option>
            </Select>
          </Field>
          <Field label={t("replay.control.positions")}>
            <Select value={positionDisposition} onChange={(event) => setPositionDisposition(event.target.value as typeof positionDisposition)}>
              <option value="keep">{t("replay.control.keepUnrealized")}</option><option value="mark_close">{t("replay.control.markClose")}</option>
            </Select>
          </Field>
        </div>
      </Dialog>
    </section>
  );
}
