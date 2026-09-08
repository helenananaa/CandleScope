export interface ReplayOrderCtaStateInput {
  readonly permanentlyUnavailable: boolean;
  readonly transientlyBlocked: boolean;
  readonly submitting: boolean;
}

export interface ReplayOrderCtaState {
  readonly disabled: boolean;
  readonly ariaDisabled: boolean;
}

/**
 * Keep the order CTA visually stable while an unrelated replay command is in
 * flight. It still blocks activation through aria-disabled and the click guard.
 * Advisory quotes are preemptible: submission performs its own fresh checks.
 * Only a real submission or durable validation failure uses native disabled.
 */
export function replayOrderCtaState({
  permanentlyUnavailable,
  transientlyBlocked,
  submitting,
}: ReplayOrderCtaStateInput): ReplayOrderCtaState {
  const disabled = permanentlyUnavailable || submitting;
  return {
    disabled,
    ariaDisabled: disabled || transientlyBlocked,
  };
}
