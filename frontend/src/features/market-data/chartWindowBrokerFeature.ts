export interface ChartWindowBrokerEnvironment {
  CHART_WINDOW_BROKER_ENABLED?: unknown;
}

function enabled(value: unknown): boolean {
  return value === undefined || value === true || value === 1 || value === "1";
}

export function resolveChartWindowBrokerEnabled(
  environment: ChartWindowBrokerEnvironment = {},
): boolean {
  return enabled(environment.CHART_WINDOW_BROKER_ENABLED);
}

function viteEnvironment(): ChartWindowBrokerEnvironment {
  try {
    return {
      CHART_WINDOW_BROKER_ENABLED: import.meta.env?.VITE_CHART_WINDOW_BROKER_ENABLED,
    };
  } catch {
    return {};
  }
}

/** Shared requests/scheduling default on, independently of chart/window capacity. */
export const CHART_WINDOW_BROKER_ENABLED = resolveChartWindowBrokerEnabled(viteEnvironment());
