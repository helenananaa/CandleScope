import { useState } from "react";
import { Button, InlineAlert } from "../components/ui/index.js";
import {
  backendConnectionStore,
  useBackendConnection,
  type BackendConnectionState,
  type BackendConnectionStore,
} from "../desktop/backendConnection.js";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";

function headline(state: BackendConnectionState): string {
  if (state.phase === "restarting") {
    return state.attempt > 0
      ? t("backend.restarting", { attempt: state.attempt, max: Math.max(state.attempt, state.maxAttempts) })
      : t("backend.restartingRequested");
  }
  return state.phase === "failed" ? t("backend.failed") : t("backend.stopped");
}

/**
 * Says when the local service is down, so nothing on the page reads as live,
 * and offers a restart once automatic restarts have stopped.
 */
export default function BackendStatusBanner({ store = backendConnectionStore() }: { store?: BackendConnectionStore }) {
  useLocale();
  const state = useBackendConnection(store);
  const [requesting, setRequesting] = useState(false);
  if (state.phase === "running") return null;
  const canRestart = state.phase === "failed" || state.phase === "stopped";
  const restart = () => {
    setRequesting(true);
    void store.restart().finally(() => setRequesting(false));
  };
  return (
    <div className="backend-status-banner" data-backend-phase={state.phase}>
      <InlineAlert
        tone={canRestart ? "danger" : "warning"}
        title={headline(state)}
        action={canRestart ? (
          <Button variant="primary" size="sm" disabled={requesting} onClick={restart} data-backend-restart="true">
            {t("backend.restart")}
          </Button>
        ) : null}
      >
        <span>{t("backend.notLive")}</span>
        {canRestart && state.error ? (
          <span className="backend-status-banner-reason" title={state.error}>{t("backend.reason", { reason: state.error })}</span>
        ) : null}
      </InlineAlert>
    </div>
  );
}
