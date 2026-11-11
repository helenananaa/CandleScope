import "./styles/fonts.js";
import "./index.css";
import "./features/backtest/backtest.css";
import "./features/backtest/research/backtestResearch.css";
import {
  isBacktestLegacyWorkbenchEnabled,
  isBacktestResearchEnabled,
} from "./features/backtest/backtestFlags.js";
import { mountStrategyResearchPage } from "./features/strategy-research/strategyResearchBootstrap.js";

void mountStrategyResearchPage({
  page: "backtest",
  researchEnabled: isBacktestResearchEnabled(),
  legacyEnabled: isBacktestLegacyWorkbenchEnabled(),
}); // compatibility URL; canonical is /strategy.html
