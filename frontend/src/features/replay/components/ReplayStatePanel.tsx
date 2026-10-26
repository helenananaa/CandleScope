import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ReplayRuntime } from "../useReplayRuntime.js";

type StateRuntime = Pick<ReplayRuntime, "phase" | "error">
  & { readonly store: Pick<ReplayRuntime["store"], "hasAuthoritativeSnapshot" | "error">;
      readonly actions: Pick<ReplayRuntime["actions"], "retry" | "requestResync"> };

export default function ReplayStatePanel({ runtime }: { readonly runtime: StateRuntime }) {
  useLocale();
  const terminalError = runtime.phase === "ERROR" || runtime.phase === "ENTRY_ERROR";
  // A resync clears the old snapshot before reconnecting. Transport failures
  // still belong to the store, even though the runtime phase remains ACTIVE.
  const error = terminalError ? runtime.error
    : !runtime.store.hasAuthoritativeSnapshot ? runtime.store.error : null;
  if (terminalError || error !== null) {
    return (
      <div className="chart-area" data-replay-state="error" data-replay-error={error?.code ?? "REPLAY_RUNTIME_ERROR"}>
        <div className="error-overlay">
          <div className="error-icon">!</div>
          <div className="error-message">
            <strong>{t("replay.shell.unavailable")}</strong><br />
            {error?.code ?? "REPLAY_RUNTIME_ERROR"}: {error?.message ?? "Unknown replay error"}
            <small>{t("replay.shell.failClosed")}</small>
          </div>
          {runtime.phase === "ERROR" && <button className="retry-btn" type="button" onClick={runtime.actions.retry}>{t("replay.shell.retryCaps")}</button>}
          {!terminalError && <button className="retry-btn" type="button" data-replay-action="resync"
            onClick={() => runtime.actions.requestResync("manual recovery")}>{t("replay.control.resync")}</button>}
        </div>
      </div>
    );
  }
  const labels: Readonly<Record<string, string>> = {
    IDLE: t("replay.shell.idle"),
    LOADING_CAPABILITIES: t("replay.shell.loadingCaps"),
    VALIDATING_SESSION: t("replay.shell.validating"),
    CONNECTING_SESSION: t("replay.shell.connecting"),
    STOPPED: t("replay.shell.stopped"),
  };
  return (
    <div className="chart-area" data-replay-state="loading">
      <div className="error-overlay">
        <div className="replay-loading-spinner" />
        <div className="error-message"><strong>{t("replay.shell.replay")}</strong><br />{labels[runtime.phase] ?? t("replay.shell.recovering")}<small>{t("replay.shell.noLiveMock")}</small></div>
      </div>
    </div>
  );
}

