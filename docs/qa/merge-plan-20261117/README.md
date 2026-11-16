# PR integration acceptance — 2026-11-17

This candidate composes the latest #436 product with main after #442 and #443.
The macOS arm64 runtime/plugins come from the verified main CI artifact at be8ae299; all tracked backend application files and a freshly built current frontend are overlaid on a new copy and strictly signed. This is retained-runtime native evidence, not a fresh release or Windows acceptance.

The driver uses an empty isolated profile, real public Binance USD-M history, unchanged 128-bar / 180-second per-cell readiness, independent market and EMA checks, ten minutes of actual renderer updates, native hide/restore, interval switching, reconstruction and saved exit/restart. No market seed, response substitution or diagnostic bootstrap is enabled. Each minute must produce a distinct rendered tail state for every chart.

Results: pending the new run. Historical native passes are not qualification of this integration.
