import { Badge, InlineAlert } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ReplayReviewResponse } from "../replayIntegrityModel.js";
import type { ReactNode } from "react";

export default function ReplayReviewRightRail({ review, notes }: { readonly review: ReplayReviewResponse; readonly notes?: ReactNode }) {
  useLocale();
  const selectedTrackId = String(review.projection.viewer_state.selected_track_id ?? "");
  const selected = review.projection.tracks.find((track) => track.track_id === selectedTrackId)
    ?? review.projection.tracks[0]
    ?? null;
  const portfolio = review.projection.domain.portfolio;
  const accountRecord = portfolio !== null && typeof portfolio === "object" && !Array.isArray(portfolio)
    ? portfolio as Readonly<Record<string, unknown>> : null;
  const positionText = Array.isArray(accountRecord?.positions) ? accountRecord.positions.flatMap((position: unknown) => {
    if (position === null || typeof position !== "object" || Array.isArray(position)) return [];
    const record = position as Readonly<Record<string, unknown>>;
    if (record.track_id !== selectedTrackId) return [];
    const side = record.position_side === "LONG" ? t("replay.results.long")
      : record.position_side === "SHORT" ? t("replay.results.short") : "";
    return [`${side} ${String(record.quantity)}`.trim()];
  }).join(" · ") || "0" : "--";
  return (
    <aside
      className="replay-review-right-rail"
      aria-label={t("replay.shell.reviewPortfolio")}
      data-review-track-id={selectedTrackId}
    >
      <header className="replay-review-rail-head">
        <h3>{String(selected?.symbol ?? "--")}</h3>
        <Badge tone="accent">{t("replay.kicker.reviewReadOnly")}</Badge>
      </header>
      <dl className="replay-review-rail-facts">
        <div><dt>{t("replay.shell.publicTime")}</dt><dd>{review.events.find((event) => event.event_id === review.selected_event_id)?.public_time.label ?? "--"}</dd></div>
        <div><dt>{t("replay.shell.equity")}</dt><dd>{String(accountRecord?.equity ?? "--")}</dd></div>
        <div><dt>{t("replay.shell.position")}</dt><dd>{positionText}</dd></div>
        <div><dt>{t("replay.shell.unrealized")}</dt><dd>{String(accountRecord?.unrealized_pnl ?? "--")}</dd></div>
        <div><dt>{t("replay.shell.available")}</dt><dd>{String(accountRecord?.available_equity ?? "--")}</dd></div>
        <div><dt>{t("replay.shell.ordersFills")}</dt><dd>{review.projection.orders.length} / {review.projection.fills.length}</dd></div>
        <div><dt>{t("replay.shell.ledger")}</dt><dd>{review.projection.ledger.length}</dd></div>
        <div><dt>{t("replay.shell.drawingRev")}</dt><dd>r{review.projection.drawing_revision}</dd></div>
      </dl>
      {accountRecord?.status === "LEGACY_PARTIAL" && <InlineAlert tone="warning">{t("replay.shell.legacyAccountIncomplete")}</InlineAlert>}
      {accountRecord?.status === "UNAVAILABLE" && <InlineAlert tone="warning">{t("serverError.unavailable")}</InlineAlert>}
      <p className="replay-review-rail-hint">{t("replay.shell.reviewSidebarHint")}</p>
      {notes}
    </aside>
  );
}

