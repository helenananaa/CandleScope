import { t } from "../../i18n/index.js";
import {
  getIntervalSemanticSpec,
  intervalsSemanticallyEquivalent,
  intervalTiles,
  formatIntervalLabel,
} from "../../utils/intervals.js";

import type { LocalDatasetManifest } from "./localDataTypes.js";


export const MAX_LOCAL_RESAMPLE_FACTOR = 10_000;

export interface LocalIntervalSupport {
  supported: boolean;
  source: string;
  target: string;
  factor: number | null;
  derived: boolean;
  code: string | null;
  message: string;
}

const COMMON_LOCAL_INTERVALS = [
  "1s", "1m", "3m", "5m", "15m", "30m", "1h", "90m", "2h", "4h", "6h", "12h", "1d",
] as const;

function unsupported(
  source: string,
  target: string,
  code: string,
  message: string,
): LocalIntervalSupport {
  return { supported: false, source, target, factor: null, derived: false, code, message };
}

export function resolveLocalIntervalSupport(
  manifest: Pick<LocalDatasetManifest, "interval" | "alignment_offset_ms"> &
    Partial<Pick<LocalDatasetManifest, "first_open_ms">>,
  requestedInterval: string,
): LocalIntervalSupport {
  const sourceSpec = getIntervalSemanticSpec(manifest.interval);
  const targetSpec = getIntervalSemanticSpec(requestedInterval);
  const source = sourceSpec?.canonicalValue ?? manifest.interval;
  const target = targetSpec?.canonicalValue ?? requestedInterval.trim();
  if (!sourceSpec) {
    return unsupported(source, target, "dataset_corrupt", t("local.int.unrecognized", { interval: manifest.interval }));
  }
  if (!targetSpec) {
    return unsupported(source, target, "interval_not_available", t("local.int.badFormat"));
  }
  if (intervalsSemanticallyEquivalent(source, target)) {
    return {
      supported: true,
      source,
      target: source,
      factor: 1,
      derived: false,
      code: null,
      message: t("local.int.source", { source }),
    };
  }
  const sourceWidth = sourceSpec.widthSeconds;
  const targetWidth = targetSpec.widthSeconds;
  if (sourceWidth === null || targetWidth === null || sourceSpec.timezone) {
    return unsupported(
      source,
      target,
      "interval_not_composable",
      t("local.int.fixedOnly"),
    );
  }
  if (targetWidth <= sourceWidth) {
    return unsupported(
      source,
      target,
      "interval_not_composable",
      t("local.int.noDownsample", { target, source }),
    );
  }
  const alignmentOffsetMs = manifest.alignment_offset_ms
    ?? (manifest.first_open_ms === undefined
      ? -1
      : manifest.first_open_ms % (sourceWidth * 1_000));
  if (alignmentOffsetMs !== (sourceSpec.phaseSeconds ?? 0) * 1000) {
    return unsupported(
      source,
      target,
      "interval_alignment_incompatible",
      t("local.int.notUtc", { source }),
    );
  }
  if ((!targetSpec.timezone && targetWidth % sourceWidth !== 0) || !intervalTiles(source, target)) {
    return unsupported(
      source,
      target,
      "interval_not_composable",
      t("local.int.notMultiple", { target, source }),
    );
  }
  const maximumWidth = targetSpec.timezone ? targetSpec.amount * ({ d: 1, w: 7, M: 31 }[targetSpec.unit as "d" | "w" | "M"]) * 86400 + 7200 : targetWidth;
  const factor = Math.ceil(maximumWidth / sourceWidth);
  const factorLimit = targetSpec.timezone ? 600_000 : MAX_LOCAL_RESAMPLE_FACTOR;
  if (factor > factorLimit) {
    return unsupported(
      source,
      target,
      "interval_resample_factor_too_large",
      t("local.int.factorTooBig", { factor, source, limit: factorLimit }),
    );
  }
  return {
    supported: true,
    source,
    target,
    factor,
    derived: true,
    code: null,
    message: targetSpec.timezone ? t("interval.calendarHelp") : t("local.int.compose", { factor, source: formatIntervalLabel(source), target: formatIntervalLabel(target) }),
  };
}

export function getCommonLocalIntervals(
  manifest: Pick<LocalDatasetManifest, "interval" | "alignment_offset_ms"> &
    Partial<Pick<LocalDatasetManifest, "first_open_ms">>,
): string[] {
  const candidates = [manifest.interval, ...COMMON_LOCAL_INTERVALS];
  const seen = new Set<string>();
  return candidates.filter((candidate) => {
    const support = resolveLocalIntervalSupport(manifest, candidate);
    if (!support.supported || seen.has(support.target)) return false;
    seen.add(support.target);
    return true;
  });
}
