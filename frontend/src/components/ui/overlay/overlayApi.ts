// Imperative entry points for code that cannot render a component at the call site:
// confirmAction() replaces window.confirm, notify() replaces window.alert for results.
import { createElement, useState } from "react";
import { createRoot } from "react-dom/client";
import { ConfirmDialog, ToastRegion } from "../Feedback.js";
import { overlayHost } from "./overlayRuntime.js";
import { toastStore, type ToastOptions } from "./toastStore.js";

export interface ConfirmOptions {
  title: string;
  message?: string;
  /** States the action ("Delete alert"). */
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
}

/** Resolves true when the user confirms, false when they cancel or press Escape. */
export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const container = document.createElement("div");
    container.className = "ui-overlay-mount";
    overlayHost().append(container);
    const root = createRoot(container);
    let settled = false;
    const settle = (value: boolean) => {
      if (settled) return;
      settled = true;
      resolve(value);
      // Unmount after the event that settled it has finished, so focus returns cleanly.
      setTimeout(() => { root.unmount(); container.remove(); }, 0);
    };
    function Host() {
      const [open, setOpen] = useState(true);
      const finish = (value: boolean) => { setOpen(false); settle(value); };
      return createElement(ConfirmDialog, {
        open, title: options.title, onConfirm: () => finish(true), onCancel: () => finish(false),
        ...(options.message !== undefined ? { message: options.message } : {}),
        ...(options.confirmLabel !== undefined ? { confirmLabel: options.confirmLabel } : {}),
        ...(options.cancelLabel !== undefined ? { cancelLabel: options.cancelLabel } : {}),
        ...(options.tone !== undefined ? { tone: options.tone } : {}),
      });
    }
    root.render(createElement(Host));
  });
}

let toastRootMounted = false;

/** Shows a toast and returns its id. Mounts the toast region on first use. */
export function notify(options: ToastOptions): number {
  if (!toastRootMounted && typeof document !== "undefined") {
    toastRootMounted = true;
    const container = document.createElement("div");
    container.className = "ui-overlay-mount";
    overlayHost().append(container);
    createRoot(container).render(createElement(ToastRegion));
  }
  return toastStore.add(options);
}

export function dismissToast(id: number): void {
  toastStore.dismiss(id);
}
