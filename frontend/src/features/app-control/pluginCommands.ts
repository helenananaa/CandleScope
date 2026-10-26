import type { JsonValue, PluginLiveConfirmationPreview, PluginLiveConfirmationReceipt, PluginPlatformRuntime } from "../plugins/pluginPlatformTypes.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { array, bool, choice, empty, number, object, optional, record, text } from "./commandSchema.js";
import { publishControlFile, readControlFile } from "./controlFiles.js";

/** Only server-returned live previews/receipts can be referenced by subsequent commands. */
export class PluginControlSession {
  readonly live = new Map<string, { accountRef: string; shadowRef: string; preview: PluginLiveConfirmationPreview; receipt?: PluginLiveConfirmationReceipt }>();
  remember(accountRef: string, shadowRef: string, preview: PluginLiveConfirmationPreview) {
    if (this.live.size >= 32) throw new Error("LIVE_PREVIEW_BUDGET");
    const previewRef = crypto.randomUUID(); this.live.set(previewRef, { accountRef, shadowRef, preview }); return previewRef;
  }
}
export function pluginCommands(id: string, runtime: PluginPlatformRuntime, session: PluginControlSession): ControlCommandGroup {
  const { view: v, actions: a } = runtime;
  const manageable = () => v.managementAvailable;
  const trust = { available: manageable, requiredScope: "app.trust" };
  const live = { available: () => v.liveControl.available, requiredScope: "app.live" };
  const plugin = (id: string) => { if (!v.catalog?.plugins.some((row) => row.id === id)) throw new Error("PLUGIN_UNAVAILABLE"); return id; };
  const target = object({ pluginId: text(128) });
  const review = object({ candidateId: text(128), previewSha256: text(128), reason: text(2048), acknowledgements: array(text(256), 64) });
  const state = () => ({ market: v.marketIdentity, catalog: v.catalog, marketplace: v.marketplaceCatalog, registries: v.registries, snapshot: v.snapshot,
    loading: v.loading, error: v.error, managementAvailable: v.managementAvailable, notice: v.notice, liveControl: v.liveControl,
    surfaces: { manager: v.managerOpen, palette: v.paletteOpen, viewId: v.openViewId, settingsId: v.openSettingsId, live: v.liveControlOpen } });
  return { id: `plugins:${id}`, title: "Plugin management and declared commands", context: () => ({ market: v.marketIdentity, revision: v.catalog?.platform.registryRevision, liveControl: v.liveControl, loading: v.loading }), snapshot: state, commands: [
    command("refresh", "Refresh plugin catalogs and runtime state.", empty, () => a.refresh()),
    command("surface", "Open/close plugin UI surfaces.", object({ surface: choice(["manager", "palette", "view", "settings", "live"]), open: bool, id: optional(text(128)) }), ({ surface, open, id }) => {
      if (surface === "manager") return open ? a.openManager() : a.closeManager();
      if (surface === "palette") return open ? a.openPalette() : a.closePalette();
      if (surface === "live") return open ? a.openLiveControl() : a.closeLiveControl();
      if (surface === "view") { if (!open) return a.closeView(); if (!id || ![...v.registries.sidePanel, ...v.registries.bottomPanel, ...v.registries.statusArea].some((row) => row.id === id && row.available)) throw new Error("VIEW_UNAVAILABLE"); return a.openView(id); }
      if (!open) return a.closeSettings(); if (!id || !v.registries.settings.some((row) => row.id === id && row.available)) throw new Error("SETTINGS_UNAVAILABLE"); return a.openSettings(id);
    }),
    command("invoke", "Invoke only an available, installed declared plugin command. Existing plugin schema, grants, trust and user-action checks still apply.", object({ id: text(128), input: optional(record) }), ({ id, input }) => {
      if (![...v.registries.commandPalette, ...v.registries.topToolbar, ...v.registries.chartContextMenu].some((row) => row.id === id && row.available)) throw new Error("PLUGIN_COMMAND_UNAVAILABLE");
      return a.invokeCommand(id, input as Record<string, JsonValue> | undefined);
    }),
    command("readSettings", "Read a declared plugin settings contribution.", object({ id: text(128) }), ({ id }) => { if (!v.registries.settings.some((row) => row.id === id)) throw new Error("SETTINGS_UNAVAILABLE"); return a.readSettings(id); }, { readOnly: true }),
    command("writeSettings", "Write declared plugin settings using its schema and permissions.", object({ id: text(128), value: record }), ({ id, value }) => { if (!v.registries.settings.some((row) => row.id === id && row.available)) throw new Error("SETTINGS_UNAVAILABLE"); return a.writeSettings(id, value as Record<string, JsonValue>); }),
    command("detail", "Read a listed plugin's management, permission and trust status.", target, ({ pluginId }) => a.loadDetail(plugin(pluginId)), { readOnly: true, available: manageable }),
    command("marketplaceStatus", "Read marketplace status.", empty, () => a.loadMarketplaceStatus(), { readOnly: true, available: manageable }),
    command("refreshMarketplace", "Refresh a marketplace using the UI management action.", object({ marketplaceId: text(128) }), ({ marketplaceId }) => a.refreshMarketplace(marketplaceId), { available: manageable }),
    command("prepareMarketplace", "Prepare a marketplace release; does not activate it.", object({ pluginId: text(128), version: text(128) }), ({ pluginId, version }) => a.prepareMarketplaceRelease(pluginId, version), { available: manageable }),
    command("applyMarketplace", "Apply a prepared marketplace release with existing supply-chain guards.", target, ({ pluginId }) => a.applyMarketplaceRelease(pluginId), { available: manageable }),
    command("activateMarketplace", "Activate a prepared marketplace release.", target, ({ pluginId }) => a.activateMarketplaceRelease(pluginId), { available: manageable }),
    command("previewV1Import", "Preview compatibility import.", empty, () => a.previewV1CompatibilityImport(), { readOnly: true, available: manageable }),
    command("applyV1Import", "Apply the exact inspected compatibility import hash.", object({ previewSha256: text(128) }), ({ previewSha256 }) => a.applyV1CompatibilityImport(previewSha256), { available: manageable }),
    command("previewV1Rollback", "Preview compatibility rollback.", empty, () => a.previewV1CompatibilityRollback(), { readOnly: true, available: manageable }),
    command("applyV1Rollback", "Apply the exact inspected compatibility rollback hash.", object({ previewSha256: text(128) }), ({ previewSha256 }) => a.applyV1CompatibilityRollback(previewSha256), { available: manageable }),
    command("prepareLocalInstall", "Validate a staged bundle and produce the existing install candidate; does not grant trust.", object({ fileRef: text(96) }), async ({ fileRef }) => a.prepareLocalInstall(await readControlFile(fileRef)), { available: manageable }),
    command("reviewLocalInstall", "Review the exact install candidate/hash and required acknowledgements. Requires explicit app.trust launch scope.", review, ({ candidateId, previewSha256, reason, acknowledgements }) => a.reviewLocalInstall(candidateId, previewSha256, reason, acknowledgements), trust),
    command("confirmLocalInstall", "Confirm a reviewed install using the server-issued token, candidate identity and preview hash.", object({ candidateId: text(128), previewSha256: text(128), confirmationToken: text(2048) }), ({ candidateId, previewSha256, confirmationToken }) => a.confirmLocalInstall(candidateId, previewSha256, confirmationToken), trust),
    command("reviewTrust", "Review an installed plugin trust change under explicit app.trust scope.", object({ pluginId: text(128), targetMode: choice(["marketplace-sandboxed", "trusted-local"]), reason: text(2048), acknowledgements: array(text(256), 64) }), ({ pluginId, targetMode, reason, acknowledgements }) => a.reviewTrustChange(plugin(pluginId), targetMode, reason, acknowledgements), trust),
    command("confirmTrust", "Confirm the reviewed plugin trust change with its server-issued token/hash.", object({ pluginId: text(128), changeId: text(128), previewSha256: text(128), confirmationToken: text(2048) }), ({ pluginId, changeId, previewSha256, confirmationToken }) => a.confirmTrustChange(plugin(pluginId), changeId, previewSha256, confirmationToken), trust),
    command("state", "Enable/disable/rollback/uninstall an installed plugin with existing domain checks.", object({ pluginId: text(128), action: choice(["enable", "disable", "rollback", "uninstall"]) }), ({ pluginId, action }) => a.changeState(plugin(pluginId), action), { available: manageable }),
    command("permissionGrant", "Grant a requested plugin permission using explicit app.trust scope and the existing scope validator.", object({ pluginId: text(128), permissionId: text(128), scope: optional(record) }), ({ pluginId, permissionId, scope }) => a.decidePermission(plugin(pluginId), permissionId, "grant", scope as Record<string, JsonValue> | undefined), trust),
    command("permissionRevoke", "Deny/revoke a plugin permission.", object({ pluginId: text(128), permissionId: text(128), decision: choice(["deny", "revoke"]) }), ({ pluginId, permissionId, decision }) => a.decidePermission(plugin(pluginId), permissionId, decision), { available: manageable }),
    command("stageUserFile", "Convert a staged agent file into an existing plugin file capability handle.", object({ id: text(128), field: text(128), fileRef: text(96) }), async ({ id, field, fileRef }) => a.stageUserFile(id, field, await readControlFile(fileRef))),
    command("prepareUserFileSave", "Prepare the declared plugin save capability.", object({ id: text(128), field: text(128) }), ({ id, field }) => a.prepareUserFileSave(id, field)),
    command("downloadUserFile", "Read a completed plugin download handle into a bounded control file.", object({ pluginId: text(128), downloadId: text(128), name: text(160) }), async ({ pluginId, downloadId, name }) => publishControlFile(await a.downloadUserFile(plugin(pluginId), downloadId), name)),
    command("paperKillSwitch", "Set the simulated paper-account kill switch.", object({ enabled: bool }), ({ enabled }) => a.setPaperKillSwitch(enabled)),
    command("liveMode", "Arm/disarm through the existing live-control protocol; requires explicit app.live scope.", object({ mode: choice(["armed", "disarmed"]), reason: text(2048), acknowledgeKill: bool }), ({ mode, reason, acknowledgeKill }) => a.setLiveControlMode(mode, reason, acknowledgeKill), live),
    command("liveKill", "Engage the live kill switch using the existing control-generation protocol.", object({ reason: text(2048) }), ({ reason }) => a.killLiveControl(reason), { ...live, interrupt: true }),
    command("liveRevokeAuthority", "Revoke a live authority under explicit app.live scope.", object({ scopeType: choice(["grant", "plugin", "publisher", "credential"]), subject: text(256), reason: text(2048) }), ({ scopeType, subject, reason }) => a.revokeLiveAuthority(scopeType, subject, reason), live),
    command("livePreview", "Read a live intent/risk preview. This does not submit or issue confirmation.", object({ accountRef: text(128), shadowRef: text(128) }), async ({ accountRef, shadowRef }) => { const preview = await a.previewLiveConfirmation(accountRef, shadowRef); return { previewRef: session.remember(accountRef, shadowRef, preview), preview }; }, { readOnly: true, available: () => v.liveControl.available }),
    command("liveConfirm", "Issue a confirmation for the exact server-returned preview, limits, generation and intent hash. Requires app.live scope.", object({ previewRef: text(128), ttlSeconds: number(1, 300, true), confirmed: choice([true]) }), async ({ previewRef, ttlSeconds }) => { const item = session.live.get(previewRef); if (!item) throw new Error("LIVE_PREVIEW_UNAVAILABLE"); item.receipt = await a.issueLiveConfirmation(item.accountRef, item.shadowRef, item.preview, ttlSeconds); return item.receipt; }, live),
    command("liveExecute", "Submit/cancel only with the receipt issued for this preview. Backend expiry, action, intent, grants and generation checks remain authoritative.", object({ previewRef: text(128), action: choice(["submit", "cancel"]) }), ({ previewRef, action }) => { const item = session.live.get(previewRef); if (!item?.receipt) throw new Error("LIVE_RECEIPT_UNAVAILABLE"); return action === "submit" ? a.submitLiveExecution(item.accountRef, item.shadowRef, item.receipt) : a.cancelLiveExecution(item.accountRef, item.shadowRef, item.receipt); }, live),
    command("liveRevokeConfirmation", "Revoke an issued live confirmation.", object({ receiptRef: text(128), reason: text(2048) }), ({ receiptRef, reason }) => a.revokeLiveConfirmation(receiptRef, reason), live),
    command("liveReconcile", "Reconcile an uncertain live execution through the existing backend, without blind resubmission.", object({ accountRef: text(128), shadowRef: text(128) }), ({ accountRef, shadowRef }) => a.reconcileLiveExecution(accountRef, shadowRef), live),
    command("liveAudit", "Export the live audit through the existing domain action to a fileRef.", empty, async () => { let result: unknown; await a.downloadLiveAudit(async (blob) => { result = await publishControlFile(blob, "live-audit.json"); }); return result; }, { available: () => v.liveControl.available }),
  ] };
}
