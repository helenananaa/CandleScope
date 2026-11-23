import * as React from "react";
import { unifiedAssetBase } from "../plugins/pluginPlatformApi.js";
import type { Dispose, ExtensionContext, ExtensionModule } from "./contracts.js";
import { bindHostService, emitHostEvent, subscribeHostEvent, getExtensionState, getHostService, publishExtensions } from "./state.js";

const commands = new Map<string, (payload?: unknown) => unknown>();
const slotOwners = new Map<string, string>();
const serviceOwners = new Map<string, string>();
const validSlots = new Set(["shell", "topBar", "intervalSelector", "workspace", "featureSurfaces", "statusBar", "toolbar", "chart", "bottomPanel", "rightRail", "exportOverlay"]);

async function boundedActivation<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([work, new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error("Extension activation timed out; reload after disabling it")), 10_000);
    })]);
  } finally { if (timer !== undefined) clearTimeout(timer); }
}

export function createExtensionContext(item: { manifest: {id: string; internalApiVersion?: 1}; assetBase?: string },
  guard: () => void = () => {}, resolveAssets = unifiedAssetBase, validateResult?: () => Promise<void>,
  allowSlot: (name: string) => boolean = () => true): { context: ExtensionContext; dispose: Dispose } {
  const cleanups: Dispose[] = [];
  let disposed = false;
  const id = item.manifest.id;
  const track = (cleanup: Dispose) => {
    if (disposed) { void Promise.resolve().then(cleanup).catch((error) => report(id, error)); throw new Error("Extension has been disposed"); }
    cleanups.push(cleanup);
  };
  const context: ExtensionContext = {
    id, apiVersion: 1, React, track,
    assetUrl(path) {
      guard();
      if (!/^[A-Za-z0-9_./-]+$/.test(path) || path.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("Invalid extension asset path");
      return `${resolveAssets(item.assetBase ?? "")}${path}`;
    },
    ui: {
      replaceSlot(name, component) {
        guard();
        if (!validSlots.has(name) || !allowSlot(name) || slotOwners.has(name)) throw new Error(`Slot unavailable or already replaced: ${name}`);
        slotOwners.set(name, id);
        const slots = new Map(getExtensionState().slots);
        slots.set(name, component);
        publishExtensions({ slots });
        track(() => {
          if (slotOwners.get(name) !== id) return;
          slotOwners.delete(name);
          const remaining = new Map(getExtensionState().slots);
          remaining.delete(name);
          publishExtensions({ slots: remaining });
        });
      },
      stylesheet(css) {
        guard();
        const element = document.createElement("style");
        element.dataset.extensionOwner = id;
        // Extension CSS joins the app's features layer, so it competes with feature CSS by
        // specificity and order exactly as it did before cascade layers.
        element.textContent = `@layer features {\n${css}\n}`;
        document.head.append(element);
        track(() => element.remove());
      },
    },
    commands: {
      register(name, handler) {
        guard();
        const key = `${id}.${name}`;
        if (commands.has(key)) throw new Error(`Duplicate command: ${key}`);
        const checked = (payload?: unknown) => {
          guard();
          const value = handler(payload);
          if (validateResult) return Promise.resolve(value).then(async (result: unknown) => { guard(); await validateResult(); guard(); return result; });
          if (value instanceof Promise) return value.then((result: unknown) => { guard(); return result; });
          guard(); return value;
        };
        commands.set(key, checked);
        track(() => { if (commands.get(key) === checked) commands.delete(key); });
      },
      execute(name, payload) {
        guard();
        const handler = commands.get(name);
        if (!handler) throw new Error(`Command unavailable: ${name}`);
        return handler(payload);
      },
    },
    events: {
      on(name, listener) {
        guard();
        track(subscribeHostEvent(name, (payload) => {
          try { guard(); void Promise.resolve(listener(payload)).catch((error) => report(id, error)); } catch (error) { report(id, error); }
        }));
      },
      emit(name, payload) { guard(); emitHostEvent(name, payload); },
    },
    services: {
      get<T>(name: string) { guard(); return getHostService<T>(name); },
      register(name, value) {
        guard();
        const key = `${id}.${name}`;
        if (serviceOwners.has(key)) throw new Error(`Duplicate service: ${key}`);
        serviceOwners.set(key, id);
        const unbind = bindHostService(key, value);
        track(() => { unbind(); serviceOwners.delete(key); });
      },
    },
    ...(item.manifest.internalApiVersion === 1 ? { internal: { apiVersion: 1 as const, get: getHostService } } : {}),
  };
  return { context, async dispose() {
    disposed = true;
    const errors: unknown[] = [];
    for (const cleanup of cleanups.reverse()) {
      try { await boundedActivation(Promise.resolve(cleanup())); } catch (error) { errors.push(error); }
    }
    cleanups.length = 0;
    if (errors.length) throw new AggregateError(errors, `Failed to dispose ${id}`);
  } };
}

/** Host-code gateway for approved unified frontend entries. */
export async function loadUnifiedFrontend(url: string): Promise<ExtensionModule> {
  return import(/* @vite-ignore */ url) as Promise<ExtensionModule>;
}

function report(id: string, error: unknown): void {
  publishExtensions({ errors: { ...getExtensionState().errors, [id]: String(error) } });
}
