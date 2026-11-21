/**
 * The run facade's contracts (ADR-BACKTEST-015 step P2): one status shape for
 * every run family, and one capability matrix in place of the three per-family
 * capability endpoints. Served by `/api/v1/strategy-runs`.
 */
import { readNdjsonUntilTerminal, StrategyRunStreamError } from "../backtestRunStream.js";
import type { RunResultAuthority, RunResultFamily } from "./runResult.js";

export const STRATEGY_RUN_SCHEMA = "candlescope.strategy-run/1";
export const STRATEGY_RUN_CAPABILITIES_SCHEMA = "candlescope.strategy-run-capabilities/1";

/** `follow`: a chart's live HOST run (ADR-BACKTEST-015 P4b), held by chart-cell leases. */
export type StrategyRunFamily = RunResultFamily | "continuous" | "follow";
export type StrategyRunState = "QUEUED" | "RUNNING" | "PAUSED" | "BLOCKED" | "COMPLETED" | "FAILED" | "CANCELLED";
/**
 * A FIXED run has a fixed history; a FOLLOW run keeps a chart's strategy current as bars close
 * and recomputes when they are revised; a FORWARD run keeps going on its own committed account.
 */
export type StrategyRunClockPolicy = "FIXED" | "FOLLOW" | "FORWARD";

const FAMILIES = ["host", "native", "external", "continuous", "follow"] as const satisfies readonly StrategyRunFamily[];
const STATES = ["QUEUED", "RUNNING", "PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"] as const satisfies readonly StrategyRunState[];
const AUTHORITIES = ["HOST", "SCRIPT"] as const satisfies readonly RunResultAuthority[];
const CLOCK_POLICIES = ["FIXED", "FOLLOW", "FORWARD"] as const satisfies readonly StrategyRunClockPolicy[];
const TERMINAL: ReadonlySet<StrategyRunState> = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

export interface StrategyRunError {
  code: string;
  message: string | null;
}

export interface StrategyRunStatus {
  run_id: string;
  family: StrategyRunFamily;
  authority: RunResultAuthority;
  clock_policy: StrategyRunClockPolicy;
  /** Null for a native run: the script fills by its own model. */
  fidelity: string | null;
  language: string | null;
  state: StrategyRunState;
  /** The family's own state, for detail; decisions use `state`. */
  source_state: string;
  terminal: boolean;
  generation: number | null;
  result_available: boolean;
  error: StrategyRunError | null;
  /** The content-addressed version of the run's code (ADR-BACKTEST-015 P3b); null while unknown. */
  version_hash: string | null;
}

export const STRATEGY_VERSION_SCHEMA = "candlescope.strategy-version/1";
const VERSION_HASH = /^sha256:[0-9a-f]{64}$/;

/** The exact code a run executed: language, source, libraries and the runtime that interpreted it. */
export interface StrategyVersion {
  version_hash: string;
  language: string;
  source: string;
  libraries: Record<string, string>;
  runtime: Record<string, unknown>;
  created_at_ms: number;
  /** The names pointing at this version ("named save" names a hash). */
  names: string[];
}

export interface StrategyRunAvailability {
  available: boolean;
  reason: string | null;
}

export interface StrategyRunProfile extends StrategyRunAvailability {
  family: StrategyRunFamily;
  language: string;
  authority: RunResultAuthority;
  clock_policy: StrategyRunClockPolicy;
  /** Null when no host fidelity applies (a native run). */
  fidelities: string[] | null;
  /** Null when the script owns its account. */
  account_models: string[] | null;
  /** Null when any chart interval is accepted. */
  intervals: string[] | null;
  /** True when only fixed-length intervals are accepted (FOLLOW: weeks and months are not followed). */
  fixed_intervals_only: boolean;
  controls: { cancel: boolean };
  /** How a forward run may start; forward profiles only. */
  starts: string[] | null;
}

export interface StrategyRunCapabilities {
  families: Record<StrategyRunFamily, StrategyRunAvailability>;
  profiles: StrategyRunProfile[];
}

export class StrategyRunContractError extends Error {
  constructor(readonly path: string, message: string) {
    super(`strategy-run ${path}: ${message}`);
    this.name = "StrategyRunContractError";
  }
}

type Row = Record<string, unknown>;

function fail(path: string, message: string): never {
  throw new StrategyRunContractError(path, message);
}

function row(value: unknown, path: string): Row {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(path, "must be an object");
  return value as Row;
}

function text(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) fail(path, "must be a non-empty string");
  return value;
}

function optionalText(value: unknown, path: string): string | null {
  return value === null ? null : text(value, path);
}

function flag(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(path, "must be a boolean");
  return value;
}

function choice<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) fail(path, `must be one of ${allowed.join(", ")}`);
  return value as T;
}

function optionalTexts(value: unknown, path: string): string[] | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value)) fail(path, "must be an array or null");
  return value.map((item, index) => text(item, `${path}[${index}]`));
}

function availability(value: unknown, path: string): StrategyRunAvailability {
  const body = row(value, path);
  const available = flag(body.available, `${path}.available`);
  const reason = optionalText(body.reason, `${path}.reason`);
  if (available === (reason !== null)) fail(`${path}.reason`, "is set exactly when unavailable");
  return { available, reason };
}

/** Validate a served `candlescope.strategy-run/1` status. Throws `StrategyRunContractError`. */
export function parseStrategyRunStatus(value: unknown): StrategyRunStatus {
  const body = row(value, "$");
  if (body.schema !== STRATEGY_RUN_SCHEMA) fail("schema", `must be ${STRATEGY_RUN_SCHEMA}`);
  const state = choice(body.state, STATES, "state");
  const terminal = flag(body.terminal, "terminal");
  if (terminal !== TERMINAL.has(state)) fail("terminal", `disagrees with state ${state}`);
  const generation = body.generation;
  if (generation !== null && (typeof generation !== "number" || !Number.isSafeInteger(generation) || generation < 0)) {
    fail("generation", "must be a non-negative integer or null");
  }
  const resultAvailable = flag(body.result_available, "result_available");
  const clockPolicy = choice(body.clock_policy, CLOCK_POLICIES, "clock_policy");
  // A fixed run has a result once it completes; a forward run's committed account is its result.
  if (resultAvailable && clockPolicy === "FIXED" && state !== "COMPLETED") fail("result_available", "only a completed fixed run has a result");
  const error = body.error === null ? null : row(body.error, "error");
  return {
    run_id: text(body.run_id, "run_id"),
    family: choice(body.family, FAMILIES, "family"),
    authority: choice(body.authority, AUTHORITIES, "authority"),
    clock_policy: clockPolicy,
    fidelity: optionalText(body.fidelity, "fidelity"),
    language: optionalText(body.language, "language"),
    state,
    source_state: text(body.source_state, "source_state"),
    terminal,
    generation: generation as number | null,
    result_available: resultAvailable,
    error: error === null ? null : { code: text(error.code, "error.code"), message: optionalText(error.message, "error.message") },
    version_hash: versionHash(body.version_hash, "version_hash"),
  };
}

function versionHash(value: unknown, path: string): string | null {
  // Backends before P3b do not report a version.
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !VERSION_HASH.test(value)) fail(path, "must be a sha256 version hash or null");
  return value;
}

/** Validate a served `candlescope.strategy-version/1`. Throws `StrategyRunContractError`. */
export function parseStrategyVersion(value: unknown): StrategyVersion {
  const body = row(value, "$");
  if (body.schema !== STRATEGY_VERSION_SCHEMA) fail("schema", `must be ${STRATEGY_VERSION_SCHEMA}`);
  const libraries = row(body.libraries, "libraries");
  if (!Array.isArray(body.names)) fail("names", "must be an array");
  const created = body.created_at_ms;
  if (typeof created !== "number" || !Number.isSafeInteger(created) || created < 0) fail("created_at_ms", "must be integer milliseconds");
  return {
    version_hash: versionHash(body.version_hash, "version_hash") ?? fail("version_hash", "is required"),
    language: text(body.language, "language"),
    source: typeof body.source === "string" ? body.source : fail("source", "must be text"),
    libraries: Object.fromEntries(Object.entries(libraries).map(([name, code]) => [name,
      typeof code === "string" ? code : fail(`libraries.${name}`, "must be text")])),
    runtime: row(body.runtime, "runtime"),
    created_at_ms: created,
    names: body.names.map((name, index) => text(name, `names[${index}]`)),
  };
}

/** Validate a served `candlescope.strategy-run-capabilities/1` matrix. Throws `StrategyRunContractError`. */
export function parseStrategyRunCapabilities(value: unknown): StrategyRunCapabilities {
  const body = row(value, "$");
  if (body.schema !== STRATEGY_RUN_CAPABILITIES_SCHEMA) fail("schema", `must be ${STRATEGY_RUN_CAPABILITIES_SCHEMA}`);
  const served = row(body.families, "families");
  const families = Object.fromEntries(FAMILIES.map((family) => [family, availability(served[family], `families.${family}`)])) as
    Record<StrategyRunFamily, StrategyRunAvailability>;
  if (!Array.isArray(body.profiles)) fail("profiles", "must be an array");
  const profiles = body.profiles.map((item, index): StrategyRunProfile => {
    const at = `profiles[${index}]`, profile = row(item, at);
    const controls = row(profile.controls, `${at}.controls`);
    return {
      family: choice(profile.family, FAMILIES, `${at}.family`),
      language: text(profile.language, `${at}.language`),
      authority: choice(profile.authority, AUTHORITIES, `${at}.authority`),
      clock_policy: choice(profile.clock_policy, CLOCK_POLICIES, `${at}.clock_policy`),
      fidelities: optionalTexts(profile.fidelities, `${at}.fidelities`),
      ...availability(profile, at),
      account_models: optionalTexts(profile.account_models, `${at}.account_models`),
      intervals: optionalTexts(profile.intervals, `${at}.intervals`),
      fixed_intervals_only: profile.fixed_intervals_only === undefined ? false
        : flag(profile.fixed_intervals_only, `${at}.fixed_intervals_only`),
      controls: { cancel: flag(controls.cancel, `${at}.controls.cancel`) },
      starts: optionalTexts(profile.starts, `${at}.starts`),
    };
  });
  return { families, profiles };
}

/** The profile that would run `language` in `family`, or null when the backend does not offer it. */
export function strategyRunProfile(capabilities: StrategyRunCapabilities, family: StrategyRunFamily,
  language: string): StrategyRunProfile | null {
  return capabilities.profiles.find((profile) => profile.family === family && profile.language === language) ?? null;
}

export const STRATEGY_RUN_STREAM_SCHEMA = "candlescope.strategy-run-stream/1";

/** The latest checkpoint of a host run; null for native runs and finished runs. */
export interface StrategyRunProgress {
  sequence: number;
  created_at_ms: number;
}

/**
 * Consume one `candlescope.strategy-run-stream/1` body until the run's terminal status.
 * Every status must be for `runId` and keep its generation. A server error frame or
 * EOF before a terminal status throws `StrategyRunStreamError`; the run itself is untouched.
 */
export function readStrategyRunStatusStream(input: {
  body: ReadableStream<Uint8Array>;
  runId: string;
  signal?: AbortSignal;
  onStatus?: (status: StrategyRunStatus, progress: StrategyRunProgress | null) => void;
  maxFrameCharacters?: number;
}): Promise<StrategyRunStatus> {
  let generation: number | null | undefined;
  const parse = (line: string): StrategyRunStatus | null => {
    let raw: unknown;
    try { raw = JSON.parse(line); } catch { fail("frame", "must be JSON"); }
    const frame = row(raw, "frame");
    if (frame.schema !== STRATEGY_RUN_STREAM_SCHEMA) fail("frame.schema", `must be ${STRATEGY_RUN_STREAM_SCHEMA}`);
    if (frame.type === "heartbeat") {
      if (frame.terminal !== false) fail("frame.terminal", "a heartbeat is never terminal");
      return null;
    }
    if (frame.type === "error") {
      const error = row(frame.error, "frame.error");
      if (frame.terminal !== true || frame.run_id !== input.runId) fail("frame", "an error ends this run's stream");
      throw new StrategyRunStreamError(text(error.code, "frame.error.code"), text(error.message, "frame.error.message"));
    }
    if (frame.type !== "status") fail("frame.type", "must be status, heartbeat or error");
    const status = parseStrategyRunStatus(frame.status);
    if (status.run_id !== input.runId) fail("frame.status.run_id", `asked for ${input.runId}, served ${status.run_id}`);
    if (frame.terminal !== status.terminal) fail("frame.terminal", "disagrees with the status");
    if (generation !== undefined && status.generation !== generation) fail("frame.status.generation", "changed within one stream");
    generation = status.generation;
    let progress: StrategyRunProgress | null = null;
    if (frame.progress !== null) {
      const value = row(frame.progress, "frame.progress");
      if (!Number.isSafeInteger(value.sequence) || (value.sequence as number) < 0
        || !Number.isSafeInteger(value.created_at_ms)) fail("frame.progress", "must hold an integer sequence and time");
      progress = { sequence: value.sequence as number, created_at_ms: value.created_at_ms as number };
    }
    input.onStatus?.(status, progress);
    return status.terminal ? status : null;
  };
  return readNdjsonUntilTerminal({ body: input.body, parse, ...(input.signal ? { signal: input.signal } : {}),
    ...(input.maxFrameCharacters ? { maxFrameCharacters: input.maxFrameCharacters } : {}) });
}
