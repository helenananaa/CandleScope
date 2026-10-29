import type { AppShellViewModelContext } from "../appShellContracts.js";
import type { StatusBarModel } from "../StatusBar.js";

export function buildStatusBarViewModel({
  marketDisplay,
  marketStatus,
  marketView,
  sessionStatus,
  indicatorComputing,
}: AppShellViewModelContext): StatusBarModel {
  const {
    wsStatusLabel,
    exchangeLabel,
    marketLabel,
  } = marketDisplay;

  return {
    connectionStatus: marketView.connectionStatus,
    dataSource: marketView.dataSource || "",
    exchangeLabel,
    marketLabel,
    wsStatus: marketView.wsStatus,
    wsStatusLabel,
    barCount: marketStatus.barCount,
    loadingMoreLeft: marketStatus.loadingMoreLeft,
    hasMoreLeft: marketStatus.hasMoreLeft,
    historyPreparing: marketStatus.historyPreparing === true,
    indicatorComputing,
    exchangeCatalogStatus: sessionStatus.exchangeCatalogStatus,
    exchangeLimitations: sessionStatus.exchangeLimitations,
  };
}
