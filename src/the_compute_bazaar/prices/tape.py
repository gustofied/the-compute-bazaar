"""Generate local GPU price tape observations for the draft article.

The CSV is intentionally long-form: one row is one observed point on one line.
That makes it easy to build indexes, spreads, and later joins against papers or
market quotes without reverse-engineering browser state.

Rows can describe different evidence shapes. Some sources give one price point,
some sources give a short historical line, and later we can emit computed traces
or baskets from many raw observations.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


GPU_FAMILIES = ["H100", "H200", "B200", "B300", "A100", "L40S"]

SOURCE_ARCHETYPES = [
    {
        "name": "Compute exchange indicative floor",
        "evidence_type": "contract",
        "unit": "usd/gpu-hour",
        "note": "Indicative capacity contract line. Replace with actual traded or quoted term sheet when available.",
        "confidence": "watchlist",
        "bias": -0.04,
    },
    {
        "name": "Provider on-demand page",
        "evidence_type": "provider",
        "unit": "usd/gpu-hour",
        "note": "Published provider page. Good for current price, weaker for realized clearing price.",
        "confidence": "direct",
        "bias": 0.16,
    },
    {
        "name": "Marketplace observed ask",
        "evidence_type": "marketplace",
        "unit": "usd/gpu-hour",
        "note": "Observed public ask. Useful for floors, but availability and reliability must be checked.",
        "confidence": "direct",
        "bias": -0.18,
    },
    {
        "name": "Internet Archive provider page",
        "evidence_type": "archive",
        "unit": "usd/gpu-hour",
        "note": "Historical provider page from an archive snapshot. Date quality matters.",
        "confidence": "direct",
        "bias": 0.08,
    },
    {
        "name": "Training paper derived run",
        "evidence_type": "paper",
        "unit": "derived usd/gpu-hour",
        "note": "Paper gives accelerator type and GPU-hours; price is matched from contemporaneous curve.",
        "confidence": "derived",
        "bias": 0.02,
    },
    {
        "name": "Inference API implied capacity",
        "evidence_type": "inference",
        "unit": "implied usd/gpu-hour",
        "note": "Token price converted through throughput/utilization assumptions. Treat as a model, not a quote.",
        "confidence": "modelled",
        "bias": 0.34,
    },
    {
        "name": "Neocloud filing capex line",
        "evidence_type": "filing",
        "unit": "amortized usd/gpu-hour",
        "note": "Quarterly capex or depreciation mapped into GPU-hour economics.",
        "confidence": "modelled",
        "bias": -0.06,
    },
    {
        "name": "Operator social post",
        "evidence_type": "social",
        "unit": "usd/gpu-hour",
        "note": "Public claim from an operator, founder, or buyer. Useful lead; verify before benchmark use.",
        "confidence": "lead",
        "bias": -0.1,
    },
    {
        "name": "Sandbox credit conversion",
        "evidence_type": "provider",
        "unit": "effective usd/gpu-hour",
        "note": "VPS, notebook, or sandbox credit price converted into an effective accelerator-hour.",
        "confidence": "derived",
        "bias": 0.24,
    },
    {
        "name": "Reserved cluster indication",
        "evidence_type": "contract",
        "unit": "usd/gpu-hour",
        "note": "Reserved term indication. Needs term length, region, and minimum commitment.",
        "confidence": "watchlist",
        "bias": -0.28,
    },
]

GPU_BASES = {
    "H100": {"start": 4.65, "end": 2.1, "volatility": 0.2},
    "H200": {"start": 6.1, "end": 2.75, "volatility": 0.22},
    "B200": {"start": 8.8, "end": 4.15, "volatility": 0.28},
    "B300": {"start": 11.5, "end": 5.4, "volatility": 0.34},
    "A100": {"start": 2.55, "end": 0.92, "volatility": 0.16},
    "L40S": {"start": 1.42, "end": 0.62, "volatility": 0.12},
}

COLORS = [
    "#1b5e20",
    "#0f766e",
    "#235789",
    "#5f4bb6",
    "#8f2d56",
    "#b35c00",
    "#7a6f2b",
    "#3b6f8f",
    "#426b1f",
    "#9b3d12",
    "#226f54",
    "#6c4f7d",
]

FIELDNAMES = [
    "line_order",
    "point_order",
    "line_id",
    "line_label",
    "line_kind",
    "evidence_shape",
    "gpu",
    "evidence_type",
    "unit",
    "confidence",
    "source",
    "source_url",
    "source_claim",
    "normalization_note",
    "note",
    "color",
    "date",
    "price_usd_gpu_hour",
    "observed",
]

RAW_FIELDNAMES = [
    "include",
    "observation_id",
    "trace_id",
    "trace_label",
    "line_kind",
    "evidence_shape",
    "gpu",
    "evidence_type",
    "source_title",
    "source_url",
    "source_date",
    "observed_date",
    "raw_claim",
    "raw_value",
    "raw_unit",
    "normalized_usd_per_gpu_hour",
    "normalized_unit",
    "confidence",
    "normalization_note",
    "notes",
    "color",
]

RAW_EXAMPLE_ROWS = [
    {
        "include": "false",
        "observation_id": "example-paper-h100-2024-01",
        "trace_id": "example-h100-paper-fragment",
        "trace_label": "H100 paper-derived example",
        "line_kind": "research",
        "evidence_shape": "point",
        "gpu": "H100",
        "evidence_type": "paper",
        "source_title": "Example paper title",
        "source_url": "https://example.com/paper",
        "source_date": "2024-01",
        "observed_date": "2024-01",
        "raw_claim": "Example: 64 H100s for 10 days cost $30,720.",
        "raw_value": "30720",
        "raw_unit": "usd total run cost",
        "normalized_usd_per_gpu_hour": "2.000",
        "normalized_unit": "usd/gpu-hour",
        "confidence": "derived",
        "normalization_note": "30720 / (64 GPUs * 10 days * 24 hours).",
        "notes": "Disabled example row. Change include to true only for real evidence.",
        "color": "",
    },
    {
        "include": "false",
        "observation_id": "example-provider-h100-2024-06",
        "trace_id": "example-h100-provider-page",
        "trace_label": "H100 provider page example",
        "line_kind": "research",
        "evidence_shape": "source_line",
        "gpu": "H100",
        "evidence_type": "provider",
        "source_title": "Example provider pricing page",
        "source_url": "https://example.com/pricing",
        "source_date": "2024-06",
        "observed_date": "2024-06",
        "raw_claim": "Example: H100 listed at $3.20/hr.",
        "raw_value": "3.20",
        "raw_unit": "usd/gpu-hour",
        "normalized_usd_per_gpu_hour": "3.200",
        "normalized_unit": "usd/gpu-hour",
        "confidence": "direct",
        "normalization_note": "Already listed per GPU-hour.",
        "notes": "Disabled example row. Duplicate trace_id across dates to make a short line.",
        "color": "",
    },
]

DEFAULT_DATA_PATH = Path("data/gpu-price-tape/gpu_price_tape.csv")
DEFAULT_RAW_PATH = Path("data/gpu-price-tape/raw_observations.csv")
DEFAULT_SITE_PATH = Path("external/AdamSioud/exemplars/compute/gpu-price-tape.csv")


@dataclass(frozen=True)
class TapePoint:
    date: str
    price: float
    observed: bool = True


@dataclass(frozen=True)
class TapeLine:
    line_id: str
    label: str
    line_kind: str
    evidence_shape: str
    gpu: str
    evidence_type: str
    unit: str
    confidence: str
    source: str
    note: str
    color: str
    points: tuple[TapePoint, ...]
    source_url: str = ""
    source_claim: str = ""
    normalization_note: str = ""


def seeded_noise(seed: int, step: int) -> float:
    value = math.sin(seed * 17.17 + step * 2.417) * 10000
    return value - math.floor(value)


def month_label(index: int) -> str:
    year = 2023 + index // 12
    month = index % 12 + 1
    return f"{year:04d}-{month:02d}"


def comparison_lines() -> list[TapeLine]:
    return [
        TapeLine(
            line_id="comparison-ornn-ocpi-h100",
            label="H100 Ornn OCPI public sample",
            line_kind="comparison",
            evidence_shape="point",
            gpu="H100",
            evidence_type="benchmark",
            unit="usd/gpu-hour",
            confidence="benchmark",
            source="Ornn",
            source_url="https://ornn.com/",
            color="#111111",
            points=(TapePoint("2026-06", 1.9),),
            note=(
                "Comparison row. Ornn's public page shows OCPI-H100 SXM sample values "
                "($1.90, $1.85, $1.80) and describes OCPI as live traded spot pricing."
            ),
            source_claim="Public OCPI-H100 SXM sample values on Ornn.",
            normalization_note="Already quoted as USD per GPU-hour style market value.",
        ),
        TapeLine(
            line_id="comparison-silicon-data-neo-h100",
            label="H100 Silicon Data Neo Cloud index",
            line_kind="comparison",
            evidence_shape="source_line",
            gpu="H100",
            evidence_type="benchmark",
            unit="usd/gpu-hour",
            confidence="reported-index",
            source="Silicon Data via Business Insider",
            source_url="https://www.businessinsider.com/ai-demand-boosts-gpu-prices-silicon-data-ceo-carmen-li-2026-4",
            color="#c0392b",
            points=(TapePoint("2026-01", 2.2), TapePoint("2026-04", 2.64)),
            note=(
                "Comparison row. Business Insider reported Silicon Data's Neo Cloud H100 index "
                "rose from $2.20 to $2.64 over the prior three months."
            ),
            source_claim="Reported index moved from $2.20 to $2.64 across the prior three months.",
            normalization_note="Stored as a reported source line in USD per GPU-hour.",
        ),
        TapeLine(
            line_id="comparison-silicon-data-neo-b200",
            label="B200 Silicon Data Neo Cloud index",
            line_kind="comparison",
            evidence_shape="source_line",
            gpu="B200",
            evidence_type="benchmark",
            unit="usd/gpu-hour",
            confidence="reported-index",
            source="Silicon Data via Business Insider",
            source_url="https://www.businessinsider.com/ai-demand-boosts-gpu-prices-silicon-data-ceo-carmen-li-2026-4",
            color="#8e44ad",
            points=(TapePoint("2026-01", 4.4), TapePoint("2026-04", 5.35)),
            note=(
                "Comparison row. Business Insider reported Silicon Data's Neo Cloud B200 index "
                "rose from $4.40 to $5.35 over the prior three months."
            ),
            source_claim="Reported index moved from $4.40 to $5.35 across the prior three months.",
            normalization_note="Stored as a reported source line in USD per GPU-hour.",
        ),
        TapeLine(
            line_id="comparison-silicon-data-hyperscaler-h100",
            label="H100 Silicon Data hyperscaler index",
            line_kind="comparison",
            evidence_shape="source_line",
            gpu="H100",
            evidence_type="benchmark",
            unit="usd/gpu-hour",
            confidence="reported-index",
            source="Silicon Data via Business Insider",
            source_url="https://www.businessinsider.com/ai-demand-boosts-gpu-prices-silicon-data-ceo-carmen-li-2026-4",
            color="#34495e",
            points=(TapePoint("2026-01", 7.26), TapePoint("2026-04", 7.46)),
            note=(
                "Comparison row. Business Insider reported Silicon Data's Hyperscaler H100 index "
                "rose from $7.26 to $7.46 over the prior three months."
            ),
            source_claim="Reported index moved from $7.26 to $7.46 across the prior three months.",
            normalization_note="Stored as a reported source line in USD per GPU-hour.",
        ),
    ]


def mock_lines(limit: int = 100) -> list[TapeLine]:
    series: list[TapeLine] = []
    line_index = 0
    variant = 0
    while len(series) < limit:
        gpu = GPU_FAMILIES[variant % len(GPU_FAMILIES)]
        gpu_config = GPU_BASES[gpu]
        variant_round = variant // len(GPU_FAMILIES)
        for lane, _ in enumerate(SOURCE_ARCHETYPES):
            if len(series) >= limit:
                break
            source = SOURCE_ARCHETYPES[(lane + variant_round) % len(SOURCE_ARCHETYPES)]
            lane_seed = line_index + 3
            phase = seeded_noise(lane_seed, 0) * 1.7
            points: list[TapePoint] = []
            for step in range(42):
                t = step / 41
                trend = gpu_config["start"] * (1 - t) + gpu_config["end"] * t
                seasonal = math.sin(step / 4.8 + phase) * gpu_config["volatility"]
                shock = (
                    0.36 * (1 - abs(step - 17) / 5)
                    if 14 < step < 21 and gpu in {"H100", "H200"}
                    else 0
                )
                sparse = source["evidence_type"] in {"paper", "filing"}
                observed = not sparse or step % (7 if source["evidence_type"] == "paper" else 9) == lane % 5
                noise = (seeded_noise(lane_seed, step) - 0.5) * gpu_config["volatility"]
                price = max(0.18, trend * (1 + source["bias"]) + seasonal + shock + noise)
                if observed:
                    points.append(TapePoint(month_label(step), round(price, 3), True))

            series.append(
                TapeLine(
                    line_id=f"tape-{line_index + 1:03d}",
                    label=f"{gpu} {source['name']} {variant_round + 1}.{lane + 1}",
                    line_kind="mock",
                    evidence_shape="computed_trace",
                    gpu=gpu,
                    evidence_type=str(source["evidence_type"]),
                    unit=str(source["unit"]),
                    confidence=str(source["confidence"]),
                    source=str(source["name"]),
                    note=str(source["note"]),
                    color=COLORS[line_index % len(COLORS)],
                    points=tuple(points),
                    source_claim="Synthetic placeholder generated from a source archetype.",
                    normalization_note="Mock normalized USD per GPU-hour curve for layout and workflow testing.",
                )
            )
            line_index += 1
        variant += 1
    return series


def ensure_raw_template(path: Path) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDNAMES)
        writer.writeheader()
        writer.writerows(RAW_EXAMPLE_ROWS)
    return True


def included(value: str | None) -> bool:
    return str(value or "true").strip().lower() not in {"0", "false", "no", "n", "skip"}


def read_raw_observation_lines(path: Path) -> list[TapeLine]:
    if not path.exists():
        return []

    grouped: dict[str, dict[str, object]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not included(row.get("include")):
                continue

            observation_id = (row.get("observation_id") or "").strip()
            date = (row.get("observed_date") or row.get("source_date") or "").strip()
            price_text = (row.get("normalized_usd_per_gpu_hour") or "").strip()
            gpu = (row.get("gpu") or "").strip()
            if not observation_id or not date or not price_text or not gpu:
                continue

            try:
                price = float(price_text)
            except ValueError:
                continue

            trace_id = (row.get("trace_id") or observation_id).strip()
            if trace_id not in grouped:
                color = (row.get("color") or "").strip() or COLORS[(len(grouped) + 4) % len(COLORS)]
                grouped[trace_id] = {
                    "trace_id": trace_id,
                    "label": (row.get("trace_label") or row.get("source_title") or observation_id).strip(),
                    "line_kind": (row.get("line_kind") or "research").strip(),
                    "evidence_shape": (row.get("evidence_shape") or "").strip(),
                    "gpu": gpu,
                    "evidence_type": (row.get("evidence_type") or "research").strip(),
                    "unit": (row.get("normalized_unit") or "usd/gpu-hour").strip(),
                    "confidence": (row.get("confidence") or "unreviewed").strip(),
                    "source": (row.get("source_title") or observation_id).strip(),
                    "source_url": (row.get("source_url") or "").strip(),
                    "source_claim": (row.get("raw_claim") or "").strip(),
                    "normalization_note": (row.get("normalization_note") or "").strip(),
                    "note": (row.get("notes") or row.get("raw_claim") or "").strip(),
                    "color": color,
                    "points": [],
                }

            grouped[trace_id]["points"].append(TapePoint(date=date, price=round(price, 3), observed=True))  # type: ignore[index, union-attr]

    lines: list[TapeLine] = []
    for data in grouped.values():
        points = tuple(sorted(data["points"], key=lambda point: point.date))  # type: ignore[arg-type]
        evidence_shape = str(data["evidence_shape"] or ("point" if len(points) == 1 else "source_line"))
        lines.append(
            TapeLine(
                line_id=str(data["trace_id"]),
                label=str(data["label"]),
                line_kind=str(data["line_kind"]),
                evidence_shape=evidence_shape,
                gpu=str(data["gpu"]),
                evidence_type=str(data["evidence_type"]),
                unit=str(data["unit"]),
                confidence=str(data["confidence"]),
                source=str(data["source"]),
                source_url=str(data["source_url"]),
                source_claim=str(data["source_claim"]),
                normalization_note=str(data["normalization_note"]),
                note=str(data["note"]),
                color=str(data["color"]),
                points=points,
            )
        )
    return lines


def tape_lines(mock_count: int = 100, raw_lines: Iterable[TapeLine] = ()) -> list[TapeLine]:
    return [*comparison_lines(), *raw_lines, *mock_lines(mock_count)]


def rows(lines: Iterable[TapeLine]) -> Iterable[dict[str, str | int | float]]:
    for line_order, line in enumerate(lines):
        for point_order, point in enumerate(line.points):
            yield {
                "line_order": line_order,
                "point_order": point_order,
                "line_id": line.line_id,
                "line_label": line.label,
                "line_kind": line.line_kind,
                "evidence_shape": line.evidence_shape,
                "gpu": line.gpu,
                "evidence_type": line.evidence_type,
                "unit": line.unit,
                "confidence": line.confidence,
                "source": line.source,
                "source_url": line.source_url,
                "source_claim": line.source_claim,
                "normalization_note": line.normalization_note,
                "note": line.note,
                "color": line.color,
                "date": point.date,
                "price_usd_gpu_hour": f"{point.price:.3f}",
                "observed": "true" if point.observed else "false",
            }


def write_csv(path: Path, lines: list[TapeLine]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows(lines):
            writer.writerow(row)
            row_count += 1
    return row_count


def main() -> None:
    parser = argparse.ArgumentParser(prog="gpu-price-tape")
    parser.add_argument("--mock-lines", type=int, default=100)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument(
        "--site-out",
        type=Path,
        default=DEFAULT_SITE_PATH,
        help="Static copy for the local article page.",
    )
    parser.add_argument("--no-raw", action="store_true", help="Ignore raw observations and emit only comparisons/mocks.")
    parser.add_argument("--init-raw-only", action="store_true", help="Create the raw observations template and exit.")
    parser.add_argument("--no-site-copy", action="store_true", help="Only write the analysis CSV.")
    args = parser.parse_args()

    if args.mock_lines < 0:
        parser.error("--mock-lines must be zero or greater")

    created_raw = ensure_raw_template(args.raw)
    if created_raw:
        print(f"created raw observations template at {args.raw}")
    if args.init_raw_only:
        return

    raw_lines = [] if args.no_raw else read_raw_observation_lines(args.raw)
    lines = tape_lines(args.mock_lines, raw_lines)
    row_count = write_csv(args.out, lines)
    print(f"wrote {row_count} observations across {len(lines)} lines to {args.out}")
    if raw_lines:
        print(f"included {len(raw_lines)} research traces from {args.raw}")

    if not args.no_site_copy:
        site_row_count = write_csv(args.site_out, lines)
        print(f"wrote {site_row_count} observations across {len(lines)} lines to {args.site_out}")


if __name__ == "__main__":
    main()
