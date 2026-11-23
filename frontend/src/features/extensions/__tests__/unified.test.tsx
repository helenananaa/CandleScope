import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createExtensionContext } from "../runtime.js";
import UnifiedPluginManager from "../UnifiedPluginManager.js";
import { parseUnifiedPlan } from "../unifiedRuntime.js";
import { OpaquePluginFrame } from "../../plugins/SandboxPluginFrame.js";
import { t } from "../../../i18n/index.js";

function fixture() {
  return {sessionId:"session",hostInstance:"host",entries:[{
    pluginId:"example.multi",entry:{id:"ui",kind:"frontend",path:"ui.mjs"},instanceId:"a".repeat(32),
    identity:{pluginId:"example.multi",version:"1.0.0",generation:1,packageSha256:`sha256:${"a".repeat(64)}`},
    assetBase:`/api/v2/plugins/unified-assets/${"a".repeat(43)}/`,state:"pending-start",
    manifest:{schema:"candlescope.unified-plugin/1",hostApiVersion:1,id:"example.multi",name:"Multi",version:"1.0.0",trust:"full-trust",entries:[]},
  }]};
}
const assets = (path: string) => {
  assert.match(path,/^\/api\/v2\/plugins\/unified-assets\/[A-Za-z0-9_-]{40,64}\/$/);
  return path;
};

test("unified frontend plans require the approved package identity and host trust",()=>{
  assert.equal(parseUnifiedPlan(fixture(),assets).entries.length,1);
  for(const mutate of [
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.manifest.trust="restricted";},
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.identity.generation=0;},
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.identity.pluginId="other";},
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.entry.kind="backend";},
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.entry.path="../ui.mjs";},
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.manifest.hostApiVersion=2;},
    (value: ReturnType<typeof fixture>)=>{value.entries.push(value.entries[0]!);},
    (value: ReturnType<typeof fixture>)=>{value.entries[0]!.assetBase="https://example.com/";},
  ]) {
    const value=fixture(); mutate(value);
    assert.throws(()=>parseUnifiedPlan(value,assets));
  }
});

test("sandbox entries remain opaque and never receive the frontend context",()=>{
  const value=fixture();
  value.entries[0]!.entry.kind="sandbox-view";
  value.entries[0]!.entry.path="index.html";
  value.entries[0]!.manifest.trust="restricted";
  assert.equal(parseUnifiedPlan(value,assets).entries[0]!.entry.kind,"sandbox-view");
  const html=renderToStaticMarkup(<OpaquePluginFrame src="http://127.0.0.1/view" title="Restricted"/>);
  assert.match(html,/sandbox="allow-scripts"/);
  assert.match(html,/credentialless=""/);
  assert.match(html,/referrerPolicy="no-referrer"/);
  assert.doesNotMatch(html,/allow-same-origin|allow-popups|allow-top-navigation|srcdoc/i);
  Object.assign(value.entries[0]!.entry, { startup: ["shell"] });
  assert.throws(() => parseUnifiedPlan(value, assets), /startup shell claim/);
});

test("revoked frontend commands reject an already pending result",async()=>{
  let active=true;
  let finish: ((value: string)=>void) | undefined;
  const owned=createExtensionContext({manifest:{id:"example.unified"}},()=>{if(!active)throw new Error("revoked");});
  owned.context.commands.register("probe",()=>new Promise<string>((resolve)=>{finish=resolve;}));
  const pending=owned.context.commands.execute("example.unified.probe");
  active=false; finish!("late");
  await assert.rejects(async()=>{await pending;},/revoked/);
  assert.throws(()=>owned.context.services.register("late",42),/revoked/);
  await owned.dispose();
});

test("unified management renders package import without starting code",()=>{
  const html=renderToStaticMarkup(<UnifiedPluginManager/>);
  assert.ok(html.includes(t("unified.title")));
  assert.match(html,/accept="\.cspkg"/);
  assert.match(html,/disabled/);
});

test("window results need an owner acknowledgement even when locally current",async()=>{
  const owned=createExtensionContext({manifest:{id:"example.checked"}},()=>{},undefined,async()=>{throw new Error("owner revoked");});
  owned.context.commands.register("probe",()=>"result");
  await assert.rejects(async()=>{await owned.context.commands.execute("example.checked.probe");},/owner revoked/);
  await owned.dispose();
});
