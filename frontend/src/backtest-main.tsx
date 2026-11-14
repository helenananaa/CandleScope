import "./styles/layers.css";
import "./styles/fonts.js";
import "./index.css";
import "./features/backtest/backtest.css";
import "./features/backtest/research/backtestResearch.css";
import { mountStrategyResearchPage } from "./features/strategy-research/strategyResearchBootstrap.js";

void mountStrategyResearchPage({ page: "backtest" }); // compatibility URL; canonical is /strategy.html
