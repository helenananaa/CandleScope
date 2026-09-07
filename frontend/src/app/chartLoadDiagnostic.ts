export function buildChartLoadDiagnostic(error: string, context?: { symbol: string; interval: string }): string {
  return [
    "CandleScope — chart data load failure",
    ...(context ? [`Symbol: ${context.symbol}`, `Interval: ${context.interval}`] : []),
    "Error:",
    error,
  ].join("\n");
}

export async function copyChartLoadDiagnostic(text: string, writeText: (text: string) => Promise<void>): Promise<boolean> {
  try {
    await writeText(text);
    return true;
  } catch {
    return false;
  }
}
