/** Source preparation may advance inside one display bucket before math can. */
type SourceProgress = {
  windowStart: number; windowStop: number; phase: "context" | "trades";
  prepared: number; target: number;
};

/** Count the completed mathematical prefix, never divide absolute timestamps
 * or compare a trade sequence with milliseconds. Source work inside the next
 * bucket is intentionally indeterminate until that bucket is complete. */
export function replayIndicatorPreparationFraction(origin: unknown, prepared: unknown, target: unknown): number | null {
  if (![origin, prepared, target].every(Number.isSafeInteger)) return null;
  const start = Number(origin), before = Number(prepared), end = Number(target);
  return start >= 0 && start <= before && before < end ? (before - start) / (end - start) : null;
}

export class ReplayIndicatorProgress {
  private before = -1;
  private source: SourceProgress | null = null;

  advance(body: Record<string, unknown>, targetBefore: number, sourceSequence?: number): {
    phase: "history" | "prefix"; prepared: number; target: number;
  } {
    const next = body.prepared_before_ms, target = body.target_before_ms;
    if (typeof next !== "number" || typeof target !== "number" || !Number.isSafeInteger(next)
      || !Number.isSafeInteger(target) || next < 0 || next >= target || target !== targetBefore || next < this.before) {
      throw new TypeError("canonical indicator preparation did not progress");
    }
    if (body.source_preparation === undefined) {
      if (next <= this.before) throw new TypeError("canonical indicator preparation did not progress");
      this.before = next; this.source = null;
      return { phase: "prefix", prepared: next, target };
    }
    const raw = body.source_preparation;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError("invalid indicator source progress");
    const value = raw as Record<string, unknown>;
    const fields = ["window_start_ms", "window_stop_ms", "phase", "prepared", "target", "source_sequence"];
    if (Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key))
      || [value.window_start_ms, value.window_stop_ms, value.prepared, value.target, value.source_sequence]
        .some(item => !Number.isSafeInteger(item) || Number(item) < 0)
      || value.window_start_ms !== next || Number(value.window_stop_ms) <= next || Number(value.window_stop_ms) > target
      || Number(value.prepared) >= Number(value.target) || sourceSequence === undefined || value.source_sequence !== sourceSequence
      || (value.phase !== "context" && value.phase !== "trades")
      || (value.phase === "trades" && Number(value.target) > sourceSequence)
      || (value.phase === "context" && (Number(value.prepared) < next || Number(value.target) > Number(value.window_stop_ms)))) {
      throw new TypeError("invalid indicator source progress");
    }
    const progress: SourceProgress = { windowStart: next, windowStop: Number(value.window_stop_ms),
      phase: value.phase, prepared: Number(value.prepared), target: Number(value.target) };
    if (next === this.before && this.source !== null) {
      const previous = this.source;
      if (previous.windowStop !== progress.windowStop || (previous.phase === "trades" && progress.phase === "context")
        || (previous.phase === progress.phase && (previous.target !== progress.target || progress.prepared <= previous.prepared))) {
        throw new TypeError("canonical indicator source preparation did not progress");
      }
    }
    this.before = next; this.source = progress;
    return { phase: "history", prepared: progress.prepared, target: progress.target };
  }
}
