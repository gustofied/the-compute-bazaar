"""Provider-neutral GPU naming helpers."""

from __future__ import annotations

from collections.abc import Callable


def _has_vram(gpu_ram_mb: float | int | None, gib: int) -> bool:
    if gpu_ram_mb is None:
        return True
    return float(gpu_ram_mb) >= gib * 1024 * 0.9


GpuRule = tuple[Callable[[str], bool], int, str]


GPU_RULES: list[GpuRule] = [
    (lambda n: n == "A10", 24, "A10_24GB"),
    (lambda n: n == "A40", 48, "A40_48GB"),
    (lambda n: n == "L4", 24, "L4_24GB"),
    (lambda n: n == "L40", 48, "L40_48GB"),
    (lambda n: n == "L40S", 48, "L40S_48GB"),
    (lambda n: n == "RTX 2080 TI", 11, "RTX2080Ti_11GB"),
    (lambda n: n == "RTX 3060 TI", 8, "RTX3060Ti_8GB"),
    (lambda n: n == "RTX 3060", 12, "RTX3060_12GB"),
    (lambda n: n == "RTX 3070 TI", 8, "RTX3070Ti_8GB"),
    (lambda n: n == "RTX 3070", 8, "RTX3070_8GB"),
    (lambda n: n == "RTX 3080 TI", 12, "RTX3080Ti_12GB"),
    (lambda n: n == "RTX 3080", 10, "RTX3080_10GB"),
    (lambda n: n == "RTX 3090 TI", 24, "RTX3090Ti_24GB"),
    (lambda n: n == "RTX 3090", 24, "RTX3090_24GB"),
    (lambda n: n == "RTX 4060", 8, "RTX4060_8GB"),
    (lambda n: n == "RTX 4060 TI", 16, "RTX4060Ti_16GB"),
    (lambda n: n == "RTX 4070 TI", 12, "RTX4070Ti_12GB"),
    (lambda n: n == "RTX 4070", 12, "RTX4070_12GB"),
    (lambda n: n == "RTX 4070S TI", 16, "RTX4070STi_16GB"),
    (lambda n: n == "RTX 4070S", 12, "RTX4070S_12GB"),
    (lambda n: n == "RTX 4080", 16, "RTX4080_16GB"),
    (lambda n: n == "RTX 4080S", 16, "RTX4080S_16GB"),
    (lambda n: n == "RTX 4090", 24, "RTX4090_24GB"),
    (lambda n: n == "RTX 5000ADA", 32, "RTX5000Ada_32GB"),
    (lambda n: n == "RTX 5060", 8, "RTX5060_8GB"),
    (lambda n: n == "RTX 5060 TI", 8, "RTX5060Ti_8GB"),
    (lambda n: n == "RTX 5060 TI", 16, "RTX5060Ti_16GB"),
    (lambda n: n == "RTX 5070 TI", 16, "RTX5070Ti_16GB"),
    (lambda n: n == "RTX 5070", 12, "RTX5070_12GB"),
    (lambda n: n == "RTX 5080", 16, "RTX5080_16GB"),
    (lambda n: n == "RTX 5090", 32, "RTX5090_32GB"),
    (lambda n: n == "RTX 6000ADA", 48, "RTX6000Ada_48GB"),
    (lambda n: n == "RTX A4000", 16, "A4000_16GB"),
    (lambda n: n == "RTX A4500", 20, "A4500_20GB"),
    (lambda n: n == "RTX A5000", 24, "A5000_24GB"),
    (lambda n: n == "RTX A6000", 48, "A6000_48GB"),
    (lambda n: n == "TESLA V100", 16, "V100_16GB"),
    (lambda n: n == "TESLA V100", 32, "V100_32GB"),
    (lambda n: n == "TESLA P100", 12, "P100_12GB"),
    (lambda n: n == "TESLA P100", 16, "P100_16GB"),
    (lambda n: n == "TESLA P40", 24, "P40_24GB"),
    (lambda n: n.startswith("RTX PRO 4000"), 24, "RTXPro4000B_24GB"),
    (lambda n: n.startswith("RTX PRO 4500"), 32, "RTXPro4500B_32GB"),
    (lambda n: n.startswith("RTX PRO 5000"), 48, "RTXPro5000B_48GB"),
    (lambda n: n.startswith("RTX PRO 6000"), 96, "RTXPro6000B_96GB"),
    (lambda n: n.startswith("A100"), 40, "A100_40GB"),
    (lambda n: n.startswith("A100"), 80, "A100_80GB"),
    (lambda n: n.startswith("H100"), 80, "H100_80GB"),
    (lambda n: n.startswith("H200"), 141, "H200_141GB"),
    (lambda n: n.startswith("B200"), 180, "B200_180GB"),
    (lambda n: n.startswith("B300"), 288, "B300_288GB"),
]


def canonical_gpu_model(gpu_name: str, gpu_ram_mb: float | int | None = None) -> str | None:
    normalized = " ".join(gpu_name.replace("_", " ").upper().split())
    matches = [
        canonical
        for predicate, vram_gb, canonical in GPU_RULES
        if predicate(normalized) and _has_vram(gpu_ram_mb, vram_gb)
    ]
    if not matches:
        return None
    return matches[-1]

