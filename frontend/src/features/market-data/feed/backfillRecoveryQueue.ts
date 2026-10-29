/** Per-consumer recovery queue. Detached generations can finish, but never own a successor. */
export class BackfillRecoveryQueue<Job extends { epoch: number; eventKeys: Set<string> }> {
  private readonly states = new Map<string, { epoch: number; queue: Job[]; keys: Set<string>; done: Promise<void> }>();
  private readonly seen = new Map<string, number>();

  constructor(private readonly handlers: {
    merge(queued: Job, incoming: Job): boolean;
    read(job: Job): Promise<boolean>;
    verify(job: Job): Promise<void>;
    needsVerification(job: Job): boolean;
    isCurrent(job: Job): boolean;
    cooldown(job: Job): number;
    onError(error: unknown): void;
    now?: () => number;
  }) {}

  get activeKeys(): ReadonlySet<string> { return new Set(this.states.keys()); }
  cancel(key: string): void { this.states.delete(key); }
  async whenIdle(key: string): Promise<void> { await this.states.get(key)?.done; }

  enqueue(key: string, job: Job): void {
    const now = (this.handlers.now ?? Date.now)();
    let state = this.states.get(key);
    if (state && state.epoch !== job.epoch) { this.cancel(key); state = undefined; }
    const eventId = (event: string) => `${key}|${job.epoch}|${event}`;
    if ([...job.eventKeys].every((event) => state?.keys.has(event) || (this.seen.get(eventId(event)) ?? 0) > now)) return;
    const created = !state;
    state ??= { epoch: job.epoch, queue: [], keys: new Set(), done: Promise.resolve() };
    if (!state.queue.some((queued) => this.handlers.merge(queued, job))) state.queue.push(job);
    for (const event of job.eventKeys) state.keys.add(event);
    if (!created) return;
    this.states.set(key, state);
    // Set ownership before starting asynchronous work (including synchronous callbacks).
    state.done = this.drain(key, state);
  }

  private async drain(key: string, state: NonNullable<ReturnType<typeof this.states.get>>): Promise<void> {
    const owns = () => this.states.get(key) === state;
    try {
      do {
        let verify: Job | undefined;
        while (owns() && state.queue.length) {
          const job = state.queue.shift()!;
          try {
            const resolved = await this.handlers.read(job);
            if (owns() && this.handlers.isCurrent(job)) {
              if (resolved) verify = undefined;
              else if (this.handlers.needsVerification(job)) verify = job;
            }
          } catch (error) { this.handlers.onError(error); }
          finally {
            if (owns()) {
              const expires = (this.handlers.now ?? Date.now)() + Math.max(1_000, this.handlers.cooldown(job));
              for (const event of job.eventKeys) {
                state.keys.delete(event);
                this.seen.set(`${key}|${job.epoch}|${event}`, expires);
              }
              while (this.seen.size > 1_024) this.seen.delete(this.seen.keys().next().value!);
            }
          }
        }
        if (owns() && verify && this.handlers.isCurrent(verify)) await this.handlers.verify(verify);
      } while (owns() && state.queue.length);
    } catch (error) { this.handlers.onError(error); }
    finally { if (owns()) this.states.delete(key); }
  }
}
