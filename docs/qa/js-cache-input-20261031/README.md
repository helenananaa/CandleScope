# #164 bounded JS cache inputs

The runtime now subscribes to immutable shared market facts over its explicit chart-window range. Shared-cache correction notifications can trigger JS calculation before that chart publishes its own projection. Per-consumer retention and input version/ownership fences remain separate from Worker execution and existing result-cache admission.

Validation: 19 targeted input/broker/cache tests; 4,673 frontend tests plus one isolated performance gate; 124 desktop tests; architecture, plugin, i18n, TypeScript, lint and production build checks. Lint retains the existing SingleChartPanes cleanup warning; build retains existing chunk-size warnings.

Production Chromium passed 11 real-runtime indicator-flow checks, 12 JavaScript/replay checks and three editor checks. Transports are controlled; real React/chart/isolated Workers execute. Final unmount releases input leases and all Workers. JSON receipts and SHA-256 source manifest are adjacent.

The exact-source installed native package is still to be qualified. Broader #164 result-subscription/recovery consolidation remains open; no persistent Worker or incremental SDK work is included. This does not close #164 or certify the full release matrix.
