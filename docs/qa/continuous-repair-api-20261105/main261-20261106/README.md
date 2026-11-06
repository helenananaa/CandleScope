# PR257 dependency integration on main261

Source `1f2306c37c7be7fbd7f9f3df62a29b0253424e43` merges prior `d159c590d985fa469d51f5ddc82943b559d0eb43` with the previous qualified
dependency `5c34df78425a7fa99709ca4fac8c31d370d1b7c9`, without conflicts. Includes main261 `0de39f37f2389b09a35fc91e3a6d8d5844137da8`.
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
