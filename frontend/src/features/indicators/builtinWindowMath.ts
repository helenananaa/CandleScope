// Same ordered arithmetic as app.indicator.window_math. Recompute only the
// bounded period, so discarded prices cannot affect a finite-window indicator.
// A window is values[start, end): callers pass one price array and slide the
// range instead of allocating a window per bar.
function compensatedSum(values: readonly number[], start: number, end: number, term: (value: number) => number): number {
  let sum = 0, correction = 0;
  for (let index = start; index < end; index++) {
    const value = term(values[index]!);
    const next = sum + value;
    correction += Math.abs(sum) >= Math.abs(value) ? (sum - next) + value : (value - next) + sum;
    sum = next;
  }
  return sum + correction;
}

export function windowMean(values: readonly number[], start = 0, end = values.length): number {
  const anchor = values[start]!;
  return anchor + compensatedSum(values, start, end, value => value - anchor) / (end - start);
}

export function windowMoments(values: readonly number[], start = 0, end = values.length): [number, number] {
  const mean = windowMean(values, start, end);
  return [mean, compensatedSum(values, start, end, value => (value - mean) * (value - mean))];
}
