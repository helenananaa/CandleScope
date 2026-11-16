// Replay and ordinary charts share the validated builtin mathematics.
export { BuiltinIncrementalState as ReplayBuiltinState, roundBuiltinValue,
  createIncrementalBuiltinCompute as createReplayBuiltinCompute } from "../indicators/builtinIncrementalCompute.js";
export type { BuiltinIncrementalSeed as ReplayBuiltinSeed } from "../indicators/builtinIncrementalCompute.js";
