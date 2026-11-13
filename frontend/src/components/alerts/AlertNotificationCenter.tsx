import { useCallback, useEffect, useRef } from "react";
import { dismissToast, notify } from "../ui/overlay/overlayApi.js";
import { toastStore } from "../ui/overlay/toastStore.js";
import { useControlCommands } from "../../features/app-control/useControlCommands.js";
import { command } from "../../features/app-control/commandRegistry.js";
import { empty, object, text } from "../../features/app-control/commandSchema.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";

import {
  buildAlertEventStreamUrl,
  recordAlertDispatchReceipt,
} from "../../features/alerts/alertsClient.js";
import {
  ALERT_RULE_STATE_CHANGED_EVENT,
  deliverAlertNotification,
} from "../../features/alerts/alertDeliveryClient.js";
import {
  parseAlertNotificationMessage,
} from "../../features/alerts/alertTypes.js";
import type { AlertNotificationMessage } from "../../features/alerts/alertTypes.js";

export interface AlertNotificationCenterProps {
  onOpenAlerts(): void;
}

const TOAST_LIFETIME_MS = 15_000;

/**
 * Listens for fired alerts and shows them on the shared toast stack (`notify`), above dialogs,
 * with 打开警报 as their action. Alert toasts are keyed by dispatch so automation can dismiss them.
 */
export default function AlertNotificationCenter({ onOpenAlerts }: AlertNotificationCenterProps) {
  useLocale();
  // Dispatch key → toast id on the shared stack.
  const toastIdsRef = useRef(new Map<string, number>());
  const seenDispatchesRef = useRef(new Set<string>());
  const seenEventsRef = useRef(new Set<string>());

  const show = useCallback((key: string, options: Parameters<typeof notify>[0]) => {
    const previous = toastIdsRef.current.get(key);
    if (previous !== undefined) dismissToast(previous);
    toastIdsRef.current.set(key, notify(options));
    if (toastIdsRef.current.size > 64) toastIdsRef.current = new Map([...toastIdsRef.current].slice(-32));
  }, []);

  const publishToast = useCallback((notification: AlertNotificationMessage) => {
    const symbol = notification.target.symbol || "--";
    show(notification.dispatchId, {
      tone: "info",
      title: t("alert.toastHit", { symbol }),
      message: notification.message || t("alert.toastDefault", { symbol }),
      action: { label: t("alert.openAlerts"), onClick: onOpenAlerts },
      durationMs: TOAST_LIFETIME_MS,
    });
  }, [onOpenAlerts, show]);

  const publishDeliveryError = useCallback((notification: AlertNotificationMessage, detail: string) => {
    show(`delivery-error-${notification.dispatchId}`, {
      tone: "danger",
      title: t("alert.toastFailed"),
      message: [notification.message, detail].filter(Boolean).join(" · "),
      action: { label: t("alert.openAlerts"), onClick: onOpenAlerts },
      durationMs: TOAST_LIFETIME_MS,
    });
  }, [onOpenAlerts, show]);

  const activeToasts = () => {
    const live = new Set(toastStore.list().map((toast) => toast.id));
    return [...toastIdsRef.current].filter(([, id]) => live.has(id)).map(([key]) => key);
  };

  useEffect(() => {
    if (typeof EventSource === "undefined") return undefined;
    const source = new EventSource(buildAlertEventStreamUrl());
    const handleNotification = (event: MessageEvent<string>) => {
      void (async () => {
        let notification: AlertNotificationMessage;
        try {
          const value: unknown = JSON.parse(event.data);
          notification = parseAlertNotificationMessage(value);
        } catch (error: unknown) {
          console.error("Invalid alert notification payload", error);
          return;
        }
        if (seenDispatchesRef.current.has(notification.dispatchId)) return;
        seenDispatchesRef.current.add(notification.dispatchId);
        if (seenDispatchesRef.current.size > 512) {
          seenDispatchesRef.current = new Set([notification.dispatchId]);
        }
        if (!seenEventsRef.current.has(notification.eventId)) {
          seenEventsRef.current.add(notification.eventId);
          if (seenEventsRef.current.size > 512) {
            seenEventsRef.current = new Set([notification.eventId]);
          }
          window.dispatchEvent(new CustomEvent(ALERT_RULE_STATE_CHANGED_EVENT, {
            detail: {
              eventId: notification.eventId,
              ruleId: notification.ruleId,
            },
          }));
        }

        const receipt = await deliverAlertNotification(notification, publishToast, onOpenAlerts);
        if (receipt.status !== "delivered" && notification.action.type !== "in_app") {
          publishDeliveryError(notification, receipt.detail);
        }
        try {
          await recordAlertDispatchReceipt(
            notification.eventId,
            notification.dispatchId,
            receipt.status,
            receipt.detail,
          );
        } catch (error: unknown) {
          console.warn("Failed to record alert delivery receipt", error);
        }
      })();
    };
    source.addEventListener("alert.notification", handleNotification as EventListener);
    return () => {
      source.removeEventListener("alert.notification", handleNotification as EventListener);
      source.close();
    };
  }, [onOpenAlerts, publishDeliveryError, publishToast]);

  useControlCommands(() => ({ id: "alert-notifications", title: "Alert notification center", context: () => activeToasts(), snapshot: () => ({ toasts: activeToasts() }), commands: [
    command("dismiss", "Dismiss a current notification toast.", object({ toastId: text(128) }), ({ toastId }) => {
      const id = toastIdsRef.current.get(toastId);
      if (id === undefined || !activeToasts().includes(toastId)) throw new Error("TOAST_UNAVAILABLE");
      dismissToast(id);
    }),
    command("openAlerts", "Open the existing alerts panel.", empty, onOpenAlerts),
  ] }));
  return null;
}
