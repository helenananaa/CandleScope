# CandleScope Pine bridge 0.4.0 candidate

Targets the official Pine 0.3.3 runtime. Adds shared library/metadata/clock inputs,
compiled dependency discovery, native drawing scenes, durable observed-session
recovery, and opt-in confirmed live-bar notifications. Native and host-matched
strategy entry points share the validated inputs. Host matching retains account
authority; evaluated Renko descriptors retain the existing causal prefix path.

These are candidate source pins. All platform installation jobs must pass before
a release tag is created. The public plugin catalog is unchanged by this PR.

Calendar/FX/session data remain explicit inputs. Recovery cannot reconstruct ticks
missed while disconnected. Drawing typography/layout is approximate, and this is
not a claim of complete TradingView equivalence.
