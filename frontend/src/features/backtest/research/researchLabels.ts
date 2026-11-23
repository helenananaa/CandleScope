import { t, type MessageKey } from "../../../i18n/index.js";
import { getLocale } from "../../../i18n/locale.js";

/**
 * Display names for the codes research data carries: run, study and review states, and the
 * accuracy a run's fills were computed at. A code without a name of its own is shown as sent,
 * so a new backend state stays visible instead of being mislabelled.
 */
const STATE_KEYS: Readonly<Record<string, MessageKey>> = {
  DRAFT: "common.state.draft",
  VALIDATING: "common.state.validating",
  QUEUED: "common.state.queued",
  PLANNED: "common.state.queued",
  PREPARING: "common.state.preparing",
  RUNNING: "common.state.running",
  PAUSING: "common.state.pausing",
  PAUSED: "common.state.paused",
  COMPLETING: "common.state.completing",
  COMPLETED: "common.state.completed",
  CANCELLING: "common.state.cancelling",
  CANCELLED: "common.state.cancelled",
  CANCELED: "common.state.cancelled",
  FAILED: "common.state.failed",
  INTERRUPTED: "common.state.interrupted",
  AWAITING_HOLDOUT: "common.state.awaitingHoldout",
  SEALED: "common.state.awaitingHoldout",
  BLINDED: "common.state.blinded",
  REVEALED: "common.state.revealed",
  READY: "common.state.ready",
  ACCEPTED: "common.state.accepted",
  FILLED: "common.state.filled",
  REJECTED: "common.state.rejected",
  EXPIRED: "common.state.expired",
};

export function researchStateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  const key = STATE_KEYS[state.toUpperCase()];
  return key ? t(key) : state;
}

const FIDELITY_KEYS: Readonly<Record<string, MessageKey>> = {
  BAR_APPROX: "research.fidelity.bar",
  TRADE_TAPE: "research.fidelity.tape",
  AGG_TRADE_TAPE: "research.fidelity.aggTape",
  AGG_TRADE_EXECUTION: "research.fidelity.aggTape",
  BOOK_ASSISTED: "research.fidelity.bookAssisted",
  BOOK_DEPTH: "research.fidelity.bookDepth",
  BOOK_SAMPLED: "research.fidelity.bookSampled",
  QUEUE_EXACT: "research.fidelity.queue",
};

/** The accuracy a run's fills were computed at (its fidelity mode). */
export function researchFidelityLabel(mode: string | null | undefined): string {
  if (!mode) return "—";
  const key = FIDELITY_KEYS[mode.toUpperCase()];
  return key ? t(key) : mode;
}

/** Why a chart's data cannot be used as it is, for a chart-context resolution status. */
export function chartContextStatusLabel(status: string): string {
  switch (status) {
    case "NEEDS_DATA": return t("chartTester.status.needs_data");
    case "UNSUPPORTED_INTERVAL": return t("chartTester.error.interval");
    case "UNSUPPORTED_FIDELITY": return t("chartTester.error.fidelity");
    case "AMBIGUOUS_MARKET": return t("research.context.ambiguousMarket");
    case "UNAVAILABLE": return t("serverError.unavailable");
    default: return status;
  }
}

/** A time range sent as epoch milliseconds, as UTC dates and times (the zone the range fields edit in). */
export function researchTimeRangeLabel(startMs: number | null | undefined, endMs: number | null | undefined): string {
  const format = (value: number | null | undefined) =>
    typeof value === "number" && Number.isFinite(value) ? new Date(value).toLocaleString(getLocale(), { timeZone: "UTC" }) : "—";
  return `${format(startMs)} → ${format(endMs)} UTC`;
}

/** A content fingerprint such as "sha256:a4ee…", without its algorithm and cut to a readable length. */
export function shortFingerprint(value: string | null | undefined, length = 12): string {
  if (!value) return "—";
  const digest = value.includes(":") ? value.slice(value.indexOf(":") + 1) : value;
  return digest.length > length ? `${digest.slice(0, length)}…` : digest;
}
