// Same ordered arithmetic as app.indicator.window_math. Recompute only the
// bounded period, so discarded prices cannot affect a finite-window indicator.
function compensatedSum(values: readonly number[]): number {
  let sum = 0, correction = 0;
  for (const value of values) {
    const next = sum + value;
    correction += Math.abs(sum) >= Math.abs(value) ? (sum - next) + value : (value - next) + sum;
    sum = next;
  }
  return sum + correction;
}

export function replayWindowMean(values: readonly number[]): number {
  const anchor = values[0]!;
  return anchor + compensatedSum(values.map(value => value - anchor)) / values.length;
}

export function replayWindowMoments(values: readonly number[]): [number, number] {
  const mean = replayWindowMean(values);
  return [mean, compensatedSum(values.map(value => (value - mean) * (value - mean)))];
}
