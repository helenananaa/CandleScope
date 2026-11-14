import { Fragment } from "react";
import { Icon, type IconName } from "../../components/icons/Icon.js";
import { t, type MessageKey } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { StrategyResearchMode } from "./strategyResearchMode.js";

const MODES: ReadonlyArray<{ mode: StrategyResearchMode; icon: IconName; label: MessageKey; title: MessageKey; detail: MessageKey }> = [
  { mode: "quick", icon: "play", label: "strategy.mode.quick", title: "strategy.mode.quick", detail: "strategy.mode.quickDetail" },
  { mode: "precise", icon: "check", label: "strategy.mode.precise", title: "research.task.precise.title", detail: "research.task.precise.detail" },
  { mode: "robust", icon: "sliders", label: "strategy.mode.robust", title: "research.task.robust.title", detail: "research.task.robust.detail" },
  { mode: "python", icon: "bot", label: "strategy.mode.python", title: "research.task.python.title", detail: "research.task.python.detail" },
  { mode: "multi", icon: "exchange", label: "strategy.mode.multi", title: "research.task.multi.title", detail: "research.task.multi.detail" },
  { mode: "replay", icon: "book", label: "strategy.mode.replay", title: "research.task.replay.title", detail: "research.task.replay.detail" },
];

/** Left mode rail of the strategy research page: 快速测试 and the five research tools. */
export default function StrategyResearchModeRail({
  mode,
  pending = false,
  onSelect,
}: {
  /** Null while a launch context is still choosing its tool. */
  mode: StrategyResearchMode | null;
  pending?: boolean;
  onSelect(mode: StrategyResearchMode): void;
}) {
  useLocale();
  return (
    <nav className="research-mode-rail" aria-label={t("strategy.mode.rail")} aria-busy={pending || undefined} data-testid="research-mode-rail">
      {MODES.map((item, index) => (
        <Fragment key={item.mode}>
          {index === 1 && <span className="research-mode-rail-divider" aria-hidden="true" />}
          <button
            type="button"
            className="research-mode-item"
            data-mode={item.mode}
            aria-current={mode === item.mode ? "page" : undefined}
            title={`${t(item.title)} · ${t(item.detail)}`}
            disabled={pending}
            onClick={() => onSelect(item.mode)}
          >
            <Icon name={item.icon} size={18} />
            <span>{t(item.label)}</span>
          </button>
        </Fragment>
      ))}
    </nav>
  );
}
