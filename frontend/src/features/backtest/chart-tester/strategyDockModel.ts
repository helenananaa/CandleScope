export function strategyDockHeight(requested: number, available: number, maximized = false): number {
  const space = Math.max(36, Number.isFinite(available) ? available : 600);
  if (maximized) return space;
  const maximum = Math.max(36, space - Math.min(240, space * 0.55));
  const minimum = Math.min(260, maximum);
  return Math.round(Math.max(minimum, Math.min(maximum, Number.isFinite(requested) ? requested : 280)));
}
