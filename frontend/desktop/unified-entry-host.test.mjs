import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { UnifiedEntryLifecycle } from "./unified-entry-lifecycle.mjs";
import { UnifiedDesktopHost } from "./unified-entry-host.mjs";

function item(id = "one", generation = 1) {
  return { pluginId: "example.multi", entry: { id, kind: "desktop", path: `${id}.mjs` },
    identity: {pluginId:"example.multi",version:"1.0.0",packageSha256:`sha256:${"a".repeat(64)}`,generation},
    instanceId: `${generation}${id}`.padEnd(32,"0"),
    manifest: {schema:"candlescope.unified-plugin/1",hostApiVersion:1,id:"example.multi",name:"Multi",version:"1.0.0",trust:"full-trust",dependencies:{}},
  };
}
const plan = (...entries) => ({sessionId:"test-session",hostInstance:"backend-instance",entries});

test("an in-flight desktop plan cannot reactivate entries after shutdown", async () => {
  const { promise, resolve } = Promise.withResolvers();
  const host = new UnifiedDesktopHost({ context: {}, request: () => promise });
  const applied = [];
  host.host.reconcile = async (next) => { applied.push(next); };
  const starting = host.start();
  await host.stop();
  resolve(plan(item()));
  await starting;
  assert.equal(applied.length, 1);
  assert.equal(applied[0].safeMode, true);
  assert.equal(host.timer, undefined);
});
function context(guard, events) {
  let disposed = false;
  const cleanups = [];
  return {context: {track(cleanup) {
    if (disposed) { void cleanup(); throw new Error("revoked"); }
    guard(); cleanups.push(cleanup);
  }},async dispose() {disposed=true; for (const cleanup of cleanups.reverse()) await cleanup();events.push("disposed");}};
}

test("entries share package identity and package failure releases local peers",async()=>{
  const events=[], reports=[];
  const lifecycle = new UnifiedEntryLifecycle({
    load: (entry)=>({activate(ctx) { if(entry.entry.id==="bad") throw new Error("broken");ctx.track(()=>events.push("cleanup")); }}),
    createContext: (_,guard)=>context(guard,events), report: async(_,entry,state)=>reports.push([entry.entry.id,state]),
  });
  await lifecycle.reconcile(plan(item(),item("bad")));
  assert.equal(lifecycle.diagnostics().active.length,0);
  assert.ok(events.includes("cleanup"));
  assert.deepEqual(reports,[["one","running"],["one","pending-restart"],["bad","failed"]]);
  assert.equal(lifecycle.restartRequired,true);
});

test("superseded async activation runs late cleanup without adopting the result",async()=>{
  const events=[], reports=[];
  let resolve;
  const activation=new Promise((done)=>{resolve=done;});
  const lifecycle=new UnifiedEntryLifecycle({load:()=>({activate:()=>activation}),
    createContext:(_,guard)=>context(guard,events),report:async(_,__,state)=>reports.push(state)});
  const pending=lifecycle.reconcile(plan(item()));
  await new Promise((done)=>setImmediate(done));
  const stopped=lifecycle.reconcile(plan());
  resolve(()=>events.push("late-cleanup"));
  await Promise.all([pending,stopped]);
  assert.equal(lifecycle.diagnostics().active.length,0);
  assert.ok(events.includes("late-cleanup"));
  assert.ok(!reports.includes("running"));
});

test("a timed-out activation still releases a late returned cleanup",async()=>{
  const events=[];
  let resolve;
  const lifecycle=new UnifiedEntryLifecycle({timeoutMs:5,
    load:()=>({activate:()=>new Promise((done)=>{resolve=done;})}),
    createContext:(_,guard)=>context(guard,events),report:async()=>{}});
  await lifecycle.reconcile(plan(item()));
  resolve(()=>events.push("late-cleanup"));
  await new Promise((done)=>setImmediate(done));
  assert.ok(events.includes("late-cleanup"));
  assert.equal(lifecycle.diagnostics().active.length,0);
});

test("stopped host code waits for a fresh process instead of claiming a hot update",async()=>{
  let starts=0;
  const reports=[];
  const lifecycle=new UnifiedEntryLifecycle({load:()=>({activate(){starts++;}}),
    createContext:(_,guard)=>context(guard,[]),report:async(_,__,state)=>reports.push(state)});
  await lifecycle.reconcile(plan(item()));
  await lifecycle.reconcile(plan(item("one",2)));
  assert.equal(starts,1);
  assert.equal(lifecycle.diagnostics().active.length,0);
  assert.ok(reports.includes("pending-restart"));
});

test("desktop loads pinned ESM and disposes actual module resources on disable",async()=>{
  const root=await mkdtemp(path.join(tmpdir(),"unified-desktop-"));
  try {
    const code="export function activate(ctx) {ctx.host.events.push('active');ctx.track(()=>ctx.host.events.push('cleanup'));}";
    await writeFile(path.join(root,"one.mjs"),code);
    const entry={...item(),root,files:{"one.mjs":createHash("sha256").update(code).digest("hex")}};
    let current=plan(entry);
    const events=[],reports=[];
    const host=new UnifiedDesktopHost({context:{host:{events}},request:async(route,body)=>{
      if(route==="/realm")return current;
      reports.push(body);return {ok:true};
    }});
    await host.refresh();
    assert.deepEqual(events,["active"]);
    assert.equal(host.diagnostics().active[0].entryId,"one");
    current=plan();
    await host.refresh();
    assert.deepEqual(events,["active","cleanup"]);
    assert.equal(host.diagnostics().restartRequired,true);
    await host.stop();
    assert.equal(reports[0].state,"running");
  } finally {await rm(root,{recursive:true,force:true});}
});

test("desktop rejects changed bytes before evaluating a module",async()=>{
  const root=await mkdtemp(path.join(tmpdir(),"unified-desktop-"));
  try {
    await writeFile(path.join(root,"one.mjs"),"throw new Error('evaluated tampered code');");
    const entry={...item(),root,files:{"one.mjs":"a".repeat(64)}};
    const host=new UnifiedDesktopHost({context:{},request:async(route)=>route==="/realm"?plan(entry):{ok:true}});
    await host.refresh();
    assert.match(host.diagnostics().errors[entry.pluginId],/integrity/);
    assert.doesNotMatch(host.diagnostics().errors[entry.pluginId],/evaluated tampered/);
    await host.stop();
  } finally {await rm(root,{recursive:true,force:true});}
});

test("an owner rejecting activation acknowledgement prevents local adoption",async()=>{
  const events=[];
  const lifecycle=new UnifiedEntryLifecycle({load:()=>({activate(ctx){ctx.track(()=>events.push("cleanup"));}}),
    createContext:(_,guard)=>context(guard,events),report:async(_,__,state)=>{if(state==="running")throw new Error("revoked at owner");}});
  await lifecycle.reconcile(plan(item()));
  assert.equal(lifecycle.diagnostics().active.length,0);
  assert.deepEqual(events,["cleanup","disposed"]);
});


test("an interrupted desktop activation stays blocked while unrelated entries start", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "unified-desktop-recovery-"));
  try {
    const markerPath = path.join(root, "marker.json");
    const code = "export function activate(ctx) { ctx.host.events.push(ctx.id); }";
    const files = {};
    for (const name of ["one.mjs", "other.mjs"]) {
      await writeFile(path.join(root, name), code);
      files[name] = createHash("sha256").update(code).digest("hex");
    }
    const blocked = { ...item(), root, files };
    const allowed = { ...item("other"), root, files, pluginId: "example.other" };
    allowed.identity.pluginId = allowed.pluginId;
    allowed.manifest.id = allowed.pluginId;
    const marker = {
      pluginId: blocked.pluginId,
      packageSha256: blocked.identity.packageSha256,
      generation: blocked.identity.generation,
      entryId: blocked.entry.id,
    };
    await writeFile(markerPath, JSON.stringify(marker));
    const events = [];
    const reports = [];
    const host = new UnifiedDesktopHost({
      markerPath, context: { host: { events } },
      request: async (route, body) => {
        if (route === "/realm") return plan(blocked, allowed);
        reports.push(body);
        return { ok: true };
      },
    });
    try {
      await host.start();
      assert.deepEqual(events, ["example.other"]);
      assert.match(host.diagnostics().errors[blocked.pluginId], /interrupted/);
      assert.ok(reports.some((r) => r.instanceId === blocked.instanceId && r.state === "failed"));
      assert.deepEqual(JSON.parse(await readFile(markerPath, "utf8")), marker);
    } finally {
      await host.stop();
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
