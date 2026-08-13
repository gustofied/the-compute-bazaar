"""Stable local identity for one Compute Bazaar checkout."""

from __future__ import annotations

import hashlib
from pathlib import Path


def project_identity(project_root: Path) -> str:
    return hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:12]


def native_session_cookie(project_root: Path) -> str:
    return f"compute_bazaar_terminal_session_{project_identity(project_root)}"
