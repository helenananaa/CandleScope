import type { CommandSchema } from "./commandSchema.js";
import { empty, object, optional, text, record } from "./commandSchema.js";
import type { ControlRequest, ControlResult } from "./controlModel.js";

export interface AppCommand {
  name: string; description: string; inputSchema: Record<string, unknown>; readOnly: boolean;
  interrupt: boolean; available(): boolean; validate(args: unknown): unknown; execute(args: unknown): unknown | Promise<unknown>;
  requiredScope?: string;
}
export function command<T>(name: string, description: string, input: CommandSchema<T>, execute: (args: T) => unknown | Promise<unknown>,
  options: { readOnly?: boolean; available?: () => boolean; interrupt?: boolean; requiredScope?: string } = {}): AppCommand {
  return { name, description, inputSchema: input.jsonSchema, readOnly: options.readOnly ?? false,
    interrupt: options.interrupt ?? false, ...(options.requiredScope ? { requiredScope: options.requiredScope } : {}),
    available: () => (!options.requiredScope || (typeof window !== "undefined" && window.candlescopeDesktop?.controlScopes?.includes(options.requiredScope) === true)) && (options.available?.() ?? true), validate: input.parse, execute: (args) => execute(args as T) };
}
export interface ControlCommandGroup {
  id: string; title: string; commands: readonly AppCommand[];
  context(): unknown; snapshot(): unknown;
}
interface Registration { owner: symbol; group: ControlCommandGroup; fingerprint: string; token: string }
const queryInput = object({ windowId: text(96), groupId: text(160), command: text(96), args: optional(record) });
const executeInput = object({ windowId: text(96), groupId: text(160), command: text(96), args: optional(record), requestId: text(96), expectedContext: text(160) });
const referenceIds = new WeakMap<object, number>();
let referenceSequence = 0;
/** Track replacement of large, immutable UI input objects without serializing their contents on every discovery. */
export function contextReference(value: unknown): unknown {
  if (!value || typeof value !== "object") return value;
  let id = referenceIds.get(value);
  if (id === undefined) { id = ++referenceSequence; referenceIds.set(value, id); }
  return `reference:${id}`;
}

/** One registry per renderer. Every entry points to an explicit existing UI/domain action. */
export class AppCommandRegistry {
  private readonly groups = new Map<string, Registration>();
  private sequence = 0;
  private readonly epoch = Math.random().toString(36).slice(2);
  private mutationPending = false;
  register(group: ControlCommandGroup): () => void {
    if (this.groups.has(group.id)) throw new Error(`Duplicate control group: ${group.id}`);
    const entry = { owner: Symbol(group.id), group, fingerprint: "", token: "" };
    this.groups.set(group.id, entry);
    return () => { if (this.groups.get(group.id)?.owner === entry.owner) this.groups.delete(group.id); };
  }
  private token(entry: Registration): string {
    const fingerprint = JSON.stringify(entry.group.context());
    if (!entry.token || fingerprint !== entry.fingerprint) {
      entry.fingerprint = fingerprint; entry.token = `${this.epoch}:${++this.sequence}`;
    }
    return entry.token;
  }
  list() {
    return [...this.groups.values()].map((entry) => ({ id: entry.group.id, title: entry.group.title, context: entry.group.context(),
      contextToken: this.token(entry), commands: [{ name: "inspect", description: "Read the current UI/domain state.", inputSchema: empty.jsonSchema, readOnly: true, available: true },
        ...entry.group.commands.map((item) => ({ name: item.name, description: item.description, inputSchema: item.inputSchema, readOnly: item.readOnly, requiredScope: item.requiredScope, available: item.available() }))] }));
  }
  async execute(request: ControlRequest, windowId: string): Promise<ControlResult> {
    const result = await this.executeDomain(request, windowId);
    try {
      // UI state can include reactive proxies. Cross the JSON-only protocol boundary
      // before Electron's structured clone, and reject non-data fields explicitly.
      return JSON.parse(JSON.stringify(result, (key, value: unknown) => {
        if (typeof value === "function" || typeof value === "symbol" || typeof value === "bigint" || value instanceof Map || value instanceof Set) throw new Error(`NON_JSON_RESULT:${key}`);
        return value;
      })) as ControlResult;
    } catch (error) {
      const message = error instanceof Error ? error.message : "NON_JSON_RESULT";
      return result.state === "applied" ? { state: "applied", code: "RESULT_UNAVAILABLE", readiness: "unverified", message }
        : { state: "failed", code: "RESULT_UNAVAILABLE", message };
    }
  }
  private async executeDomain(request: ControlRequest, windowId: string): Promise<ControlResult> {
    let started = false;
    let ownsMutation = false;
    try {
      if (request.method === "app.commands") {
        if (object({ windowId: text(96) }).parse(request.params).windowId !== windowId) throw new Error("TARGET_MISMATCH");
        return { state: "ready", groups: this.list() };
      }
      const query = request.method === "app.query";
      if (!query && request.method !== "app.execute") return { state: "failed", code: "UNKNOWN_METHOD" };
      const input = query ? queryInput.parse(request.params) : executeInput.parse(request.params);
      if (input.windowId !== windowId || (!query && (input as ReturnType<typeof executeInput.parse>).requestId !== request.id)) throw new Error("TARGET_MISMATCH");
      const entry = this.groups.get(input.groupId);
      if (!entry) throw new Error("GROUP_UNAVAILABLE");
      if (input.command === "inspect") {
        empty.parse(input.args ?? {});
        if (!query) throw new Error("READ_ONLY_COMMAND");
        return { state: "ready", contextToken: this.token(entry), snapshot: entry.group.snapshot() };
      }
      const selected = entry.group.commands.find((item) => item.name === input.command);
      if (!selected) throw new Error("COMMAND_UNAVAILABLE");
      if (query && !selected.readOnly) throw new Error("READ_ONLY_REQUIRED");
      if (!query && selected.readOnly) throw new Error("READ_ONLY_COMMAND");
      if (!selected.available()) throw new Error("COMMAND_DISABLED");
      if (!query && this.token(entry) !== (input as ReturnType<typeof executeInput.parse>).expectedContext) throw new Error("CONTEXT_CONFLICT");
      const args = selected.validate(input.args ?? {});
      if (!query && !selected.interrupt) {
        if (this.mutationPending) throw new Error("CONTROL_BUSY");
        this.mutationPending = true; ownsMutation = true;
      }
      started = !query;
      const output = await selected.execute(args);
      // React actions publish their new runtime in the next commit. This is an acknowledgement, never a generic readiness claim.
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      if (this.groups.get(input.groupId)?.owner !== entry.owner) return { state: "applied", code: "TARGET_UNMOUNTED", readiness: "unverified", output: output ?? null };
      return { state: query ? "ready" : "applied", readiness: query ? "observed" : "command-acknowledged",
        contextToken: this.token(entry), output: output ?? null, snapshot: entry.group.snapshot() };
    } catch (error) {
      return { state: "failed", code: started ? "OUTCOME_UNKNOWN" : "COMMAND_REJECTED",
        message: error instanceof Error ? error.message : "COMMAND_ERROR", readiness: started ? "unverified" : "not-applied" };
    } finally { if (ownsMutation) this.mutationPending = false; }
  }
}
export const appCommandRegistry = new AppCommandRegistry();
