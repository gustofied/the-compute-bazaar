"""Provider-neutral GPU naming helpers."""

from __future__ import annotations

from collections.abc import Callable


def _has_vram(gpu_ram_mb: float | int | None, gib: int) -> bool:
    if gpu_ram_mb is None:
        return True
    return float(gpu_ram_mb) >= gib * 1024 * 0.9


GpuRule = tuple[Callable[[str], bool], int, str]


GPU_RULES: list[GpuRule] = [
    (lambda n: n == "A16", 16, "A16_16GB"),
    (lambda n: n == "A10", 24, "A10_24GB"),
    (lambda n: n == "A30", 24, "A30_24GB"),
    (lambda n: n == "A40", 48, "A40_48GB"),
    (lambda n: n == "A800 PCIE" or n.startswith("A800"), 80, "A800_80GB"),
    (lambda n: n == "L4", 24, "L4_24GB"),
    (lambda n: n == "L40", 48, "L40_48GB"),
    (lambda n: n == "L40S", 48, "L40S_48GB"),
    (lambda n: n == "GTX 1050", 2, "GTX1050_2GB"),
    (lambda n: n == "GTX 1050", 3, "GTX1050_3GB"),
    (lambda n: n == "GTX 1050 TI", 4, "GTX1050Ti_4GB"),
    (lambda n: n == "GTX 1060", 3, "GTX1060_3GB"),
    (lambda n: n == "GTX 1060", 6, "GTX1060_6GB"),
    (lambda n: n == "GTX 1070", 8, "GTX1070_8GB"),
    (lambda n: n == "GTX 1070 TI", 8, "GTX1070Ti_8GB"),
    (lambda n: n == "GTX 1080", 8, "GTX1080_8GB"),
    (lambda n: n == "GTX 1080 TI", 11, "GTX1080Ti_11GB"),
    (lambda n: n == "GTX 1650", 4, "GTX1650_4GB"),
    (lambda n: n == "GTX 1650 S", 4, "GTX1650S_4GB"),
    (lambda n: n == "GTX 1660", 6, "GTX1660_6GB"),
    (lambda n: n == "GTX 1660 S", 6, "GTX1660S_6GB"),
    (lambda n: n == "GTX 1660 TI", 6, "GTX1660Ti_6GB"),
    (lambda n: n == "GTX TITAN X", 12, "TitanX_12GB"),
    (lambda n: n == "Q RTX 4000" or n == "QUADRO RTX 4000", 8, "QuadroRTX4000_8GB"),
    (lambda n: n == "Q RTX 6000", 24, "QuadroRTX6000_24GB"),
    (lambda n: n == "Q RTX 8000", 48, "QuadroRTX8000_48GB"),
    (lambda n: n == "QUADRO P4000", 8, "QuadroP4000_8GB"),
    (lambda n: n == "RTX 2000ADA", 16, "RTX2000Ada_16GB"),
    (lambda n: n == "RTX 2060", 6, "RTX2060_6GB"),
    (lambda n: n == "RTX 2060S", 8, "RTX2060S_8GB"),
    (lambda n: n == "RTX 2070S", 8, "RTX2070S_8GB"),
    (lambda n: n == "RTX 2080 TI", 11, "RTX2080Ti_11GB"),
    (lambda n: n == "RTX 2080S", 8, "RTX2080S_8GB"),
    (lambda n: n == "RTX 3050", 8, "RTX3050_8GB"),
    (lambda n: n == "RTX 3060 LAPTOP", 6, "RTX3060Laptop_6GB"),
    (lambda n: n == "RTX 3060 TI", 8, "RTX3060Ti_8GB"),
    (lambda n: n == "RTX 3060", 12, "RTX3060_12GB"),
    (lambda n: n == "RTX 3070 TI", 8, "RTX3070Ti_8GB"),
    (lambda n: n == "RTX 3070", 8, "RTX3070_8GB"),
    (lambda n: n == "RTX 3080 TI", 12, "RTX3080Ti_12GB"),
    (lambda n: n == "RTX 3080", 10, "RTX3080_10GB"),
    (lambda n: n == "RTX 3090 TI", 24, "RTX3090Ti_24GB"),
    (lambda n: n == "RTX 3090", 24, "RTX3090_24GB"),
    (lambda n: n == "RTX 4060", 8, "RTX4060_8GB"),
    (lambda n: n == "RTX 4060 TI", 8, "RTX4060Ti_8GB"),
    (lambda n: n == "RTX 4060 TI", 16, "RTX4060Ti_16GB"),
    (lambda n: n == "RTX 4070 TI", 12, "RTX4070Ti_12GB"),
    (lambda n: n == "RTX 4070", 12, "RTX4070_12GB"),
    (lambda n: n == "RTX 4070S TI", 16, "RTX4070STi_16GB"),
    (lambda n: n == "RTX 4070S", 12, "RTX4070S_12GB"),
    (lambda n: n == "RTX 4080", 16, "RTX4080_16GB"),
    (lambda n: n == "RTX 4080S", 16, "RTX4080S_16GB"),
    (lambda n: n == "RTX 4090D", 24, "RTX4090D_24GB"),
    (lambda n: n == "RTX 4090", 24, "RTX4090_24GB"),
    (lambda n: n == "RTX 4000ADA", 20, "RTX4000Ada_20GB"),
    (lambda n: n == "RTX 5000ADA", 32, "RTX5000Ada_32GB"),
    (lambda n: n == "RTX 5060 LAPTOP", 8, "RTX5060Laptop_8GB"),
    (lambda n: n == "RTX 5060", 8, "RTX5060_8GB"),
    (lambda n: n == "RTX 5060 TI", 8, "RTX5060Ti_8GB"),
    (lambda n: n == "RTX 5060 TI", 16, "RTX5060Ti_16GB"),
    (lambda n: n == "RTX 5070 TI", 16, "RTX5070Ti_16GB"),
    (lambda n: n == "RTX 5070", 12, "RTX5070_12GB"),
    (lambda n: n == "RTX 5080", 16, "RTX5080_16GB"),
    (lambda n: n == "RTX 5090", 32, "RTX5090_32GB"),
    (lambda n: n == "RTX 5880ADA", 48, "RTX5880Ada_48GB"),
    (
        lambda n: n == "RTX 6000ADA" or n.startswith("RTX 6000 ADA"),
        48,
        "RTX6000Ada_48GB",
    ),
    (lambda n: n == "RTX A2000", 6, "A2000_6GB"),
    (lambda n: n == "RTX A2000", 12, "A2000_12GB"),
    (lambda n: n == "RTX A4000", 16, "A4000_16GB"),
    (lambda n: n == "RTX A4500", 20, "A4500_20GB"),
    (lambda n: n == "RTX A5000", 24, "A5000_24GB"),
    (lambda n: n == "RTX A6000", 48, "A6000_48GB"),
    (lambda n: n == "TESLA V100", 16, "V100_16GB"),
    (lambda n: n == "TESLA V100", 32, "V100_32GB"),
    (lambda n: n == "TESLA P100", 12, "P100_12GB"),
    (lambda n: n == "TESLA P100", 16, "P100_16GB"),
    (lambda n: n == "TESLA P40", 24, "P40_24GB"),
    (lambda n: n == "TESLA P4", 8, "P4_8GB"),
    (lambda n: n == "TESLA T4", 16, "T4_16GB"),
    (lambda n: n == "TITAN RTX", 24, "TitanRTX_24GB"),
    (lambda n: n == "TITAN V", 12, "TitanV_12GB"),
    (lambda n: n == "TITAN XP", 12, "TitanXp_12GB"),
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


def canonical_gpu_model(
    gpu_name: str, gpu_ram_mb: float | int | None = None
) -> str | None:
    normalized = _normalize_gpu_name(gpu_name)
    matches = [
        canonical
        for predicate, vram_gb, canonical in GPU_RULES
        if predicate(normalized) and _has_vram(gpu_ram_mb, vram_gb)
    ]
    if not matches:
        return None
    return matches[-1]


def _normalize_gpu_name(gpu_name: str) -> str:
    normalized = " ".join(
        gpu_name.replace("_", " ")
        .replace("-", " ")
        .upper()
        .replace("NVIDIA", "")
        .replace("GEFORCE", "")
        .split()
    )
    aliases = {
        "A2000": "RTX A2000",
        "A4000": "RTX A4000",
        "A4500": "RTX A4500",
        "A5000": "RTX A5000",
        "A6000": "RTX A6000",
        "RTX4000ADA": "RTX 4000ADA",
        "RTX4090": "RTX 4090",
        "RTX5000ADA": "RTX 5000ADA",
        "RTX6000ADA": "RTX 6000ADA",
        "RTXPRO4000": "RTX PRO 4000",
        "RTXPRO4500": "RTX PRO 4500",
        "RTXPRO5000": "RTX PRO 5000",
        "RTXPRO6000": "RTX PRO 6000",
        "V100": "TESLA V100",
        "V100 32G": "TESLA V100",
    }
    return aliases.get(normalized, normalized)
