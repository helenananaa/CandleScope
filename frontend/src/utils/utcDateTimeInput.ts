export function formatUtcDateTimeInput(value: number | null): string {
  if (value === null || !Number.isSafeInteger(value) || value < 0) return "";
  try {
    return new Date(value).toISOString().slice(0, 19);
  } catch {
    return "";
  }
}

export function parseUtcDateTimeInput(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (match === null) return null;
  const [, yearToken, monthToken, dayToken, hourToken, minuteToken, secondToken = "0"] = match;
  const parts = [yearToken, monthToken, dayToken, hourToken, minuteToken, secondToken]
    .map((part) => Number(part));
  const [year, month, day, hour, minute, second] = parts;
  if ([year, month, day, hour, minute, second].some((part) => !Number.isInteger(part))
    || year === undefined || month === undefined || day === undefined
    || hour === undefined || minute === undefined || second === undefined) return null;
  const result = Date.UTC(year, month - 1, day, hour, minute, second);
  if (!Number.isSafeInteger(result) || result < 0) return null;
  const instant = new Date(result);
  if (instant.getUTCFullYear() !== year
    || instant.getUTCMonth() !== month - 1
    || instant.getUTCDate() !== day
    || instant.getUTCHours() !== hour
    || instant.getUTCMinutes() !== minute
    || instant.getUTCSeconds() !== second) return null;
  return result;
}

