import {
  projectResearchCapabilities,
} from "../research-data/researchDataSourceModel.js";
import type { LocaleId } from "../../i18n/index.js";
import type {
  ResearchCapabilitySummaryV1,
  ResearchRuntimeMode,
  ResearchSourceKind,
} from "../research-data/researchDataTypes.js";
import {
  EMPTY_STRATEGY_RESEARCH_STATE,
  loadStrategyResearchWorkspace,
  persistStrategyResearchWorkspace,
  strategyResearchReducer,
  type StrategyResearchAction,
  type StrategyResearchState,
} from "./strategyResearchState.js";

export class StrategyResearchRuntime {
  state: StrategyResearchState;
  runtimeMode: ResearchRuntimeMode;

  constructor(options: {
    runtimeMode?: ResearchRuntimeMode;
    restoreWorkspace?: boolean;
  } = {}) {
    this.runtimeMode = options.runtimeMode ?? "LIVE";
    this.state = options.restoreWorkspace === false
      ? EMPTY_STRATEGY_RESEARCH_STATE
      : loadStrategyResearchWorkspace();
  }

  dispatch(action: StrategyResearchAction): StrategyResearchState {
    this.state = strategyResearchReducer(this.state, action);
    persistStrategyResearchWorkspace(this.state);
    return this.state;
  }

  capabilitiesFor(kind: ResearchSourceKind, locale?: LocaleId): ResearchCapabilitySummaryV1 {
    return projectResearchCapabilities({
      sourceKind: kind,
      runtimeMode: this.runtimeMode,
      ...(locale ? { locale } : {}),
    });
  }

  currentChartRunnable(): boolean {
    return this.runtimeMode === "LIVE" && this.state.source.source?.kind === "CURRENT_CHART";
  }
}
