import { t, type MessageKey } from "../../i18n/index.js";

/**
 * Display names for codes the plugin platform sends: live-control modes, release channels,
 * permission kinds and decisions, runtime verification, sandbox status and trust modes.
 * A code without a name of its own is shown as sent, so a new value stays visible.
 */
function named(keys: Readonly<Record<string, MessageKey>>, value: string | null | undefined): string {
  if (!value) return "—";
  const key = keys[value];
  return key ? t(key) : value;
}

const LIVE_MODE_KEYS: Readonly<Record<string, MessageKey>> = {
  unavailable: "plugin.liveMode.unavailable",
  disarmed: "plugin.liveMode.disarmed",
  armed: "plugin.liveMode.armed",
  killed: "plugin.liveMode.killed",
};
export const liveModeLabel = (mode: string | null | undefined) => named(LIVE_MODE_KEYS, mode);

export const RELEASE_CHANNELS = ["internal", "opted-in-local", "preview", "stable"] as const;
const CHANNEL_KEYS: Readonly<Record<string, MessageKey>> = {
  internal: "plugin.channel.internal",
  "opted-in-local": "plugin.channel.optedInLocal",
  preview: "plugin.channel.preview",
  stable: "plugin.channel.stable",
};
export const releaseChannelLabel = (channel: string | null | undefined) => named(CHANNEL_KEYS, channel);

/** The channels in rollout order, as "Internal → Local opt-in → Preview → Stable". */
export function releaseChannelOrder(): string {
  return RELEASE_CHANNELS.map(releaseChannelLabel).join(" → ");
}

const PERMISSION_KIND_KEYS: Readonly<Record<string, MessageKey>> = {
  required: "plugin.permission.required",
  optional: "plugin.permission.optional",
};
export const permissionKindLabel = (kind: string | null | undefined) => named(PERMISSION_KIND_KEYS, kind);

const DECISION_KEYS: Readonly<Record<string, MessageKey>> = {
  pending: "plugin.decision.pending",
  granted: "plugin.decision.granted",
  denied: "plugin.decision.denied",
  revoked: "plugin.decision.revoked",
};
export const permissionDecisionLabel = (decision: string | null | undefined) => named(DECISION_KEYS, decision);

const VERIFICATION_KEYS: Readonly<Record<string, MessageKey>> = {
  verified: "plugin.verification.verified",
  missing: "plugin.verification.missing",
  corrupt: "plugin.verification.corrupt",
  revoked: "plugin.decision.revoked",
  probed: "plugin.verification.probed",
};
export const runtimeVerificationLabel = (status: string | null | undefined) => named(VERIFICATION_KEYS, status);

const SANDBOX_KEYS: Readonly<Record<string, MessageKey>> = {
  "windows-appcontainer": "plugin.sandbox.appContainer",
  "trusted-local-user-approved": "plugin.sandbox.trustedLocal",
  "unavailable-trusted-local-only": "plugin.sandbox.unavailable",
};
export const sandboxStatusLabel = (status: string | null | undefined) => named(SANDBOX_KEYS, status);

const TRUST_MODE_KEYS: Readonly<Record<string, MessageKey>> = {
  "first-party-pinned": "plugin.trustMode.firstPartyPinned",
  "marketplace-sandboxed": "plugin.trustMode.marketplaceSandboxed",
  "trusted-local": "plugin.trustMode.trustedLocal",
  "developer-local": "plugin.trustMode.developerLocal",
  "ui-only-untrusted": "plugin.trustMode.uiOnlyUntrusted",
};
export const trustModeLabel = (mode: string | null | undefined) => named(TRUST_MODE_KEYS, mode);
