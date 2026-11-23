import type { ContinuousRun } from "../backtest/continuous/continuousTypes.js";
import { PRACTICE_ACCOUNT_RULES } from "../backtest/continuous/continuousAccountRules.js";

/**
 * Forward runs on the accounts page (ADR-BACKTEST-015 P6e): each is listed beside the practice
 * accounts with its own ledger, read-only. Their options carry a prefix practice account ids never
 * have, so one select holds both.
 */
export const FORWARD_OPTION_PREFIX = "forward-run:";
const SELECTION = "candlescope.trading-accounts.forward.v1";

export interface ForwardAccount {
  runId: string;
  option: string;
  label: string;
  /** On the practice account model; otherwise the strategy test's model. */
  practice: boolean;
}

function field(run: ContinuousRun, key: string): string {
  const market = run.market !== null && typeof run.market === "object" ? run.market as Record<string, unknown> : {};
  return typeof market[key] === "string" ? market[key] : "";
}

/** One entry per run, named by its market; runs on the same market are told apart by their id. */
export function forwardAccounts(runs: readonly ContinuousRun[]): ForwardAccount[] {
  const named = runs.map((run) => {
    const symbol = field(run, "symbol"), interval = field(run, "interval");
    return { run, name: symbol ? [symbol, interval].filter(Boolean).join(" · ") : run.id };
  });
  const counts = new Map<string, number>();
  for (const { name } of named) counts.set(name, (counts.get(name) ?? 0) + 1);
  return named.map(({ run, name }) => ({
    runId: run.id,
    option: FORWARD_OPTION_PREFIX + run.id,
    label: (counts.get(name) ?? 0) > 1 && name !== run.id ? `${name} · ${run.id.slice(-8)}` : name,
    practice: run.account_rules === PRACTICE_ACCOUNT_RULES,
  }));
}

export function forwardRunFromOption(option: string): string | null {
  return option.startsWith(FORWARD_OPTION_PREFIX) ? option.slice(FORWARD_OPTION_PREFIX.length) || null : null;
}

export function rememberedForwardRun(): string | null {
  try {
    const value = localStorage.getItem(SELECTION);
    return value && value.length <= 128 ? value : null;
  } catch { return null; }
}

export function rememberForwardRun(runId: string | null): void {
  try {
    if (runId) localStorage.setItem(SELECTION, runId);
    else localStorage.removeItem(SELECTION);
  } catch { /* The choice is a convenience; the page works without storage. */ }
}
