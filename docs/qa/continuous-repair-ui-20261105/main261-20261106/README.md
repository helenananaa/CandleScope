# PR258 dependency integration on main261

Source `142a348ddccde98ee292e7226a64af2ba41c688a` merges prior `78a33525d26e166eac20a31c51006e455c8be9ea` with the previous qualified
dependency `b56dac312f3682d13596601c6284c23d2d6075dc`, without conflicts. Includes main261 `0de39f37f2389b09a35fc91e3a6d8d5844137da8`.
Original feature scope and its source-specific evidence remain in the parent README.

Current combined backend regression: **423 passed / 2 Windows-only
skips / 5 existing warnings**. This includes all present continuous tests,
Manager/profile/shutdown, actual Python processes, financial/source/cache contracts
and applicable HTTP/WS/repair cases. The skips are Windows AppContainer and ACL
lifecycle tests, not Windows passes. The10 architecture findings remain byte-equal
to the recorded actual-main261 baseline. Source/file/tree fingerprints, precise
command and isolated environment are recorded beside the complete log.

This run does not repeat frontend/browser/package/Native/save/full-quit/restart or
Windows/public-market qualification. Frontend changes are checked on the final
integrated research stack separately. No user profile or public feed was used.
CI runs in the background; main merging requires exact-head/current-base checks.
Keep Draft; preserve original incomplete Native and broader issue boundaries.
