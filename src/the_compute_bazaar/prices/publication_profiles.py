"""Content-derived versions for immutable publication renderers."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


_ROOT = Path(__file__).parent
_SHARED_RENDER_INPUTS = (
    "publication_profiles.py",
    "publication_store.py",
    "publication_page.py",
    "publication_metadata.py",
    "publication_chart_common.py",
    "assets/fonts/Geist-Regular.ttf",
    "assets/fonts/Geist-Medium.ttf",
    "assets/fonts/Geist-SemiBold.ttf",
)


def _render_profile(name: str, *specific_inputs: str) -> str:
    """Fingerprint every source and asset that can alter a frozen preview."""
    digest = sha256()
    for relative_path in (*_SHARED_RENDER_INPUTS, *specific_inputs):
        path = _ROOT / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"social_png_rgb_1200x630_{name}_{digest.hexdigest()[:12]}"


WORKLOAD_PUBLICATION_RENDER_PROFILE = _render_profile(
    "workload_cost",
    "publication_sandbox_chart.py",
    "sandbox_publications.py",
)
GPU_PUBLICATION_RENDER_PROFILE = _render_profile(
    "gpu_index",
    "publication_gpu_chart.py",
    "gpu_publications.py",
)
PRIME_PUBLICATION_RENDER_PROFILE = _render_profile(
    "gpu_availability",
    "publication_prime_chart.py",
    "prime_publications.py",
)
