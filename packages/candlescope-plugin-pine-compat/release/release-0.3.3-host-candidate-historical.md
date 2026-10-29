# CandleScope Pine plugin 0.3.3

The Pine bridge uses the official `pine-compat-runtime` 0.3.3 release and
`candlescope-plugin-sdk` 0.2.1. Each platform lock binds the engine release
manifest, exact wheel bytes and deterministic analyze/execute probes. Bundles
install offline into isolated Python 3.12 workers.

- Native Pine risk declarations retain their effective constraints even inside
  conditional declarations. Repeated rules apply the strictest limit.
- Supplied linear contract point values, exact quantity increments and minima
  flow through sizing, execution, fees, margin and account reports.
- Requested-data updates preserve observation clocks and invalidate dependent
  contexts. Runtime window discovery restarts a tentative account execution
  without retaining its discarded orders, positions or cash movements.
- Historical account execution supports Pine OHLC observations. Physical trade
  and depth streams drive persistent realtime observations with causal source
  construction, closing passes and restored account history.
- Persistent worker sessions bind their identity once before accepting compact
  identity references. This keeps full results and recovery data while avoiding
  repeated immutable identity payloads on every observation.

The native interpreter and CandleScope host retain separate responsibilities.
These deterministic compatibility controls do not establish arbitrary
TradingView/Renko construction equivalence, exchange queue priority or connected
live-feed qualification. Core resource measurements cover Windows and Linux;
macOS wheel installation is checked in CI. Desktop UI and recovery qualification
are recorded separately from plugin protocol probes.
