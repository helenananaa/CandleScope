/** Engine locations are 1-based; only expose a jump for a valid source line. */
export function diagnosticLocation(text: string, source: string): { line: number; column: number; offset: number } | null {
  const match = /(?:Error|Warning):(\d+):(\d+):|\(line (\d+):(\d+)\)/.exec(text);
  if (!match) return null;
  const line = Number(match[1] ?? match[3]), column = Number(match[2] ?? match[4]);
  const lines = source.split("\n");
  if (line < 1 || line > lines.length || column < 1) return null;
  return { line, column, offset: lines.slice(0, line - 1).reduce((n, value) => n + value.length + 1, 0) + Math.min(column - 1, lines[line - 1]!.length) };
}
