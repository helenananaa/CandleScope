import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { Button, IconButton } from "./Button.js";
import { Dialog } from "./Overlays.js";
import { toastStore, type Toast, type ToastAction } from "./overlay/toastStore.js";

export interface ConfirmDialogProps {
  open: boolean;
  title: ReactNode;
  message?: ReactNode;
  /** States the action ("Delete alert"); defaults to OK. */
  confirmLabel?: string;
  cancelLabel?: string;
  /** Danger for destructive actions: the confirm button turns red and Cancel takes focus. */
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Asks before an action that cannot be undone. Replaces window.confirm. */
export function ConfirmDialog({ open, title, message, confirmLabel, cancelLabel, tone = "primary", busy = false, onConfirm, onCancel }: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog open={open} onClose={onCancel} title={title} size="sm" role="alertdialog" dismissible={!busy}
      initialFocusRef={tone === "danger" ? cancelRef : confirmRef}
      footer={<>
        <Button ref={cancelRef} disabled={busy} onClick={onCancel}>{cancelLabel ?? t("common.cancel")}</Button>
        <Button ref={confirmRef} variant={tone === "danger" ? "danger" : "primary"} disabled={busy} onClick={onConfirm}>{confirmLabel ?? t("common.ok")}</Button>
      </>}>
      {message ? <p className="ui-dialog-message">{message}</p> : null}
    </Dialog>
  );
}

function ToastItem({ toast }: { toast: Toast }) {
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (!toast.durationMs || paused) return undefined;
    const timer = setTimeout(() => toastStore.dismiss(toast.id), toast.durationMs);
    return () => clearTimeout(timer);
  }, [toast.id, toast.durationMs, paused]);
  const actionButton = (action: ToastAction, variant?: "ghost") => (
    <Button size="sm" {...(variant ? { variant } : {})} onClick={() => { action.onClick(); toastStore.dismiss(toast.id); }}>{action.label}</Button>
  );
  return (
    <div className="ui-toast" data-tone={toast.tone} role={toast.tone === "danger" ? "alert" : "status"}
      onPointerEnter={() => setPaused(true)} onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <div className="ui-toast-text">
        <strong className="ui-toast-title">{toast.title}</strong>
        {toast.message ? <span className="ui-toast-message">{toast.message}</span> : null}
        {toast.secondaryAction ? (
          <div className="ui-toast-actions">
            {toast.action ? actionButton(toast.action) : null}
            {actionButton(toast.secondaryAction, "ghost")}
          </div>
        ) : null}
      </div>
      {toast.action && !toast.secondaryAction ? actionButton(toast.action) : null}
      <IconButton size="sm" label={t("common.close")} onClick={() => toastStore.dismiss(toast.id)}
        icon={<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>} />
    </div>
  );
}

/** Where toasts appear; mounted once by notify(). */
export function ToastRegion() {
  const toasts = useSyncExternalStore(toastStore.subscribe, toastStore.list, toastStore.list);
  return (
    <section className="ui-toast-region" aria-label={t("common.notifications")}>
      {toasts.map((toast) => <ToastItem key={toast.id} toast={toast} />)}
    </section>
  );
}
