/** Shared lifecycle for window and desktop modules. The backend owns identities. */
export class UnifiedEntryLifecycle {
  constructor({ load, createContext, report, timeoutMs = 10000, changed = () => {} }) {
    Object.assign(this, { load, createContext, report, timeoutMs, changed });
    this.running = new Map();
    this.errors = {};
    this.plan = { entries: [], sessionId: "", hostInstance: "" };
    this.restartRequired = false;
    this.pump = null;
  }

  current(item) {
    return !this.plan.safeMode && this.plan.entries.some((next) => next.instanceId === item.instanceId
      && next.pluginId === item.pluginId && next.identity.generation === item.identity.generation
      && next.identity.packageSha256 === item.identity.packageSha256);
  }

  async bounded(work) {
    let timer;
    try {
      return await Promise.race([work, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Plugin operation timed out; restart required")), this.timeoutMs);
      })]);
    } finally { clearTimeout(timer); }
  }

  async status(plan, item, state, error) {
    try { await this.report(plan, item, state, error); }
    catch (failure) {
      if (this.current(item)) this.errors.runtime = String(failure);
      if (state === "running") throw failure;
    }
  }

  async stopRun(run) {
    run.active = false;
    this.running.delete(run.item.instanceId);
    if (run.item.entry.kind !== "sandbox-view") this.restartRequired = true;
    try { await this.bounded(Promise.resolve(run.owned.dispose())); }
    catch (error) { this.errors[run.item.pluginId] = String(error); }
    await this.status(run.plan, run.item, run.item.entry.kind === "sandbox-view" ? "stopped" : "pending-restart");
  }

  reconcile(plan) {
    this.plan = plan;
    // Guards change immediately, before a slow activation/cleanup settles.
    for (const run of this.running.values()) if (!this.current(run.item)) run.active = false;
    if (!this.pump) {
      this.pump = (async () => {
        let applied;
        do {
          applied = this.plan;
          await this.apply(applied);
        } while (applied !== this.plan);
      })().finally(() => { this.pump = null; this.changed(); });
    }
    return this.pump;
  }

  async apply(plan) {
    for (const run of [...this.running.values()].reverse()) {
      if (!this.current(run.item)) await this.stopRun(run);
    }
    const failed = new Set();
    for (const item of plan.safeMode ? [] : plan.entries) {
      if (!this.current(item) || this.running.has(item.instanceId)) continue;
      if (Object.keys(item.manifest.dependencies ?? {}).some((id) => failed.has(id))) {
        failed.add(item.pluginId);
        await this.status(plan, item, "failed", "Dependency failed");
        continue;
      }
      if (this.restartRequired && item.entry.kind !== "sandbox-view") {
        await this.status(plan, item, "pending-restart");
        continue;
      }
      if (failed.has(item.pluginId)) continue;
      const run = { item, plan, active: true, owned: null };
      const guard = () => {
        if (!run.active || !this.current(item)) throw new Error("Plugin activation was revoked");
      };
      const owned = this.createContext(item, guard);
      run.owned = owned;
      try {
        const module = await this.bounded(Promise.resolve(this.load(item)));
        guard();
        if (typeof module.activate !== "function") throw new Error("Entry must export activate(context)");
        if (typeof module.deactivate === "function") owned.context.track(module.deactivate);
        // Register a late returned cleanup even when the timeout already revoked this context.
        const activation = Promise.resolve(module.activate(owned.context)).then(async (cleanup) => {
          if (typeof cleanup !== "function") return;
          if (!run.active || !this.current(item)) {
            try { await this.bounded(Promise.resolve(cleanup())); }
            catch (error) { this.errors[item.pluginId] = String(error); this.changed(); throw error; }
          } else owned.context.track(cleanup);
        });
        await this.bounded(activation);
        guard();
        await this.status(plan, item, "running");
        guard();
        this.running.set(item.instanceId, run);
      } catch (error) {
        run.active = false;
        const stale = !this.current(item);
        if (!stale) { failed.add(item.pluginId); this.errors[item.pluginId] = String(error); }
        this.restartRequired ||= item.entry.kind !== "sandbox-view";
        try { await this.bounded(Promise.resolve(owned.dispose())); } catch { /* error remains visible */ }
        for (const peer of [...this.running.values()].reverse()) {
          if (peer.item.pluginId === item.pluginId) await this.stopRun(peer);
        }
        if (!stale) await this.status(plan, item, "failed", String(error));
        else await this.status(plan, item, item.entry.kind === "sandbox-view" ? "stopped" : "pending-restart");
      }
    }
    this.changed();
  }

  diagnostics() {
    return { restartRequired: this.restartRequired, errors: { ...this.errors },
      active: [...this.running.values()].filter((run) => run.active).map(({ item }) => ({
        pluginId: item.pluginId, entryId: item.entry.id, identity: item.identity, instanceId: item.instanceId,
      })) };
  }

  async stop() {
    await this.reconcile({ entries: [], safeMode: true, sessionId: "", hostInstance: "" });
  }
}
