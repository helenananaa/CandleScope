# Archive probing outside the readiness chain

Related #124/#125/#127. The original startup awaited public archive resolution,
download and parsing before wiring BackfillCoordinator or starting DataManager.
A slow optional archive source could therefore prevent local HTTP/WS readiness.

The runtime now starts one owned background qualification task after its normal
components are attached. The router still verifies every unqualified cold route.
Startup and on-demand readers share one probe per provider; cancelling a waiter
does not cancel another's qualification. Shutdown first cancels the runtime
waiter, then the archive owner drains/cancels probe downloads before transports
close. Failed/ambiguous probes never enter the passed set. Existing cooldown and
permanent compatibility rejection remain in their original owner.

The actual `start_data_engine()` test with a controlled blocked probe fails on
unchanged main before coordinator wiring/DM start; the fixed runtime returns and
shutdown proves cancellation order. Four additional cases cover shared probe
waiters, independent cancellation, router close, temporary and format failures.

**206 passed**, including all archive suites, runtime market-data owners and
architecture boundaries. Backend architecture and whitespace passed. The first
broad invocation ran from the repo root and three subprocess crash tests could
not import `app`; the correct backend working-directory rerun passed all 206.
[Raw final logs/XML and baseline failure](evidence/index.json).

This is startup/readiness and qualification lifecycle evidence. It does not by
itself qualify cold public history completion, source capability expansion,
network speed or native desktop startup latency. Native qualification follows
against the exact integrated package.
