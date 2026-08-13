"""Build provenance embedded in deployed Compute Bazaar workers."""

from __future__ import annotations

import os


def build_revision() -> str:
    """Return the exact Git revision supplied while building the worker image."""
    return os.getenv("COMPUTE_BAZAAR_REVISION", "unknown")
