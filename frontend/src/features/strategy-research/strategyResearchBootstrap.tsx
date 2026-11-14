import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import AppProviders, { ChartErrorBoundary } from "../../app/AppProviders.js";
import { bindDocumentLocale, initializeLocale } from "../../i18n/index.js";
import { readPersistedLocale } from "../settings/chartAppearanceSettings.js";
import "./strategyResearch.css";
// Event markers on imported data (LocalAnalysisPanel, which tests import, so it cannot import CSS itself).
import "../local-data/localAnalysis.css";
import "../backtest/research/backtestResearch.css";
import "../backtest/chart-tester/chartStrategyTester.css";
import "../backtest/continuous/continuousStrategy.css";
import {
  parseStrategyResearchLaunch,
  type StrategyResearchLaunchIntent,
  type StrategyResearchPage,
} from "./strategyResearchLaunch.js";
import { canonicalStrategyResearchHref } from "./strategyResearchMode.js";

const StrategyResearchApp = lazy(() => import("./StrategyResearchApp.js"));

/** strategy.html, and its compatibility URLs backtest.html and local.html, all open the one strategy research page. */
export function renderStrategyResearchBootstrap(input: {
  page: StrategyResearchPage;
  location?: { pathname: string; search: string };
}): ReactNode {
  const location = input.location ?? { pathname: `/${input.page}.html`, search: "" };
  const intent: StrategyResearchLaunchIntent = parseStrategyResearchLaunch(location);
  return <StrategyResearchApp intent={intent} />;
}

export async function mountStrategyResearchPage(input: {
  page: StrategyResearchPage;
}): Promise<void> {
  await initializeLocale(readPersistedLocale());
  // One page: the compatibility URLs carry the strategy research title too.
  bindDocumentLocale({ titleKey: "strategy.documentTitle", descriptionKey: "strategy.documentDescription" });
  const root = document.getElementById("root");
  if (!(root instanceof HTMLElement)) {
    throw new Error("Strategy research document root is missing");
  }
  const location = { pathname: window.location.pathname, search: window.location.search };
  // backtest.html and local.html stay as compatibility URLs: show the canonical address.
  const canonical = canonicalStrategyResearchHref(location, parseStrategyResearchLaunch(location));
  if (canonical !== null) window.history.replaceState(window.history.state, "", canonical);
  createRoot(root).render(
    <StrictMode>
      <ChartErrorBoundary>
        <Suspense fallback={<main className="research-status-page" data-state="loading" />}>
          <AppProviders>
            {renderStrategyResearchBootstrap({ page: input.page, location })}
          </AppProviders>
        </Suspense>
      </ChartErrorBoundary>
    </StrictMode>,
  );
}
