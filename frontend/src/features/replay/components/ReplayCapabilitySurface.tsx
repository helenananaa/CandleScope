import React from "react";
import { Badge } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ReplayCapabilityModel, ReplayCapabilityState } from "../replayCapabilityModel.js";


export interface ReplayCapabilitySurfaceProps {
  readonly capabilities: ReplayCapabilityModel;
}

function stateBadge(state: ReplayCapabilityState): { tone: "success" | "warning" | "neutral"; label: string } {
  if (state === "AVAILABLE_EXACT") return { tone: "success", label: t("replay.capability.exact") };
  if (state === "AVAILABLE_APPROX") return { tone: "warning", label: t("replay.capability.approx") };
  return { tone: "neutral", label: t("replay.capability.unsupported") };
}

/** What this run's history can show: one row per capability, its state as a badge and why. The state code stays in data-capability-state. */
function ReplayCapabilitySurface({ capabilities }: ReplayCapabilitySurfaceProps) {
  useLocale();
  return (
    <section className="replay-capability-surface" aria-label={t("replay.capability.aria")} data-replay-panel="capabilities">
      <header>
        <strong>{t("replay.capability.title")}</strong>
        <p>{t("replay.capability.hint")}</p>
      </header>
      <ul className="replay-capability-list">
        {Object.entries(capabilities).map(([id, capability]) => {
          const badge = stateBadge(capability.state);
          return (
            <li key={id} data-replay-capability={id} data-capability-state={capability.state}>
              <div className="replay-capability-head">
                <strong>{capability.label}</strong>
                {capability.value !== "--" && <code>{capability.value}</code>}
                <Badge tone={badge.tone}>{badge.label}</Badge>
              </div>
              <p>{capability.detail}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default React.memo(ReplayCapabilitySurface);
