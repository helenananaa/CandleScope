import { canResolveIntervalFromNativeValues } from "../../utils/intervals.js";
import type { IntervalSelectorProps } from "../../components/IntervalSelector.js";
import type { AppShellViewModelContext } from "../appShellContracts.js";

export function buildIntervalSelectorViewModel({
  sessionActions,
  sessionStatus,
  sessionView,
}: AppShellViewModelContext): IntervalSelectorProps {
  const {
    interval,
    nativeIntervals,
    intervalGroups,
    customIntervalRecords,
    savedCustomIntervals,
    intervalNotice,
  } = sessionView;

  return {
    interval,
    capabilityReady: sessionStatus.exchangeCapabilityAvailable,
    capabilityLoading: sessionStatus.exchangeCatalogStatus === "loading",
    nativeIntervals,
    intervalGroups,
    customIntervalRecords,
    savedCustomIntervals,
    onSelectInterval: sessionActions.selectInterval,
    onCreateCustomInterval: sessionActions.createCustomInterval,
    onRemoveCustomInterval: sessionActions.removeCustomInterval,
    onRestoreCustomInterval: sessionActions.restoreCustomInterval,
    onTogglePinCustomInterval: sessionActions.togglePinCustomInterval,
    onClearCustomIntervals: sessionActions.clearCustomIntervals,
    intervalNotice,
    intervalAvailability: (value) => canResolveIntervalFromNativeValues(value, nativeIntervals.map((item) => item.value), sessionStatus.tradeCandlesAvailable),
  };
}
