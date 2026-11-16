import { replayCapabilityStateLabel } from "../trainingHubLabels.js";
import React from "react";
import { Badge } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ReplayCapabilityModel, ReplayCapabilityState } from "../replayCapabilityModel.js";


export interface ReplayCapabilitySurfaceProps {
  readonly capabilities: ReplayCapabilityModel;
}

function stateBadge(state: ReplayCapabilityState): { tone: "success" | "warning" | "neutral"; label: string } {
  const label = replayCapabilityStateLabel(state);
  if (state === "AVAILABLE_EXACT") return { tone: "success", label };
  if (state === "AVAILABLE_APPROX") return { tone: "warning", label };
  return { tone: "neutral", label };
}

/** What this run's history can show: one row per capability, its level as a badge and why. The state and value codes stay in data attributes (the value also as a tooltip). */
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
            <li key={id} data-replay-capability={id} data-capability-state={capability.state}
              data-capability-value={capability.value} {...(capability.value !== "--" ? { title: capability.value } : {})}>
              <div className="replay-capability-head">
                <strong>{capability.label}</strong>
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
