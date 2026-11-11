import type { IndicatorCalculationPosition, IndicatorCalculationReference, IndicatorPayloadEnvelope,
  IndicatorRangeRequest } from "./indicatorTypes.js";

export interface ChartCalculationApi {
  open(input: IndicatorRangeRequest): Promise<IndicatorPayloadEnvelope>;
  read(input: { calculation: IndicatorCalculationReference; clientId: string; start: number; end: number;
    rebuild?: boolean }): Promise<IndicatorPayloadEnvelope>;
  close(domainId: string): Promise<void>;
}

interface Entry {
  key: string;
  clientId: string;
  retired: boolean;
  position: IndicatorCalculationPosition | null;
  displayed: IndicatorCalculationPosition | null;
  opening: Promise<IndicatorPayloadEnvelope> | null;
  closing: Promise<void> | null;
  pending: number;
}

function reference(position: IndicatorCalculationPosition): IndicatorCalculationReference {
  return { schemaVersion: 1, domainId: position.domainId, generation: position.generation, sequence: position.sequence };
}

function notOlder(next: IndicatorCalculationPosition, old: IndicatorCalculationPosition): boolean {
  return next.domainId === old.domainId && next.origin === old.origin
    && next.generation >= old.generation && next.sequence >= old.sequence;
}

function stale(): DOMException { return new DOMException("Chart calculation changed", "AbortError"); }

/** Chart-owned handles only. History/output stay in the existing server runtime and renderer.
 * An abandoned open is still observed and released. Failed cleanup holds the bounded slot.
 */
export class ChartCalculationSessions {
  private context = "";
  private readonly entries = new Map<string, Entry>();
  private readonly retired = new Set<Entry>();
  constructor(private readonly api: ChartCalculationApi, private readonly changed: () => void,
    private readonly capacity = 8) {}

  setContext(context: string): void {
    if (context === this.context) return;
    this.context = context;
    for (const entry of this.entries.values()) this.retire(entry);
    this.entries.clear();
  }

  reconcile(keys: ReadonlyMap<string, string>): void {
    for (const [id, entry] of this.entries) {
      if (keys.get(id) === entry.key) continue;
      this.entries.delete(id);
      this.retire(entry);
    }
  }

  private retire(entry: Entry): void {
    entry.retired = true;
    this.retired.add(entry);
    void this.close(entry).catch(() => { /* Retain ownership/capacity for retry. */ });
  }

  private close(entry: Entry): Promise<void> {
    if (entry.closing) return entry.closing;
    const operation = (async () => {
      if (entry.opening) await entry.opening.catch(() => undefined);
      if (entry.position) await this.api.close(entry.position.domainId);
      this.retired.delete(entry);
    })();
    entry.closing = operation;
    void operation.finally(() => { if (entry.closing === operation) entry.closing = null; }).catch(() => undefined);
    return operation;
  }

  getReference(clientId: string, key: string): IndicatorCalculationReference | null {
    const entry = this.entries.get(clientId);
    return entry?.key === key && entry.position && !entry.retired ? reference(entry.position) : null;
  }

  /** ACKs update request CAS only. They never certify or replace displayed output. */
  acknowledge(clientId: string, key: string, position: IndicatorCalculationPosition | undefined): boolean {
    const entry = this.entries.get(clientId);
    if (!entry || entry.key !== key || !entry.position || !position || !notOlder(position,entry.position)) return false;
    entry.position = position;
    return true;
  }

  admit(clientId: string, key: string, payload: IndicatorPayloadEnvelope): "reject" | "same" | "reset" {
    const entry = this.entries.get(clientId), position = payload.calculation;
    if (!entry || entry.key !== key || entry.retired || !entry.position || !position || payload.ok === false
        || !notOlder(position,entry.position) || (entry.displayed && !notOlder(position,entry.displayed))) return "reject";
    const reset = !entry.displayed || position.generation !== entry.displayed.generation;
    if (reset && payload.type !== "indicator.snapshot") return "reject";
    entry.position = entry.displayed = position;
    return reset ? "reset" : "same";
  }

  async range(context: string, key: string, input: IndicatorRangeRequest, origin: number, recover = 1): Promise<IndicatorPayloadEnvelope> {
    if (this.context !== context || input.signal?.aborted) throw stale();
    let entry = this.entries.get(input.clientId);
    if (entry && (entry.key !== key || (entry.position && input.start < entry.position.origin))) {
      this.entries.delete(input.clientId);this.retire(entry);entry = undefined;
    }
    if (!entry) {
      // Cleanup completes before admission; failure keeps its resource slot.
      await Promise.all([...this.retired].map(item => this.close(item)));
      if (this.context !== context || input.signal?.aborted) throw stale();
      // A concurrent request may have finished the same cleanup wait.
      entry = this.entries.get(input.clientId);
      if (!entry) {
        if (this.entries.size+this.retired.size >= this.capacity) throw new Error("Chart calculation capacity reached");
        entry = { key,clientId:input.clientId,retired:false,position:null,displayed:null,opening:null,closing:null,pending:0 };
        this.entries.set(input.clientId,entry);
        const owned = entry;
        owned.opening = this.api.open({ ...input,start:Math.min(input.start,origin) }).then(payload => {
          if (payload.ok !== false && payload.calculation) {
            owned.position = payload.calculation;
            if (!owned.retired) this.changed();
          }
          return payload;
        });
      }
    }
    const owned = entry;
    if (owned.key !== key) throw stale();
    if (owned.pending >= 8) throw new Error("Chart calculation busy");
    owned.pending++;
    const current = () => this.context === context && this.entries.get(input.clientId) === owned && !owned.retired;
    try {
      const opening = owned.opening;
      const opened = opening ? await opening : null;
      if (owned.opening === opening) owned.opening = null;
      if (!current() || input.signal?.aborted) throw stale();
      if (opened?.ok === false || !owned.position) {
        this.entries.delete(input.clientId);this.retire(owned);
        if (!opened) throw stale();
        return opened;
      }
      if (input.start < owned.position.origin) {
        this.entries.delete(input.clientId);this.retire(owned);
        if (recover > 0) return await this.range(context,key,input,origin,recover-1);
        throw new Error("Chart calculation origin unavailable");
      }
      // Always request a complete current projection. A CAS recovery may have
      // crossed generations; range-clipped data cannot prove a full replacement.
      let rebuild = false;
      for (let attempt=0;attempt<2;attempt++) {
        const result = await this.api.read({ calculation:reference(owned.position),clientId:input.clientId,
          start:Math.max(owned.position.origin,input.start),end:Math.max(input.end,owned.position.observedThrough),
          rebuild });
        if (!current() || input.signal?.aborted) throw stale();
        if (result.ok !== false) {
          if (!result.calculation || !notOlder(result.calculation,owned.position)) throw stale();
          // Keep the request cursor current even if React aborts before apply.
          owned.position = result.calculation;
          return result;
        }
        if (result.code === "INDICATOR_CALCULATION_CHANGED" && result.calculation
            && notOlder(result.calculation,owned.position)) {
          owned.position = result.calculation;
          continue;
        }
        if (["INDICATOR_CALCULATION_OUTPUT_LOST","INDICATOR_CALCULATION_REBUILD_REQUIRED"].includes(result.code || "")) {
          rebuild = true;continue;
        }
        if (result.code === "INDICATOR_CALCULATION_NOT_FOUND" && recover > 0) {
          this.entries.delete(input.clientId);this.retire(owned);
          return await this.range(context,key,input,origin,recover-1);
        }
        return result;
      }
      throw stale();
    } catch (error) {
      if (current() && !owned.position) {
        this.entries.delete(input.clientId);this.retire(owned);
      }
      throw error;
    } finally { owned.pending--; }
  }

  async dispose(): Promise<void> {
    this.setContext("");
    await Promise.all([...this.retired].map(entry => this.close(entry)));
  }
}
