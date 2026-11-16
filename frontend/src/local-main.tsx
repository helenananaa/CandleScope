import "./styles/fonts.js";
import "./index.css";
import { mountStrategyResearchPage } from "./features/strategy-research/strategyResearchBootstrap.js";

void mountStrategyResearchPage({ page: "local" }); // compatibility URL; canonical is /strategy.html
