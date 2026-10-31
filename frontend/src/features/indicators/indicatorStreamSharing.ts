import { resolveKlineSeriesIdentity } from "../market-data/klineSeriesIdentity.js";
import { indicatorRequestKey } from "./indicatorRequestBroker.js";
import { normalizeIndicatorRevision } from "./indicatorRangeCoverage.js";
import type { IndicatorStreamSubscription } from "./indicatorStreamConnection.js";
import type { IndicatorSubscribeMessage, IndicatorWsMessage } from "./indicatorTypes.js";

/** Definition equality is exact, not a script hash or a consumer's signature.
 * Script subscriptions own live state/observations/alerts. No provider contract
 * currently certifies them shareable, so their owner remains part of identity. */
export function indicatorStreamSharingKey(
  subscription: IndicatorStreamSubscription,
  scope: readonly [string, string],
  owner: string,
): string {
  const { action: _action, clientId: _client, historyLimit: _history, resumeFrom: _resume,
    serverEpoch: _epoch, correctionRevision: _revision, seriesIdentity, ...definition } = subscription.message;
  void _action; void _client; void _history; void _resume; void _epoch; void _revision;
  return indicatorRequestKey({ scope, definition: { ...definition,
    seriesIdentity: resolveKlineSeriesIdentity(definition.exchange, seriesIdentity) },
  ...(definition.kind === "script" ? { owner } : {}) });
}

/** Resume only from a checkpoint every consumer can accept. A late join gets
 * a fresh cold ACK; each chart's existing HTTP hydration owns its history. */
export function sharedIndicatorSubscribeMessage(
  subscriptions: readonly IndicatorStreamSubscription[],
  clientId: string,
  cold: boolean,
): IndicatorSubscribeMessage {
  const first = subscriptions[0]!.message;
  const { resumeFrom: _resume, serverEpoch: _epoch, correctionRevision: _revision, ...definition } = first;
  void _resume; void _epoch; void _revision;
  // Seed depth is a budget, not live session identity. Normal chart growth
  // updates the next subscribe's budget without restarting an active session.
  // Existing controller warmup checks explicitly refresh insufficient seeds.
  const message: IndicatorSubscribeMessage = { ...definition, clientId,
    historyLimit: Math.max(...subscriptions.map(({ message: item }) => item.historyLimit)) };
  const sameRevision = Boolean(first.serverEpoch && first.correctionRevision !== undefined
    && subscriptions.every(({ message: item }) => item.serverEpoch === first.serverEpoch
      && item.correctionRevision === first.correctionRevision));
  if (sameRevision) {
    message.serverEpoch = first.serverEpoch!;
    message.correctionRevision = first.correctionRevision!;
    if (!cold && subscriptions.every(({ message: item }) => Number.isFinite(item.resumeFrom) && Number(item.resumeFrom) > 0)) {
      message.resumeFrom = Math.floor(Math.min(...subscriptions.map(({ message: item }) => Number(item.resumeFrom))));
    }
  }
  return message;
}

export function localizeSharedIndicatorMessage(
  message: IndicatorWsMessage,
  subscription: IndicatorStreamSubscription,
): IndicatorWsMessage {
  // Consumers normalize output and may retain/mutate nested arrays. A callback
  // must never alter the next consumer's frame or the physical message.
  const local = { ...structuredClone(message), clientId: subscription.clientId } as IndicatorWsMessage;
  if (local.type !== "indicator.subscribed" || local.ok === false) return local;
  const revision = normalizeIndicatorRevision(local);
  const previous = subscription.message;
  if (revision && ((previous.serverEpoch !== undefined && revision.serverEpoch !== previous.serverEpoch)
    || (previous.correctionRevision !== undefined && revision.correctionRevision !== previous.correctionRevision))) {
    // A group with incompatible checkpoints subscribed cold. The server did
    // not receive each owner's old revision; never silently certify that
    // owner's cached history with the group's newer acknowledgement.
    local.dataRevision = { ...revision, historyInvalid: true };
  }
  return local;
}
