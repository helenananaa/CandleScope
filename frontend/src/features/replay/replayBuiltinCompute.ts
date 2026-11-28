// Replay and live charts share the validated builtin mathematics. Replay keeps
// the strict defaults: no sparse seeds, and only the revealed rows it is given.
export { BuiltinIncrementalState as ReplayBuiltinState, roundBuiltinValue,
  createIncrementalBuiltinCompute as createReplayBuiltinCompute } from "../indicators/builtinIncrementalCompute.js";
export type { BuiltinIncrementalSeed as ReplayBuiltinSeed } from "../indicators/builtinIncrementalCompute.js";
