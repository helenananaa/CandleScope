"""Unified package contracts; importing this module never executes plugins.

The unified host consumes these contracts; legacy consumers migrate separately.
See docs/UNIFIED_PLUGIN_IMPLEMENTATION_zh.md for rollout and retirement gates.
"""

from .manifest import MANIFEST_SCHEMA, Entry, Manifest, ManifestError
from .planning import ActivationIdentity, PlanError, activation_order

__all__ = [
    "MANIFEST_SCHEMA",
    "ActivationIdentity",
    "Entry",
    "Manifest",
    "ManifestError",
    "PlanError",
    "activation_order",
]
