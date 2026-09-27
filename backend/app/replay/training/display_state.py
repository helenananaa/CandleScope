"""Display state shared by training coordinators."""

from __future__ import annotations

_NATIVE_DISPLAY_PIN_PROOF_CACHE_SIZE = 4_096


_NativeDisplayPinProofKey = tuple[str, str, str, str, str, int, int, int, str]


_NativeDisplayPinProof = tuple[int, str, int]
