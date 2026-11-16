import { useState } from "react";

import { Button, InlineAlert, buttonClassName } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { dismissCompatNotice, isCompatNoticeDismissed } from "./strategyResearchCompat.js";

export function StrategyResearchCompatNotice({ page }: { page: "local" | "backtest" }) {
  useLocale();
  const [dismissed, setDismissed] = useState(() => isCompatNoticeDismissed());
  if (dismissed) return null;
  return (
    <aside
      className="strategy-research-compat-notice"
      role="note"
      data-testid="strategy-research-compat-notice"
      data-compat-page={page}
    >
      <InlineAlert
        tone="info"
        action={<>
          <a href="/strategy.html" className={buttonClassName({ variant: "ghost", size: "sm" })}>{t("strategy.compat.canonical")}</a>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              dismissCompatNotice();
              setDismissed(true);
            }}
          >
            {t("strategy.compat.dismiss")}
          </Button>
        </>}
      >
        {page === "local" ? t("strategy.compat.local") : t("strategy.compat.backtest")}
      </InlineAlert>
    </aside>
  );
}
