import type { PythonBarExecutionModel, StrategyExecutionOverrides, StrategyInitializationSettings } from "../../../shared/strategyRunSettings.js";
import type { ContinuousRunReference } from "./continuousRunReference.js";

/** The run setting for the practice account model, shared with practice accounts (ADR-BACKTEST-015 P6e). */
export const PRACTICE_ACCOUNT_RULES = "PRACTICE_V1";

/**
 * How a forward run matches. A new run trades on the practice account model; a run continued from a
 * research result keeps that result's model; a saved run keeps the model it was created with
 * (references from before the practice model carry no leverage: the worst-case model).
 */
export function forwardExecutionModel(initialization: StrategyInitializationSettings | undefined,
  reference: Pick<ContinuousRunReference, "settings"> | null): PythonBarExecutionModel {
  if (initialization) return initialization.executionModel ?? "V2";
  if (reference) return reference.settings.leverage === undefined ? "LEGACY" : "PRACTICE";
  return "PRACTICE";
}

/** A practice account's default leverage on futures; spot is fully paid. */
export function defaultForwardLeverage(marketType: string, initialExecution?: StrategyExecutionOverrides): string {
  return initialExecution?.leverage ?? (marketType === "spot" ? "1" : "10");
}

/** The leverage a forward run's account uses: chosen on the practice model for futures, otherwise 1. */
export function forwardAccountLeverage(model: PythonBarExecutionModel, marketType: string, leverage: string): string {
  return model === "PRACTICE" && marketType !== "spot" ? leverage : "1";
}

export function validForwardLeverage(leverage: string): boolean {
  return /^\d+(?:\.\d+)?$/.test(leverage) && Number(leverage) >= 1 && Number(leverage) <= 125;
}

/** The execution fields the model adds to a forward run's request. */
export function forwardModelExecution(model: PythonBarExecutionModel, leverage: string): Record<string, string> {
  if (model === "V2") return { execution_model_revision: "EXECUTION_REALISM_V2", participation_rate: "0.1", order_end_policy: "CANCEL_AT_END" };
  if (model === "PRACTICE") return { account_rules: PRACTICE_ACCOUNT_RULES, leverage };
  return {};
}
