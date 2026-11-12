import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import type { ControlSize } from "./Button.js";
import { choiceKeyTarget, tabId, tabPanelId } from "./helpers.js";

export interface ChoiceOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  /** Accessible name when the label is an icon only. */
  ariaLabel?: string;
}

function useRovingKeys<T extends string>(options: readonly ChoiceOption<T>[], value: T, onChange: (value: T) => void) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const target = choiceKeyTarget(event.key, index, options.map((o) => Boolean(o.disabled)));
    if (target == null || target === index) return;
    event.preventDefault();
    const option = options[target];
    if (!option) return;
    onChange(option.value);
    refs.current[target]?.focus();
  };
  const tabIndexFor = (option: ChoiceOption<T>) => {
    const selectedEnabled = options.some((o) => o.value === value && !o.disabled);
    if (selectedEnabled) return option.value === value ? 0 : -1;
    return options.find((o) => !o.disabled)?.value === option.value ? 0 : -1;
  };
  return { refs, onKeyDown, tabIndexFor };
}

export interface SegmentedControlProps<T extends string> {
  /** Accessible name of the group. */
  label: string;
  value: T;
  options: readonly ChoiceOption<T>[];
  onChange: (value: T) => void;
  size?: ControlSize;
  /** Stretch segments to fill the row. */
  fullWidth?: boolean;
  className?: string;
}

/** One choice out of two to five, shown side by side. Arrow keys move and select. */
export function SegmentedControl<T extends string>({ label, value, options, onChange, size = "md", fullWidth = false, className }: SegmentedControlProps<T>) {
  const { refs, onKeyDown, tabIndexFor } = useRovingKeys(options, value, onChange);
  const classes = ["ui-segmented", size === "sm" ? "ui-segmented-sm" : null, fullWidth ? "ui-segmented-block" : null, className].filter(Boolean).join(" ");
  return (
    <div role="radiogroup" aria-label={label} className={classes}>
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={(el) => { refs.current[index] = el; }}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          aria-label={option.ariaLabel}
          tabIndex={tabIndexFor(option)}
          disabled={option.disabled}
          className="ui-segment"
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {option.icon ? <span className="ui-segment-icon" aria-hidden="true">{option.icon}</span> : null}
          {option.label}
        </button>
      ))}
    </div>
  );
}

export interface TabsProps<T extends string> {
  label: string;
  value: T;
  tabs: readonly (ChoiceOption<T> & { badge?: ReactNode })[];
  onChange: (value: T) => void;
  /** Base id linking tabs and panels; pass the same id to TabPanel. */
  id?: string;
  className?: string;
}

/** Tab list. Render the selected content in a TabPanel with the same id. */
export function Tabs<T extends string>({ label, value, tabs, onChange, id, className }: TabsProps<T>) {
  const fallbackId = useId();
  const base = id ?? fallbackId;
  const { refs, onKeyDown, tabIndexFor } = useRovingKeys(tabs, value, onChange);
  return (
    <div role="tablist" aria-label={label} className={["ui-tabs", className].filter(Boolean).join(" ")}>
      {tabs.map((tab, index) => (
        <button
          key={tab.value}
          ref={(el) => { refs.current[index] = el; }}
          type="button"
          role="tab"
          id={tabId(base, tab.value)}
          aria-selected={tab.value === value}
          aria-controls={tabPanelId(base, tab.value)}
          aria-label={tab.ariaLabel}
          tabIndex={tabIndexFor(tab)}
          disabled={tab.disabled}
          className="ui-tab"
          onClick={() => onChange(tab.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {tab.icon ? <span className="ui-tab-icon" aria-hidden="true">{tab.icon}</span> : null}
          {tab.label}
          {tab.badge != null ? <span className="ui-tab-badge">{tab.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}

export interface TabPanelProps {
  /** The id passed to Tabs. */
  tabsId: string;
  value: string;
  className?: string;
  children: ReactNode;
}

export function TabPanel({ tabsId, value, className, children }: TabPanelProps) {
  return (
    <div role="tabpanel" id={tabPanelId(tabsId, value)} aria-labelledby={tabId(tabsId, value)} tabIndex={0} className={["ui-tab-panel", className].filter(Boolean).join(" ")}>
      {children}
    </div>
  );
}
