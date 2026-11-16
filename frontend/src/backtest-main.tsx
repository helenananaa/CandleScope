import "./styles/layers.css";
import "./styles/fonts.js";
import "./index.css";
import { mountStrategyResearchPage } from "./features/strategy-research/strategyResearchBootstrap.js";

void mountStrategyResearchPage({ page: "backtest" }); // compatibility URL; canonical is /strategy.html
