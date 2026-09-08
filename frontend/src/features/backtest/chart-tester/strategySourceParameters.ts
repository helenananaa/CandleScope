export interface StrategySourceParameter { line: number; label: string; value: string; prefix: string; suffix: string; original: string; }

/** Edit only supported whole-line literals; arbitrary expressions remain in the code editor. */
export function strategySourceParameters(source: string): StrategySourceParameter[] {
  return source.split("\n").flatMap((original, line) => {
    const match = original.match(/^(\s*([A-Za-z_]\w*)\s*=\s*(sma|rsi|highest|lowest)\(\s*(?:close|high|low|open|volume)\s*,\s*)(\d+)(\s*\)\s*)$/);
    if (match) return [{ line, label: `${match[2]} · ${match[3]}`, prefix: match[1]!, value: match[4]!, suffix: match[5]!, original }];
    const scalar = original.match(/^(\s*([A-Za-z_]\w*)\s*=\s*)(-?\d+(?:\.\d+)?)(\s*)$/);
    if (scalar) return [{ line, label: scalar[2]!, prefix: scalar[1]!, value: scalar[3]!, suffix: scalar[4]!, original }];
    const target = original.match(/^(\s*target_position\(\s*)(-?\d+(?:\.\d+)?)(\s*\)\s*)$/);
    if (target) return [{ line, label: "target_position", prefix: target[1]!, value: target[2]!, suffix: target[3]!, original }];
    const threshold = original.match(/^(\s*(?:else\s+)?if\s+([A-Za-z_]\w*\s*[<>]=?)\s*)(-?\d+(?:\.\d+)?)(\s*)$/);
    return threshold ? [{ line, label: threshold[2]!, prefix: threshold[1]!, value: threshold[3]!, suffix: threshold[4]!, original }] : [];
  });
}

export function replaceStrategySourceParameter(source: string, parameter: StrategySourceParameter, value: string): string {
  if (!/^-?\d+(?:\.\d+)?$/.test(value) || !Number.isFinite(Number(value))) return source;
  if (/=\s*(sma|rsi|highest|lowest)\(/.test(parameter.prefix) && (!Number.isInteger(Number(value)) || Number(value) < 1)) return source;
  const lines = source.split("\n");
  if (lines[parameter.line] !== parameter.original) return source;
  lines[parameter.line] = `${parameter.prefix}${value}${parameter.suffix}`;
  return lines.join("\n");
}
