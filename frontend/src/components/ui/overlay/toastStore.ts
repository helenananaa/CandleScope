// Toast notifications: a small store the ToastRegion renders.

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  tone?: "info" | "success" | "warning" | "danger";
  title: string;
  message?: string;
  action?: ToastAction;
  /** Milliseconds before it hides; 0 keeps it until dismissed. Defaults: 5 s, 8 s for danger. */
  durationMs?: number;
}

export interface Toast extends Required<Pick<ToastOptions, "tone" | "title">> {
  id: number;
  message: string | undefined;
  action: ToastAction | undefined;
  durationMs: number;
}

/** At most this many toasts are shown; older ones give way. */
export const MAX_TOASTS = 4;

export function createToastStore() {
  let toasts: Toast[] = [];
  let nextId = 1;
  const listeners = new Set<() => void>();
  const emit = () => { for (const listener of [...listeners]) listener(); };
  return {
    add(options: ToastOptions): number {
      const tone = options.tone ?? "info";
      const toast: Toast = {
        id: nextId++, tone, title: options.title, message: options.message, action: options.action,
        durationMs: options.durationMs ?? (tone === "danger" ? 8000 : 5000),
      };
      toasts = [...toasts, toast].slice(-MAX_TOASTS);
      emit();
      return toast.id;
    },
    dismiss(id: number) {
      const before = toasts.length;
      toasts = toasts.filter((toast) => toast.id !== id);
      if (toasts.length !== before) emit();
    },
    list: () => toasts,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}

export const toastStore = createToastStore();
