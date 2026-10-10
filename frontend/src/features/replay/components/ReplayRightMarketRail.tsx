import React, { useCallback, useMemo } from "react";
import MarketRightRailFrame from "../../../app/MarketRightRailFrame.js";
import {
  AccountRailIcon,
  ActivityRailIcon,
  CapabilityRailIcon,
  PaperRailIcon,
  WatchlistRailIcon,
} from "../../../app/marketRailIcons.js";
import type { MarketRailViewDescriptor } from "../../../app/marketRailTypes.js";
import ReplayCapabilitySurface from "./ReplayCapabilitySurface.js";
import { buildReplayCapabilityModel } from "../replayCapabilityModel.js";
import ReplayMarketDataDock from "./ReplayMarketDataDock.js";
import ReplayPaperTradingDock from "./ReplayPaperTradingDock.js";
import ReplayTradingWorkbench from "./ReplayTradingWorkbench.js";
import ReplayWatchlistPanel from "./ReplayWatchlistPanel.js";
import {
  REPLAY_RAIL_VIEW_IDS,
} from "../replayWorkspacePreferences.js";
import type {
  ReplayRailViewId,
  ReplayWorkspacePreferenceActions,
  ReplayWorkspacePreferences,
} from "../replayWorkspacePreferences.js";
import type {
  ReplaySharedIndicatorRuntime,
} from "../useReplaySharedIndicatorRuntime.js";
import type { ReplayRuntime } from "../useReplayRuntime.js";
import type { ReplayViewerRuntime } from "../useReplayViewerRuntime.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";

export interface ReplayRightMarketRailProps {
  readonly runtime: ReplayRuntime;
  readonly viewer: ReplayViewerRuntime;
  readonly indicators: ReplaySharedIndicatorRuntime;
  readonly preferences: ReplayWorkspacePreferences;
  readonly actions: ReplayWorkspacePreferenceActions;
  readonly upColor: string;
  readonly downColor: string;
  readonly formatTime: (valueMs: number) => string;
}

function ReplayRightMarketRail({
  runtime,
  viewer,
  indicators,
  preferences,
  actions,
  upColor,
  downColor,
  formatTime,
}: ReplayRightMarketRailProps) {
  const locale = useLocale();
  const selectedTrackId = viewer.viewerState?.selected_track_id ?? null;
  const selectedTrack = viewer.marketTracks?.tracks.find(
    (track) => track.track_id === selectedTrackId,
  ) ?? null;
  const capabilities = useMemo(() => buildReplayCapabilityModel(
    runtime.store.sessionConfig?.source_kind ?? "BAR",
    selectedTrack?.historical_book ?? null,
  ), [runtime.store.sessionConfig?.source_kind, selectedTrack?.historical_book]);

  // One view at a time, ordered by how often a trader reaches for it.
  const views = useMemo<MarketRailViewDescriptor[]>(() => [
    {
      id: REPLAY_RAIL_VIEW_IDS.paper,
      title: t("replay.rail.paper", {}, locale),
      icon: <PaperRailIcon />,
      order: 10,
      sizing: "flex",
      collapsedSummary: t("replay.rail.paperSummary", {}, locale),
    },
    {
      id: REPLAY_RAIL_VIEW_IDS.account,
      title: t("replay.rail.account", {}, locale),
      icon: <AccountRailIcon />,
      order: 20,
      sizing: "flex",
      collapsedSummary: t("replay.rail.accountSummary", {}, locale),
    },
    {
      id: REPLAY_RAIL_VIEW_IDS.watchlist,
      title: t("replay.rail.watchlist", {}, locale),
      icon: <WatchlistRailIcon />,
      order: 30,
      sizing: "flex",
      collapsedSummary: t("replay.rail.watchlistSummary", {}, locale),
    },
    {
      id: REPLAY_RAIL_VIEW_IDS.activity,
      title: t("replay.rail.activity", {}, locale),
      icon: <ActivityRailIcon />,
      order: 40,
      sizing: "flex",
      collapsedSummary: t("replay.rail.activitySummary", {}, locale),
    },
    {
      id: REPLAY_RAIL_VIEW_IDS.capabilities,
      title: t("replay.rail.capabilities", {}, locale),
      icon: <CapabilityRailIcon />,
      order: 50,
      sizing: "flex",
      collapsedSummary: t("replay.rail.capabilitiesSummary", {}, locale),
    },
  ], [locale]);

  const onActivateView = useCallback((viewId: string) => {
    actions.activateView(viewId as ReplayRailViewId);
  }, [actions]);

  const tradingViewOpen = preferences.openViewIds[0] === REPLAY_RAIL_VIEW_IDS.paper
    || preferences.openViewIds[0] === REPLAY_RAIL_VIEW_IDS.account;
  const effectiveRailWidth = tradingViewOpen
    ? Math.max(360, preferences.railWidth)
    : preferences.railWidth;

  const renderView = useCallback((viewId: string) => {
    if (viewId === REPLAY_RAIL_VIEW_IDS.watchlist) {
      return (
        <ReplayWatchlistPanel
          runtime={runtime}
          viewer={viewer}
          collapsed={false}
          embedded
          onCollapsedChange={(collapsed) => {
            if (collapsed) actions.setPanelCollapsed(true);
          }}
        />
      );
    }

    const title =
      viewId === REPLAY_RAIL_VIEW_IDS.paper ? t("replay.rail.paper", {}, locale)
        : viewId === REPLAY_RAIL_VIEW_IDS.account ? t("replay.rail.account", {}, locale)
          : viewId === REPLAY_RAIL_VIEW_IDS.activity ? t("replay.rail.activity", {}, locale)
            : viewId === REPLAY_RAIL_VIEW_IDS.capabilities ? t("replay.rail.capabilities", {}, locale)
              : viewId;
    const dockAttr =
      viewId === REPLAY_RAIL_VIEW_IDS.paper ? "paper"
        : viewId === REPLAY_RAIL_VIEW_IDS.account ? "account"
          : viewId === REPLAY_RAIL_VIEW_IDS.activity ? "activity"
            : "capabilities";

    return (
      <section
        className="replay-market-dock"
        style={{ height: "100%" }}
        data-active-dock={dockAttr}
        aria-label={t("replay.rail.dockAria", { title }, locale)}
      >
        <div className="replay-market-dock-body">
          {viewId === REPLAY_RAIL_VIEW_IDS.capabilities && (
            <ReplayCapabilitySurface capabilities={capabilities} />
          )}
          {viewId === REPLAY_RAIL_VIEW_IDS.paper && (
            <ReplayPaperTradingDock
              runtime={runtime}
              viewer={viewer}
            />
          )}
          {viewId === REPLAY_RAIL_VIEW_IDS.account && (
            <ReplayTradingWorkbench
              runtime={runtime}
              viewer={viewer}
              formatTime={formatTime}
            />
          )}
          {viewId === REPLAY_RAIL_VIEW_IDS.activity && (
            <ReplayMarketDataDock
              runtime={runtime}
              viewer={viewer}
              indicatorStatus={indicators.status}
              formatTime={formatTime}
            />
          )}
        </div>
      </section>
    );
  }, [
    actions,
    capabilities,
    formatTime,
    indicators.status,
    runtime,
    locale,
    viewer,
  ]);

  return (
    <MarketRightRailFrame
      source="replay"
      layoutMode="single-view"
      ariaLabel={t("replay.rail.sidebarAria")}
      views={views}
      openViewIds={preferences.openViewIds}
      panelCollapsed={preferences.panelCollapsed}
      onToggleView={onActivateView}
      onTogglePanelCollapsed={actions.togglePanelCollapsed}
      renderView={renderView}
      layout={{
        width: effectiveRailWidth,
        onWidthChange: actions.setRailWidth,
      }}
      upColor={upColor}
      downColor={downColor}
    />
  );
}

export default React.memo(ReplayRightMarketRail);
