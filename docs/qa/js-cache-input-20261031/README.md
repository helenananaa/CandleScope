# #164 bounded JS cache inputs

The runtime now subscribes to immutable shared market facts over its explicit chart-window range. Shared-cache correction notifications can trigger JS calculation before that chart publishes its own projection. Per-consumer retention and input version/ownership fences remain separate from Worker execution and existing result-cache admission.

Validation: 19 targeted input/broker/cache tests; 4,673 frontend tests plus one isolated performance gate; 124 desktop tests; architecture, plugin, i18n, TypeScript, lint and production build checks. Lint retains the existing SingleChartPanes cleanup warning; build retains existing chunk-size warnings.

Production Chromium passed 11 real-runtime indicator-flow checks, 12 JavaScript/replay checks and three editor checks. Transports are controlled; real React/chart/isolated Workers execute. Final unmount releases input leases and all Workers. JSON receipts and SHA-256 source manifest are adjacent.

The macOS arm64 ZIP was subsequently qualified on 2026-11-01, after fixing a cold-market chart rendering failure found in the original package. See [installed-package acceptance](../js-cache-native-20261101/README.md) for the exact source/archive, failure and repair evidence, live-data value comparisons, disconnect recovery and full-exit/restart results. Reopening follows the existing latest-bar policy while retaining zoom and chart configuration. Broader #164 result-subscription/recovery consolidation remains open; no persistent Worker or incremental SDK work is included. This does not close #164 or certify the full release matrix.
