"""Build provenance embedded in deployed Compute Bazaar workers."""

from __future__ import annotations

import os

from ._build_revision import BUILD_REVISION


def build_revision() -> str:
    """Return the exact Git revision supplied while building the worker image."""
    if BUILD_REVISION != "unknown":
        return BUILD_REVISION
    return os.getenv("COMPUTE_BAZAAR_REVISION", "unknown")
