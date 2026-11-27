import React, { useEffect } from "react";
import type { ErrorInfo, PropsWithChildren, ReactNode } from "react";
import { t } from "../i18n/index.js";
import { Button } from "../components/ui/index.js";
import { ExtensionRecovery } from "../features/extensions/ExtensionManager.js";
import { startUnified } from "../features/extensions/unifiedRuntime.js";
import { installTouchLongPress } from "./touchLongPress.js";
import BackendStatusBanner from "./BackendStatusBanner.js";

export type ChartErrorBoundaryProps = PropsWithChildren;

interface ChartErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ChartErrorBoundary extends React.Component<
  ChartErrorBoundaryProps,
  ChartErrorBoundaryState
> {
  constructor(props: ChartErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ChartErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="app-crash">
          <div className="app-crash-mark" aria-hidden="true">!</div>
          <div className="app-crash-title">{t("shell.chartErrorTitle")}</div>
          <div className="app-crash-detail">{t("shell.chartErrorDetail")}</div>
          <Button variant="primary" onClick={() => this.setState({ hasError: false, error: null })}>
            {t("shell.retry")}
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function AppProviders({ children }: PropsWithChildren): ReactNode {
  useEffect(() => { startUnified(); }, []);
  useEffect(() => installTouchLongPress(), []);
  return <>{children}<ExtensionRecovery /><BackendStatusBanner /></>;
}
